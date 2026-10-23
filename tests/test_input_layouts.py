"""Unsupported utility layouts should explain the input issue before tool setup."""

import struct

import pytest

from decompnet.forks import scratch_dsd
from decompnet.forks.project import ForkError
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError


@pytest.mark.parametrize("table", [(0, 0), (0x300, 4), (0x400, 32)])
def test_ds_table_requirements_are_checked_before_compiler_setup(tmp_path, monkeypatch, table):
    rom = bytearray(0x400)
    rom[:12] = b"BOOT UTILITY"
    struct.pack_into("<IIII", rom, 0x20, 0x200, 0x02000000, 0x02000000, 4)
    struct.pack_into("<II", rom, 0x40, *table)
    struct.pack_into("<H", rom, 0x15E, scratch_dsd.crc16(rom[:0x15E]))
    path = tmp_path / "boot.nds"
    path.write_bytes(rom)
    monkeypatch.setattr(scratch_dsd, "versions", lambda: pytest.fail("input validation must precede compiler setup"))
    reason = "no Nitro filesystem" if table[1] == 0 else "file name table"
    with pytest.raises(ForkError, match=reason):
        scratch_dsd.create(tmp_path / "project", path)
    assert not (tmp_path / "project").exists()


def test_apploader_only_gamecube_disc_is_identified_before_extraction(tmp_path, monkeypatch):
    head = bytearray(0x440)
    head[:6] = b"GTEST0"
    struct.pack_into(">I", head, 0x1C, 0xC2339F3D)
    path = tmp_path / "boot.iso"
    path.write_bytes(head)
    net = RomNetwork(tmp_path/'app.db',tmp_path/'projects')
    monkeypatch.setattr(scratch_dsd,"versions",lambda: pytest.fail("retired input must not start tool setup"))
    with pytest.raises(NetworkError, match="removed"):
        net.import_rom(path,confirmed=True)
    assert not (tmp_path/'projects').exists()
