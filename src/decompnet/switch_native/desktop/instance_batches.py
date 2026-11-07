"""Consolidate exact Maxwell MME instance loops without changing Draw callers."""
from pathlib import Path

from .patches import replace_once


def apply(root):
    gpu = root / 'crates/rt/src/gpu'
    vk = gpu / 'vulkan'
    adapter = Path(__file__).parent
    replace_once(gpu / 'mod.rs', '        impl mme::Host for Host<\'_> {', '''        impl mme::Host for Host<'_> {
            fn draw_vertex_instances(&mut self, first: u32, subsequent: u32, count: u32, instances: u32) -> bool {
                self.gpu.draw_vertex_instances(self.mem, self.eng, self.sub, first, subsequent, count, instances)
            }
            fn draw_indexed_instances(&mut self, first: u32, subsequent: u32, count: u32, instances: u32) -> bool {
                self.gpu.draw_indexed_instances(self.mem, self.eng, self.sub, first, subsequent, count, instances)
            }''')
    with (gpu / 'threed.rs').open('a', encoding='utf-8', newline='\n') as output:
        output.write((adapter / 'instance_batches_gpu.rs').read_text(encoding='utf-8'))
    replace_once(vk / 'mod.rs', '    pub pushes_reused: u64,', '''    pub pushes_reused: u64,
    pub instance_batches: u64,
    pub instance_stream_batches: u64,
    pub instance_pending_batches: u64,''')
    draw = vk / 'draw.rs'
    replace_once(draw, '        let ok = self.try_draw(gpu, mem, regs, cbufs, draw, cursors);',
                 '        let ok = self.try_draw(gpu, mem, regs, cbufs, draw, &mut 1, cursors);')
    replace_once(draw, 'draw: Draw, cursors: &mut [u64; 4]) -> Result<(), String> {',
                 'draw: Draw, instances: &mut u32, cursors: &mut [u64; 4]) -> Result<(), String> {')
    source = draw.read_text(encoding='utf-8')
    if source.count('self.stats.noop_draws += 1;') != 2:
        raise ValueError('Switch instance-batch no-op accounting no longer applies')
    draw.write_text(source.replace('self.stats.noop_draws += 1;',
                    'self.stats.noop_draws += u64::from(*instances);'), encoding='utf-8', newline='\n')
    replace_once(draw, '        let xfb = self.stream_capture(gpu, mem, regs, draw, cursors)?;', '''        if *instances > 1 && (regs[reg::STREAM_OUTPUT] & 1 != 0
            || [0, 2, 3, 4].iter().any(|&stage| regs[reg::PIPELINE + 16 * stage] & 1 != 0))
        {
            *instances = 1;
        }
        let xfb = self.stream_capture(gpu, mem, regs, draw, cursors)?;''')
    replace_once(draw, '        let exports_depth = fs.as_ref()', '''        // Readonly storage uses the same ring-buffer snapshot across the loop.
        // Writes and image operations may depend on the individual draw boundary.
        if *instances > 1 && std::iter::once(&vs).chain(fs.as_ref())
            .any(|shader| shader.shader.storage_written != 0 || !shader.shader.images.is_empty())
        {
            *instances = 1;
        }
        let exports_depth = fs.as_ref()''')
    replace_once(draw, '        vk_bindings.sort_unstable_by_key(|binding| binding.0);', '''        vk_bindings.sort_unstable_by_key(|binding| binding.0);
        let has_instance_stream = *instances > 1 && streams.iter().any(|&stream| instanced_stream(regs, stream));
        let use_instance_streams = has_instance_stream
            && crate::env_var!("KIRIKAE_INSTANCE_VERTEX_STREAMS").is_some_and(|value| value == "1");
        if has_instance_stream && !use_instance_streams {
            *instances = 1;
        }''')
    replace_once(draw, '        let pipeline = self.pipeline(&key, lasting)?;', '''        // Select the input-rate variant only after its streams are prepared.
        // Ordinary draws keep their early pipeline lookup.
        let mut pipeline = if use_instance_streams { None } else { Some(self.pipeline(&key, lasting)?) };''')
    replace_once(draw, '        self.scratch_key = key;\n\n', '')
    replace_once(draw, '''        self.feedback_used.clear();
        let described = self.descriptors(gpu, mem, regs, cbufs, &vs, fs.as_deref(), &mut descriptors);
        self.draw_targets.clear();
        described?;''', '''        self.feedback_used.clear();
        self.draw_texture_alias = (*instances > 1).then_some(false);
        let described = self.descriptors(gpu, mem, regs, cbufs, &vs, fs.as_deref(), &mut descriptors);
        self.draw_targets.clear();
        let texture_alias = self.draw_texture_alias.take() == Some(true);
        described?;
        if texture_alias || !self.feedback_used.is_empty() {
            *instances = 1;
        }''')
    replace_once(draw, '        self.vertex_buffers(gpu, mem, regs, &streams, draw, range, 0, &mut vertex_buffers)?;', '''        let mut uploaded = 0;
        let mut forwarded = 0;
        if use_instance_streams && *instances > 1 {
            match self.instance_vertex_buffers(gpu, mem, regs, &streams, &key.attributes, draw.instance, *instances, &mut vertex_buffers) {
                Ok((bindings, pending)) => {
                    uploaded = bindings;
                    forwarded = pending;
                    for (binding, stride, rate) in &mut key.bindings {
                        if uploaded & (1 << *binding) != 0 {
                            *stride = regs[reg::VERTEX_STREAM + 4 * *binding as usize] & 0xfff;
                            *rate = vk::VertexInputRate::INSTANCE;
                        }
                    }
                    match self.pipeline(&key, lasting) {
                        Ok(instance_pipeline) => pipeline = Some(instance_pipeline),
                        Err(_) => {
                            for (_, stride, rate) in &mut key.bindings {
                                if *rate == vk::VertexInputRate::INSTANCE {
                                    *stride = 0;
                                    *rate = vk::VertexInputRate::VERTEX;
                                }
                            }
                            uploaded = 0;
                            forwarded = 0;
                            vertex_buffers.clear();
                            *instances = 1;
                        }
                    }
                }
                Err(_) => {
                    vertex_buffers.clear();
                    *instances = 1;
                }
            }
        }
        self.vertex_buffers(gpu, mem, regs, &streams, draw, range, uploaded, &mut vertex_buffers)?;
        let pipeline = match pipeline {
            Some(pipeline) => pipeline,
            None => self.pipeline(&key, lasting)?,
        };
        self.scratch_key = key;''')
    replace_once(draw, 'd.cmd_draw_indexed(cmd, count, 1, 0, base.wrapping_sub(lowest as i32), draw.instance);',
                 'd.cmd_draw_indexed(cmd, count, *instances, 0, base.wrapping_sub(lowest as i32), draw.instance);')
    replace_once(draw, 'd.cmd_draw(cmd, draw.count, 1, draw.first - lowest, draw.instance)',
                 'd.cmd_draw(cmd, draw.count, *instances, draw.first - lowest, draw.instance)')
    replace_once(draw, '        if let Some((xfb, offset)) = capture {\n            self.end_stream_capture', '''        if *instances > 1 {
            self.stats.instance_batches += 1;
        }
        if uploaded != 0 {
            self.stats.instance_stream_batches += 1;
        }
        if forwarded != 0 {
            self.stats.instance_pending_batches += 1;
        }
        if let Some((xfb, offset)) = capture {
            self.end_stream_capture''')
    with draw.open('a', encoding='utf-8', newline='\n') as output:
        output.write((adapter / 'instance_batches_draw.rs').read_text(encoding='utf-8'))
    probe = root / 'crates/rt/examples/decomp-graphics.rs'
    replace_once(probe, '    primitive_restart(&gpu, &mem);', '''    primitive_restart(&gpu, &mem);
    instance_batches(&gpu, &mem);''')
    replace_once(probe, '    gpu.shutdown();', '    gpu.shutdown();\n    derived_feedback();')
    with probe.open('a', encoding='utf-8', newline='\n') as output:
        output.write((adapter / 'instance_batches_probe.rs').read_text(encoding='utf-8'))
        output.write((adapter / 'derived_feedback_probe.rs').read_text(encoding='utf-8'))
