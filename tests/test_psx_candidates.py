"""Inferred narrow stores do not prove narrow o32 input parameters."""

import os
import struct

import pytest

from decompnet import compiler, elfobj, project, seeds
from decompnet.app.engine import RomNetwork
from decompnet.rom.psx_candidates import inferred_parameter_candidates
from .test_overlays import _iso, _resident_exe


def test_narrow_inputs_have_word_candidates_without_changing_pointer_types_or_body():
    source = "void target(s8 *arg0, s8 arg1) { if (arg1 >= 0) *arg0 = arg1; }"
    assert inferred_parameter_candidates(source, "target") == [
        "void target(s8 *arg0, int arg1) { if (arg1 >= 0) *arg0 = arg1; }",
        "void target(s8 *arg0, unsigned int arg1) { if (arg1 >= 0) *arg0 = arg1; }",
    ]


def test_multiple_narrow_inputs_include_combined_candidate_once():
    source = "int target(u8 arg0, s16 arg1) { return arg0 + arg1; }"
    candidates = inferred_parameter_candidates(source, "target")
    assert len(candidates) == len(set(candidates)) == 7
    assert "int target(unsigned int arg0, int arg1) { return arg0 + arg1; }" in candidates


@pytest.mark.parametrize("source,context", [
    ("void target(s8 *arg0, s8 arg1) {}", "void target(char *, char);"),
    ("void target(s8 *output, s8 value) {}", ""),
    ("void target(double arg0, s8 arg1) {}", ""),
    ("void target(s8 *arg0, int arg1) {}", ""),
])
def test_reviewed_non_inferred_wide_and_already_word_signatures_are_preserved(source, context):
    assert not inferred_parameter_candidates(source, "target", context)


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_full_word_sign_branch_and_byte_store_recover_through_the_exact_judge(tmp_path, toolchain):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none"}})
    original = compiler.compile_source(cfg, "", "void original(signed char *out, int value) { if (value >= 0) *out = value; }")
    assert original.ok, original.log
    target = elfobj.extract_function(original.obj, "original")
    assert not target.relocs
    # BLTZ must test the complete incoming a1, including values such as 256.
    assert struct.unpack("<5I", target.code) == (0x04A00002, 0, 0xA0850000, 0x03E00008, 0)
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(target.code)] = target.code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    header = net._context(proj["id"], fn["unit"])["header"]
    draft = net._machine_draft(fn, proj, header, valid=True)
    assert draft and "s8 arg1" in draft
    broken = net._compile(proj, header, seeds.M2C_MACROS + "\n" + draft, fn)
    assert broken.ok and net._evaluate(fn, proj, broken.obj)[1] is False
    for candidate in inferred_parameter_candidates(draft, fn["name"], header):
        result = net._compile(proj, header, seeds.M2C_MACROS + "\n" + candidate, fn)
        if result.ok and net._evaluate(fn, proj, result.obj)[1] is True:
            break
    else:
        pytest.fail("word-parameter candidates did not reproduce the original full-register branch")
    agent, _ = net.local_agent("word-parameter-test")
    assert net._autopilot_one(agent, proj, fn["id"], prepare_seed=False) == "match"
    assert net._function(fn["name"], slug)["status"] == "matched"
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
