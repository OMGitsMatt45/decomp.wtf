"""Byte offsets in inferred C must not acquire an extra pointer-size factor."""

import hashlib
import os
import struct

import pytest

from decompnet import compiler, elfobj, project, seeds
from decompnet.app.engine import RomNetwork
from decompnet.rom.psx_pointer_candidates import inferred_pointer_candidates
from .test_overlays import _iso, _overlay, _resident_exe


def test_opaque_automatic_global_has_byte_address_alternative():
    source = "extern M2C_UNK D_80011800;\nvoid target(s32 arg0, s32 arg1) { *(&D_80011800 + (arg0 * 4)) = arg1; }"
    assert inferred_pointer_candidates(source, "target") == [
        "extern M2C_UNK D_80011800;\nvoid target(s32 arg0, s32 arg1) { *((M2C_UNK *)((unsigned int)&D_80011800 + (arg0 * 4))) = arg1; }"
    ]


def test_automatic_overlay_global_and_reviewed_type_are_distinguished():
    source = ("extern M2C_UNK D_ovl_battle_room_80180800;\n"
              "void target(s32 arg0) { *(&D_ovl_battle_room_80180800 + arg0) = 1; }")
    candidates = inferred_pointer_candidates(source, "target")
    assert candidates == [source.replace(
        "*(&D_ovl_battle_room_80180800 + arg0)",
        "*((M2C_UNK *)((unsigned int)&D_ovl_battle_room_80180800 + arg0))")]
    assert not inferred_pointer_candidates(source, "target", "extern int D_ovl_battle_room_80180800[];")
    assert not inferred_pointer_candidates(source.replace("D_ovl_battle_room_", "D_reviewed_"), "target")


def test_reversed_address_and_inferred_argument_steps_are_bounded_candidates():
    source = "extern s16 D_80011800;\nvoid target(s32 *arg0) { *(((arg0[0] * 2)) + &D_80011800) = 1; arg0 += 4; }"
    # Array indexing in the offset requires more facts, but the inferred step
    # still has its independent alternative.
    candidates = inferred_pointer_candidates(source, "target")
    assert candidates == [source.replace("arg0 += 4", "arg0 += 1")]
    source = source.replace("arg0[0]", "3")
    candidates = inferred_pointer_candidates(source, "target")
    assert len(candidates) == 3
    assert any("(s16 *)(((3 * 2)) + (unsigned int)&D_80011800)" in item for item in candidates)
    assert candidates[0].endswith("arg0 += 1; }")


def test_other_function_bodies_and_quoted_examples_are_preserved():
    source = ('extern M2C_UNK D_80011800;\n'
              'void target(s32 *arg0) { const char *example = "arg0 += 4;"; arg0 += 4; }\n'
              'void other(s32 *arg0) { arg0 += 4; *(&D_80011800 + 4) = 1; }')
    assert inferred_pointer_candidates(source, "target") == [source.replace(
        '"arg0 += 4;"; arg0 += 4;', '"arg0 += 4;"; arg0 += 1;')]


def test_inferred_return_and_assignment_address_sums_have_byte_base_alternatives():
    source = ("extern M2C_UNK D_80011800;\nvoid *target(s32 arg0) { void *var_v0; "
              "var_v0 = &D_80011800 + (arg0 * 0x48); return (arg0 * 0x48) + &D_80011800; }")
    candidates = inferred_pointer_candidates(source, "target")
    assert len(candidates) == 3
    assert candidates[0] == source.replace("&D_80011800", "(s8 *)&D_80011800")
    assert not inferred_pointer_candidates(source, "target", "extern char D_80011800[];")


@pytest.mark.parametrize("source,context", [
    ("extern M2C_UNK D_80011800;\nvoid target(s32 arg0) { *(&D_80011800 + arg0) = 1; }", "extern int D_80011800;"),
    ("extern M2C_UNK D_80011800;\nvoid target(s32 arg0) { *(&D_80011800 + arg0) = 1; }", "void target(int);"),
    ("extern int table;\nvoid target(s32 arg0) { *(&table + arg0) = 1; }", ""),
    ("void target(s32 *cursor) { cursor += 4; }", ""),
    ("extern M2C_UNK D_80011800;\nvoid target(void) { /* *(&D_80011800 + 4) */ }", ""),
    ("extern s8 D_80011800;\nvoid target(void) { *(&D_80011800 + 4) = 1; }", ""),
    ("extern M2C_UNK D_80011800;\nvoid target(void) { *((s32 *)(&D_80011800 + 4)) = 1; }", ""),
    ("extern M2C_UNK D_80011800;\nvoid *target(void) { return (s32 *)(&D_80011800 + 4); }", ""),
    ("extern M2C_UNK D_80011800;\nvoid *target(void) { return callee(&D_80011800 + 4); }", ""),
])
def test_reviewed_or_explicit_types_and_noncode_are_preserved(source, context):
    assert not inferred_pointer_candidates(source, "target", context)


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("definition,symbol", [
    ("extern int table[]; void original(int index, int value) { table[index] = value; }", "table"),
    ("extern char rows[]; void *original(int index) { return rows + index * 0x48; }", "rows"),
], ids=["word-array-store", "row-byte-address"])
def test_original_byte_offsets_recover_through_exact_judge(tmp_path, toolchain, definition, symbol):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "flags": ["-O2", "-G0"], "sandbox": "none"}})
    original = compiler.compile_source(cfg, "", definition)
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "original")
    assert target.relocs and {r.type for r in target.relocs} == {5, 6}
    address = 0x80011800
    code = bytearray(target.code)
    for relocation in target.relocs:
        assert relocation.symbol == symbol
        value = ((address + 0x8000) >> 16) & 0xFFFF if relocation.type == 5 else address & 0xFFFF
        word = struct.unpack_from("<I", code, relocation.offset)[0]
        struct.pack_into("<I", code, relocation.offset, word & 0xFFFF0000 | value)
    exe = bytearray(_resident_exe())
    struct.pack_into("<II", exe, 0x28, address, 4)
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    header = net._context(proj["id"], fn["unit"])["header"]
    draft = net._machine_draft(fn, proj, header, valid=True)
    assert draft and "&D_80011800" in draft
    broken = net._compile(proj, header, seeds.M2C_MACROS + "\n" + draft, fn)
    assert broken.ok and net._evaluate(fn, proj, broken.obj)[1] is False
    candidates = inferred_pointer_candidates(draft, fn["name"], header)
    assert candidates
    for candidate in candidates:
        result = net._compile(proj, header, seeds.M2C_MACROS + "\n" + candidate, fn)
        if result.ok and net._evaluate(fn, proj, result.obj)[1] is True:
            break
    else:
        pytest.fail("byte-address candidates did not reproduce the original byte offsets")
    assert not inferred_pointer_candidates(draft, fn["name"], header + "\nextern int D_80011800[];")
    agent, _ = net.local_agent("byte-offset-test")
    assert net._autopilot_one(agent, proj, fn["id"], prepare_seed=False) == "match"
    assert net._function(fn["name"], slug)["status"] == "matched"
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_original_overlay_byte_offset_recovers_and_exports(tmp_path, toolchain):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "flags": ["-O2", "-G0"], "sandbox": "none"}})
    original = compiler.compile_source(cfg, "", "extern int table[]; void original(int index, int value) { table[index] = value; }")
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "original")
    address = 0x80180800
    code = bytearray(target.code)
    assert len(code) <= 32 and target.relocs
    for relocation in target.relocs:
        assert relocation.symbol == "table" and relocation.type in (5, 6)
        value = ((address + 0x8000) >> 16) & 0xFFFF if relocation.type == 5 else address & 0xFFFF
        word = struct.unpack_from("<I", code, relocation.offset)[0]
        struct.pack_into("<I", code, relocation.offset, word & 0xFFFF0000 | value)
    overlay = bytearray(_overlay(0x80180000, 40)).ljust(0x1000, b"\0")
    overlay[:32] = code.ljust(32, b"\0")
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "BATTLE.BIN": overlay})
    review = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": [{
        "name": "battle", "path": "BATTLE.BIN", "stored_size": len(overlay), "size": len(overlay),
        "load": 0x80180000, "code_end": 0x500}]}
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, reviewed_layout=review, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND unit='ovl_battle' AND vram=?", proj["id"], 0x80180000)
    assert fn is not None
    header = net._context(proj["id"], fn["unit"])["header"]
    draft = net._machine_draft(fn, proj, header, valid=True)
    assert draft and "&D_ovl_battle_80180800" in draft
    assert inferred_pointer_candidates(draft, fn["name"], header)
    assert not inferred_pointer_candidates(draft, fn["name"], header + "\nextern int D_ovl_battle_80180800[];")
    agent, _ = net.local_agent("overlay-byte-offset-test")
    assert net._autopilot_one(agent, proj, fn["id"], prepare_seed=False) == "match"
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
