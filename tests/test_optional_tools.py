"""Real optional tools, including Ghidra's Java script and native decompiler."""

import os
import subprocess
import sys

import pytest

from decompnet import toolchains
from decompnet.forks import ghidra

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_OPTIONAL_TOOLS") != "1",
                                reason="requires the pinned optional tool downloads and Java 21")


@pytest.mark.parametrize("tool", ["cloudflared", "coddog"])
def test_optional_native_binary_starts(tool):
    run = subprocess.run([str(toolchains.binary(tool)), "--version"], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert tool in run.stdout.lower() + run.stderr.lower()


def test_maspsx_starts():
    script = toolchains.require("maspsx") / "maspsx.py"
    run = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "aspsx" in run.stdout.lower()


def test_ghidra_decompiles_an_object_and_reuses_its_cache(tmp_path, monkeypatch):
    assert ghidra.available(), "the optional Ghidra integration must actually run"
    suffix = ".exe" if sys.platform == "win32" else ""
    compiler = toolchains.require("arm-gnu") / "bin" / f"arm-none-eabi-gcc{suffix}"
    source, obj = tmp_path / "draft.c", tmp_path / "draft.o"
    source.write_text("int release_probe(int a) { return a + 7; }\n", encoding="utf-8")
    subprocess.run([str(compiler), "-O2", "-c", str(source), "-o", str(obj)], check=True, timeout=30)
    logs = []
    real_run = subprocess.run

    def capture(*args, **kwargs):
        result = real_run(*args, **kwargs)
        logs.append((result.stdout or "") + (result.stderr or ""))
        return result

    monkeypatch.setattr(ghidra.subprocess, "run", capture)
    cache = tmp_path / "draft cache"
    drafts = ghidra.decompile_object(obj, cache, timeout=180)
    assert "release_probe" in drafts, "Ghidra did not export the compiled function:\n" + "\n".join(logs)[-3500:]
    assert "7" in drafts["release_probe"]
    monkeypatch.setattr(ghidra, "available", lambda: False)
    assert ghidra.decompile_object(obj, cache) == drafts
