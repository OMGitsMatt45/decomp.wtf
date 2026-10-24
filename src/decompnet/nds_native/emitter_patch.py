"""Bounds recovery fixes for the pinned MIT DQ9-Decomp emitter.

A signed lower-bound guard must not truncate a following switch table. This
adapts the upstream emitter through its decoded instruction interface; no game
addresses, bytes or title-specific entry lists are used.
"""
from capstone.arm_const import ARM_OP_IMM, ARM_OP_REG


def install(emitter):
    cls=emitter.FunctionEmitter
    if getattr(cls,'_decomp_bounds_fixed',False):return
    original=cls._jump_case_count

    def count(self,insn,index_reg,default):
        if not insn.thumb:
            return original(self,insn,index_reg,default)
        previous=self._preceding(insn,20)
        register,base=index_reg,0
        saw_guard=False
        for position in range(len(previous)-1,-1,-1):
            prior=previous[position];name=self._branch_name(prior).rstrip('s');ops=prior.operands
            if name=='sub' and prior.condition==14 and base==0 and len(ops)==3 and \
                    ops[0].type==ARM_OP_REG and emitter.operand_reg(prior,ops[0])==register and \
                    ops[1].type==ARM_OP_REG and ops[2].type==ARM_OP_IMM:
                register,base=emitter.operand_reg(prior,ops[1]),emitter._immediate_value(prior,ops[2])
                continue
            if name!='cmp' or len(ops)!=2 or ops[0].type!=ARM_OP_REG or ops[1].type!=ARM_OP_IMM or \
                    emitter.operand_reg(prior,ops[0])!=register:
                continue
            # A guard consumes these flags before another flag-writing op.
            guard=None
            for following in previous[position+1:]:
                if self._branch_name(following)=='b' and following.condition!=14:
                    guard=following.condition;break
                if following.update_flags:break
            if guard==11 and int(ops[1].imm)==0:  # signed negative-index guard
                saw_guard=True
                continue
            if saw_guard and guard in (2,8,10,12):  # >= or > takes the out-of-range path
                bound=int(ops[1].imm)-base+(guard in (8,12))
                return min(256,max(0,bound))
        if saw_guard:
            return min(256,max(0,default)) if default is not None else None
        return original(self,insn,index_reg,default)

    cls._jump_case_count=count
    cls._decomp_bounds_fixed=True
