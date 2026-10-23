"""Architectural GNU C BIOS thunks require pinned tools and the hardware ABI."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet import compiler, project
from decompnet.app.engine import RomNetwork
from decompnet.psx_bios import candidates, register_annotations
from decompnet.rom import match
from decompnet.rom.psx_recover import _profile_search
from decompnet.rom.symbols import SymbolTable
from .test_overlays import _iso, _resident_exe


REAL = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs original PS1 compilers and maspsx")


def words(vector=0xB0, selector=0x0C):
    return struct.pack("<3I", 0x240A0000 | vector, 0x01400008, 0x24090000 | selector)


def source():
    return candidates(words(), "bios_call")[0]


@pytest.mark.parametrize("keyword", ["asm", "__asm__"])
def test_dispatch_is_an_explicit_separate_capability_and_keeps_its_hardware_classification(keyword):
    authored = source().replace("asm(", keyword + "(")
    assert len(register_annotations(authored)) == 2
    assert "Architectural GNU C BIOS tail dispatch" in authored
    for options in ({}, {"psx_gp_registers": True}):
        with pytest.raises(compiler.SourceRejected, match="inline assembly"):
            compiler.check_source(authored, **options)
    compiler.check_source(authored, psx_bios_dispatch=True)


@pytest.mark.parametrize("old,new", [
    ('"$10"', '"$11"'), ('"$9"', '"$28"'),
    ('"$10"', '"$10; jr $ra"'),
    ('bios_vector = 0xB0;', 'bios_vector = 0xD0;'),
    ('bios_vector = 0xB0;', 'bios_vector = 0160;'),
    ('bios_selector = 0x0C;', 'bios_selector = 0x100;'),
    ('bios_selector = 0x0C;', 'bios_selector = -1;'),
    ('bios_selector = 0x0C;', 'bios_selector = selector_from_game;'),
    ('asm("$10");', 'asm("$10") = 0;'),
    ('register unsigned int', 'register unsigned long'),
    ('goto *(void *)bios_vector;', 'goto *(void *)bios_selector;'),
    ('goto *(void *)bios_vector;', 'goto *(void *)(bios_vector + 4);'),
    ('goto *(void *)bios_vector;', 'goto *(void *)bios_vector; return 0;'),
    ('goto *(void *)bios_vector;', 'asm("nop"); goto *(void *)bios_vector;'),
    ('bios_selector', 'bios_vector'),
    ('int bios_call()', 'int bios_vector()'),
])
def test_binding_exception_rejects_other_registers_dynamic_dispatch_and_extra_operations(old, new):
    changed = source().replace(old, new)
    assert not register_annotations(changed)
    with pytest.raises(compiler.SourceRejected, match="inline assembly"):
        compiler.check_source(changed, psx_gp_registers=True, psx_bios_dispatch=True)


def test_standalone_bindings_macros_and_extra_functions_do_not_form_a_dispatcher():
    for changed in (source().split("int bios_call()")[0],
                    '#define BIOS_VECTOR 0xB0\n' + source(),
                    source() + "void another(void *p) { goto *p; }",
                    source() + 'register unsigned int gp asm("$28");'):
        assert not register_annotations(changed)
        with pytest.raises(compiler.SourceRejected, match="inline assembly"):
            compiler.check_source(changed, psx_gp_registers=True, psx_bios_dispatch=True)


def test_candidate_recognition_requires_the_whole_canonical_stub_and_preserves_reviewed_prototypes():
    assert candidates(words(), "bios_call")
    assert not candidates(words(), "bios_call", "int bios_call(int arg0);")
    assert not candidates(words(), "not a C identifier")
    for code in (words(0x90), words(selector=256), words() + bytes(4), words()[4:],
                 struct.pack("<3I", 0x340A00B0, 0x01400008, 0x2409000C),
                 struct.pack("<3I", 0x240A00B0, 0x03E00008, 0x2409000C)):
        assert not candidates(code, "bios_call")


def test_custom_commands_and_cpp_cannot_enable_bios_dispatch(tmp_path):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "cmd": ["unused-custom-command"], "language": "c", "psx_bios_dispatch": True}})
    assert not cfg.psx_bios_dispatch
    # Even a manually constructed C++ config cannot activate the C exception.
    result = compiler.compile_source(compiler.CompilerConfig(["must-not-run"], language="c++", psx_bios_dispatch=True), "", source())
    assert not result.ok and "rejected" in result.log


def execute(code, vector, selector):
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
    from unicorn import mips_const as regs
    for arguments in ((0, 0, 0, 0), (1, 2, 3, 4), (0xFFFFFFFF, 0x80000000, 0x13579BDF, 0x2468ACE0)):
        cpu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        cpu.mem_map(0, 0x200000)
        cpu.mem_write(0x10500, code)
        ra, sp, gp = 0x80011000, 0x801FF000, 0x80121938
        for reg, value in ((regs.UC_MIPS_REG_RA, ra), (regs.UC_MIPS_REG_SP, sp), (regs.UC_MIPS_REG_GP, gp)):
            cpu.reg_write(reg, value)
        argregs = (regs.UC_MIPS_REG_A0, regs.UC_MIPS_REG_A1, regs.UC_MIPS_REG_A2, regs.UC_MIPS_REG_A3)
        for reg, value in zip(argregs, arguments):
            cpu.reg_write(reg, value)
        canary = bytes(range(32))
        cpu.mem_write((sp & 0x1FFFFFFF) + 16, canary)
        expected = (sum(arguments) & 0xFFFFFFFF, (arguments[0] ^ arguments[3] ^ selector) & 0xFFFFFFFF)
        dispatches = []
        def handler(uc, address, size, user):
            if address != vector:
                return
            assert tuple(cpu.reg_read(reg) for reg in argregs) == arguments
            assert cpu.reg_read(regs.UC_MIPS_REG_T1) == selector
            assert cpu.reg_read(regs.UC_MIPS_REG_T2) == vector
            assert cpu.reg_read(regs.UC_MIPS_REG_RA) == ra and cpu.reg_read(regs.UC_MIPS_REG_SP) == sp
            assert bytes(cpu.mem_read((sp & 0x1FFFFFFF) + 16, len(canary))) == canary
            dispatches.append(address)
            cpu.reg_write(regs.UC_MIPS_REG_V0, expected[0])
            cpu.reg_write(regs.UC_MIPS_REG_V1, expected[1])
            cpu.reg_write(regs.UC_MIPS_REG_PC, ra)
        cpu.hook_add(UC_HOOK_CODE, handler)
        cpu.emu_start(0x80010500, ra, count=100)
        assert dispatches == [vector]
        assert (cpu.reg_read(regs.UC_MIPS_REG_V0), cpu.reg_read(regs.UC_MIPS_REG_V1)) == expected
        assert cpu.reg_read(regs.UC_MIPS_REG_RA) == ra and cpu.reg_read(regs.UC_MIPS_REG_GP) == gp


@REAL
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("assembler", [None, {"tool": "maspsx", "version": "2.56"}], ids=["gnu", "maspsx-2.56"])
@pytest.mark.parametrize("vector,selector", [(0xA0, 1), (0xB0, 0x0C), (0xC0, 255)])
def test_original_c_compilers_emit_exact_thunks_and_preserve_the_firmware_abi(tmp_path, toolchain, assembler, vector, selector):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c", "flags": ["-O2", "-G0"], "sandbox": "none", "assembler": assembler}})
    assert cfg.psx_bios_dispatch
    code = words(vector, selector)
    authored = candidates(code, "bios_call")[0]
    result = compiler.compile_source(cfg, "", authored)
    assert result.ok, result.log
    target = match.RomTarget("bios_call", 0x80010500, code, [], False)
    linked = match.link(result.obj, "bios_call", target, SymbolTable([]), lambda *_: None)
    assert linked.exact, linked.problems
    changed = compiler.compile_source(cfg, "", authored.replace(f"bios_selector = 0x{selector:02X};", f"bios_selector = 0x{selector ^ 1:02X};"))
    assert changed.ok, changed.log
    assert not match.link(changed.obj, "bios_call", target, SymbolTable([]), lambda *_: None).exact
    execute(code, vector, selector)


@REAL
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("assembler", [None, {"tool": "maspsx", "version": "2.56"}], ids=["gnu", "maspsx-2.56"])
def test_zero_selector_literal_encoding_remains_guarded_when_the_c_compiler_uses_a_move(tmp_path, toolchain, assembler):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c", "flags": ["-O2", "-G0"], "sandbox": "none", "assembler": assembler}})
    original = words(0xA0, 0)
    result = compiler.compile_source(cfg, "", candidates(original, "bios_call")[0])
    assert result.ok, result.log
    target = match.RomTarget("bios_call", 0x80010500, original, [], False)
    linked = match.link(result.obj, "bios_call", target, SymbolTable([]), lambda *_: None)
    assert not linked.exact and linked.candidate.code != original
    # Equivalent architectural behavior does not grant an exact-byte match.
    execute(linked.candidate.code, 0xA0, 0)


@REAL
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_explicit_c_profile_is_judged_and_clean_standalone_export_retains_dispatch(tmp_path, toolchain):
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD0C] = words()
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    assert net.cfg(proj)["compiler"].get("language", "c++") == "c++"
    agent, _ = net.local_agent("architectural-bios-dispatch")
    selected = _profile_search(net, slug, agent, fn, machine_drafts=False)
    assert selected and selected["language"] == "c"
    saved = net._function(fn["name"], slug)
    assert saved["status"] == "matched" and register_annotations(saved["matched_source"])
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    tree = Path(exported["path"])
    meta = json.loads((tree / "build.json").read_text())
    stored = next(item for item in meta["functions"] if item["vram"] == 0x80010500)
    assert stored["compiler"]["language"] == "c" and stored["source"].endswith(".c")
    for directory in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(tree / directory, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=180)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / meta["disc"]["output"]).read_bytes() == original
