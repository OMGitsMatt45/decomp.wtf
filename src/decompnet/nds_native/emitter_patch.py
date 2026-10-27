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
        prologue=self.decoder.decode(self.begin)
        if prologue is None or cls._branch_name(prologue)!='push' or prologue.condition!=14:return False
        saved={emitter.operand_reg(prologue,op) for op in prologue.operands if op.type==ARM_OP_REG}
        if 14 not in saved:return False
        expected=(saved-{14})|{15}
        allocation=0;prologue_sites={self.begin};address=prologue.next_address
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
        epilogue_sites=epilogue(module,target,end)
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
        result=branch(self,insn)
        if result is None or not insn.thumb or self._branch_name(insn)!='bl':return result
        target=self._branch_target(insn)
        if target is None or (self.dispatch_entries is not None and self._inside(target&~1)):return result
        if insn.address in getattr(self,"_decomp_tail_exits",set()):
            return result+'\nreturn;'
        return result

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
