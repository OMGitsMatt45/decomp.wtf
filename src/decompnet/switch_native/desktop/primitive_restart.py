"""Preserve Maxwell restart indices in Vulkan indexed strips and fans."""
from .patches import replace_once


def apply(root):
    gpu = root / 'crates/rt/src/gpu'
    pipeline, draw, buffers = (gpu / 'vulkan' / name for name in ('pipeline.rs', 'draw.rs', 'buffers.rs'))
    replace_once(pipeline, '    pub(super) topology: vk::PrimitiveTopology,',
                 '    pub(super) topology: vk::PrimitiveTopology,\n    pub(super) primitive_restart: bool,')
    replace_once(pipeline, '''        let restart = matches!(key.topology, vk::PrimitiveTopology::TRIANGLE_STRIP | vk::PrimitiveTopology::LINE_STRIP | vk::PrimitiveTopology::TRIANGLE_FAN);
        let assembly = vk::PipelineInputAssemblyStateCreateInfo::default().topology(key.topology).primitive_restart_enable(restart && false);''',
                 '''        let assembly = vk::PipelineInputAssemblyStateCreateInfo::default().topology(key.topology).primitive_restart_enable(key.primitive_restart);''')
    replace_once(draw, '        key.topology = topology;', '''        key.topology = topology;
        let restart = (matches!(draw.index_size, Some(1 | 2 | 4)) && regs[reg::PRIMITIVE_RESTART] & 1 != 0
            && matches!(topology, vk::PrimitiveTopology::TRIANGLE_STRIP | vk::PrimitiveTopology::LINE_STRIP | vk::PrimitiveTopology::TRIANGLE_FAN))
            .then_some(regs[reg::PRIMITIVE_RESTART + 1]);
        key.primitive_restart = restart.is_some();''')
    replace_once(draw, 'self.index_buffer(gpu, mem, regs, draw, quads)?', 'self.index_buffer(gpu, mem, regs, draw, quads, restart)?')
    replace_once(gpu / 'buffer_cache.rs', '    Index(u32, bool),', '    Index(u32, bool, Option<u32>),')
    replace_once(buffers, 'draw: Draw, quads: bool) -> Result<Option<(vk::Buffer, u64, vk::IndexType, u32)>, String>',
                 'draw: Draw, quads: bool, restart: Option<u32>) -> Result<Option<(vk::Buffer, u64, vk::IndexType, u32)>, String>')
    replace_once(buffers, '''                let widen = move |b: &[u8]| -> Vec<u8> {
                    triangles(match size {
                        1 => b.iter().map(|&b| b as u32).collect(),
                        2 => b.as_chunks::<2>().0.iter().map(|b| u16::from_le_bytes(*b) as u32).collect(),
                        _ => b.as_chunks::<4>().0.iter().map(|b| u32::from_le_bytes(*b)).collect(),
                    })
                };''', '''                let custom_u32_restart = size == 4 && restart.is_some_and(|index| index != u32::MAX);
                let widen = move |b: &[u8]| -> Vec<u8> {
                    let canonical = |index| if Some(index) == restart { u32::MAX } else { index };
                    triangles(match size {
                        1 => b.iter().map(|&b| canonical(b as u32)).collect(),
                        2 => b.as_chunks::<2>().0.iter().map(|b| canonical(u16::from_le_bytes(*b) as u32)).collect(),
                        _ => b.as_chunks::<4>().0.iter().map(|b| canonical(u32::from_le_bytes(*b))).collect(),
                    })
                };''')
    replace_once(buffers, 'buffer_cache::Kind::Index(size, quads)', 'buffer_cache::Kind::Index(size, quads, restart)')
    replace_once(buffers, '''                    if let Some((buffer, offset)) = self.cached(cpu, len, key.2, source, widen) {
                        return Ok(Some((buffer, offset, vk::IndexType::UINT32, count)));
                    }
                    return self.ring_indices(widen(source), count);
                }
                widen(source)''', '''                    let cached = self.cached(cpu, len, key.2, source, widen);
                    // A real UINT32_MAX index would also restart in Vulkan.
                    // Reuse the cached guest range to detect it without rescanning on hits.
                    if custom_u32_restart && self.buffers.index_range(key, restart, |b| vertex_range(b, size, restart))
                        .is_some_and(|(_, hi)| hi == u32::MAX)
                    {
                        return Err("custom restart index collides with Vulkan UINT32 restart".into());
                    }
                    if let Some((buffer, offset)) = cached {
                        return Ok(Some((buffer, offset, vk::IndexType::UINT32, count)));
                    }
                    return self.ring_indices(widen(source), count);
                }
                if custom_u32_restart && source.as_chunks::<4>().0.contains(&[u8::MAX; 4]) {
                    return Err("custom restart index collides with Vulkan UINT32 restart".into());
                }
                widen(source)''')
