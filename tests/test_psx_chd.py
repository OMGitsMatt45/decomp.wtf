"""Independent MAME containers: exact PCM/subcode, metadata and mod authoring."""

import hashlib
import json
import random
from pathlib import Path

import pytest

from decompnet.rom import chd, chd_write, detect, psx_disc, psx_modify, psx_sector
from decompnet.rom.n64 import RomError
from .psx_chd_fixture import decoded, METADATA
from .test_psx_disc import joined

FIXTURES = Path(__file__).parent / "fixtures/psx-chd"
CODECS = ("cdlz", "cdzl", "cdfl", "lzma", "zlib")


@pytest.mark.parametrize("codec", CODECS)
def test_independent_chd_audio_parity_subcode_metadata_and_hashes(codec):
    path = FIXTURES / f"{codec}.chd"
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    raw = decoded()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == provenance["files"][path.name]["sha256"]
    assert hashlib.sha256(raw).hexdigest() == provenance["decoded_sha256"]
    with chd.Chd(path) as disc:
        assert disc.read() == raw
        disc.seek(0)
        assert disc.read(1 << 20) == raw and disc.read(1) == b""
        assert disc.header[64:84] == hashlib.sha1(raw).digest()
        assert disc.header[84:104] == chd.overall_sha1(hashlib.sha1(raw).digest(), disc.metadata)
        assert disc.metadata == [(tag.encode(), int(checked), text.encode() + b"\0") for tag, text, checked in METADATA]
        assert any(kind == chd.SELF for kind, _, _ in disc.map)
        disc.seek(32 * 2448)
        assert any(disc.read(8 * 2448))  # non-silent stereo track


@pytest.mark.parametrize("codec", CODECS)
def test_mod_recompression_changes_only_one_program_sector_and_preserves_tracks(tmp_path, codec):
    original = FIXTURES / f"{codec}.chd"
    picked = detect.identify(original)
    assert picked.disc["supported"]
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    output = tmp_path / "modified.chd"
    assert psx_modify.rebuild(original, image, layout, output)["changed_sectors"] == 0
    assert output.read_bytes() == original.read_bytes()
    changed = bytearray(image)
    changed[0x808] ^= 1
    result = psx_modify.rebuild(original, changed, layout, output)
    assert result["changed_sectors"] == 1 and result["chd"]["lossless_verified"]
    before = decoded()
    expected = bytearray(before)
    lba = layout["maps"][0]["lba"] + 1
    at = lba * 2448
    payload = bytearray(before[at + 24:at + 24 + 2048])
    payload[8] ^= 1
    expected[at:at + 2448] = psx_sector.replace(before[at:at + 2448], payload)
    with chd.Chd(original) as src, chd.Chd(output) as dst:
        assert dst.read() == expected
        assert dst.metadata == src.metadata
        assert dst.header[64:84] == hashlib.sha1(expected).digest()
        assert dst.header[84:104] == chd.overall_sha1(hashlib.sha1(expected).digest(), dst.metadata)
        assert dst.codecs[0] == b"zlib"
    chd_write.verify_geometry(original, output, result["chd"])
    bad_report = dict(result["chd"], logical_size=len(expected) + 2448)
    with pytest.raises(RomError, match="geometry"):
        chd_write.verify_geometry(original, output, bad_report)
    bad_report = dict(result["chd"], decoded_sha256="00" * 32)
    with pytest.raises(RomError, match="decoded hash"):
        chd_write.verify_geometry(original, output, bad_report)


@pytest.mark.parametrize("damage", ["map", "hunk", "truncated", "metadata", "raw-sha"])
def test_damaged_chd_cannot_publish_a_modified_container(tmp_path, damage):
    source = FIXTURES / "cdfl.chd"
    data = bytearray(source.read_bytes())
    with chd.Chd(source) as disc:
        if damage == "map":
            data[int.from_bytes(data[40:48], "big") + 10] ^= 1
        elif damage == "hunk":
            _, length, offset = disc.map[4]
            data[offset + length // 2] ^= 0x10
        elif damage == "truncated":
            data = data[:-1]
        elif damage == "metadata":
            data[data.index(b"TRACK:2") + len("TRACK:")] ^= 1
        else:
            data[64] ^= 1
            # A consistent metadata hash still cannot hide a bad raw data hash.
            data[84:104] = chd.overall_sha1(bytes(data[64:84]), disc.metadata)
    original, output = tmp_path / "bad.chd", tmp_path / "modified.chd"
    original.write_bytes(data)
    output.write_bytes(b"stale output")
    with pytest.raises(RomError):
        chd_write.rewrite(original, output, {})
    assert not output.exists()


def test_overlapping_patch_rejection_and_raw_copy_mode(tmp_path):
    from .test_psx_media import original_chd
    raw = decoded()
    original, output = tmp_path / "original.chd", tmp_path / "mod.chd"
    original.write_bytes(original_chd(raw))
    with pytest.raises(RomError, match="overlap"):
        chd_write.rewrite(original, output, {10: b"123", 12: b"45"})
    assert not output.exists()
    report = chd_write.rewrite(original, output, {2448: b"test"})
    chd_write.verify_geometry(original, output, report)
    with chd.Chd(output) as result:
        assert result.read() == raw[:2448] + b"test" + raw[2452:]
    with pytest.raises(RomError, match="separate"):
        chd_write.rewrite(original, original, {})
    assert original.read_bytes() == original_chd(raw)


@pytest.mark.parametrize("hunks", [1, 2])
def test_incompressible_audio_uses_raw_hunks_with_valid_odd_and_even_maps(tmp_path, hunks):
    from .test_psx_media import original_chd
    raw = random.Random(12345).randbytes(2448 * 8 * hunks)
    original, output = tmp_path / "original.chd", tmp_path / "output.chd"
    original.write_bytes(original_chd(raw))
    chd_write.rewrite(original, output, {0: b"abcd"})
    with chd.Chd(output) as result:
        assert all(kind == chd.NONE for kind, _, _ in result.map)
        assert result.read() == b"abcd" + raw[4:]


def test_mod_temporary_name_cannot_overwrite_original_input(tmp_path):
    from .test_psx_disc import fixture
    raw = fixture()
    picked = detect.identify(raw)
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    original, output = tmp_path / "modified.bin.tmp", tmp_path / "modified.bin"
    original.write_bytes(raw)
    changed = bytearray(image)
    changed[0x808] ^= 1
    assert psx_modify.rebuild(original, changed, layout, output)["changed_sectors"] == 1
    assert original.read_bytes() == raw and output.read_bytes() != raw
    assert not list(tmp_path.glob(".psx-mod-*.tmp"))


def test_single_symbol_huffman_map_and_partial_final_hunk(tmp_path):
    from .test_psx_media import original_chd
    # The tree's only symbol has length one; its unused prefix must still fail.
    lengths = "00010001" + "0000" * 15
    encoded = int(lengths + "0000", 2).to_bytes(9, "big")
    decoder = chd._Huffman(chd._Bits(encoded))
    assert decoder.decode(chd._Bits(b"\0")) == 0
    with pytest.raises(RomError, match="Huffman code"):
        decoder.decode(chd._Bits(b"\x80"))
    original, output = tmp_path / "original.chd", tmp_path / "mod.chd"
    original.write_bytes(original_chd(bytes(2448)))
    with chd.Chd(original) as disc:
        assert disc.read(1 << 20) == bytes(2448) and disc.tell() == 2448
    chd_write.rewrite(original, output, {2447: b"x"})
    with chd.Chd(output) as disc:
        assert disc.read(1 << 20) == bytes(2447) + b"x"
