"""Capture collection failures and native process exits as well as JUnit failures."""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    suites = sys.argv[1:] or ["--ignore=tests/test_gb.py", "--ignore=tests/test_gb_app.py"]
    command = [sys.executable, "-m", "pytest", "-q", "-p", "tools.operational_progress", *suites,
               "--junitxml=operational-results.xml"]
    with tempfile.TemporaryDirectory(prefix="operational-progress-") as temporary:
        progress = Path(temporary) / "active-test"
        started = time.monotonic()
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "DECOMP_OPERATIONAL_PROGRESS": str(progress)}) as process:
            while True:
                try:
                    output = process.communicate(timeout=30)[0]
                    break
                except subprocess.TimeoutExpired:
                    active = progress.read_text(encoding="utf-8") if progress.exists() else "collecting tests"
                    print(f"::notice::Operational check {int(time.monotonic() - started)}s: {active}", flush=True)
            returncode = process.returncode
    output = re.sub(r"([?&]k=)[A-Za-z0-9_-]+", r"\1<redacted>", output)
    Path("operational-output.log").write_text(output, encoding="utf-8")
    print(output)
    if returncode:
        diagnostic = f"pytest exit {returncode}:\n" + output[-22000:]
        print("::error::" + diagnostic.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
    return 1 if returncode else 0


if __name__ == "__main__":
    raise SystemExit(main())
