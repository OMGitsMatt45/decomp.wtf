"""Control-flow corrections for the pinned MIT DQ9-Decomp emitter.

A signed lower-bound guard must not truncate a switch, and shared epilogues
must return to the caller whose saved frame they consume. This adapts the
upstream emitter through its decoded instruction interface; no game addresses,
bytes or title-specific entry lists are used.
"""
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG


def install(emitter):
    cls=emitter.FunctionEmitter
    if getattr(cls,'_decomp_bounds_fixed',False):return
    original=cls._jump_case_count
    branch=cls._branch
    secondary=emitter._secondary_branch_entries
    table_info=cls._jump_table_info
    slot_for=cls._slot_for

    def overlay_slot(self,target,source):
        entry=slot_for(self,target,source)
        if entry is None or entry.module_id<0:return entry
        owners={item.module_id for item in self.address_entries.get(entry.address,[])
                if item.thumb==entry.thumb}
        # Identical caller bytes may exist in several overlays while their
        # callees differ. A caller's byte hash cannot establish which overlay
        # owns a direct C++ slot. Resolve the live callee bytes at these sites.
        return None if len(owners)>1 else entry

    def constant(self,register,previous,depth=0):
        if depth>8:return None
        for index in range(len(previous)-1,-1,-1):
            op=previous[index];name=cls._branch_name(op).rstrip('s');args=op.operands
            if name in ('b','bl','bx','blx','pop'):return None
            _,writes=op.detail.regs_access()
            if not any(op.detail.reg_name(r) in (f'r{register}',{9:'sb',10:'sl',11:'fp',12:'ip'}.get(register)) for r in writes):continue
            if op.condition!=14 or not args or args[0].type!=ARM_OP_REG:return None
            if name in ('mov','mvn') and len(args)==2 and args[1].type==ARM_OP_IMM:
                value=int(args[1].imm)
                return (value if name=='mov' else ~value)&0xffffffff
            if (name not in ('add','sub','rsb') or len(args)!=3 or args[1].type!=ARM_OP_REG
                    or args[2].type!=ARM_OP_IMM or args[1].shift.type):return None
            value=constant(self,emitter.operand_reg(op,args[1]),previous[:index],depth+1)
            if value is None:return None
            immediate=int(args[2].imm)
            return {'add':value+immediate,'sub':value-immediate,'rsb':immediate-value}[name]&0xffffffff
        return None

    def bounded_arm_table(self,insn):
        result=table_info(self,insn)
        if insn.thumb or cls._branch_name(insn)!='add' or insn.condition not in (3,9):return result
        ops=insn.operands
        if len(ops)!=3 or any(op.type!=ARM_OP_REG for op in ops):return result
        if emitter.operand_reg(insn,ops[0])!=15 or emitter.operand_reg(insn,ops[1])!=15:return result
        shift,register,_=emitter.shift_kind(ops[2].shift.type)
        if shift!=0 or register or ops[2].shift.value!=2:return result
        previous=self._preceding(insn,20)
        if not previous:return result
        compare=previous[-1];args=compare.operands
        if (cls._branch_name(compare)!='cmp' or compare.condition!=14 or len(args)!=2
                or args[0].type!=ARM_OP_REG or args[1].type not in (ARM_OP_IMM,ARM_OP_REG)
                or emitter.operand_reg(compare,args[0])!=emitter.operand_reg(insn,ops[2])):return result
        bound=(int(args[1].imm) if args[1].type==ARM_OP_IMM else
               constant(self,emitter.operand_reg(compare,args[1]),previous[:-1]))
        if bound is None or args[1].shift.type:return result
        count=bound+(insn.condition==9)
        if not 0<count<=4096:return result
        start=insn.address+8
        cases=[(index,start+index*4) for index in range(count)]
        if not all(self._function_contains(address) for _,address in cases):return result
        # CMP followed immediately by unsigned ADDLO/ADDLS proves the full
        # bound. An inline return or another instruction is a valid slot too;
        # a contiguous run of B instructions must not truncate the table.
        return dict(kind='add',index=emitter.operand_reg(insn,ops[2]),base=start,shift=2,cases=cases)

    def secondary_entries(edges,entries,*args,**kwargs):
        # A branch can only acquire a secondary entry in its own module/mode.
        # Preserve the upstream ownership/overlap proof, but avoid scanning
        # every function in every overlay for each branch in a large game.
        groups={}
        for entry in entries:
            groups.setdefault((entry.module_id,entry.thumb),[]).append(entry)
        branches={}
        for source,target in edges:
            branches.setdefault((source.module_id,source.thumb),[]).append((source,target))
        result=[];sources=set()
        for key in sorted(branches):
            found,used=secondary(branches[key],groups.get(key,[]),*args,**kwargs)
            result.extend(found);sources.update(used)
        return sorted(result,key=lambda entry:(entry.module_id,entry.address,entry.thumb)),sources

    discover_source=cls._discover

    def adjustment(op):
        name=cls._branch_name(op).rstrip('s');ops=op.operands
        if name not in ('add','sub') or len(ops) not in (2,3) or op.condition!=14:
            return None
        if ops[0].type!=ARM_OP_REG or emitter.operand_reg(op,ops[0])!=13 or ops[-1].type!=ARM_OP_IMM:
            return None
        if len(ops)==3 and (ops[1].type!=ARM_OP_REG or emitter.operand_reg(op,ops[1])!=13):
            return None
        value=int(ops[-1].imm)
        if value<0 or value%4:return None
        return value if name=='add' else -value

    def stack_load(op,register,offset=None):
        if cls._branch_name(op)!='ldr' or len(op.operands)!=2 or op.writeback:return False
        dest,source=op.operands
        return (dest.type==ARM_OP_REG and emitter.operand_reg(op,dest)==register
                and source.type==ARM_OP_MEM and emitter.reg_index(op,source.mem.base)==13
                and not source.mem.index and source.mem.disp>=0 and source.mem.disp%4==0
                and (offset is None or source.mem.disp==offset))

    def registers(op,name,expected):
        return (cls._branch_name(op)==name and all(item.type==ARM_OP_REG for item in op.operands)
                and {emitter.operand_reg(op,item) for item in op.operands}==expected)

    def probe(decoder,address,limit,entry=False):
        # Compiler entry/exit instrumentation saves its argument around a
        # returning helper. Recognize the whole balanced sequence, including
        # the entry's restoration of the original LR; never ignore arbitrary
        # PUSHes, calls or stack writes while proving a shared return.
        ops=[]
        for _ in range(7 if entry else 6):
            op=decoder.decode(address)
            if op is None or op.next_address>limit or op.condition!=14:return None
            ops.append(op);address=op.next_address
        call=ops[2] if entry else ops[3]
        if (cls._branch_name(call) not in ('bl','blx') or len(call.operands)!=1
                or call.operands[0].type!=ARM_OP_IMM):return None
        if entry:
            load=ops[1];move=ops[4]
            if not (registers(ops[0],'push',{0,14}) and cls._branch_name(load)=='ldr'
                    and len(load.operands)==2 and load.operands[0].type==ARM_OP_REG
                    and emitter.operand_reg(load,load.operands[0])==0
                    and load.operands[1].type==ARM_OP_MEM
                    and emitter.reg_index(load,load.operands[1].mem.base)==15
                    and not load.operands[1].mem.index and not load.writeback
                    and stack_load(ops[3],0,4) and cls._branch_name(move).rstrip('s')=='mov'
                    and len(move.operands)==2 and all(item.type==ARM_OP_REG for item in move.operands)
                    and [emitter.operand_reg(move,item) for item in move.operands]==[14,0]
                    and stack_load(ops[5],0,0) and adjustment(ops[6])==8):return None
        elif not (registers(ops[0],'push',{0}) and stack_load(ops[1],0)
                  and registers(ops[2],'push',{0}) and stack_load(ops[4],0,4)
                  and adjustment(ops[5])==8):return None
        return address,{op.address for op in ops}

    def shared_exit(self,insn,target):
        """Prove a Thumb helper releases exactly this caller's stack frame.

        BL can be a long branch to a shared epilogue. Match the saved registers
        and a constant prologue allocation against ADD sp / POP {...,pc}; reject
        new callee frames, other stack writes and ambiguous control flow.
        """
        if not insn.thumb or insn.condition!=14:return False
        target &= ~1
        entry=slot_for(self,target,insn)
        if entry is not None:
            if not entry.thumb:return False
            module,end=entry.module,entry.end
        elif self._inside(target):
            module,end=self.module,self.end
        else:return False
        instrumented=probe(self.decoder,self.begin,self.end,entry=True)
        start,probe_sites=instrumented if instrumented else (self.begin,set())
        prologue=self.decoder.decode(start)
        if prologue is None or cls._branch_name(prologue)!='push' or prologue.condition!=14:return False
        saved={emitter.operand_reg(prologue,op) for op in prologue.operands if op.type==ARM_OP_REG}
        if 14 not in saved:return False
        expected=(saved-{14})|{15}
        allocation=0;prologue_sites=probe_sites|{start};address=prologue.next_address
        for _ in range(4):
            op=self.decoder.decode(address)
            delta=adjustment(op) if op is not None else None
            if delta is None or delta>=0:break
            allocation-=delta;prologue_sites.add(address);address=op.next_address
        def epilogue(image,start,limit):
            base=int(image['base'])
            if image is self.module:prefix=self.image[start-base:min(limit-base,start-base+64)]
            else:
                with open(image['image'],'rb') as stream:
                    stream.seek(start-base);prefix=stream.read(min(limit-start,64))
            decoder=emitter.Decoder(prefix,start,self.arch,True)
            released=0;sites=set();address=start
            for _ in range(16):
                if address>=limit:return None
                op=decoder.decode(address)
                if op is None or op.next_address>limit or op.condition!=14:return None
                name=cls._branch_name(op).rstrip('s');sites.add(address)
                if name=='push' and released==allocation:
                    instrumented=probe(decoder,address,limit)
                    if instrumented is None:return None
                    address,probe_sites=instrumented;sites.update(probe_sites)
                    continue
                if name=='pop':
                    restored={emitter.operand_reg(op,item) for item in op.operands if item.type==ARM_OP_REG}
                    return sites if restored==expected and released==allocation else None
                delta=adjustment(op)
                if delta is not None:
                    if delta<0:return None
                    released+=delta
                    if released>allocation:return None
                else:
                    if name not in ('mov','mvn','add','sub','and','orr','eor','bic','lsl','lsr','asr','ror',
                                    'cmp','tst','ldr','ldrb','ldrh','ldrsb','ldrsh','str','strb','strh','nop'):return None
                    if name in ('str','strb','strh') and any(
                            op.detail.reg_name(reg) in ('sp','pc','r13','r15')
                            for item in op.operands if item.type==ARM_OP_MEM
                            for reg in (item.mem.base,item.mem.index) if reg):return None
                    _,writes=op.detail.regs_access()
                    if any(op.detail.reg_name(r) in ('sp','lr','pc','r13','r14','r15') for r in writes):return None
                address=op.next_address
            return None
        def body_exit(start):
            # A Thumb BL may be the compiler's long branch into a large arm
            # of the same function. Follow its decoded graph, including loops
            # and ordinary external calls, and prove every exit consumes the
            # caller's frame. A new frame, LR return, unknown dispatch, missing
            # instruction or inconsistent stack delta makes this inconclusive.
            if not self._inside(start) or start not in self.insns:return None
            pending=[(start,0)];states={};sites=set();returned=False;edges=set();tables=[]
            def follow(source,destination,released):
                edges.add((source,destination));pending.append((destination,released))
            while pending:
                address,released=pending.pop()
                if address in states:
                    if states[address]!=released:return None
                    continue
                op=self.insns.get(address)
                if op is None:return None
                states[address]=released;sites.add(address)
                name=cls._branch_name(op).rstrip('s')
                if op.condition!=14 and name!='b':return None
                if name=='pop':
                    restored={emitter.operand_reg(op,item) for item in op.operands if item.type==ARM_OP_REG}
                    if restored!=expected or released!=allocation:return None
                    returned=True;continue
                if name=='b':
                    destination=self._branch_target(op)
                    if destination is None or not self._inside(destination&~1):return None
                    follow(address,destination&~1,released)
                    if op.condition!=14:follow(address,op.next_address,released)
                    continue
                if name in ('bl','blx'):
                    destination=self._branch_target(op)
                    if destination is None:return None
                    if self._inside(destination&~1):
                        # Follow nested long branches through loop conditions
                        # and bodies. The same graph proof still rejects a
                        # new frame, LR return or inconsistent release; a
                        # straight-line epilogue is not required at each BL.
                        if released:return None
                        follow(address,destination&~1,released)
                    else:follow(address,op.next_address,released)
                    continue
                if name=='bx':return None
                delta=adjustment(op)
                if delta is not None:
                    if delta<0 or released+delta>allocation:return None
                    released+=delta
                else:
                    _,writes=op.detail.regs_access()
                    if any(op.detail.reg_name(r) in ('sp','r13') for r in writes):return None
                    if any(op.detail.reg_name(r) in ('pc','r15') for r in writes):
                        info=self._jump_table_info(op)
                        if info is None or not info.get('guard'):return None
                        tables.append((address,info['guard']))
                        for _,destination in info['cases']:
                            if not self._inside(destination):return None
                            follow(address,destination,released)
                        continue
                follow(address,op.next_address,released)
            for dispatch,guard in tables:
                # No edge may enter between the range guard and its dispatch.
                # The table recognizer preserves the bounded key until its
                # verified address/offset construction. This excludes bypasses
                # and loops which invalidate the range on a later visit.
                # Entering the conditional branch without executing its CMP
                # would reuse unrelated flags and bypass the bound as well.
                if start==guard['address'] or any(destination==guard['address']
                        and source!=guard['compare'] for source,destination in edges):return None
                address=guard['fallthrough'];previous=guard['address'];predecessors={}
                while address<=dispatch:
                    if address not in self.insns:return None
                    predecessors[address]=previous
                    previous,address=address,self.insns[address].next_address
                if dispatch not in predecessors or start in predecessors:return None
                if any(destination in predecessors and source!=predecessors[destination]
                       for source,destination in edges):return None
            return sites if returned else None
        epilogue_sites=epilogue(module,target,end)
        if epilogue_sites is None and module is self.module:epilogue_sites=body_exit(target)
        if epilogue_sites is None:return False
        stack_writes=[]
        for other in self.insns.values():
            _,writes=other.detail.regs_access()
            if any(other.detail.reg_name(r) in ('sp','r13') for r in writes):stack_writes.append(other)
        # Other branches may return through equivalent inline epilogues. Prove
        # each whole release/POP path before allowing its stack writes; a POP
        # by itself is not evidence that the local frame was restored.
        for other in stack_writes:
            if other.address in prologue_sites or other.address in epilogue_sites:continue
            delta=adjustment(other)
            if (delta is not None and delta>=0) or (allocation==0 and cls._branch_name(other)=='pop'):
                sites=epilogue(self.module,other.address,self.end)
                if sites is not None:epilogue_sites.update(sites)
        return all(op.address in prologue_sites or op.address in epilogue_sites for op in stack_writes)

    def discover(self):
        leaders=set(self.leaders);loops=set(self.loop_headers);stats=dict(self.stats)
        discover_source(self)
        # Establish the frame proof against the complete first-pass graph.
        # Revisit reachability without following a proven tail's return address;
        # literal words after it must never become executable instructions.
        tails={op.address for op in self.insns.values() if cls._branch_name(op)=='bl'
               and (target:=self._branch_target(op)) is not None and shared_exit(self,op,target)}
        self._decomp_tail_exits=tails
        if not tails or self.dispatch_entries is not None:return
        name=self._branch_name;manual=self._manual_link
        self.insns.clear();self.leaders=leaders;self.loop_headers=loops
        self.stats.clear();self.stats.update(stats)
        self._branch_name=lambda op:'b' if op.address in tails else name(op)
        self._manual_link=lambda op:None if op.address in tails else manual(op)
        try:discover_source(self)
        finally:self._branch_name=name;self._manual_link=manual

    def emit_branch(self,insn):
        if insn.address in getattr(self,"_decomp_tail_exits",set()):
            target=self._branch_target(insn)
            if self.dispatch_entries is None or not self._inside(target&~1):
                link=insn.next_address|1
                if self._inside(target&~1):
                    body=f'goto L_{target&~1:08x};'
                else:
                    body=self._call_direct(insn,target,tail=True)
                    if body is None:
                        self.stats['dsr_call_sites']+=1
                        body=f'::dsr::dsr_call(c, 0x{target|1:08x}u);\nreturn;'
                # BL still sets LR, but the consumed frame belongs to our
                # caller. A returning-call check against BL+4 is incorrect.
                return f'c->r[14] = 0x{link:08x}u;\n'+body
        return branch(self,insn)

    def count(self,insn,index_reg,default):
        if not insn.thumb:
            return original(self,insn,index_reg,default)
        previous=self._preceding(insn,20)
        register,base=index_reg,0
        saw_guard=False
        for position in range(len(previous)-1,-1,-1):
            prior=previous[position];name=self._branch_name(prior).rstrip('s');ops=prior.operands
            if name=='sub' and prior.condition==14 and base==0 and len(ops)==3 and \
                    ops[0].type==ARM_OP_REG and emitter.operand_reg(prior,ops[0])==register and \
                    ops[1].type==ARM_OP_REG and ops[2].type==ARM_OP_IMM:
                register,base=emitter.operand_reg(prior,ops[1]),emitter._immediate_value(prior,ops[2])
                continue
            if name!='cmp' or len(ops)!=2 or ops[0].type!=ARM_OP_REG or ops[1].type!=ARM_OP_IMM or \
                    emitter.operand_reg(prior,ops[0])!=register:
                continue
            # A guard consumes these flags before another flag-writing op.
            guard=None
            for following in previous[position+1:]:
                if self._branch_name(following)=='b' and following.condition!=14:
                    guard=following.condition;break
                if following.update_flags:break
            if guard==11 and int(ops[1].imm)==0:  # signed negative-index guard
                saw_guard=True
                continue
            if saw_guard and guard in (2,8,10,12):  # >= or > takes the out-of-range path
                bound=int(ops[1].imm)-base+(guard in (8,12))
                return min(256,max(0,bound))
        if saw_guard:
            return min(256,max(0,default)) if default is not None else None
        return original(self,insn,index_reg,default)

    cls._jump_case_count=count
    cls._slot_for=overlay_slot
    cls._jump_table_info=bounded_arm_table
    cls._branch=emit_branch
    cls._discover=discover
    emitter._secondary_branch_entries=secondary_entries
    from .wider_table import make
    cls._thumb_halfword_table_info=make(emitter)
    cls._decomp_bounds_fixed=True
