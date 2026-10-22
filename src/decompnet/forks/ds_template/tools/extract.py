#!/usr/bin/env python3
"""Run ds-decomp extraction and reject a secure area it could not decrypt.

dsd can warn about an invalid decrypted prefix and still exit successfully.
Such output must not become the reference objects used to judge source.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from nds_input import empty_constructors, restore_prefix, stage_decrypted


def arm7_contexts(dsd, staged, target):
    """Regenerate private decoded views when a standalone export extracts afresh."""
    manifest = target.parent.parent / "config" / target.name / "arm7" / "units.json"
    if not manifest.is_file():
        return
    from arm7_codec import decode
    for module in json.loads(manifest.read_text(encoding="utf-8"))["modules"].values():
        if not module.get("codec"):
            continue
        local = lambda value: staged / Path(value).relative_to(Path("extract") / target.name)
        original = local(module["output_binary"]).read_bytes()
        start = module["output_offset"]
        if start < 0 or start + module["size"] > len(original):
            raise ValueError("ARM7 protected view exceeds the original program")
        plain, _ = decode(dsd, original[start:start + module["size"]], module["address"], local(module["codec"]))
        local(module["binary"]).write_bytes(plain)


def main(argv: list[str]) -> int:
    argv = list(argv)
    analysis = "--analysis-layout" in argv
    if analysis:
        argv.remove("--analysis-layout")
    input_format = "auto"
    if "--input-format" in argv:
        at = argv.index("--input-format")
        input_format = argv[at + 1]
        del argv[at:at + 2]
    if input_format not in ("auto", "decrypted"):
        raise ValueError("input format must be auto or decrypted")
    if input_format == "decrypted" and "--arm7-bios" in argv:
        raise ValueError("decrypted inputs must not be decrypted again with a BIOS")
    output = argv.index("--output-path") + 1
    target = Path(argv[output]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # dsd writes config.yaml before validating the secure area. Keep partial
    # output away from Ninja's dependency target and existing reference data.
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-extract-", dir=target.parent) as temporary:
        staged = Path(temporary) / "rom"
        command = [*argv[:output], str(staged), *argv[output + 1:]]
        prefix = None
        if input_format == "decrypted":
            source = command.index("--rom") + 1
            copied = Path(temporary) / "decrypted.nds"
            prefix = stage_decrypted(Path(command[source]), copied)
            command[source] = str(copied)
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=3500)
        except subprocess.TimeoutExpired:
            print("error: ds-decomp ROM extraction timed out", file=sys.stderr)
            return 124
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode:
            return result.returncode
        if "Failed to decrypt secure area" in result.stdout + result.stderr:
            print("error: the ARM7 BIOS did not validate the ROM's encrypted secure area. "
                  "Check your BIOS and game copy; nonstandard secure-area prefixes are not supported.", file=sys.stderr)
            return 1
        if prefix is not None:
            restore_prefix(staged, prefix)
        empty_constructors(staged, analysis=analysis)
        arm7_contexts(argv[0], staged, target)
        previous = Path(temporary) / "previous"
        if target.exists():
            target.replace(previous)
        try:
            staged.replace(target)
        except OSError:
            if previous.exists():
                previous.replace(target)
            raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
