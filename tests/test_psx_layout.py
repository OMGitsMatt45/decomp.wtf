"""Reviewed archived/compressed/relocated modules use independent strict targets."""

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import zlib

import pytest
from starlette.testclient import TestClient

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.cli import main
from decompnet.rom import detect, psx_layout
from decompnet.rom.errors import RomError
from .test_overlays import _iso, _overlay, _resident_exe

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")


def fixture(root):
    cfg = project.compiler_config(root, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.7.2-psx", "language": "c", "sandbox": "none"}})
    compiled = compiler.compile_source(cfg, "", "int leaf(int x) { return x + 7; }")
    assert compiled.ok, compiled.log
    leaf = elfobj.extract_function(compiled.obj, "leaf").code
    base, address = 0x80180000, 0x80180500
    code = bytearray(_overlay(base, 40) + leaf)
    struct.pack_into("<I", code, 8, 0x0C000000 | ((address >> 2) & 0x03FFFFFF))
    archive, modules = bytearray(b"original archive header".ljust(123, b"\0")), []
    for codec in ("raw", "zlib", "gzip"):
        decoded = bytearray(code)
        relocations = []
        if codec == "zlib":
            struct.pack_into("<I", decoded, 8, 0x0C000000)
            relocations = [{"offset": 8, "type": "R_MIPS_26", "value": address}]
        stored = bytes(decoded) if codec == "raw" else zlib.compress(decoded) if codec == "zlib" else gzip.compress(decoded, mtime=0)
        modules.append({"name": codec + "_module", "path": "CODE.ARC", "offset": len(archive),
            "stored_size": len(stored), "size": len(decoded), "codec": codec, "load": base, "relocations": relocations})
        archive += stored + b"archive record separator"
    original = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "CODE.ARC": bytes(archive)})
    return original, {"format": 1, "sha256": hashlib.sha256(original).hexdigest(), "modules": modules}, address


def test_reviewed_archive_modules_recover_cpp_and_retain_exact_encoded_disc(tmp_path, capsys):
    original, layout, address = fixture(tmp_path)
    path, layout_path = tmp_path / "game.iso", tmp_path / "reviewed.json"
    path.write_bytes(original)
    layout_path.write_text(json.dumps(layout))
    db, workspace = tmp_path / "app.db", tmp_path / "projects"
    assert main(["--db", str(db), "psx", "import", str(path), "--layout", str(layout_path),
                 "--own-copy", "--workspace", str(workspace)]) == 0
    slug = json.loads(capsys.readouterr().out)["project"]
    net = RomNetwork(db, workspace)
    net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    functions = net.store.all("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], address)
    assert len(functions) == 3
    agent, _ = net.local_agent("reviewed-modules")
    for fn in functions:
        result = net.attempt(agent, fn["name"], f"int {fn['name']}(int x) {{ return x + 7; }}", slug)
        assert result["matched"], result
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["matched"] == 3 and not result["fallback"], result
    assert (Path(result["path"]) / result["disc"]["output"]).read_bytes() == original


@pytest.mark.parametrize("error", ["sha", "codec", "extent", "bss", "relocation", "duplicate"])
def test_reviewed_layout_rejects_wrong_identity_and_unsafe_module_facts(tmp_path, error):
    original, layout, _ = fixture(tmp_path)
    bad = copy.deepcopy(layout)
    first = bad["modules"][0]
    if error == "sha":
        bad["sha256"] = "0" * 64
    elif error == "codec":
        first["codec"] = "unknown-loader"
    elif error == "extent":
        first["stored_size"] = 10000000
    elif error == "bss":
        first.update(bss=first["load"], bss_size=4)
    elif error == "relocation":
        first["relocations"] = [{"offset": 3, "type": "R_MIPS_32", "value": 0}]
    else:
        bad["modules"].append(first)
    with pytest.raises((RomError, zlib.error)):
        psx_layout.apply(detect.identify(original), original, bad)


def test_browser_reviewed_ps1_layout_import_and_token_expiry(tmp_path):
    original, layout, _ = fixture(tmp_path)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    mcp, _, security = build(net, tmp_path / "home", 6499, "test-secret")
    app = mcp.streamable_http_app(transport_security=security, host="127.0.0.1")
    with TestClient(app, base_url="http://127.0.0.1:6499") as client:
        assert client.post("/api/rom/layout", json={"layout": layout}).status_code == 401
        client.cookies.set("decomp_live", "test-secret")
        headers = {"X-Decomp": "1"}
        token = client.post("/api/rom/layout", json={"layout": layout}, headers=headers).json()["id"]
        params = {"confirmed": "1", "reviewed_layout": token}
        response = client.post("/api/import", params=params, content=original, headers=headers)
        assert response.status_code == 200
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = client.get("/api/job", params={"id": response.json()["job"]}).json()
            if job["state"] != "running":
                break
            time.sleep(0.02)
        assert job["state"] == "done", job
        overview = net.overview(job["result"]["slug"])
        assert overview["disc"]["programs"] == 4
        assert client.post("/api/import", params=params, content=original, headers=headers).status_code == 400
