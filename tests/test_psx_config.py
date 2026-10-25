"""Repair malformed initial text guesses before running the disassembler."""

import copy

import pytest

from decompnet.rom.psx_code import repair_config
from .test_overlays import _resident_exe


@pytest.mark.parametrize("subsegments", [
    [[0x800, "rodata", "prefix"], [0, "c", "main"]],
    [[0x900, "rodata", "prefix"], [0x800, "c", "main"]],
])
def test_out_of_order_or_out_of_parent_text_is_recovered_from_original_entry(subsegments):
    cfg = {"segments": [{"type": "bin", "start": 0},
                        {"type": "code", "start": 0x800, "vram": 0x80010000, "subsegments": subsegments},
                        [0x1000]]}
    assert repair_config(cfg, _resident_exe())
    repaired = cfg["segments"][1]["subsegments"]
    assert repaired[0][:2] == [0x800, "c"]
    assert all(0x800 <= item[0] <= 0x1000 for item in repaired)
    assert [item[0] for item in repaired] == sorted(item[0] for item in repaired)


def test_valid_entry_coverage_keeps_existing_sections():
    cfg = {"segments": [{"type": "code", "start": 0x800, "vram": 0x80010000,
                         "subsegments": [[0x800, "c", "main"], [0xE00, "data", "constants"]]}, [0x1000]]}
    original = copy.deepcopy(cfg)
    assert not repair_config(cfg, _resident_exe())
    assert cfg == original
