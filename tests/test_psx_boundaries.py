"""Reviewed boundaries retain all original evidence and require a new exact match."""

import hashlib
import json
import os
from pathlib import Path
import struct
import time

import pytest

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.network import NetworkError
from decompnet.rom import split
from decompnet.rom.psx_boundaries import merge_reviewed
from .test_overlays import _iso, _resident_exe


def model(tmp_path):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    root = tmp_path / "image"
    root.mkdir()
    words = (0x8F820008, 0x10800003, 0, 0x03E00008, 0, 0x8F82000C, 0x03E00008, 0,
             0x03E00008, 0x24020063, 0, 0, 0, 0)
    image = struct.pack("<%dI" % len(words), *words)
    (root / "original.bin").write_bytes(image)
    cfg = {"kind": "rom", "platform": "psx", "big_endian": False,
           "rom": {"file": "original.bin"}, "gp": 0x80118000,
           "compiler": {"toolchain": "gcc-2.7.2-psx", "flags": ["-O2", "-G8"], "language": "c++"},
           "segments": [{"name": "main", "rom_start": 0, "rom_end": len(image), "vram": 0x80010000}]}
    with net.store.tx() as db:
        pid = db.execute("INSERT INTO projects(slug,name,arch,root,config) VALUES(?,?,?,?,?)",
                         ("reviewed", "Reviewed", "mips", str(root), json.dumps(cfg))).lastrowid
        for name, first, last in (("func_80010000", 0, 5), ("func_80010014", 5, 8), ("func_80010020", 8, 10)):
            instructions = []
            for index in range(first, last):
                opcode = words[index]
                mnemonic, operands = {
                    0x8F820008: ("lw", "$v0, 8($gp)"), 0x8F82000C: ("lw", "$v0, 12($gp)"),
                    0x10800003: ("beqz", "$a0, .L80010014"), 0x03E00008: ("jr", "$ra"),
                    0x24020063: ("addiu", "$v0, $zero, 99"), 0: ("nop", ""),
                }[opcode]
                instructions.append(split.AsmLine(index * 4, 0x80010000 + index * 4, opcode, mnemonic, operands))
            fn = split.RomFunction(name, instructions[0].vram, first * 4, "main", instructions, Path())
            relocations = [[0, 7, cfg["gp"] + (8 if first == 0 else 12)]] if first < 8 else []
            db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,unit,vram,rom_offset) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (pid, name, fn.size, len(instructions), image[first * 4:last * 4],
                        json.dumps(relocations), net._asm_source(fn), "main", fn.vram, first * 4))
            db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?)",
                       (pid, name, fn.vram, fn.size, "func"))
    agent, _ = net.local_agent("boundary-reviewer")
    return net, net.project_row("reviewed"), agent


def merge(net, agent, **kwargs):
    return merge_reviewed(net, "reviewed", "func_80010000", "func_80010014", agent=agent,
                          reason="Reviewed branch reaches the shared return block", **kwargs)


def test_merge_archives_old_rows_attempts_and_profiles_without_recovery_credit(tmp_path):
    net, proj, agent = model(tmp_path)
    head, tail = [net._function(name, "reviewed") for name in ("func_80010000", "func_80010014")]
    other = net._function("func_80010020", "reviewed")
    with net.store.tx() as db:
        for fn in (head, tail):
            db.execute("INSERT INTO attempts(function_id,agent_id,score,source,context_version) VALUES(?,?,?,?,?)",
                       (fn["id"], agent.id, 50, "old inferred draft", 1))
            db.execute("UPDATE functions SET attempts=1,best_score=50,best_source='old inferred draft' WHERE id=?", (fn["id"],))
        db.execute("INSERT INTO notes(project_id,function_id,agent_id,text) VALUES(?,?,?,?)",
                   (proj["id"], tail["id"], agent.id, "Original tail observation"))
        db.execute("UPDATE functions SET status='matched',matched_source='existing verified source' WHERE id=?", (other["id"],))
        cfg = net.cfg(proj)
        cfg["function_compilers"] = {head["name"]: {"flags": ["-O2", "-G8"]}, tail["name"]: {"flags": ["-O1", "-G0"]}}
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    before = [dict(net.store.one("SELECT * FROM functions WHERE id=?", fn["id"])) for fn in (head, tail, other)]
    net._syms[proj["id"]] = object()
    net._xrefs[proj["id"]] = object()
    net._ops[proj["id"]] = object()
    net._diffs[(head["id"], "old")] = {}
    result = merge(net, agent)
    merged = net._function(head["name"], "reviewed")
    assert result["status"] == merged["status"] == "open" and merged["id"] == head["id"]
    assert merged["target"] == head["target"] + tail["target"]
    assert json.loads(merged["relocs"]) == [[0, 7, 0x80118008], [20, 7, 0x8011800C]]
    assert ".L80010014:" in merged["asm"] and "endlabel func_80010014" not in merged["asm"]
    assert merged["size"] == 32 and merged["n_insns"] == 8
    assert merged["best_source"] is None and merged["best_score"] is None and merged["attempts"] == 0
    assert merged["matched_source"] is None
    assert net.store.one("SELECT 1 FROM functions WHERE id=?", tail["id"]) is None
    assert not net.store.all("SELECT * FROM attempts")
    assert net.store.one("SELECT function_id FROM notes")["function_id"] == head["id"]
    review = net.store.one("SELECT * FROM psx_boundary_reviews WHERE id=?", result["review"])
    evidence = json.loads(review["evidence"])
    for key, old in zip(("head", "tail"), before):
        expected = dict(old)
        expected["target"] = {"encoding": "hex", "data": old["target"].hex()}
        assert evidence[key] == expected
    assert len(evidence["attempts"]) == 2 and len(evidence["notes"]) == 1
    assert evidence["function_compilers"][tail["name"]] == {"flags": ["-O1", "-G0"]}
    assert tail["name"] not in net.cfg(net.project_row("reviewed"))["function_compilers"]
    assert dict(net.store.one("SELECT * FROM functions WHERE id=?", other["id"])) == before[2]
    assert all(proj["id"] not in cache for cache in (net._syms, net._xrefs, net._ops))
    assert not net._diffs
    assert result["sha256"] == hashlib.sha256(merged["target"]).hexdigest()


@pytest.mark.parametrize("side", ["func_80010000", "func_80010014"])
@pytest.mark.parametrize("guard", ["matched", "claimed"])
def test_matched_or_claimed_ranges_are_preserved(tmp_path, side, guard):
    net, proj, agent = model(tmp_path)
    fn = net._function(side, "reviewed")
    with net.store.tx() as db:
        if guard == "matched":
            db.execute("UPDATE functions SET status='matched',matched_source='verified source' WHERE id=?", (fn["id"],))
        else:
            db.execute("INSERT INTO claims VALUES(?,?,?,?)", (fn["id"], agent.id, time.time(), time.time() + 300))
    before = [dict(row) for row in net.store.all("SELECT * FROM functions ORDER BY id")]
    with pytest.raises(NetworkError, match="matched|claimed"):
        merge(net, agent)
    assert [dict(row) for row in net.store.all("SELECT * FROM functions ORDER BY id")] == before


@pytest.mark.parametrize("change", ["unit", "rom", "ram", "bytes", "listing"])
def test_module_coordinate_and_original_byte_disagreements_are_rejected(tmp_path, change):
    net, proj, agent = model(tmp_path)
    tail = net._function("func_80010014", "reviewed")
    with net.store.tx() as db:
        if change == "unit":
            db.execute("UPDATE functions SET unit='ovl_other' WHERE id=?", (tail["id"],))
        elif change in ("rom", "ram"):
            column = "rom_offset" if change == "rom" else "vram"
            db.execute(f"UPDATE functions SET {column}={column}+4 WHERE id=?", (tail["id"],))
        elif change == "bytes":
            db.execute("UPDATE functions SET target=? WHERE id=?", (bytes(12), tail["id"]))
        else:
            db.execute("UPDATE functions SET asm=replace(asm,'8F82000C','8F820010') WHERE id=?", (tail["id"],))
    before = [dict(row) for row in net.store.all("SELECT * FROM functions ORDER BY id")]
    with pytest.raises(NetworkError, match="adjacent|original|listing"):
        merge(net, agent)
    assert [dict(row) for row in net.store.all("SELECT * FROM functions ORDER BY id")] == before


@pytest.mark.parametrize("reference", ["call", "branch", "relocation", "constant", "data", "context"])
def test_external_entries_and_pointer_references_keep_the_tail(tmp_path, reference):
    net, proj, agent = model(tmp_path)
    other = net._function("func_80010020", "reviewed")
    target = 0x80010018  # include interior references, not just the tail's start
    with net.store.tx() as db:
        if reference == "relocation":
            db.execute("UPDATE functions SET relocs=? WHERE id=?", (json.dumps([[0, 4, target]]), other["id"]))
        elif reference in ("call", "branch", "constant"):
            if reference == "call":
                words = [0x0C000000 | (target >> 2 & 0x3FFFFFF), 0]
            elif reference == "branch":
                words = [0x10000000 | ((target - (other["vram"] + 4)) // 4 & 0xFFFF), 0]
            else:
                words = [0x3C028001, 0x24420018]
            db.execute("UPDATE functions SET target=? WHERE id=?", (struct.pack("<2I", *words), other["id"]))
        elif reference == "context":
            db.execute("INSERT INTO context_versions(project_id,version,header) VALUES(?,?,?)",
                       (proj["id"], 1, "extern int func_80010014(void);"))
        else:
            path = Path(proj["root"]) / "original.bin"
            raw = bytearray(path.read_bytes())
            struct.pack_into("<I", raw, 40, target)
            path.write_bytes(raw)
    with pytest.raises(NetworkError, match="references|points|context"):
        merge(net, agent)
    assert net.store.one("SELECT COUNT(*) n FROM functions")["n"] == 3


def test_merge_requires_explicit_review_reason_and_stale_work_cannot_gain_credit(tmp_path):
    net, proj, agent = model(tmp_path)
    old = [net._function(name, "reviewed") for name in ("func_80010000", "func_80010014")]
    with pytest.raises(NetworkError, match="reviewed evidence"):
        merge_reviewed(net, "reviewed", old[0]["name"], old[1]["name"], agent=agent, reason=" ")
    merge(net, agent)
    for stale in old:
        with pytest.raises(NetworkError, match="target changed"):
            net.try_quietly(agent, proj, stale, "stale draft")
        with pytest.raises(NetworkError, match="target changed"):
            net._record(stale, agent, 0, "stale source", 1, matched=True)
    assert not net.store.all("SELECT * FROM attempts")
    assert not net.store.all("SELECT * FROM functions WHERE status='matched'")
    assert not net.store.all("SELECT * FROM claims")


def test_expired_claims_are_released_before_reviewed_merge(tmp_path):
    net, proj, agent = model(tmp_path)
    head = net._function("func_80010000", "reviewed")
    with net.store.tx() as db:
        db.execute("INSERT INTO claims VALUES(?,?,?,?)", (head["id"], agent.id, time.time() - 10, time.time() - 1))
    merge(net, agent)
    assert not net.store.all("SELECT * FROM claims")
    assert net.store.one("SELECT 1 FROM events WHERE kind='expired'")


def test_console_reviewed_merge_keeps_evidence_and_reports_guard_failures(tmp_path, capsys):
    net, proj, agent = model(tmp_path)
    args = ["--db", str(tmp_path / "app.db"), "psx", "merge", "reviewed", "func_80010000", "func_80010014",
            "--reason", "Reviewed branch reaches its existing return block", "--workspace", str(tmp_path / "projects")]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "open" and report["retired"] == "func_80010014"
    assert net.store.one("SELECT 1 FROM psx_boundary_reviews WHERE id=?", report["review"])
    assert main(args) == 1
    assert "distinct existing" in capsys.readouterr().err


def test_removing_project_also_removes_its_archived_boundary_evidence(tmp_path):
    net, proj, agent = model(tmp_path)
    merge(net, agent)
    assert net.store.one("SELECT COUNT(*) n FROM psx_boundary_reviews")["n"] == 1
    net.remove_project("reviewed")
    assert not net.store.all("SELECT * FROM psx_boundary_reviews")


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_reviewed_merge_restores_original_compiler_function_and_exact_disc(tmp_path, capsys, toolchain):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "flags": ["-O2", "-G0"], "sandbox": "none"}})
    result = compiler.compile_source(cfg, "", "int original(int x) { if (x) return x + 1; return 7; } int peer(void) { return 99; }")
    assert result.ok, result.log
    original, peer = [elfobj.extract_function(result.obj, name) for name in ("original", "peer")]
    assert not original.relocs and not peer.relocs
    exe = bytearray(_resident_exe())
    for at, address in ((0x808, 0x80010500), (0x828, 0x80010600)):
        struct.pack_into("<I", exe, at, 0x0C000000 | (address >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(original.code)] = original.code
    exe[0xE00:0xE00 + len(peer.code)] = peer.code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    agent, _ = net.local_agent("boundary-recovery-test")
    head = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    peer = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010600)
    assert net._autopilot_one(agent, proj, peer["id"], prepare_seed=False) == "match"
    preserved = dict(net._function(peer["name"], slug))
    branch = next((index, word) for index, (word,) in enumerate(struct.iter_unpack("<I", original.code)) if word >> 26 in (4, 5))
    index, word = branch
    immediate = word & 0xFFFF
    if immediate & 0x8000:
        immediate -= 0x10000
    boundary = head["vram"] + (index + 1 + immediate) * 4
    assert head["vram"] < boundary < head["vram"] + head["size"]
    tail_name = f"func_{boundary:08X}"
    command = ["--db", str(tmp_path / "app.db"), "psx"]
    workspace = ["--workspace", str(tmp_path / "projects")]
    assert main(command + ["split", slug, head["name"], "--at", hex(boundary), "--name", tail_name] + workspace) == 0
    assert json.loads(capsys.readouterr().out)["at"] == boundary
    halves = [net._function(name, slug) for name in (head["name"], tail_name)]
    for half in halves:
        net._record(half, agent, None, "uncompiled draft for old extent", net._context(proj["id"], half["unit"])["version"], compiled=False)
    assert main(command + ["merge", slug, head["name"], tail_name, "--reason",
                "Authored compiler function was split at its own conditional return block"] + workspace) == 0
    review = json.loads(capsys.readouterr().out)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    merged = net._function(head["name"], slug)
    assert merged["status"] == "open" and merged["target"] == original.code and merged["attempts"] == 0
    evidence = json.loads(net.store.one("SELECT evidence FROM psx_boundary_reviews WHERE id=?", review["review"])["evidence"])
    assert len(evidence["attempts"]) == 2
    assert dict(net._function(peer["name"], slug)) == preserved
    assert net._autopilot_one(agent, net.project_row(slug), merged["id"], prepare_seed=False) == "match"
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
