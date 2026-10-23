"""Original CD parity vectors and genuine C++ source changes in pinned slots."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom import psx_sector, psx_modify, detect, psx_disc
from decompnet.rom.n64 import RomError
from .test_psx_disc import fixture, joined
from .test_psx_set import fixtures, imported


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
def test_embedded_later_mips_words_and_gte_rebuild_without_changing_cpu_isa(tmp_path):
    from .test_overlays import _iso, _resident_exe
    original = bytearray(_resident_exe())
    struct.pack_into("<I", original, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    words = (0xBC010801, 0xF9280653, 0x620594ED, 0x4A180001, 0x03E00008, 0)
    struct.pack_into('<6I', original, 0xD00, *words)
    image = _iso({'SYSTEM.CNF': b'BOOT = cdrom:\\GAME.EXE;1\n', 'GAME.EXE': bytes(original)})
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(image, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c['compiler'].update(sandbox='none'))
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'], result
    tree = Path(result['path'])
    meta = json.loads((tree / 'build.json').read_text())
    assert (tree / meta['disc']['output']).read_bytes() == image
    for folder in ('asm', 'assets', 'build'):
        shutil.rmtree(tree / folder, ignore_errors=True)
    (tree / meta['image']).unlink()
    process = subprocess.run([sys.executable, 'build.py'], cwd=tree, capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tree / meta['disc']['output']).read_bytes() == image


def valid_raw(image, size, skip):
    result = bytearray()
    for lba in range(len(image) // 2048):
        sector = bytearray(size)
        sector[:12] = b"\0" + b"\xff" * 10 + b"\0"
        sector[12:16] = bytes([0, 2, lba % 75, 1 if skip == 16 else 2])
        if skip == 24:
            sector[16:24] = bytes([0, 0, 8, 0]) * 2
        sector[skip:skip + 2048] = image[lba * 2048:(lba + 1) * 2048]
        if size == 2448:
            sector[2352:] = bytes((i + lba) % 256 for i in range(96))
        result += psx_sector.corrected(sector)
    return bytes(result)


def syndromes(sector, major_count, minor_count, major_mult, minor_inc, parity_at):
    """Check the two Reed-Solomon roots independently of the parity encoder."""
    source = bytearray(sector[12:parity_at])
    if sector[15] == 2:
        source[:4] = bytes(4)
    for major in range(major_count):
        index = (major // 2) * major_mult + major % 2
        values = []
        for _ in range(minor_count):
            values.append(source[index])
            index = (index + minor_inc) % (major_count * minor_count)
        values.extend([sector[parity_at + major], sector[parity_at + major_count + major]])
        root_zero = root_one = 0
        for value in values:
            root_zero ^= value
            root_one ^= value
            root_one = (root_one * 2) ^ (0x11D if root_one & 128 else 0)
        assert root_zero == root_one == 0


@pytest.mark.parametrize("size,skip", [(2352, 16), (2352, 24), (2448, 16), (2448, 24)])
def test_changed_raw_sector_has_valid_edc_and_both_ecc_syndromes(size, skip):
    assert psx_sector.edc(b"123456789") == bytes.fromhex("c4edc26e")
    original = valid_raw(bytes(range(256)) * 8, size, skip)
    changed = bytearray(original[skip:skip + 2048])
    changed[123] ^= 0x81
    result = psx_sector.replace(original, changed)
    assert result != original and result[:skip] == original[:skip]
    assert result[skip:skip + 2048] == changed and result[2352:] == original[2352:]
    at, start = (2064, 0) if skip == 16 else (2072, 16)
    assert result[at:at + 4] == psx_sector.edc(result[start:at])
    syndromes(result, 86, 24, 2, 86, 2076)
    syndromes(result, 52, 43, 86, 88, 2248)
    bad = bytearray(original)
    bad[2100] ^= 1
    with pytest.raises(RomError, match="nonstandard original EDC/ECC"):
        psx_sector.replace(bytes(bad), changed)


@pytest.mark.parametrize("size,skip", [(2048, 0), (2352, 16), (2352, 24), (2448, 24)])
def test_modified_disc_keeps_unrelated_bytes_and_exact_file_extents(tmp_path, size, skip):
    original = fixture() if size == 2048 else valid_raw(fixture(), size, skip)
    picked = detect.identify(original)
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    path, output = tmp_path / "original.bin", tmp_path / "mod.bin"
    path.write_bytes(original)
    changed = bytearray(image)
    changed[0x808] ^= 1
    report = psx_modify.rebuild(path, bytes(changed), layout, output)
    assert report["changed_sectors"] == 1
    before, after = original, output.read_bytes()
    assert len(before) == len(after)
    mapping = layout["maps"][0]
    sector = (mapping["lba"] + 1) * size
    assert before[:sector] == after[:sector] and before[sector + size:] == after[sector + size:]
    if size != 2048:
        syndromes(after[sector:sector + size], 86, 24, 2, 86, 2076)
        syndromes(after[sector:sector + size], 52, 43, 86, 88, 2248)
    with pytest.raises(RomError, match="file sizes"):
        psx_modify.rebuild(path, bytes(changed) + b"x", layout, output)
    assert not output.exists()
    changed[0x10] ^= 1
    with pytest.raises(RomError, match="headers"):
        psx_modify.rebuild(path, bytes(changed), layout, output)
    assert not output.exists()


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("tcid", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("function_offset", [0, 4])
def test_cpp_changes_build_without_weakening_matching_and_fail_cleanly(tmp_path, tcid, function_offset):
    original = fixtures(tmp_path, tcid, function_offset)[0]
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=tcid, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"], result
    tree = Path(result["path"])
    meta = json.loads((tree / "build.json").read_text())
    fn = next(f for f in meta["functions"] if f["vram"] == 0x80010500 + function_offset)
    source = tree / f"src/{fn['seg']}/{fn['name']}.cpp"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f'extern "C" int {fn["name"]}(int x) {{ return x + 8; }}\n')

    def run(*args):
        return subprocess.run([sys.executable, "build.py", *args], cwd=tree, capture_output=True, text=True, timeout=120)

    built = run("mod")
    assert built.returncode == 0, built.stdout + built.stderr
    report = json.loads((tree / "build/psx-mod-result.json").read_text())
    assert report["baseline_identical"] and report["changed_functions"] == [fn["name"]]
    modified = (tree / report["artifacts"][0]["output"]).read_bytes()
    assert modified != original and len(modified) == len(original)
    assert run().returncode != 0
    # A clean mod build must recover the original baseline from the retained
    # input rather than depend on earlier objects or an analysis image.
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    (tree / meta["image"]).unlink()
    assert run("mod").returncode == 0
    assert (tree / report["artifacts"][0]["output"]).read_bytes() == modified
    source.write_text(f'int introduced = 3;\nextern "C" int {fn["name"]}(int x) {{ return x + 8; }}\n')
    refused = run("mod")
    assert refused.returncode != 0 and "cannot add owned data/BSS" in refused.stdout + refused.stderr
    assert not (tree / "build/psx-mod-result.json").exists()
    source.write_text(f'extern "C" int {fn["name"]}(int x) {{ return x + 8; }}\n')
    meta["symbols"]["interior_alias"] = fn["vram"] + 4
    (tree / "build.json").write_text(json.dumps(meta))
    refused = run("mod")
    assert refused.returncode != 0 and "interior symbol" in refused.stdout + refused.stderr
    assert not (tree / "build/psx-mod-result.json").exists()
    del meta["symbols"]["interior_alias"]
    (tree / "build.json").write_text(json.dumps(meta))
    source.write_text(f'extern "C" int {fn["name"]}(int x) {{ volatile int v[20]; v[0] = x; return v[0] + x; }}\n')
    failed = run("mod")
    assert failed.returncode != 0 and "function slot" in failed.stdout + failed.stderr
    assert not (tree / "build/psx-mod-result.json").exists()
    assert not (tree / "build/psx-mod").exists()


@pytest.mark.parametrize("kind", ["cue-gap-audio", "cue-shared-audio", "chd"])
def test_modified_media_preserves_audio_pregap_paths_and_refuses_changed_chd(tmp_path, kind):
    from .test_psx_media import original_chd
    if kind == "chd":
        original = original_chd(valid_raw(fixture(), 2448, 24), compressed=True)
        path = tmp_path / "disc.chd"
        path.write_bytes(original)
    else:
        (tmp_path / "tracks").mkdir()
        audio = b"original audio".ljust(2352 * 8, b"\0")
        raw = bytes(2352 * 150) + valid_raw(fixture(), 2352, 24)
        shared = kind == "cue-shared-audio"
        original = raw + audio if shared else raw
        (tmp_path / "tracks/data.bin").write_bytes(original)
        (tmp_path / "tracks/audio.bin").write_bytes(audio)
        path = tmp_path / "disc.cue"
        frames = len(raw) // 2352
        cue = 'FILE "tracks/data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 00 00:00:00\n INDEX 01 00:02:00\n'
        cue += (f' TRACK 02 AUDIO\n INDEX 01 {frames // 4500:02}:{frames // 75 % 60:02}:{frames % 75:02}\n' if shared else
                'FILE "tracks/audio.bin" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n')
        path.write_text(cue)
    from decompnet.rom import psx_media
    picked = detect.identify(path)
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    primary = psx_media.snapshot(path, picked, pinned)
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    changed = bytearray(image)
    changed[0x808] ^= 1
    output = tmp_path / "output/disc.bin"
    if kind == "chd":
        assert psx_modify.rebuild(primary, image, layout, output)["changed_sectors"] == 0
        assert output.read_bytes() == original
        with pytest.raises(RomError, match="lossless track/audio recompression"):
            psx_modify.rebuild(primary, changed, layout, output)
        assert not output.exists()
    else:
        assert psx_modify.rebuild(primary, changed, layout, output)["changed_sectors"] == 1
        result = output.read_bytes()
        assert result[:150 * 2352] == original[:150 * 2352]
        assert result[-len(audio):] == original[-len(audio):]
        psx_media.companions(primary, layout, tmp_path / "output")
        assert (tmp_path / "output/disc.cue").read_text() == cue
        if not shared:
            assert (tmp_path / "output/tracks/audio.bin").read_bytes() == audio


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("media", ["iso", "cue"])
def test_cli_combined_mod_uses_shared_source_and_disc_two_failure_removes_all_outputs(tmp_path, capsys, media):
    if media == "iso":
        net, slugs, originals = imported(tmp_path, recover=True)
    else:
        net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
        slugs, originals = [], []
        for number, image in enumerate(fixtures(tmp_path)):
            folder = tmp_path / f"input-{number}"
            (folder / "tracks").mkdir(parents=True)
            original = valid_raw(image, 2352, 24)
            originals.append(original)
            (folder / "tracks/data.bin").write_bytes(original)
            cue = folder / "disc.cue"
            cue.write_text('FILE "tracks/data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n')
            slug = net.import_rom(cue, confirmed=True, log=lambda *_: None)
            slugs.append(slug)
            net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
            row = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", net.project_row(slug)["id"], 0x80010500)
            agent, _ = net.local_agent(f"disc-{number}")
            assert net.attempt(agent, row["name"], f'int {row["name"]}(int x) {{ return x + 7; }}', slug)["matched"]
    net.set_psx_disc_set(slugs[0], slugs, "Modified two-disc game")
    result = net.export_rom(slugs[0], log=lambda *_: None)
    assert result["identical"], result
    tree = Path(result["path"])
    source = next((tree / "shared/src").glob("*.cpp"))
    source.write_text(source.read_text().replace("+ 7", "+ 8"))
    assert main(["psx", "build", str(tree), "--mod"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["baseline_identical"] and len(report["discs"]) == 2
    for disc, original in zip(report["discs"], originals):
        assert len(disc["changed_functions"]) == 1
        output = tree / disc["artifacts"][0]["output"]
        assert output.read_bytes() != original and output.stat().st_size == len(original)
        if media == "cue":
            cue = tree / disc["artifacts"][1]["output"]
            assert (cue.parent / "tracks/data.bin") == output
            assert 'tracks/data.bin' in cue.read_text()
    assert main(["psx", "build", str(tree)]) == 1
    disc_two = tree / "discs/disc-2"
    meta = json.loads((disc_two / "build.json").read_text())
    (disc_two / meta["disc"]["image"]).write_bytes(b"corrupted original")
    assert main(["psx", "build", str(tree), "--mod"]) == 1
    assert not (tree / "build/mod").exists()


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
def test_reviewed_archive_fragment_modification_requires_raw_unrelocated_storage(tmp_path):
    from .test_psx_layout import fixture as archived_fixture
    from decompnet.rom import psx_layout
    original, review, _ = archived_fixture(tmp_path)
    picked = detect.identify(original)
    psx_layout.apply(picked, original, review)
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    path, output = tmp_path / "original.iso", tmp_path / "modified.iso"
    path.write_bytes(original)
    for mapping in layout["maps"][1:]:
        changed = bytearray(image)
        changed[mapping["analysis_offset"] + mapping["size"] - 4] ^= 1
        if mapping["codec"] == "raw":
            assert psx_modify.rebuild(path, changed, layout, output)["changed_sectors"] == 1
            assert output.read_bytes() != original
        else:
            with pytest.raises(RomError, match="storage/loader authoring adapter"):
                psx_modify.rebuild(path, changed, layout, output)
            assert not output.exists()
    with pytest.raises(RomError, match="separate output path"):
        psx_modify.rebuild(path, image, layout, path)
    assert path.read_bytes() == original
