//! Dependency-free command adapter for the pinned MIT 3dsrecomp emitter.
//! The upstream source is copied to sdk/ in a separate build directory.
#[path = "sdk/src/arm.rs"] mod arm;
#[path = "sdk/src/thumb.rs"] mod thumb;
#[path = "sdk/src/rom.rs"] mod rom;
#[path = "sdk/src/image.rs"] mod image;
#[path = "sdk/src/discover.rs"] mod discover;
#[path = "sdk/src/overrides.rs"] mod overrides;
#[path = "sdk/src/codegen/mod.rs"] mod codegen;
#[path = "sdk/src/cro.rs"] mod cro;
#[cfg(test)]
#[path = "sdk/src/compile.rs"] mod compile;

fn imported(modules:&[(cro::Module,Vec<u8>)], crs:Option<&cro::Module>, target:&cro::Module)->Vec<u32> {
    modules.iter().map(|(module,_)|module).chain(crs)
        .flat_map(|module|&module.anonymous_imports)
        .filter(|(name,_)|*name==target.name)
        .filter_map(|(_,tag)|target.code_address(*tag)).collect()
}

/// ARM linker veneers compute a Thumb entry without storing a pointer literal.
/// Recognize the complete ADD Rd,pc,#odd / BX Rd pair; never scan arbitrary words
/// as Thumb function pointers. Apply this to main text and relocated modules.
fn interworking(program:&mut discover::Program) {
    let text=&program.text;
    for offset in (0..text.bytes.len().saturating_sub(7)).step_by(4) {
        let first=u32::from_le_bytes(text.bytes[offset..offset+4].try_into().unwrap());
        let second=u32::from_le_bytes(text.bytes[offset+4..offset+8].try_into().unwrap());
        let register=(first>>12)&15;
        if first&0xffff0000==0xe28f0000 && register!=15 && second==(0xe12fff10|register) {
            let immediate = (first & 255).rotate_right(((first >> 8) & 15) * 2);
            if let Some(target) = text.base.checked_add((offset+8) as u32).and_then(|pc| pc.checked_add(immediate)) {
                if target & 1 != 0 && text.read16(target & !1).is_some() {
                    program.seeds.push((target,discover::Source::Hint));
                }
            }
        }
    }
}

/// Accept only unconditional data processing instructions that leave the
/// table base intact while the caller prepares the index or return address.
fn preserves_arm_table_base(word: u32, base: u32) -> bool {
    let destination = (word >> 12) & 15;
    word & 0xfc100000 == 0xe0000000
        && (word & (1 << 25) != 0 || word & 16 == 0)
        && matches!((word >> 21) & 15, 0 | 2 | 4 | 13)
        && destination != base && destination != 15
}

/// Read a backward ARM jump table addressed by ADR, LDR (scaled index),
/// and ADD PC. The index calculation can separate ADR from the load.
fn arm_relative_targets(text: &image::Segment, function: &discover::Function, pc: u32) -> Option<Vec<u32>> {
    let branch = text.read32(pc)?;
    if branch & 0xfff0fff0 != 0xe080f000 { return None; }
    let left = (branch >> 16) & 15;
    let right = branch & 15;
    let preceding = |at: u32| {
        let address = at.checked_sub(4)?;
        function.instructions.binary_search(&address).ok()?;
        Some((address, text.read32(address)?))
    };
    let (mut load_pc, mut load) = preceding(pc)?;
    let written = (load >> 12) & 15;
    if load & 0xffff0ff0 == 0xe1a00000 && written != 15 && written != left && written != right {
        (load_pc, load) = preceding(load_pc)?;
    }
    if load & 0xfff00ff0 != 0xe7900100 || load & 15 == 15 { return None; }
    let base = (load >> 16) & 15;
    let offset = (load >> 12) & 15;
    if base == offset || base == 15 || offset == 15
        || !((left == base && right == offset) || (left == offset && right == base)) {
        return None;
    }
    let (mut adr_pc, mut adr) = preceding(load_pc)?;
    for _ in 0..12 {
        if !preserves_arm_table_base(adr, base) { break; }
        (adr_pc, adr) = preceding(adr_pc)?;
    }
    if (adr >> 12) & 15 != base { return None; }
    let distance = (adr & 255).rotate_right(((adr >> 8) & 15) * 2);
    // A backward table has a structural upper bound at its ADR instruction.
    let table = match adr >> 16 {
        0xe24f => (adr_pc + 8).checked_sub(distance)?,
        _ => return None,
    };
    if table % 4 != 0 || table >= adr_pc { return None; }
    let mut targets = Vec::new();
    let mut table_end = adr_pc;
    for slot in (table..adr_pc).step_by(4).take(256) {
        if slot >= table_end { break; }
        let word = text.read32(slot)?;
        // Once a forward case bounds the table, a zero slot can be padding
        // for an unused case without terminating discovery of later entries.
        if word == 0 && table_end < adr_pc { continue; }
        let target = table.wrapping_add(word);
        if target % 4 != 0 || (table..=slot).contains(&target) || text.read32(target).is_none() {
            break;
        }
        if target > slot { table_end = table_end.min(target); }
        targets.push(target);
    }
    (targets.len() >= 3).then_some(targets)
}

/// A speculative literal can hide an ARM loop's back edge, or a register
/// initialization immediately before it. Recover the tail only when ARM
/// fallthrough reaches it and the branch rejoins the same decoded function.
/// A relocation is authoritative evidence of data.
fn recover_arm_loop_edges(program: &discover::Program, analysis: &mut discover::Analysis) {
    use arm::{Flow, ALWAYS};
    use discover::{Byte, Mode};

    let text = &program.text;
    let mut recovered = Vec::new();
    for function in analysis.functions.values_mut().filter(|f| f.mode == Mode::Arm) {
        let mut edges = Vec::new();
        for &previous in &function.instructions {
            let at = previous + 4;
            let offset = (at - text.base) as usize;
            if analysis.map.get(offset..offset + 4) != Some(&[Byte::Literal; 4]) {
                continue;
            }
            let Some(word) = text.read32(at) else { continue; };
            // MOV immediate, unconditional, leaving CPSR and PC intact.
            let initializes_register = word & 0xffff_0000 == 0xe3a0_0000
                && word & 0x0000_f000 != 0x0000_f000;
            let branch_at = if initializes_register { at + 4 } else { at };
            if program.slots.as_ref().is_some_and(|slots| slots.contains(&at) || slots.contains(&branch_at)) {
                continue;
            }
            let before = arm::decode(text.read32(previous).unwrap(), previous);
            if before.flow != Flow::Other {
                continue;
            }
            let Some(word) = text.read32(branch_at) else { continue; };
            let branch = arm::decode(word, branch_at);
            if let Flow::Branch { target, link: false } = branch.flow {
                if branch.condition == ALWAYS && target <= previous && function.instructions.binary_search(&target).is_ok() {
                    edges.extend((at..=branch_at).step_by(4));
                    function.labels.insert(target);
                    recovered.extend((offset..=offset + (branch_at - at) as usize).step_by(4));
                }
            }
        }
        if !edges.is_empty() {
            function.instructions.extend(edges);
            function.instructions.sort_unstable();
        }
    }
    for offset in recovered {
        analysis.map[offset..offset + 4].fill(Byte::Code);
    }
}

/// Speculative Thumb literals can also split an ARM compare and forward
/// conditional branch from the already decoded continuation. Both successors
/// must be in the contiguous ARM fragment that follows the missing word.
fn recover_arm_conditional_edges(program: &discover::Program, analysis: &mut discover::Analysis) {
    use arm::{Flow, ALWAYS};
    use discover::{Byte, Mode};

    let text = &program.text;
    let edges = analysis.functions.iter().filter_map(|(&entry, function)| {
        if function.mode != Mode::Arm { return None; }
        let compare = *function.instructions.last()?;
        if text.read32(compare)? & 0xfff0_0000 != 0xe350_0000 { return None; }
        let branch = compare + 4;
        let offset = (branch - text.base) as usize;
        if analysis.map.get(offset..offset + 4)? != [Byte::Literal; 4]
            || program.slots.as_ref().is_some_and(|slots| slots.contains(&branch)) {
            return None;
        }
        let fallthrough = branch + 4;
        let continuation = analysis.functions.get(&fallthrough)?;
        if continuation.mode != Mode::Arm || continuation.instructions.first() != Some(&fallthrough) {
            return None;
        }
        let decoded = arm::decode(text.read32(branch)?, branch);
        let Flow::Branch { target, link: false } = decoded.flow else { return None; };
        (decoded.condition < ALWAYS && target > fallthrough
            && continuation.instructions.binary_search(&target).is_ok()).then_some((entry, branch, offset))
    }).collect::<Vec<_>>();
    for (entry, branch, offset) in edges {
        analysis.functions.get_mut(&entry).unwrap().instructions.push(branch);
        analysis.map[offset..offset + 4].fill(Byte::Code);
    }
}

/// A speculative literal can cut a run of ARM VFP arithmetic in two. Recover
/// one word between decoded instructions when the following fragment is ARM
/// and all three words are unconditional VFP data operations.
fn recover_arm_vfp_gap(program: &discover::Program, analysis: &mut discover::Analysis) {
    use discover::{Byte, Mode};

    let text = &program.text;
    let is_vfp = |at| text.read32(at).is_some_and(|word| word & 0xff00_0e10 == 0xee00_0a00);
    let mut recovered = std::collections::BTreeMap::<u32, Vec<u32>>::new();
    for (&entry, function) in analysis.functions.iter().filter(|(_, function)| function.mode == Mode::Arm) {
        for &previous in &function.instructions {
            let at = previous + 4;
            let offset = (at - text.base) as usize;
            if analysis.map.get(offset..offset + 4) != Some(&[Byte::Literal; 4])
                || program.slots.as_ref().is_some_and(|slots| slots.contains(&at)) {
                continue;
            }
            let next = at + 4;
            if analysis.functions.get(&next).is_some_and(|continuation|
                continuation.mode == Mode::Arm && continuation.instructions.first() == Some(&next))
                && [previous, at, next].into_iter().all(is_vfp) {
                recovered.entry(entry).or_default().push(at);
            }
        }
    }
    for (entry, instructions) in recovered {
        let function = analysis.functions.get_mut(&entry).unwrap();
        for at in instructions {
            let offset = (at - text.base) as usize;
            analysis.map[offset..offset + 4].fill(Byte::Code);
            function.instructions.push(at);
        }
        function.instructions.sort_unstable();
    }
}

/// A decoded ARM call can distinguish a callee's stack prologue from a
/// speculative literal when the rest of the callee already decoded as ARM.
fn called_arm_prologue(program: &discover::Program, analysis: &discover::Analysis, pc: u32) -> Option<u32> {
    let word = program.text.read32(pc)?;
    if word >> 24 != 0xeb { return None; }
    let call = arm::decode(word, pc);
    let arm::Flow::Branch { target, link: true } = call.flow else { return None };
    let word = program.text.read32(target)?;
    // PUSH with LR and at least one general register, without SP or PC.
    if word & 0xffff_e000 != 0xe92d_4000 || word & 0x1fff == 0 {
        return None;
    }
    let offset = target.checked_sub(program.text.base)? as usize;
    if analysis.map.get(offset..offset + 4)? != [discover::Byte::Literal; 4]
        || program.slots.as_ref().is_some_and(|slots| slots.contains(&target))
    {
        return None;
    }
    let next = target.checked_add(4)?;
    let continuation = analysis.functions.get(&next)?;
    (continuation.mode == discover::Mode::Arm && continuation.instructions.first() == Some(&next))
        .then_some(target)
}

/// Recover Thumb PIC callback pointers only from decoded instruction paths.
/// LDR Rt,[pc,#literal] followed by ADD Rt,pc may have preserving stores between
/// them. A branch, a write to Rt or an unknown gap ends the candidate.
fn analyze(program:&mut discover::Program)->Result<discover::Analysis,&'static str> {
    interworking(program);
    for _ in 0..8 {
        let mut analysis=discover::analyze(program);
        let text=&program.text;
        let hints=program.seeds.iter().filter_map(|(at,source)|(*source==discover::Source::Hint).then_some(*at))
            .collect::<std::collections::BTreeSet<_>>();
        let mut found=std::collections::BTreeSet::new();
        for function in analysis.functions.values().filter(|f| f.mode == discover::Mode::Arm) {
            for &pc in &function.instructions {
                if let Some(target) = called_arm_prologue(program, &analysis, pc) {
                    if !hints.contains(&target) { found.insert(target); }
                }
                if let Some(targets) = arm_relative_targets(text, function, pc) {
                    found.extend(targets.into_iter().filter(|at| !hints.contains(at)
                        && !analysis.functions.get(at).is_some_and(|f| f.mode == discover::Mode::Arm && !f.instructions.is_empty())));
                }
            }
        }
        for function in analysis.functions.values().filter(|f|f.mode==discover::Mode::Thumb) {
            for &pc in &function.instructions {
                let Some(op)=text.read16(pc) else {continue;};
                if op&0xf800!=0x4800 {continue;}
                let register=(op>>8)&7;
                let Some(literal)=(pc+4 & !3).checked_add(u32::from(op&255)*4) else {continue;};
                let Some(relative)=text.read32(literal) else {continue;};
                for delta in [2,4,6,8] {
                    let at=pc+delta;
                    if function.instructions.binary_search(&at).is_err() {break;}
                    let Some(next)=text.read16(at) else {break;};
                    if next==0x4478|register {
                        let target=at.wrapping_add(4).wrapping_add(relative);
                        if target&1!=0 && text.contains(target&!1) && !hints.contains(&target)
                            && !analysis.functions.get(&(target&!1)).is_some_and(|f|f.mode==discover::Mode::Thumb) {
                            found.insert(target);
                        }
                        break;
                    }
                    let store=matches!(next&0xf800,0x6000|0x7000|0x8000|0x9000);
                    let other_immediate=next&0xf800==0x2000 && (next>>8)&7!=register;
                    let other_literal=next&0xf800==0x4800 && (next>>8)&7!=register;
                    if !store && !other_immediate && !other_literal && !matches!(next,0x46c0|0xbf00) {break;}
                }
            }
        }
        if found.is_empty() {
            recover_arm_loop_edges(program, &mut analysis);
            recover_arm_conditional_edges(program, &mut analysis);
            recover_arm_vfp_gap(program, &mut analysis);
            return Ok(analysis);
        }
        program.seeds.extend(found.into_iter().map(|at|(at,discover::Source::Hint)));
    }
    Err("position-independent target discovery exceeded eight passes")
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    // Qualification uses the pinned independent decoder as an oracle for the
    // Python importer, including real executable bytes and overlapping runs.
    if args.len()==3 && args[0]=="--decode-blz" {
        let raw=std::fs::read(&args[1])?;
        if raw.len()<8 || raw.len()>64*1024*1024 {return Err("BLZ input exceeds its bound".into());}
        let extra=u32::from_le_bytes(raw[raw.len()-4..].try_into()?) as usize;
        if extra>64*1024*1024-raw.len() {return Err("BLZ output exceeds its bound".into());}
        if std::path::Path::new(&args[2]).exists() {return Err("preserve the existing decoder output".into());}
        std::fs::write(&args[2],rom::decompress(&raw)?)?;
        return Ok(());
    }
    if args.len()<4 {return Err("expected TEXT BASE SEEDS OUTPUT [--instruction-boundaries] [--analyze-only] [--modules DIRECTORY]".into());}
    let (mut boundaries,mut analyze_only,mut measure,mut directory)=(false,false,false,None);
    let mut options=args[4..].iter();
    while let Some(option)=options.next() {
        match option.as_str() {
            "--instruction-boundaries"=>boundaries=true,
            "--analyze-only"=>analyze_only=true,
            "--measure-output"=>measure=true,
            "--modules"=>directory=Some(options.next().ok_or("--modules needs a directory")?),
            _=>return Err(format!("unknown emitter option: {option}").into()),
        }
    }
    let base: u32 = args[1].parse()?;
    let bytes = std::fs::read(&args[0])?;
    let mut seeds = std::fs::read_to_string(&args[2])?.lines().enumerate()
        .map(|(i,line)| {
            let (value,source)=if let Some(value)=line.strip_prefix("hint:") {
                (value,discover::Source::Hint)
            } else {(line,if i==0 {discover::Source::Entry} else {discover::Source::Pointer})};
            value.parse::<u32>().map(|at|(at,source))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let (mut modules,mut crs)=(Vec::new(),None);
    if let Some(directory)=directory {
        let mut paths=std::fs::read_dir(directory)?.map(|p|p.map(|p|p.path())).collect::<Result<Vec<_>,_>>()?;
        paths.sort();
        for path in paths {
            let extension=path.extension().and_then(|e|e.to_str()).unwrap_or("");
            if !matches!(extension,"cro"|"crs") {continue;}
            let raw=std::fs::read(&path)?;
            let module=cro::parse(&raw).ok_or_else(||format!("invalid CRO/CRS structure: {}",path.display()))?;
            // The pinned code generator writes module names in C strings.
            if module.name.is_empty() || module.name.len()>255 || !module.name.bytes().all(|b|b.is_ascii_graphic() && b!=b'"' && b!=b'\\') {
                return Err("CRO/CRS has an unsupported module name".into());
            }
            if extension=="crs" {
                if crs.is_some() {return Err("multiple static CRS descriptions are not supported".into());}
                crs=Some(module);
            } else {
                if let Some((_,other))=modules.iter().find(|(other,_):&&(cro::Module,Vec<u8>)|other.name==module.name) {
                    if *other==raw {continue;}
                    return Err("CRO module name has conflicting contents".into());
                }
                modules.push((module,raw));
            }
        }
    }
    if let Some(crs)=&crs {
        seeds.extend(crs.code_exports().into_iter().map(|at|(at,discover::Source::Export)));
        seeds.extend(imported(&modules,Some(crs),crs).into_iter().map(|at|(at,discover::Source::Import)));
    }
    let main=discover::Program {text:image::Segment {base,bytes},seeds,slots:None};
    let mut programs=vec![(None,main)];
    for (module,raw) in &modules {
        let program=module.program(raw,&imported(&modules,crs.as_ref(),module))
            .ok_or_else(||format!("CRO {} has no bounded executable segment",module.name))?;
        programs.push((Some(module.name.as_str()),program));
    }
    let mut analyses=programs.iter_mut().map(|(_,program)|analyze(program)).collect::<Result<Vec<_>,_>>()?;
    for analysis in &mut analyses {
        if boundaries {
            // Every scheduler boundary, including relocated modules, must be
            // resumable without interpretation.
            for function in analysis.functions.values_mut() {
                function.labels.extend(function.instructions.iter().copied());
            }
        }
        if analysis.functions.is_empty() {return Err("no ARM/Thumb functions discovered for an executable unit".into());}
    }
    let output = std::path::Path::new(&args[3]);
    std::fs::create_dir_all(output)?;
    if !analyze_only {
        let units=programs.iter().zip(&analyses).map(|((module,program),analysis)|codegen::Unit {module:*module,program,analysis}).collect::<Vec<_>>();
        let sources=codegen::generate(&units,&[]);
        if measure {
            eprintln!("generated_source_bytes={} files={}",sources.iter().map(|(_,s)|s.len()).sum::<usize>(),sources.len());
        } else {
            for (name,source) in sources {
                std::fs::write(output.join(name),source)?;
            }
        }
    }
    let mut report = format!("functions={}\n", analyses.iter().map(|a|a.functions.len()).sum::<usize>());
    for (index,analysis) in analyses.iter().enumerate() {
        for (entry,function) in &analysis.functions {
            report.push_str(&format!("{index}:{entry:08x},{:?},{}\n",function.mode,function.instructions.len()));
        }
    }
    std::fs::write(output.join("functions.csv"), report)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("3DS source generation: {error}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn called_arm_prologue_survives_a_competing_thumb_literal() {
        use discover::{Byte, Source};

        let base = 0x100000;
        let words: [u32; 8] = [
            0xe12fff1e, // bx lr
            0x47704803, // Thumb pointer guesses the callee's first word as data
            0xe320f000, // nop
            0xeb000000, // bl callee
            0xe12fff1e, // bx lr
            0xe92d4010, // push {r4, lr}
            0xe1a04000, // mov r4, r0
            0xe8bd8010, // pop {r4, pc}
        ];
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer),
                (base + 12, Source::Pointer), (base + 24, Source::Pointer)],
            slots: None,
        };
        let target = base + 20;
        let original = discover::analyze(&program);
        assert_eq!(original.map[20..24], [Byte::Literal; 4]);
        let repaired = analyze(&mut program).unwrap();
        assert!(repaired.functions[&target].instructions.contains(&target));

        program.seeds.retain(|(_, source)| *source != Source::Hint);
        program.slots = Some([target].into_iter().collect());
        let relocated = analyze(&mut program).unwrap();
        assert_eq!(relocated.map[20..24], [Byte::Literal; 4]);
    }

    #[test]
    fn arm_loop_edge_survives_a_competing_thumb_literal() {
        use discover::{Byte, Source};

        let base = 0x100000;
        let words: [u32; 8] = [
            0xe12fff1e, // ARM entry: bx lr
            0x47704804, // Thumb guess: ldr r0, [pc, #16]; bx lr
            0xe3500000, // cmp r0, #0
            0x0a000002, // beq exit
            0xe2400001, // sub r0, r0, #1
            0xe320f000, // nop
            0xeafffffa, // b loop (also the guessed Thumb literal)
            0xe12fff1e, // exit: bx lr
        ];
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer), (base + 8, Source::Pointer)],
            slots: None,
        };
        let branch = base + 24;
        let original = discover::analyze(&program);
        assert_eq!(original.map[24], Byte::Literal);
        assert!(!original.functions[&(base + 8)].instructions.contains(&branch));

        let repaired = analyze(&mut program).unwrap();
        assert!(repaired.functions[&(base + 8)].instructions.contains(&branch));
        assert_eq!(repaired.map[24], Byte::Code);

        program.slots = Some([branch].into_iter().collect());
        let with_relocation = analyze(&mut program).unwrap();
        assert_eq!(with_relocation.map[24], Byte::Literal);
        assert!(!with_relocation.functions[&(base + 8)].instructions.contains(&branch));
    }

    #[test]
    fn arm_loop_recovers_initialization_before_the_back_edge() {
        use discover::{Byte, Source};
        let base = 0x100000;
        let words: [u32; 9] = [
            0xe12fff1e, // bx lr
            0x47704804, // Thumb ldr uses the ARM mov at +24 as its literal
            0xe3500000, // cmp r0, #0
            0x0a000003, // beq exit
            0xe2400001, // sub r0, r0, #1
            0xe320f000, // nop
            0xe3a03000, // mov r3, #0
            0xeafffff9, // b loop
            0xe12fff1e, // exit: bx lr
        ];
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer), (base + 8, Source::Pointer)],
            slots: None,
        };
        let original = discover::analyze(&program);
        assert_eq!(original.map[24], Byte::Literal);
        let repaired = analyze(&mut program).unwrap();
        assert!(repaired.functions[&(base + 8)].instructions.contains(&(base + 24)));
        assert!(repaired.functions[&(base + 8)].instructions.contains(&(base + 28)));

        program.slots = Some([base + 24, base + 28].into_iter().collect());
        let relocated = analyze(&mut program).unwrap();
        assert_eq!(relocated.map[24..32], [Byte::Literal; 8]);
    }

    #[test]
    fn arm_loop_recovers_tail_after_last_decoded_instruction() {
        use discover::{Byte, Source};
        let base = 0x100000;
        let words: [u32; 9] = [
            0xe12fff1e, // bx lr
            0x47704804, // Thumb ldr uses the ARM mov at +24 as its literal
            0xe3500000, // cmp r0, #0
            0xe2400001, // sub r0, r0, #1
            0xe320f000, // nop
            0xe320f000, // last decoded instruction
            0xe3a03000, // mov r3, #0
            0xeafffff9, // b loop
            0xe12fff1e, // separate entry
        ];
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer),
                (base + 8, Source::Pointer), (base + 32, Source::Pointer)],
            slots: None,
        };
        let original = discover::analyze(&program);
        assert_eq!(original.map[24], Byte::Literal);
        assert_eq!(original.functions[&(base + 8)].instructions.last(), Some(&(base + 20)));

        let repaired = analyze(&mut program).unwrap();
        assert!(repaired.functions[&(base + 8)].instructions.ends_with(&[base + 24, base + 28]));
        assert_eq!(repaired.map[24..32], [Byte::Code; 8]);
    }

    #[test]
    fn forward_arm_conditional_edge_survives_a_competing_thumb_literal() {
        use discover::{Byte, Source};

        let base = 0x100000;
        let words: [u32; 8] = [
            0xe12fff1e, // ARM entry: bx lr
            0x47704801, // Thumb guess: ldr r0, [pc, #4]; bx lr
            0xe3500000, // cmp r0, #0
            0x0a000001, // beq to the addition
            0xe3a00029, // mov r0, #41
            0xe320f000, // nop
            0xe2800001, // add r0, r0, #1
            0xe12fff1e, // bx lr
        ];
        let branch = base + 12;
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer),
                (base + 8, Source::Pointer), (base + 16, Source::Pointer)],
            slots: None,
        };
        let original = discover::analyze(&program);
        assert_eq!(original.map[12], Byte::Literal);
        assert!(!original.functions[&(base + 8)].instructions.contains(&branch));

        let repaired = analyze(&mut program).unwrap();
        assert!(repaired.functions[&(base + 8)].instructions.contains(&branch));
        assert_eq!(repaired.map[12], Byte::Code);

        program.slots = Some([branch].into_iter().collect());
        assert_eq!(analyze(&mut program).unwrap().map[12], Byte::Literal);
    }

    #[test]
    fn arm_vfp_arithmetic_survives_a_competing_thumb_literal() {
        use discover::{Byte, Source};
        let base = 0x100000;
        let words: [u32; 6] = [
            0xe12fff1e, // bx lr
            0x47704801, // Thumb ldr reads the middle ARM VFP word as a literal
            0xee222a82,
            0xee621aa1,
            0xee752a86,
            0xe12fff1e, // bx lr
        ];
        let mut program = discover::Program {
            text: image::Segment { base, bytes: words.into_iter().flat_map(u32::to_le_bytes).collect() },
            seeds: vec![(base, Source::Entry), (base + 5, Source::Pointer),
                (base + 8, Source::Pointer), (base + 16, Source::Pointer)],
            slots: None,
        };
        let original = discover::analyze(&program);
        assert_eq!(original.map[12], Byte::Literal);
        let repaired = analyze(&mut program).unwrap();
        assert_eq!(repaired.functions[&(base + 8)].instructions, [base + 8, base + 12]);
        assert_eq!(repaired.map[12], Byte::Code);

        program.slots = Some([base + 12].into_iter().collect());
        assert_eq!(analyze(&mut program).unwrap().map[12], Byte::Literal);
    }
}
