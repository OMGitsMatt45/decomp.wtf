"""PS-X EXE module facts and portable period compiler choices."""

import re

from .. import cpp, toolchains
from .psx import read_exe


def profile(default, override):
    if not isinstance(override, dict) or set(override) - {"toolchain", "flags", "language"}:
        raise ValueError("PS1 function profiles accept toolchain, flags and language only")
    name = override.get("toolchain", default.get("toolchain"))
    if name not in ("gcc-2.7.2-psx", "gcc-2.8.1-psx"):
        raise ValueError("choose PS1 GCC 2.7.2 or 2.8.1")
    flags = override.get("flags", default.get("flags", toolchains.get(name).flags))
    if not isinstance(flags, list) or len(flags) > 128 or any(
            not isinstance(f, str) or len(f) > 2048 or any(c in f for c in "\0\r\n") for f in flags):
        raise ValueError("compiler flags must be a bounded list of single-line strings")
    result = {"toolchain": name, "flags": list(flags), "language": override.get("language", default.get("language", "c++"))}
    cpp.language({"kind": "rom", "platform": "psx", "compiler": result})
    return result


def gp(cfg, unit):
    return cfg.get("psx_modules", {}).get(unit, {}).get("gp", cfg.get("gp", 0))


def facts(program, overlays, default_gp):
    result = {}
    for name, data in [("main", program), *[("ovl_" + n, d) for n, d, _, _ in overlays or []]]:
        if not data.startswith(b"PS-X EXE"):
            continue
        _, info = read_exe(data)
        result[name] = {"gp": info["gp"] or (default_gp if name == "main" else 0),
                        "bss": info["bss"], "bss_size": info["bss_size"], "basis": "PS-X EXE header"}
    return result


def bss_layout(cfg, modules):
    raw = cfg["segments"]
    for i, segment in enumerate(raw):
        if not isinstance(segment, dict) or segment.get("type") != "code":
            continue
        meta = modules.get(segment["name"], {})
        if not meta.get("bss_size"):
            continue
        end = next((s[0] if isinstance(s, list) else s["start"] for s in raw[i + 1:] if isinstance(s, list) or "start" in s), None)
        loaded_end = segment["vram"] + end - segment["start"]
        # EXE sizes are sector-rounded; initial BSS bytes can also be present
        # as zero padding in that file. NOBITS still begins at its header address.
        segment["bss_size"] = max(0, meta["bss"] + meta["bss_size"] - loaded_end)
        segment["subsegments"] = [s for s in segment.get("subsegments", []) if not isinstance(s, dict)
                                  or s.get("type") not in ("bss", "sbss")]
        segment["subsegments"].append({"type": "bss", "vram": meta["bss"], "name": segment["name"] + "_bss"})


def literal_gp(workdir):
    """Keep module GP operands and special instruction/data words literal.

    Broad text envelopes can contain embedded data that spimdisasm prints as
    later MIPS instructions. PS1 GTE words also need no assembler reinterpretation.
    Preserve their exact encoding instead of enabling a different CPU ISA.
    """
    ordinary = set(("add addu addi addiu sub subu and andi or ori xor xori nor slt sltu slti sltiu "
                    "sll sllv srl srlv sra srav lui mult multu div divu mfhi mflo mthi mtlo "
                    "j jal jr jalr beq bne blez bgtz bltz bgez bltzal bgezal "
                    "lb lbu lh lhu lw lwl lwr sb sh sw swl swr syscall break "
                    "nop move neg negu not b bal beqz bnez li la .word").split())
    for path in (workdir / "asm/nonmatchings").glob("**/*.s"):
        text = path.read_text(encoding="utf-8")
        lines = []
        for line in text.splitlines():
            m = re.match(r"(\s*/\* [0-9A-F]+ [0-9A-F]{8} ([0-9A-F]{8}) \*/\s+)(\S+)(.*)", line)
            if m and m[3] not in ordinary:
                word = int.from_bytes(bytes.fromhex(m[2]), "little")
                note = (m[3] + m[4]).replace("/*", "").replace("*/", "")
                line = f"{m[1]}.word 0x{word:08X} /* literal encoding: {note.strip()} */"
            elif "%gp_rel(" in line and m:
                word = int.from_bytes(bytes.fromhex(m[2]), "little")
                immediate = (word & 0xFFFF) - (0x10000 if word & 0x8000 else 0)
                line = re.sub(r"%gp_rel\([^)]*\)", str(immediate), line)
            lines.append(line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
