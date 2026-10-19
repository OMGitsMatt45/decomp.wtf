"""Native Windows selection and portable compiler pipelines, without WSL or downloads."""

import json
import subprocess
import sys

import pytest

from decompnet import agbcc, compiler, project, toolchains, wsl
from decompnet.app import cli, updates


@pytest.fixture
def windows_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("DECOMPNET_TOOLCHAINS", str(tmp_path / "tools with spaces"))
    monkeypatch.delenv("DECOMP_WSL", raising=False)
    monkeypatch.setattr(toolchains, "current_platform", lambda: "windows-x86_64")
    reg = {}
    monkeypatch.setattr(toolchains, "registry", lambda: reg)

    def add(tid, **kwargs):
        tc = toolchains.Toolchain(id=tid, name=tid, license="MIT", source="test", **kwargs)
        reg[tid] = tc
        return tc

    return add


def mark_installed(tid):
    where = toolchains.path(tid)
    where.mkdir(parents=True)
    (where / toolchains.MANIFEST).write_text(json.dumps({"platform": "windows-x86_64"}))
    return where


def test_windows_does_not_implicitly_use_wsl(monkeypatch, windows_catalog):
    monkeypatch.setattr(wsl.sys, "platform", "win32")
    tc = windows_catalog("linux-only", parts=[{"url": "unused", "platforms": ["linux-x86_64"]}])
    assert not wsl.wanted() and not tc.via_wsl and not tc.supported
    assert "no native Windows build" in tc.unsupported_reason
    with pytest.raises(toolchains.ToolchainError, match="no native Windows build"):
        toolchains.install(tc.id)


def test_native_dependencies_replace_linux_runtime(windows_catalog):
    runtime = windows_catalog("runtime-i386", kind="runtime", parts=[{"url": "unused", "platforms": ["linux-x86_64"]}])
    tc = windows_catalog("native-cc", requires=[runtime.id], windows_requires=[],
                         parts=[{"url": "unused", "platforms": ["windows-x86_64"]}], cc=["{tc}/cc"])
    where = mark_installed(tc.id)
    (where / "cc.exe").touch()
    cfg = project.compiler_config(where, {"compiler": {"toolchain": tc.id}})
    assert tc.supported and tc.dependencies() == []
    assert cfg.cmd[0] == (where / "cc.exe").as_posix()
    assert cfg.runtime32 is None and not cfg.wsl and cfg.ro_paths == (str(where),)


def test_missing_dependency_prevents_claiming_native_support(windows_catalog):
    dep = windows_catalog("missing", parts=[{"url": "unused", "platforms": ["linux-x86_64"]}])
    tc = windows_catalog("native-cc", requires=[dep.id],
                         parts=[{"url": "unused", "platforms": ["windows-x86_64"]}])
    assert not tc.supported and "needs missing" in tc.unsupported_reason
    with pytest.raises(toolchains.ToolchainError, match="needs missing"):
        toolchains.install(tc.id)
    assert not toolchains.path(dep.id).exists() and not toolchains.path(tc.id).exists()


def test_wrong_host_manifest_is_not_an_installed_native_tool(windows_catalog):
    tc = windows_catalog("native-tool", parts=[{"url": "unused"}])
    where = mark_installed(tc.id)
    (where / toolchains.MANIFEST).write_text(json.dumps({"platform": "linux-x86_64"}))
    assert toolchains.installed(tc.id) is None


def test_windows_pipeline_template_expands_python_dependencies_and_flags(windows_catalog):
    dep = windows_catalog("arm-gnu", parts=[{"url": "unused"}])
    tc = windows_catalog("agbcc", parts=[{"url": "unused"}], requires=[dep.id], flags=["-O2", "-mthumb-interwork"],
                         cmd=["/bin/sh", "-c", "Linux pipeline"],
                         windows_cmd=["{python}", "-m", "decompnet.agbcc", "--cpp", "{tc:arm-gnu}/bin/cpp.exe",
                                      "--cc", "{tc}/bin/agbcc.exe", "--", "{flags}"])
    where, arm = mark_installed(tc.id), mark_installed(dep.id)
    cfg = project.compiler_config(where, {"compiler": {"toolchain": tc.id}})
    assert cfg.cmd == [sys.executable, "-m", "decompnet.agbcc", "--cpp", f"{arm.as_posix()}/bin/cpp.exe",
                       "--cc", f"{where.as_posix()}/bin/agbcc.exe", "--", "-O2", "-mthumb-interwork"]
    assert not cfg.wsl


def test_missing_agbcc_cpp_frontend_never_falls_back_to_c(windows_catalog):
    arm = windows_catalog("arm-gnu", parts=[{"url": "unused"}])
    tc = windows_catalog("agbcc", parts=[{"url": "unused"}], requires=[arm.id])
    where = mark_installed(tc.id)
    mark_installed(arm.id)
    with pytest.raises(toolchains.ToolchainError, match="C\\+\\+ frontend is missing"):
        project.compiler_config(where, {"kind": "rom", "platform": "gba", "compiler": {"toolchain": tc.id}})


def test_compile_source_expands_native_pipeline_paths_through_all_stages(windows_catalog, monkeypatch):
    arm = windows_catalog("arm-gnu", parts=[{"url": "unused"}])
    tc = windows_catalog("agbcc", requires=[arm.id], parts=[{"url": "unused"}], flags=["-O2"],
                         windows_cmd=["{python}", "-m", "decompnet.agbcc", "--cpp", "{tc:arm-gnu}/bin/cpp.exe",
                                      "--cc", "{tc}/bin/agbcc.exe", "--as", "{tc:arm-gnu}/bin/as.exe",
                                      "--builtin-include", "{tc}/include", "--src={src}", "--obj={obj}",
                                      "--include={include}", "--", "{flags}"])
    where = mark_installed(tc.id)
    mark_installed(arm.id)
    cfg = project.compiler_config(where, {"compiler": {"toolchain": tc.id, "sandbox": "none"}})
    stages = []

    def stage(command):
        output = compiler.Path(command[command.index("-o") + 1])
        if command[0].endswith("cpp.exe"):
            source = compiler.Path(command[-3])
            assert source.read_text().startswith('#include "context.h"')
            includes = [compiler.Path(command[i + 1]) for i, token in enumerate(command) if token == "-I"]
            assert (includes[-1] / "context.h").read_text() == "typedef int s32;\n"
            output.write_bytes(source.read_bytes())
        elif command[0].endswith("agbcc.exe"):
            assert command[1] == "-O2"
            output.write_bytes(compiler.Path(command[-3]).read_bytes())
        else:
            assert compiler.Path(command[-1]).is_file()
            output.write_bytes(b"\x7fELF native pipeline output")
        stages.append(command[0])
        return subprocess.CompletedProcess(command, 0)

    def execute(cfg, work, command, timeout, **kwargs):
        assert command[:3] == [sys.executable, "-m", "decompnet.agbcc"]
        assert not any("{src}" in arg or "{obj}" in arg or "{include}" in arg for arg in command)
        return subprocess.CompletedProcess(command, agbcc.main(command[3:]), "", "")

    monkeypatch.setattr(compiler, "_exec", execute)
    monkeypatch.setattr(agbcc.subprocess, "run", stage)
    result = compiler.compile_source(cfg, "typedef int s32;\n", "s32 f(s32 a) { return a + 1; }")
    assert result.ok and result.obj == b"\x7fELF native pipeline output"
    assert len(stages) == 3


def test_windows_uses_native_cc_override(windows_catalog):
    tc = windows_catalog("native-cc", parts=[{"url": "unused"}], cc=["/bin/sh", "linux-script"],
                         windows_cc=["{tc}/cc.exe", "-c"])
    where = mark_installed(tc.id)
    cfg = project.compiler_config(where, {"compiler": {"toolchain": tc.id}})
    assert cfg.cmd[:2] == [f"{where.as_posix()}/cc.exe", "-c"]


def test_native_compile_does_not_use_unix_wrappers_found_on_path(monkeypatch):
    monkeypatch.setattr(compiler.sys, "platform", "win32")
    monkeypatch.setattr(compiler.shutil, "which", lambda name: f"C:/Git/usr/bin/{name}.exe")
    cfg = compiler.CompilerConfig(["cc.exe"])
    assert compiler._sandbox_mode(cfg) == "none"
    assert compiler._wrap(cfg, compiler.Path("work"), ["cc.exe"]) == ["cc.exe"]


def test_failure_to_start_native_compiler_is_a_compile_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("the executable could not be found")

    monkeypatch.setattr(compiler.subprocess, "run", missing)
    result = compiler.compile_source(compiler.CompilerConfig(["missing-cc.exe"]), "", "int f(void) { return 1; }")
    assert not result.ok and "couldn't start compiler missing-cc.exe" in result.log


def test_tool_binary_finds_exe_in_bin(windows_catalog):
    tc = windows_catalog("arm-gnu", kind="tool", binary_name="arm-none-eabi-as", parts=[{"url": "unused"}])
    where = mark_installed(tc.id)
    (where / "bin").mkdir()
    exe = where / "bin/arm-none-eabi-as.exe"
    exe.touch()
    assert toolchains.binary(tc.id) == exe


@pytest.mark.parametrize("failed_stage", [None, 0, 1])
def test_agbcc_runs_stages_without_a_shell_and_stops_on_failure(monkeypatch, failed_stage):
    calls = []

    def run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 9 if len(calls) - 1 == failed_stage else 0)

    monkeypatch.setattr(agbcc.subprocess, "run", run)
    rc = agbcc.main(["--cpp", "C:/Tools & Games/cpp.exe", "--cc", "C:/Tools & Games/agbcc.exe",
                     "--as", "C:/Tools & Games/as.exe", "--builtin-include", "C:/Tools & Games/include",
                     "--src", "C:/Work with spaces/func.c", "--obj", "C:/Work with spaces/func.o",
                     "--include", "C:/Work with spaces/include", "--", "-O2", "-mthumb-interwork"])
    assert rc == (0 if failed_stage is None else 9)
    assert len(calls) == (3 if failed_stage is None else failed_stage + 1)
    assert calls[0][0] == "C:/Tools & Games/cpp.exe" and calls[0][-1] == "C:/Work with spaces/func.o.i"
    if len(calls) > 1:
        assert calls[1][1:3] == ["-O2", "-mthumb-interwork"]
    if len(calls) > 2:
        assert calls[2][-3:] == ["-o", "C:/Work with spaces/func.o", "C:/Work with spaces/func.o.s"]


def test_setup_reports_unavailable_tools_and_continues(windows_catalog, monkeypatch, capsys):
    windows_catalog("gcc-2.7.2-kmc", parts=[{"url": "unused", "platforms": ["linux-x86_64"]}])
    windows_catalog("m2c", git="https://example.invalid/m2c")
    windows_catalog("objdiff-cli", parts=[{"url": "unused"}])
    calls = []

    def install(tid, **kwargs):
        calls.append(tid)
        if tid == "m2c":
            raise toolchains.ToolchainError("download failed")

    monkeypatch.setattr(toolchains, "install", install)
    monkeypatch.setattr(cli, "home_dir", lambda: toolchains.root())
    monkeypatch.setattr("decompnet.app.agents.detect", lambda: [])
    assert cli.setup(None) == 0
    output = capsys.readouterr().out
    assert calls == ["m2c", "objdiff-cli"]
    assert "no native Windows build" in output and "download failed" in output
    assert "tools unavailable: gcc-2.7.2-kmc, m2c" in output


def test_native_windows_update_instructions_do_not_require_wsl(monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    ok, why = updates.can_apply()
    assert not ok and "close decomp.wtf" in why and "windows.cmd" in why and "WSL" not in why


def test_uv_is_found_as_a_windows_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.shutil, "which", lambda name: None)
    monkeypatch.setattr(updates.Path, "home", lambda: tmp_path)
    exe = tmp_path / ".local/bin/uv.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    assert updates.uv() == str(exe)
