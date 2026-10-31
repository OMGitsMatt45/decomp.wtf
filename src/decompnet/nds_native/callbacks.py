"""Recover referenced ARM9 callbacks that the DS importer classified as data.

Same-image pointers and module-qualified direct calls seed the normal ARM/Thumb
translator's control-flow decoder. Unreferenced prologues and overlay guesses do not.
Only validated instruction bytes are removed from the importer's data ranges.
"""
from bisect import bisect_right
from collections import defaultdict,deque
from pathlib import Path
import struct

from capstone.arm_const import ARM_OP_MEM, ARM_REG_PC


def _runs(values):
    result=[]
    for value in sorted(values):
        if result and value==result[-1][1]:result[-1][1]+=1
        else:result.append([value,value+1])
    return result


def _merge(ranges):
    result=[]
    for low,high in sorted(ranges):
        if low>=high:continue
        if result and low<=result[-1][1]:result[-1][1]=max(high,result[-1][1])
        else:result.append([low,high])
    return result


def _subtract(ranges,removed):
    result=[]
    for low,high in ranges:
        position=low
        for start,end in removed:
            if end<=position:continue
            if start>=high:break
            if position<start:result.append([position,start])
            position=max(position,end)
            if position>=high:break
        if position<high:result.append([position,high])
    return result


def codec_functions(manifest,metadata,reader):
    """Use decoded DS Protect function boundaries instead of broad gap guesses.

    These are the toolkit's input-derived codec records, not signature guesses.
    Separating each protected function prevents its inactive encrypted neighbors
    from invalidating live dispatch identity.
    """
    if manifest['cpu']!='arm9':return []
    additions=[]
    for module in manifest['modules']:
        item=metadata.get(int(module['module_id']),{})
        protect=item.get('dsprot') if isinstance(item,dict) else None
        state=protect.get('unencrypted') if isinstance(protect,dict) else None
        if not isinstance(state,dict) or not state.get('functions'):continue
        base=int(module['base']);limit=base+Path(module['image']).stat().st_size
        records=[]
        for record in state['functions']:
            start=int(record['address']);size=int(record['size']);pool=int(record.get('pool_size') or 0)
            if start%4 or size<=0 or size%4 or pool<0 or pool%4 or not base<=start<start+size+pool<=limit:
                raise ValueError('DS Protect function boundary exceeds its decoded module or is unaligned')
            records.append((start,size,pool,record))
        records.sort(key=lambda item:item[0])
        if any(a[0]+a[1]+a[2]>b[0] for a,b in zip(records,records[1:])):
            raise ValueError('overlapping DS Protect function boundaries')
        extents=[(start,start+size+pool) for start,size,pool,_ in records]
        code=[[start,start+size] for start,size,_,_ in records]
        pools=[[start+size,start+size+pool] for start,size,pool,_ in records if pool]
        def overlaps(start,end):return any(start<high and low<end for low,high in extents)
        names={int(f['addr']):f['name'] for f in module['functions'] if not f['thumb']}
        module['functions']=[f for f in module['functions'] if not overlaps(int(f['addr']),int(f['addr'])+int(f['size']))]
        module['dispatch_regions']=[r for r in module.get('dispatch_regions',[]) if not overlaps(int(r['addr']),int(r['addr'])+int(r['size']))]
        module['labels']=[label for label in module.get('labels',[]) if not any(low<=int(label['addr'])<high for low,high in pools)]
        module['data_ranges']=_merge(_subtract(module.get('data_ranges',[]),code)+pools)
        module['code_ranges']=_merge(module.get('code_ranges',[])+code)
        evidence=[]
        for start,size,pool,record in records:
            module['functions'].append(dict(addr=start,size=size+pool,thumb=False,
                name=names.get(start,reader._function_name(module,start))))
            module['dispatch_regions'].append(dict(addr=start,size=size+pool,thumb=False,
                data_ranges=[[start+size,start+size+pool]] if pool else [],entries=[start]))
            evidence.append(dict(module_id=module['module_id'],address=start,code_size=size,
                pool_size=pool,version=state.get('version'),encryption=record.get('encryption')))
        module['codec_recovery']=evidence;additions.extend(evidence)
        module['functions'].sort(key=lambda f:(f['addr'],f['thumb']))
        module['dispatch_regions'].sort(key=lambda r:(r['addr'],r['thumb']))
    manifest['codec_recovery']=additions
    return additions


def recover(manifest,emitter,reader):
    """Supplement a decoded manifest with statically validated callbacks/callees."""
    if manifest['cpu']!='arm9':return []
    entries,images,module_entries,calls=emitter._prepare_entries(manifest,None)
    address_entries=defaultdict(list)
    for entry in entries:address_entries[entry.address].append(entry)
    mode_entries={(e.module_id,e.address,e.thumb):e for e in entries}
    direct_roots=defaultdict(lambda:defaultdict(list))
    for source in manifest['modules']:
        image=images[int(source['module_id'])];base=int(source['base'])
        ranges=sorted((int(f['addr']),int(f['addr'])+int(f['size']),bool(f['thumb']))
                      for f in source['functions'])
        source_starts=[low for low,_,_ in ranges];source_ends=[]
        for _,end,_ in ranges:source_ends.append(max(end,source_ends[-1] if source_ends else end))
        for call in source.get('calls',[]):
            targets=call.get('modules',[])
            if len(targets)!=1:continue
            site=int(call['from']);target=int(call['to'])&~1
            index=bisect_right(source_starts,site)-1;modes=set()
            while index>=0 and source_ends[index]>site:
                if site<ranges[index][1]:modes.add(ranges[index][2])
                index-=1
            if len(modes)!=1 or not base<=site<base+len(image):continue
            thumb=modes.pop()
            if site%(2 if thumb else 4):continue
            decoded=next(reader._disassembler(thumb).disasm(image[site-base:site-base+4],site,1),None)
            effect=reader._effect(decoded,thumb) if decoded is not None else None
            if (effect is None or effect.flow not in ('call','branch') or
                    effect.target is None or effect.target&~1!=target):continue
            mode=thumb!=decoded.mnemonic.startswith('blx')
            direct_roots[int(targets[0])][(target,mode)].append(
                dict(module_id=int(source['module_id']),address=site))
    additions=[]
    for module in manifest['modules']:
        image=images[int(module['module_id'])];base=int(module['base']);limit=base+len(image)
        declared=_merge(module.get('data_ranges',[]))
        if not image:continue
        data_starts=[low for low,_ in declared]
        functions=module['functions']
        intervals=sorted((int(f['addr']),int(f['addr'])+int(f['size'])) for f in functions)
        starts=[low for low,_ in intervals];ends=[]
        for _,end in intervals:ends.append(max(end,ends[-1] if ends else end))
        def covered(address):
            index=bisect_right(starts,address)-1
            return index>=0 and address<ends[index]
        decoders={thumb:emitter.Decoder(image,base,'v5te',thumb) for thumb in (False,True)}
        def classify(op,thumb):
            decoded=next(reader._disassembler(thumb).disasm(
                image[op.address-base:op.address-base+4],op.address,1),None)
            if decoded is None or decoded.size!=op.size:return None
            result=reader._effect(decoded,thumb)
            if result is not None:return result
            # ARM permits PC-relative stores to nearby data. Prove that the
            # destination is initialized non-code bytes using the same literal
            # checks as loads, rather than allowing a write into instructions.
            width={'str':4,'strb':1,'strh':2}.get(decoded.insn_name())
            memory=next((operand.mem for operand in decoded.operands if operand.type==ARM_OP_MEM),None)
            if (not thumb and width and memory is not None and memory.base==ARM_REG_PC
                    and not memory.index and not decoded.writeback):
                return reader._Effect('next',op.condition!=14,literal=(op.address+8+memory.disp,width))
            return None
        def plausible(address,thumb):
            if not base<=address<limit or address%(2 if thumb else 4):return False
            op=decoders[thumb].decode(address)
            return (op is not None and op.condition==14 and
                classify(op,thumb) is not None)
        roots={}
        call_sources={}
        for key,sources in direct_roots[int(module['module_id'])].items():
            address,thumb=key
            if not covered(address) and plausible(address,thumb):
                roots[key]=[];call_sources[key]=sources
        for offset in range((-base)%4,len(image)-3,4):
            source=base+offset;index=bisect_right(data_starts,source)-1
            if index<0 or source+4>declared[index][1]:continue
            value=struct.unpack_from('<I',image,offset)[0];address=value&~1;thumb=bool(value&1)
            if covered(address) or not plausible(address,thumb):continue
            roots.setdefault((address,thumb),[]).append(source)
        boundaries=sorted({*starts,*(address for address,_ in roots),limit})
        pending=deque(roots);visited=set();accepted={}
        while pending:
            address,thumb=pending.popleft();key=(address,thumb)
            if key in visited or covered(address) or not plausible(address,thumb):continue
            visited.add(key)
            end=boundaries[bisect_right(boundaries,address)]
            function=dict(addr=address,size=end-address,thumb=thumb,
                name=reader._function_name(module,address))
            entry=emitter.Entry(module,function,address,thumb,function['name'],False,'arm9')
            body=emitter.FunctionEmitter('arm9','v5te',module,image,entry,address_entries,
                calls,{},module_entries,decoders[thumb],module_mode_entries=mode_entries)
            body._discover()
            if address not in body.insns:continue
            valid=True;code=set();extent=address;targets=[];body_calls=[]
            for op in body.insns.values():
                effect=classify(op,thumb)
                if effect is None:valid=False;break
                if ((effect.flow in ('next','call') or effect.conditional) and
                        op.address not in getattr(body,'_decomp_tail_exits',set()) and
                        op.next_address not in body.insns):
                    valid=False;break
                if (effect.flow=='branch' and effect.target is not None and
                        address<=effect.target<end and effect.target not in body.insns):
                    valid=False;break
                code.update(range(op.address,op.next_address));extent=max(extent,op.next_address)
                if effect.literal is not None:
                    literal,width=effect.literal
                    if base<=literal and literal+width<=limit:
                        if literal+width<=end:extent=max(extent,literal+width)
                        if any(byte in code for byte in range(literal,literal+width)):
                            valid=False;break
                    else:valid=False;break
                if effect.flow in ('branch','call') and effect.target is not None:
                    target=effect.target&~1
                    mode=thumb!=(body._branch_name(op)=='blx')
                    if base<=target<limit and (effect.flow=='call' or not address<=target<end):
                        targets.append((target,mode))
                        body_calls.append(dict(**{'from':op.address,'to':target},modules=[module['module_id']]))
            if not valid:continue
            # Check literal conflicts after the complete graph has been decoded.
            if any(effect.literal is not None and any(byte in code for byte in
                    range(effect.literal[0],effect.literal[0]+effect.literal[1]))
                    for op in body.insns.values() if (effect:=classify(op,thumb)) is not None):
                continue
            function['size']=extent-address
            accepted[key]=(function,code,body.leaders,body_calls)
            for target in targets:
                if target not in visited and not covered(target[0]):pending.append(target)
        invalid=set();owners={}
        for key,(_,code,_,_) in accepted.items():
            for byte in code:
                previous=owners.setdefault(byte,key)
                if previous[1]!=key[1]:invalid.update((previous,key))
        for key in invalid:accepted.pop(key,None)
        if not accepted:continue
        code=set().union(*(record[1] for record in accepted.values()));runs=_runs(code)
        module['data_ranges']=_subtract(declared,runs)
        module['code_ranges']=_merge(module.get('code_ranges',[])+runs)
        labels={(int(x['addr']),bool(x['thumb'])) for x in module.get('labels',[])}
        evidence=[]
        for (address,thumb),(function,code,leaders,body_calls) in accepted.items():
            functions.append(function)
            end=address+function['size']
            holes=_subtract([[address,end]],_runs(code))
            if holes:
                # Mutable literals must not participate in overlay identity.
                # The existing region runtime hashes instructions while still
                # executing loads/stores against the actual guest data bytes.
                module.setdefault('dispatch_regions',[]).append(dict(addr=address,
                    size=function['size'],thumb=thumb,data_ranges=holes,
                    entries=sorted({address,*(leader for leader in leaders if address<=leader<end)})))
            labels.update((leader,thumb) for leader in leaders if address<=leader<address+function['size'])
            module.setdefault('calls',[]).extend(body_calls)
            evidence.append(dict(module_id=module['module_id'],address=address,thumb=thumb,
                size=function['size'],pointer_sources=roots.get((address,thumb),[]),
                call_sources=call_sources.get((address,thumb),[])))
        module.setdefault('callback_recovery',[]).extend(evidence);additions.extend(evidence)
        module['labels']=[dict(addr=address,thumb=thumb) for address,thumb in sorted(labels)]
        functions.sort(key=lambda f:(f['addr'],f['thumb']))
    manifest['callback_recovery']=additions
    return additions


def complete(manifest,emitter,reader):
    """Alternate referenced callbacks and strict code-gap scans to a fixed point.

    Recovering a callback can partition a previously rejected gap into valid
    bounded functions. Keep established dispatch regions while the upstream
    gap scanner builds regions for those newly inferred functions.
    """
    if manifest['cpu']!='arm9':return dict(callbacks=[],gaps=[])
    callbacks=[];gaps=[]
    while True:
        added=recover(manifest,emitter,reader);callbacks.extend(added)
        previous={int(m['module_id']):list(m.get('dispatch_regions',[])) for m in manifest['modules']}
        scan=reader._GapDiscovery(manifest['modules'],[m.get('code_ranges',[]) for m in manifest['modules']])
        for module in manifest['modules']:
            regions={}
            for region in previous[int(module['module_id'])]+module.get('dispatch_regions',[]):
                regions[(int(region['addr']),int(region['size']),bool(region['thumb']))]=region
            module['dispatch_regions']=[regions[key] for key in sorted(regions)]
            records=[record for record in scan.added if int(record['module_id'])==int(module['module_id'])]
            if records:module.setdefault('callback_gap_recovery',[]).extend(records)
        gaps.extend(scan.added)
        if not added and not scan.added:break
    manifest['callback_recovery']=[record for module in manifest['modules'] for record in module.get('callback_recovery',[])]
    return dict(callbacks=callbacks,gaps=gaps)
