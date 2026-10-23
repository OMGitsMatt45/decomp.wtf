"""One source tree/command for all discs, with independently verified shared source."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import zipfile

import pytest
from starlette.testclient import TestClient

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.cli import main
from decompnet.network import NetworkError
from .test_overlays import _iso, _resident_exe

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and binutils")


def fixtures(root, toolchain="gcc-2.7.2-psx"):
    cfg = project.compiler_config(root, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c", "sandbox": "none"}})
    compiled = compiler.compile_source(cfg, "", "int disc_value(int x) { return x + 7; }")
    assert compiled.ok, compiled.log
    fn = elfobj.extract_function(compiled.obj, "disc_value")
    assert fn and not fn.relocs
    exe = bytearray(_resident_exe())
    address = 0x80010500
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | ((address >> 2) & 0x03FFFFFF))
    exe[0xD00:0xD00 + len(fn.code)] = fn.code
    return [_iso({"SYSTEM.CNF": b"BOOT = cdrom:\\GAME.EXE;1\n", "GAME.EXE": bytes(exe),
                  "DISC.ID": bytes([number]), "DATA.BIN": bytes([number]) * 2000}) for number in (1, 2)]


def imported(tmp_path, recover=False):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects with spaces")
    originals = fixtures(tmp_path)
    slugs = []
    for data, toolchain in zip(originals, ("gcc-2.7.2-psx", "gcc-2.8.1-psx")):
        slug = net.import_rom(data, toolchain=toolchain, confirmed=True, log=lambda *_: None)
        slugs.append(slug)
        net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
        if recover:
            row = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", net.project_row(slug)["id"], 0x80010500)
            agent, _ = net.local_agent("disc-" + slug)
            result = net.attempt(agent, row["name"], f"int {row['name']}(int x) {{ return x + 7; }}", slug)
            assert result["matched"], result
    return net, slugs, originals


def test_one_project_builds_both_discs_and_shares_verified_cpp(tmp_path):
    net, slugs, originals = imported(tmp_path, recover=True)
    overview = net.set_psx_disc_set(slugs[0], slugs, "Original two-disc game")
    assert overview["disc_set"]["title"] == "Original two-disc game"
    assert net.overview(slugs[1])["disc_set"] == overview["disc_set"]
    result = net.export_rom(slugs[1], log=lambda *_: None)
    assert result["identical"] and result["scope"] == "disc-set", result
    assert result["matched"] == 2 and result["shared_sources"] == 1
    tree = Path(result["path"])
    manifest = json.loads((tree / "disc-set.json").read_text())
    archive = Path(result["archive"])
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert len([name for name in zipped.namelist() if "/shared/src/" in name]) == 1
        for disc, original in zip(manifest["discs"], originals):
            assert zipped.read("source-set/" + disc["output"]) == original
        assert not any("/discs/disc-1/build/" in name for name in zipped.namelist())
    assert len(list((tree / "shared/src").glob("*.cpp"))) == 1
    for disc, original in zip(manifest["discs"], originals):
        assert (tree / disc["output"]).read_bytes() == original
        assert not list((tree / disc["project"] / "src").rglob("*.cpp"))
        for generated in ("asm", "assets", "build"):
            shutil.rmtree(tree / disc["project"] / generated, ignore_errors=True)
        (tree / disc["project"] / "baserom.exe").unlink()
    shutil.rmtree(tree / "build")

    def run():
        return subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=180)

    rebuilt = run()
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    shared = next((tree / "shared/src").glob("*.cpp"))
    source = shared.read_text()
    shared.write_text(source.replace("+ 7", "+ 8"))
    assert run().returncode != 0
    assert not list((tree / "build").glob("disc-*.iso"))
    assert not (tree / "build/disc-set-result.json").exists()
    shared.write_text(source)
    assert run().returncode == 0
    # Failure on disc 2 must also remove the previous good disc 1 aggregate output.
    disc = manifest["discs"][1]
    child = json.loads((tree / disc["project"] / "build.json").read_text())
    (tree / disc["project"] / child["disc"]["image"]).write_bytes(b"corrupt second disc")
    assert run().returncode != 0
    assert not list((tree / "build").glob("disc-*.iso"))


def test_group_validation_order_identity_missing_members_and_ungroup(tmp_path):
    net, slugs, _ = imported(tmp_path)
    for projects, title in [([slugs[0]], "Game"), ([slugs[0], slugs[0]], "Game"), (slugs, ""), (slugs, "x\ny")]:
        with pytest.raises(NetworkError):
            net.set_psx_disc_set(slugs[0], projects, title)
    net.set_psx_disc_set(slugs[0], slugs[::-1], "Ordered game")
    assert net.overview(slugs[0])["disc_set"]["discs"][0]["slug"] == slugs[1]
    with pytest.raises(NetworkError, match="another game"):
        net.set_psx_disc_set(slugs[0], slugs, "Different order")
    net.set_psx_disc_set(slugs[1], None)
    assert all(net.overview(slug)["disc_set"] is None for slug in slugs)
    net.set_psx_disc_set(slugs[0], slugs, "Game")
    net.remove_project(slugs[1])
    with pytest.raises(NetworkError):
        net.export_rom(slugs[0], log=lambda *_: None)
    net.set_psx_disc_set(slugs[0], None)
    assert net.overview(slugs[0])["disc_set"] is None


def test_cli_combines_and_exports_one_game(tmp_path, capsys):
    net, slugs, originals = imported(tmp_path)
    base = ["--db", str(tmp_path / "app.db"), "psx"]
    workspace = str(net.workspace)
    assert main([*base, "combine", *slugs, "--title", "Two-disc game", "--workspace", workspace]) == 0
    assert len(json.loads(capsys.readouterr().out)["disc_set"]["discs"]) == 2
    assert main([*base, "export", slugs[0], "--workspace", workspace]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "disc-set" and result["identical"]
    for disc, original in zip(result["discs"], originals):
        assert (Path(result["path"]) / disc["output"]).read_bytes() == original
    assert main([*base, "ungroup", slugs[0], "--workspace", workspace]) == 0
    assert json.loads(capsys.readouterr().out)["disc_set"] is None


def test_browser_disc_set_security_configuration_and_export(tmp_path):
    net, slugs, _ = imported(tmp_path)
    mcp, _, security = build(net, tmp_path / "home", 6499, "test-secret")
    app = mcp.streamable_http_app(transport_security=security, host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:6499") as client:
        body = {"slug": slugs[0], "projects": slugs, "title": "Browser game"}
        assert client.post("/api/psx/disc-set", json=body).status_code == 401
        client.cookies.set("decomp_live", "test-secret")
        assert client.post("/api/psx/disc-set", json=body).status_code == 403
        response = client.post("/api/psx/disc-set", json=body, headers={"X-Decomp": "1"})
        assert response.status_code == 200 and len(response.json()["disc_set"]["discs"]) == 2
        invalid = client.post("/api/psx/disc-set", json=dict(body, projects=slugs[:1]), headers={"X-Decomp": "1"})
        assert invalid.status_code == 400
        export = client.post("/api/export", json={"slug": slugs[1]}, headers={"X-Decomp": "1"})
        assert export.status_code == 200
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = client.get("/api/job", params={"id": export.json()["job"]}).json()
            if job["state"] != "running":
                break
            time.sleep(0.02)
        assert job["state"] == "done", job
        archive = client.get("/api/export/archive", params={"slug": slugs[0]})
        assert archive.status_code == 200 and archive.content[:2] == b"PK"
        client.cookies.clear()
        assert client.get("/api/export/archive", params={"slug": slugs[0]}).status_code == 401
        client.cookies.set("decomp_live", "test-secret")
        cleared = client.post("/api/psx/disc-set", json={"slug": slugs[1], "projects": None}, headers={"X-Decomp": "1"})
        assert cleared.status_code == 200 and cleared.json()["disc_set"] is None
        assert client.get("/api/export/archive", params={"slug": slugs[0]}).status_code != 200
