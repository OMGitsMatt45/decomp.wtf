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

fn imported(modules:&[(cro::Module,Vec<u8>)], crs:Option<&cro::Module>, target:&cro::Module)->Vec<u32> {
    modules.iter().map(|(module,_)|module).chain(crs)
        .flat_map(|module|&module.anonymous_imports)
        .filter(|(name,_)|*name==target.name)
        .filter_map(|(_,tag)|target.code_address(*tag)).collect()
}

/// ARM linker veneers compute a Thumb entry without storing a pointer literal.
/// Recognize the complete ADD Rd,pc,#1 / BX Rd pair; never scan arbitrary words
/// as Thumb function pointers. Apply this to main text and relocated modules.
fn interworking(program:&mut discover::Program) {
    let text=&program.text;
    for offset in (0..text.bytes.len().saturating_sub(8)).step_by(4) {
        let first=u32::from_le_bytes(text.bytes[offset..offset+4].try_into().unwrap());
        let second=u32::from_le_bytes(text.bytes[offset+4..offset+8].try_into().unwrap());
        let register=(first>>12)&15;
        if first&0xffff0fff==0xe28f0001 && register!=15 && second==(0xe12fff10|register) {
            if let Some(target)=text.base.checked_add((offset+8) as u32) {
                program.seeds.push((target|1,discover::Source::Hint));
            }
        }
    }
}

/// Recover Thumb PIC callback pointers only from decoded instruction paths.
/// LDR Rt,[pc,#literal] followed by ADD Rt,pc may have preserving stores between
/// them. A branch, a write to Rt or an unknown gap ends the candidate.
fn analyze(program:&mut discover::Program)->Result<discover::Analysis,&'static str> {
    interworking(program);
    for _ in 0..8 {
        let analysis=discover::analyze(program);
        let text=&program.text;
        let hints=program.seeds.iter().filter_map(|(at,source)|(*source==discover::Source::Hint).then_some(*at))
            .collect::<std::collections::BTreeSet<_>>();
        let mut found=std::collections::BTreeSet::new();
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
        if found.is_empty() {return Ok(analysis);}
        program.seeds.extend(found.into_iter().map(|at|(at,discover::Source::Hint)));
    }
    Err("position-independent callback discovery exceeded eight passes")
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
