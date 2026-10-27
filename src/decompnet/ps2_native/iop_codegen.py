"""Select pinned R3000A semantics at export time for original IRX instructions.

Each emitted function contains one fixed instruction's register operations.
Relocations can supply immediate bits, never select an opcode at runtime.
The source semantics remain under the pinned PS2Recomp runtime's GPL-3.0 terms.
"""
import re


def _cases(text, spaces):
    pattern=re.compile(r'^'+(' '*spaces)+r'(?:case (0x[0-9A-Fa-f]+):|default:)',re.M)
    matches=list(pattern.finditer(text));result={};pending=[]
    for index,match in enumerate(matches):
        if match[1] is None:continue
        pending.append(int(match[1],16))
        end=matches[index+1].start() if index+1<len(matches) else len(text)
        body=text[match.end():end]
        # Adjacent labels on one line implement the same instruction family.
        extra=re.match(r'\s*case (0x[0-9A-Fa-f]+):',body)
        while extra:
            pending.append(int(extra[1],16));body=body[extra.end():]
            extra=re.match(r'\s*case (0x[0-9A-Fa-f]+):',body)
        if not re.sub(r'//[^\n]*|\s','',body):continue
        body=re.sub(r'\bbreak;\s*(?://[^\n]*)?\s*$','',body)
        body=re.sub(r'\bbreak;\s*\}\s*$', '}',body)
        for value in pending:result[value]=body
        pending=[]
    return result


class Semantics:
    def __init__(self,source):
        outer='            switch (op >> 26)\n            {'
        inner='                switch (op & 63u)\n                {'
        footer='            // An ALU result written in a load delay slot wins over the load.'
        if source.count(outer)!=1 or source.count(inner)!=1 or source.count(footer)!=1:
            raise ValueError('pinned IOP instruction source layout differs')
        self.prefix=source.split('// Leaving a delay slot takes the branch;',1)[1].split(outer,1)[0]
        self.prefix='// Leaving a delay slot takes the branch;'+self.prefix
        table=source.split(outer,1)[1].split(footer,1)[0]
        self.primary=_cases(table,12)
        self.special=_cases(table.split(inner,1)[1].split('                }\n                break;',1)[0],16)
        self.footer=footer+source.split(footer,1)[1].split('        }\n        return StopReason::Budget;',1)[0]
        # Keep the original syscall/fault exits, load-delay retirement and
        # branch-pending interface. Fixed field indexes are export-time facts.
        if len(self.primary)!=31 or len(self.special)!=28:
            raise ValueError('pinned IOP instruction families differ')

    def emit(self,word,mask=0):
        if mask not in (0,0xffff,0x3ffffff):
            raise ValueError('IOP relocation may only change an immediate operand')
        op=word>>26
        if mask==0x3ffffff and op not in (2,3) or mask==0xffff and op in (0,2,3,0x10):
            raise ValueError('IOP relocation changes instruction selection or register fields')
        body=(self.special.get(word&63) if op==0 else self.primary.get(op))
        if body is None:body='m_faultPc=pc;return StopReason::Fault;'
        # Primary SPECIAL's nested decoder is never copied into the output.
        if op==0 and 'switch' in body:raise ValueError('IOP native body contains a decoder')
        prefix=self.prefix
        for field,shift in (('rs',21),('rt',16),('rd',11)):
            prefix=re.sub(r'const uint32_t '+field+r' = [^;]+;',
                          f'constexpr uint32_t {field} = {(word>>shift)&31}u;',prefix)
        prefix=prefix.replace('signExtend16(op)','static_cast<int16_t>(op & 0xffffu)')
        value=(f'0x{word:08x}u' if not mask else
               f'(0x{word&~mask:08x}u|(relocated&0x{mask:08x}u))')
        return f'''template <> StopReason Cpu::nativeStep<0x{word:08x}u,0x{mask:08x}u>(
    CpuContext &c,uint64_t &cycles,uint32_t relocated){{
    uint32_t *const r=c.gpr;const uint32_t pc=c.pc;
    const uint32_t op={value};(void)relocated;++cycles;
{prefix}
{body}
{self.footer}
    return StopReason::Budget;
}}
'''
