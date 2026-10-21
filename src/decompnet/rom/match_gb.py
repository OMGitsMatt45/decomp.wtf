"""Link an RGBDS candidate at its bank/CPU address and compare every owned byte."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..compiler import CompilerConfig, _SLOTS, compile_source, run_in
from ..elfobj import FunctionObj
from . import gb


def source(raw: bytes, address: int, size: int, name: str) -> str:
    region = gb.CodeRange(gb.Address.from_key(address), size)
    original = f"code_{region.start.bank:03x}_{region.start.cpu:04x}"
    return gb.assembly(raw, region).replace(original, name)


def externals(symbols, exclude: set[str]) -> str:
    stubs = []
    for index, sym in enumerate(symbols.by_name.values()):
        if sym.name in exclude:
            continue
        try:
            other = gb.Address.from_key(sym.address)
        except gb.CartridgeError:
            stubs += [f"DEF {sym.name} EQU ${sym.address & 0xffff:04x}", f"EXPORT {sym.name}"]
            continue
        section = f"ROMX[${other.cpu:04x}], BANK[${other.bank:x}]" if other.bank else f"ROM0[${other.cpu:04x}]"
        stubs += [f'SECTION "__dn_external_{index}", {section}', f"{sym.name}::"]
    return "\n".join(stubs)


def link(obj: bytes, name: str, address: int, target: bytes, symbols, cfg: CompilerConfig):
    """Return candidate, strict verdict, diagnostics; never relocation-normalize SM83 bytes."""
    addr = gb.Address.from_key(address)
    executable = Path(cfg.cmd[0])
    linker = str(executable.with_name("rgblink.exe" if sys.platform == "win32" else "rgblink"))
    compiled = compile_source(cfg, "", externals(symbols, {name}), trusted=True)
    if not compiled.ok:
        return None, False, ["could not assemble external symbol addresses", compiled.log]
    with tempfile.TemporaryDirectory(prefix="decomp-gb-link-") as temp:
        work = Path(temp)
        (work / "candidate.o").write_bytes(obj)
        (work / "externals.o").write_bytes(compiled.obj)
        try:
            with _SLOTS:
                result = run_in(cfg, work, [linker, "-o", "candidate.gb", "-m", "candidate.map", "-n", "candidate.sym",
                                             "candidate.o", "externals.o"], timeout=cfg.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, False, [f"RGBDS linker failed: {error}"]
        if result.returncode:
            return None, False, [(result.stdout + result.stderr)[-4000:]]
        locations = {}
        for line in (work / "candidate.sym").read_text(encoding="utf-8").splitlines():
            found = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]{4}) (\S+)", line)
            if found:
                locations[found[3]] = (int(found[1], 16), int(found[2], 16))
        sections, bank = [], None
        for line in (work / "candidate.map").read_text(encoding="utf-8").splitlines():
            head = re.fullmatch(r"(ROM0|ROMX|VRAM|SRAM|WRAM0|WRAMX|OAM|HRAM) bank #(\d+):", line)
            if head:
                bank = (head[1], int(head[2]))
            section = re.search(r'SECTION: \$([0-9a-fA-F]+)(?:-\$[0-9a-fA-F]+)? \(\$([0-9a-fA-F]+) bytes?\)', line)
            if section and int(section[2], 16):
                sections.append((bank, int(section[1], 16), int(section[2], 16)))
        expected = (("ROMX" if addr.bank else "ROM0", addr.bank), addr.cpu, len(target))
        problems = []
        if locations.get(name) != (addr.bank, addr.cpu):
            problems.append(f"{name} must start at bank/CPU address {addr}")
        if sections != [expected]:
            problems.append(f"candidate must own exactly one ROM section at {addr}, {len(target)} bytes; found {sections}")
        if problems:
            return None, False, problems
        raw = (work / "candidate.gb").read_bytes()
        code = raw[addr.offset:addr.offset + len(target)]
        return FunctionObj(name, "sm83", False, code), code == target, []
