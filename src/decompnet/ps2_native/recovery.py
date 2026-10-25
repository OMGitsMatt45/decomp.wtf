"""Automatically map a closed reachable EE CFG; ambiguous programs need review."""
import struct
import rabbitizer
from .discovery import discover
from .media import elf_info
from ..pc import PCError


def closed_module(original):
    report=discover(original)
    if (report['unresolved'] or report['invalid'] or report['services'] or
        any(r['writable'] for r in report['pointer_reads'])):
        raise PCError('stripped PS2 code requires a reviewed input-bound profile: unresolved control flow, system callbacks or writable pointer data; use ps2-inspect --discover-code')
    info=elf_info(original)
    reachable={a for s in report['code_ranges'] for a in range(s['address'],s['address']+s['size'],4)}
    roots={f['address'] for f in report['function_seeds']}
    indirect={v['pc']:v['targets'] for v in report['resolved_indirect']}
    def decode(pc):
        segments=[s for s in info['loads'] if s['address']<=pc and pc+4<=s['address']+s['file_size']]
        if len(segments)!=1:raise PCError('stripped PS2 recovery has ambiguous executable loads')
        s=segments[0];at=s['offset']+pc-s['address']
        return rabbitizer.Instruction(struct.unpack_from('<I',original,at)[0],pc,category=rabbitizer.InstrCategory.R5900)
    functions=[];covered=set()
    for root in sorted(roots):
        pending=[root];owned=set()
        while pending:
            pc=pending.pop()
            if pc in owned or pc!=root and pc in roots:continue
            if pc not in reachable:raise PCError('stripped PS2 recovery leaves declared reachable code')
            owned.add(pc);inst=decode(pc);word=inst.getRaw()
            op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31;rd=(word>>11)&31
            call=inst.isFunctionCall() and not(op==0 and word&63==9 and rd==0)
            taken=True if inst.isUnconditionalBranch() else None
            if op in (4,5,20,21) and rs==rt:taken=op in (4,20)
            elif op in (6,7,22,23) and rs==0:taken=op in (6,22)
            elif op==1 and rs==0 and rt in (0,1,2,3,16,17,18,19):taken=bool(rt&1)
            if inst.hasDelaySlot() and not(inst.isBranchLikely() and taken is False):owned.add(pc+4)
            if call:pending.append(pc+8)
            elif inst.isBranch():
                if taken is not False:pending.append(inst.getBranchVramGeneric())
                if taken is not True:pending.append(pc+8)
            elif inst.isJumpWithAddress():pending.append(inst.getInstrIndexAsVram())
            elif inst.isJump():
                if not(inst.isReturn() or op==0 and word&63==9 and rd==0 and rs==31):pending.extend(indirect.get(pc,[]))
            else:pending.append(pc+4)
        if not owned or min(owned)!=root or len(owned)*4!=max(owned)+4-root:
            raise PCError('stripped PS2 functions contain shared/backward entries or embedded gaps; supply reviewed function and code/data ranges')
        covered|=owned
        functions.append(dict(name=f'function_{root:08x}',address=root,size=len(owned)*4))
    if covered!=reachable:raise PCError('stripped PS2 function ownership is incomplete; supply a reviewed profile')
    return dict(sha256=info['sha256'],functions=functions,native_services=[],
        code_ranges=[dict(address=s['address'],size=s['size']) for s in report['code_ranges']],
        recovery=dict(method='bounded-closed-reachable-cfg',resolved_indirect=report['resolved_indirect'],
                      unknown_code='reject',external_callbacks=False))
