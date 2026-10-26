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

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
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
        .map(|(i,line)| line.parse::<u32>().map(|at| (at,
            if i==0 {discover::Source::Entry} else {discover::Source::Pointer})))
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
    let mut analyses=programs.iter().map(|(_,program)|discover::analyze(program)).collect::<Vec<_>>();
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
