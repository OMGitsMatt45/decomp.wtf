"""Failed console drafts remain reviewable without receiving recovered credit."""

import os
import struct

import pytest

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.rom.psx_recover import _profile_search
from .test_overlays import _iso, _resident_exe


def failed_project(tmp_path, toolchain):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c", "sandbox": "none", "flags": ["-O2", "-G8"]}})
    compiled = compiler.compile_source(cfg, "", """
        void *head;
        int find_pointer(void *needle) {
            void *walk = head;
            while (walk) {
                if (walk == needle) return 1;
                walk = *(void **)((char *)*(void **)((char *)walk + 12) + 396);
            }
            return 0;
        }
    """)
    assert compiled.ok, compiled.log
    fn = elfobj.extract_function(compiled.obj, "find_pointer")
    code = bytearray(fn.code)
    address, gp, head = 0x80010500, 0x80018000, 0x80011800
    assert {r.type for r in fn.relocs} <= {4, 7} and any(r.type == 7 for r in fn.relocs)
    for relocation in fn.relocs:
        word = struct.unpack_from("<I", code, relocation.offset)[0]
        if relocation.type == 7:
            assert relocation.symbol == "head"
            word = word & 0xFFFF0000 | (head - gp) & 0xFFFF
        else:
            # The authored function's local absolute jump originally has .text
            # based at zero; place that self-jump at the fixture's load address.
            assert relocation.symbol in (".text", "find_pointer")
            word = word & 0xFC000000 | ((word & 0x3FFFFFF) + (address >> 2)) & 0x3FFFFFF
        struct.pack_into("<I", code, relocation.offset, word)
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x14, gp)
    struct.pack_into("<II", exe, 0x28, head, 4)
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (address >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    target = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], address)
    agent, _ = net.local_agent("failed-draft-review")
    return net, slug, proj, target, agent


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs original PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_failed_pointer_draft_is_retained_once_without_recovery_credit(tmp_path, toolchain):
    net, slug, proj, target, agent = failed_project(tmp_path, toolchain)
    assert net._autopilot_one(agent, proj, target["id"], prepare_seed=False) == "fail"
    saved = net._function(target["name"], slug)
    assert saved["status"] == "open" and saved["matched_source"] is None and saved["best_score"] is None
    attempts = net.store.all("SELECT * FROM attempts WHERE function_id=?", target["id"])
    assert len(attempts) == 1
    failure = attempts[0]
    assert not failure["compiled"] and failure["score"] is None and failure["via"] == "autopilot"
    assert target["name"] in failure["source"]
    diagnostic = net.function_diff(slug, target["name"])
    assert diagnostic["rows"] is None and "pointer" in diagnostic["error"]
    assert diagnostic["source"] == failure["source"]
    assert net._autopilot_one(agent, proj, target["id"], prepare_seed=False) == "fail"
    assert net.store.one("SELECT COUNT(*) n FROM attempts WHERE function_id=?", target["id"])["n"] == 1


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs original PS1 compilers and m2c")
def test_profile_search_reuses_a_retained_failed_draft_without_regenerating_m2c(tmp_path):
    net, slug, proj, target, agent = failed_project(tmp_path, "gcc-2.7.2-psx")
    assert net._autopilot_one(agent, proj, target["id"], prepare_seed=False) == "fail"
    saved = net._function(target["name"], slug)
    failure = net.store.one("SELECT * FROM attempts WHERE function_id=?", target["id"])
    # The retained source is a genuine C candidate; only the full original-byte
    # judge can promote it after selecting a working period C compiler profile.
    selected = _profile_search(net, slug, agent, saved, machine_drafts=False)
    assert selected and selected["language"] == "c"
    recovered = net._function(target["name"], slug)
    assert recovered["status"] == "matched" and recovered["matched_source"] == failure["source"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
