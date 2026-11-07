//! Regenerate from the repository root with
//! `cargo run --manifest-path tools/switch-present-shader/Cargo.toml`.
//! Pass `-- --check` to verify the checked-in output without writing it.

use naga::back::spv::{self, BindingInfo, Options, PipelineOptions, WriterFlags};
use naga::compact::{self, KeepUnused};
use naga::valid::{Capabilities, ValidationFlags, Validator};
use naga::{ResourceBinding, ShaderStage};
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::path::Path;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let check = match args.next().as_deref() {
        None => false,
        Some("--check") if args.next().is_none() => true,
        _ => return Err("usage: switch-present-shader [--check]".into()),
    };
    let dir = Path::new("src/decompnet/switch_native/vendor/kirikae-src/crates/rt/src/gpu/vulkan");
    let shader = fs::read_to_string(dir.join("present_filter.wgsl"))?;
    let module = naga::front::wgsl::parse_str(&shader).map_err(|err| err.emit_to_string(&shader))?;
    let mut validator = Validator::new(ValidationFlags::all(), Capabilities::IMMEDIATES);
    validator.validate(&module)?;
    let mut options = Options {
        lang_version: (1, 0),
        flags: WriterFlags::empty(),
        fake_missing_bindings: false,
        ..Options::default()
    };
    options.binding_map.insert(
        ResourceBinding { group: 0, binding: 0 },
        BindingInfo {
            descriptor_set: 0,
            binding: 0,
            binding_array_size: None,
        },
    );

    let mut output = String::from(concat!(
        "// Generated from present_filter.wgsl with Naga 30.0.1.\n",
        "// Regenerate: cargo run --manifest-path tools/switch-present-shader/Cargo.toml\n\n",
    ));
    for (stage, label) in [(ShaderStage::Vertex, "VERTEX"), (ShaderStage::Fragment, "FRAGMENT")] {
        let mut module = module.clone();
        module.entry_points.retain(|entry| entry.stage == stage);
        let [entry] = module.entry_points.as_mut_slice() else {
            return Err(format!("expected one {stage:?} entry point").into());
        };
        entry.name = "main".into();
        compact::compact(&mut module, KeepUnused::No);
        let info = validator.validate(&module)?;
        let pipeline = PipelineOptions {
            shader_stage: stage,
            entry_point: "main".into(),
        };
        let words = spv::write_vec(&module, &info, &options, Some(&pipeline))?;
        writeln!(output, "pub(super) const {label}: &[u32] = &[")?;
        for chunk in words.chunks(8) {
            output.push_str("    ");
            for (index, word) in chunk.iter().enumerate() {
                if index != 0 {
                    output.push(' ');
                }
                write!(output, "0x{word:08x},")?;
            }
            output.push('\n');
        }
        output.push_str("];\n\n");
    }

    let path = dir.join("present_filter_shader.rs");
    let output = output.trim_end_matches('\n').to_owned() + "\n";
    if check {
        if fs::read_to_string(&path)? != output {
            return Err(format!("{} differs from generated output", path.display()).into());
        }
    } else {
        fs::write(path, output)?;
    }
    Ok(())
}
