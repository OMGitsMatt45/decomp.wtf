"""Ahead-of-time, ROM-bound instruction alternatives; guest code stays unchanged.

Only reviewed, predecoded alternatives become C++ cases. Runtime selection
chooses those cases; it never decodes instructions or changes function hashes.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

SCHEMA='decomp.wtf.nds-instruction-choices/v1'
_active=ContextVar('nds_instruction_choices',default=None)

def _edit(root,name,before,after):
    path=root/name;text=path.read_text()
    if text.count(before)!=1:raise ValueError('Pinned instruction-choice runtime anchor differs: '+name)
    path.write_text(text.replace(before,after))

def patch_runtime(root):
    _edit(root,'runtime/include/dsr/rt.h','struct FnEntry {', '''// Every value here has a statically compiled C++ implementation.
struct InstructionChoice {
    CpuId cpu;
    std::int32_t module;
    std::uint32_t address, original;
    unsigned width;
    bool thumb;
    const std::uint32_t* values;
    std::size_t value_count;
};
struct InstructionChoiceTable {
    const InstructionChoice* entries = nullptr;
    std::size_t count = 0;
    const char* sha256 = "";
};
std::uint32_t dsr_instruction_choice(Cpu*, std::size_t, std::uint32_t fallback);

struct FnEntry {''')
    _edit(root,'runtime/include/dsr/machine.h','    GuestAbiConfig guest_abi{};',
          '    GuestAbiConfig guest_abi{};\n    InstructionChoiceTable instruction_choices{};')
    _edit(root,'runtime/include/dsr/machine.h','    Gpu2D& gpu2d();', '''    const InstructionChoiceTable& instruction_choice_table() const;
    bool select_instruction_choice(std::size_t index, std::uint32_t value, std::uint32_t owner);
    void clear_instruction_choices(std::uint32_t owner);
    std::uint32_t instruction_choice(std::size_t index, std::uint32_t fallback) const;

    Gpu2D& gpu2d();''')
    _edit(root,'runtime/core/src/core_internal.h','    MachineConfig config;', '''    MachineConfig config;
    struct InstructionSelection { std::uint32_t value=0,owner=0; };
    std::vector<InstructionSelection> instruction_selections;''')
    _edit(root,'runtime/core/src/machine.cpp','#include <limits>', '#include <limits>\n#include <stdexcept>')
    anchor='Machine::Impl::Impl(const MachineConfig& cfg) : config(cfg), spi(cfg.firmware) {'
    _edit(root,'runtime/core/src/machine.cpp',anchor,anchor+'''
    const auto& choices=cfg.instruction_choices;
    if(choices.count>65536 || (choices.count&&!choices.entries))
        throw std::runtime_error("Invalid native instruction-choice table");
    for(std::size_t i=0;i<choices.count;++i) {
        const auto& entry=choices.entries[i];
        if((entry.cpu!=CpuId::Arm9&&entry.cpu!=CpuId::Arm7)||
           (entry.width!=2&&entry.width!=4)||entry.address%(entry.thumb?2:4)||
           (entry.value_count&&!entry.values)||entry.value_count>256||
           (entry.width==2&&entry.original>65535))
            throw std::runtime_error("Invalid native instruction-choice entry");
        for(std::size_t n=0;n<entry.value_count;++n)
            if(entry.width==2&&entry.values[n]>65535)throw std::runtime_error("Native choice exceeds its width");
    }
    instruction_selections.resize(choices.count);''')
    _edit(root,'runtime/core/src/machine.cpp','bool Machine::replace_function(', '''const InstructionChoiceTable& Machine::instruction_choice_table() const {
    return impl_->config.instruction_choices;
}
bool Machine::select_instruction_choice(std::size_t index,std::uint32_t value,std::uint32_t owner) {
    const auto& table=impl_->config.instruction_choices;
    if(!owner||index>=table.count)return false;
    const auto& entry=table.entries[index];
    if(value!=entry.original) {
        bool allowed=false;
        for(std::size_t i=0;i<entry.value_count;++i)allowed|=entry.values[i]==value;
        if(!allowed)return false;
    }
    impl_->instruction_selections[index]=value==entry.original?Impl::InstructionSelection{}:Impl::InstructionSelection{value,owner};
    return true;
}
void Machine::clear_instruction_choices(std::uint32_t owner) {
    if(!owner)return;
    for(auto& selected:impl_->instruction_selections)if(selected.owner==owner)selected={};
}
std::uint32_t Machine::instruction_choice(std::size_t index,std::uint32_t fallback) const {
    if(index>=impl_->instruction_selections.size())return fallback;
    const auto& selected=impl_->instruction_selections[index];
    return selected.owner?selected.value:fallback;
}
std::uint32_t dsr_instruction_choice(Cpu* cpu,std::size_t index,std::uint32_t fallback) {
    return cpu->m->instruction_choice(index,fallback);
}
bool Machine::replace_function(''')

def _number(value):
    if isinstance(value,str):return int(value,0)
    if type(value) is not int:raise ValueError('Instruction choices require integer fields')
    return value

def prepare(spec,manifests,digest,emitter):
    if spec is None:return dict(sites=[],sha256='')
    if not isinstance(spec,dict) or spec.get('schema')!=SCHEMA or spec.get('input_sha256')!=digest:raise ValueError('Instruction-choice schema or ROM identity differs')
    source=spec.get('sites')
    if not isinstance(source,list) or not 0<len(source)<=65536:raise ValueError('Invalid instruction-choice site count')
    modules={(m['cpu'],int(module['module_id'])):(m,module) for m in manifests for module in m['modules']}
    images={};sites=[];seen=set()
    for record in source:
        if not isinstance(record,dict):raise ValueError('Invalid instruction-choice record')
        cpu=record.get('cpu');module_id=_number(record.get('module'));pc=_number(record.get('address'))
        if cpu not in ('arm9','arm7'):raise ValueError('Unknown instruction-choice CPU')
        width=_number(record.get('width'));original=_number(record.get('original'));thumb=record.get('thumb')
        if type(thumb) is not bool or width not in (2,4) or pc%(2 if thumb else 4):raise ValueError('Invalid instruction-choice mode or alignment')
        key=cpu,module_id,pc,thumb
        if key in seen:raise ValueError('Duplicate instruction-choice site')
        seen.add(key)
        if (cpu,module_id) not in modules:raise ValueError('Unknown instruction-choice module')
        manifest,module=modules[cpu,module_id]
        if (cpu,module_id) not in images:images[cpu,module_id]=Path(module['image']).read_bytes()
        raw=images[cpu,module_id];offset=pc-int(module['base'])
        if offset<0 or offset+width>len(raw) or int.from_bytes(raw[offset:offset+width],'little')!=original:
            raise ValueError(f'Instruction-choice original bytes differ at {cpu}:{module_id}:{pc:#x}')
        values=record.get('values')
        if not isinstance(values,list) or len(values)>256:raise ValueError('Invalid instruction-choice alternatives')
        values=sorted(set(_number(x) for x in values)-{original})
        if original<0 or original>=1<<(width*8) or any(x<0 or x>=1<<(width*8) for x in values):raise ValueError('Instruction choice exceeds its width')
        decoded={}
        for word in [original,*values]:
            op=emitter.Decoder(word.to_bytes(width,'little'),pc,manifest['arch'],thumb).decode(pc)
            if op is None or op.size!=width:raise ValueError(f'Instruction-choice boundary differs at {pc:#x}')
            decoded[word]=op
        sites.append(dict(cpu=cpu,module=module_id,address=pc,width=width,thumb=thumb,original=original,values=values,decoded=decoded))
    sites.sort(key=lambda x:(x['cpu'],x['module'],x['address'],x['thumb']))
    canonical=[]
    for index,site in enumerate(sites):
        site['index']=index;canonical.append({k:v for k,v in site.items() if k!='decoded'})
    policy_hash=hashlib.sha256(json.dumps(dict(input_sha256=digest,sites=canonical),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(sites=sites,sha256=policy_hash)

@contextmanager
def activate(policy):
    state=dict(sites={(s['cpu'],s['module'],s['address'],s['thumb']):s for s in policy['sites']},used=set())
    token=_active.set(state)
    try:yield state
    finally:_active.reset(token)

def write_header(root,policy):
    if not policy['sites']:return
    lines=['#pragma once','#include <dsr/machine.h>','namespace nds_native_choices {']
    for s in policy['sites']:
        if s['values']:lines.append('inline constexpr std::uint32_t values_'+str(s['index'])+'[]={'+','.join(hex(v)+'u' for v in s['values'])+'};')
    lines.append('inline constexpr dsr::InstructionChoice entries[]={')
    for s in policy['sites']:
        values='values_'+str(s['index']) if s['values'] else 'nullptr'
        lines.append('{dsr::CpuId::'+('Arm9' if s['cpu']=='arm9' else 'Arm7')+f',{s["module"]},{s["address"]}u,{s["original"]}u,{s["width"]},'+str(s['thumb']).lower()+f',{values},{len(s["values"])}'+'},')
    lines.extend(['};','inline void configure(dsr::MachineConfig& config){config.instruction_choices={entries,'+str(len(policy['sites']))+','+json.dumps(policy['sha256'])+'};}','}'])
    (root/'native/instruction_choices.hpp').write_text('\n'.join(lines)+'\n')

def install(emitter):
    cls=emitter.FunctionEmitter
    if getattr(cls,'_decomp_instruction_choices',False):return
    original_one=cls._one;original_discover=cls._discover;original_memory=cls._memory_instruction
    def site_for(self,address):
        state=_active.get()
        return state['sites'].get((self.cpu,self.entry.module_id,address,self.thumb)) if state else None
    def discover(self):
        original_discover(self);state=_active.get()
        if not state:return
        processed=set()
        while True:
            candidates=[site_for(self,pc) for pc in list(self.insns)]
            pending=[s for s in candidates if s and s['index'] not in processed]
            if not pending:break
            for site in pending:
                processed.add(site['index']);pc=site['address'];original=self.insns[pc]
                for value in site['values']:
                    alt=site['decoded'][value];clone=copy(self)
                    clone.insns={p:i for p,i in self.insns.items() if p!=pc}
                    clone.leaders=set(self.leaders);clone.loop_headers=set(self.loop_headers)
                    clone.dispatch_entries=[SimpleNamespace(address=pc)]
                    delegate=self.decoder
                    class OverlayDecoder:
                        def decode(_,address):return alt if address==pc else delegate.decode(address)
                        def __getattr__(_,name):return getattr(delegate,name)
                    clone.decoder=OverlayDecoder();original_discover(clone)
                    new_loops=clone.loop_headers-self.loop_headers
                    if new_loops:raise ValueError('Instruction choices cannot introduce a new backward checkpoint')
                    for address,op in clone.insns.items():
                        if address!=pc:self.insns.setdefault(address,op)
                    self.leaders.update(clone.leaders)
                    if self._terminator(original) and not self._terminator(alt) and self._inside(original.next_address):
                        self.leaders.add(original.next_address)
    def one(self,insn):
        site=site_for(self,insn.address)
        if not site:return original_one(self,insn)
        _active.get()['used'].add(site['index'])
        base=original_one(self,insn)
        if not site['values']:return base
        bodies=[];all_exit=True
        for value in [site['original'],*site['values']]:
            op=insn if value==site['original'] else site['decoded'][value]
            body,exits=base if value==site['original'] else original_one(self,op)
            if not exits and base[1] and not self._inside(op.next_address):
                target=op.next_address|int(self.thumb)
                if not any(e.thumb==self.thumb for e in self.address_entries.get(op.next_address,[])):
                    raise ValueError(f'Instruction-choice continuation needs a decoded entry at {target:#x}')
                body+=f'\n::dsr::dsr_call(c, {target}u);\nreturn;';exits=True
            all_exit&=exits
            bodies.append(f'case {value}u: {{\n{body}\nbreak;\n}}')
        body=f'switch (::dsr::dsr_instruction_choice(c, {site["index"]}u, {site["original"]}u)) {{\n'+'\n'.join(bodies)+f'\ndefault: ::dsr::dsr_undefined(c, {insn.address}u, {insn.raw}u);\n}}'
        return body,all_exit
    def memory(self,insn):
        body=original_memory(self,insn)
        if body is None or insn.mnemonic.split('.')[0]!='ldr':return body
        mem=next((o.mem for o in insn.operands if o.type==emitter.ARM_OP_MEM),None)
        if mem is None:return body
        target=self._mem_literal_address(insn,mem,False)
        site=site_for(self,target) if target is not None else None
        if not site or site['width']!=4:return body
        _active.get()['used'].add(site['index'])
        before=f'::dsr::ldr32(c, {emitter._u32(target)})'
        if body.count(before)!=1:raise ValueError('Instruction-choice literal load differs from pinned emitter')
        return body.replace(before,f'::dsr::dsr_instruction_choice(c, {site["index"]}u, {before})')
    cls._discover=discover;cls._one=one;cls._memory_instruction=memory;cls._decomp_instruction_choices=True
