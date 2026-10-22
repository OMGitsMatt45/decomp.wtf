"""Conservative ARMv4T function discovery within the ARM7 runtime module map."""

from collections import deque
from dataclasses import dataclass

from capstone import CS_ARCH_ARM, CS_GRP_CALL, CS_GRP_JUMP, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm import (ARM_CC_AL, ARM_CC_INVALID, ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,
                          ARM_REG_LR, ARM_REG_PC)
from .dsprot import detect


@dataclass
class Function:
    module: str
    address: int
    size: int
    mode: str
    instructions: list
    pools: set[int]
    calls: set[tuple[int, str]]


def discover(image, *, decoded=None, protected_entries=None, max_instructions=16384):
    """Follow entries, direct calls and constant BX destinations; retain undecodable bytes.

    This is discovery, not proof of semantic equivalence. Source and whole-ROM
    checks still compare all original bytes before consuming any recovered code.
    """
    modules = {n: m for n, m in image.modules.items() if m.cpu == "arm7"}
    programs = {}
    for name in modules:
        try:
            programs[name] = decoded[name] if decoded is not None and name in decoded else image.code(name)
            if (decoded is None or name not in decoded) and detect(programs[name], modules[name].address):
                del programs[name]  # retain protected bytes until a decoded ARM7 context exists
        except ValueError:
            pass
    decoders = {}
    for mode in ("arm", "thumb"):
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB if mode == "thumb" else CS_MODE_ARM)
        decoder.detail = True
        decoders[mode] = decoder
    entry = int.from_bytes(image.data[0x34:0x38], "little")
    entries = deque((n, (entry & ~1) if n == "arm7" else m.address,
                     "thumb" if n == "arm7" and entry & 1 else "arm")
                    for n, m in modules.items() if n in programs)
    entries.extend((name, address, "arm") for name, addresses in (protected_entries or {}).items()
                   if name in programs for address in addresses)
    boundaries = {name: set(addresses) for name, addresses in (protected_entries or {}).items()}
    functions, seen = {}, set()

    def locate(address):
        found = [name for name, module in modules.items() if name in programs and
                 module.address <= address < module.address + len(programs[name])]
        return found[0] if len(found) == 1 else None

    while entries:
        name, start, mode = entries.popleft()
        if (name, start, mode) in seen:
            continue
        seen.add((name, start, mode))
        module, code, decoder = modules[name], programs[name], decoders[mode]
        queue, visited, instructions, pools, calls = deque([start]), set(), {}, set(), set()
        valid, finished = True, False
        while queue and valid and len(visited) < max_instructions:
            at, constants = queue.popleft(), {}
            while at not in visited and len(visited) < max_instructions:
                if at != start and at in boundaries.get(name, ()):
                    finished = True
                    break
                offset = at - module.address
                if offset < 0 or offset >= len(code) or at < start:
                    valid = False
                    break
                instruction = next(decoder.disasm(code[offset:offset + 4], at, count=1), None)
                if instruction is None:
                    valid = False
                    break
                visited.add(at)
                instructions[at] = instruction
                operands = instruction.operands
                destination = operands[0].reg if operands and operands[0].type == ARM_OP_REG else None
                value = None
                if instruction.mnemonic.startswith("ldr") and len(operands) > 1 and \
                        operands[1].type == ARM_OP_MEM and operands[1].mem.base == ARM_REG_PC:
                    pc = (at + 4) & ~3 if mode == "thumb" else at + 8
                    pool = pc + operands[1].mem.disp
                    relative = pool - module.address
                    if not 0 <= relative <= len(code) - 4:
                        valid = False
                        break
                    pools.add(pool)
                    value = int.from_bytes(code[relative:relative + 4], "little")
                elif instruction.mnemonic.startswith("mov") and len(operands) == 2:
                    value = operands[1].imm if operands[1].type == ARM_OP_IMM else \
                        constants.get(operands[1].reg) if operands[1].type == ARM_OP_REG else None
                _, written = instruction.regs_access()
                for register in written:
                    constants.pop(register, None)
                if destination is not None and destination in written:
                    if value is not None:
                        constants[destination] = value
                conditional = instruction.cc not in (ARM_CC_AL, ARM_CC_INVALID)
                is_call = instruction.group(CS_GRP_CALL)
                is_return = (instruction.mnemonic == "bx" and operands[0].reg == ARM_REG_LR) or \
                    (instruction.mnemonic.startswith(("pop", "ldm")) and
                     any(op.type == ARM_OP_REG and op.reg == ARM_REG_PC for op in operands)) or \
                    (instruction.mnemonic.startswith("mov") and destination == ARM_REG_PC and
                     len(operands) > 1 and operands[1].type == ARM_OP_REG and operands[1].reg == ARM_REG_LR)
                if is_return:
                    finished = True
                    if not conditional:
                        break
                elif is_call or instruction.group(CS_GRP_JUMP) or destination == ARM_REG_PC:
                    operand = operands[-1] if operands else None
                    target = operand.imm if operand is not None and operand.type == ARM_OP_IMM else \
                        constants.get(operand.reg) if operand is not None and operand.type == ARM_OP_REG else value
                    target_mode = mode
                    if instruction.mnemonic.startswith(("bx", "blx")) or destination == ARM_REG_PC:
                        target_mode = "thumb" if target is not None and target & 1 else "arm"
                    if target is not None:
                        target &= ~1
                        owner = locate(target)
                        if is_call:
                            calls.add((target, target_mode))
                            if owner:
                                entries.append((owner, target, target_mode))
                            constants.clear()
                        elif owner != name or target < start or instruction.mnemonic.startswith("bx"):
                            if owner:
                                entries.append((owner, target, target_mode))
                            finished = True
                            if not conditional:
                                break
                        else:
                            queue.append(target)
                            if not conditional:
                                finished = True
                                break
                    elif not is_call:
                        finished = True
                        if not conditional:
                            break
                at += instruction.size
        if not valid or not instructions or not finished or len(visited) >= max_instructions:
            continue
        end = max(max(i.address + i.size for i in instructions.values()), max((p + 4 for p in pools), default=start))
        if start <= min(instructions) and end <= module.address + len(code):
            functions[name, start] = Function(name, start, end - start, mode,
                                               sorted(instructions.values(), key=lambda i: i.address), pools, calls)
    # Alternate entries and tail calls can share ranges. Keep the larger owner;
    # automatic source units must never overlap or cut through another function.
    result = []
    for function in sorted(functions.values(), key=lambda f: (f.module, f.address, -f.size)):
        if result and result[-1].module == function.module and function.address < result[-1].address + result[-1].size:
            continue
        result.append(function)
    return result

