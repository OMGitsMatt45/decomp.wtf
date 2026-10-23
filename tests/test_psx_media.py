"""Original CUE/CHD fixtures, including audio, pregaps and private ZIP exports."""

import json
import binascii
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.rom import chd, detect
from decompnet.rom.errors import RomError
from .test_psx_disc import fixture

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")


def original_chd(image, compressed=False):
    """Real uncompressed v5 map with hunks stored out of logical order."""
    hunk = 2448 * 8
    count = (len(image) + hunk - 1) // hunk
    head = bytearray(124)
    head[:8] = chd.MAGIC
    struct.pack_into(">II", head, 8, 124, 5)
    struct.pack_into(">QQQII", head, 32, len(image), 124, 0, hunk, 2448)
    if compressed:
        head[16:20] = b"zlib"
        chunks = []
        for i in range(count):
            compressor = zlib.compressobj(wbits=-15)
            chunks.append(compressor.compress(image[i * hunk:(i + 1) * hunk].ljust(hunk, b"\0")) + compressor.flush())
        # A complete canonical 4-bit Huffman tree for the map's 16 codes,
        # followed by codec-0 entries and their lengths/CRC fields.
        first = 124 + 16 + (64 + 44 * count + 7) // 8
        offsets, cursor = [], first
        for chunk in chunks:
            offsets.append(cursor)
            cursor += len(chunk)
        crcs = [binascii.crc_hqx(image[i * hunk:(i + 1) * hunk].ljust(hunk, b"\0"), 0xFFFF) for i in range(count)]
        raw_map = b"".join(bytes(1) + len(chunk).to_bytes(3, "big") + offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
                           for chunk, offset, crc in zip(chunks, offsets, crcs))
        bits = "0100" * 16 + "0000" * count
        bits += "".join(f"{len(chunk):024b}{crc:016b}" for chunk, crc in zip(chunks, crcs))
        bits += "0" * (-len(bits) % 8)
        encoded_map = int(bits, 2).to_bytes(len(bits) // 8, "big")
        first = 124 + 16 + len(encoded_map)
        map_header = struct.pack(">I", len(encoded_map)) + first.to_bytes(6, "big") + binascii.crc_hqx(raw_map, 0xFFFF).to_bytes(2, "big") + bytes([24, 0, 0, 0])
        return bytes(head) + map_header + encoded_map + b"".join(chunks)
    blocks = list(range(count + 1, 1, -1))
    result = bytearray((count + 2) * hunk)
    result[:124] = head
    result[124:124 + count * 4] = struct.pack(f">{count}I", *blocks)
    for i, block in enumerate(blocks):
        part = image[i * hunk:(i + 1) * hunk]
        result[block * hunk:block * hunk + len(part)] = part
    return bytes(result)


@pytest.mark.parametrize("kind", ["cue", "cue-gap-audio", "chd", "chd-zlib"])
def test_media_clean_rebuild_and_tampering(tmp_path, kind):
    source = tmp_path / "owned media"
    source.mkdir()
    if kind.startswith("chd"):
        original = original_chd(fixture(2448, 24), compressed=kind == "chd-zlib")
        path = source / "disc.chd"
        path.write_bytes(original)
    else:
        offset = 150 if kind == "cue-gap-audio" else 0
        original = bytes(2352 * offset) + fixture(2352, 24)
        (source / "data track.bin").write_bytes(original)
        path = source / "disc.cue"
        path.write_text('FILE "data track.bin" BINARY\n TRACK 01 MODE2/2352\n' +
            (' INDEX 00 00:00:00\n' if offset else '') + f' INDEX 01 00:0{offset // 75}:00\n' +
            ('FILE "audio.bin" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n' if offset else ''))
        if offset:
            (source / "audio.bin").write_bytes(b"original audio".ljust(2352 * 8, b"\0"))
    picked = detect.identify(path)
    assert picked.disc["supported"], picked.disc
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(path, confirmed=True, log=lambda *_: None)
    shutil.rmtree(source)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["scope"] == "disc", result
    tree = Path(result["path"])
    manifest = json.loads((tree / "build.json").read_text())
    assert (tree / manifest["disc"]["output"]).read_bytes() == original
    for name in ("asm", "assets", "build"):
        shutil.rmtree(tree / name, ignore_errors=True)
    (tree / manifest["image"]).unlink()

    def run():
        return subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=120)

    clean = run()
    assert clean.returncode == 0, clean.stdout + clean.stderr
    disc = manifest["disc"]
    if kind.startswith("cue"):
        cue = tree / "build/disc-media/disc.cue"
        assert cue.is_file() and 'data track.bin' in cue.read_text()
        companion = tree / "baserom-media/disc.cue"
        companion.write_bytes(b"changed CUE")
    else:
        (tree / disc["image"]).write_bytes(original[:-1])
    failed = run()
    assert failed.returncode != 0
    assert all(not (tree / a["output"]).exists() for a in disc["artifacts"])


@pytest.mark.parametrize("body", [
    'FILE "../outside.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00',
    'FILE "missing.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00',
    'FILE "data.bin" BINARY\n TRACK 02 MODE2/2352\n INDEX 01 00:00:00',
    'FILE "data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 99:00:00',
    'FILE "data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n INDEX 01 00:00:01',
    'FILE "data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n CDTEXTFILE "other"',
])
def test_cue_rejects_ambiguous_or_escaping_layouts(tmp_path, body):
    (tmp_path / "data.bin").write_bytes(fixture(2352, 24))
    path = tmp_path / "disc.cue"
    path.write_text(body)
    with pytest.raises((RomError, OSError)):
        detect.identify(path)


def test_combined_cue_chd_zip_preserves_every_media_artifact(tmp_path):
    (tmp_path / "data.bin").write_bytes(fixture(2352, 24))
    cue = tmp_path / "disc.cue"
    cue.write_text('FILE "data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n')
    compressed = tmp_path / "disc.chd"
    original = original_chd(fixture(2448, 24), compressed=True)
    compressed.write_bytes(original)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slugs = [net.import_rom(p, confirmed=True, log=lambda *_: None) for p in (cue, compressed)]
    net.set_psx_disc_set(slugs[0], slugs, "Original media set")
    result = net.export_rom(slugs[1], log=lambda *_: None)
    assert result["identical"], result
    tree = Path(result["path"])
    assert (tree / "build/disc-1/disc.cue").read_bytes() == cue.read_bytes()
    assert (tree / "build/disc-1/data.bin").read_bytes() == fixture(2352, 24)
    assert (tree / "build/disc-2/disc.chd").read_bytes() == original
    (tree / "discs/disc-2/baserom-disc.chd").write_bytes(b"bad CHD")
    failed = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=120)
    assert failed.returncode != 0
    assert not any(p.is_file() for p in (tree / "build").rglob("*"))
