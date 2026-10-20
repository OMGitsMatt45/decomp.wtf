"""Frontend identity is explicit; a missing classic build must never select EDG."""

import json
from pathlib import Path

import pytest

from decompnet import ido_cfront, project, toolchains, wsl


def setup_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchains, "runtime_dirs", lambda _: [tmp_path])
    monkeypatch.setattr(wsl, "run", lambda *a, **kw: pytest.fail("classic cfront must not use WSL"))
    suffix = ".exe" if toolchains.current_platform().startswith("windows-") else ""
    for name in ("CC", "cfront", "ptcomp", "markc++", "NCC", "edgcpfe"):
        (tmp_path / (name + suffix)).touch()
    manifest = {"format": 1, "toolchain": "ido-5.3", "frontend": "cfront",
                "upstream_revision": "d5aec59932034b8a20f23f471297a55c45dcbc45",
                "irix_inputs": ido_cfront.IRIX_INPUTS}
    (tmp_path / "cfront-build.json").write_text(json.dumps(manifest), encoding="utf-8")
    return suffix, manifest


def configure(root, toolchain="ido-5.3"):
    return project.compiler_config(root, {"kind": "rom", "platform": "n64", "compiler": {
        "toolchain": toolchain, "cpp_frontend": "cfront", "sandbox": "none"}})


def test_a_pinned_classic_overlay_selects_its_original_driver(tmp_path, monkeypatch):
    suffix, _ = setup_overlay(tmp_path, monkeypatch)
    cfg = configure(tmp_path)
    assert not cfg.wsl
    assert Path(cfg.cmd[cfg.cmd.index("--driver") + 1]).name == "CC" + suffix
    assert not any(Path(a).stem in ("NCC", "edgcpfe") for a in cfg.cmd)


def test_an_incomplete_classic_overlay_fails_even_when_edg_is_installed(tmp_path, monkeypatch):
    suffix, _ = setup_overlay(tmp_path, monkeypatch)
    (tmp_path / ("ptcomp" + suffix)).unlink()
    with pytest.raises(toolchains.ToolchainError, match="classic cfront overlay is missing"):
        configure(tmp_path)


def test_a_different_frontend_identity_is_rejected(tmp_path, monkeypatch):
    _, manifest = setup_overlay(tmp_path, monkeypatch)
    manifest["irix_inputs"] = {**manifest["irix_inputs"], "usr/lib/c++/cfront": "edgcpfe"}
    (tmp_path / "cfront-build.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(toolchains.ToolchainError, match="pinned original IDO 5.3 inputs"):
        configure(tmp_path)


def test_71_does_not_substitute_edg_for_classic_53(tmp_path, monkeypatch):
    setup_overlay(tmp_path, monkeypatch)
    with pytest.raises(toolchains.ToolchainError, match="no verified setup"):
        configure(tmp_path, "ido-7.1")
