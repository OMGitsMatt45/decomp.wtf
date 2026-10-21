"""Capture collection failures and native process exits as well as JUnit failures."""

import re
import subprocess
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    suites = sys.argv[1:] or ["--ignore=tests/test_gb.py", "--ignore=tests/test_gb_app.py"]
    command = [sys.executable, "-m", "pytest", "-q", *suites, "--junitxml=operational-results.xml"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    output = re.sub(r"([?&]k=)[A-Za-z0-9_-]+", r"\1<redacted>", result.stdout)
    Path("operational-output.log").write_text(output, encoding="utf-8")
    print(output)
    if result.returncode:
        diagnostic = f"pytest exit {result.returncode}:\n" + output[-22000:]
        print("::error::" + diagnostic.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
    return 1 if result.returncode else 0


if __name__ == "__main__":
    raise SystemExit(main())
