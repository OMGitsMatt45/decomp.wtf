"""GB/GBC GUI and agent workflow, using the actual pinned native assembler/linker."""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from decompnet import seeds
from decompnet.app import agents, tools
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build as build_server
from decompnet.compiler import CompilerConfig, compile_source
from decompnet.network import NetworkError
from decompnet.rom import detect, gb

from .test_gb import cartridge, rgbds  # noqa: F401


@pytest.fixture(params=[False, True], ids=["gb", "gbc"])
def project(tmp_path, request, rgbds, monkeypatch):
    def no_c(*args, **kwargs):
        pytest.fail("an assembly project entered C/m2c or automatic twin verification")
    monkeypatch.setattr(seeds, "generate_from_asm", no_c)
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    monkeypatch.setattr(net.twins, "after_match", no_c)
    # Expose BANK(label) and an unresolved ROM0->ROMX call for strict bank tests.
    raw = bytearray(cartridge(cgb=request.param))
    raw[0x150:0x156] = bytes.fromhex("3e 02 cd 00 40 c9")
    slug = net.import_rom(bytes(raw), confirmed=True, log=lambda _: None)
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    # This managed container cannot create user namespaces; native execution is
    # tested here. Linux's existing sandbox tests cover the common runner.
    cfg["compiler"]["sandbox"] = "none"
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    agent, _ = net.local_agent("reviewer")
    return net, slug, agent, bytes(raw)


def add_banks(net, slug, agent):
    for bank in (1, 2):
        result = net.split_function(agent, slug, "func_00000100", f"{bank:02x}:4000", f"bank_{bank}")
        assert result.startswith("✅"), result


def test_import_detection_progress_and_ownership(project):
    net, slug, agent, raw = project
    picked = detect.identify(raw)
    assert picked.platform == net.overview(slug)["platform"]
    assert net.import_rom(raw, confirmed=True, log=lambda _: None) == slug
    with pytest.raises(NetworkError, match="legally obtained"):
        net.import_rom(raw)
    with pytest.raises(NetworkError, match="RGBDS"):
        net.import_rom(raw, confirmed=True, toolchain="agbcc")
    overview = net.overview(slug)
    assert overview["compiler"]["language"] == "asm" and overview["exportable"]
    assert overview["progress_kind"] == "assembly" and overview["matched_bytes"] == 0
    assert overview["bytes"] == len(raw) and overview["assembly_bytes"] == 10
    assert overview["base_bytes"] == len(raw) - 10
    assert "RGBDS SM83 assembly" in tools.project_info(net, slug)
    assert "retained from the base ROM" in tools.project_info(net, slug)
    assert net.reader(net.project_row(slug))(gb.Address(2, 0x4000).key, 3) == raw[0x8000:0x8003]


def test_single_claim_assembly_prompt_and_matching(project):
    net, slug, agent, _ = project
    brief = net.claim_many(agent, slug, 4)
    assert "context.inc" in brief and "RGBDS" in brief and "one complete" in brief
    assert "write C for" not in brief and "m2c:" not in brief
    claims = net.store.all("SELECT * FROM claims")
    assert len(claims) == 1
    row = net.store.one("SELECT * FROM functions WHERE id=?", claims[0]["function_id"])
    assert net.get_context(slug).startswith("; context.inc")
    source = row["seed"] + "\n; reviewed entry and branch\n"
    result = net.attempt(agent, row["name"], source, slug)
    assert result["matched"] and result["score"] == 0, result
    assert not net.store.all("SELECT * FROM claims")
    detail = net.function_detail(slug, row["name"])
    assert detail["language"] == "asm" and detail["bank"] == 0 and detail["source_kind"] == "matched"
    assert net.function_diff(slug, row["name"])["percent"] == 100
    with pytest.raises(NetworkError, match="review"):
        net.start_autopilot(slug)
    with pytest.raises(NetworkError, match="one RGBDS"):
        net.attempt_many(agent, [row["name"]], source, slug)
    manager = agents.Manager.__new__(agents.Manager)
    manager.net = net
    prompt = manager.prompt(SimpleNamespace(slug=slug, options={"per_session": 2}))
    assert "RGBDS" in prompt and "reviewing GB/GBC" in prompt
    assert "Your job: turn functions" not in prompt and "KMC" not in prompt


def test_same_cpu_in_different_banks_and_external_bank_symbols(project):
    net, slug, agent, _ = project
    add_banks(net, slug, agent)
    one, two = net._function("01:4000", slug), net._function("02:4000", slug)
    assert one["vram"] != two["vram"] and one["rom_offset"] != two["rom_offset"]
    assert one["name"] == "bank_1" and two["name"] == "bank_2"
    target = net._function("func_00000150", slug)
    source = target["seed"].replace("$02", "BANK(bank_2)").replace("$4000", "bank_2")
    wrong = net.attempt(agent, target["name"], source.replace("BANK(bank_2)", "BANK(bank_1)"), slug)
    assert not wrong["matched"] and wrong["score"] > 0
    right = net.attempt(agent, target["name"], source, slug)
    assert right["matched"], right
    assert net.read_data(slug, "02:4000", 4).find("22") >= 0
    assert net.rename_symbol(agent, slug, "bank_2", "selected_bank").startswith("✅")
    assert "BANK(selected_bank)" in net._function(target["name"], slug)["matched_source"]
    assert net.function_diff(slug, target["name"])["score"] == 0


@pytest.mark.parametrize("case", ["operand", "bank", "address", "size", "extra_section", "ram_section", "missing_label", "undefined", "bad_source"])
def test_bad_candidates_never_receive_credit(project, case):
    net, slug, agent, _ = project
    add_banks(net, slug, agent)
    row = net._function("bank_2", slug)
    source = row["seed"]
    source = {
        "operand": source.replace("$22", "$23"),
        "bank": source.replace("BANK[$2]", "BANK[$1]"),
        "address": source.replace("$4000", "$4001").replace("$4003", "$4004"),
        "size": source.replace("ret", "ret\n    nop"),
        "extra_section": source + '\nSECTION "extra", ROM0[$0300]\n    db $42\n',
        "ram_section": source + '\nSECTION "scratch", HRAM[$ff80]\n    ds 1\n',
        "missing_label": source.replace("bank_2", "other_label"),
        "undefined": source.replace("$22", "missing_symbol"),
        "bad_source": "this is invalid assembly",
    }[case]
    result = net.attempt(agent, row["name"], source, slug)
    assert not result["matched"] and result["score"] != 0, result
    assert net._function(row["name"], slug)["status"] != "matched"
    if case in ("bank", "address", "extra_section", "ram_section"):
        assert "exactly one ROM section" in result["text"]
        assert "exactly one ROM section" in net.function_diff(slug, row["name"])["error"]


@pytest.mark.parametrize("source", ['INCBIN "/secret"', 'INCLUDE "file"', 'DEF x EQUS "IN"',
                                   'MACRO hidden\nENDM', r'IN\1CBIN "file"', '{"INCBIN"}',
                                   'SECTION ";", ROM0 : INCBIN "file"'])
def test_assembly_file_access_and_generated_directives_rejected(source):
    result = compile_source(CompilerConfig(["must-not-run"], language="asm"), "", source)
    assert not result.ok and "self-contained" in result.log
    result = compile_source(CompilerConfig(["must-not-run"], language="asm"), source, "nop")
    assert not result.ok and "self-contained" in result.log


def test_context_edits_regress_saved_matches_and_export_separate_units(project, rgbds, tmp_path, monkeypatch):
    net, slug, agent, raw = project
    add_banks(net, slug, agent)
    assert net.edit_context(agent, slug, "", "DEF VALUE_0 EQU $02\nDEF VALUE_1 EQU $11\nDEF VALUE_2 EQU $22",
                            "shared numeric constants").startswith("✅")
    for name, value, symbol in (("func_00000150", "$02", "VALUE_0"), ("bank_1", "$11", "VALUE_1"), ("bank_2", "$22", "VALUE_2")):
        row = net._function(name, slug)
        source = row["seed"].replace(value.lower(), symbol) + "\n; reviewed and annotated\n"
        result = net.attempt(agent, name, source, slug)
        assert result["matched"], result
    rejected = net.edit_context(agent, slug, "DEF VALUE_2 EQU $22", "DEF VALUE_2 EQU $23", "wrong immediate")
    assert "REJECTED" in rejected
    if sys.platform == "win32":
        monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32"))
        assert (rgbds / "rgbasm.exe").read_bytes()[:2] == b"MZ"
    else:
        monkeypatch.setenv("PATH", "")
    first = net.export_rom(slug, log=lambda _: None)
    first["path"] = Path(first["path"])
    assert first["identical"] and first["matched"] == 3 and first["language"] == "asm"
    assert any("reviewed and annotated" in p.read_text() for p in first["path"].glob("src/*.asm"))
    (first["path"] / "README.md").write_text("local export edits\n")
    second = net.export_rom(slug, log=lambda _: None)
    second["path"] = Path(second["path"])
    assert second["path"] != first["path"] and (first["path"] / "README.md").read_text() == "local export edits\n"
    extension = ".gbc" if net.overview(slug)["platform"] == "gbc" else ".gb"
    result = subprocess.run([sys.executable, "-I", "-S", str(second["path"] / "build.py"),
                             str(Path(net.project_row(slug)["root"]) / ("rom" + extension)), "--rgbds", str(rgbds)],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(json.loads(result.stdout)["output"]).read_bytes() == raw


def test_split_boundaries_rename_and_verified_range_protection(project):
    net, slug, agent, _ = project
    with pytest.raises(NetworkError, match="operand"):
        net.split_function(agent, slug, "func_00000100", "00:0102", "bad")
    assert net.split_function(agent, slug, "func_00000100", "00:0101", "entry_jump").startswith("✅")
    head = net._function("func_00000100", slug)
    assert head["size"] == 1 and net.attempt(agent, head["name"], head["seed"], slug)["matched"]
    assert net.rename_symbol(agent, slug, "entry_jump", "start_game").startswith("✅")
    row = net._function("start_game", slug)
    # The source from the GUI must use the renamed label, not the stale seed.
    detail = net.function_detail(slug, "start_game")
    result = net.attempt(agent, "start_game", detail["source"], slug)
    assert result["matched"], result
    assert net.overview(slug)["matched_bytes"] == row["size"] + 1
    assert net.overview(slug)["matched_bytes"] < net.overview(slug)["bytes"]
    assert net.split_function(agent, slug, "start_game", "02:4000", "extra").startswith("✅")
    with pytest.raises(NetworkError, match="RGBDS"):
        net.set_compiler(slug, "agbcc")
    net.set_compiler(slug, "rgbds")
    assert net._function("extra", slug)["seed"]


def test_browser_header_detection_matches_backend(tmp_path):
    node = shutil.which("node")
    if not node:
        if os.environ.get("DECOMP_TEST_GB_ASM") == "1":
            pytest.fail("the required browser parser check needs Node on the CI runner")
        pytest.skip("browser parser check needs Node")
    javascript = (Path(__file__).resolve().parents[1] / "src/decompnet/app/static/app.js").read_text(encoding="utf-8")
    parser = javascript[javascript.index("function identifyHead("):javascript.index("function notSupported(")]
    cases = [cartridge(), cartridge(cgb=True), cartridge(banks=72), cartridge()[:-1]]
    wrong_header = bytearray(cases[0]); wrong_header[0x14D] ^= 1
    cases.append(bytes(wrong_header))
    script = tmp_path / "browser-parser.cjs"
    script.write_text(parser + '\nconst cases = JSON.parse(require("fs").readFileSync(0, "utf8"));\n'
                      'console.log(JSON.stringify(cases.map(c => identifyHead(new Uint8Array(Buffer.from(c.head,"base64")), '
                      '{name:"homebrew.gb",size:c.size}))));\n', encoding="utf-8")
    result = subprocess.run([node, str(script)], text=True, capture_output=True,
                            input=json.dumps([{"head": base64.b64encode(raw[:0x150]).decode(), "size": len(raw)} for raw in cases]), timeout=30)
    assert result.returncode == 0, result.stderr
    picked = json.loads(result.stdout)
    assert [p["platform"] if p else None for p in picked] == ["gb", "gbc", "gb", None, None]
    assert picked[2]["banks"] == 72


def test_large_code_regions_fit_the_submission_limit(tmp_path, rgbds):
    raw = bytearray(cartridge())
    raw[0x150:0x2150] = b"\0" * 0x2000
    raw[0x2150] = 0xC9
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    slug = net.import_rom(bytes(raw), confirmed=True, log=lambda _: None)
    rows = net.store.all("SELECT size,seed FROM functions")
    assert sum(r["size"] for r in rows) == 0x2005
    assert all(r["size"] <= 2048 and len(r["seed"].encode()) < 65536 for r in rows)


def test_claims_and_splits_respect_another_agents_lease(project):
    net, slug, agent, _ = project
    other, _ = net.local_agent("other-reviewer")
    row = net._function("func_00000100", slug)
    net.claim(agent, slug, row["name"])
    with pytest.raises(NetworkError, match="claimed by"):
        net.attempt(other, row["name"], row["seed"], slug)
    with pytest.raises(NetworkError, match="claimed by"):
        net.split_function(other, slug, row["name"], "00:0101", "stolen")


def test_export_reports_and_replaces_a_broken_saved_match(project):
    net, slug, agent, raw = project
    add_banks(net, slug, agent)
    row = net._function("bank_2", slug)
    assert net.attempt(agent, row["name"], row["seed"], slug)["matched"]
    with net.store.tx() as db:
        db.execute("UPDATE functions SET matched_source=? WHERE id=?", (row["seed"].replace("$22", "$23"), row["id"]))
    log = []
    result = net.export_rom(slug, log=log.append)
    assert result["fallback"] == ["bank_2"] and result["matched"] == 0 and result["identical"]
    assert any("no longer verifies" in line for line in log)
    files = list((Path(result["path"]) / "build").glob("*.gb*"))
    assert len(files) == 1 and files[0].read_bytes() == raw


def test_invalid_header_rejected_before_browser_project_created(tmp_path):
    data = bytearray(cartridge())
    data[0x14D] ^= 1
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        net.import_rom(bytes(data), confirmed=True)
    assert not net.store.all("SELECT * FROM projects")


def test_browser_upload_claim_try_and_export(project):
    net, slug, agent, raw = project
    internal = net.workspace / ".decomp"
    internal.mkdir()
    mcp, manager, security = build_server(net, internal, 6499, "gb-test")
    client = TestClient(mcp.streamable_http_app(transport_security=security, host="127.0.0.1"),
                        base_url="http://127.0.0.1:6499")
    client.cookies.set("decomp_live", "gb-test")
    headers = {"X-Decomp": "1"}
    def follow(response):
        assert response.status_code == 200, response.text
        job = response.json()["job"]
        for _ in range(200):
            status = client.get("/api/job", params={"id": job}).json()
            if status["state"] != "running":
                assert status["state"] == "done", status
                return status["result"]
            time.sleep(0.01)
        pytest.fail("browser job did not finish")
    assert client.post("/api/import?name=test.gb", content=raw, headers=headers).status_code == 400
    imported = follow(client.post("/api/import?name=test.gb&confirmed=1&toolchain=rgbds", content=raw, headers=headers))
    assert imported["slug"] == slug
    rows = net.store.all("SELECT * FROM functions ORDER BY vram")
    row = rows[0]
    result = client.post("/api/try", json={"slug": slug, "name": row["name"], "source": row["seed"]}, headers=headers)
    assert result.status_code == 200 and result.json()["matched"], result.text
    detail = client.get("/api/function", params={"slug": slug, "name": row["name"]}).json()
    assert detail["bank"] == 0 and detail["language"] == "asm"
    exported = follow(client.post("/api/export", json={"slug": slug}, headers=headers))
    assert exported["identical"] and exported["language"] == "asm"
    manager.stop()
