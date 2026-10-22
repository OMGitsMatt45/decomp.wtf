"""Original protected overlay vector, using ds-rom's public MIT-licensed V1 signatures.

No retail instructions or keys. The toolkit encrypts our two-instruction function,
then the normal importer decodes it and must reproduce all protected bytes.
"""

import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom.dsprot import SIGNATURES
from decompnet.forks.project import ForkProject
from decompnet.forks import scratch_dsd
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
    extracted = root / "extract/adqe"
    config = yaml.safe_load((extracted / "config.yaml").read_text())
    overlay_path = extracted / config["arm9_overlays"]
    table = yaml.load(overlay_path.read_text(), Loader=yaml.BaseLoader)
    decoded = next(o for o in table["overlays"] if int(o["id"]) == 0)
    assert (overlay_path.parent / decoded["file_name"]).read_bytes()[0x1C:0x24] == recovered
    assert (root / "build/adqe/adqe.nds").read_bytes() == protected.read_bytes()
    metadata = (root / "build/adqe/build/arm9_overlays.yaml").read_text()
    assert '1.00' in metadata and "encrypted_ranges" in metadata


@pytest.mark.parametrize("module", ["arm7", "arm7:autoload0", "arm7:ov0"])
@pytest.mark.parametrize("language", ["c", "c++"])
def test_protected_arm7_sources_are_decoded_linked_and_reencrypted(encrypted, tmp_path, monkeypatch, module, language):
    game, bios = encrypted
    seed = tmp_path / "protected ARM7 seed"
    shutil.copytree(game.parent / "seed", seed)
    base = {"arm7": 0x02380000, "arm7:autoload0": 0x037F8000, "arm7:ov0": 0x02390000}[module]
    table = seed / "arm9/overlays.yaml"
    config = json.loads(table.read_text())
    overlay = config["overlays"][0]
    plain = bytearray(0x60)
    key = 0xEB000001
    struct.pack_into("<7I", plain, 0, 0xE92D0001, 0xE1A0000F, 0xE2800010, 0xE1A00000,
                     0xE8BD0001, 0xEA000000, key)
    recovered = struct.pack("<2I", 0xE3A00007, 0xE12FFF1E)
    plain[0x1C:0x24] = recovered
    struct.pack_into("<I", plain, 0x24, key)
    plain[0x40:0x58] = SIGNATURES["1.00"]
    (seed / "arm9" / overlay["file_name"]).write_bytes(plain)
    overlay.update(base_address=base, code_size=len(plain), bss_size=4, ctor_start=0, ctor_end=0,
                   dsprot={"unencrypted": {"version": "1.00", "encrypted_ranges": [
                       {"start_address": base + 0x1C, "end_address": base + 0x24, "seed_key": key}]}})
    table.write_text(json.dumps(config))
    encrypted_vector = tmp_path / "vector.nds"
    dsd = str(toolchains.binary("dsd"))
    subprocess.run([dsd, "rom", "build", "--config", str(seed / "config.yaml"), "--rom", str(encrypted_vector),
                    "--arm7-bios", str(bios)], check=True, capture_output=True)
    from decompnet.rom.nds_modules import NdsImage
    cipher = NdsImage.read(encrypted_vector).code("arm9:ov0")
    assert cipher[0x1C:0x24] != recovered
    # Remove the codec vector from ARM9; the tested protection now lives solely
    # in the ARM7 program, a copied runtime block, or an ARM7 overlay.
    shutil.copytree(game.parent / "seed/arm9", seed / "arm9", dirs_exist_ok=True)
    if module == "arm7":
        (seed / "arm7/arm7.bin").write_bytes(cipher)
        config_path = seed / "arm7/arm7.yaml"
        info = yaml.safe_load(config_path.read_text())
        info["entry_function"] = base + 0x1C
        config_path.write_text(yaml.safe_dump(info))
    elif module == "arm7:autoload0":
        loader = bytearray(0x40)
        struct.pack_into("<3I", loader, 0, 0xE59F0000, 0xE12FFF1E, 0x02380020)
        struct.pack_into("<5I", loader, 0x20, 0x023800A0, 0x023800AC, 0x02380040, 0x02380100, 0x02380110)
        (seed / "arm7/arm7.bin").write_bytes(loader + cipher + struct.pack("<3I", base, len(cipher), 16))
    else:
        (seed / "arm7/ov000.bin").write_bytes(cipher)
        table = seed / "arm7/overlays.yaml"
        info = json.loads(table.read_text())
        info["overlays"][0].update(code_size=len(cipher), ctor_start=0, ctor_end=0)
        table.write_text(json.dumps(info))
    protected = tmp_path / "protected ARM7.nds"
    subprocess.run([dsd, "rom", "build", "--config", str(seed / "config.yaml"), "--rom", str(protected),
                    "--arm7-bios", str(bios)], check=True, capture_output=True)
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    net.forks.background_links = False
    slug = net.import_rom(protected, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    manifest = json.loads((root / "config/adqe/arm7/units.json").read_text())
    unit = next(u for u in manifest["units"] if u["module"] == module and u["address"] == base + 0x1C)
    reference = manifest["modules"][module]
    assert (root / reference["binary"]).read_bytes()[reference["source_offset"] + 0x1C:reference["source_offset"] + 0x24] == recovered
    agent, _ = net.local_agent("protected-arm7-owner")
    net.forks.configure_arm7_unit(agent, slug, unit["source"], language=language)
    source = str(Path(unit["source"]).with_suffix(".cpp" if language == "c++" else ".c")).replace("\\", "/")
    result = net.attempt(agent, unit["symbol"], ("extern \"C\" " if language == "c++" else "") +
                         f"int {unit['symbol']}(void) {{ return 7; }}", slug)
    assert result["matched"], result["text"]
    linked = net.forks.link(slug, log=lambda *_: None)
    assert source in linked["linked"], linked
    assert (root / "build/adqe/adqe.nds").read_bytes() == protected.read_bytes()
    if module == "arm7:autoload0" and language == "c++":
        clean = tmp_path / "standalone protected ARM7 with spaces"
        shutil.copytree(root, clean, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json", ".ninja_*"))
        shutil.rmtree(clean / "extract/adqe")
        fp = ForkProject(clean)
        assert fp.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
        ok, log = fp.run(["ninja"], timeout=120)
        assert ok, log
        assert (clean / "build/adqe/adqe.nds").read_bytes() == protected.read_bytes()
    if module == "arm7" and language == "c":
        from decompnet.forks.ds_template.tools import arm7_codec
        with monkeypatch.context() as failed_codec:
            def refuse(*args):
                raise ValueError("original malformed protection-layout fixture")
            failed_codec.setattr(arm7_codec, "decode", refuse)
            retained = RomNetwork(tmp_path / "retained.db", tmp_path / "retained projects")
            retained.forks.background_links = False
            retained_slug = retained.import_rom(protected, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
            retained_root = Path(retained.project_row(retained_slug)["root"])
            recorded = json.loads((retained_root / "config/adqe/arm7/units.json").read_text())
            assert "retained" in recorded["modules"][module]["recovery_status"]
            assert not any(u["module"] == module for u in recorded["units"])
            assert (retained_root / "build/adqe/adqe.nds").read_bytes() == protected.read_bytes()
        (root / source).write_text(f"int {unit['symbol']}(void) {{ return 8; }}", encoding="utf-8")
        result = net.forks.check_rom(slug, log=lambda *_: None)
        assert not result["identical"] and "differs in .text" in result["detail"], result
        assert not (root / "build/adqe/rom.ok").exists()


@pytest.mark.parametrize("size", [0x20, 0x3C, 0x40])
@pytest.mark.parametrize("tail", [0x12345678, 0xE12FFF1E])
def test_absent_constructor_without_zero_word_rebuilds_and_detects_changes(encrypted, tmp_path, monkeypatch, size, tail):
    game, bios = encrypted
    seed = tmp_path / "absent constructor seed"
    shutil.copytree(game.parent / "seed", seed)
    table = seed / "arm9/overlays.yaml"
    config = json.loads(table.read_text())
    overlay = config["overlays"][0]
    code = bytearray(struct.pack("<I", 0x12345678) * (size // 4))
    struct.pack_into("<2I", code, 0, 0xE2800001, 0xE12FFF1E)
    if size == 0x3C:
        # A real pointer into the first BSS word must remain at its original
        # address when the analyzer's 32-byte alignment assumption is removed.
        struct.pack_into("<4I", code, 0, 0xE59F0004, 0xE5900000, 0xE12FFF1E, overlay["base_address"] + size)
    struct.pack_into("<I", code, size - 4, tail)
    assert bytes(4) not in code
    (seed / "arm9" / overlay["file_name"]).write_bytes(code)
    empty = overlay["base_address"] + 8 if tail == 0xE12FFF1E else 0
    overlay.update(code_size=size, bss_size=4, ctor_start=empty, ctor_end=empty)
    table.write_text(json.dumps(config))
    original = tmp_path / "no constructor.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                    "--rom", str(original), "--arm7-bios", str(bios)], check=True, capture_output=True)
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    net.forks.background_links = False
    slug = net.import_rom(original, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    assert (root / "build/adqe/adqe.nds").read_bytes() == original.read_bytes()
    fp = ForkProject(root)
    for command in ([str(toolchains.binary("dsd")), "check", "modules", "--config-path", "config/adqe/arm9/config.yaml", "--fail"],
                    [str(toolchains.binary("dsd")), "check", "symbols", "--config-path", "config/adqe/arm9/config.yaml",
                     "--elf-path", "build/adqe/arm9.o", "--fail"]):
        ok, log = fp.run(command)
        assert ok, log
    layout = root / "extract/adqe/retained_layout.json"
    recorded = json.loads(layout.read_text())
    assert recorded["absent_arm9_constructors"]["0"]["tail_word"] == tail
    delinks = (root / "config/adqe/arm9/overlays/ov000/delinks.txt").read_text()
    boundary = overlay["base_address"] + size - 4
    assert re.search(rf"\.ctor\s+start:0x{boundary:08x} end:0x{boundary:08x}", delinks)
    if size == 0x3C and tail == 0xE12FFF1E:
        clean = tmp_path / "clean layout with spaces"
        shutil.copytree(root, clean, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json", ".ninja_*"))
        shutil.rmtree(clean / "extract/adqe")
        standalone = ForkProject(clean)
        assert standalone.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
        ok, log = standalone.run(["ninja"], timeout=120)
        assert ok, log
        assert (clean / "build/adqe/adqe.nds").read_bytes() == original.read_bytes()
    # The linker emits retained unowned bytes. Changing them remains visible to
    # the complete-image check; there is no checksum/comparison exception.
    recorded["absent_arm9_constructors"]["0"]["tail_word"] ^= 1
    layout.write_text(json.dumps(recorded))
    (root / "build/adqe/arm9.lcf").unlink()
    result = net.forks.check_rom(slug, log=lambda *_: None)
    assert not result["identical"], result
    assert not (root / "build/adqe/rom.ok").exists()
