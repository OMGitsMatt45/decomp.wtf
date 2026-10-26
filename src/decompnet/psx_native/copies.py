"""Ahead-of-time copies of bounded input routines, independent of RAM placement.

The pinned emitter translates each body at two nominal uncached addresses.
Only tokens that move consistently with those addresses become a base argument.
Instruction literals remain literals, even when their value resembles a PC.
Runtime selection compares complete bytes; it contains no instruction decoder.
"""
import hashlib
from pathlib import Path
import re
import struct
import tempfile

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

from .. import pc
from . import codegen

BASES = (0xa01e0000, 0xa01d0000)
MAX_BODY = 1024
MAX_COPIES = 16384
_C_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
                      r'0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[a-zA-Z_]\w*|\S')
_CONT = re.compile(r'switch\s*\(_cont\)\s*\{\s*'
                   r'((?:case\s+0x[0-9a-fA-F]+u:\s*goto\s+\w+;\s*)+)'
                   r'default:\s*break;\s*\}')


def _word(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _supported(word):
    op = word >> 26
    if op == 0:
        return word & 63 in (0, 2, 3, 4, 6, 7, 8, 16, 17, 18, 19, 24, 25, 26, 27,
                             32, 33, 34, 35, 36, 37, 38, 39, 42, 43)
    if op == 1:
        return word >> 16 & 31 in (0, 1)
    return op in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                  32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 46)


def _control(word):
    return word >> 26 in (1, 4, 5, 6, 7) or word >> 26 == 0 and word & 63 == 8


def _body(data, start, decoder):
    """A contiguous closed CFG, with ordinary delay slots and an indirect exit."""
    pending = [start]
    visited, delays, targets = set(), set(), {start}
    exit_seen = False
    while pending:
        at = pending.pop()
        if at in visited:
            continue
        if at & 3 or not start <= at <= min(start+MAX_BODY, len(data))-4:
            return None
        word = _word(data, at)
        if not _supported(word) or not next(decoder.disasm(data[at:at+4], at, count=1), None):
            return None
        visited.add(at)
        if not _control(word):
            pending.append(at+4)
            continue
        delay = at+4
        if delay+4 > min(start+MAX_BODY, len(data)):
            return None
        following = _word(data, delay)
        if not _supported(following) or _control(following) or not next(
                decoder.disasm(data[delay:delay+4], delay, count=1), None):
            return None
        visited.add(delay);delays.add(delay)
        if word >> 26 == 0:
            exit_seen = True
            continue
        relative = struct.unpack('<h', struct.pack('<H', word & 0xffff))[0]
        target = at+4+relative*4
        targets.update((target, at+8));pending.extend((target, at+8))
    if not exit_seen or delays & targets:
        return None
    end = max(visited)+4
    if end-start < 16 or visited != set(range(start, end, 4)):
        return None
    return data[start:end]


def discover(discs):
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    found, images = {}, set()
    for disc in discs:
        for item in [disc, *disc.get('modules', [])]:
            data = item['image'][2048:]
            image_id = hashlib.sha256(data).digest()
            if image_id in images:
                continue
            images.add(image_id)
            low = item['info']['load']
            roots = {address-low for address in codegen.seeds(item['image'], item['info'])}
            for offset in range(0, len(data)-11, 4):
                word = _word(data, offset)
                if word >> 26 == 0 and word & 63 == 8:
                    at = offset+8
                    for _ in range(6):
                        if at+4 > len(data) or _word(data, at):
                            break
                        at += 4
                    roots.add(at)
            for offset in sorted(roots):
                body = _body(data, offset, decoder)
                if body is None:
                    continue
                key = hashlib.sha256(body).hexdigest()
                if key in found:
                    continue
                if len(found) >= MAX_COPIES:
                    raise pc.PCError('position-independent PS1 routines exceed the source catalog bound')
                found[key] = dict(data=body, sha256=key,
                    source=dict(disc=disc['index'],program=item['boot'],offset=offset))
    return list(found.values())


def _continuations(text):
    return _CONT.sub(lambda match: ''.join(
        f'if (_cont == {value}) goto {label};\n' for value, label in re.findall(
            r'case\s+(0x[0-9a-fA-F]+u):\s*goto\s+(\w+);', match[1])), text)


def _tokens(text):
    return [match for match in _C_TOKEN.finditer(text) if not match[0].startswith(('//', '/*'))]


def parameterize(first, second, size):
    """Pair emitted C tokens, rejecting differences that are not PC relocation."""
    first, second = _continuations(first), _continuations(second)
    left, right = _tokens(first), _tokens(second)
    if len(left) != len(right):
        raise ValueError('copied PS1 translation has placement-dependent structure')
    changes = []
    for a, b in zip(left, right):
        old, other = a[0], b[0]
        if old == other:
            continue
        if old.startswith(('0x', '0X')) and other.startswith(('0x', '0X')):
            va, vb = int(old.rstrip('uUlL'), 16), int(other.rstrip('uUlL'), 16)
            offset = va-BASES[0]
            if not 0 <= offset <= size or vb-BASES[1] != offset:
                raise ValueError('copied PS1 literal is not a proven PC relocation')
            # Converted continuation switches use comparisons; a remaining
            # case label would require a compile-time constant.
            if a.start() and first[:a.start()].rstrip().endswith('case'):
                raise ValueError('copied PS1 translation has an unsupported PC switch')
            changes.append((a.start(), a.end(), f'(decomp_base+{offset}u)'))
            continue
        def normalized(name, base):
            return re.sub(r'[0-9a-fA-F]{8}', lambda match:
                f'PC_{int(match[0],16)-base:x}' if base <= int(match[0],16) <= base+size else match[0], name)
        if re.fullmatch(r'[a-zA-Z_]\w*', old) and normalized(old,BASES[0]) == normalized(other,BASES[1]):
            continue  # Local labels/variables keep their first nominal names.
        raise ValueError('copied PS1 translation has an unrecognized placement dependency')
    for start, end, value in reversed(changes):
        first = first[:start]+value+first[end:]
    return first


def emit_body(recompiler, sdk, item, folder, ordinal, run):
    """Retain ordinary editable C; the temporary paired translation is discarded."""
    folder.mkdir(parents=True)
    data = item['data'];prefix = f'decomp_copy{ordinal}_'
    with tempfile.TemporaryDirectory(prefix='.copy-proof-', dir=folder) as temporary:
        stages = []
        for index, base in enumerate(BASES):
            stage = Path(temporary)/str(index);stage.mkdir()
            header = bytearray(2048);header[:8] = b'PS-X EXE'
            struct.pack_into('<4I',header,0x10,base,0,base,len(data))
            image = stage/'COPY.EXE';image.write_bytes(header+data)
            seed = stage/'seeds.txt';seed.write_text(hex(base)+'\n',encoding='utf-8')
            run([recompiler,image,'--seeds',seed,'--out-dir',stage,'--strict','--project-root',sdk],
                'PS1 copied-routine C generation')
            stages.append(stage)
        first, second = stages
        sources = sorted(first.glob('*_full_*.c'))+[first/'COPY.EXE_decls.h']
        for path in sources:
            paired = second/path.name
            text = parameterize(path.read_text(), paired.read_text(), len(data))
            text = re.sub(r'\b((?:func_|psx_alias_body_)[0-9a-fA-F]{8})\b', prefix+r'\1', text)
            text = re.sub(r'\b('+prefix+r'(?:func_|psx_alias_body_)[0-9a-fA-F]{8})\(CPUState\* cpu\)',
                          r'\1(CPUState* cpu,uint32_t decomp_base)', text)
            text = re.sub(r'\b('+prefix+r'(?:func_|psx_alias_body_)[0-9a-fA-F]{8})\(cpu\)',
                          r'\1(cpu,decomp_base)', text)
            (folder/path.name).write_text(text,encoding='utf-8')
        table = (first/'COPY.EXE_dispatch.c').read_text().split(
            'static const PsxGameDispatchEntry k_psx_game_dispatch[] = {',1)[1].split('};',1)[0]
        rows = re.findall(r'\{0x([0-9a-fA-F]+)u,\s*0x([0-9a-fA-F]+)u,\s*\d+u,\s*\d+u,\s*(\w+)\}',table)
        if len(rows) != len(codegen.dispatch_entries((first/'COPY.EXE_dispatch.c').read_text())):
            raise ValueError('pinned copied PS1 entry layout differs')
        entries = []
        for address, resume, function in rows:
            offset, continuation = int(address,16)-BASES[0], int(resume,16)
            if not 0 <= offset <= len(data)-4 or continuation and not BASES[0] <= continuation < BASES[0]+len(data):
                raise ValueError('copied PS1 entry escapes its original bytes')
            entries.append(dict(offset=offset,resume=continuation-BASES[0] if continuation else None,
                                function=prefix+function))
    return dict(sha256=item['sha256'],size=len(data),source=item['source'],entries=entries)


def registry(items, path):
    lines=['#include "cpu_state.h"','#include <stdint.h>','#include <stdlib.h>','#include <string.h>',
           'extern unsigned char *g_psx_ram;',
           'extern uint64_t decomp_native_dispatches;',
           'uint64_t decomp_copy_dispatches=0;',
           'extern void psx_check_interrupts_dispatch_entry(CPUState*,uint32_t);']
    rows=[]
    for index,(item,meta) in enumerate(items):
        name=f'copy_bytes_{index}'
        lines.append(f'static const unsigned char {name}[]={{'+','.join(map(str,item['data']))+'};')
        for entry in meta['entries']:
            function=entry['function']
            lines.append(f'extern void {function}(CPUState*,uint32_t);')
            offset,resume=entry['offset'],entry['resume']
            word=_word(item['data'],offset)
            rows.append((word,index,offset,
                f'{{0x{word:08x}u,{len(item["data"])}u,{offset}u,{resume or 0}u,'
                f'{int(resume is not None)}u,{name},{function}}}'))
    if not rows:
        lines.extend(['int decomp_psx_copy_valid(uint32_t address){(void)address;return 0;}',
                      'int decomp_psx_dispatch_copy(CPUState *cpu,uint32_t address){(void)cpu;(void)address;return 0;}'])
    else:
        lines.extend(['typedef struct {uint32_t word,size,offset,resume,has_resume;'
                      'const unsigned char *bytes;void (*fn)(CPUState*,uint32_t);} DecompCopy;',
                      'static const DecompCopy copies[]={',
                      ',\n'.join(row[3] for row in sorted(rows)),'};',r'''
static const DecompCopy *copy_at(uint32_t address,uint32_t *base){
    uint32_t segment=address&0xe0000000u,physical=address&0x1fffffffu;
    if(!g_psx_ram||(address&3u)||physical>0x1ffffcu||
       (segment!=0u&&segment!=0x80000000u&&segment!=0xa0000000u))return NULL;
    const char *force=getenv("PSX_FORCE_INTERP");
    if(force&&*force&&*force!='0')return NULL;
    uint32_t word;memcpy(&word,g_psx_ram+physical,4);
    uint32_t low=0,high=(uint32_t)(sizeof(copies)/sizeof(copies[0]));
    while(low<high){uint32_t mid=low+(high-low)/2;
        if(copies[mid].word<word)low=mid+1;else high=mid;}
    for(uint32_t i=low;i<sizeof(copies)/sizeof(copies[0])&&copies[i].word==word;i++){
        const DecompCopy *copy=copies+i;
        if(physical<copy->offset)continue;
        uint32_t start=physical-copy->offset;
        if(copy->size>0x200000u-start)continue;
        if(!memcmp(g_psx_ram+start,copy->bytes,copy->size)){
            *base=address-copy->offset;return copy;
        }
    }
    return NULL;
}
int decomp_psx_copy_valid(uint32_t address){uint32_t base;return copy_at(address,&base)!=NULL;}
int decomp_psx_dispatch_copy(CPUState *cpu,uint32_t address){
    uint32_t base;const DecompCopy *copy=copy_at(address,&base);if(!copy)return 0;
    psx_check_interrupts_dispatch_entry(cpu,address);
    cpu->pc=copy->has_resume?base+copy->resume:0u;
    decomp_native_dispatches++;decomp_copy_dispatches++;
    copy->fn(cpu,base);return 1;
}'''])
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
