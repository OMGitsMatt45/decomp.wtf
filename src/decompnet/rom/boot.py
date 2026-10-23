"""Assembly-only DS boot utilities with explicit original-image provenance."""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path
import capstone
from .. import platforms
from .errors import RomError


def identify(path: Path):
    from ..forks import scratch_dsd
    from .detect import Picked
    with path.open('rb') as source:
        head = source.read(0x440)
    platforms.require(platforms.removed_input(head, path.stat().st_size), RomError)
    if not scratch_dsd.is_nds(head):
        return None
    if struct.unpack_from("<II", head, 0x40)[1]:
        return None
    data = path.read_bytes()
    segments, entries = [], []
    for name, at in (("arm9", 0x20), ("arm7", 0x30)):
        offset, entry, ram, size = struct.unpack_from("<IIII", head, at)
        if not size:
            continue
        if offset < 0x200 or offset + size > len(data) or not ram <= (entry & ~1) < ram + size:
            raise RomError(f"invalid DS {name} program range")
        segments.append({"name": name, "rom_start": offset, "rom_end": offset + size, "vram": ram})
        entries.append(entry)
    meta = {"arch": "arm", "scope": "cartridge", "segments": segments, "entries": entries}
    title = scratch_dsd.game_info(path)["title"]
    platform, game_id, filename = "nds", head[12:16].decode("ascii", "replace").strip(), "baserom.nds"
    with path.open("rb") as source:
        meta["input_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    info = {"title": title, "game_code": game_id, "region": "Boot utility", "size": len(data),
            "sha1": hashlib.sha1(data).hexdigest(), "platform": platform, "byte_order": "big" if platform != "nds" else "little",
            "compiler_guess": "GNU assembly (boot utility)", "gp": 0, "boot_utility": meta}
    return Picked(platform, data, filename, info, platform != "nds")


def disassembler(arch: str, thumb: bool = False):
    if arch == "ppc":
        md = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 | capstone.CS_MODE_BIG_ENDIAN)
    else:
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB if thumb else capstone.CS_MODE_ARM)
    md.detail = True
    return md


def discover(data: bytes, meta: dict) -> list[dict]:
    """Follow direct control flow. Indirect branches and unvisited data stay in the base.

    Results are contiguous instruction ranges, deliberately not guesses at C
    function boundaries. Small ranges also keep submissions within source limits.
    """
    arch = meta["arch"]
    engines = {False: disassembler(arch), True: disassembler(arch, True)}
    pending = [(entry & ~1, bool(entry & 1)) for entry in meta.get("entries", [meta.get("entry", 0)])]
    decoded = {}
    def executable(value):
        return any(s["vram"] <= (value & ~1) < min(s["vram"] + s["rom_end"] - s["rom_start"],
                                                  meta.get("analysis_end", 1 << 32)) for s in meta["segments"])

    while pending:
        address, thumb = pending.pop()
        registers = {}
        while address not in decoded:
            seg = next((s for s in meta["segments"] if s["vram"] <= address < s["vram"] + s["rom_end"] - s["rom_start"]), None)
            if seg is None or address >= meta.get("analysis_end", 1 << 32):
                break
            offset = seg["rom_start"] + address - seg["vram"]
            insn = next(engines[thumb].disasm(data[offset:min(offset + 4, seg["rom_end"])], address, count=1), None)
            if insn is None or not any(insn.bytes):
                break
            decoded[address] = (insn, thumb, offset, seg["name"])
            # Apploader entry points return callbacks through pointer arguments;
            # those functions have no direct callers. Follow constant addresses.
            if arch == "ppc" and insn.mnemonic == "lis" and len(insn.operands) == 2:
                registers[insn.operands[0].reg] = (insn.operands[1].imm << 16) & 0xFFFFFFFF
            elif arch == "ppc" and insn.mnemonic in ("addi", "ori") and len(insn.operands) == 3:
                dest, src, imm = insn.operands
                if src.reg in registers:
                    value = (registers[src.reg] + imm.imm if insn.mnemonic == "addi" else registers[src.reg] | imm.imm) & 0xFFFFFFFF
                    registers[dest.reg] = value
            elif arch == "ppc" and insn.mnemonic == "stw" and insn.operands:
                value = registers.get(insn.operands[0].reg)
                if value is not None:
                    if executable(value) and value % 4 == 0:
                        pending.append((value, False))
            elif arch == "arm" and insn.mnemonic.startswith("ldr") and len(insn.operands) == 2:
                operand = insn.operands[-1]
                if operand.type == capstone.arm.ARM_OP_MEM and operand.mem.base == capstone.arm.ARM_REG_PC:
                    literal = ((address + 4) & ~3 if thumb else address + 8) + operand.mem.disp
                    at = seg["rom_start"] + literal - seg["vram"]
                    if seg["rom_start"] <= at and at + 4 <= seg["rom_end"]:
                        value = struct.unpack_from("<I", data, at)[0]
                        registers[insn.operands[0].reg] = value
                        if insn.operands[0].reg == capstone.arm.ARM_REG_PC and executable(value):
                            pending.append((value & ~1, bool(value & 1)))
            if arch == "arm" and insn.mnemonic in ("bx", "blx") and insn.operands \
                    and insn.operands[0].type == capstone.arm.ARM_OP_REG:
                value = registers.get(insn.operands[0].reg)
                if value is not None and executable(value):
                    pending.append((value & ~1, bool(value & 1)))
            jump = insn.group(capstone.CS_GRP_JUMP)
            call = insn.group(capstone.CS_GRP_CALL)
            dest = None
            if jump or call:
                # ARM and PPC both expose an immediate branch target last.
                if insn.operands and insn.operands[-1].type == 2:
                    dest = insn.operands[-1].imm & 0xFFFFFFFF
                    pending.append((dest & ~1, not thumb if insn.mnemonic.startswith("blx") else thumb))
            name, ops = insn.mnemonic, insn.op_str
            unconditional = name in ("b", "bx", "bxj", "blr", "bctr", "ba", "rfi")
            returns = insn.group(capstone.CS_GRP_RET) or (arch == "arm" and
                       ((name.startswith("pop") or name.startswith("ldm")) and "pc" in ops
                        or name == "mov" and ops == "pc, lr"))
            if (jump and not call and unconditional) or returns:
                break
            address += insn.size
    ranges = []
    for address, (insn, thumb, offset, segment) in sorted(decoded.items()):
        if ranges and ranges[-1]["addr"] + ranges[-1]["size"] == address and ranges[-1]["thumb"] == thumb \
                and ranges[-1]["segment"] == segment and ranges[-1]["size"] < 1024:
            ranges[-1]["size"] += insn.size
        else:
            ranges.append({"name": f"boot_{address:08X}", "addr": address, "offset": offset,
                           "size": insn.size, "thumb": thumb, "segment": segment})
    if not ranges:
        raise RomError("no boot instructions were reachable from the program entry points")
    return ranges


def assembly(code: bytes, address: int, name: str, arch: str, thumb: bool = False) -> str:
    """Editable instructions with absolute linker symbols for direct branches."""
    import re

    lines = [".text", f".global {name}", f".type {name}, %function"]
    if arch == "arm":
        lines += [".syntax unified", ".thumb" if thumb else ".arm"]
        if thumb:
            lines += [".thumb_func"]
    lines += [f"{name}:"]
    end = address
    for insn in disassembler(arch, thumb).disasm(code, address):
        ops = insn.op_str
        mnemonic = insn.mnemonic
        if arch == "arm" and thumb and mnemonic == "adr":
            # Capstone reports the encoded PC displacement; GNU's ADR pseudo
            # expects a label. The explicit ADD form retains the displacement.
            mnemonic = "add"
            ops = ops.replace(", #", ", pc, #", 1)
        if arch == "ppc":
            # Capstone spells condition bits cr1eq; GNU as takes bit numbers.
            ops = re.sub(r"\bcr([0-7])(lt|gt|eq|so|un)\b",
                         lambda m: str(4 * int(m[1]) + {"lt": 0, "gt": 1, "eq": 2, "so": 3, "un": 3}[m[2]]), ops)
        if (insn.group(capstone.CS_GRP_JUMP) or insn.group(capstone.CS_GRP_CALL)) and insn.operands \
                and insn.operands[-1].type == 2:
            target = insn.operands[-1].imm & 0xFFFFFFFF
            ops = re.sub(r"#?(?:0x[0-9a-f]+|[0-9]+)$", f"__boot_{target & ~1:08X}", ops)
        lines.append(f"/* {insn.address:08X} */  {mnemonic} {ops}".rstrip())
        end += insn.size
    if end != address + len(code):
        raise RomError("assembly range contains undecodable instruction bytes")
    lines += [f".size {name}, . - {name}"]
    return "\n".join(lines) + "\n"
