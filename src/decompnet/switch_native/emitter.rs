//! Small file-based adapter around the pinned nxport/LASRecomp lifter.
use nxport_lifter::{lift_module, Module, Options, RUNTIME_FILES};
use std::{collections::BTreeSet, env, fs, io::{self, BufRead}, path::PathBuf};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<String> = env::args().collect();
    let read_anchors = a.get(9).is_some_and(|arg| arg == "--anchor-origins");
    if a.len() != 8 && a.len() != 9 && !(a.len() == 10 && read_anchors) {
        return Err("usage: emitter image base text-offset text-size entries output report [module-name [--anchor-origins]]".into());
    }
    let image = fs::read(&a[1])?;
    let base: u64 = a[2].parse()?;
    let offset: u64 = a[3].parse()?;
    let size: u64 = a[4].parse()?;
    if size == 0 || size % 4 != 0 || offset + size > image.len() as u64 {
        return Err("invalid executable range".into());
    }
    let seeds: BTreeSet<u64> = fs::read_to_string(&a[5])?
        .lines().map(str::parse).collect::<Result<_, _>>()?;
    if seeds.is_empty() || seeds.iter().any(|s| *s < base + offset || *s >= base + offset + size || s % 4 != 0) {
        return Err("invalid function entry".into());
    }
    let name = a.get(8).map(String::as_str).unwrap_or("guest");
    if name.is_empty() || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_') {
        return Err("invalid generated module name".into());
    }
    let module = Module { name: name.into(), base, image: &image,
        text: base + offset..base + offset + size, seeds };
    let mut options = Options::default();
    if read_anchors {
        for line in io::stdin().lock().lines() {
            let address = line?.parse()?;
            if !module.text.contains(&address) || address % 4 != 0 || !options.anchor_origins.insert(address) {
                return Err("invalid switch anchor origin".into());
            }
        }
    }
    let output = lift_module(&module, &options);
    let out = PathBuf::from(&a[6]);
    fs::create_dir_all(&out)?;
    for (name, text) in &output.files { fs::write(out.join(name), text)?; }
    for (name, text) in RUNTIME_FILES { fs::write(out.join(name), text)?; }
    // A machine-readable report, including unsupported instructions. They remain traps.
    let mut report = format!("{{\"functions\":{},\"instructions\":{},\"jump_tables\":{},\"unresolved_computed\":{},\"unsupported\":[",
        output.functions, output.instructions, output.jump_tables, output.unresolved_computed);
    for (i, (reason, count)) in output.unsupported.iter().enumerate() {
        if i != 0 { report.push(','); }
        report.push_str(&format!("{{\"reason\":{:?},\"count\":{}}}", reason, count));
    }
    report.push_str("]}\n");
    fs::write(&a[7], report)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("{error}"); std::process::exit(1); }
}
