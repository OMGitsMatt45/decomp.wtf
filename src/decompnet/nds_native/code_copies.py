"""Translate bounded ARM code copies without changing original startup or memory.

Only literal-addressed word loops and two-word constant-stack copies are
recognized. A following branch must resolve into the completed copy. Original bytes
are decoded at their runtime destination; runtime dispatch still requires their
exact live hash, allowing successive programs to occupy the same scratch space.
"""
from pathlib import Path
import hashlib
import struct

import capstone
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC


def _imm(word):
    value=word&255;rotation=((word>>8)&15)*2
    return ((value>>rotation)|(value<<(32-rotation)))&0xffffffff if rotation else value


def _literal(image,base,at):
    word=struct.unpack_from('<I',image,at)[0]
    if word&0xff7f0000!=0xe51f0000:return None
    pos=at+8+((word&4095)if word&0x800000 else -(word&4095))
    if pos<0 or pos+4>len(image) or pos%4:return None
    return (word>>12)&15,struct.unpack_from('<I',image,pos)[0]


def _step(image,base,at,known):
    word=struct.unpack_from('<I',image,at)[0]
    literal=_literal(image,base,at)
    if literal is not None:known[literal[0]]=literal[1];return
    if word&0xfff00000==0xe3a00000:known[(word>>12)&15]=_imm(word);return
    if word&0xffe00000 in (0xe2800000,0xe2400000):
        dst,src=(word>>12)&15,(word>>16)&15
        if src in known:known[dst]=(known[src]+(_imm(word)if word&0xffe00000==0xe2800000 else -_imm(word)))&0xffffffff
        else:known.pop(dst,None)
        return
    # No unknown instruction may preserve speculative register constants.
    known.clear()


def _pic(raw,address):
    decoder=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM);decoder.detail=True
    pending=[address];visited=set();returns=False
    while pending:
        pc=pending.pop()
        if pc in visited:continue
        if pc%4 or not address<=pc<address+len(raw):return False
        insn=next(decoder.disasm(raw[pc-address:pc-address+4],pc,count=1),None)
        if insn is None or insn.mnemonic in ('bl','blx'):return False
        visited.add(pc)
        if insn.mnemonic.startswith('bx'):
            if insn.op_str in ('pc','sp'):return False
            returns=True
            if insn.mnemonic!='bx':pending.append(pc+4)
            continue
        if insn.mnemonic.startswith('b') and len(insn.operands)==1 and insn.operands[0].type==ARM_OP_IMM:
            pending.append(int(insn.operands[0].imm))
            if insn.mnemonic!='b':pending.append(pc+4)
            continue
        for operand in insn.operands:
            if operand.type==ARM_OP_MEM and operand.mem.base==ARM_REG_PC:
                target=pc+8+operand.mem.disp
                if not address<=target<=address+len(raw)-4:return False
        if insn.mnemonic.startswith(('ldr','str')) and insn.operands[0].type!=ARM_OP_MEM:
            if insn.reg_name(insn.operands[0].reg)=='pc':return False
        pending.append(pc+4)
        if len(visited)>1024:return False
    return returns


def _constant(image,base,start,at,register,depth=0):
    """Back-slice a bank-local constant; unknown writes and volatile calls stop it."""
    if depth>20:return None
    decoder=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM);decoder.detail=True
    for pos in range(at-4,start-1,-4):
        word=struct.unpack_from('<I',image,pos)[0]
        if word&0x0f000000==0x0b000000 and register in (0,1,2,3,12,14):return None
        if register==13 and word&0x0fb0fff0==0x0120f000:return None  # CPSR bank change
        insn=next(decoder.disasm(image[pos:pos+4],base+pos,count=1),None)
        if insn is None:return None
        _,writes=insn.regs_access()
        names={insn.reg_name(r)for r in writes}
        name='sp'if register==13 else 'lr'if register==14 else f'r{register}'
        if register==12:name='ip'
        if name not in names:continue
        if word>>28!=14:return None
        literal=_literal(image,base,pos)
        if literal is not None and literal[0]==register:return literal[1]
        if word&0xfff00000==0xe3a00000:return _imm(word)
        opcode=word&0xffe00000
        if opcode in (0xe2800000,0xe2400000,0xe0800000,0xe0400000):
            left=_constant(image,base,start,pos,(word>>16)&15,depth+1)
            right=_imm(word)if word&0x02000000 else _constant(image,base,start,pos,word&15,depth+1)if word&0xff0==0 else None
            if left is None or right is None:return None
            return (left+(right if opcode in(0xe2800000,0xe0800000)else -right))&0xffffffff
        return None
    return None


def recover(manifest,directory):
    """Append proven destination variants, preserving every existing module byte."""
    found=[];seen=set();directory=Path(directory);directory.mkdir(exist_ok=True)
    next_id=min([-1023]+[int(m['module_id'])for m in manifest['modules']])-1
    for module in list(manifest['modules']):
        image=Path(module['image']).read_bytes();base=int(module['base'])
        spans=[(int(f['addr'])-base,int(f['addr'])-base+int(f['size']))for f in module['functions']if not f['thumb']]
        for start,end in spans:
            for at in range(max(start,4),min(end,len(image))-15,4):
                words=struct.unpack_from('<4I',image,at);known={};kind=None
                # ldr value,[source],#4; str value,[dest],#4; cmp dest,end; blt loop
                if (words[0]&0xfff00fff==0xe4900004 and words[1]&0xfff00fff==0xe4800004
                        and words[0]>>12&15==words[1]>>12&15 and words[2]&0xfff0fff0==0xe1500000
                        and words[3]==0xbafffffb):
                    if at<start+12:continue
                    for pos in range(at-12,at,4):_step(image,base,pos,known)
                    src,dst=(words[0]>>16)&15,(words[1]>>16)&15;stop=words[2]&15
                    if (words[2]>>16)&15!=dst or len({src,dst,stop,(words[0]>>12)&15})!=4:continue
                    if not all(r in known for r in (src,dst,stop)):continue
                    source,destination=known[src],known[dst];size=known[stop]-destination
                    kind='forward-word-loop';known[src]+=size;known[dst]+=size
                # subs count,count,#4; ldr value,[source,count]; str value,[dest,count]; bgt loop
                elif (words[0]&0xfff00fff==0xe2500004 and words[1]&0xfff00ff0==0xe7900000
                        and words[2]&0xfff00ff0==0xe7800000 and words[3]==0xcafffffb):
                    if at<start+16:continue
                    count=(words[0]>>12)&15
                    if (words[0]>>16)&15!=count or words[1]&15!=count or words[2]&15!=count or words[1]>>12&15!=words[2]>>12&15:continue
                    for pos in range(at-16,at,4):_step(image,base,pos,known)
                    src,dst=(words[1]>>16)&15,(words[2]>>16)&15
                    if len({src,dst,count,(words[1]>>12)&15})!=4 or not all(r in known for r in(src,dst,count)):continue
                    source,destination,size=known[src],known[dst],known[count];known[count]=0;kind='backward-word-loop'
                # Two literal-sourced words copied below/at a statically based SP.
                elif (words[0]&0xfff00fff==0xe4900004 and words[1]&0xffff0fff==0xe50d0004
                        and words[2]&0xfff00fff==0xe5900000 and words[3]&0xffff0fff==0xe58d0000):
                    src=(words[0]>>16)&15;temp=(words[0]>>12)&15
                    if src in (13,15)or temp in (13,15)or (words[2]>>16)&15!=src or any((w>>12)&15!=temp for w in words[1:]):continue
                    literal=_literal(image,base,at-4)
                    sp=_constant(image,base,start,at,13)
                    if literal is None or literal[0]!=src or sp is None:continue
                    source=literal[1];destination=sp-4;size=8;kind='two-word-stack-copy';known={13:sp}
                if kind is None or size<=0 or size>4096 or size%4 or destination%4:continue
                if not (0x01000000<=destination<destination+size<=0x04000000):continue
                if not base<=source<source+size<=base+len(image):continue
                # An unknown instruction, branch or call ends the proof window.
                call=None
                for pos in range(at+16,min(at+112,end,len(image))-3,4):
                    word=struct.unpack_from('<I',image,pos)[0]
                    if word&0xffffffe0==0xe12fff20 or word&0xfffffff0==0xe12fff10:
                        target=known.get(word&15)
                        if target is not None and destination<=target<destination+size and target%4==0:call=(pos,target)
                        break
                    # Halfword communication stores do not alter address registers.
                    if word&0xfff00ff0==0xe1c000b0:continue
                    if word==0xe1a0e00f:continue  # manual LR/PC call link
                    _step(image,base,pos,known)
                if call is None:continue
                raw=image[source-base:source-base+size]
                if not _pic(raw,destination):continue
                key=(destination,raw,call[1])
                if key in seen:continue
                seen.add(key);path=directory/f'copy-{len(found)}.bin';path.write_bytes(raw)
                proof=dict(source_module=int(module['module_id']),source=source,destination=destination,size=size,
                           copy_loop=base+at,call=base+call[0],entry=call[1],kind=kind,
                           source_module_sha256=hashlib.sha256(image).hexdigest())
                variant=dict(name=f'code_copy_{len(found)}',module_id=next_id,base=destination,image=str(path.resolve()),
                             functions=[dict(addr=call[1],size=destination+size-call[1],thumb=False,name=f'copied_{call[1]:08x}')],
                             labels=[],calls=[],code_ranges=[[destination,destination+size]],data_ranges=[],runtime_code_copy=proof)
                manifest['modules'].append(variant);next_id-=1;found.append(proof)
    return found


def patch_runtime(root):
    """Reserved copy-module IDs require live hashes even with one candidate."""
    path=Path(root)/'runtime/core/src/runtime.cpp';text=path.read_text(encoding='utf-8')
    changes={
        'if (target.candidates.size() == 1) continue;':
        'if (target.candidates.size() == 1 && target.candidates.front()->module > -1024) continue;',
        'if (bucket.candidates.size() == 1) return bucket.candidates.front();':
        'if (bucket.candidates.size() == 1 && bucket.candidates.front()->module > -1024) return bucket.candidates.front();',
    }
    for before,after in changes.items():
        if text.count(before)!=1:raise ValueError('pinned copied-code dispatch site differs')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
