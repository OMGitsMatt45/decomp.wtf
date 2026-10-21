"""Record the active integration test for the operational runner's heartbeat."""

import os
from pathlib import Path


def pytest_runtest_logstart(nodeid, location):
    if path := os.environ.get("DECOMP_OPERATIONAL_PROGRESS"):
        Path(path).write_text(nodeid, encoding="utf-8")
