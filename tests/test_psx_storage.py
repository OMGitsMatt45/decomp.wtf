"""Modified compressed modules fit reviewed archive space and preserve loader fixups."""

import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import zlib

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom import detect, psx, psx_layout, psx_disc, psx_modify
from decompnet.rom.n64 import RomError
from .test_overlays import _iso, _overlay, _resident_exe
from .test_psx_disc import joined
from .test_psx_modify import valid_raw


def fixture():
    code = bytearray(_overlay(0x80180000, 40).ljust(0x1000, b"\0"))
    struct.pack_into("<I", code, 8, 0x0C000000)
    struct.pack_into("<2I", code, 0x500, 0x03E00008, 0x24820007)
    archive, modules = bytearray(128), []
    for index, codec in enumerate(("zlib", "gzip")):
        encoder = zlib.compressobj(9, zlib.DEFLATED, 31 if codec == "gzip" else 15)
        stored = encoder.compress(code) + encoder.flush()
        at, capacity = len(archive), 0x800
        endian, width = ("little", 4) if index == 0 else ("big", 2)
        archive[index * 8:index * 8 + width] = len(stored).to_bytes(width, endian)
        archive += stored + bytes(capacity - len(stored)) + b"retain archive separator"
        modules.append({"name": codec + "_module", "path": "CODE.ARC", "offset": at,
                        "stored_size": len(stored), "size": len(code), "codec": codec, "load": 0x80180000,
                        "code_end": 0x508, "relocations": [{"offset": 8, "type": "R_MIPS_26", "value": 0x80180500}],
                        "storage": {"capacity": capacity, "length_offset": index * 8, "length_width": width, "endian": endian}})
    image = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "CODE.ARC": bytes(archive)})
    return image, {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": modules}


@pytest.mark.parametrize("error", ["length", "nonzero_capacity", "overlap", "field_overlap", "bounds"])
def test_reviewed_storage_refuses_bad_loader_fields_and_allocations(error):
    image, layout = fixture()
    item = layout["modules"][0]
    if error == "length":
        item["stored_size"] += 1
    elif error == "nonzero_capacity":
        item["storage"]["capacity"] += 1
    elif error == "overlap":
        layout["modules"].append(copy.deepcopy(item) | {"name": "duplicate_storage"})
    elif error == "field_overlap":
        layout["modules"][1]["storage"].update(length_offset=0, length_width=4, endian="little")
    else:
        item["storage"]["length_offset"] = 0xFFFFFF
    with pytest.raises(RomError):
        psx_layout.apply(detect.identify(image), image, layout)


@pytest.mark.parametrize("raw", [False, True])
def test_recompression_updates_loader_lengths_and_rejects_exhaustion_or_changed_fixups(tmp_path, raw):
    image, review = fixture()
    if raw:
        image = valid_raw(image, 2352, 24)
        review["sha256"] = hashlib.sha256(image).hexdigest()
    picked = detect.identify(image)
    psx_layout.apply(picked, image, review)
    baseline, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, baseline)
    original, output = tmp_path / "original.bin", tmp_path / "modified.bin"
    original.write_bytes(image)
    changed = bytearray(baseline)
    for mapping in layout["maps"][1:]:
        at = mapping["analysis_offset"] + 0x504
        changed[at:at + 4] = (0x24820008).to_bytes(4, "little")
    result = psx_modify.rebuild(original, changed, layout, output)
    assert len(result["module_storage"]) == 2
    assert output.stat().st_size == len(image)
    with output.open("rb") as stream:
        archive = psx._Disc(stream).find("CODE.ARC")
    assert archive is not None
    for mapping, record in zip(layout["maps"][1:], result["module_storage"]):
        storage, offset = mapping["storage"], mapping["file_offset"]
        size = int.from_bytes(archive[storage["length_offset"]:storage["length_offset"] + storage["length_width"]], storage["endian"])
        assert size == record["stored_size"] <= storage["capacity"]
        encoded = archive[offset:offset + size]
        at = mapping["analysis_offset"]
        assert psx_layout.transform(encoded, mapping) == changed[at:at + mapping["size"]]
        assert not archive[offset + size:offset + storage["capacity"]].strip(b"\0")
        decoded = zlib.decompress(encoded, 31 if mapping["codec"] == "gzip" else 15)
        assert int.from_bytes(decoded[8:12], "little") == 0x0C000000
    mapping = layout["maps"][1]
    changed[mapping["analysis_offset"] + 8] ^= 1
    with pytest.raises(RomError, match="changed loader relocation sites"):
        psx_modify.rebuild(original, changed, layout, output)
    assert not output.exists()
    changed = bytearray(baseline)
    start = mapping["analysis_offset"] + 0x600
    changed[start:start + 0xA00] = random.Random(123).randbytes(0xA00)
    with pytest.raises(RomError, match="exceeds its reviewed encoded storage"):
        psx_modify.rebuild(original, changed, layout, output)
    assert not output.exists()


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
def test_console_build_grown_cpp_in_two_compressed_exclusive_modules(tmp_path, capsys):
    image, review = fixture()
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, reviewed_layout=review, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"], result
    root = Path(result["path"])
    meta = json.loads((root / "build.json").read_text())
    for fn in (f for f in meta["functions"] if f["vram"] == 0x80180500):
        fn["compiler"] = {"flags": ["-O0", "-G0"]}
        source = root / f'src/{fn["seg"]}/{fn["name"]}.cpp'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f'extern "C" {{ int state = 3; static int helper(int x) {{ return x + state; }} '
                          f'int {fn["name"]}(int x) {{ return helper(x) + 1; }} }}\n')
    (root / "build.json").write_text(json.dumps(meta))
    for module in ("ovl_zlib_module", "ovl_gzip_module"):
        assert main(["psx", "reserve", str(root), "--module", module, "--start", "0x80180600", "--size", "0x800"]) == 0
    assert main(["psx", "build", str(root), "--mod"]) == 0
    report = json.loads((root / "build/psx-mod-result.json").read_text())
    assert len(report["spaces"]) == len(report["changed_functions"]) == len(report["disc"]["module_storage"]) == 2
    assert subprocess.run([sys.executable, "build.py"], cwd=root, capture_output=True, timeout=120).returncode != 0
