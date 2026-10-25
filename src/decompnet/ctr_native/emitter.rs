//! Dependency-free command adapter for the pinned MIT 3dsrecomp emitter.
//! The upstream source is copied to sdk/ in a separate build directory.
#[path = "sdk/src/arm.rs"] mod arm;
#[path = "sdk/src/thumb.rs"] mod thumb;
#[path = "sdk/src/rom.rs"] mod rom;
#[path = "sdk/src/image.rs"] mod image;
#[path = "sdk/src/discover.rs"] mod discover;
#[path = "sdk/src/overrides.rs"] mod overrides;
#[path = "sdk/src/codegen/mod.rs"] mod codegen;

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 4 || args[4..].iter().any(|a|a!="--instruction-boundaries" && a!="--analyze-only") {
        return Err("expected TEXT BASE SEEDS OUTPUT [--instruction-boundaries] [--analyze-only]".into());
    }
    let base: u32 = args[1].parse()?;
    let bytes = std::fs::read(&args[0])?;
    let seeds = std::fs::read_to_string(&args[2])?.lines().enumerate()
        .map(|(i,line)| line.parse::<u32>().map(|at| (at,
            if i==0 {discover::Source::Entry} else {discover::Source::Pointer})))
        .collect::<Result<Vec<_>, _>>()?;
    let program = discover::Program { text: image::Segment { base, bytes }, seeds, slots: None };
    let mut analysis = discover::analyze(&program);
    if args[4..].iter().any(|a|a=="--instruction-boundaries") {
        // The scheduler may yield at any guest instruction. Make every point
        // resumable so short event budgets never need interpreter assistance.
        for function in analysis.functions.values_mut() {
            function.labels.extend(function.instructions.iter().copied());
        }
    }
    if analysis.functions.is_empty() { return Err("no ARM/Thumb functions discovered".into()); }
    let output = std::path::Path::new(&args[3]);
    std::fs::create_dir_all(output)?;
    if !args[4..].iter().any(|a|a=="--analyze-only") {
        let unit = codegen::Unit { module: None, program: &program, analysis: &analysis };
        for (name, source) in codegen::generate(&[unit], &[]) {
            std::fs::write(output.join(name), source)?;
        }
    }
    let mut report = format!("functions={}\n", analysis.functions.len());
    for (entry, function) in &analysis.functions {
        report.push_str(&format!("{entry:08x},{:?},{}\n", function.mode, function.instructions.len()));
    }
    std::fs::write(output.join("functions.csv"), report)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("3DS source generation: {error}"); std::process::exit(1); }
}
