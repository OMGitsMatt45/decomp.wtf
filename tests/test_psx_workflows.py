"""PS1 browser/CLI disc workflows and source-built mutually exclusive overlays."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

import pytest
from starlette.testclient import TestClient

from decompnet import compiler, elfobj, project, toolchains
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.cli import main
from decompnet.network import NetworkError
from .test_overlays import _iso, _overlay, _resident_exe
from .test_psx_disc import fixture

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and binutils")


@pytest.mark.parametrize("tcid", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_two_overlays_match_their_own_cpp_and_rebuild_from_clean_sources(tmp_path, tcid):
    assert all(toolchains.installed(t) is not None for t in (tcid, "binutils-mips"))
    base, count = 0x80180000, 40
    address = base + 64 + count * 32
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": tcid, "language": "c", "sandbox": "none"}})

    def module(value):
        result = compiler.compile_source(cfg, "", f"int disc_value(int x) {{ return x + {value}; }}")
        assert result.ok, result.log
        fn = elfobj.extract_function(result.obj, "disc_value")
        assert fn and not fn.relocs
        calls = bytearray(_overlay(base + 64, count))
        struct.pack_into("<I", calls, 8, 0x0C000000 | ((address >> 2) & 0x03FFFFFF))
        return bytes(64) + calls + fn.code

    original = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\DEMOQ_PS1.EXE;1\n", "DEMOQ_PS1.EXE": _resident_exe(),
                     "BATTLE.BIN": module(7), "FIELD.BIN": module(9), "DATA.BIN": b"unrelated file"})
    work = tmp_path / "PS1 project with spaces"
    work.mkdir()
    net = RomNetwork(work / "app.db", work / "projects")
    slug = net.import_rom(original, toolchain=tcid, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    functions = net.store.all("SELECT * FROM functions WHERE project_id=? AND vram=? ORDER BY unit", proj["id"], address)
    assert len(functions) == 2
    first, _ = net.local_agent("battle-agent")
    second, _ = net.local_agent("field-agent")
    for agent, fn, value in zip((first, second), functions, (7, 9)):
        assert net.claim_row(agent, slug, fn["name"])["id"] == fn["id"]
        assert net.reader(proj, fn)(address, fn["size"]) == elfobj.extract_function(
            compiler.compile_source(cfg, "", f"int disc_value(int x) {{ return x + {value}; }}").obj, "disc_value").code
        source = f"int {fn['name']}(int x) {{ return x + {value}; }}"
        wrong = net.attempt(agent, fn["name"], source.replace(f"+ {value}", "+ 11"), slug)
        assert not wrong["matched"]
        result = net.attempt(agent, fn["name"], source, slug)
        assert result["matched"], result
    with pytest.raises(NetworkError, match="module-qualified"):
        net._function(hex(address), slug)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["scope"] == "disc" and result["matched"] == 2, result
    assert not result["fallback"]
    tree = Path(result["path"])
    manifest = json.loads((tree / "build.json").read_text())
    output = tree / manifest["disc"]["output"]
    assert output.read_bytes() == original
    # No generated target, assembly, assets or previous object may carry this rebuild.
    for name in ("asm", "assets", "build"):
        shutil.rmtree(tree / name, ignore_errors=True)
    (tree / manifest["image"]).unlink()

    def run():
        return subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=120)

    built = run()
    assert built.returncode == 0, built.stdout + built.stderr
    assert output.read_bytes() == original
    source = next((tree / "src").rglob("*.cpp"))
    before = source.read_text()
    source.write_text(before.replace("+ 7", "+ 11").replace("+ 9", "+ 11"))
    failed = run()
    assert failed.returncode != 0 and "not identical" in failed.stdout + failed.stderr
    assert not output.exists()
    source.write_text(before)
    assert run().returncode == 0
    disc_path = tree / manifest["disc"]["image"]
    disc_path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    failed = run()
    assert failed.returncode != 0 and "original PS1 disc differs" in failed.stdout + failed.stderr
    assert not output.exists()


@pytest.mark.parametrize("size,skip", [(2352, 16), (2352, 24), (2448, 24)])
def test_raw_disc_exports_rebuild_the_complete_image(tmp_path, size, skip):
    original = fixture(size, skip)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["scope"] == "disc", result
    assert (Path(result["path"]) / result["disc"]["output"]).read_bytes() == original


def test_cli_inventory_import_dedup_and_export(tmp_path, capsys):
    original = fixture()
    path = tmp_path / "my disc.iso"
    path.write_bytes(original)
    base = ["--db", str(tmp_path / "app.db"), "psx"]
    assert main([*base, "inspect", str(path)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["disc"]["supported"] and len(info["overlays"]) == 2
    workspace = str(tmp_path / "projects")
    command = [*base, "import", str(path), "--workspace", workspace, "--own-copy"]
    assert main(command) == 0
    slug = json.loads(capsys.readouterr().out)["project"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["project"] == slug
    # Two discs share an executable but carry different game resources.
    # They must retain distinct projects and independently reconstruct both.
    second_disc = bytearray(original)
    music = next(f for f in info["disc"]["files"] if f["path"] == "MUSIC.VAB")
    second_disc[music["lba"] * 2048] ^= 1
    path.write_bytes(second_disc)
    assert main(command) == 0
    second_slug = json.loads(capsys.readouterr().out)["project"]
    assert second_slug != slug
    path.unlink()  # the imported project retains its own private disc
    for project_slug, disc_image in ((slug, original), (second_slug, second_disc)):
        assert main([*base, "export", project_slug, "--workspace", workspace]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["identical"] and result["scope"] == "disc"
        assert (Path(result["path"]) / result["disc"]["output"]).read_bytes() == disc_image


def test_browser_disc_import_export_and_failure_reporting(tmp_path):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    mcp, _, security = build(net, tmp_path / "home", 6499, "test-secret")
    app = mcp.streamable_http_app(transport_security=security, host="127.0.0.1")

    def job(client, response):
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 120
        last = None
        while time.monotonic() < deadline:
            last = client.get("/api/job", params={"id": response.json()["job"]}).json()
            if last["state"] != "running":
                return last
            time.sleep(0.02)
        pytest.fail(f"disc workflow timed out: {last}")

    with TestClient(app, base_url="http://127.0.0.1:6499") as client:
        assert client.post("/api/import", params={"confirmed": "1"}, content=fixture()).status_code == 401
        client.cookies.set("decomp_live", "test-secret")
        h = {"X-Decomp": "1"}
        client.post("/api/settings", json={"autopilot": False}, headers=h)
        imported = job(client, client.post("/api/import", params={"confirmed": "1", "name": "my disc.iso"}, content=fixture(), headers=h))
        assert imported["state"] == "done", imported
        slug = imported["result"]["slug"]
        overview = client.get("/api/project", params={"slug": slug}).json()
        assert overview["disc"]["supported"] and overview["disc"]["programs"] == 3
        exported = job(client, client.post("/api/export", json={"slug": slug}, headers=h))
        assert exported["state"] == "done" and exported["result"]["identical"], exported
        assert exported["result"]["scope"] == "disc"
        proj = net.project_row(slug)
        cfg = net.cfg(proj)
        (Path(proj["root"]) / cfg["psx_disc"]["file"]).write_bytes(b"corrupt disc")
        failed = job(client, client.post("/api/export", json={"slug": slug}, headers=h))
        assert failed["state"] == "error" and "original PS1 disc differs" in failed["error"], failed
