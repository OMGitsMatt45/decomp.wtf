"""Architectural GP access is a C register binding, never an instruction body."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet import compiler, cpp, project
from decompnet.app.engine import RomNetwork
from decompnet.rom import match
from decompnet.rom.symbols import Symbol, SymbolTable
from .test_overlays import _iso, _resident_exe


REAL = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs original PS1 compilers and maspsx")
BINDING = 'register unsigned int architectural_gp asm("$28");'


@pytest.mark.parametrize("keyword", ["asm", "__asm__"])
def test_only_explicitly_enabled_gp_declarations_are_accepted_and_keep_c_linkage(keyword):
    binding = BINDING.replace("asm", keyword)
    with pytest.raises(compiler.SourceRejected, match="inline assembly"):
        compiler.check_source(binding)
    source = "/* architectural register */\n" + binding + "\nvoid save(void) {}"
    compiler.check_source(source, psx_gp_registers=True)
    assert cpp.game_abi(source) == "/* architectural register */\n" + binding + '\nextern "C" void save(void) {}'


@pytest.mark.parametrize("source", [
    'register unsigned int gp asm("$29");',
    'register unsigned int gp asm("$gp");',
    'register unsigned long gp asm("$28");',
    'register int gp asm("$28");',
    'typedef unsigned int word; register word gp asm("$28");',
    'register unsigned int gp asm("$28") = 0;',
    'unsigned int gp asm("$28");',
    'extern unsigned int gp asm("$28");',
    'void gp(void) asm("$28");',
    'register unsigned int gp asm("$28; sw $a0,0($a1)");',
    'register unsigned int gp asm("$28" "\\n.word 0");',
    'void f(void) { register unsigned int gp asm("$28"); }',
    '#define BIND register unsigned int gp asm("$28");\nBIND',
    BINDING + '\nvoid f(void) { asm("nop"); }',
    BINDING + '\nasm(".word 0");',
])
def test_other_registers_symbol_aliases_initializers_macros_and_instruction_assembly_are_rejected(source):
    with pytest.raises(compiler.SourceRejected, match="inline assembly"):
        compiler.check_source(source, psx_gp_registers=True)


def test_custom_commands_cannot_enable_the_registered_ps1_compiler_feature(tmp_path):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "cmd": ["unused-custom-command"], "language": "c", "psx_gp_registers": True}})
    assert not cfg.psx_gp_registers


def config(root, toolchain, language):
    return project.compiler_config(root, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": language, "flags": ["-O2", "-G0"], "sandbox": "none",
        "assembler": {"tool": "maspsx", "version": "2.56"}}})


def golden(toolchain):
    words = (0x3C018001, 0xAC3C2000, 0x03E00008, 0) if toolchain == "gcc-2.7.2-psx" else \
        (0x3C028001, 0x03E00008, 0xAC5C2000)
    return struct.pack(f"<{len(words)}I", *words), 4 if toolchain == "gcc-2.7.2-psx" else 8


def source(name):
    return "/* Hardware wrapper: GCC binding reads the architectural GP register. */\n" + BINDING + \
        f"\nextern unsigned int saved_gp;\nvoid {name}(void) {{ saved_gp = architectural_gp; }}\n"


@REAL
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("language", ["c", "c++"])
def test_original_compilers_match_gp_save_code_and_execute_real_register_values(tmp_path, toolchain, language):
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
    from unicorn.mips_const import UC_MIPS_REG_GP, UC_MIPS_REG_RA
    cfg = config(tmp_path, toolchain, language)
    assert cfg.psx_gp_registers
    result = compiler.compile_source(cfg, "", source("save_gp"))
    assert result.ok, result.log
    code, low = golden(toolchain)
    target = match.RomTarget("save_gp", 0x80010500, code, [(0, 5, 0x80012000), (low, 6, 0x80012000)], False)
    linked = match.link(result.obj, "save_gp", target, SymbolTable([Symbol("saved_gp", 0x80012000)]), lambda *_: None)
    assert linked.exact, linked.problems
    changed = compiler.compile_source(cfg, "", source("save_gp").replace("= architectural_gp;", "= architectural_gp + 4U;"))
    assert changed.ok, changed.log
    assert not match.link(changed.obj, "save_gp", target, SymbolTable([Symbol("saved_gp", 0x80012000)]), lambda *_: None).exact
    for gp in (0x80018000, 0x80121938, 0x13579BDF):
        cpu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        cpu.mem_map(0, 0x200000)
        cpu.mem_write(0x10500, code)
        cpu.reg_write(UC_MIPS_REG_GP, gp)
        cpu.reg_write(UC_MIPS_REG_RA, 0x80011000)
        cpu.emu_start(0x80010500, 0x80011000, count=100)
        assert struct.unpack("<I", cpu.mem_read(0x12000, 4))[0] == gp
        assert cpu.reg_read(UC_MIPS_REG_GP) == gp


@REAL
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_gp_wrapper_matches_and_rebuilds_from_a_clean_standalone_export(tmp_path, toolchain):
    code, _ = golden(toolchain)
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    struct.pack_into("<I", exe, 0x14, 0x80018000)
    exe[0xD00:0xD00 + len(code)] = code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    net.set_function_compiler(slug, fn["name"], {"assembler": {"tool": "maspsx", "version": "2.56"}})
    authored = source(fn["name"]).replace("saved_gp", "D_80012000")
    agent, _ = net.local_agent("architectural-gp-wrapper")
    assert not net.attempt(agent, fn["name"], authored.replace("= architectural_gp;", "= architectural_gp + 4U;"), slug)["matched"]
    assert net.attempt(agent, fn["name"], authored, slug)["matched"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    tree = Path(exported["path"])
    meta = json.loads((tree / "build.json").read_text())
    for directory in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(tree / directory, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=180)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / meta["disc"]["output"]).read_bytes() == original
