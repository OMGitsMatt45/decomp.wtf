"""Reviewed data migration retains prior targets, source and nonrange matches."""

import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import time

import pytest
import yaml

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.network import NetworkError
from decompnet.rom import psx_data, psx_data_review, split
from .test_psx_main_data import fixture


def model(tmp_path):
    image, declaration, module = fixture()
    old = copy.deepcopy(declaration)
    old.pop("main_data")
    old["modules"][0]["copies"].pop()
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, reviewed_layout=old, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
    project = net.project_row(slug)
    at, address = 0x1340, 0x80010B40
    function = split.RomFunction("func_80010B40", address, at, "main", [
        split.AsmLine(at, address, 0x03E00008, "jr", "$ra"),
        split.AsmLine(at + 4, address + 4, 0x24820007, "addiu", "$v0, $a0, 7")], Path(), set())
    with net.store.tx() as db:
        db.execute("INSERT INTO functions(project_id,name,unit,vram,rom_offset,size,n_insns,target,relocs,asm) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (project["id"], function.name, "main", address, at, 8, 2, module[0x500:0x508], "[]", net._asm_source(function)))
        db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?)",
                   (project["id"], function.name, address, 8, "func"))
    # Model an earlier explicit text classification of a resource's leaf bytes.
    config = next(Path(project["root"]).glob("*.yaml"))
    splat = yaml.safe_load(config.read_text())
    subs = next(s for s in splat["segments"] if isinstance(s, dict) and s.get("name") == "main")["subsegments"]
    subs.insert(2, [at, "c", "old_resource_code"])
    subs.insert(3, [at + 8, "data", "old_resource_tail"])
    config.write_text(yaml.safe_dump(splat, sort_keys=False))
    agent, _ = net.local_agent("authored-data-review")
    fn = net._function(function.name, slug)
    return net, slug, declaration, agent, fn


def migrate(net, slug, declaration, agent, **kwargs):
    return psx_data_review.migrate(net, slug, declaration, agent=agent,
        reason="Original loader treats this hash-bound resource envelope as data; identical loose bytes own the executable source", **kwargs)


def rows(net):
    return [dict(row) for row in net.store.all("SELECT * FROM functions ORDER BY id")]


def test_data_review_archives_all_prior_work_and_preserves_other_rows_and_profiles(tmp_path, monkeypatch):
    net, slug, declaration, agent, fn = model(tmp_path)
    project, cfg = net.project_row(slug), net.cfg(net.project_row(slug))
    other = net.store.one("SELECT * FROM functions WHERE project_id=? AND unit!='main' ORDER BY id LIMIT 1", project["id"])
    with net.store.tx() as db:
        db.execute("UPDATE functions SET status='matched',matched_source='authored archived C',best_source='authored archived C',best_score=0,attempts=1 WHERE id=?", (fn["id"],))
        db.execute("INSERT INTO attempts(function_id,agent_id,score,source,context_version) VALUES(?,?,?,?,?)", (fn["id"], agent.id, 0, "authored archived C", 1))
        db.execute("INSERT INTO notes(project_id,function_id,agent_id,text) VALUES(?,?,?,?)", (project["id"], fn["id"], agent.id, "Original observation"))
        db.execute("INSERT INTO twin_misses(function_id,source_hash,project_id,why) VALUES(?,?,?,?)", (fn["id"], "old", project["id"], "earlier mismatch"))
        db.execute("UPDATE functions SET status='matched',matched_source='unaffected retained C',best_source='unaffected retained C',best_score=0 WHERE id=?", (other["id"],))
        cfg["function_compilers"] = {fn["name"]: {"flags": ["-O1", "-G0"]}, other["name"]: {"flags": ["-O2", "-G8"]}}
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), project["id"]))
    before, config = rows(net), next(Path(project["root"]).glob("*.yaml"))
    original_splat = config.read_bytes()
    layout_path = Path(project["root"]) / "psx-layout.json"
    original_layout = layout_path.read_bytes()
    original_files = {path: path.read_bytes() for path in Path(project["root"]).iterdir() if path.suffix in (".exe", ".iso", ".bin")}
    # Another worker commits an unrelated verified profile after our read.
    original_classify = psx_data.classify
    def interleave(splat, definitions):
        original_classify(splat, definitions)
        net._update_cfg(slug, lambda c: c["function_compilers"].update({"another_function": {"flags": ["-O0", "-G0"]}}))
    monkeypatch.setattr(psx_data, "classify", interleave)
    result = migrate(net, slug, declaration, agent, transfer=False)
    assert result["archived"] == [fn["name"]] and not result["transferred"]
    assert rows(net) == [row for row in before if row["id"] != fn["id"]]
    review = json.loads(net.store.one("SELECT evidence FROM psx_data_reviews WHERE id=?", result["review"])["evidence"])
    saved = review["targets"][0]
    expected = next(row for row in before if row["id"] == fn["id"])
    expected["target"] = {"encoding": "hex", "data": expected["target"].hex()}
    assert saved["function"] == expected
    assert saved["compiler"]["flags"] == ["-O1", "-G0"]
    assert len(saved["attempts"]) == len(saved["notes"]) == len(saved["twin_misses"]) == len(saved["symbols"]) == 1
    assert Path(result["evidence"]).is_file()
    assert json.loads(Path(result["evidence"]).read_text()) == review
    assert review["original_splat"].encode() == original_splat
    assert review["original_layout"].encode() == original_layout
    assert json.loads(layout_path.read_text()) == declaration
    assert review["original_config"]["function_compilers"][fn["name"]] == {"flags": ["-O1", "-G0"]}
    latest = net.cfg(net.project_row(slug))
    assert set(latest["function_compilers"]) == {other["name"], "another_function"}
    assert latest["psx_modules"]["main"] == {**cfg["psx_modules"]["main"], "data_ranges": declaration["main_data"]}
    assert net.store.one("SELECT * FROM symbols WHERE name=?", fn["name"])["kind"] == "data"
    assert all(path.read_bytes() == original for path, original in original_files.items())
    assert not net.store.all("SELECT * FROM attempts WHERE function_id=?", fn["id"])
    assert not net.store.all("SELECT * FROM notes WHERE function_id=?", fn["id"])
    assert not net.store.all("SELECT * FROM twin_misses WHERE function_id=?", fn["id"])
    net.remove_project(slug)
    assert not net.store.all("SELECT * FROM psx_data_reviews")


def test_layout_write_failure_rolls_back_target_archival_and_splat_changes(tmp_path, monkeypatch):
    net, slug, declaration, agent, _ = model(tmp_path)
    project = net.project_row(slug)
    root = Path(project["root"])
    config = next(root.glob("*.yaml"))
    before = rows(net)
    original_splat = config.read_bytes()
    original_layout = (root / "psx-layout.json").read_bytes()
    write = psx_data_review._write
    def fail_layout(path, data):
        if path.name == "psx-layout.json":
            raise OSError("authored layout write failure")
        return write(path, data)
    monkeypatch.setattr(psx_data_review, "_write", fail_layout)
    with pytest.raises(OSError, match="authored layout write failure"):
        migrate(net, slug, declaration, agent, transfer=False)
    assert rows(net) == before
    assert net.project_row(slug)["config"] == project["config"]
    assert config.read_bytes() == original_splat
    assert (root / "psx-layout.json").read_bytes() == original_layout


@pytest.mark.parametrize("change", ["claimed", "crossing", "target", "gp", "code-end", "copies", "hash"])
def test_review_rejects_unowned_stale_or_changed_classifications_without_losing_source(tmp_path, change):
    net, slug, declaration, agent, fn = model(tmp_path)
    if change == "claimed":
        net.claim_row(agent, slug, fn["name"])
    elif change in ("crossing", "target"):
        with net.store.tx() as db:
            if change == "crossing":
                db.execute("UPDATE functions SET rom_offset=? WHERE id=?", (declaration["main_data"][0]["offset"] - 4, fn["id"]))
            else:
                db.execute("UPDATE functions SET target=? WHERE id=?", (bytes(8), fn["id"]))
    elif change == "gp": declaration["modules"][0]["gp"] = 0x80188000
    elif change == "code-end": declaration["modules"][0]["code_end"] += 4
    elif change == "copies": declaration["modules"][0]["copies"].pop(0)
    elif change == "hash": declaration["main_data"][0]["sha256"] = "0" * 64
    before, cfg = rows(net), net.cfg(net.project_row(slug))
    config = next(Path(net.project_row(slug)["root"]).glob("*.yaml"))
    old_text = config.read_bytes()
    with pytest.raises((NetworkError, ValueError), match="claimed|edge|original|canonical|storage copy|SHA-256"):
        migrate(net, slug, declaration, agent, transfer=False)
    assert rows(net) == before and net.cfg(net.project_row(slug)) == cfg
    assert config.read_bytes() == old_text


@pytest.mark.parametrize("word", [0x0C000000 | (0x80010600 >> 2 & 0x3FFFFFF), 0x45010000 | ((0x80010600 - 0x80010004) // 4 & 0xFFFF)])
@pytest.mark.parametrize("module", ["main", "ovl_shared"])
def test_any_executable_module_control_entry_keeps_boot_resources_executable(word, module):
    function = split.RomFunction("caller", 0x80010000, 0x800, module, [
        split.AsmLine(0x800, 0x80010000, word, "branch", "")], Path(), set())
    with pytest.raises(ValueError, match="control flow enters"):
        psx_data.reject_control_entries([function], [{"offset": 0xE00, "size": 0x100}], 0x80010000)


def test_data_review_console_reports_archival_evidence(tmp_path, capsys):
    net, slug, declaration, _, fn = model(tmp_path)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(declaration))
    assert main(["--db", str(tmp_path / "app.db"), "psx", "data-review", slug,
        "--workspace", str(tmp_path / "projects"), "--layout", str(path), "--no-transfer", "--reason", "Reviewed resource loader and original-byte identity"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["archived"] == [fn["name"]] and Path(result["evidence"]).exists()


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers")
def test_genuine_wrong_base_source_transfers_only_after_full_canonical_judge_and_clean_export(tmp_path, monkeypatch):
    net, slug, declaration, agent, fn = model(tmp_path)
    monkeypatch.setattr(net, "on_match", lambda *_: None)
    source = f"int {fn['name']}(int x) {{ return x + 7; }}"
    assert net.attempt(agent, fn["name"], source, slug)["matched"]
    archived = dict(net._function(fn["name"], slug))
    result = migrate(net, slug, declaration, agent)
    target = net.store.one("SELECT * FROM functions WHERE unit!='main' AND vram=?", 0x80180500)
    assert result["transferred"] == [target["name"]] and target["status"] == "matched"
    assert target["matched_source"] == source.replace(fn["name"], target["name"])
    assert archived["matched_source"] in Path(result["evidence"]).read_text()
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    metadata = json.loads((Path(exported["path"]) / "build.json").read_text())
    assert all(f["name"] != fn["name"] for f in metadata["functions"])
    assert metadata["symbols"][fn["name"]] == fn["vram"]
