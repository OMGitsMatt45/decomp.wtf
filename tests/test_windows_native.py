"""Opt-in native Windows integration: real compilers and the bundled, freely shared demo.

CI installs the pinned free toolchains before setting DECOMP_TEST_NATIVE_WINDOWS=1.
Missing tools fail these tests; Windows never falls back to WSL to pass them.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from importlib import resources
from io import BytesIO
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import compiler, elfobj, hostenv, project, toolchains, wsl
from decompnet.app.engine import RomNetwork
from decompnet.forks import objdiff

from .fixtures.generate_native_compiler_parity import describe_functions

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FREE_TOOLS = ("gcc-2.7.2-kmc", "gcc-2.7.2-psx", "agbcc", "arm-gnu", "objdiff-cli", "dtk", "binutils-mips", "gc-wii-binutils")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("DECOMP_TEST_NATIVE_WINDOWS") != "1",
    reason="opt-in native Windows integration (DECOMP_TEST_NATIVE_WINDOWS=1)",
)


@pytest.fixture
def native_workspace(tmp_path, monkeypatch):
    work = tmp_path / "Native Windows workspace with spaces"
    work.mkdir()
    temporary = work / "Compiler temporary files"
    temporary.mkdir()
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(temporary))
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    monkeypatch.setenv("DECOMP_RUNTIME", "native")
    monkeypatch.delenv("DECOMP_WSL", raising=False)
    hostenv.runtime.cache_clear()

    sentinel = work / "No WSL available"
    sentinel.mkdir()
    (sentinel / "wsl.exe").write_bytes(b"MZ: WSL must not be executed by native Windows tests")
    monkeypatch.setenv("PATH", str(sentinel) + os.pathsep + os.environ.get("PATH", ""))
    start = subprocess.Popen

    def native_only(args, *positional, **kwargs):
        first = args.split()[0].strip('"') if isinstance(args, str) else str(args[0])
        assert Path(first).name.lower() not in ("wsl", "wsl.exe"), "Native Windows attempted to start WSL"
        return start(args, *positional, **kwargs)

    def no_wsl(*args, **kwargs):
        pytest.fail("Native Windows attempted to use the WSL bridge")

    monkeypatch.setattr(subprocess, "Popen", native_only)
    monkeypatch.setattr(wsl, "status", no_wsl)
    monkeypatch.setattr(wsl, "run", no_wsl)
    for tid in FREE_TOOLS:
        installed = toolchains.installed(tid)
        assert installed is not None, f"Required native toolchain {tid} was not installed"
        assert not installed.get("wsl"), f"{tid} must use a Windows build"
        assert not toolchains.get(tid).via_wsl
    yield work
    hostenv.runtime.cache_clear()


def native_compile(source, work):
    config = project.compiler_config(work, {"compiler": {"toolchain": "gcc-2.7.2-kmc"}})
    assert not config.wsl
    result = compiler.compile_source(config, "", source)
    assert result.ok, result.log
    assert result.obj.startswith(b"\x7fELF")
    return result.obj


def test_native_compiler_payloads_are_windows_executables(native_workspace):
    payloads = [("gcc-2.7.2-kmc", name) for name in ("gcc.exe", "cpp.exe", "cc1.exe", "as.exe")]
    payloads.append(("agbcc", "bin/agbcc.exe"))
    for tid, name in payloads:
        executable = toolchains.require(tid) / name
        with executable.open("rb") as stream:
            assert stream.read(2) == b"MZ", f"{executable} is not a Windows executable"


def test_native_kmc_matches_linux_machine_code_and_relocations(native_workspace):
    source = FIXTURES / "native_compiler_parity.c"
    expected = json.loads((FIXTURES / "native_compiler_parity.json").read_text(encoding="utf-8"))
    # read_text normalizes a Git for Windows checkout's CRLF, just as compile_source does.
    assert hashlib.sha256(source.read_text(encoding="utf-8").encode("utf-8")).hexdigest() == expected["source_sha256"]
    assert toolchains.get(expected["toolchain"]).flags == expected["flags"]
    actual = native_compile(source.read_text(encoding="utf-8"), native_workspace)
    assert describe_functions(actual) == expected["functions"]


def test_cpp_kmc_binutils_preserve_real_n64_objects(native_workspace):
    """Exercise the C++ archive/conversion/strip/demangler implementations too."""
    directory = toolchains.require("gcc-2.7.2-kmc")
    inventory = json.loads((directory / "CPP-BUILD.json").read_text())
    assert len(inventory["translation_units"]) >= 160
    assert {unit["language"] for unit in inventory["translation_units"]} == {"GNU C++98"}
    data = native_compile("int native_archive_probe(int value) { return value * 3; }", native_workspace)
    obj = native_workspace / "Archive probe.o"
    obj.write_bytes(data)
    elf = ELFFile(BytesIO(data))
    text = elf.get_section_by_name(".text").data()

    def run(program, *args):
        result = subprocess.run([str(directory / program), *map(str, args)], cwd=native_workspace,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    archive = native_workspace / "Probe archive.a"
    run("ar.exe", "rc", archive, obj)
    assert "Archive probe.o" in run("ar.exe", "t", archive)
    raw = native_workspace / "Raw code.bin"
    # Binutils 2.6 predates --only-section/-j. Remove other allocated sections
    # using its original CLI rather than requiring a modern option.
    remove = [argument for section in elf.iter_sections()
              if section.name != ".text" and section["sh_flags"] & 2
              for argument in ("-R", section.name)]
    run("objcopy.exe", "-O", "binary", *remove, obj, raw)
    assert raw.read_bytes() == text
    stripped = native_workspace / "Stripped probe.o"
    stripped.write_bytes(data)
    run("strip.exe", "-s", stripped)
    assert ELFFile(BytesIO(stripped.read_bytes())).get_section_by_name(".text").data() == text
    assert "foo(int)" in run("c++filt.exe", "foo__Fi")


def test_native_psx_preprocessor_and_compiler_produce_little_endian_mips(native_workspace):
    config = project.compiler_config(native_workspace, {"compiler": {"toolchain": "gcc-2.7.2-psx"}})
    header = "#ifndef NATIVE_PSX_CONTEXT\n#define NATIVE_PSX_CONTEXT\n#if 2 + 2 == 4\ntypedef int s32;\n#else\n#error preprocessor failed\n#endif\n#endif\n"
    result = compiler.compile_source(config, header,
                                     "s32 native_psx_abs(s32 v) { return v < 0 ? -v : v; }")
    assert result.ok, result.log
    function = elfobj.extract_function(result.obj, "native_psx_abs")
    assert function.arch == "mips" and not function.big_endian
    assert function.code


@pytest.mark.parametrize("tid", ["gcc-2.7.2-kmc", "gcc-2.7.2-psx"])
def test_native_gcc_driver_reports_preprocessor_failure(native_workspace, tid):
    config = project.compiler_config(native_workspace, {"compiler": {"toolchain": tid}})
    source = native_workspace / "Invalid source.c"
    source.write_text("#error intentional native compiler failure\n", encoding="ascii", newline="\n")
    output = native_workspace / "Invalid source.o"
    values = {"{src}": source.as_posix(), "{obj}": output.as_posix(), "{include}": native_workspace.as_posix()}
    command = []
    for argument in config.cmd:
        for key, value in values.items():
            argument = argument.replace(key, value)
        command.append(argument)
    result = compiler.run_in(config, native_workspace, command, timeout=30)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not output.exists()
    assert "intentional native compiler failure" in result.stdout + result.stderr


def test_native_demo_import_rejects_wrong_code_and_accepts_exact_match(native_workspace):
    demo = resources.files("decompnet.app").joinpath("static/demo/demo-quest-64.z64").read_bytes()
    game = native_workspace / "My demo game.z64"
    game.write_bytes(demo)
    network = RomNetwork(native_workspace / "decomp.db", native_workspace)
    slug = network.import_rom(game, confirmed=True, log=lambda *_: None)
    overview = network.overview(slug)
    assert slug == "demo-quest-64" and overview["functions"] >= 95
    assert overview["compiler"]["toolchain"] == "gcc-2.7.2-kmc"
    assert overview["compiler"]["installed"] and not overview["compiler"]["wsl"]
    agent, _ = network.local_agent("native-windows-smoke")
    wrong = network.attempt(agent, "func_800007F4", "s32 func_800007F4(s32 value) { return value; }", slug)
    assert not wrong["matched"] and wrong["score"] is not None and wrong["score"] > 0, wrong["text"]
    exact = network.attempt(agent, "func_800007F4", "s32 func_800007F4(s32 value) { return value < 0 ? -value : value; }", slug)
    assert exact["matched"] and exact["score"] == 0, exact["text"]
    difference = network.function_diff(slug, "func_800007F4")
    assert difference["score"] == 0 and all(row[0] == " " for row in difference["rows"])
    exported = network.export_rom(slug, log=lambda *_: None)
    assert exported["identical"], exported["log"]


def test_native_objdiff_judges_real_kmc_objects(native_workspace):
    source = "int native_abs(int value) { return value < 0 ? -value : value; }"
    target = native_workspace / "Expected object.o"
    target.write_bytes(native_compile(source, native_workspace))
    candidate = native_workspace / "Candidate object.o"
    candidate.write_bytes(native_compile("int native_abs(int value) { return value; }", native_workspace))
    wrong = objdiff.diff(target, candidate, "native_abs", native_workspace)
    assert not wrong.matched and any(row[0] != " " for row in wrong.rows)
    candidate.write_bytes(native_compile(source, native_workspace))
    assert objdiff.diff(target, candidate, "native_abs", native_workspace).matched


def test_native_agbcc_pipeline_produces_thumb_code(native_workspace):
    config = project.compiler_config(native_workspace, {"compiler": {"toolchain": "agbcc"}})
    assert not config.wsl and config.cmd[0] == sys.executable
    assert not any("/bin/sh" in argument for argument in config.cmd)
    source = """extern int native_total;
int native_gba_sum(const int *values, int count) {
    int i, total = native_total;
    for (i = 0; i < count; i++) total += values[i] * 3;
    return total;
}
"""
    result = compiler.compile_source(config, "", source)
    assert result.ok, result.log
    elf = ELFFile(BytesIO(result.obj))
    assert elf["e_machine"] == "EM_ARM" and elf.little_endian
    symbols = list(elf.get_section_by_name(".symtab").iter_symbols())
    function = next(symbol for symbol in symbols if symbol.name == "native_gba_sum")
    assert function["st_info"]["type"] == "STT_FUNC" and function["st_size"] > 0
    assert function["st_value"] & 1, "The GBA compiler must produce Thumb code"
    assert any(symbol.name == "native_total" and symbol["st_shndx"] == "SHN_UNDEF" for symbol in symbols)


@pytest.mark.parametrize("tid", ["objdiff-cli", "dtk", "binutils-mips", "arm-gnu"])
def test_free_native_tools_start(native_workspace, tid):
    executable = toolchains.binary(tid)
    assert executable.suffix.lower() == ".exe"
    assert executable.read_bytes().startswith(b"MZ")
    result = subprocess.run([str(executable), "--version"], cwd=native_workspace,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("tid,name,source,args,arch", [
    ("binutils-mips", "mips-ps2-decompals-as.exe", ".text\n.set noreorder\n.globl native_probe\n.ent native_probe\nnative_probe:\n jr $ra\n nop\n.end native_probe\n", ["-EB", "-march=vr4300", "-mabi=32"], "mips"),
    ("gc-wii-binutils", "powerpc-eabi-as.exe", ".text\n.globl native_probe\n.type native_probe,@function\nnative_probe:\n blr\n.size native_probe,.-native_probe\n", ["-mppc"], "ppc"),
])
def test_free_native_assemblers_produce_console_objects(native_workspace, tid, name, source, args, arch):
    candidates = list(toolchains.require(tid).rglob(name))
    assert len(candidates) == 1, f"Expected one {name} in {toolchains.require(tid)}"
    assembly = native_workspace / "Console source.s"
    assembly.write_text(source, encoding="ascii", newline="\n")
    output = native_workspace / "Console object.o"
    result = subprocess.run([str(candidates[0]), *args, "-o", str(output), str(assembly)], cwd=native_workspace,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    function = elfobj.extract_function(output.read_bytes(), "native_probe")
    assert function.arch == arch and function.big_endian
