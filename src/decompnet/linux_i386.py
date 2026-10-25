"""Explicit user-mode emulation for period compilers on Linux without IA32 support.

The original toolchain stays read-only. A temporary mirror supplies shell launchers
for its i386 programs, including GCC's child phases; no binfmt registration is used.
The caller runs these launchers inside the same compile sandbox as native tools.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from . import wsl


def is_i386(path: Path) -> bool:
    try:
        with path.open("rb") as executable:
            head = executable.read(20)
        return head[:6] == b"\x7fELF\x01\x01" and head[18:20] == b"\x03\x00"
    except OSError:
        return False


def prepare(argv: list[str], roots: tuple[str, ...], dest: Path, qemu: str,
            runtime32: str | None) -> list[str]:
    """Mirror only toolchains containing i386 executables and rewrite their paths."""
    emulator = Path(qemu)
    if not emulator.is_absolute() or not emulator.is_file():
        raise ValueError("qemu_i386 must be the absolute path to an installed qemu-i386 executable")
    replacements = {}
    for index, root in enumerate(dict.fromkeys(roots)):
        original = Path(root)
        files = sorted(p for p in original.rglob("*") if p.is_file())
        programs = {p for p in files if is_i386(p)}
        if not programs:
            continue
        mirror = dest / str(index)
        replacements[str(original)] = str(mirror)
        # GCC searches these before its compiled-in paths. Child programs need
        # their own launchers because QEMU does not emulate a host execve.
        phases = sorted({str(mirror / p.parent.relative_to(original)) + "/"
                         for p in files if p.name in ("cc1", "cc1plus", "cpp0", "as", "ee-as")
                         and "-B" + str(p.parent) + "/" not in argv})
        for path in files:
            target = mirror / path.relative_to(original)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path not in programs:
                target.symlink_to(path)
                continue
            command = [qemu, "-R", "1G"]
            if wsl.is_dynamic_i386(path):
                if not runtime32:
                    raise ValueError(f"i386 program {path.name} needs compiler.runtime32")
                command += [str(Path(runtime32) / "ld-linux.so.2"), "--library-path", runtime32]
            command.append(str(path))
            if path.name in ("gcc", "g++") or path.name.endswith(("-gcc", "-g++")):
                command += ["-B" + directory for directory in phases]
            target.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n', encoding="utf-8")
            target.chmod(0o755)
    if not replacements:
        return argv
    # Also handles full paths inside the trusted agbcc shell pipeline and -B
    # flags. Replace each original prefix once, longest first for nested roots.
    pattern = re.compile("|".join(re.escape(p) for p in sorted(replacements, key=len, reverse=True)))
    return [pattern.sub(lambda match: replacements[match[0]], arg) for arg in argv]
