//! Original module/ABI qualification. Not a retail or gameplay acceptance tool.
use std::{ffi::c_void,ptr::addr_of};
use zakuro_core::{loader,Config,memory::{MemoryState,Permission}};

include!("identity.rs");
extern "C" {
    static recomp_abi:u32;
    static recomp_generation:u32;
    static recomp_entry_count:u32;
    static recomp_entries:u8;
    static recomp_module_count:u32;
    static recomp_modules:u8;
    static recomp_origins:u8;
}

fn run()->Result<(),Box<dyn std::error::Error>> {
    let args=std::env::args().skip(1).collect::<Vec<_>>();
    if args==["--vblank-wake"] {
        use zakuro_core::{System,StepOutcome,CYCLES_PER_FRAME,kernel::{sync::ResetType,thread::{ThreadStatus,THREAD_EXIT_MAGIC}}};
        let mut system=System::new(Config {clock:Some(0),..Config::default()});
        let address=0x10002000;
        system.memory.map(address,0x26000000,0x1000,Permission::RW,MemoryState::Code);
        let (event,_)=system.kernel.create_event(ResetType::OneShot,"original vblank waiter");
        system.services.gsp.shared_memory_address=address;
        system.services.gsp.interrupt_event_object=Some(event);
        let waiter=system.kernel.create_thread("original vblank waiter",THREAD_EXIT_MAGIC,0,0,0x20,0);
        let thread=system.kernel.thread_mut(waiter);
        thread.status=ThreadStatus::WaitSync;thread.wait_objects=vec![event];
        let deadline=CYCLES_PER_FRAME*8;
        if system.step(Some(deadline))!=StepOutcome::Ran || system.cpu.cycles!=CYCLES_PER_FRAME {
            return Err(format!("blocked CPU skipped vertical blank: tick {} instead of {}",system.cpu.cycles,CYCLES_PER_FRAME).into());
        }
        if system.step(Some(deadline))!=StepOutcome::Ran || system.frames!=1
            || system.kernel.thread(waiter).status!=ThreadStatus::Dead {
            return Err("vertical blank failed to wake the blocked original thread".into());
        }
        println!("{}",serde_json::json!({"schema":"decomp.wtf.3ds-vblank-wake/v1","passed":true,
            "frames":system.frames,"interpreted_instructions":system.interpreted_instructions}));
        return Ok(());
    }
    if args.len()==2 && args[0]=="--gsp-reopen" {
        use zakuro_core::kernel::{ipc::{CommandBuffer,Header,Descriptor},sync::ResetType};
        let mut system=loader::load(&args[1],Config {find_recompiled:false,clock:Some(0),..Config::default()})?;
        system.kernel.schedule(&mut system.cpu,0);
        let command=CommandBuffer::new(system.cpu.cp15.thread_id_ro);
        let (_event,event_handle)=system.kernel.create_event(ResetType::OneShot,"original GSP event");
        let register=|system:&mut zakuro_core::System|->Result<u32,Box<dyn std::error::Error>> {
            let header=Header::new(0x0013,1,2);
            for (i,v) in [header.0,0,Descriptor::handles(1),event_handle].into_iter().enumerate() {command.set(&mut system.memory,i as u32,v);}
            if !zakuro_core::services::gsp::handle(system,&command,header) {return Err("GSP registration is unimplemented".into());}
            Ok(command.get(&mut system.memory,4))
        };
        let first=register(&mut system)?;
        let original=system.kernel.resolve(first).ok_or("initial GSP shared memory is invalid")?;
        if !system.kernel.handles.close(&mut system.kernel.objects,first) {return Err("failed to close the original GSP handle".into());}
        let second=register(&mut system)?;
        let reopened=system.kernel.resolve(second).ok_or("registration reused a closed GSP shared-memory handle")?;
        if reopened!=original {return Err("GSP lost its service-owned shared memory across client closure".into());}
        println!("{}",serde_json::json!({"schema":"decomp.wtf.3ds-gsp-reopen/v1","passed":true,"reopened":true,
            "interpreted_instructions":system.interpreted_instructions}));
        return Ok(());
    }
    if args.len()==2 && args[0]=="--empty-cecd" {
        use zakuro_core::kernel::ipc::{CommandBuffer,Header};
        let mut system=loader::load(&args[1],Config {find_recompiled:false,clock:Some(0),..Config::default()})?;
        system.kernel.schedule(&mut system.cpu,0);
        let command=CommandBuffer::new(system.cpu.cp15.thread_id_ro);
        let address=0x02000000;
        system.memory.map(address,0x26000000,0x1000,Permission::RW,MemoryState::Code);
        system.memory.write_bytes(address,&[0xa5;16]);
        for (path_type,size,descriptor,expected) in [(1,16,0x10c,0xc8810bef),
            (10,16,0x10c,0xc8810bea),(1,0x100001,0x10c,0xe0e10bec),
            (1,16,0x10a,0xe0e10bec)] {
            let header=Header::new(0x0012,4,4);
            let request=[header.0,size,0x0ff3de00,path_type,1,0x20,0,descriptor,address];
            for (index,value) in request.into_iter().enumerate() {
                command.set(&mut system.memory,index as u32,value);
            }
            if !zakuro_core::services::cecd::handle(&mut system,&command,header) {
                return Err("empty CECD read remained unimplemented".into());
            }
            if command.get(&mut system.memory,0)!=Header::new(0x0012,2,2).0
                || command.get(&mut system.memory,1)!=expected
                || command.get(&mut system.memory,2)!=0
                || command.get(&mut system.memory,3)!=descriptor
                || command.get(&mut system.memory,4)!=address {
                return Err("empty CECD reply lost its result or mapped buffer".into());
            }
            let mut actual=[0;16];system.memory.read_bytes(address,&mut actual);
            if actual!=[0xa5;16] {return Err("empty CECD read changed guest storage".into());}
        }
        println!("{{\"schema\":\"decomp.wtf.3ds-empty-cecd/v1\",\"passed\":true,\"cases\":4,\"interpreted_instructions\":0,\"guest_buffer_preserved\":true}}");
        return Ok(());
    }
    if args.len()==4 && args[0]=="--save" {
        let raw=std::fs::read(&args[2])?;
        if raw.len()>0x1000 || raw.get(0x80..0x84)!=Some(b"CRO0") {
            return Err("save fixture expects its original one-page module".into());
        }
        let linked=unsafe {zakuro_core::recompiled::Linked::new(TITLE_ID,recomp_abi,
            addr_of!(recomp_entries) as *const c_void,recomp_entry_count,
            addr_of!(recomp_modules) as *const c_void,recomp_module_count)
            .with_origins(recomp_generation,addr_of!(recomp_origins) as *const c_void)};
        let mut system=loader::load(&args[1],Config {linked:Some(linked),find_recompiled:false,
            strict_static:true,data_dir:Some((&args[3]).into()),clock:Some(0),..Config::default()})?;
        let base=0x02000000;
        system.memory.map(base,0x26000000,0x1000,
            Permission::RW|Permission::EXECUTE,MemoryState::Code);
        system.memory.write_bytes(base,&raw);
        let library=system.recompiled.as_mut().ok_or("save fixture has no linked C")?;
        library.forbid_fallback=true;
        library.place("OriginalSave",base,&mut system.memory);
        if !library.has_code(base+0x200) {return Err("save fixture has no translated entry".into());}
        // Select the loaded main thread before replacing its entry. Subsequent
        // asynchronous filesystem waits use the ordinary kernel scheduler.
        system.kernel.schedule(&mut system.cpu,0);
        system.cpu.regs[15]=base+0x200;
        system.cpu.cpsr.thumb=false;
        while system.cpu.cycles<10_000_000 {
            if !matches!(system.step(Some(10_000_000)),zakuro_core::StepOutcome::Ran) {break;}
        }
        let library=system.recompiled.as_ref().unwrap();
        let interpreted=system.interpreted_instructions+library.fallbacks();
        if !system.exited || system.cpu.regs[0]!=0 || interpreted!=0 || library.rejected.get().is_some()
            || !system.static_misses.is_empty() || !system.unimplemented_svcs.is_empty()
            || !system.services.unimplemented.is_empty() {
            return Err(format!("save fixture failed: exit={}, r0={:X}, pc={:X}, misses={:?}",
                system.exited,system.cpu.regs[0],system.cpu.regs[15],system.static_misses).into());
        }
        println!("{}",serde_json::json!({"schema":"decomp.wtf.3ds-save-fixture/v1","passed":true,
            "counter":system.cpu.regs[1],"native_instructions":system.recompiled_instructions,
            "interpreted_instructions":interpreted,"retail_qualified":false}));
        return Ok(());
    }
    if args.len()==3 && args[0]=="--loaded-code" {
        let expected=std::fs::read(&args[2])?;
        let mut system=loader::load(&args[1],Config {find_recompiled:false,clock:Some(0),..Config::default()})?;
        let title=system.title.as_ref().ok_or("fixture title was not loaded")?;
        if title.code()?!=expected {return Err("runtime and exporter decompressed code differ".into());}
        let ex=&title.exheader;
        let rows=[(ex.text,0),(ex.rodata,ex.text.num_pages as usize*0x1000),
            (ex.data,(ex.text.num_pages+ex.rodata.num_pages) as usize*0x1000)];
        for (segment,offset) in rows {
            let mut actual=vec![0;segment.size as usize];
            system.memory.read_bytes(segment.address,&mut actual);
            if actual!=expected[offset..offset+actual.len()] {return Err("loaded executable memory differs".into());}
        }
        println!("{{\"schema\":\"decomp.wtf.3ds-loaded-code/v1\",\"passed\":true,\"interpreted_instructions\":0}}");
        return Ok(());
    }
    if args.len()!=3 {return Err("usage: ctr_module_scenes ORIGINAL_FIXTURE MODULE_FILE MODULE_NAME".into());}
    let raw=std::fs::read(&args[1])?;
    if raw.len()>0x1000 || raw.get(0x80..0x84)!=Some(b"CRO0") {
        return Err("this original-fixture check accepts a one-page CRO".into());
    }
    let module=&args[2];
    let thumb=module=="OriginalThumb";
    let linked=unsafe {zakuro_core::recompiled::Linked::new(TITLE_ID,recomp_abi,
        addr_of!(recomp_entries) as *const c_void,recomp_entry_count,
        addr_of!(recomp_modules) as *const c_void,recomp_module_count)
        .with_origins(recomp_generation,addr_of!(recomp_origins) as *const c_void)};
    let mut system=loader::load(&args[0],Config {linked:Some(linked),find_recompiled:false,
        strict_static:true,clock:Some(0),..Config::default()})?;
    let library=system.recompiled.as_mut().ok_or("no linked library")?;
    library.forbid_fallback=true;
    let mut previous=None;
    for (index,base) in [0x02000000u32,0x03000000].into_iter().enumerate() {
        system.memory.map(base,0x26000000+index as u32*0x1000,0x1000,
            Permission::RW|Permission::EXECUTE,MemoryState::Code);
        system.memory.write_bytes(base,&raw);
        library.place(module,base,&mut system.memory);
        let entry=base+0x200+thumb as u32;
        if !library.has_code(entry) {return Err("relocated module has no translated entry".into());}
        if previous.is_some_and(|old|library.has_code(old)) {return Err("relocated module retained its old entry".into());}
        system.cpu.regs[0]=0;
        system.cpu.regs[14]=0x04000000;
        system.cpu.regs[15]=entry & !1;
        system.cpu.cpsr.thumb=thumb;
        let (ran,_)=library.run(&mut system.cpu,&mut system.memory,100);
        if ran!=2 || system.cpu.regs[0]!=42 || library.fallbacks()!=0 || library.rejected.get().is_some() {
            return Err("relocated ARM/Thumb C did not execute independently".into());
        }
        // Rechecking executable provenance must invalidate the compiled code
        // before a changed module is eligible to run.
        system.memory.write_bytes(base+0x200,&[0xff,0xff,0xff,0xff]);
        library.place(module,base,&mut system.memory);
        if library.has_code(entry) {return Err("modified module retained a translated entry".into());}
        // A clean module can be loaded again and then unloaded completely.
        system.memory.write_bytes(base,&raw);
        library.place(module,base,&mut system.memory);
        if !library.has_code(entry) {return Err("clean module failed to reload".into());}
        previous=Some(entry);
    }
    library.place(module,0,&mut system.memory);
    if previous.is_some_and(|at|library.has_code(at)) {return Err("unloaded module retained translated code".into());}
    println!("{}",serde_json::json!({"schema":"decomp.wtf.3ds-module-scenes/v1","module":module,
        "relocations":2,"native_instructions":4,"interpreted_instructions":library.fallbacks(),
        "provenance_checked":true,"unload_checked":true,"passed":true,"retail_qualified":false}));
    Ok(())
}

fn main() {
    if let Err(error)=run() {eprintln!("3DS module scenes: {error}");std::process::exit(1);}
}
