"""Decode guarded ARM halfword-offset switches without executing their data."""
import struct
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG


def make(emitter):
    def table(self,insn):
        if insn.thumb or insn.condition!=14 or self._branch_name(insn)!='add' or insn.update_flags:
            return None
        operands=insn.operands
        if (len(operands)!=3 or any(p.type!=ARM_OP_REG for p in operands)
                or [emitter.operand_reg(insn,p) for p in operands[:2]]!=[15,15]
                or operands[2].shift.type):return None
        offset_reg=emitter.operand_reg(insn,operands[2])
        previous=self._preceding(insn,16)
        if len(previous)<4:return None
        guard,setup,load=previous[-3:]
        if any(op.address!=insn.address-12+4*i for i,op in enumerate((guard,setup,load))):return None
        if len(setup.operands)!=3 or setup.operands[2].type!=ARM_OP_REG:return None
        key=emitter.operand_reg(setup,setup.operands[2])
        compare=None
        for prior in reversed(previous[:-3]):
            if self._branch_name(prior)=='cmp':
                compare=prior;break
            if (prior.condition!=14 or prior.update_flags or self._branch_name(prior)in('b','bl','blx','bx','msr','pop')
                    or key in {emitter.reg_index(prior,r)for r in prior.detail.regs_access()[1]
                               if prior.detail.reg_name(r)not in('cpsr','apsr')}):return None
        if compare is None:return None
        if (self._branch_name(compare)!='cmp' or compare.condition!=14 or compare.update_flags is False
                or len(compare.operands)!=2 or compare.operands[0].type!=ARM_OP_REG
                or compare.operands[1].type!=ARM_OP_IMM
                or self._branch_name(guard)!='b' or guard.condition not in (2,8)
                or setup.condition!=14 or load.condition!=14 or setup.update_flags or load.writeback):return None
        if (self._branch_name(setup)!='add' or len(setup.operands)!=3
                or any(p.type!=ARM_OP_REG for p in setup.operands)
                or emitter.operand_reg(setup,setup.operands[1])!=15
                or emitter.operand_reg(setup,setup.operands[2])!=emitter.operand_reg(compare,compare.operands[0])):return None
        shift,by_register,_=emitter.shift_kind(setup.operands[2].shift.type)
        if shift!=0 or by_register or setup.operands[2].shift.value!=1:return None
        name=self._branch_name(load)
        if (name not in ('ldrh','ldrsh') or len(load.operands)!=2 or load.operands[0].type!=ARM_OP_REG
                or emitter.operand_reg(load,load.operands[0])!=offset_reg or load.operands[1].type!=ARM_OP_MEM):return None
        memory=load.operands[1].mem
        if (memory.index or emitter.reg_index(load,memory.base)!=emitter.operand_reg(setup,setup.operands[0])):return None
        start=setup.address+8+memory.disp
        count=int(compare.operands[1].imm)+(guard.condition==8)
        end=start+2*count
        if (not 0<count<=4096 or start!=insn.next_address or end>self.end
                or not self.base<=start<end<=self.base+len(self.image)):return None
        target=self._branch_target(guard)
        if target is None or start<=target<end:return None
        if any(start<=address<end for address in self.insns):return None
        # An explicit alternate entry inside this sequence has no established
        # guard. Preserve ordinary decoding/diagnostics in that situation.
        if any(e.module_id==self.entry.module_id and setup.address<=e.address<=insn.address
               for e in self.module_mode_entries.values()):return None
        cases={}
        branch_base=insn.address+8
        for index in range(count):
            offset=struct.unpack_from('<h' if name=='ldrsh' else '<H',self.image,start-self.base+index*2)[0]
            address=(branch_base+offset)&0xffffffff&~3
            if not self._inside(address) or start<=address<end or self._decode_at(address) is None:return None
            cases[offset&0xffffffff]=address
        # Shared regions also sweep instructions linearly. Retain the table's
        # data ownership so that sweep cannot reinterpret halfword offsets.
        ranges=sorted([*self.data_ranges,(start,end)])
        merged=[]
        for low,high in ranges:
            if merged and low<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],high))
            else:merged.append((low,high))
        self.data_ranges=merged
        return dict(kind='add',index=offset_reg,base=branch_base,shift=0,cases=sorted(cases.items()))
    return table
