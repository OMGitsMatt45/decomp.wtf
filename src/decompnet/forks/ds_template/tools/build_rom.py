"""Build a ROM atomically, preserving checksum metadata for explicitly decrypted inputs."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from nds_input import retain_secure_crc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsd")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--decrypted-reference", type=Path)
    parser.add_argument("--arm7-bios", type=Path)
    args = parser.parse_args()
    if args.decrypted_reference and args.arm7_bios:
        parser.error("decrypted inputs must not be re-encrypted with a BIOS")
    args.rom.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rom-build-", dir=args.rom.parent) as temporary:
        staged = Path(temporary) / args.rom.name
        command = [args.dsd, "rom", "build", "--config", str(args.config), "--rom", str(staged)]
        if args.arm7_bios:
            command += ["--arm7-bios", str(args.arm7_bios)]
        result = subprocess.run(command)
        if result.returncode:
            return result.returncode
        if args.decrypted_reference:
            retain_secure_crc(staged, args.decrypted_reference)
        staged.replace(args.rom)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
