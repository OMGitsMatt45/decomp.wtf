"""Reviewed boot resources stay data and share canonical source module bytes."""

import hashlib

import pytest

from decompnet.rom import psx_data
from decompnet.rom.errors import RomError


def test_main_data_facts_extend_original_gp_and_bss():
    original = {"main": {"gp": 0x80188000, "bss": 0x80190000, "bss_size": 128}}
    declaration = {"main": {"data_ranges": [{"offset": 0x1000, "size": 64}]}}
    merged = psx_data.merge_facts(original, declaration)
    assert merged["main"] == {**original["main"], **declaration["main"]}
    assert "data_ranges" not in original["main"]


def test_mirror_synchronization_preserves_data_and_rejects_conflicting_independent_edits():
    original = b"metaABCDtailABCD"
    layout = {"maps": [{"analysis_offset": 12, "size": 4, "copies": [
        {"main_data": True, "analysis_offset": 4}]}]}
    changed = original[:12] + b"WXYZ"
    expected = b"metaWXYZtailWXYZ"
    assert psx_data.synchronize(original, changed, layout) == expected
    assert psx_data.synchronize(original, expected, layout) == expected
    psx_data.verify_mirrors(expected, layout)
    with pytest.raises(RomError, match="mirrors differ"):
        psx_data.verify_mirrors(changed, layout)
    with pytest.raises(RomError, match="conflicts"):
        psx_data.synchronize(original, b"metaZZZZtailWXYZ", layout)


import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom import detect, psx, psx_disc, psx_layout, psx_modify, psx_space, split
from .test_overlays import _iso, _resident_exe
from .test_psx_disc import joined
from .test_psx_module_copies import fixture as module_fixture


def fixture():
    _, _, module, _ = module_fixture()
    header, trailer = b"opaque resource metadata".ljust(64, b"\0"), b"original resource trailer".ljust(32, b"\0")
    blob = header + module + trailer
    at = 0xE00
    boot = bytearray(_resident_exe().ljust(0x2000, b"\0"))
    struct.pack_into("<I", boot, 0x1C, 0x1800)
    struct.pack_into("<I", boot, 0x14, 0x80188000)
    struct.pack_into("<II", boot, 0x28, 0x80014000, 128)
    boot[at:at + len(blob)] = blob
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": bytes(boot),
                  "CODE.BIN": module, "ARCHIVE.DAT": b"x" * 123 + module + b"\xCD" * 17})
    review = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "main_data": [
        {"offset": at, "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}], "modules": [{
        "name": "shared", "path": "CODE.BIN", "stored_size": len(module), "size": len(module),
        "codec": "raw", "load": 0x80180000, "code_end": 0x508, "copies": [
            {"path": "ARCHIVE.DAT", "offset": 123}, {"path": "GAME.EXE", "offset": at + len(header)}]}]}
    return image, review, module


def prepared(image, review):
    picked = detect.identify(image)
    psx_layout.apply(picked, image, review)
    baseline, segments = joined(picked)
    return baseline, psx_disc.bind(picked.disc, segments, baseline)


@pytest.mark.parametrize("error", ["unloaded-trailer", "boot-entry"])
def test_reviewed_main_data_requires_loaded_payload_and_preserves_the_original_boot_entry(error):
    image, review, _ = fixture()
    picked = detect.identify(image)
    boot = bytearray(picked.data)
    if error == "unloaded-trailer":
        struct.pack_into("<I", boot, 0x1C, 0x800)
    else:
        review["main_data"] = [{"offset": 0x800, "size": 8,
                                "sha256": hashlib.sha256(boot[0x800:0x808]).hexdigest()}]
    replacement = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": bytes(boot),
                        "CODE.BIN": bytes(0x800), "ARCHIVE.DAT": bytes(0x1000)})
    review["sha256"] = hashlib.sha256(replacement).hexdigest()
    with pytest.raises(RomError, match="loaded boot payload|boot entry"):
        psx_layout.apply(detect.identify(replacement), replacement, review)


@pytest.mark.parametrize("error", ["hash", "header", "alignment", "outside", "overlap", "fields", "missing", "boot-offset", "relocated"])
def test_boot_aliases_require_reviewed_data_identity_bounds_and_raw_storage(error):
    image, review, _ = fixture()
    data = review["main_data"][0]
    if error == "hash": data["sha256"] = "0" * 64
    elif error == "header": data["offset"] = 0
    elif error == "alignment": data["size"] -= 1
    elif error == "outside": data["size"] = 1 << 20
    elif error == "overlap": review["main_data"].append(copy.deepcopy(data))
    elif error == "fields": data["reason"] = "unreviewed field"
    elif error == "missing": review.pop("main_data")
    elif error == "boot-offset": review["modules"][0]["copies"][1]["offset"] = 0x800
    elif error == "relocated": review["modules"][0]["relocations"] = [{"offset": 8, "type": "R_MIPS_26", "value": 0x80180508}]
    with pytest.raises(RomError):
        psx_layout.apply(detect.identify(image), image, review)


def test_boot_copy_rebuild_requires_coherent_analysis_and_preserves_other_blob_bytes(tmp_path):
    image, review, module = fixture()
    baseline, layout = prepared(image, review)
    original, output = tmp_path / "original.iso", tmp_path / "output.iso"
    original.write_bytes(image)
    assert psx_disc.analysis(original, layout) == baseline
    psx_disc.rebuild(original, baseline, layout, output)
    assert output.read_bytes() == image
    mapping = layout["maps"][1]
    mirror = mapping["copies"][1]["analysis_offset"]
    changed = bytearray(baseline)
    changed[mapping["analysis_offset"] + 0x504] ^= 1
    with pytest.raises(RomError, match="mirrors differ"):
        psx_modify.rebuild(original, changed, layout, output)
    changed = psx_data.synchronize(baseline, changed, layout)
    assert changed[mirror:mirror + len(module)] == changed[mapping["analysis_offset"]:mapping["analysis_offset"] + len(module)]
    result = psx_modify.rebuild(original, changed, layout, output)
    assert set(result["files"]) == {"GAME.EXE", "CODE.BIN", "ARCHIVE.DAT"}
    with output.open("rb") as stream:
        disc = psx._Disc(stream)
        boot = disc.find("GAME.EXE")
        expected = bytearray(baseline[:layout["maps"][0]["size"]])
        expected[mirror + 0x504] ^= 1
        assert boot == expected
        assert disc.find("CODE.BIN")[0x504] == module[0x504] ^ 1
        assert disc.find("ARCHIVE.DAT")[123 + len(module):] == b"\xCD" * 17


def test_main_data_classification_preserves_previous_data_and_rejects_direct_code_entries():
    cfg = {"segments": [{"name": "main", "type": "code", "start": 0x800, "vram": 0x80010000,
        "subsegments": [[0x800, "c", "main"], [0x1000, "data", "tail"]]}, [0x1800]]}
    ranges = [{"offset": 0xE00, "size": 0x400}]
    psx_data.classify(cfg, ranges)
    assert [entry[:2] for entry in cfg["segments"][0]["subsegments"]] == [
        [0x800, "c"], [0xE00, "data"], [0x1000, "data"], [0x1200, "data"]]
    function = split.RomFunction("real", 0x80010000, 0x800, "main", [
        split.AsmLine(0x800, 0x80010000, 0x3C028001, "lui", ""),
        split.AsmLine(0x804, 0x80010004, 0x24420600, "addiu", "")], Path(), set())
    psx_data.reject_control_entries([function], ranges, 0x80010000)
    function.lines[0].word = 0x0C000000 | (0x80010600 >> 2 & 0x3FFFFFF)
    with pytest.raises(RomError, match="control flow enters"):
        psx_data.reject_control_entries([function], ranges, 0x80010000)


def test_reviewed_data_cannot_be_claimed_as_zero_filled_growth_space():
    image, review, _ = fixture()
    baseline, layout = prepared(image, review)
    assert baseline[0xE20:0xE30] == bytes(16)
    meta = {"segments": [{"name": "main", "kind": "code", "start": 0x800, "end": 0x2000, "vram": 0x80010000}],
            "disc": {"layout": layout}, "functions": []}
    declaration = {"format": 1, "sha256": hashlib.sha256(baseline).hexdigest(), "modules": [
        {"module": "main", "start": 0x80010620, "size": 16}]}
    with pytest.raises(ValueError, match="loaded resource data"):
        psx_space.validate(meta, baseline, declaration)


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers")
def test_boot_resources_have_one_canonical_cpp_target_and_mod_analysis_mirrors_stay_consistent(tmp_path):
    image, review, module = fixture()
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, reviewed_layout=review, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    project = net.project_row(slug)
    facts = net.cfg(project)["psx_modules"]["main"]
    assert facts["gp"] == 0x80188000 and facts["bss"] == 0x80014000 and facts["bss_size"] == 128
    data = review["main_data"][0]
    assert not net.store.all("SELECT * FROM functions WHERE project_id=? AND unit='main' AND rom_offset>=? AND rom_offset<?",
                             project["id"], data["offset"], data["offset"] + data["size"])
    targets = net.store.all("SELECT * FROM functions WHERE project_id=? AND vram=?", project["id"], 0x80180500)
    assert len(targets) == 1
    fn = targets[0]
    agent, _ = net.local_agent("canonical-recovery")
    source = f"int {fn['name']}(int x) {{ return x + 7; }}"
    assert net.attempt(agent, fn["name"], source, slug)["matched"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    root = Path(exported["path"])
    meta = json.loads((root / "build.json").read_text())
    for folder in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(root / folder, ignore_errors=True)
    built = subprocess.run([sys.executable, "build.py"], cwd=root, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stdout + built.stderr
    record = next(f for f in meta["functions"] if f["name"] == fn["name"])
    (root / "src" / record["seg"] / (fn["name"] + ".cpp")).write_text(source.replace("+ 7", "+ 8"))
    assert main(["psx", "build", str(root), "--mod"]) == 0
    layout = meta["disc"]["layout"]
    modified = (root / "build/psx-mod/program.exe").read_bytes()
    psx_data.verify_mirrors(modified, layout)
    owner = layout["maps"][1]
    mirror = next(c["analysis_offset"] for c in owner["copies"] if c.get("main_data"))
    assert struct.unpack_from("<I", modified, mirror + 0x504)[0] == 0x24820008
    report = json.loads((root / "build/psx-mod-result.json").read_text())
    with (root / report["artifacts"][0]["output"]).open("rb") as stream:
        disc = psx._Disc(stream)
        assert struct.unpack_from("<I", disc.find("GAME.EXE"), mirror + 0x504)[0] == 0x24820008
        assert disc.find("CODE.BIN") == modified[owner["analysis_offset"]:owner["analysis_offset"] + len(module)]
