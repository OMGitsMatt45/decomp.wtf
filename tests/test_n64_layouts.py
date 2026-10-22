"""Original cartridges with reviewed overlays, compressed modules and TLB mappings."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import n64_layout
from .test_n64code import _code


def fixture(codec="none"):
    image = bytearray(0x40000)
    image[:4] = bytes.fromhex("80371240")
    struct.pack_into(">I", image, 8, 0x80000400)
    image[0x20:0x34] = b"REVIEWED N64 TEST".ljust(20, b" ")
    image[0x3B:0x3F] = b"NTSE"
    main = _code(0x80000400, 40) + struct.pack(">4I", 1, 2, 3, 4)
    image[0x1000:0x1000 + len(main)] = main
    modules = [{"name": "main", "rom_start": 0x1000, "rom_end": 0x1000 + len(main), "vram": 0x80000400,
                "sections": [{"offset": 0, "type": "code"}, {"offset": 40 * 32, "type": "data"}], "bss_size": 16}]
    for index, name in enumerate(("battle", "field")):
        code = _code(0x7F000000, 40) + struct.pack(">4I", 7 + index, 0x11223344, 0x55667788, 9)
        if codec == "none":
            stored = code
        elif codec == "yaz0":
            stored = b"Yaz0" + len(code).to_bytes(4, "big") + bytes(8)
            stored += b"".join(b"\xff" + code[at:at + 8] for at in range(0, len(code), 8))
        else:
            stream = zlib.compressobj(9, zlib.DEFLATED, -15)
            stored = bytes.fromhex("1172" if codec.endswith("1172") else "1173")
            if codec.endswith("1173"):
                stored += len(code).to_bytes(3, "big")
            stored += stream.compress(code) + stream.flush()
        start = 0x10000 + index * 0x10000
        image[start:start + len(stored)] = stored
        modules.append({"name": name, "rom_start": start, "rom_end": start + len(stored), "vram": 0x7F000000,
                        "exclusive_group": "scenes", "compression": codec,
                        "sections": [{"offset": 0, "type": "code"}, {"offset": 40 * 32, "type": "data"}],
                        **({"decoded_size": len(code)} if codec != "none" else {})})
    return bytes(image), {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": modules}


@pytest.mark.parametrize("codec", ["none", "yaz0", "deflate-1172", "deflate-1173"])
def test_reviewed_modules_and_exact_container_exports(tmp_path, codec):
    if toolchains.installed("binutils-mips") is None:
        pytest.skip("requires pinned native MIPS binutils")
    original, layout = fixture(codec)
    segments, working, metadata = n64_layout.reviewed(original, layout)
    assert n64_layout.working_image(original, metadata) == working
    assert [s["vram"] for s in segments if isinstance(s, dict) and s["type"] == "code"] == [0x80000400, 0x7F000000, 0x7F000000]
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    project = net.project_row(slug)
    assert net.cfg(project)["n64_layout"]
    rows = net.store.all("SELECT name, vram, rom_offset FROM functions WHERE project_id=?", project["id"])
    assert len(rows) >= 120 and len({r["name"] for r in rows}) == len(rows)
    overlay_rows = [r for r in rows if r["vram"] == 0x7F000000]
    assert len(overlay_rows) == 2 and len({r["rom_offset"] for r in overlay_rows}) == 2
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"], result["log"]
    tree = Path(result["path"])
    assert (tree / "build/game.z64").read_bytes() == original
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated)
    (tree / "analysis.z64").unlink(missing_ok=True)
    process = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tree / "build/game.z64").read_bytes() == original
    if codec != "none":
        # A decoded source/assembly edit must fail before emitting a cartridge;
        # retaining the original compressed stream cannot hide changed code.
        assembly = next((tree / "asm/nonmatchings/battle").glob("*.s"))
        text = assembly.read_text()
        assert "addiu" in text
        assembly.write_text(text.replace("addiu", "ori", 1))
        process = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
        assert process.returncode != 0
        assert not (tree / "build/game.z64").exists()


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "SHA-256"), ("uncertain", "source extent"), ("group", "exclusive_group"),
    ("source", "source ranges overlap"), ("section", "sections must"), ("extent", "outside"),
])
def test_bad_layouts_fail_before_project_creation(tmp_path, mutation, reason):
    original, layout = fixture()
    layout = copy.deepcopy(layout)
    if mutation == "hash":
        layout["sha256"] = "0" * 64
    elif mutation == "uncertain":
        layout["modules"][1]["vram"] = None
    elif mutation == "group":
        del layout["modules"][1]["exclusive_group"]
    elif mutation == "source":
        layout["modules"][1]["rom_start"] = 0x1000
    elif mutation == "section":
        layout["modules"][1]["sections"][0]["offset"] = 4
    else:
        layout["modules"][1]["rom_end"] = len(original) + 4
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    with pytest.raises(NetworkError, match=reason):
        net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    assert net.store.one("SELECT COUNT(*) AS n FROM projects")["n"] == 0
    assert not list((tmp_path / "projects").glob("*/rom.z64"))


def test_automatically_unpacked_code_exports_the_original_cartridge(tmp_path):
    original, _ = fixture('none')
    # A single TLB block avoids the intentionally overlapping reviewed modules.
    image = bytearray(original)
    image[0x10000:0x30000] = bytes(0x20000)
    code = _code(0x7F000000, 160)
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = b'\x11\x73' + len(code).to_bytes(3, 'big') + packer.compress(code) + packer.flush()
    image[0x10000:0x10000 + len(packed)] = packed
    original = bytes(image)
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, confirmed=True, log=lambda *_: None)
    project = net.project_row(slug)
    provenance = json.loads((Path(project['root']) / 'n64-provenance.json').read_text())
    assert provenance['blocks']
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported['identical'], exported['log']
    tree = Path(exported['path'])
    assert (tree / 'build/game.z64').read_bytes() == original
    assert (tree / 'build/analysis.z64').stat().st_size > len(original)


@pytest.mark.parametrize('codec', ['yaz0', 'deflate-1172', 'deflate-1173'])
def test_reviewed_compression_rejects_truncated_or_wrong_size_modules(codec):
    original, layout = fixture(codec)
    bad = copy.deepcopy(layout)
    bad['modules'][1]['decoded_size'] += 4
    with pytest.raises(ValueError, match='size|header|truncated'):
        n64_layout.reviewed(original, bad)
    bad = copy.deepcopy(layout)
    bad['modules'][1]['rom_end'] = bad['modules'][1]['rom_start'] + 17
    with pytest.raises(ValueError):
        n64_layout.reviewed(original, bad)
