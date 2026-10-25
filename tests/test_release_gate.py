"""A release requires both native hosts at the exact commit."""

import pytest

from tools import release_gate


@pytest.mark.parametrize("linux,windows,allowed", [
    ("success", "success", True),
    ("failure", "success", False),
    ("success", "skipped", False),
    (None, "success", False),
])
def test_release_requires_both_core_hosts(tmp_path, monkeypatch, linux, windows, allowed):
    notes, output = tmp_path / "notes.md", tmp_path / "published.md"
    notes.write_text("Release notes", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", ["release_gate", "--sha", "tested", "--notes", str(notes), "--output", str(output)])
    run = {"id": 1, "name": "Full operational check", "head_sha": "tested", "html_url": "https://example.test/run/1"}
    jobs = [{"name": name, "conclusion": status} for name, status in (
        ("core (ubuntu-24.04)", linux), ("core (windows-2022)", windows))]
    monkeypatch.setattr(release_gate, "get", lambda path: {"jobs": jobs} if "/jobs?" in path else {"workflow_runs": [run]})
    if allowed:
        release_gate.main()
        text = output.read_text(encoding="utf-8")
        assert "Tested commit: `tested`" in text
    else:
        with pytest.raises(SystemExit, match="release blocked"):
            release_gate.main()
        assert not output.exists()


def test_successful_different_commit_cannot_authorize_release(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", ["release_gate", "--sha", "untested", "--notes", str(tmp_path / "notes"),
                                    "--output", str(tmp_path / "output")])
    monkeypatch.setattr(release_gate, "get", lambda path: {"workflow_runs": [
        {"id": 1, "name": "Full operational check", "head_sha": "other"}]})
    with pytest.raises(SystemExit, match="release blocked"):
        release_gate.main()
