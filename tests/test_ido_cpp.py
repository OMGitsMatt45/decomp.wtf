"""Actual IDO C++ compilation and C-origin ROM rebuilding on Windows and Linux.

Run after explicitly installing the proprietary IDO packages:
DECOMP_TEST_IDO_CPP=1 python -m pytest tests/test_ido_cpp.py
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import compiler, elfobj, project, seeds, toolchains, wsl
from decompnet.app.engine import RomNetwork
from .fixtures.generate_native_compiler_parity import describe_functions

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_IDO_CPP") != "1", reason="requires the pinned IDO packages")
FIXTURES = Path(__file__).parent / "fixtures"
GIT = shutil.which("git")  # capture before native_only removes non-system PATH entries
HEADER = """extern int ido_total;
int ido_add(int value);
int ido_call(int value);
int ido_global(void);
int ido_clamp(int value);
"""
C_FUNCTIONS = {
    "ido_call": "int ido_call(int value) { return ido_add(value); }",
    "ido_add": "int ido_add(int value) { return value + 1; }",
    "ido_global": "int ido_global(void) { return ido_total; }",
    "ido_clamp": "int ido_clamp(int value) { if (value < 0) return 0; if (value > 31) return 31; return value; }",
}
CPP_ADD = """#ifndef __cplusplus
#error This translation unit must be compiled as C++
#endif
template<class T> class Counter { public: T value; };
int ido_add(int value) {
    Counter<int> counter;
    int &reference = counter.value;
    reference = value + 1;
    return counter.value;
}
"""


@pytest.fixture(autouse=True)
def native_only(monkeypatch):
    monkeypatch.setenv("DECOMP_RUNTIME", "native")
    if sys.platform == "win32":
        # A regular Windows installation has no MSYS on PATH. Dependencies must
        # be bundled with the compiler, including for its child processes.
        monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32"))
    def no_wsl(*args, **kwargs):
        pytest.fail("IDO must run natively without WSL")
    monkeypatch.setattr(wsl, "status", no_wsl)
    monkeypatch.setattr(wsl, "run", no_wsl)
    start = subprocess.Popen
    def native_process(args, *positional, **kwargs):
        first = args.split()[0].strip('"') if isinstance(args, str) else str(args[0])
        assert Path(first).name.lower() not in ("wsl", "wsl.exe")
        return start(args, *positional, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", native_process)


def config(root, language=None, toolchain="ido-7.1", frontend="edg"):
    assert toolchains.installed(toolchain) is not None
    values = {"toolchain": toolchain, "sandbox": "none", "cpp_frontend": frontend}
    if language is not None:
        values["language"] = language
    cfg = project.compiler_config(root, {"kind": "rom", "platform": "n64", "compiler": values})
    assert not cfg.wsl
    return cfg


@pytest.mark.parametrize("toolchain", ["ido-5.3", "ido-7.1"])
def test_templates_classes_and_references_match_the_original_c_target(tmp_path, toolchain):
    cfg = config(tmp_path, toolchain=toolchain)
    assert cfg.language == "c++" and Path(cfg.cmd[0]).stem == "NCC"
    cpp = compiler.compile_source(cfg, HEADER, CPP_ADD)
    original = compiler.compile_source(config(tmp_path, "c", toolchain), HEADER, C_FUNCTIONS["ido_add"])
    assert cpp.ok, cpp.log
    assert original.ok, original.log
    actual = elfobj.extract_function(cpp.obj, "ido_add")
    target = elfobj.extract_function(original.obj, "ido_add")
    assert actual.arch == "mips" and actual.big_endian
    assert actual.code == target.code and actual.relocs == target.relocs == []
    assert ELFFile(BytesIO(cpp.obj))["e_machine"] == "EM_MIPS"
    assert elfobj.list_functions(cpp.obj) == ["ido_add"]


@pytest.mark.parametrize("toolchain", ["ido-5.3", "ido-7.1"])
def test_matches_pinned_cpp_code_and_relocation_reference(tmp_path, toolchain):
    source = (FIXTURES / "native_compiler_parity.c").read_text(encoding="utf-8")
    expected = json.loads((FIXTURES / f"ido{toolchain[4:].replace('.', '')}_cpp_compiler_parity.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(source.encode()).hexdigest() == expected["source_sha256"]
    assert toolchains.get(toolchain).flags == expected["flags"]
    result = compiler.compile_source(config(tmp_path, toolchain=toolchain), "", source)
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]


def test_ido53_retains_its_explicit_c_compiler(tmp_path):
    cfg = config(tmp_path, "c", "ido-5.3")
    assert cfg.language == "c" and Path(cfg.cmd[0]).stem == "cc"
    result = compiler.compile_source(cfg, "", C_FUNCTIONS["ido_add"])
    assert result.ok, result.log
    assert elfobj.extract_function(result.obj, "ido_add").code


def test_ido53_never_substitutes_edg_for_a_missing_classic_cfront(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchains, "runtime_dirs", lambda _: [tmp_path / "missing-overlay"])
    with pytest.raises(toolchains.ToolchainError, match="classic cfront overlay is missing"):
        project.compiler_config(tmp_path, {"kind": "rom", "platform": "n64", "compiler": {
            "toolchain": "ido-5.3", "language": "c++", "cpp_frontend": "cfront", "sandbox": "none"}})


def test_ido53_cpp_features_match_the_original_irix_frontend(tmp_path):
    source = (FIXTURES / "ido_cpp_features.cpp").read_text(encoding="utf-8")
    expected = json.loads((FIXTURES / "ido53_cpp_features_parity.json").read_text())
    assert hashlib.sha256(source.encode()).hexdigest() == expected["source_sha256"]
    result = compiler.compile_source(config(tmp_path, toolchain="ido-5.3"), "", source)
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]


@pytest.mark.parametrize("toolchain", ["ido-5.3", "ido-7.1"])
def test_real_cpp_draft_compiles_and_matches_the_c_target(tmp_path, toolchain, frontend="edg"):
    assert toolchains.installed("m2c") is not None
    original = compiler.compile_source(config(tmp_path, "c", toolchain), "", C_FUNCTIONS["ido_add"])
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "ido_add")
    draft = seeds.generate_from_asm(seeds.gnu_asm(target), "ido_add", toolchain, language="c++", valid=True)
    assert draft, "m2c did not produce a C++ draft"
    header = "typedef signed char s8; typedef short s16; typedef int s32;\n" + seeds.M2C_MACROS
    result = compiler.compile_source(config(tmp_path, toolchain=toolchain, frontend=frontend), header, draft)
    assert result.ok, result.log
    function = elfobj.extract_function(result.obj, "ido_add")
    assert function.code == target.code and function.relocs == target.relocs


def run(argv, **kwargs):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def c_game(root, toolchain):
    """Create a homemade C target with the real IDO C compiler, not the C++ candidate."""
    result = compiler.compile_source(config(root, "c", toolchain), HEADER, "int ido_total = 7;\n" + "\n".join(C_FUNCTIONS.values()))
    assert result.ok, result.log
    obj = root / "original.o"
    obj.write_bytes(result.obj)
    script = root / "original.ld"
    script.write_text("""OUTPUT_ARCH(mips)
ENTRY(ido_call)
SECTIONS {
  . = 0x80000460;
  .text : { *(.text) }
  .rodata : { *(.rodata) *(.rdata) }
  .data : { *(.data) *(.sdata) }
  /DISCARD/ : { *(.reginfo) *(.mdebug*) *(.pdr) *(.comment) *(.note*) *(.MIPS.abiflags) }
}
""", encoding="utf-8")
    tools = toolchains.binary("binutils-mips").parent
    suffix = ".exe" if sys.platform == "win32" else ""
    elf, body = root / "original.elf", root / "original.bin"
    run([tools / f"mips-ps2-decompals-ld{suffix}", "-EB", "-T", script, "-o", elf, obj])
    run([tools / f"mips-ps2-decompals-objcopy{suffix}", "-O", "binary", elf, body])
    binary = body.read_bytes()
    assert len(binary) < 0x1000
    rom = bytearray(0x40000)
    rom[:16] = struct.pack(">IIII", 0x80371240, 0xF, 0x80000400, 0x1449)
    rom[0x20:0x34] = b"IDO C++ TEST".ljust(20, b" ")
    # A conventional 0x60-byte boot entry, followed by the C-compiled functions.
    rom[0x1000:0x1060] = struct.pack(">II", 0x0C000118, 0) + bytes(0x58)  # jal ido_call; nop
    rom[0x1060:0x1060 + len(binary)] = binary
    image = root / "ido-game.z64"
    image.write_bytes(rom)
    with elf.open("rb") as stream:
        symbols = {s.name: s["st_value"] for s in ELFFile(stream).get_section_by_name(".symtab").iter_symbols()}
    return image, symbols


@pytest.mark.parametrize("toolchain", ["ido-5.3", "ido-7.1"])
def test_cpp_export_rebuilds_a_c_origin_rom_from_a_clean_tree(tmp_path, toolchain, frontend="edg"):
    assert toolchains.installed("binutils-mips") is not None
    root = tmp_path / "IDO C++ project with spaces"
    root.mkdir()
    image, symbols = c_game(root, toolchain)
    net = RomNetwork(root / "app.db", root)
    slug = net.import_rom(image, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    agent, _ = net.local_agent("agent")
    proj = net.project_row(slug)
    pid = proj["id"]
    # This fixture contains only our own source; also run in cloud containers
    # that prohibit the network namespaces used by bubblewrap.
    cfg = net.cfg(proj)
    cfg["compiler"]["sandbox"] = "none"
    cfg["compiler"]["cpp_frontend"] = frontend
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), pid))
    assert net.overview(slug)["compiler"]["language"] == "c++"
    assert net.overview(slug)["compiler"]["cpp_frontend"] == frontend
    for name in sorted(C_FUNCTIONS, key=symbols.get):
        addr = symbols[name]
        row = net.store.one("SELECT name, vram FROM functions WHERE project_id=? AND vram<=? AND vram+size>?", pid, addr, addr)
        assert row, name
        if row["vram"] != addr:
            net.split_function(agent, slug, row["name"], f"0x{addr:08X}", name)
    for name in [*C_FUNCTIONS, "ido_total"]:
        current, offset = net.symbols(pid).name_at(symbols[name])
        assert offset == 0, (name, current, offset)
        if current != name:
            net.rename_symbol(agent, slug, current, name)
    assert net.edit_context(agent, slug, "", HEADER, "original game declarations").startswith("✅")
    # Identical call opcodes with a different relocation destination must fail,
    # as must C++ that changes the result by one.
    wrong_sources = {"ido_call": "int ido_call(int value) { return ido_clamp(value); }",
                     "ido_add": CPP_ADD.replace("value + 1", "value + 2")}
    for name, c in C_FUNCTIONS.items():
        if name in wrong_sources:
            wrong = net.attempt(agent, name, wrong_sources[name], slug)
            assert wrong["score"] is not None and not wrong["matched"], wrong
        result = net.attempt(agent, name, CPP_ADD if name == "ido_add" else c, slug)
        assert result["matched"], (name, result)
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["language"] == "c++" and out["identical"], out["log"]
    assert out["matched"] == len(C_FUNCTIONS) and not out["fallback"]
    tree = Path(out["path"])
    assert len(list((tree / "src").glob("*/*.cpp"))) == len(C_FUNCTIONS)
    assert not list((tree / "src").rglob("*.c"))
    build = json.loads((tree / "build.json").read_text())
    assert build["compiler"]["toolchain"] == toolchain and build["compiler"]["language"] == "c++"
    assert build["compiler"]["cpp_frontend"] == frontend
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    # Simulate Git for Windows restoring a clone with autocrlf enabled. Its
    # normal CRLF conversion must never reach the period C++ frontend.
    assert GIT is not None
    run([GIT, "init", "-q"], cwd=tree)
    run([GIT, "-c", "core.autocrlf=true", "add", "-A"], cwd=tree)
    sources = [*(tree / "src").rglob("*.cpp"), *(tree / "include").rglob("*.h")]
    for source in sources:
        source.unlink()
    run([GIT, "-c", "core.autocrlf=true", "checkout-index", "-a", "-f"], cwd=tree)
    assert all(b"\r" not in source.read_bytes() for source in sources)
    result = run([sys.executable, "build.py"], cwd=tree)
    assert "identical" in result.stdout and "functions in C++" in result.stdout
    assert (tree / build["output"]).read_bytes() == image.read_bytes()
