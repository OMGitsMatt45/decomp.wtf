"""Install a locally built classic overlay into an already accepted IDO 5.3 suite."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from decompnet import ido_cfront, toolchains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    if error := ido_cfront.manifest_error(args.package):
        parser.error(error)
    manifest = json.loads((args.package / "cfront-build.json").read_text(encoding="utf-8"))
    if manifest["platform"] != toolchains.current_platform():
        parser.error("the classic overlay was built for a different host platform")
    suffix = ".exe" if sys.platform == "win32" else ""
    files = [f"{name}{suffix}" for name in ("CC", "cfront", "ptcomp", "markc++")]
    for name in files:
        if not (args.package / name).is_file():
            parser.error(f"the classic overlay is missing {name}")
    destination = toolchains.require("ido-5.3")
    for name in [*files, "cfront-build.json"]:
        shutil.copy2(args.package / name, destination / name)
    print(f"Installed classic cfront overlay in {destination}; original C and EDG stages retained")


if __name__ == "__main__":
    main()
