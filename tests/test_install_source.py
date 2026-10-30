"""Installer provenance is exercised with fake tools: no installs, network or user settings."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "site/public/install.sh"
UPSTREAM = "OMGitsMatt45/decomp.wtf"
COMMIT = "a" * 40
HEAD = "b" * 40

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux installer harness uses Bash")


@pytest.fixture
def install(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = tmp_path / "source with spaces"
    (source / "src/decompnet").mkdir(parents=True)
    (source / ".git").mkdir()
    (tmp_path / ".git").mkdir()  # git would also discover a containing checkout after a ZIP loses its own .git
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    (source / "pyproject.toml").write_text('[project]\nname = "decompnet"\nversion = "0.0.0"\n')
    for name in ("README.md", "LICENSE"):
        (source / name).touch()
    logfile = tmp_path / "calls.jsonl"
    tool = bindir / "fake-tool"
    tool.write_text(f"#!{sys.executable}\n" + '''\
import json, os, sys
from pathlib import Path

name, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["INSTALL_TEST_LOG"], "a") as out:
    out.write(json.dumps([name, *args]) + "\\n")
if name == "git":
    if args[-3:] == ["config", "--get", "remote.origin.url"]:
        print(os.environ.get("INSTALL_TEST_ORIGIN", ""))
    elif "--abbrev-ref" in args:
        print("feature/windows")
    else:
        print("a" * 40)
elif name == "uv":
    if args == ["--version"]:
        print("uv 1.0.0")
    elif args == ["tool", "dir", "--bin"]:
        print(Path(sys.argv[0]).parent)
elif name == "curl" and "/commits/" in args[-1]:
    print(json.dumps({"sha": "b" * 40}))
''')
    tool.chmod(0o755)
    for name in ("git", "uv", "decomp", "curl"):
        (bindir / name).symlink_to(tool.name)

    def run(*, origin="https://github.com/fork-user/decomp.wtf.git", repo=None, branch=None,
            source_arg=None, zipped=False):
        logfile.unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DECOMP_")}
        env.update(PATH=f"{bindir}:{os.environ['PATH']}", INSTALL_TEST_LOG=str(logfile),
                   INSTALL_TEST_ORIGIN=origin, HOME=str(isolated_home), DISPLAY="", WAYLAND_DISPLAY="")
        if repo is not None:
            env["DECOMP_REPO"] = repo
        if branch is not None:
            env["DECOMP_BRANCH"] = branch
        if zipped:
            (source / ".git").rmdir()
        result = subprocess.run(["bash", str(INSTALLER), "--no-start", "--source", source_arg or str(source)],
                                env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in logfile.read_text().splitlines()] if logfile.exists() else []
        metadata = next((call[2:] for call in calls if call[:2] == ["decomp", "install-info"]), None)
        return result, calls, dict(zip(metadata[::2], metadata[1::2])) if metadata else None

    return run


@pytest.mark.parametrize("origin", ["https://github.com/fork-user/decomp.wtf.git",
                                   "git@github.com:fork-user/decomp.wtf.git",
                                   "ssh://git@github.com/fork-user/decomp.wtf.git"])
def test_checkout_records_its_github_origin(install, origin):
    result, _, metadata = install(origin=origin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata == {"--channel": "branch", "--branch": "feature/windows", "--commit": COMMIT,
                        "--repo": "fork-user/decomp.wtf"}


def test_explicit_repo_overrides_checkout_origin(install):
    result, _, metadata = install(repo="another-fork/decomp.wtf")
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata["--repo"] == "another-fork/decomp.wtf"


@pytest.mark.parametrize("origin", ["https://gitlab.com/fork-user/decomp.wtf.git",
                                   "https://github.com/fork-user/decomp.wtf.git?token=secret",
                                   "https://github.com/fork-user/decomp.wtf/extra",
                                   "https://github.com/fork-user/.."])
def test_non_github_or_invalid_origin_falls_back_to_upstream(install, origin):
    result, _, metadata = install(origin=origin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata["--repo"] == UPSTREAM


@pytest.mark.parametrize("repo", ["https://github.com/fork-user/decomp.wtf", "fork-user/..", "fork-user/repo?token=x"])
def test_invalid_explicit_repo_is_rejected_before_install(install, repo):
    result, calls, metadata = install(repo=repo)
    assert result.returncode != 0
    assert "DECOMP_REPO must be a GitHub owner/repository" in result.stderr
    assert metadata is None and not any(call[0] == "uv" for call in calls)


def test_branch_archive_and_metadata_use_selected_fork(install):
    result, calls, metadata = install(source_arg="branch:feature/windows", repo="fork-user/decomp.wtf")
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(call[0] == "curl" and call[-1] ==
               "https://api.github.com/repos/fork-user/decomp.wtf/commits/feature/windows" for call in calls)
    assert ["uv", "tool", "install", "--force", "--quiet", "--python", "3.12",
            f"decompnet @ https://github.com/fork-user/decomp.wtf/archive/{HEAD}.tar.gz"] in calls
    assert metadata["--repo"] == "fork-user/decomp.wtf" and metadata["--commit"] == HEAD


def test_release_honors_the_selected_repository(install):
    result, calls, metadata = install(source_arg="release", repo="fork-user/decomp.wtf")
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata["--channel"] == "release" and metadata["--repo"] == "fork-user/decomp.wtf"
    assert any(call[0] == "uv" and "github.com/fork-user/decomp.wtf/releases/download/v0.20.1/" in call[-1] for call in calls)


def test_source_zip_does_not_inherit_its_parent_checkout(install):
    result, calls, metadata = install(zipped=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata["--channel"] == "release" and metadata["--branch"] == "" and metadata["--commit"] == ""
    assert not any(call[0] == "git" for call in calls)


def test_source_zip_can_follow_an_explicit_fork_branch(install):
    result, _, metadata = install(zipped=True, repo="fork-user/decomp.wtf", branch="windows-fixes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert metadata["--channel"] == "branch" and metadata["--branch"] == "windows-fixes"
    assert metadata["--repo"] == "fork-user/decomp.wtf" and metadata["--commit"] == ""
