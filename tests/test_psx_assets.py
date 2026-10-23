"""Resource growth, loader fields, CUE tracks and combined source builds."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom import detect, psx_assets, psx_disc, psx_media, psx_hbd
from decompnet.rom.n64 import RomError
from .test_psx_disc import fixture, joined
from .test_psx_modify import valid_raw
from .test_psx_media import original_chd
from .test_psx_set import fixtures
from .test_psx_hbd import archive
from .test_overlays import _iso, _resident_exe


@pytest.mark.parametrize("kind", ["iso", "mode2"])
def test_independent_iso_library_reads_nested_resized_file_and_volume_bounds(tmp_path, kind):
    import pycdlib
    filesystem = pycdlib.PyCdlib()
    filesystem.new(interchange_level=1, vol_ident="ORIGINAL")
    filesystem.add_directory("/DATA")
    contents = {"/SYSTEM.CNF;1": b"BOOT=cdrom:\\GAME.EXE;1\n", "/GAME.EXE;1": _resident_exe(),
                "/DATA/CONTENT.BIN;1": b"old resource"}
    for name, data in contents.items():
        filesystem.add_fp(io.BytesIO(data), len(data), iso_path=name)
    image = io.BytesIO()
    filesystem.write_fp(image)
    filesystem.close()
    root, meta, _, output = exported(tmp_path, kind, image.getvalue())
    replacement = tmp_path / "replacement.bin"
    data = b"independently read resource " * 500
    replacement.write_bytes(data)
    psx_assets.stage(root, "DATA/CONTENT.BIN", replacement, relocate=True)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    raw = output.read_bytes()
    # Decode raw sector payloads independently of the project's disc reader.
    iso_bytes = raw if kind == "iso" else b"".join(raw[at + 24:at + 24 + 2048] for at in range(0, len(raw), 2352))
    independent = pycdlib.PyCdlib()
    independent.open_fp(io.BytesIO(iso_bytes))
    rebuilt = io.BytesIO()
    independent.get_file_from_iso_fp(rebuilt, iso_path="/DATA/CONTENT.BIN;1")
    record = independent.get_record(iso_path="/DATA/CONTENT.BIN;1")
    assert rebuilt.getvalue() == data
    assert record.extent_location() == report["files"][0]["lba"]
    assert independent.pvd.space_size == len(iso_bytes) // 2048
    independent.close()


def exported(tmp_path, kind="iso", image=None):
    image = image or fixture()
    source = tmp_path / "input"
    source.mkdir()
    if kind == "cue":
        (source / "tracks").mkdir()
        data = bytes(150 * 2352) + valid_raw(image, 2352, 24)
        count = len(data) // 2352
        audio = bytes(range(256)) * (2352 * 12 // 256) + bytes(2352 * 12 % 256)
        (source / "tracks/data.bin").write_bytes(data + audio)
        path = source / "disc.cue"
        path.write_text('FILE "tracks/data.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 00 00:00:00\n INDEX 01 00:02:00\n'
                        f' TRACK 02 AUDIO\n INDEX 00 {count // 4500:02}:{count // 75 % 60:02}:{count % 75:02}\n'
                        f' INDEX 01 {(count + 4) // 4500:02}:{(count + 4) // 75 % 60:02}:{(count + 4) % 75:02}\n')
    else:
        data = image if kind == "iso" else valid_raw(image, 2448 if kind in ("chd", "raw2448") else 2352, 16 if kind == "mode1" else 24)
        path = source / ("disc.chd" if kind == "chd" else "disc.bin")
        path.write_bytes(original_chd(data, compressed=True) if kind == "chd" else data)
    picked = detect.identify(path)
    root = tmp_path / "exported"
    root.mkdir()
    primary = psx_media.snapshot(path, picked, root)
    analysis, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, analysis)
    meta = {"platform": "psx", "disc": {"image": primary.name, "layout": layout}}
    (root / "build.json").write_text(json.dumps(meta))
    output = root / "build/psx-mod" / ("disc/tracks/data.bin" if kind == "cue" else "disc.chd" if kind == "chd" else "disc.bin")
    output.parent.mkdir(parents=True)
    shutil.copyfile(primary, output)
    if kind == "cue":
        psx_media.companions(primary, layout, output.parent.parent)
    return root, meta, primary, output


@pytest.mark.parametrize("kind", ["iso", "mode1", "mode2", "raw2448", "cue"])
def test_resource_relocation_updates_directory_volume_and_preserves_other_files_and_audio(tmp_path, kind):
    root, meta, original, output = exported(tmp_path, kind)
    before = original.read_bytes()
    replacement = tmp_path / "replacement.bin"
    data = b"replacement resource" * 600
    replacement.write_bytes(data)
    with pytest.raises(RomError, match="relocate"):
        psx_assets.stage(root, "MUSIC.VAB", replacement)
    psx_assets.stage(root, "MUSIC.VAB", replacement, relocate=True)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    assert report["insert_frames"] == (len(data) + 2047) // 2048
    assert output.stat().st_size == len(before) + report["insert_frames"] * meta["disc"]["layout"]["sector_size"]
    with psx_assets.opened(output, meta["disc"]["layout"]) as (disc, _), psx_assets.opened(original, meta["disc"]["layout"]) as (old, _):
        assert disc.find("MUSIC.VAB") == data
        for name in ("DEMOQ_PS1.EXE", "BATTLE.BIN", "FIELD.EXE"):
            assert disc.find(name) == old.find(name)
        assert int.from_bytes(disc.sector(16)[80:84], "little") == report["insert_lba"] + report["insert_frames"]
    if kind == "cue":
        cut = 150 * 2352 + report["insert_lba"] * 2352
        after = output.read_bytes()
        assert after[:150 * 2352] == before[:150 * 2352]
        assert after[cut + report["insert_frames"] * 2352:] == before[cut:]
        cue = output.parent.parent / "disc.cue"
        cut_before, _ = psx_assets.cue_shift((original.parent / "original-media/disc.cue").read_bytes(), "tracks/data.bin", 0)
        cut_after, _ = psx_assets.cue_shift(cue.read_bytes(), "tracks/data.bin", 0)
        assert cut_after - cut_before == report["insert_frames"]
    assert original.read_bytes() == before


@pytest.mark.parametrize("kind", ["iso", "chd"])
def test_in_place_resize_preserves_chd_and_resource_tail_and_rejects_stale_declarations(tmp_path, kind):
    root, meta, original, output = exported(tmp_path, kind)
    replacement = tmp_path / "replacement.bin"
    data = b"smaller resource" * 123
    replacement.write_bytes(data)
    psx_assets.stage(root, "MUSIC.VAB", replacement)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    assert report["insert_frames"] == 0
    with psx_assets.opened(output, meta["disc"]["layout"]) as (disc, _):
        assert disc.find("MUSIC.VAB") == data
    declaration = root / "psx-assets.json"
    wrong = json.loads(declaration.read_text())
    wrong["sha256"] = "00" * 32
    declaration.write_text(json.dumps(wrong))
    with pytest.raises(RomError, match="SHA-256"):
        psx_assets.apply(root, meta, output)


def test_resource_loader_length_and_lba_fields_are_updated_and_bound_to_original(tmp_path):
    from .test_overlays import _iso, _resident_exe
    import struct
    images = {"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "DATA.BIN": b"a" * 100,
              "LOOKUP.BIN": bytes(12)}
    initial = detect.identify(_iso(images))
    rec = next(r for r in initial.disc["files"] if r["path"] == "DATA.BIN")
    images["LOOKUP.BIN"] = struct.pack("<I", rec["lba"]) + (100).to_bytes(4, "big") + (1).to_bytes(4, "little")
    root, meta, _, output = exported(tmp_path, image=_iso(images))
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"b" * 5000)
    refs = [{"file": "LOOKUP.BIN", "offset": at, "kind": kind, "width": 4, "endian": endian}
            for at, kind, endian in ((0, "lba", "little"), (4, "size", "big"), (8, "sectors", "little"))]
    psx_assets.stage(root, "DATA.BIN", replacement, relocate=True, references=refs)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    with psx_assets.opened(output, meta["disc"]["layout"]) as (disc, _):
        table = disc.find("LOOKUP.BIN")
    assert int.from_bytes(table[:4], "little") == report["files"][0]["lba"]
    assert int.from_bytes(table[4:8], "big") == 5000 and int.from_bytes(table[8:], "little") == 3
    refs[0]["offset"] = 1
    with pytest.raises(RomError, match="original value"):
        psx_assets.stage(root, "DATA.BIN", replacement, relocate=True, references=refs[:1])


@pytest.mark.parametrize("conflict", ["overlap", "self", "replaced-table"])
def test_resource_loader_conflicts_fail_before_output_changes(tmp_path, conflict):
    data = (100).to_bytes(4, "little") + bytes(96)
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(),
                  "ONE.BIN": data, "TWO.BIN": data, "LOOKUP.BIN": data})
    root, meta, _, output = exported(tmp_path, image=image)
    before = output.read_bytes()
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"new data" * 1000)
    refs = [{"file": "ONE.BIN" if conflict == "self" else "LOOKUP.BIN",
             "offset": 0, "kind": "size", "width": 4, "endian": "little"}]
    psx_assets.stage(root, "ONE.BIN", replacement, relocate=True, references=refs)
    if conflict == "overlap":
        psx_assets.stage(root, "TWO.BIN", replacement, relocate=True, references=refs)
    elif conflict == "replaced-table":
        psx_assets.stage(root, "LOOKUP.BIN", replacement, relocate=True)
    with pytest.raises(RomError, match="overlap across|cannot target"):
        psx_assets.apply(root, meta, output)
    assert output.read_bytes() == before


def test_archive_member_replacement_integrates_with_raw_sector_authoring(tmp_path):
    packed, values = archive(1)
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "DATA.HBD": packed})
    root, meta, _, output = exported(tmp_path, "mode2", image)
    replacement = tmp_path / "member.bin"
    data = values[1].replace(b"original", b"modified")
    replacement.write_bytes(data)
    psx_assets.stage(root, "DATA.HBD", replacement, sector=1, member=1)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    assert report["insert_frames"] == 0
    with psx_assets.opened(output, meta["disc"]["layout"]) as (disc, _):
        archived = disc.find("DATA.HBD")
    read = lambda at, count: archived[at:at + count]
    item = psx_hbd.block(read, len(archived), 1)
    assert psx_hbd.decoded(read, item["members"][1]) == data
    assert psx_hbd.decoded(read, item["members"][0]) == values[0]


def test_staging_replaces_links_atomically_and_cannot_truncate_the_retained_disc(tmp_path):
    root, meta, original, _ = exported(tmp_path)
    replacement = tmp_path / "resource.bin"
    replacement.write_bytes(b"first resource")
    declaration = psx_assets.stage(root, "MUSIC.VAB", replacement)
    target = root / declaration["files"][0]["source"]
    target.unlink()
    target.hardlink_to(original)
    before = original.read_bytes()
    replacement.write_bytes(b"second resource")
    psx_assets.stage(root, "MUSIC.VAB", replacement)
    assert original.read_bytes() == before and target.read_bytes() == b"second resource"


def test_export_upgrade_preserves_custom_source_and_backs_up_old_helpers(tmp_path, capsys):
    root, _, _, _ = exported(tmp_path)
    old = b"# older copied helper with local notes\n"
    (root / "psx_mod.py").write_bytes(old)
    source = root / "src/custom.cpp"
    source.parent.mkdir()
    source.write_text("int unchanged_source = 7;\n")
    replacement = tmp_path / "resource.bin"
    replacement.write_bytes(b"resource")
    with pytest.raises(RomError, match="upgrade"):
        psx_assets.stage(root, "MUSIC.VAB", replacement)
    assert main(["psx", "upgrade", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["updated"] == ["psx_mod.py"]
    assert next(root.glob("psx_mod.py.before-upgrade-*")).read_bytes() == old
    assert source.read_text() == "int unchanged_source = 7;\n"
    psx_assets.stage(root, "MUSIC.VAB", replacement)


@pytest.mark.parametrize("damage", ["audio", "cue"])
def test_resource_verification_rejects_corrupted_audio_and_cue(tmp_path, damage):
    root, meta, _, output = exported(tmp_path, "cue")
    replacement = tmp_path / "resource.bin"
    replacement.write_bytes(b"new content" * 1000)
    psx_assets.stage(root, "MUSIC.VAB", replacement, relocate=True)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    if damage == "audio":
        with output.open("r+b") as stream:
            stream.seek(-10, 2)
            stream.write(b"corruption")
    else:
        (output.parent.parent / "disc.cue").write_text("corrupted CUE")
    with pytest.raises(RomError, match="audio|CUE"):
        psx_assets.verify(root, meta, output, report)


@pytest.mark.parametrize("subcode", ["zero", "opaque"])
def test_chd_track_growth_preserves_audio_pregap_and_metadata_and_refuses_opaque_retiming(tmp_path, subcode):
    from decompnet.rom.chd import Chd
    from decompnet.rom.chd_write import rewrite
    from decompnet.rom.psx_chd_tracks import tracks
    source = Path(__file__).parent / "fixtures/psx-chd/cdfl.chd"
    prepared = tmp_path / "prepared.chd"
    if subcode == "zero":
        rewrite(source, prepared, {frame * 2448 + 2352: bytes(96) for frame in range(32, 68)})
    else:
        shutil.copyfile(source, prepared)
    picked = detect.identify(prepared)
    image, segments = joined(picked)
    root = tmp_path / "export"
    root.mkdir()
    original = psx_media.snapshot(prepared, picked, root)
    layout = psx_disc.bind(picked.disc, segments, image)
    meta = {"platform": "psx", "disc": {"image": original.name, "layout": layout}}
    (root / "build.json").write_text(json.dumps(meta))
    output = root / "build/psx-mod/disc.chd"
    output.parent.mkdir(parents=True)
    shutil.copyfile(original, output)
    replacement = tmp_path / "new-resource.bin"
    replacement.write_bytes(b"new content" * 1000)
    psx_assets.stage(root, "MUSIC.VAB", replacement, relocate=True)
    before = output.read_bytes()
    if subcode == "opaque":
        with pytest.raises(RomError, match="raw subcode"):
            psx_assets.apply(root, meta, output)
        assert output.read_bytes() == before
        return
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    assert report["insert_frames"] == 8
    with Chd(original) as old, Chd(output) as new:
        old_tracks, new_tracks = tracks(old), tracks(new)
        assert old_tracks[0]["frames"] == 30 and new_tracks[0]["frames"] == 38
        assert old_tracks[1] == new_tracks[1]
        old.seek(32 * 2448)
        new.seek(40 * 2448)
        assert new.read() == old.read()
        for (tag, flags, data), (new_tag, new_flags, new_data) in zip(old.metadata, new.metadata):
            assert (tag, flags) == (new_tag, new_flags)
            if b"TRACK:1 " not in data:
                assert new_data == data
            else:
                assert new_data == data.replace(b"FRAMES:30", b"FRAMES:38")


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("kind", ["iso", "cue", "chd"])
def test_combined_console_build_publishes_resized_resources_and_cleans_all_discs_on_failure(tmp_path, capsys, kind):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slugs = []
    for number, image in enumerate(fixtures(tmp_path)):
        if kind in ("cue", "chd"):
            folder = tmp_path / f"disc-{number}"
            folder.mkdir()
            if kind == "cue":
                (folder / "track.bin").write_bytes(valid_raw(image, 2352, 24))
                image = folder / "disc.cue"
                image.write_text('FILE "track.bin" BINARY\n TRACK 01 MODE2/2352\n INDEX 01 00:00:00\n')
            else:
                from decompnet.rom.chd import overall_sha1
                raw = valid_raw(image, 2448, 24)
                frames = len(raw) // 2448
                raw = raw.ljust((frames + 3) // 4 * 4 * 2448, b"\0")
                container = bytearray(original_chd(raw, compressed=True))
                text = f"TRACK:1 TYPE:MODE2_RAW SUBTYPE:RW_RAW FRAMES:{frames} PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:0\0".encode()
                offset = len(container)
                container += b"CHT2\x01" + len(text).to_bytes(3, "big") + bytes(8) + text
                container[48:56] = offset.to_bytes(8, "big")
                container[64:84] = hashlib.sha1(raw).digest()
                container[84:104] = overall_sha1(bytes(container[64:84]), [(b"CHT2", 1, text)])
                image = folder / "disc.chd"
                image.write_bytes(container)
        slug = net.import_rom(image, confirmed=True, log=lambda *_: None)
        net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
        project = net.project_row(slug)
        fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", project["id"], 0x80010500)
        agent, _ = net.local_agent(f"disc-{number}")
        assert net.attempt(agent, fn["name"], f"int {fn['name']}(int x) {{ return x + 7; }}", slug)["matched"]
        slugs.append(slug)
    net.set_psx_disc_set(slugs[0], slugs, "Resource authoring game")
    result = net.export_rom(slugs[0], log=lambda *_: None)
    assert result["identical"], result
    root = Path(result["path"])
    shared = next((root / "shared/src").glob("*.cpp"))
    shared.write_text(shared.read_text().replace("+ 7", "+ 8"))
    data = tmp_path / "replacement.bin"
    data.write_bytes(b"resized resource" * 500)
    for number in (1, 2):
        assert main(["psx", "replace", str(root / f"discs/disc-{number}"), "--file", "DATA.BIN", "--input", str(data), "--relocate"]) == 0
        capsys.readouterr()
    assert main(["psx", "build", str(root), "--mod"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["discs"]) == 2
    assert all(d["disc"]["assets"]["insert_frames"] > 0 for d in report["discs"])
    assert all(len(d["changed_functions"]) == 1 for d in report["discs"])
    declaration = root / "discs/disc-2/psx-assets.json"
    bad = json.loads(declaration.read_text())
    bad["sha256"] = "00" * 32
    declaration.write_text(json.dumps(bad))
    assert main(["psx", "build", str(root), "--mod"]) == 1
    assert not (root / "build/mod").exists()
