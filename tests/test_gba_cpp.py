"""Required native Windows/Linux tests of actual agbcc C++ and strict matching."""

from io import BytesIO
from dataclasses import replace
import os
from pathlib import Path
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import compiler, elfobj, project, seeds, toolchains
from decompnet.rom import match_arm
from decompnet.rom.symbols import Symbol, SymbolTable

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_GBA_CPP") != "1", reason="needs the pinned GBA C++ toolchain")
HEADER = "extern int total;\nextern int callback(int);\nextern int other(int);\n"
CPP = """#ifndef __cplusplus
#error A real C++ frontend is required
#endif
template<class T> class Counter {
public: T value; Counter(T x) : value(x) {} T next() const { return value + 1; }
};
template<class T> inline T next(T x) { const Counter<T> c(x); const T &ref = c.value; return ref + 1; }
int gba_add(int x) { return next(x); }
"""
TABLE = "static const int values[] = {31, 47, 59, 83};\nint gba_table(int i) { return values[i & 3]; }\n"


def config(tmp_path, language="c++"):
    assert all(toolchains.installed(t) is not None for t in ("agbcc", "arm-gnu", "m2c"))
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "gba", "compiler": {
        "toolchain": "agbcc", "language": language, "sandbox": "none"}})
    assert not cfg.wsl
    return cfg


def test_actual_cpp_features_preserve_c_code_and_linkage(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    assert any(Path(a).name in ("agbcc-cpp", "agbcc-cpp.exe") for a in cfg.cmd)
    start = subprocess.Popen

    def native_only(args, *positional, **kwargs):
        assert Path(args[0]).name.lower() not in ("wsl", "wsl.exe")
        return start(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", native_only)
    original = compiler.compile_source(config(tmp_path, "c"), "", "int gba_add(int x) { return x + 1; }")
    result = compiler.compile_source(cfg, "", CPP)
    assert original.ok and result.ok, original.log + result.log
    assert elfobj.extract_function(result.obj, "gba_add").code == elfobj.extract_function(original.obj, "gba_add").code
    assert ELFFile(BytesIO(result.obj))["e_machine"] == "EM_ARM"
    assert not compiler.compile_source(config(tmp_path, "c"), "", CPP).ok
    assert not compiler.compile_source(cfg, "", "int broken() { int &ref = 1; return ref; }").ok


def test_cpp_m2c_draft_compiles_and_matches_the_c_target(tmp_path):
    original = compiler.compile_source(config(tmp_path, "c"), "", "int gba_add(int x) { return x + 1; }")
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "gba_add")
    draft = seeds.generate_from_asm(seeds.gnu_asm(target), "gba_add", "agbcc", language="c++", valid=True)
    assert draft, "m2c did not generate a C++ GBA draft"
    result = compiler.compile_source(config(tmp_path), "typedef int s32;", draft)
    assert result.ok, result.log
    assert elfobj.extract_function(result.obj, "gba_add").code == target.code


def test_out_of_line_templates_and_explicit_cpp_overloads_keep_cpp_linkage(tmp_path):
    cfg = config(tmp_path)
    cfg = replace(cfg, cmd=["-O0" if a == "-O2" else a for a in cfg.cmd])
    source = '''template<class T> T helper(T x) { return x + 7; }
extern "C++" int overloaded(int x) { return helper(x); }
extern "C++" int overloaded(int *x) { return helper(*x); }
int game_entry(int x) { return overloaded(x); }
'''
    result = compiler.compile_source(cfg, "", source)
    assert result.ok, result.log
    symbols = ELFFile(BytesIO(result.obj)).get_section_by_name(".symtab")
    functions = {s.name: s for s in symbols.iter_symbols() if s["st_info"]["type"] == "STT_FUNC"}
    assert "game_entry" in functions and "overloaded" not in functions
    assert len([n for n in functions if n.startswith("overloaded__")]) == 2
    helpers = [s for n, s in functions.items() if n.startswith("helper__")]
    assert len(helpers) == 1 and helpers[0]["st_info"]["bind"] == "STB_WEAK"


@pytest.fixture
def c_target(tmp_path):
    """Link real C code/data so wrong relocations cannot pass by masking opcodes."""
    source = "int gba_add(int x) { return x + 1; }\nint gba_call(int x) { return callback(x) + total; }\n" + TABLE \
        + "int callback(int x) { return x + 7; }\nint other(int x) { return x + 13; }\n"
    result = compiler.compile_source(config(tmp_path, "c"), HEADER, source)
    assert result.ok, result.log
    obj = tmp_path / "original.o"
    obj.write_bytes(result.obj)
    script = tmp_path / "game.ld"
    script.write_text("SECTIONS { .text 0x08000200 : { *(.text) } .rodata 0x08000800 : { *(.rodata*) } }\n"
                      "total = 0x02000000;\n")
    tools = toolchains.require("arm-gnu") / "bin"
    suffix = ".exe" if os.name == "nt" else ""
    elf, binary = tmp_path / "original.elf", tmp_path / "original.bin"
    for args in ([str(tools / f"arm-none-eabi-ld{suffix}"), "-T", str(script), "-o", str(elf), str(obj)],
                 [str(tools / f"arm-none-eabi-objcopy{suffix}"), "-O", "binary", str(elf), str(binary)]):
        subprocess.run(args, check=True, capture_output=True)
    image = binary.read_bytes()
    linked = ELFFile(BytesIO(elf.read_bytes()))
    syms = [Symbol(s.name, s["st_value"] & ~1, s["st_size"], "func" if s["st_info"]["type"] == "STT_FUNC" else "data")
            for s in linked.get_section_by_name(".symtab").iter_symbols() if s.name]
    table = SymbolTable(syms)

    def read(addr, size):
        off = addr - 0x08000200
        return image[off:off + size] if 0 <= off and off + size <= len(image) else None

    def check(name, source):
        symbol = table.by_name[name]
        result = compiler.compile_source(config(tmp_path), HEADER, source)
        assert result.ok, result.log
        target = match_arm.ArmTarget(name, symbol.address, read(symbol.address, symbol.size), True)
        return match_arm.link(result.obj, name, target, table, read)

    return check


def test_strict_cpp_match_rejects_wrong_instruction_relocation_and_owned_data(c_target):
    assert c_target("gba_add", CPP).exact
    assert not c_target("gba_add", CPP.replace("ref + 1", "ref + 2")).exact
    call = "int gba_call(int x) { return callback(x) + total; }"
    assert c_target("gba_call", call).exact
    assert not c_target("gba_call", call.replace("callback(x)", "other(x)")).exact
    assert c_target("gba_table", TABLE).exact
    assert not c_target("gba_table", TABLE.replace("47", "48")).exact


@pytest.mark.parametrize("variant", ["normal", "old"])
def test_each_thumb_cpp_variant_uses_its_corresponding_c_backend(tmp_path, variant, monkeypatch):
    if os.name == "nt":
        monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32"))
        start = subprocess.Popen
        def native_only(args, *positional, **kwargs):
            assert Path(args[0]).stem.lower() not in ("wsl", "bash", "sh")
            return start(args, *positional, **kwargs)
        monkeypatch.setattr(subprocess, "Popen", native_only)
    def configured(language):
        return project.compiler_config(tmp_path, {"kind": "rom", "platform": "gba", "compiler": {
            "toolchain": "agbcc", "language": language, "agbcc_variant": variant, "sandbox": "none"}})
    c = compiler.compile_source(configured("c"), HEADER, "int gba_add(int x) { return callback(x + 1) + total; }")
    cpp = compiler.compile_source(configured("c++"), HEADER, CPP.replace("return next(x);", "return callback(next(x)) + total;"))
    assert c.ok and cpp.ok, c.log + cpp.log
    original, candidate = [elfobj.extract_function(r.obj, "gba_add") for r in (c, cpp)]
    assert candidate.code == original.code and candidate.relocs == original.relocs
    assert {r.symbol for r in candidate.relocs} >= {"callback", "total"}
    if variant == "old":
        assert any(Path(a).stem == "old_agbcc-cpp" for a in configured("c++").cmd)
