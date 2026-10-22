"""Keep original compilers immutable and their emulated children sandboxed."""

import hashlib
import shlex
import struct
import subprocess
import sys

import pytest

from decompnet import compiler, linux_i386, project

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux compatibility path")


def elf32(path, *, dynamic=False, machine=3):
    head = bytearray(52)
    head[:6] = b"\x7fELF\x01\x01"
    struct.pack_into("<H", head, 18, machine)
    if dynamic:
        struct.pack_into("<I", head, 28, 52)
        struct.pack_into("<HH", head, 42, 32, 1)
        head += struct.pack("<I", 3) + bytes(28)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head)
    return path


def test_driver_and_child_launchers_keep_pinned_files_and_native_assembler(tmp_path):
    root = tmp_path / "tools with 'quotes'"
    gcc = elf32(root / "bin/ee-gcc", dynamic=True)
    frontend = elf32(root / "lib/gcc-lib/ee/version/cc1plus", dynamic=True)
    assembler = elf32(root / "bin/ee-as", machine=8)  # target data isn't a host program
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (gcc, frontend, assembler)}
    qemu = tmp_path / "qemu with spaces"
    qemu.touch()
    runtime = str(tmp_path / "runtime with spaces")
    mirror = tmp_path / "mirror"
    command = linux_i386.prepare([str(gcc), "-B" + str(root) + "/", str(frontend)],
                                 (str(root),), mirror, str(qemu), runtime)
    driver = mirror / "0/bin/ee-gcc"
    args = shlex.split(driver.read_text().splitlines()[1])
    assert args[:9] == ["exec", str(qemu), "-R", "1G", runtime + "/ld-linux.so.2",
                        "--library-path", runtime, str(gcc), "-B" + str(mirror / "0/bin") + "/"]
    assert "-B" + str(mirror / "0/lib/gcc-lib/ee/version") + "/" in args
    assert command[0] == str(driver)
    assert command[2] == str(mirror / "0/lib/gcc-lib/ee/version/cc1plus")
    assert (mirror / "0/bin/ee-as").is_symlink()
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original} == original


def test_dynamic_compiler_requires_runtime_and_missing_emulator_is_actionable(tmp_path):
    root = tmp_path / "tools"
    gcc = elf32(root / "gcc", dynamic=True)
    qemu = tmp_path / "qemu"
    qemu.touch()
    with pytest.raises(ValueError, match="runtime32"):
        linux_i386.prepare([str(gcc)], (str(root),), tmp_path / "mirror", str(qemu), None)
    with pytest.raises(ValueError, match="absolute path"):
        linux_i386.prepare([str(gcc)], (str(root),), tmp_path / "mirror", "qemu-i386", None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux execution path")
def test_emulator_failure_is_reported_and_launchers_are_mounted_read_only(tmp_path, monkeypatch):
    root = tmp_path / "tools"
    gcc = elf32(root / "gcc")
    qemu = tmp_path / "qemu"
    qemu.touch()
    cfg = compiler.CompilerConfig([str(gcc), "{src}", "-o", "{obj}"], sandbox="docker", image="pinned-image",
                                  qemu_i386=str(qemu), toolchain_dirs=(str(root),), ro_paths=(str(root),))

    def run(command, **kwargs):
        assert command[:4] == ["docker", "run", "--rm", "--network"]
        assert "none" in command and "--read-only" in command
        assert command[command.index("pinned-image") + 1] != str(gcc)
        mounts = [command[i + 1] for i, part in enumerate(command) if part == "-v"]
        assert any("decompnet-i386-" in mount and mount.endswith(":ro") for mount in mounts)
        assert f"{qemu}:{qemu}:ro" in mounts
        return subprocess.CompletedProcess(command, 29, "", "frontend failed")

    monkeypatch.setattr(compiler.subprocess, "run", run)
    result = compiler.compile_source(cfg, "", "int value(void) { return 1; }")
    assert not result.ok and result.obj is None and result.log == "frontend failed"


def test_linux_environment_defaults_preserve_explicit_project_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(project.sys, "platform", "linux")
    monkeypatch.setenv("DECOMP_COMPILER_SANDBOX", "docker")
    monkeypatch.setenv("DECOMP_COMPILER_IMAGE", "pinned-image")
    monkeypatch.setenv("DECOMP_QEMU_I386", "/tools/qemu-i386")
    config = {"compiler": {"cmd": ["cc"]}}
    cfg = project.compiler_config(tmp_path, config)
    assert (cfg.sandbox, cfg.image, cfg.qemu_i386) == ("docker", "pinned-image", "/tools/qemu-i386")
    config["compiler"].update(sandbox="bwrap", image="project-image", qemu_i386=None)
    cfg = project.compiler_config(tmp_path, config)
    assert (cfg.sandbox, cfg.image, cfg.qemu_i386) == ("bwrap", "project-image", None)
    monkeypatch.setattr(project.sys, "platform", "win32")
    cfg = project.compiler_config(tmp_path, {"compiler": {"cmd": ["cc"]}})
    assert cfg.sandbox == "auto" and cfg.qemu_i386 is None and cfg.image is None
