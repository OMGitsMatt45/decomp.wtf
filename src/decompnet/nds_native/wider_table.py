"""Wider bounded Thumb halfword tables from the pinned MIT emitter.

MIT License

Copyright (c) 2026 DQ9-Decomp contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This license covers only the original source code in this repository. It
grants no rights in Dragon Quest IX or any other third-party work; see
LEGAL.md.

The original 256-entry ceiling is raised to 4096. Image bounds, function
bounds and the first case-code boundary still bound inference.
"""
from capstone.arm_const import ARM_OP_REG,ARM_OP_IMM,ARM_OP_MEM


def make(emitter):
    operand_reg=emitter.operand_reg
    reg_index=emitter.reg_index
    _U32=0xffffffff
    def table_info(self, insn):
        ops = insn.operands
        if len(ops) != 2 or ops[0].type != ARM_OP_REG or ops[1].type != ARM_OP_REG:
            return None
        if operand_reg(insn, ops[0]) != 15:
            return None
        target_reg = operand_reg(insn, ops[1])
        previous = self._preceding(insn, 24)
        load_pos = -1
        load = None
        mem = None
        for pos in range(len(previous) - 1, -1, -1):
            candidate = previous[pos]
            if candidate.mnemonic.split(".")[0] not in {"ldrh", "ldrsh"} or len(candidate.operands) < 2:
                continue
            if candidate.operands[0].type != ARM_OP_REG or operand_reg(candidate, candidate.operands[0]) != target_reg:
                continue
            memop = next((operand for operand in candidate.operands if operand.type == ARM_OP_MEM), None)
            if memop is None or not memop.mem.base or memop.mem.index:
                continue
            load_pos, load, mem = pos, candidate, memop.mem
            break
        if load is None or mem is None:
            return None

        base_reg = reg_index(load, mem.base)
        add_pos = -1
        for pos in range(load_pos - 1, -1, -1):
            candidate = previous[pos]
            candidate_ops = candidate.operands
            if candidate.mnemonic.split(".")[0].rstrip("s") != "add" or len(candidate_ops) != 2:
                continue
            if (
                candidate_ops[0].type == ARM_OP_REG
                and candidate_ops[1].type == ARM_OP_REG
                and operand_reg(candidate, candidate_ops[0]) == base_reg
                and operand_reg(candidate, candidate_ops[1]) == 15
            ):
                add_pos = pos
                break
        if add_pos < 0:
            return None

        key_reg = None
        for candidate in reversed(previous[:add_pos]):
            candidate_ops = candidate.operands
            if not candidate_ops or candidate_ops[0].type != ARM_OP_REG:
                continue
            if operand_reg(candidate, candidate_ops[0]) != base_reg:
                continue
            name = candidate.mnemonic.split(".")[0].rstrip("s")
            if name == "add" and len(candidate_ops) >= 3 and candidate_ops[1].type == ARM_OP_REG and candidate_ops[2].type == ARM_OP_REG:
                lhs = operand_reg(candidate, candidate_ops[1])
                rhs = operand_reg(candidate, candidate_ops[2])
                if lhs == rhs:
                    key_reg = lhs
            elif name == "add" and len(candidate_ops) == 2 and candidate_ops[1].type == ARM_OP_REG:
                lhs = operand_reg(candidate, candidate_ops[1])
                if lhs == base_reg:
                    key_reg = lhs
            elif name == "lsl" and len(candidate_ops) >= 3 and candidate_ops[1].type == ARM_OP_REG:
                key_reg = operand_reg(candidate, candidate_ops[1])
            break

        signed = load.mnemonic.split(".")[0] == "ldrsh"
        shifted_high = False
        for candidate in previous[load_pos + 1 :]:
            candidate_ops = candidate.operands
            name = candidate.mnemonic.split(".")[0].rstrip("s")
            if name == "sxth" and candidate_ops and candidate_ops[0].type == ARM_OP_REG and operand_reg(candidate, candidate_ops[0]) == target_reg:
                signed = True
            if (
                name == "lsl"
                and len(candidate_ops) >= 3
                and candidate_ops[0].type == ARM_OP_REG
                and candidate_ops[1].type == ARM_OP_REG
                and candidate_ops[2].type == ARM_OP_IMM
                and operand_reg(candidate, candidate_ops[0]) == target_reg
                and operand_reg(candidate, candidate_ops[1]) == target_reg
                and int(candidate_ops[2].imm) == 16
            ):
                shifted_high = True
            if (
                shifted_high
                and name == "asr"
                and len(candidate_ops) >= 3
                and candidate_ops[0].type == ARM_OP_REG
                and candidate_ops[1].type == ARM_OP_REG
                and candidate_ops[2].type == ARM_OP_IMM
                and operand_reg(candidate, candidate_ops[0]) == target_reg
                and operand_reg(candidate, candidate_ops[1]) == target_reg
                and int(candidate_ops[2].imm) == 16
            ):
                signed = True

        table_base_pc = previous[add_pos].address + 4
        table = (table_base_pc + int(mem.disp)) & _U32
        table_offset = table - self.base
        available = min(4096, max(0, (len(self.image) - table_offset) // 2)) if table_offset >= 0 else 0
        if available == 0:
            return None

        branch_pc = insn.address + 4
        count = self._jump_case_count(insn, key_reg, None) if key_reg is not None else None
        if count is None:
            # The case code follows the table: stop at the first entry whose
            # address reaches the lowest target seen so far.
            count = 0
            lowest = None
            for index in range(available):
                entry_address = table + index * 2
                if lowest is not None and entry_address >= lowest:
                    break
                raw = self._literal(insn, entry_address, 2)
                if raw is None:
                    break
                offset = raw - 0x10000 if signed and raw & 0x8000 else raw
                target = (branch_pc + offset) & ~1
                if not self._function_contains(target):
                    break
                lowest = target if lowest is None else min(lowest, target)
                count += 1
        else:
            count = min(count, available)

        cases: list[tuple[int, int]] = []
        seen: set[int] = set()
        for index in range(count):
            raw = self._literal(insn, table + index * 2, 2)
            if raw is None:
                break
            offset = raw - 0x10000 if signed and raw & 0x8000 else raw
            target = (branch_pc + offset) & ~1
            if self._function_contains(target):
                key = offset & _U32
                if key not in seen:
                    cases.append((key, target))
                    seen.add(key)
        if not cases:
            return None
        return {"kind": "thumb_halfword", "index": target_reg, "base": branch_pc, "cases": cases}
    return table_info
