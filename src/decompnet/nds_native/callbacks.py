"""Recover referenced callbacks/callees omitted by the DS importers.

Same-image pointers and module-qualified direct calls seed the normal ARM/Thumb
translator's control-flow decoder. Unreferenced prologues and overlay guesses do not.
Reviewed, exact-image reference bounds can supplement fragmented importer records.
Only validated instruction bytes are removed from the importer's data ranges.
"""
from bisect import bisect_right
from collections import defaultdict,deque
from pathlib import Path
import hashlib
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


def _coalesce_dispatch_regions(regions):
    """Give overlapping same-mode regions one body and one slot per entry.

    The gap scanner can grow an inferred region around a recovered callback's
    smaller region. Keep the union of their executable bytes: a hole in one
    callback may contain another callback's instructions. Bytes excluded by
    every covering region remain data and do not enter dispatch identity.
    """
    result=[]
    for thumb in (False,True):
        current=None
        for original in sorted((r for r in regions if bool(r['thumb'])==thumb),
                               key=lambda r:(int(r['addr']),-int(r['size']))):
            region={**original,'addr':int(original['addr']),'size':int(original['size']),
                    'thumb':thumb,'entries':sorted(set(map(int,original['entries']))),
                    'data_ranges':_merge(original.get('data_ranges',[]))}
            start=region['addr'];end=start+region['size']
            if region['size']<=0 or any(not start<=low<high<=end for low,high in region['data_ranges']):
                raise ValueError('invalid dispatch region bounds or data ranges')
            if any(not start<=entry<end or any(low<=entry<high for low,high in region['data_ranges'])
                   for entry in region['entries']):
                raise ValueError('dispatch entry lies outside code bytes')
            if current is None or start>=current['addr']+current['size']:
                if current is not None:result.append(current)
                current=region;continue
            code=_merge(_subtract([[current['addr'],current['addr']+current['size']]],current['data_ranges'])+
                        _subtract([[start,end]],region['data_ranges']))
            data=_subtract(_merge(current['data_ranges']+region['data_ranges']),code)
            current['size']=max(end,current['addr']+current['size'])-current['addr']
            current['entries']=sorted(set(current['entries'])|set(region['entries']))
            current['data_ranges']=data
        if current is not None:result.append(current)
    return sorted(result,key=lambda r:(r['addr'],r['thumb']))


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


def arm7_executable_ranges(manifest,states):
    """Retain the pinned importer's hard autoload exclusions during recovery."""
    by_id={state.module_id:state for state in states}
    reasons={'autoload source payload','autoload block descriptors',
             'autoload/module parameter words','crt0-cleared static BSS',
             'autoload block BSS zeroed by crt0'}
    for module in manifest['modules']:
        state=by_id[int(module['module_id'])]
        allowed=[[state.base+low,state.base+min(high,state.loaded_size)]
                 for low,high in state.executable_ranges]
        excluded=[[state.base+low,state.base+high]
                  for low,high,reason in state.data_ranges if reason in reasons]
        module['executable_ranges']=_subtract(allowed,_merge(excluded))


def recover(manifest,emitter,reader,*,reference_entries=()):
    """Supplement a decoded manifest with statically validated callbacks/callees.

    Optional reviewed reference entries must name their module, instruction
    mode, full bounded extent and exact decoded-module SHA-256. They supplement
    the importer without guessing between overlays sharing a virtual address.
    The normal decoder still validates their complete reachable instruction
    graph and literals. Existing instruction interiors are not callable roots.
    """
    cpu=manifest['cpu'];arch=manifest['arch']
    if cpu not in ('arm9','arm7'):return []
    for module in manifest['modules']:
        if module.get('dispatch_regions'):
            module['dispatch_regions']=_coalesce_dispatch_regions(module['dispatch_regions'])
    entries,images,module_entries,calls=emitter._prepare_entries(manifest,None)
    modules={int(module['module_id']):module for module in manifest['modules']}
    references=defaultdict(dict);hashes={}
    for record in reference_entries:
        if not isinstance(record,dict):raise ValueError('reference callback entry must be an object')
        mid,address,size,thumb=(record.get(key) for key in ('module_id','address','size','thumb'))
        if any(type(value) is not int for value in (mid,address,size)) or type(thumb) is not bool:
            raise ValueError('reference callback module, extent or instruction mode is invalid')
        if mid not in modules:raise ValueError('reference callback module is missing')
        module=modules[mid];base=int(module['base']);alignment=2 if thumb else 4
        if address%alignment or size<=0 or size%alignment or not base<=address<address+size<=base+len(images[mid]):
            raise ValueError('reference callback extent is unaligned or exceeds its initialized module')
        if mid not in hashes:hashes[mid]=hashlib.sha256(images[mid]).hexdigest()
        if record.get('module_sha256')!=hashes[mid]:
            raise ValueError('reference callback decoded-module SHA-256 differs')
        key=(address,thumb)
        if key in references[mid]:raise ValueError('duplicate reference callback entry')
        if any(address<other+length and other<address+size for (other,_),length in references[mid].items()):
            raise ValueError('overlapping reference callback extents')
        references[mid][key]=size
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
        executable=_merge(module.get('executable_ranges',[[base,limit]]))
        if any(not base<=low<high<=limit for low,high in executable):
            raise ValueError('callback executable range exceeds its initialized module')
        def executable_bytes(address,size):
            return any(low<=address and address+size<=high for low,high in executable)
        declared=_merge(module.get('data_ranges',[]))
        if not image:continue
        data_starts=[low for low,_ in declared]
        functions=module['functions']
        intervals=sorted((int(f['addr']),int(f['addr'])+int(f['size']),bool(f['thumb'])) for f in functions)
        starts=[low for low,_,_ in intervals];ends=[]
        for _,end,_ in intervals:ends.append(max(end,ends[-1] if ends else end))
        def covered(address):
            index=bisect_right(starts,address)-1
            return ((index>=0 and address<ends[index]) or
                    any(start<=address<start+size for (start,_),size in reference_roots.items()))
        def covered_modes(address):
            index=bisect_right(starts,address)-1;result=set()
            while index>=0 and ends[index]>address:
                if address<intervals[index][1]:result.add(intervals[index][2])
                index-=1
            result.update(mode for (start,mode),size in reference_roots.items() if start<=address<start+size)
            return result
        decoders={thumb:emitter.Decoder(image,base,arch,thumb) for thumb in (False,True)}
        reference_roots={}
        for (address,thumb),size in references[int(module['module_id'])].items():
            if (int(module['module_id']),address,thumb) in mode_entries:continue
            # A broad imported extent can contain a separate callback after
            # its return. An actual instruction interior, such as a shared
            # epilogue requiring its caller's stack frame, is not a new root.
            for owner in functions:
                start=int(owner['addr'])
                if not start<=address<start+int(owner['size']):continue
                owner_thumb=bool(owner['thumb'])
                owner_entry=emitter.Entry(module,owner,start,owner_thumb,owner['name'],False,cpu)
                owner_body=emitter.FunctionEmitter(cpu,arch,module,image,owner_entry,address_entries,
                    calls,{},module_entries,decoders[owner_thumb],module_mode_entries=mode_entries)
                owner_body._discover()
                if any(op.address<=address<op.next_address for op in owner_body.insns.values()):
                    raise ValueError('reference callback begins inside existing reachable instructions')
            reference_roots[(address,thumb)]=size
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
            if not executable_bytes(address,2 if thumb else 4):return False
            op=decoders[thumb].decode(address)
            return (op is not None and op.condition==14 and
                classify(op,thumb) is not None)
        roots={key:[] for key in reference_roots}
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
        # ARM7 analysis and emission have different switch/flow decoders.
        # Also validate direct calls in the emitted graph; their destinations
        # may be initialized bytes with no data classification or call record.
        if cpu=='arm7':
            for entry in entries:
                if entry.module_id!=int(module['module_id']):continue
                body=emitter.FunctionEmitter(cpu,arch,module,image,entry,address_entries,
                    calls,{},module_entries,decoders[entry.thumb],module_mode_entries=mode_entries)
                body._discover()
                for op in body.insns.values():
                    effect=classify(op,entry.thumb)
                    if effect is None or effect.flow!='call' or effect.target is None:continue
                    target=effect.target&~1
                    mode=entry.thumb!=(body._branch_name(op)=='blx')
                    if covered(target) or not plausible(target,mode):continue
                    roots.setdefault((target,mode),[])
                    call_sources.setdefault((target,mode),[]).append(
                        dict(module_id=int(module['module_id']),address=op.address))
        boundaries=sorted({*starts,*(address for address,_ in roots),
                           *(edge for interval in executable for edge in interval),limit})
        pending=deque(roots);visited=set();accepted={}
        while pending:
            address,thumb=pending.popleft();key=(address,thumb)
            if key in visited or (covered(address) and key not in reference_roots) or not plausible(address,thumb):continue
            visited.add(key)
            # Reviewed full bounds may span partial importer records. Those
            # fragments must not truncate the callback's enclosing stack frame.
            end=address+reference_roots[key] if key in reference_roots else boundaries[bisect_right(boundaries,address)]
            function=dict(addr=address,size=end-address,thumb=thumb,
                name=reader._function_name(module,address))
            entry=emitter.Entry(module,function,address,thumb,function['name'],False,cpu)
            body=emitter.FunctionEmitter(cpu,arch,module,image,entry,address_entries,
                calls,{},module_entries,decoders[thumb],module_mode_entries=mode_entries)
            body._discover()
            if address not in body.insns:continue
            valid=True;code=set();extent=address;targets=[];body_calls=[]
            for op in body.insns.values():
                if not executable_bytes(op.address,op.size):valid=False;break
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
                    if base<=target<limit and (target%(2 if mode else 4) or
                            (covered(target) and mode not in covered_modes(target))):
                        valid=False;break
                    if base<=target<limit and (effect.flow=='call' or not address<=target<end):
                        targets.append((target,mode))
                        body_calls.append(dict(**{'from':op.address,'to':target},modules=[module['module_id']]))
            if not valid:continue
            # Check literal conflicts after the complete graph has been decoded.
            if any(effect.literal is not None and any(byte in code for byte in
                    range(effect.literal[0],effect.literal[0]+effect.literal[1]))
                    for op in body.insns.values() if (effect:=classify(op,thumb)) is not None):
                continue
            function['size']=reference_roots.get(key,extent-address)
            accepted[key]=(function,code,body.leaders,body_calls)
            for target in targets:
                if target not in visited and not covered(target[0]):pending.append(target)
        invalid=set();owners={}
        for key,(_,code,_,_) in accepted.items():
            for byte in code:
                previous=owners.setdefault(byte,key)
                if previous[1]!=key[1]:invalid.update((previous,key))
        for key in invalid:accepted.pop(key,None)
        if reference_roots.keys()-accepted.keys():
            raise ValueError('reference callback failed complete instruction-graph validation')
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
                call_sources=[dict(module_id=mid,address=site) for mid,site in sorted({
                    (x['module_id'],x['address']) for x in call_sources.get((address,thumb),[])})]))
            if (address,thumb) in reference_roots:
                evidence[-1]['reference_size']=reference_roots[(address,thumb)]
                evidence[-1]['reference_module_sha256']=hashes[int(module['module_id'])]
        module.setdefault('callback_recovery',[]).extend(evidence);additions.extend(evidence)
        module['labels']=[dict(addr=address,thumb=thumb) for address,thumb in sorted(labels)]
        functions.sort(key=lambda f:(f['addr'],f['thumb']))
        module['dispatch_regions']=_coalesce_dispatch_regions(module.get('dispatch_regions',[]))
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
            module['dispatch_regions']=_coalesce_dispatch_regions(
                previous[int(module['module_id'])]+module.get('dispatch_regions',[]))
            records=[record for record in scan.added if int(record['module_id'])==int(module['module_id'])]
            if records:module.setdefault('callback_gap_recovery',[]).extend(records)
        gaps.extend(scan.added)
        if not added and not scan.added:break
    manifest['callback_recovery']=[record for module in manifest['modules'] for record in module.get('callback_recovery',[])]
    return dict(callbacks=callbacks,gaps=gaps)
