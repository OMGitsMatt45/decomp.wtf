"""Recover referenced ARM9 callbacks that the DS importer classified as data.

Same-image pointers from declared data seed the normal ARM/Thumb translator's
control-flow decoder. Unreferenced prologues and cross-overlay guesses do not.
Only validated instruction bytes are removed from the importer's data ranges.
"""
from bisect import bisect_right
from collections import defaultdict,deque
import struct


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


def recover(manifest,emitter,reader):
    """Supplement a decoded manifest with statically validated callbacks/callees."""
    if manifest['cpu']!='arm9':return []
    entries,images,module_entries,calls=emitter._prepare_entries(manifest,None)
    address_entries=defaultdict(list)
    for entry in entries:address_entries[entry.address].append(entry)
    mode_entries={(e.module_id,e.address,e.thumb):e for e in entries}
    additions=[]
    for module in manifest['modules']:
        image=images[int(module['module_id'])];base=int(module['base']);limit=base+len(image)
        declared=_merge(module.get('data_ranges',[]))
        if not image or not declared:continue
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
            return reader._effect(decoded,thumb) if decoded is not None and decoded.size==op.size else None
        def plausible(address,thumb):
            if not base<=address<limit or address%(2 if thumb else 4):return False
            op=decoders[thumb].decode(address)
            return (op is not None and op.condition==14 and
                classify(op,thumb) is not None)
        roots={}
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
        for (address,thumb),(function,_,leaders,body_calls) in accepted.items():
            functions.append(function)
            labels.update((leader,thumb) for leader in leaders if address<=leader<address+function['size'])
            module.setdefault('calls',[]).extend(body_calls)
            evidence.append(dict(module_id=module['module_id'],address=address,thumb=thumb,
                size=function['size'],pointer_sources=roots.get((address,thumb),[])))
        module['callback_recovery']=evidence;additions.extend(evidence)
        module['labels']=[dict(addr=address,thumb=thumb) for address,thumb in sorted(labels)]
        functions.sort(key=lambda f:(f['addr'],f['thumb']))
    manifest['callback_recovery']=additions
    return additions
