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
