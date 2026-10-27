"""Input-bound IRX translation and build-selected IOP execution integration."""
import hashlib
import json
from pathlib import Path
import struct

from ..pc import PCError
from .iop_codegen import Semantics
from .runtime_patch import replace

MAX_MODULE=4*1024*1024


def parse(data):
    def bad():raise PCError('invalid or unsupported native IOP IRX layout')
    if len(data)<52 or len(data)>MAX_MODULE or data[:7]!=b'\x7fELF\1\1\1':bad()
    kind,machine=struct.unpack_from('<HH',data,16)
    if (kind,machine)!=(0xff80,8):bad()
    phoff,shoff=struct.unpack_from('<II',data,28)
    phsize,phnum,shsize,shnum=struct.unpack_from('<4H',data,42)
    if not phnum or phsize<32 or phnum>1024 or phoff+phsize*phnum>len(data):bad()
    if shnum and (shsize<40 or shnum>8192 or shoff+shsize*shnum>len(data)):bad()
    load=module=None
    for index in range(phnum):
        row=struct.unpack_from('<8I',data,phoff+phsize*index)
        segment,offset,_,_,size,memory,_,_=row
        if segment not in (1,0x70000080):continue
        if offset>len(data) or size>len(data)-offset:bad()
        if segment==1:
            if load is not None or memory<size or memory>2*1024*1024:bad()
            load=(data[offset:offset+size],memory)
        else:
            if module is not None or size<26:bad()
            module=struct.unpack_from('<6I',data,offset)
    if load is None or module is None:bad()
    image,memory=load;_,entry,gp,text,initialized,_=module
    if entry&3 or text&3 or entry>=len(image) or text+initialized>len(image):bad()
    relocations=[]
    for index in range(shnum):
        row=struct.unpack_from('<10I',data,shoff+shsize*index)
        if row[1]!=9:continue
        offset,size=row[4:6]
        if size%8 or offset>len(data) or size>len(data)-offset:bad()
        for at in range(offset,offset+size,8):
            address,info=struct.unpack_from('<II',data,at);kind=info&255
            if address&3 or address+4>len(image) or kind not in (2,4,5,6,7):bad()
            relocations.append((address,kind))
    return dict(image=image,entry=entry,gp=gp,text=text,bss=memory-len(image),relocations=relocations)


def mask_at(module):
    masks={}
    for offset,kind in module['relocations']:
        if offset>=module['text']:continue
        mask={2:None,4:0x3ffffff,5:0xffff,6:0xffff,7:0}[kind]
        if offset in masks and masks[offset]!=mask:
            raise PCError('overlapping IOP instruction relocation kinds need separate support')
        masks[offset]=mask
    return masks


def generate(inputs,source,folder):
    """inputs are original (disc path, IRX bytes), never relocated RAM snapshots."""
    folder=Path(folder);folder.mkdir(parents=True)
    semantics=Semantics(Path(source).read_text());modules=[];operations={};seen=set()
    for name,data in inputs:
        digest=hashlib.sha256(data).hexdigest()
        if digest in seen:continue
        seen.add(digest);module=parse(data);masks=mask_at(module);entries=[]
        if sum(len(m[2]['image']) for m in modules)+len(module['image'])>64*1024*1024:
            raise PCError('native IOP module catalog exceeds its export bound')
        for offset in range(0,module['text'],4):
            word=struct.unpack_from('<I',module['image'],offset)[0];mask=masks.get(offset,0)
            if mask is None:entries.append((word,0,None));continue
            key=(word,mask)
            if key not in operations:
                if len(operations)>=262144:raise PCError('native IOP instruction catalog exceeds its export bound')
                try:body=semantics.emit(word,mask)
                except ValueError as error:raise PCError(f'IOP relocation at {name}+{offset:#x}: {error}') from error
                operations[key]=(len(operations),body)
            entries.append((word,mask,operations[key][0]))
        modules.append((name,digest,module,entries))
    declarations=[]
    for (word,mask),(ordinal,_) in operations.items():
        declarations.append(f'StopReason decomp_iop_op{ordinal}(Cpu&,CpuContext&,uint64_t&,uint32_t);')
    ordered=list(operations.items())
    for start in range(0,len(ordered),128):
        text=['// Generated from original inputs and GPL-3.0 PS2Recomp instruction semantics.',
              '#include "decomp_iop_catalog.hpp"','namespace ps2x::iop::lle {']
        for (word,mask),(ordinal,body) in ordered[start:start+128]:
            text.extend([body,f'StopReason decomp_iop_op{ordinal}(Cpu& cpu,CpuContext& c,uint64_t& cycles,uint32_t value){{'
                         f'return cpu.nativeStep<0x{word:08x}u,0x{mask:08x}u>(c,cycles,value);}}'])
        text.append('}');(folder/f'operations{start//128}.cpp').write_text('\n'.join(text))
    text=['#include "decomp_iop_catalog.hpp"','namespace ps2x::iop::lle {',*declarations]
    rows=[];records=[]
    for ordinal,(name,digest,module,entries) in enumerate(modules):
        data=module['image'];image=f'module{ordinal}_image';rel=f'module{ordinal}_rel';code=f'module{ordinal}_code'
        text.append(f'static const unsigned char {image}[]={{'+','.join(map(str,data))+'};')
        text.append(f'static const IrxImage::Relocation {rel}[]={{'+
                    (','.join('{'+f'{offset}u,{kind}u'+'}' for offset,kind in module['relocations']) or '{0,0}')+'};')
        text.append(f'static const DecompNativeInstruction {code}[]={{'+
                    (',\n'.join('{'+f'0x{word:08x}u,0x{mask:08x}u,'+
                     (f'decomp_iop_op{op}' if op is not None else 'nullptr')+'}' for word,mask,op in entries) or '{0,0,nullptr}')+'};')
        rows.append('{'+f'{image},{len(data)}u,{module["text"]}u,{module["entry"]}u,{module["gp"]}u,{module["bss"]}u,'+
                    f'{rel},{len(module["relocations"])}u,{code}'+'}')
        records.append(dict(path=name,sha256=digest,text_bytes=module['text'],
                            instructions=len(entries),relocations=len(module['relocations'])))
    if rows:
        text.extend(['static const DecompNativeModule modules[]={',',\n'.join(rows),'};',
                     f'const DecompNativeModule *decomp_iop_catalog(size_t &count){{count={len(rows)}u;return modules;}}'])
    else:text.append('const DecompNativeModule *decomp_iop_catalog(size_t &count){count=0;return nullptr;}')
    text.append('}');(folder/'catalog.cpp').write_text('\n'.join(text))
    (folder/'catalog.json').write_text(json.dumps(dict(modules=records,native_operations=len(operations)),indent=2)+'\n')
    return dict(modules=records,native_operations=len(operations))


def patch(root):
    lle=Path(root)/'thirdparty/PS2Recomp/ps2xIOP/src/lle'
    (lle/'decomp_iop_execution.hpp').write_bytes(Path(__file__).with_name('iop_execution.hpp').read_bytes())
    replace(lle/'cpu.h','#include <cstdint>','#include <cstdint>\n#include <vector>')
    replace(lle/'cpu.h','    class Cpu\n','    struct IrxImage;\n    class Cpu\n')
    replace(lle/'cpu.h','        uint32_t syscallCode() const noexcept',
        '''        using NativeFunction=StopReason(*)(Cpu&,CpuContext&,uint64_t&,uint32_t);
        struct NativeEntry {uint32_t expected=0,operand=0;NativeFunction function=nullptr;};
        template <uint32_t Word,uint32_t Mask> StopReason nativeStep(CpuContext&,uint64_t&,uint32_t);
        bool nativeBind(const IrxImage&,uint32_t);
        void nativeKernelCall(uint32_t,uint32_t,uint32_t);
        void nativeKernelJump(uint32_t,uint32_t,uint32_t);
        StopReason nativeTrap(CpuContext&,uint64_t&,uint32_t);
        StopReason nativeJump(CpuContext&,uint64_t&,uint32_t);
        uint32_t syscallCode() const noexcept''')
    replace(lle/'cpu.h','        Bus &m_bus;','        Bus &m_bus;\n        std::vector<NativeEntry> m_nativeCode;')
    replace(lle/'iop.cpp','        linkImports(imports);',
        '        if(!m_cpu.nativeBind(irx,base)){release(base);return -1;}\n        linkImports(imports);')
    for where in ('kTrapBase','m_rpcTrap'):
        variable='returnWord' if where=='kTrapBase' else 'rpcWord'
        code='1' if where=='kTrapBase' else '2'
        old=f'        std::memcpy(ram + {where}, &{variable}, 4);'
        replace(lle/'iop.cpp',old,old+f'\n        m_cpu.nativeKernelCall({where},{variable},handlerFor("",{code}));')
    replace(lle/'iop.cpp','            m_bus.write32(import.stubAddress, word);',
        '''            m_bus.write32(import.stubAddress, word);
            if(exported!=m_exports.end()&&import.ordinal<exported->second.size()&&exported->second[import.ordinal])
                m_cpu.nativeKernelJump(import.stubAddress,word,exported->second[import.ordinal]);
            else m_cpu.nativeKernelCall(import.stubAddress,word,handlerFor(import.library,import.ordinal));''')
    # The original interpreter is retained only for a separate reference build.
    source=lle/'cpu.cpp'
    replace(source,'#include "cpu.h"','#include "cpu.h"\n#include "decomp_iop_execution.hpp"')
    replace(source,'        uint32_t *const r = c.gpr;','''        struct ReferenceAccounting {
            uint64_t &cycles;uint64_t start;
            ~ReferenceAccounting(){decomp_ps2::execution::iop_interpreted_instructions.fetch_add(cycles-start,std::memory_order_relaxed);}
        } accounting{cycles,cycles};
        uint32_t *const r = c.gpr;''')
    source.write_text(source.read_text()+'''
namespace ps2x::iop::lle {
bool Cpu::nativeBind(const IrxImage&,uint32_t){return true;}
void Cpu::nativeKernelCall(uint32_t,uint32_t,uint32_t){}
void Cpu::nativeKernelJump(uint32_t,uint32_t,uint32_t){}
}
''')
