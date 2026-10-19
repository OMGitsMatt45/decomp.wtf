"""Original EE-GCC 2.96 C++ frontend and strict matching on Linux."""

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from elftools.elf.elffile import ELFFile

from decompnet import compiler, elfobj, project, seeds, toolchains, wsl
from decompnet.app.engine import RomNetwork
from decompnet.rom import match, ps2, split
from decompnet.rom.symbols import Symbol, SymbolTable
from .fixtures.generate_native_compiler_parity import describe_functions

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PS2_CPP") != "1", reason="needs the pinned PS2 C++ toolchains")
FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "int total; int other_total; extern int callback(int); extern int other(int);\n"
TABLE = "int ps2_table(int i) { static const int values[] = {31, 47, 59, 83}; return values[i & 3]; }"
SMALL = "int ps2_small(void) { static volatile int state = 7; return state; }"


@pytest.fixture
def tcid():
    return "ee-gcc-2.96"


@pytest.fixture(autouse=True)
def native_only(monkeypatch):
    monkeypatch.setenv("DECOMP_RUNTIME", "native")
    if sys.platform == "win32":
        monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32"))

    def no_wsl(*args, **kwargs):
        pytest.fail("PS2 C++ must execute without WSL")

    monkeypatch.setattr(wsl, "status", no_wsl)
    monkeypatch.setattr(wsl, "run", no_wsl)
    start = subprocess.Popen

    def native_process(args, *positional, **kwargs):
        assert Path(str(args[0])).name.lower() not in ("wsl", "wsl.exe", "sh", "sh.exe", "bash", "bash.exe")
        return start(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", native_process)


def config(root, tcid, language="c++"):
    assert all(toolchains.installed(t) is not None for t in (tcid, "binutils-mips", "m2c"))
    cfg = project.compiler_config(root, {"kind": "rom", "platform": "ps2", "compiler": {
        "toolchain": tcid, "language": language, "flags": ["-O2", "-G8"], "sandbox": "none"}})
    assert not cfg.wsl
    return cfg


def test_cpp_features_match_pinned_linux_code_and_relocations(tmp_path, tcid):
    source = (FIXTURES / "ps2_cpp_features.cpp").read_text()
    expected = json.loads((FIXTURES / "ps2_cpp_parity.json").read_text())
    assert hashlib.sha256(source.encode()).hexdigest() == expected["source_sha256"]
    result = compiler.compile_source(config(tmp_path, tcid), "", source)
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]
    assert ELFFile(BytesIO(result.obj))["e_machine"] == "EM_MIPS"
    assert not elfobj.extract_function(result.obj, "ps2_template").big_endian
    assert not compiler.compile_source(config(tmp_path, tcid, "c"), "", source).ok
    assert not compiler.compile_source(config(tmp_path, tcid), "", "int broken() { return missing_identifier; }").ok


def test_cpp_draft_recompiles_to_the_original_c_code(tmp_path, tcid):
    original = compiler.compile_source(config(tmp_path, tcid, "c"), "", "int ps2_add(int x) { return x + 1; }")
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "ps2_add")
    draft = seeds.generate_from_asm(seeds.gnu_asm(target), "ps2_add", tcid, language="c++", valid=True)
    assert draft, "m2c failed to produce a PS2 C++ draft"
    result = compiler.compile_source(config(tmp_path, tcid), "typedef signed char s8; typedef short s16; typedef int s32;\n" + seeds.M2C_MACROS, draft)
    assert result.ok, result.log
    assert describe_functions(result.obj) == describe_functions(original.obj)


def test_missing_cpp_frontend_never_falls_back_to_c(tmp_path, tcid, monkeypatch):
    config(tmp_path, tcid)
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if p.name in ("cc1plus",) else original(p))
    with pytest.raises(toolchains.ToolchainError, match=r"C\+\+ frontend is missing"):
        config(tmp_path, tcid)


@pytest.fixture
def c_target(tmp_path, tcid):
    source = "int ps2_add(int x) { return x + 1; }\nint ps2_call(int x) { return callback(x) + total; }\n" + TABLE + "\n" + SMALL \
        + "\nint callback(int x) { return x + 7; }\nint other(int x) { return x + 13; }\n"
    result = compiler.compile_source(config(tmp_path, tcid, "c"), HEADER, source)
    assert result.ok, result.log
    sizes = {name: len(elfobj.extract_function(result.obj, name).code) for name in elfobj.list_functions(result.obj)}
    original_functions = {name: elfobj.extract_function(result.obj, name) for name in sizes}
    assert any(r.type == match.R_MIPS_GPREL16 for r in original_functions["ps2_call"].relocs)
    obj = tmp_path / "original.o"
    obj.write_bytes(result.obj)
    script = tmp_path / "game.ld"
    script.write_text("SECTIONS { .text 0x00100200 : { *(.text) } .rodata 0x00100800 : { *(.rodata*) *(.rdata*) } "
                      ".sdata 0x00101000 : { *(.sdata) *(.data) } /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) } }\n"
                      "_gp = 0x00108000; total = 0x00101000; other_total = 0x00101004;\n")
    tools = toolchains.require("binutils-mips")
    suffix = ".exe" if sys.platform == "win32" else ""
    elf, binary = tmp_path / "original.elf", tmp_path / "original.bin"
    for args in ([str(tools / f"mips-ps2-decompals-ld{suffix}"), "-EL", "-T", str(script), "-o", str(elf), str(obj)],
                 [str(tools / f"mips-ps2-decompals-objcopy{suffix}"), "-O", "binary", str(elf), str(binary)]):
        subprocess.run(args, check=True, capture_output=True)
    image = binary.read_bytes()
    linked = ELFFile(BytesIO(elf.read_bytes()))
    syms = [Symbol(s.name, s["st_value"], s["st_size"], "func" if s["st_info"]["type"] == "STT_FUNC" else "data")
            for s in linked.get_section_by_name(".symtab").iter_symbols() if s.name]
    table = SymbolTable(syms)

    def read(addr, size):
        off = addr - 0x00100200
        return image[off:off + size] if 0 <= off and off + size <= len(image) else None

    def check(name, source):
        symbol = table.by_name[name]
        code = read(symbol.address, sizes[name])
        original = original_functions[name]
        relocs = []
        for reloc in original.relocs:
            word = int.from_bytes(code[reloc.offset:reloc.offset + 4], "little")
            if reloc.type == match.R_MIPS_26:
                addr = ((symbol.address + reloc.offset + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
            elif reloc.type == match.R_MIPS_GPREL16:
                value = word & 0xFFFF
                addr = 0x00108000 + (value - 0x10000 if value & 0x8000 else value)
            else:
                other = next(r for r in original.relocs if r.symbol == reloc.symbol and r.type != reloc.type)
                other_word = int.from_bytes(code[other.offset:other.offset + 4], "little")
                high, low = (word, other_word) if reloc.type == match.R_MIPS_HI16 else (other_word, word)
                low &= 0xFFFF
                addr = (((high & 0xFFFF) << 16) + (low - 0x10000 if low & 0x8000 else low)) & 0xFFFFFFFF
            relocs.append((reloc.offset, reloc.type, addr))
        result = compiler.compile_source(config(tmp_path, tcid), HEADER, source)
        assert result.ok, result.log
        target = match.RomTarget(name, symbol.address, code, relocs, False, 0x00108000)
        return match.link(result.obj, name, target, table, read)

    # Keep the independently C-compiled linked image for the export regression.
    check.image, check.table, check.tcid, check.root = image, table, tcid, tmp_path
    return check


def test_strict_cpp_match_rejects_changed_instructions_call_and_gp_relocations_and_data(c_target):
    add = "int ps2_add(int x) { return x + 1; }"
    assert c_target("ps2_add", add).exact
    assert not c_target("ps2_add", add.replace("x + 1", "x + 2")).exact
    call = "int ps2_call(int x) { return callback(x) + total; }"
    assert c_target("ps2_call", call).exact
    assert not c_target("ps2_call", call.replace("callback(x)", "other(x)")).exact
    assert not c_target("ps2_call", call.replace("+ total", "+ other_total")).exact
    assert c_target("ps2_table", TABLE).exact
    assert not c_target("ps2_table", TABLE.replace("47", "48")).exact
    assert c_target("ps2_small", SMALL).exact
    assert not c_target("ps2_small", SMALL.replace("= 7", "= 8")).exact


def test_elf_reconstruction_uses_rebuilt_sections_and_rejects_stale_inputs(c_target):
    original = (c_target.root / "original.elf").read_bytes()
    flat = c_target.image
    assert ps2.rebuild_elf(original, flat, flat) == original
    changed = bytes([flat[0] ^ 1]) + flat[1:]
    rebuilt = ps2.rebuild_elf(original, flat, changed)
    offset = ELFFile(BytesIO(original)).get_section_by_name(".text")["sh_offset"]
    expected = bytearray(original)
    expected[offset] ^= 1
    assert rebuilt == expected  # the original headers/metadata stay intact
    with pytest.raises(ValueError, match="does not match"):
        ps2.rebuild_elf(original, changed, changed)
    with pytest.raises(ValueError, match="incompatible layout or size"):
        ps2.rebuild_elf(original, flat, flat[:-1])


def test_exported_build_rejects_changed_owned_table_and_small_data(c_target, monkeypatch):
    root, table, tcid = c_target.root, c_target.table, c_target.tcid
    image = root / "original.elf"
    net = RomNetwork(root / "app.db", root)
    # The tiny fixture has a known linker layout, too little startup code for
    # splat's commercial-executable section heuristics. Supply its actual map.
    patch_config = split._patch_config

    def fixture_layout(path):
        config = yaml.safe_load(path.read_text())
        config["options"]["gp_value"] = 0x00108000
        config["segments"] = [{"name": "main", "type": "code", "start": 0, "vram": 0x00100200,
            "subsegments": [[0, "c", "main"], [0x600, "rodata", "constants"], [0xE00, "data", "globals"]]},
            [len(c_target.image)]]
        path.write_text(yaml.safe_dump(config, sort_keys=False).replace("gp_value: 1081344", "gp_value: 0x00108000"))
        return patch_config(path)

    with monkeypatch.context() as scoped:
        scoped.setattr(split, "_patch_config", fixture_layout)
        slug = net.import_rom(image, toolchain=tcid, confirmed=True, log=lambda *_: None)
    agent, _ = net.local_agent("agent")
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    cfg["compiler"].update(sandbox="none", flags=["-O2", "-G8"])
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    functions = ("ps2_add", "ps2_call", "ps2_table", "ps2_small", "callback", "other")
    for name in sorted(functions, key=lambda n: table.by_name[n].address):
        addr = table.by_name[name].address
        row = net.store.one("SELECT name,vram FROM functions WHERE project_id=? AND vram<=? AND vram+size>?", proj["id"], addr, addr)
        assert row, name
        if row["vram"] != addr:
            net.split_function(agent, slug, row["name"], f"0x{addr:08X}", name)
    for name in (*functions, "total", "other_total"):
        addr = table.by_name[name].address
        current, offset = net.symbols(proj["id"]).name_at(addr)
        if offset:
            current = f"D_{addr:08X}"
        if current != name:
            net.rename_symbol(agent, slug, current, name)
    assert net.edit_context(agent, slug, "", HEADER, "game declarations").startswith("✅")
    sources = {"ps2_add": "int ps2_add(int x) { return x + 1; }",
               "ps2_call": "int ps2_call(int x) { return callback(x) + total; }",
               "ps2_table": TABLE, "ps2_small": SMALL}
    for name, source in sources.items():
        result = net.attempt(agent, name, source, slug)
        assert result["matched"], (name, result)
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["identical"] and out["matched"] == len(sources) and not out["fallback"], out["log"]
    tree = Path(out["path"])
    for name, original, wrong in (("ps2_table", "47", "48"), ("ps2_small", "= 7", "= 8")):
        path = next((tree / "src").rglob(f"{name}.cpp"))
        source = path.read_text()
        path.write_text(source.replace(original, wrong))
        for args in ([], ["check", name]):
            result = subprocess.run([sys.executable, "build.py", *args], cwd=tree, capture_output=True, text=True)
            assert result.returncode != 0, result.stdout + result.stderr
        path.write_text(source)
    result = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
    assert result.returncode == 0 and "identical" in result.stdout, result.stdout + result.stderr
