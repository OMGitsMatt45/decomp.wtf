"""Reviewed GP facts make real C/C++ drafts without altering stored targets."""

import os
import struct

import pytest

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.rom.psx_drafts import global_pointer_asm, global_pointer_source
from decompnet.rom.psx_recover import installed_profiles
from .test_overlays import _iso, _resident_exe


def test_gp_inference_requires_known_unchanged_module_gp():
    assembly = "glabel leaf\nlw $v0, -4($gp)\njr $ra\nnop\n"
    inferred, symbols = global_pointer_asm(assembly, 0x80110000)
    assert "%gp_rel(D_8010FFFC)($gp)" in inferred
    assert symbols == {"D_8010FFFC"}
    assert global_pointer_asm(assembly, 0) == (assembly, set())
    changed = "glabel leaf\nlw $gp, 4($a0)\n" + assembly
    assert global_pointer_asm(changed, 0x80110000) == (changed, set())
    assert "-4($gp)" in assembly
    pointer, names = global_pointer_asm("glabel leaf\naddiu $a1, $gp, 600\njr $ra\nnop\n", 0x80110000)
    assert "addiu $a1, $gp, %gp_rel(D_80110258)" in pointer and names == {"D_80110258"}


def test_generated_gp_common_declarations_preserve_reviewed_context():
    source = "extern s32 D_80110000;\nextern s32 unrelated;\nint leaf(void) { return D_80110000; }"
    inferred = global_pointer_source(source, {"D_80110000"}, "")
    assert inferred.startswith("s32 D_80110000;") and "extern s32 unrelated;" in inferred
    assert global_pointer_source(source, {"D_80110000"}, "extern s32 D_80110000;") == source
    pointer = "extern M2C_UNK (*D_80110000)();\n"
    assert global_pointer_source(pointer, {"D_80110000"}, "") == pointer.removeprefix("extern ")
    assert global_pointer_source(pointer, {"D_80110000"}, pointer) == pointer


def test_profile_search_covers_small_data_and_only_installed_assembler(monkeypatch):
    from decompnet import toolchains
    monkeypatch.setattr(toolchains, "installed", lambda name: None if name == "maspsx" else True)
    selected = {"toolchain": "gcc-2.7.2-psx", "flags": ["-O0", "-G", "16", "-fno-strict-aliasing"]}
    profiles = list(installed_profiles(selected))
    assert len(profiles) == 24 and all(p["assembler"] is None for p in profiles)
    assert {p["language"] for p in profiles} == {"c", "c++"}
    assert {p["flags"][1] for p in profiles} == {"-G0", "-G8"}
    assert all(p["flags"][2:] == ["-fno-strict-aliasing"] for p in profiles)
    monkeypatch.setattr(toolchains, "installed", lambda name: True)
    profiles = list(installed_profiles(selected))
    assert len(profiles) == 72
    assert {p["assembler"]["version"] for p in profiles if p["assembler"]} == {"2.56", "2.86"}


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("definition, body", [
    ("int global_state;", "if (x) global_state += x; return global_state;"),
    ("unsigned char global_state;", "if (x) global_state = x; return global_state;"),
], ids=["word-global", "byte-global"])
def test_console_drafts_recover_gp_branches_and_export_exact_disc(tmp_path, toolchain, definition, body):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none", "flags": ["-O2", "-G8"]}})
    parameter = "unsigned char" if definition.startswith("unsigned char") else "int"
    original = compiler.compile_source(cfg, "", definition + f"\nint global_leaf({parameter} x) {{ {body} }}")
    assert original.ok, original.log
    function = elfobj.extract_function(original.obj, "global_leaf")
    assert function.relocs and {r.type for r in function.relocs} == {7}
    code = bytearray(function.code)
    gp, address = 0x80018000, 0x80011800
    for relocation in function.relocs:
        word = struct.unpack_from("<I", code, relocation.offset)[0]
        struct.pack_into("<I", code, relocation.offset, word & 0xFFFF0000 | (address - gp) & 0xFFFF)
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x14, gp)
    struct.pack_into("<II", exe, 0x28, address, 4)
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    assert net.cfg(row)["gp"] == gp and "-G8" in net.cfg(row)["compiler"]["flags"]
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    assert "($gp)" in fn["asm"] and "%gp_rel" not in fn["asm"]
    agent, _ = net.local_agent("gp-console-recovery")
    assert net._autopilot_one(agent, row, fn["id"], prepare_seed=False) == "match"
    assert net.store.one("SELECT asm FROM functions WHERE id=?", fn["id"])["asm"] == fn["asm"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
