"""Regenerate original CHD fixtures with an independent MAME chdman executable.

Developer-only: python -m tools.make_psx_chd_fixtures --chdman /path/to/chdman
The application itself does not need chdman. No ROM/BIOS inputs are used.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from tests.psx_chd_fixture import decoded, METADATA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chdman", type=Path, required=True)
    args = parser.parse_args()
    executable = str(args.chdman.resolve())
    destination = Path(__file__).resolve().parents[1] / "tests/fixtures/psx-chd"
    destination.mkdir(exist_ok=True)
    def run(*arguments):
        result = subprocess.run([executable, *map(str, arguments)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout + result.stderr
    version = subprocess.run([executable, "help"], capture_output=True, text=True).stdout.splitlines()[0]
    raw = decoded()
    manifest = {"generator": version, "source": "tests/psx_chd_fixture.py; entirely original fixtures",
                "decoded_size": len(raw), "decoded_sha256": hashlib.sha256(raw).hexdigest(), "files": {}}
    with tempfile.TemporaryDirectory() as temporary:
        original = Path(temporary) / "original.bin"
        original.write_bytes(raw)
        uncompressed = Path(temporary) / "original.chd"
        run("createraw", "-i", original, "-o", uncompressed, "-hs", 19584, "-us", 2448, "-c", "none")
        indices = {}
        for tag, text, checked in METADATA:
            index = indices.get(tag, 0)
            run("addmeta", "-i", uncompressed, "-t", tag, "-ix", index, "-vt", text, *([] if checked else ["-nocs"]))
            indices[tag] = index + 1
        for codec in ("cdlz", "cdzl", "cdfl", "lzma", "zlib"):
            output = destination / f"{codec}.chd"
            run("copy", "-f", "-i", uncompressed, "-o", output, "-c", codec, "-np", 1)
            run("verify", "-i", output)
            extracted = Path(temporary) / "extracted.bin"
            run("extractraw", "-f", "-i", output, "-o", extracted)
            assert extracted.read_bytes() == raw
            manifest["files"][output.name] = {"size": output.stat().st_size,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "chdman_verified": True}
    (destination / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
