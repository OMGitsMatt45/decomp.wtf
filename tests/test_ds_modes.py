"""The autopilot's DS mode wrappers must produce Thumb code and restore surrounding ARM code."""

import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.forks import drafts, scratch_dsd


def test_missing_disassembly_leaves_a_candidate_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "_dsd_block", lambda *a: None)
    source = "void probe(void) {}"
    assert drafts.ds_mode_source(tmp_path, "unit", "probe", source) == source


@pytest.mark.skipif(not scratch_dsd.versions() or not toolchains.installed("wibo"),
                    reason="needs an existing CodeWarrior for DS installation and wibo")
def test_thumb_wrapper_restores_compiler_state(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "_dsd_block", lambda *a: ("", True))
    source = drafts.ds_mode_source(tmp_path, "unit", "thumb_probe", "void thumb_probe(void) {}")
    source += "\nvoid arm_probe(void) {}\n"
    src = tmp_path / "modes.c"
    obj = tmp_path / "modes.o"
    src.write_text(source)
    compiler = toolchains.path("mwccarm") / "mwccarm" / scratch_dsd.versions()[-1] / "mwccarm.exe"
    subprocess.run([str(toolchains.binary("wibo")), str(compiler), "-proc", "arm946e", "-O4,p", "-interworking",
                    "-c", str(src), "-o", str(obj)], check=True, capture_output=True)
    with obj.open("rb") as f:
        elf = ELFFile(f)
        sizes = {s.name: s["st_size"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
    assert sizes["thumb_probe"] == 2
    assert sizes["arm_probe"] == 4
