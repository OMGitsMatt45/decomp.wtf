"""Compile an isolated ARM7 C/C++ candidate and compare its complete raw function bytes."""

import hashlib
import re
import sys

from capstone import CS_ARCH_ARM, CS_GRP_CALL, CS_GRP_JUMP, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

from .. import seeds, toolchains
from ..compiler import CompilerConfig, compile_source
from ..elfobj import extract_function
from .dsprot import detect
from .nds_modules import NdsImage

RECOVERY_CONTEXT = """\
typedef signed char s8;
typedef unsigned char u8;
typedef signed short s16;
typedef unsigned short u16;
typedef signed int s32;
typedef unsigned int u32;
typedef signed long long s64;
typedef unsigned long long u64;
#ifndef NULL
#define NULL 0
#endif
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
#define M2C_BITWISE(type, expr) ((type)(expr))
"""


def _target(image: NdsImage, module_name: str, address: int, size: int, mode: str) -> bytes:
    module = image.modules.get(module_name)
    if module is None or module.cpu != "arm7":
        raise ValueError("select an ARM7 module (arm7 or arm7:ov<ID>)")
    if module.flags & 0x2000000:
        raise ValueError("signed ARM7 overlays need authentication support before recovery")
    if mode not in ("arm", "thumb"):
        raise ValueError("mode must be arm/thumb")
    alignment = 2 if mode == "thumb" else 4
    if size <= 0 or size % alignment or address % alignment:
        raise ValueError("function address and size must match instruction alignment")
    code = image.code(module_name)
    start = address - module.address
    if start < 0 or start + size > len(code):
        raise ValueError("function outside initialized ARM7 module")
    if detect(code, module.address):
        raise ValueError("DS Protect candidate in module: decode and validate protection before recovery")
    return code[start:start + size]


def draft(image: NdsImage, module_name: str, address: int, size: int, mode: str, symbol: str) -> str:
    """Draft a bounded leaf with m2c. External branches and PC-relative pools need a linker."""
    if not re.fullmatch(r"[A-Za-z_]\w*", symbol):
        raise ValueError("symbol must be a C identifier")
    code = _target(image, module_name, address, size, mode)
    disassembler = Cs(CS_ARCH_ARM, CS_MODE_THUMB if mode == "thumb" else CS_MODE_ARM)
    disassembler.detail = True
    instructions = list(disassembler.disasm(code, address))
    if sum(i.size for i in instructions) != size or not instructions:
        raise ValueError("range contains undecodable instructions")
    if (instructions[-1].mnemonic, instructions[-1].op_str) != ("bx", "lr"):
        raise ValueError("initial recovery requires a leaf ending in bx lr")
    boundaries = {i.address for i in instructions}
    labels = set()
    body = []
    for instruction in instructions:
        operands = instruction.op_str
        if instruction.group(CS_GRP_CALL):
            raise ValueError("calls require linked ARM7 units")
        if any((op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC) or
               (op.type == ARM_OP_REG and op.reg == ARM_REG_PC) for op in instruction.operands):
            raise ValueError("PC-relative references require linked ARM7 data")
        if instruction.group(CS_GRP_JUMP) and instruction.mnemonic != "bx":
            if not instruction.operands or instruction.operands[-1].type != ARM_OP_IMM:
                raise ValueError("indirect branch needs analysis")
            target = instruction.operands[-1].imm
            if target not in boundaries:
                raise ValueError("branch outside function needs linked ARM7 units")
            labels.add(target)
            operands = f".L_{target:08X}"
        elif instruction.mnemonic == "bx" and instruction.op_str != "lr":
            raise ValueError("indirect branch needs analysis")
        body.append((instruction.address, f"{instruction.mnemonic} {operands}"))
    lines = [f"glabel {symbol}"]
    for at, text in body:
        if at in labels:
            lines.append(f".L_{at:08X}:")
        lines.append(text)
    source = seeds.run_m2c("\n".join(lines) + "\n", symbol,
                          f"{'gba' if mode == 'thumb' else 'arm'}-mwcc-c", valid=True)
    if not source or any(token in source for token in ("M2C_ERROR", "M2C_CARRY", "M2C_OVERFLOW", "M2C_UNK")):
        raise ValueError("m2c unavailable or could not recover this leaf without unresolved operations")
    return RECOVERY_CONTEXT + "\n" + source + "\n"


def verify(image: NdsImage, module_name: str, address: int, size: int, mode: str,
           source: str, symbol: str, *, language="c", version="2.0/sp1p5") -> dict:
    """No BIOS, reference mutation, relocation masking, or whole-ROM matching claim.

    This first increment deliberately requires a relocation-free function. Calls,
    references to external data, and linked source-unit placement need a linker.
    """
    reference = _target(image, module_name, address, size, mode)
    if language not in ("c", "c++"):
        raise ValueError("language must be c/c++")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", version) or any(p in (".", "..") for p in version.split("/")):
        raise ValueError("invalid CodeWarrior version")
    base = toolchains.require("mwccarm") / "mwccarm"
    cc = base / version / "mwccarm.exe"
    if not cc.is_file():
        raise ValueError(f"CodeWarrior version is not installed: {version}")
    wrap = [] if sys.platform == "win32" else [str(toolchains.binary("wibo"))]
    dirs = (*toolchains.runtime_dirs("mwccarm"),
            *(toolchains.runtime_dirs("wibo") if wrap else ()))
    flags = ["-O4,p", "-enum", "int", "-char", "signed", "-str", "noreuse", "-proc", "arm7tdmi",
             "-gccext,on", "-fp", "soft", "-inline", "noauto", "-Cpp_exceptions", "off", "-RTTI", "off",
             "-interworking", "-w", "off", "-sym", "on", "-gccinc", "-nolink", "-msgstyle", "gcc"]
    cfg = CompilerConfig([*wrap, str(cc), *flags, f"-lang={language}", "-I{include}",
                          "-c", "{src}", "-o", "{obj}"],
                         language=language, ro_paths=tuple(str(d) for d in dirs))
    result = compile_source(cfg, f"#pragma thumb {'on' if mode == 'thumb' else 'off'}\n", source)
    report = {"module": module_name, "address": address, "size": size, "mode": mode,
              "symbol": symbol, "language": language, "compiler": f"DS/{version}", "cpu": "arm7tdmi",
              "reference_sha256": hashlib.sha256(reference).hexdigest(), "exact": False,
              "whole_rom_verified": False}
    if not result.ok:
        return {**report, "reason": "compilation failed", "log": result.log}
    try:
        function = extract_function(result.obj, symbol)
    except ValueError as error:
        return {**report, "reason": str(error)}
    if function is None:
        return {**report, "reason": f"object has no function named {symbol}"}
    report.update(compiled_size=len(function.code), compiled_sha256=hashlib.sha256(function.code).hexdigest())
    if function.arch != mode or function.big_endian:
        return {**report, "reason": "compiled instruction mode or byte order differs"}
    if function.relocs:
        return {**report, "reason": "function has relocations; linked ARM7 units are not supported yet",
                "relocations": [r.to_json() for r in function.relocs]}
    report["exact"] = function.code == reference
    if not report["exact"]:
        report["reason"] = "compiled bytes or function size differ"
    return report
