"""The verified local EE host is opt-in, native, and never deleted by install."""

import json

import pytest

from decompnet import project, toolchains, wsl


@pytest.fixture
def local_host(tmp_path, monkeypatch):
    root = tmp_path / "local EE host with spaces"
    root.mkdir()
    monkeypatch.setattr(toolchains, "current_platform", lambda: "windows-x86_64")
    monkeypatch.setenv(toolchains.EE_NATIVE_ROOT, str(root))
    metadata = {"archive_sha256": toolchains.EE_ARCHIVE_SHA256,
                "tools": {name: {} for name in toolchains.EE_HOST_PROGRAMS}}
    for name in toolchains.EE_HOST_PROGRAMS:
        path = root / (name + ".exe")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ-native-fixture")
    # The app verifies presence of the original C++ payload before compiling.
    (root / "lib/gcc-lib/ee/2.96-ee-001003-1/cc1plus").touch()
    (root / "host-build.json").write_text(json.dumps(metadata))
    return root


def test_local_host_selects_the_original_cpp_driver_without_linux_runtime(local_host, monkeypatch):
    monkeypatch.setenv("DECOMP_WSL", "wsl.exe")
    monkeypatch.setattr(wsl, "status", lambda: pytest.fail("must not start WSL"))
    tc = toolchains.get("ee-gcc-2.96")
    assert tc.supported and not tc.via_wsl and tc.dependencies() == []
    assert toolchains.require(tc.id) == local_host
    assert toolchains.installed(tc.id)["local_build"]
    cfg = project.compiler_config(local_host, {"kind": "rom", "platform": "ps2", "compiler": {
        "toolchain": tc.id, "language": "c++", "sandbox": "none"}})
    assert cfg.cmd[0] == local_host.as_posix() + "/bin/ee-gcc.exe"
    assert "-fno-exceptions" in cfg.cmd and "-fconserve-space" in cfg.cmd and not cfg.wsl
    assert cfg.runtime32 is None


def test_local_host_is_never_refreshed_or_deleted_by_force_install(local_host):
    sentinel = local_host / "keep-my-work.txt"
    sentinel.write_text("preserve")
    assert toolchains.install("ee-gcc-2.96", log=lambda *_: None) == local_host
    with pytest.raises(toolchains.ToolchainError, match="user-managed"):
        toolchains.install("ee-gcc-2.96", force=True)
    assert sentinel.read_text() == "preserve" and toolchains.installed("ee-gcc-2.96")


@pytest.mark.parametrize("defect", ["wrong-archive", "missing-exe", "linux-exe", "invalid-json", "relative-path"])
def test_invalid_local_build_fails_explicitly_without_falling_back(local_host, defect, monkeypatch):
    if defect == "wrong-archive":
        data = json.loads((local_host / "host-build.json").read_text())
        data["archive_sha256"] = "0" * 64
        (local_host / "host-build.json").write_text(json.dumps(data))
    elif defect == "invalid-json":
        (local_host / "host-build.json").write_text("{")
    elif defect == "relative-path":
        monkeypatch.chdir(local_host.parent)
        monkeypatch.setenv(toolchains.EE_NATIVE_ROOT, local_host.name)
    else:
        exe = local_host / "bin/ee-gcc.exe"
        exe.unlink() if defect == "missing-exe" else exe.write_bytes(b"\x7fELF")
    monkeypatch.setenv("DECOMP_WSL", "wsl.exe")
    assert not toolchains.get("ee-gcc-2.96").via_wsl
    assert toolchains.installed("ee-gcc-2.96") is None
    with pytest.raises(toolchains.ToolchainError, match="complete Windows host build"):
        toolchains.require("ee-gcc-2.96")


def test_linux_still_uses_its_existing_toolchain_when_local_windows_path_is_set(local_host, monkeypatch):
    monkeypatch.setattr(toolchains, "current_platform", lambda: "linux-x86_64")
    monkeypatch.delenv("DECOMP_WSL", raising=False)
    assert toolchains.path("ee-gcc-2.96") != local_host
    assert toolchains.get("ee-gcc-2.96").dependencies() == ["runtime-i386"]
