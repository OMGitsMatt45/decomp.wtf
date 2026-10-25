"""Automatic source boundaries must not cut through overlapping DS function entries."""

import json

import pytest

from decompnet.forks import scratch_dsd
from decompnet.forks.project import ForkProject


def module(tmp_path, symbols):
    (tmp_path / "delinks.txt").write_text("Sections:\n    .text start:0x1000 end:0x1040\n\n")
    (tmp_path / "symbols.txt").write_text("\n".join(
        f"fn_{i} kind:function(thumb,size=0x{size:x}) addr:0x{addr:x}" for i, (addr, size) in enumerate(symbols)))
    return tmp_path


def test_disjoint_functions_still_split_at_the_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 16)
    assert scratch_dsd._units(module(tmp_path, [(0x1000, 8), (0x1008, 8), (0x1010, 8)])) == [
        (0x1000, 0x1010, 2), (0x1010, 0x1040, 1)]


def test_overlapping_and_nested_entries_stay_together(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 16)
    symbols = [(0x1000, 12), (0x1008, 12), (0x1010, 4), (0x1014, 4)]
    units = scratch_dsd._units(module(tmp_path, symbols))
    assert units == [(0x1000, 0x1014, 3), (0x1014, 0x1040, 1)]
    for start, end, _ in units:
        assert all(addr + size <= end for addr, size in symbols if start <= addr < end)


def test_aliases_keep_the_longest_extent_and_do_not_shrink_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 8)
    symbols = [(0x1000, 24), (0x1000, 4), (0x1004, 4), (0x1010, 4), (0x1018, 4)]
    assert scratch_dsd._units(module(tmp_path, symbols)) == [(0x1000, 0x1018, 3), (0x1018, 0x1040, 1)]


def test_a_thumb_entry_at_halfword_alignment_does_not_start_a_new_object(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 16)
    symbols = [(0x1000, 18), (0x1012, 2), (0x1014, 4)]
    assert scratch_dsd._units(module(tmp_path, symbols)) == [(0x1000, 0x1014, 2), (0x1014, 0x1040, 1)]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_ds_link_markers_preserve_line_endings_and_accept_windows_paths(tmp_path, newline):
    (tmp_path / ".decomp.wtf.json").write_text(json.dumps({"platform": "nds", "created": "from scratch"}))
    fp = ForkProject(tmp_path)
    first = newline.join(["src\\auto\\one.cpp:", "    .text start:0x1000 end:0x1008", ""])
    other = "\nsrc/auto/two.c:\n    .text start:0x1008 end:0x1010\n"
    original = first + other
    updated = fp.marked_matching(original, ["src/auto/one.cpp"], None)
    marker = "    complete" + newline
    assert marker in updated
    assert updated.replace(marker, "", 1) == original
    assert updated.endswith(other)
    assert fp._ds_states_in(updated)["src/auto/one.cpp"][0] == "Matching"
    assert fp._ds_states_in(updated)["src/auto/two.c"][0] == "NonMatching"
    assert fp.marked_matching(updated, ["src/auto/one.cpp"], None) == updated
