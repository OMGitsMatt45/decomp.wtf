"""The autopilot's DS mode wrappers must produce Thumb code and restore surrounding ARM code."""

import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.elfobj import extract_function
from decompnet.forks import drafts, scratch_dsd


def test_missing_disassembly_leaves_a_candidate_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "_dsd_block", lambda *a: None)
    source = "void probe(void) {}"
    assert drafts.ds_mode_source(tmp_path, "unit", "probe", source) == source


@pytest.mark.skipif(not scratch_dsd.versions() or
                    (sys.platform != "win32" and not toolchains.installed("wibo")),
                    reason="needs CodeWarrior for DS and, on Linux, wibo")
@pytest.mark.parametrize("version", ["2.0/sp1p5", "2.0/sp1p6"])
@pytest.mark.parametrize("language", ["c", "c++"])
@pytest.mark.parametrize("thumb", [False, True])
def test_mode_wrapper_restores_compiler_state(tmp_path, monkeypatch, version, language, thumb):
    monkeypatch.setattr(drafts, "_dsd_block", lambda *a: ("", thumb))
    source = f"#pragma thumb {'off' if thumb else 'on'}\n"
    source += drafts.ds_mode_source(tmp_path, "unit", "mode_probe", "void mode_probe(void) {}")
    source += "\nvoid following_probe(void) {}\n"
    if language == "c++":
        source = 'extern "C" {\n' + source + "}\n"
    src = tmp_path / ("modes.cpp" if language == "c++" else "modes.c")
    obj = tmp_path / "modes.o"
    src.write_text(source)
    base = toolchains.require("mwccarm") / "mwccarm"
    compiler = base / version / "mwccarm.exe"
    assert compiler.is_file(), f"required compiler missing: {version}"
    monkeypatch.setenv("LM_LICENSE_FILE", str(base / "license.dat"))
    wrap = [] if sys.platform == "win32" else [str(toolchains.binary("wibo"))]
    subprocess.run([*wrap, str(compiler), "-proc", "arm946e", "-O4,p", "-interworking", f"-lang={language}",
                    "-c", str(src), "-o", str(obj)], check=True, capture_output=True)
    with obj.open("rb") as f:
        elf = ELFFile(f)
        sizes = {s.name: s["st_size"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
    assert sizes["mode_probe"] == (2 if thumb else 4)
    assert sizes["following_probe"] == (4 if thumb else 2)
    assert extract_function(obj.read_bytes(), "mode_probe").arch == ("thumb" if thumb else "arm")
    assert extract_function(obj.read_bytes(), "following_probe").arch == ("arm" if thumb else "thumb")
