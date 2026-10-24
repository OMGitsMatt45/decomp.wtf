"""Control-flow corrections for the pinned MIT DQ9-Decomp emitter.

A signed lower-bound guard must not truncate a switch, and shared epilogues
must return to the caller whose saved frame they consume. This adapts the
upstream emitter through its decoded instruction interface; no game addresses,
bytes or title-specific entry lists are used.
"""
from capstone.arm_const import ARM_OP_IMM, ARM_OP_REG


def install(emitter):
    cls=emitter.FunctionEmitter
    if getattr(cls,'_decomp_bounds_fixed',False):return
    original=cls._jump_case_count
    branch=cls._branch

    def shared_exit(self,insn,target):
        """Prove a short Thumb target consumes this caller's saved frame.

        Some Thumb compilers use BL as a long branch to a shared epilogue.
        Its POP restores the outer PC, so C++ must not execute the next case.
        Keep ordinary BL subroutines (with their own frame) unchanged.
        """
        entry=self._slot_for(target,insn)
        if entry is None or not entry.thumb:return False
        prologue=self.decoder.decode(self.begin)
        if prologue is None or self._branch_name(prologue)!='push':return False
        saved={emitter.operand_reg(prologue,op) for op in prologue.operands if op.type==ARM_OP_REG}
        if 14 not in saved:return False
        expected=(saved-{14})|{15}
        # No additional stack frame or local allocation in this caller.
        for other in self.insns.values():
            if other.address==self.begin:continue
            name=self._branch_name(other).rstrip('s')
            _,writes=other.detail.regs_access()
            if any(other.detail.reg_name(r) in ('sp','r13') for r in writes) and name!='pop':return False
        # Only the bounded epilogue prefix is needed, not another full module
        # read for every call site in a retail manifest.
        with open(entry.module['image'],'rb') as stream:
            stream.seek(entry.address-int(entry.module['base']))
            prefix=stream.read(min(entry.size,64))
        decoder=emitter.Decoder(prefix,entry.address,self.arch,True)
        address=entry.address
        for _ in range(16):
            if address>=entry.end:return False
            op=decoder.decode(address)
            if op is None or op.next_address>entry.end or op.condition!=14:return False
            name=self._branch_name(op).rstrip('s')
            if name=='pop':
                restored={emitter.operand_reg(op,item) for item in op.operands if item.type==ARM_OP_REG}
                return restored==expected
            # Straight-line register work and loads are safe before the POP.
            if name not in ('mov','mvn','add','sub','and','orr','eor','bic','lsl','lsr','asr','ror',
                            'cmp','tst','ldr','ldrb','ldrh','ldrsb','ldrsh','nop'):return False
            _,writes=op.detail.regs_access()
            if any(op.detail.reg_name(r) in ('sp','lr','pc','r13','r14','r15') for r in writes):return False
            address=op.next_address
        return False

    def emit_branch(self,insn):
        result=branch(self,insn)
        if result is None or not insn.thumb or self._branch_name(insn)!='bl':return result
        target=self._branch_target(insn)
        if target is None or (self.dispatch_entries is not None and self._inside(target&~1)):return result
        if shared_exit(self,insn,target):
            return result+'\nreturn;'
        return result

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
    cls._branch=emit_branch
    from .wider_table import make
    cls._thumb_halfword_table_info=make(emitter)
    cls._decomp_bounds_fixed=True
