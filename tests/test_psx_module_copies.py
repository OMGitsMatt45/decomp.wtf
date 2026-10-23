"""Reviewed raw aliases share source targets and propagate identical module edits."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom import detect, psx, psx_assets, psx_disc, psx_layout, psx_modify
from decompnet.rom.errors import RomError
from .test_overlays import _iso, _overlay, _resident_exe
from .test_psx_disc import joined
from .test_psx_modify import valid_raw


def fixture(copies=2, *, mismatch=False, compressed=False):
    module = bytearray(_overlay(0x80180000, 40).ljust(0x510, b"\0"))
    struct.pack_into("<I", module, 8, 0x0C000000 | (0x80180500 >> 2 & 0x3FFFFFF))
    struct.pack_into("<2I", module, 0x500, 0x03E00008, 0x24820007)
    stored = zlib.compress(module) if compressed else bytes(module)
    archive, locations = bytearray(b"original opaque archive header".ljust(123, b"\0")), []
    for index in range(copies):
        locations.append({"path": "ARCHIVE.DAT", "offset": len(archive)})
        payload = bytes(module)
        if mismatch and index == 0:
            payload = bytes([payload[0] ^ 1]) + payload[1:]
        archive += payload + b"\xCD" * (17 + index % 7)
    files = {"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(),
             "CANON.BIN": stored + b"original loose file suffix", "ARCHIVE.DAT": bytes(archive)}
    image = _iso(files)
    review = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": [{
        "name": "shared", "path": "CANON.BIN", "stored_size": len(stored), "size": len(module),
        "codec": "zlib" if compressed else "raw", "load": 0x80180000, "code_end": 0x508, "copies": locations}]}
    return image, review, bytes(module), files


def prepared(image, review):
    picked = detect.identify(image)
    psx_layout.apply(picked, image, review)
    baseline, segments = joined(picked)
    return baseline, psx_disc.bind(picked.disc, segments, baseline)


@pytest.mark.parametrize("count", [0, 2, 130])
def test_copy_count_does_not_duplicate_analysis_modules_or_exceed_source_module_limit(count):
    image, review, module, _ = fixture(count)
    baseline, layout = prepared(image, review)
    assert len(layout["maps"]) == 2
    assert len(layout["maps"][1].get("copies", [])) == count
    assert len(baseline) < len(module) + len(_resident_exe()) + 32


@pytest.mark.parametrize("raw", [False, True])
def test_strict_roundtrip_and_modified_module_update_all_copies_preserving_cd_tails(tmp_path, raw):
    image, review, module, files = fixture()
    if raw:
        image = valid_raw(image, 2352, 24)
        review["sha256"] = hashlib.sha256(image).hexdigest()
    baseline, layout = prepared(image, review)
    original, exact, modified = tmp_path / "original.bin", tmp_path / "exact.bin", tmp_path / "modified.bin"
    original.write_bytes(image)
    assert psx_disc.analysis(original, layout) == baseline
    psx_disc.rebuild(original, baseline, layout, exact)
    assert exact.read_bytes() == image
    changed = bytearray(baseline)
    changed[layout["maps"][1]["analysis_offset"] + 0x504] ^= 1
    updated = bytearray(module)
    updated[0x504] ^= 1
    result = psx_modify.rebuild(original, changed, layout, modified)
    assert set(result["files"]) == {"CANON.BIN", "ARCHIVE.DAT"}
    with modified.open("rb") as stream:
        disc = psx._Disc(stream)
        assert disc.find("CANON.BIN") == bytes(updated) + files["CANON.BIN"][len(module):]
        archive = bytearray(files["ARCHIVE.DAT"])
        for location in review["modules"][0]["copies"]:
            at = location["offset"]
            archive[at:at + len(module)] = updated
        assert disc.find("ARCHIVE.DAT") == archive
    assert modified.stat().st_size == len(image)
    assert original.read_bytes() == image
    with pytest.raises(RomError, match="source-built PS1 analysis image differs"):
        psx_disc.rebuild(original, changed, layout, exact)
    assert not exact.exists()


@pytest.mark.parametrize("error", ["mismatch", "negative", "bounds", "missing", "boot", "duplicate", "canonical", "fields", "type", "limit", "compressed"])
def test_copy_review_rejects_unproved_or_overlapping_storage(error):
    image, review, _, _ = fixture(mismatch=error == "mismatch", compressed=error == "compressed")
    module, location = review["modules"][0], review["modules"][0]["copies"][0]
    if error == "negative": location["offset"] = -1
    elif error == "bounds": location["offset"] = 1 << 30
    elif error == "missing": location["path"] = "MISSING.DAT"
    elif error == "boot": location.update(path="GAME.EXE", offset=0)
    elif error == "duplicate": module["copies"].append(copy.deepcopy(location))
    elif error == "canonical": location.update(path="CANON.BIN", offset=0)
    elif error == "fields": location["size"] = module["size"]
    elif error == "type": module["copies"] = None
    elif error == "limit": module["copies"] = [location] * (psx_layout.MAX_COPIES + 1)
    with pytest.raises(RomError):
        psx_layout.apply(detect.identify(image), image, review)


@pytest.mark.parametrize("field,value", [("file_offset", 124), ("lba", 16), ("file_size", 1),
    ("stored_size", 1), ("stored_sha256", "0" * 64), ("path", "GAME.EXE"), ("analysis_offset", 0)])
def test_rebuild_rechecks_manifest_copy_bounds_identity_and_supported_fields(tmp_path, field, value):
    image, review, _, _ = fixture()
    baseline, layout = prepared(image, review)
    layout["maps"][1]["copies"][0][field] = value
    original, output = tmp_path / "original.iso", tmp_path / "output.iso"
    original.write_bytes(image)
    with pytest.raises(RomError):
        psx_modify.rebuild(original, baseline, layout, output)
    assert not output.exists() and original.read_bytes() == image


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers")
def test_one_recovered_cpp_function_clean_export_and_mod_build_all_storage_copies(tmp_path, capsys):
    image, review, module, files = fixture()
    net = RomNetwork(tmp_path / "app.db", tmp_path / "source projects")
    slug = net.import_rom(image, reviewed_layout=review, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    project = net.project_row(slug)
    functions = net.store.all("SELECT * FROM functions WHERE project_id=? AND vram=?", project["id"], 0x80180500)
    assert len(functions) == 1
    fn = functions[0]
    agent, _ = net.local_agent("shared-source-recovery")
    source = f"int {fn['name']}(int x) {{ return x + 7; }}"
    assert net.attempt(agent, fn["name"], source, slug)["matched"]
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and not result["fallback"], result
    root = Path(result["path"])
    meta = json.loads((root / "build.json").read_text())
    for directory in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(root / directory, ignore_errors=True)
    built = subprocess.run([sys.executable, "build.py"], cwd=root, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stdout + built.stderr
    assert (root / meta["disc"]["output"]).read_bytes() == image
    saved = next(item for item in meta["functions"] if item["name"] == fn["name"])
    source_path = root / "src" / saved["seg"] / (fn["name"] + ".cpp")
    source_path.write_text(source.replace("+ 7", "+ 8"))
    assert main(["psx", "build", str(root), "--mod"]) == 0
    report = json.loads((root / "build/psx-mod-result.json").read_text())
    modified = root / report["artifacts"][0]["output"]
    with modified.open("rb") as stream:
        disc = psx._Disc(stream)
        canonical = disc.find("CANON.BIN")
        assert struct.unpack_from("<I", canonical, 0x504)[0] == 0x24820008
        archive = disc.find("ARCHIVE.DAT")
        expected = bytearray(files["ARCHIVE.DAT"])
        for location in review["modules"][0]["copies"]:
            at = location["offset"]
            expected[at:at + len(module)] = canonical[:len(module)]
        assert archive == expected


def test_raw_aliases_preserve_reviewed_loader_relocation_storage(tmp_path):
    image, review, module, _ = fixture()
    review["modules"][0]["relocations"] = [{"offset": 8, "type": "R_MIPS_26", "value": 0x80180508}]
    baseline, layout = prepared(image, review)
    original, output = tmp_path / "original.iso", tmp_path / "modified.iso"
    original.write_bytes(image)
    changed = bytearray(baseline)
    changed[layout["maps"][1]["analysis_offset"] + 0x504] ^= 1
    result = psx_modify.rebuild(original, changed, layout, output)
    assert len(result["module_storage"]) == 3
    with output.open("rb") as stream:
        disc = psx._Disc(stream)
        for location in psx_layout.storage_maps(layout["maps"][1]):
            stored = disc.find(location["path"])
            at = location.get("file_offset", 0)
            assert stored[at + 8:at + 12] == module[8:12]
            assert stored[at + 0x504] == module[0x504] ^ 1


def test_rebuild_rejects_duplicate_copy_storage_even_when_its_bytes_match(tmp_path):
    image, review, _, _ = fixture()
    baseline, layout = prepared(image, review)
    mapping = layout["maps"][1]
    mapping["copies"].append(copy.deepcopy(mapping["copies"][0]))
    original = tmp_path / "original.iso"
    original.write_bytes(image)
    with pytest.raises(RomError, match="copy extents overlap"):
        psx_disc.analysis(original, layout)


def resource_project(tmp_path):
    _, review, module, files = fixture()
    files["DATA.BIN"] = b"1234567"
    header = bytearray(files["ARCHIVE.DAT"])
    header[:2] = (7).to_bytes(2, "little")
    files["ARCHIVE.DAT"] = bytes(header)
    image = _iso(files)
    review["sha256"] = hashlib.sha256(image).hexdigest()
    _, layout = prepared(image, review)
    root = tmp_path / "exported"
    root.mkdir()
    original = root / "owner.iso"
    original.write_bytes(image)
    meta = {"platform": "psx", "disc": {"image": original.name, "layout": layout}}
    (root / "build.json").write_text(json.dumps(meta))
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"123456789")
    return root, meta, original, replacement, module, review


def asset_declaration(root, meta, *, archive=False, path="DATA.BIN", references=None):
    source = root / "mod-assets/replacement.bin"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b"123456789")
    entry = {"path": path, "source": "mod-assets/replacement.bin"}
    entry.update({"sector": 0, "member": 0} if archive else {"relocate": False, "references": references or []})
    declaration = {"format": 1, "sha256": meta["disc"]["layout"]["sha256"],
                   "files": [] if archive else [entry], "archives": [entry] if archive else []}
    (root / "psx-assets.json").write_text(json.dumps(declaration))


@pytest.mark.parametrize("phase", ["stage", "apply"])
@pytest.mark.parametrize("archive", [False, True], ids=["whole-file", "archive-member"])
def test_resource_replacements_cannot_overwrite_archive_paths_with_compiled_copies(tmp_path, phase, archive):
    root, meta, original, replacement, _, _ = resource_project(tmp_path)
    before = original.read_bytes()
    if phase == "stage":
        with pytest.raises(RomError, match="mapped programs"):
            psx_assets.stage(root, "ARCHIVE.DAT", replacement, **({"sector": 0, "member": 0} if archive else {}))
        assert not (root / "psx-assets.json").exists()
    else:
        asset_declaration(root, meta, archive=archive, path="ARCHIVE.DAT")
        with pytest.raises(RomError, match="mapped program"):
            psx_assets.apply(root, meta, original)
    assert original.read_bytes() == before


@pytest.mark.parametrize("phase", ["stage", "apply"])
@pytest.mark.parametrize("site", ["canonical", "copy"])
def test_resource_loader_fields_cannot_patch_compiled_canonical_or_copy_storage(tmp_path, phase, site):
    root, meta, original, replacement, _, review = resource_project(tmp_path)
    offset = 0x504 + (review["modules"][0]["copies"][0]["offset"] if site == "copy" else 0)
    reference = {"file": "ARCHIVE.DAT" if site == "copy" else "CANON.BIN", "offset": offset,
                 "kind": "size", "width": 2, "endian": "little"}
    before = original.read_bytes()
    if phase == "stage":
        with pytest.raises(RomError, match="overlap mapped program storage"):
            psx_assets.stage(root, "DATA.BIN", replacement, references=[reference])
    else:
        asset_declaration(root, meta, references=[reference])
        with pytest.raises(RomError, match="overlap mapped program storage"):
            psx_assets.apply(root, meta, original)
    assert original.read_bytes() == before


def test_resource_loader_fields_in_archive_metadata_outside_copies_remain_supported(tmp_path):
    root, meta, original, replacement, module, review = resource_project(tmp_path)
    reference = {"file": "ARCHIVE.DAT", "offset": 0, "kind": "size", "width": 2, "endian": "little"}
    psx_assets.stage(root, "DATA.BIN", replacement, references=[reference])
    output = root / "modified.iso"
    shutil.copyfile(original, output)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    with output.open("rb") as stream:
        disc = psx._Disc(stream)
        archive = disc.find("ARCHIVE.DAT")
        assert int.from_bytes(archive[:2], "little") == 9
        for location in review["modules"][0]["copies"]:
            at = location["offset"]
            assert archive[at:at + len(module)] == module
        assert disc.find("DATA.BIN") == replacement.read_bytes()
