"""Original protected overlay vector, using ds-rom's public MIT-licensed V1 signatures.

No retail instructions or keys. The toolkit encrypts our two-instruction function,
then the normal importer decodes it and must reproduce all protected bytes.
"""

import json
import shutil
import struct
import subprocess
from pathlib import Path

import yaml

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom.dsprot import SIGNATURES
from .test_ds_encrypted import encrypted, pytestmark


def test_protected_overlay_is_decoded_and_reencrypted_exactly(encrypted, tmp_path, monkeypatch):
    game, bios = encrypted
    seed = tmp_path / "protected seed"
    shutil.copytree(game.parent / "seed", seed)
    table = seed / "arm9/overlays.yaml"
    config = json.loads(table.read_text())
    overlay = config["overlays"][0]
    address, key = overlay["base_address"], 0xEB000001
    plain = bytearray(0x60)
    struct.pack_into("<7I", plain, 0, 0xE92D0001, 0xE1A0000F, 0xE2800010, 0xE1A00000,
                     0xE8BD0001, 0xEA000000, key)
    recovered = struct.pack("<2I", 0xE3A00007, 0xE12FFF1E)
    plain[0x1C:0x24] = recovered
    struct.pack_into("<I", plain, 0x24, key)
    plain[0x40:0x58] = SIGNATURES["1.00"]
    (seed / "arm9" / overlay["file_name"]).write_bytes(plain)
    overlay.update(code_size=len(plain), bss_size=4, ctor_start=0, ctor_end=0,
                   dsprot={"unencrypted": {"version": "1.00", "encrypted_ranges": [
                       {"start_address": address + 0x1C, "end_address": address + 0x24, "seed_key": key}]}})
    table.write_text(json.dumps(config))
    protected = tmp_path / "protected.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                    "--rom", str(protected), "--arm7-bios", str(bios)], check=True, capture_output=True)
    # The full ROM actually contains encrypted instructions, not a plaintext
    # fixture that happens to carry a metadata label.
    from decompnet.rom.nds_modules import NdsImage
    stored = NdsImage.read(protected).code("arm9:ov0")
    assert stored[0x1C:0x24] != recovered
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    net.forks.background_links = False
    slug = net.import_rom(protected, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    extracted = root / "extract/adqe/arm9"
    table = yaml.load((extracted / "overlays.yaml").read_text(), Loader=yaml.BaseLoader)
    decoded = next(o for o in table["overlays"] if int(o["id"]) == 0)
    assert (extracted / decoded["file_name"]).read_bytes()[0x1C:0x24] == recovered
    assert (root / "build/adqe/adqe.nds").read_bytes() == protected.read_bytes()
    metadata = (root / "build/adqe/build/arm9_overlays.yaml").read_text()
    assert '1.00' in metadata and "encrypted_ranges" in metadata
