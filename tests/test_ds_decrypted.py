"""Explicit processed/decrypted DS images keep their bytes and retained secure CRC metadata."""

import hashlib
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.forks import scratch_dsd
from decompnet.forks.project import ForkProject
from .test_ds_encrypted import encrypted  # original fixture and generated non-console key only

pytestmark = pytest.mark.skipif(
    any(toolchains.installed(t) is None for t in ("mwccarm", "dsd", "objdiff-cli")) or
    (sys.platform != "win32" and not toolchains.installed("wibo")), reason="needs native DS tools")


@pytest.fixture
def processed(encrypted, tmp_path):
    game, _ = encrypted
    seed = tmp_path / "seed"
    shutil.copytree(game.parent / "seed", seed)
    cfg = seed / "arm9/arm9.yaml"
    cfg.write_text(cfg.read_text().replace("encrypted: true", "encrypted: false"))
    output = tmp_path / "processed.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                    "--rom", str(output)], check=True, capture_output=True)
    data = bytearray(output.read_bytes())
    # Preserve the two original BIOS wrappers at +8..+16. Replace marker/padding
    # with deterministic original data so the content heuristic guesses encryption.
    offset = struct.unpack_from("<I", data, 0x20)[0]
    pad = bytearray(hashlib.shake_256(b"original processed secure-area test data").digest(0x800))
    pad[8:16] = data[offset + 8:offset + 16]
    data[offset:offset + 0x800] = pad
    data[0x6C:0x6E] = game.read_bytes()[0x6C:0x6E]  # retained pre-processing checksum
    struct.pack_into("<H", data, 0x15E, scratch_dsd.crc16(data[:0x15E]))
    output.write_bytes(data)
    return output


def test_explicit_decrypted_input_rebuilds_without_a_bios_and_survives_clean_setup(processed, tmp_path, monkeypatch):
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(tmp_path / "must-not-be-opened.bin"))
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(processed, toolchain="DS/2.0/sp1p5", ds_input_format="decrypted", confirmed=True,
                          log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    assert net.overview(slug)["rebuild"]["identical"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == processed.read_bytes()
    assert not (root / "extract/arm7_bios.bin").exists()
    assert "--arm7-bios" not in (root / "build.ninja").read_text()
    # Standalone builds need only their retained format setting and owner's ROM.
    standalone = tmp_path / "standalone with spaces"
    shutil.copytree(root, standalone, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json",
                                                                   ".ninja_*", ".decomp-wtf"))
    shutil.rmtree(standalone / "extract/adqe")
    project = ForkProject(standalone)
    assert project.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
    ok, log = project.run(["ninja"], timeout=120)
    assert ok, log
    assert (standalone / "build/adqe/adqe.nds").read_bytes() == processed.read_bytes()
    # Header serialization must not hide code/data changes from the strict check.
    built = standalone / "build/adqe/adqe.nds"
    data = bytearray(built.read_bytes())
    data[0x4004] ^= 1
    built.write_bytes(data)
    assert not scratch_dsd.check_rom(standalone, "adqe", log=lambda *_: None)["identical"]


def test_decrypted_selection_is_not_an_automatic_wrong_key_fallback(processed, tmp_path, monkeypatch):
    monkeypatch.delenv("DECOMP_ARM7_BIOS", raising=False)
    root = tmp_path / "strict"
    with pytest.raises(Exception, match="ARM7 BIOS"):
        scratch_dsd.create(root, processed, compiler="DS/2.0/sp1p5")
