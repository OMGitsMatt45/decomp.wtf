"""Standalone RGBDS export builder. Copied into exports as build.py (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class BuildError(ValueError):
    pass


def _run(command: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildError(f"cannot run {Path(command[0]).name}: {error}") from error
    if result.returncode:
        raise BuildError(f"{Path(command[0]).name} failed:\n{result.stdout}{result.stderr}")
    return result.stdout.strip()


def build(project: Path, base: Path, *, rgbds: Path | None = None, output: Path | None = None) -> dict:
    project = project.resolve()
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "decompnet-gb-assembly-v1" or manifest.get("rgbds") != "1.0.4":
        raise BuildError("unsupported Game Boy assembly manifest/version")
    raw = base.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != manifest["rom"]["size"] or digest != manifest["rom"]["sha256"]:
        raise BuildError("base ROM size/SHA-256 does not match this export")
    if rgbds is None:
        try:
            from decompnet import toolchains
            rgbds = toolchains.require("rgbds")
        except (ImportError, RuntimeError) as error:
            raise BuildError("install `decompnet toolchain install rgbds` or pass --rgbds DIR") from error
    rgbds = rgbds.resolve()
    suffix = ".exe" if sys.platform == "win32" else ""
    assembler, linker = (str(rgbds / (name + suffix)) for name in ("rgbasm", "rgblink"))
    versions = [_run([program, "--version"], project) for program in (assembler, linker)]
    if versions != ["rgbasm v1.0.4", "rgblink v1.0.4"]:
        raise BuildError(f"this export needs RGBDS 1.0.4, found {versions}")
    with tempfile.TemporaryDirectory(prefix="decomp-gb-") as scratch:
        work = Path(scratch)
        (work / "baserom.gb").write_bytes(raw)
        _run([assembler, "-I", project.as_posix() + "/", "-o", "project.o", str(project / "main.asm")], work)
        _run([linker, "-o", "rebuilt.gb", "-m", "rebuilt.map", "-n", "rebuilt.sym", "project.o"], work)
        rebuilt = (work / "rebuilt.gb").read_bytes()
        if rebuilt != raw:
            first = next((i for i, (a, b) in enumerate(zip(raw, rebuilt)) if a != b), min(len(raw), len(rebuilt)))
            bank, within = divmod(first, 0x4000)
            cpu = within + (0x4000 if bank else 0)
            raise BuildError(f"ROM mismatch at file offset ${first:x} (bank {bank:02x}:${cpu:04x}); "
                             f"expected {len(raw)} bytes, got {len(rebuilt)}. No output was published.")
        extension = ".gbc" if manifest["rom"]["platform"] == "gbc" else ".gb"
        output = (output or project / "build" / ("rebuilt" + extension)).resolve()
        if output == base.resolve() or (output.is_relative_to(project) and not output.is_relative_to(project / "build")):
            raise BuildError("output must not overwrite the base ROM or project sources")
        output.parent.mkdir(parents=True, exist_ok=True)
        # Publish only after the whole ROM compares equal, even for patched headers.
        fd, staged = tempfile.mkstemp(prefix=".decomp-gb-", dir=output.parent)
        try:
            with os.fdopen(fd, "wb") as dest:
                dest.write(rebuilt)
            os.replace(staged, output)
        finally:
            Path(staged).unlink(missing_ok=True)
    return {"matched": True, "sha256": digest, "size": len(rebuilt), "output": str(output),
            "assembly_bytes": manifest["assembly_bytes"], "base_bytes": manifest["base_bytes"],
            "tools": versions}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reassemble a Game Boy cartridge and verify every byte")
    ap.add_argument("rom", type=Path, help="your original .gb/.gbc file")
    ap.add_argument("--rgbds", type=Path, help="directory containing RGBDS 1.0.4 executables")
    ap.add_argument("--output", type=Path, help="verified ROM destination (default: build/rebuilt.gb or .gbc)")
    args = ap.parse_args(argv)
    try:
        print(json.dumps(build(Path(__file__).resolve().parent, args.rom, rgbds=args.rgbds, output=args.output), indent=2))
    except (BuildError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
