"""Bounded constant-set propagation for EE indirect calls and jump tables.

Unknown values stay unknown; joins never select one predecessor arbitrarily.
Delay slots execute after the jump target is latched. Native call continuations
discard caller-saved registers. File-backed writable pointer reads are reported
as assumptions, so they cannot authorize an automatic closed-code map.
"""
from collections import deque
from dataclasses import dataclass
import struct
import rabbitizer

from ..pc import PCError

MASK=(1<<64)-1
LIMIT=32


@dataclass(frozen=True)
class LessThan:
    register:int
    bound:int


def signed(value,bits):
    value&=(1<<bits)-1
    return (value-(1<<bits) if value>>(bits-1) else value)&MASK


def resolve(original,info,offset,roots,*,max_instructions):
    zero=frozenset((0,));initial=(zero,)+(None,)*31
    # MIPS reginfo's GP is relocation metadata, rather than an inferred title address.
    table=struct.unpack_from('<I',original,32)[0]
    for n in range(struct.unpack_from('<H',original,48)[0]):
        sh=struct.unpack_from('<10I',original,table+40*n)
        if sh[1]==0x70000006 and sh[5]>=24 and sh[4]+24<=len(original):
            gp=struct.unpack_from('<I',original,sh[4]+20)[0]
            if gp:initial=initial[:28]+(frozenset((signed(gp,32),)),)+initial[29:]
    states={};pending=deque();decoded={};reads={};updates=0

    def instruction(pc):
        if pc not in decoded:
            at=offset(pc)
            decoded[pc]=None if at is None else rabbitizer.Instruction(struct.unpack_from('<I',original,at)[0],pc,category=rabbitizer.InstrCategory.R5900)
        return decoded[pc]

    def join(a,b):
        if a==b:return a
        if a is None or b is None or isinstance(a,LessThan) or isinstance(b,LessThan):return None
        result=a|b
        return result if len(result)<=LIMIT else None

    def push(pc,state):
        nonlocal updates
        if offset(pc) is None:return
        if pc in states:state=tuple(join(a,b) for a,b in zip(states[pc],state))
        if states.get(pc)==state:return
        states[pc]=state;pending.append(pc);updates+=1
        if updates>max_instructions*8:raise PCError('PS2 indirect data-flow exceeds its work bound')

    def constants(value):return value if isinstance(value,frozenset) else None
    def binary(a,b,fn):
        a,b=constants(a),constants(b)
        if a is None or b is None:return None
        values=frozenset(fn(x,y)&MASK for x in a for y in b)
        return values if len(values)<=LIMIT else None

    def read(address,size):
        physical=address&0x1fffffff
        matches=[s for s in info['loads'] if s['physical']<=physical and physical+size<=s['physical']+s['file_size']]
        if len(matches)!=1:return None
        segment=matches[0];at=segment['offset']+physical-segment['physical']
        reads[(physical,size)]=bool(segment['flags']&2)
        return int.from_bytes(original[at:at+size],'little')

    def transfer(pc,state):
        inst=instruction(pc)
        if inst is None or not inst.isValid():return state
        word=inst.getRaw();op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31;rd=(word>>11)&31;sa=(word>>6)&31;fn=word&63
        imm=word&65535;sim=imm if imm<32768 else imm-65536
        out=list(state);writes={}
        if inst.modifiesRs():writes[rs]=None
        if inst.modifiesRt():writes[rt]=None
        if inst.modifiesRd():writes[rd]=None
        if op==15:writes[rt]=frozenset((signed(imm<<16,32),))
        elif op in (8,9,24,25):writes[rt]=binary(state[rs],frozenset((sim,)),lambda a,b:signed(a+b,32) if op in (8,9) else a+b)
        elif op in (12,13,14):
            if op==12 and constants(state[rs]) is None and imm.bit_count()<=5:
                values={0}
                for bit in range(16):
                    if imm&(1<<bit):values|={v|(1<<bit) for v in values}
                writes[rt]=frozenset(values)
            else:writes[rt]=binary(state[rs],frozenset((imm,)),lambda a,b:(a&b) if op==12 else ((a|b) if op==13 else a^b))
        elif op==11 and rt!=rs and 0<sim<=LIMIT and constants(state[rs]) is None:
            writes[rt]=LessThan(rs,sim)
        elif op==0:
            if fn in (0,2,3,56,58,59,60,62,63):
                shift=sa+(32 if fn in (60,62,63) else 0)
                def shifted(a,b):
                    if fn in (0,56,60):value=a<<b
                    elif fn in (3,59,63):value=((a&0xffffffff)-(1<<32) if fn==3 and a&0x80000000 else (a-(1<<64) if a>>63 else a))>>b
                    else:value=(a&0xffffffff if fn==2 else a)>>b
                    return signed(value,32) if fn in (0,2,3) else value
                writes[rd]=binary(state[rt],frozenset((shift,)),shifted)
            elif fn in (32,33,34,35,36,37,38,39,44,45,46,47):
                def operation(a,b):
                    if fn in (32,33,44,45):value=a+b
                    elif fn in (34,35,46,47):value=a-b
                    elif fn==36:value=a&b
                    elif fn==37:value=a|b
                    elif fn==38:value=a^b
                    else:value=~(a|b)
                    return signed(value,32) if fn in (32,33,34,35) else value
                writes[rd]=binary(state[rs],state[rt],operation)
        elif op in (32,33,35,36,37,39,55):
            addresses=constants(state[rs]);size={32:1,33:2,35:4,36:1,37:2,39:4,55:8}[op]
            values=[]
            if addresses is not None:
                for base in addresses:
                    address=(base+sim)&MASK;value=read(address,size)
                    if address%size or value is None:values=[];break
                    values.append(signed(value,size*8) if op in (32,33,35) else value)
            writes[rt]=frozenset(values) if values else None
        for reg in writes:
            if reg:
                for n,value in enumerate(out):
                    if isinstance(value,LessThan) and value.register==reg:out[n]=None
        for reg,value in writes.items():
            if reg:out[reg]=value
        out[0]=zero
        return tuple(out)

    def branch_state(state,inst,taken):
        word=inst.getRaw();rs=(word>>21)&31;rt=(word>>16)&31;op=word>>26
        if op in (4,5,20,21):
            pred=state[rs] if rt==0 else (state[rt] if rs==0 else None)
            if isinstance(pred,LessThan) and taken==(op in (5,21)):
                out=list(state);out[pred.register]=frozenset(range(pred.bound));return tuple(out)
        return state

    def decision(inst,state):
        if inst.isUnconditionalBranch():return True
        word=inst.getRaw();op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31
        def values(v):return frozenset((0,1)) if isinstance(v,LessThan) else constants(v)
        left,right=values(state[rs]),values(state[rt])
        if left is None:return None
        if op in (4,5,20,21) and right is not None:
            result={(a==b)==(op in (4,20)) for a in left for b in right}
        elif op in (6,7,22,23):
            result={((a-(1<<64) if a>>63 else a)<=0)==(op in (6,22)) for a in left}
        elif op==1 and rt in (0,1,2,3,16,17,18,19):
            result={((a-(1<<64) if a>>63 else a)>=0)==bool(rt&1) for a in left}
        else:return None
        return next(iter(result)) if len(result)==1 else None

    for root in roots:push(root,initial)
    while pending:
        pc=pending.popleft();state=states[pc];inst=instruction(pc)
        if inst is None or not inst.isValid():continue
        if len(states)>max_instructions:raise PCError('PS2 indirect data-flow exceeds its instruction bound')
        word=inst.getRaw();op=word>>26;rs=(word>>21)&31;rd=(word>>11)&31
        call=inst.isFunctionCall() and not(op==0 and word&63==9 and rd==0)
        taken=decision(inst,state) if inst.isBranch() else True
        ret=inst.isReturn() or (op==0 and word&63==9 and rd==0 and rs==31)
        target=None
        if inst.isJumpWithAddress():target=(inst.getInstrIndexAsVram(),)
        elif inst.isBranch():target=(inst.getBranchVramGeneric(),)
        elif inst.isJump() and not ret:
            values=constants(state[rs]);target=tuple(v&0xffffffff for v in values) if values is not None else None
        base=transfer(pc,state)
        if call:
            base=list(base);base[rd if op==0 else 31]=frozenset(((pc+8)&MASK,));base=tuple(base)
        if inst.hasDelaySlot():
            annul=inst.isBranchLikely() and taken is False
            if not annul:
                delay=instruction(pc+4)
                if delay is None or not delay.isValid() or delay.hasDelaySlot():continue
            if target and taken is not False:
                for address in target:push(address,transfer(pc+4,branch_state(base,inst,True)))
            if call and taken is not False:
                continuation=list(transfer(pc+4,base));clobbered={*range(1,16),24,25,28}
                for reg,value in enumerate(continuation):
                    if reg in clobbered or isinstance(value,LessThan) and value.register in clobbered:continuation[reg]=None
                push(pc+8,tuple(continuation))
            elif inst.isBranch() and taken is not True:
                fall=branch_state(base,inst,False)
                push(pc+8,fall if inst.isBranchLikely() else transfer(pc+4,fall))
        elif inst.getOpcodeName() not in ('eret','break'):
            # A syscall can change any caller-saved value and invoke callbacks.
            if inst.getOpcodeName()=='syscall':
                base=list(base)
                for reg in (*range(1,16),24,25):base[reg]=None
                base=tuple(base)
            push(pc+4,base)
    result={}
    for pc,state in states.items():
        inst=instruction(pc)
        if inst is None:continue
        word=inst.getRaw();rs=(word>>21)&31;rd=(word>>11)&31
        if inst.isJump() and not inst.isJumpWithAddress() and not inst.isReturn() and not(word>>26==0 and word&63==9 and rd==0 and rs==31):
            values=constants(state[rs])
            if values is not None:result[pc]=sorted(v&0xffffffff for v in values)
    return result,[dict(address=a,size=n,writable=w) for (a,n),w in sorted(reads.items())]
