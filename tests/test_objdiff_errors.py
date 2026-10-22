"""Process failures become normal comparison errors, including in background indexing."""

import subprocess
from types import SimpleNamespace

import pytest

from decompnet.forks import objdiff


@pytest.mark.parametrize("failure", [OSError("process could not start"), subprocess.TimeoutExpired("objdiff", 1)])
def test_process_errors_are_comparison_errors(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(objdiff, "_exe", lambda: "objdiff-cli")

    def run(*a, **kw):
        raise failure

    monkeypatch.setattr(objdiff, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    with pytest.raises(objdiff.ObjdiffError, match="could not run objdiff-cli"):
        objdiff._run(["diff"], tmp_path)
