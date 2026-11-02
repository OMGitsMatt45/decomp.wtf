"""Prove a frameless return through a register holding the incoming LR."""
from capstone.arm_const import ARM_OP_IMM,ARM_OP_REG


def returns_incoming_lr(function,branch,emitter):
    if function.dispatch_entries is not None or function._branch_name(branch)!='bx' or len(branch.operands)!=1:return False
    if branch.operands[0].type!=ARM_OP_REG:return False
    register=emitter.operand_reg(branch,branch.operands[0])
    if register in (13,14,15):return False
    first=function.insns.get(function.begin)
    if (first is None or first.condition!=14 or function._branch_name(first)!='mov' or len(first.operands)!=2
            or any(o.type!=ARM_OP_REG for o in first.operands)
            or emitter.operand_reg(first,first.operands[0])!=register or emitter.operand_reg(first,first.operands[1])!=14):return False
    protected={register,13}

    def writes_protected(op):
        try:_,writes=op.detail.regs_access()
        except (AttributeError,ValueError):return True
        return any(emitter.reg_index(op,r)in protected for r in writes if op.detail.reg_name(r)not in ('cpsr','spsr'))

    def preserves_leaf(entry):
        if entry.module_id!=function.entry.module_id or entry.thumb!=function.thumb:return False
        pending=[entry.address];visited=set();returned=False
        while pending:
            pc=pending.pop()
            if pc in visited:continue
            if not entry.address<=pc<entry.end:return False
            op=function.decoder.decode(pc)
            if op is None or op.next_address>entry.end or writes_protected(op):return False
            visited.add(pc);name=function._branch_name(op)
            if name in ('bl','blx'):return False
            if name=='bx':
                if len(op.operands)!=1 or op.operands[0].type!=ARM_OP_REG or emitter.operand_reg(op,op.operands[0])!=14:return False
                returned=True
                if op.condition!=14:pending.append(op.next_address)
            elif name=='b':
                target=function._branch_target(op)
                if target is None:return False
                pending.append(target&~1)
                if op.condition!=14:pending.append(op.next_address)
            else:
                # Other PC writes or indirect exits are not leaf proof.
                _,writes=op.detail.regs_access()
                if any(op.detail.reg_name(r)=='pc'for r in writes):return False
                pending.append(op.next_address)
            if len(visited)>256:return False
        return returned

    for op in function.insns.values():
        if op is first:continue
        if writes_protected(op):return False
        name=function._branch_name(op)
        if name in ('bl','blx'):
            if len(op.operands)!=1 or op.operands[0].type!=ARM_OP_IMM:return False
            target=function._branch_target(op);entry=function._slot_for(target,op)
            if entry is None or not preserves_leaf(entry):return False
    return True
