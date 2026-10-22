"""Encrypted DS imports retain the user's BIOS and pass it to subsequent extraction builds."""

import json
import re
import runpy
import shutil
import subprocess
import sys

import pytest

from decompnet.forks import scratch_dsd
from decompnet.forks.project import ForkError


def test_import_keeps_a_private_bios_and_forwards_it(tmp_path, monkeypatch):
    bios = tmp_path / "my BIOS.bin"
    bios.write_bytes(bytes(range(256)) * 64)
    root = tmp_path / "project"
    (root / "extract").mkdir(parents=True)
    runs = []
    monkeypatch.setattr(scratch_dsd, "_run", lambda *args: runs.append(args))
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    scratch_dsd._extract("dsd", root, "yv5p")
    assert (root / "extract/arm7_bios.bin").read_bytes() == bios.read_bytes()
    assert runs[0][0][-2:] == ["--arm7-bios", "extract/arm7_bios.bin"]
    assert runs[0][1] == root


def test_an_explicit_bios_takes_precedence_and_can_already_be_local(tmp_path, monkeypatch):
    (tmp_path / "extract").mkdir()
    bios = tmp_path / "extract/arm7_bios.bin"
    bios.write_bytes(b"x" * 0x4000)
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(tmp_path / "missing"))
    monkeypatch.setattr(scratch_dsd, "_run", lambda *args: None)
    scratch_dsd._extract("dsd", tmp_path, "yv5p", arm7_bios=bios)
    assert bios.read_bytes() == b"x" * 0x4000


@pytest.mark.parametrize("size", [None, 0, 0x1000, 0x4001])
def test_bad_bios_stops_before_extraction(tmp_path, monkeypatch, size):
    bios = tmp_path / "bios.bin"
    if size is not None:
        bios.write_bytes(b"x" * size)
    monkeypatch.delenv("DECOMP_ARM7_BIOS", raising=False)
    monkeypatch.setattr(scratch_dsd, "_run", lambda *a: pytest.fail("must not extract with an invalid BIOS"))
    with pytest.raises(ForkError, match="16 KiB"):
        scratch_dsd._extract("dsd", tmp_path, "yv5p", arm7_bios=bios)


def test_plain_rom_needs_no_bios_and_encrypted_errors_explain_the_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("DECOMP_ARM7_BIOS", raising=False)
    runs = []
    monkeypatch.setattr(scratch_dsd, "_run", lambda *args: runs.append(args))
    scratch_dsd._extract("dsd", tmp_path, "demo")
    assert "--arm7-bios" not in runs[0][0]
    monkeypatch.setattr(scratch_dsd, "_run", lambda *a: (_ for _ in ()).throw(ForkError("please provide ARM7 BIOS")))
    with pytest.raises(ForkError, match="DECOMP_ARM7_BIOS"):
        scratch_dsd._extract("dsd", tmp_path, "yv5p")


@pytest.mark.parametrize("has_bios", [False, True])
def test_generated_build_reuses_bios_as_a_dependency(tmp_path, monkeypatch, has_bios):
    root = tmp_path / "project"
    shutil.copytree(scratch_dsd.TEMPLATE, root)
    (root / "extract").mkdir()
    if has_bios:
        (root / "extract/arm7_bios.bin").write_bytes(b"x" * 0x4000)
    fake_dsd = tmp_path / "tools with spaces" / "dsd.exe"
    delinks = {"files": [], "arm9_lcf_file": "build/arm9.lcf", "arm9_objects_file": "build/objects.txt"}

    def describe(cmd, **kwargs):
        assert cmd[:3] == [str(fake_dsd), "json", "delinks"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(delinks))

    monkeypatch.setattr(subprocess, "run", describe)
    monkeypatch.syspath_prepend(str(root / "tools"))
    monkeypatch.setattr(sys, "argv", [str(root / "tools/configure.py"), "yv5p", "--dsd", str(fake_dsd),
                                    "--compilers", str(tmp_path / "compilers")])
    monkeypatch.chdir(root)
    runpy.run_path(str(root / "tools/configure.py"), run_name="__main__")
    ninja = re.sub(r"\$\n\s*", "", (root / "build.ninja").read_text())
    assert ("--arm7-bios extract/arm7_bios.bin" in ninja) == has_bios
    assert ("| tools/extract.py extract/arm7_bios.bin" in ninja) == has_bios
    assert "tools/extract.py" in ninja
    if has_bios:
        assert "rom build --config $in --rom $out --arm7-bios extract/arm7_bios.bin" in ninja
