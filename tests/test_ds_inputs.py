"""Reject unsupported TWL containers before installing tools or creating projects."""

import struct

import pytest

from decompnet.forks import scratch_dsd
from decompnet.forks.project import ForkError


def header(unit=0, flags=0):
    data = bytearray(0x200)
    data[:12] = b"ORIGINALTEST"
    data[12:16] = b"ADQE"
    data[0x12], data[0x1C] = unit, flags
    struct.pack_into("<IIII", data, 0x20, 0x4000, 0x02000800, 0x02000000, 0x10000)
    struct.pack_into("<H", data, 0x15E, scratch_dsd.crc16(data[:0x15E]))
    return data


@pytest.mark.parametrize("unit,flags", [(2, 0), (3, 0), (0, 1), (0, 2)])
def test_twl_import_stops_before_tools_or_project_creation(tmp_path, monkeypatch, unit, flags):
    game = tmp_path / "twl.nds"
    game.write_bytes(header(unit, flags))
    monkeypatch.setattr(scratch_dsd, "versions", lambda: pytest.fail("must reject before querying compilers"))
    root = tmp_path / "project"
    assert scratch_dsd.is_nds(game.read_bytes())  # still routes to the DS importer
    with pytest.raises(ForkError, match="TWL support.*not implemented"):
        scratch_dsd.create(root, game)
    assert not root.exists()


def test_ds_header_still_reports_ordinary_game_metadata(tmp_path):
    game = tmp_path / "ds.nds"
    game.write_bytes(header())
    info = scratch_dsd.game_info(game)
    assert info["platform"] == "nds" and info["id"] == "ADQE"
    assert info["title"] == "ORIGINALTEST"
