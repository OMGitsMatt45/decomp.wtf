"""Recognize a guarded ARM ready-list scan in the pinned ABI analyzer."""
from copy import copy


class _Instruction:
    def __init__(self,instruction,mnemonic):
        self.instruction=instruction
        self.mnemonic=mnemonic

    def __getattr__(self,name):
        return getattr(self.instruction,name)


def install(analyzer):
    if getattr(analyzer,'_decomp_conditional_scan',False):return
    original=analyzer.irq_layout

    def irq_layout(function):
        result=original(function)
        if result is not None:return result
        instructions=function.instructions
        candidates=[]
        for index in range(len(instructions)-4):
            guard,ready,compare,link,branch=instructions[index:index+5]
            if [i.mnemonic for i in (guard,ready,compare,link,branch)]!=[
                    'cmp','ldrhne','cmpne','ldrne','bne']:continue
            if any(i.address!=guard.address+4*n for n,i in enumerate((guard,ready,compare,link,branch))):continue
            if (guard.op_str!='r1, #0' or analyzer.reg(ready,ready.operands[0])!='r0'
                    or analyzer.reg(compare,compare.operands[0])!='r0'
                    or analyzer.reg(link,link.operands[0])!='r1'):continue
            try:
                if analyzer.immediate(branch,0)!=guard.address:continue
            except analyzer.DerivationError:continue
            candidates.append(index)
        if len(candidates)!=1:return None
        # Only these three instructions are conditional on the null-node and
        # ready-state comparisons. Preserve every original layout/uniqueness
        # check, including matching the wake value and all cleared queue fields.
        normalized=copy(function);normalized.instructions=list(instructions)
        index=candidates[0]
        for offset,name in ((1,'ldrh'),(2,'cmp'),(3,'ldr')):
            normalized.instructions[index+offset]=_Instruction(instructions[index+offset],name)
        return original(normalized)

    analyzer.irq_layout=irq_layout
    analyzer._decomp_conditional_scan=True
