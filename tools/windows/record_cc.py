#!/usr/bin/env python3
"""Record the configured C build inventory used by the C++ source port."""
import json
import os
import subprocess
import sys

with open(os.environ["N64_CC_LOG"], "a") as log:
    log.write(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}) + "\n")
raise SystemExit(subprocess.call([os.environ["N64_REAL_CC"], *sys.argv[1:]]))
