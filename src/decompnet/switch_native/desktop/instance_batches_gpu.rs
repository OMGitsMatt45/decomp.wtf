
impl Gpu {
    /// Consume the exact MME indexed instance loop. Refusal leaves all state alone.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn draw_indexed_instances(
        &self, mem: &GuestMemory, engines: &mut Engines, sub: u32,
        first: u32, subsequent: u32, count: u32, instances: u32,
    ) -> bool {
        self.draw_instance_loop(mem, engines, sub, first, subsequent, count, instances, true)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn draw_vertex_instances(
        &self, mem: &GuestMemory, engines: &mut Engines, sub: u32,
        first: u32, subsequent: u32, count: u32, instances: u32,
    ) -> bool {
        self.draw_instance_loop(mem, engines, sub, first, subsequent, count, instances, false)
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_instance_loop(
        &self, mem: &GuestMemory, engines: &mut Engines, sub: u32,
        first: u32, subsequent: u32, count: u32, instances: u32, indexed: bool,
    ) -> bool {
        if crate::env_var!("KIRIKAE_MME_INSTANCES").is_some_and(|value| value == "0")
            || instances < 2 || engines.classes.get(sub as usize) != Some(&super::CLASS_3D)
            || subsequent >> 26 & 3 != 1 || first & 0xffff != subsequent & 0xffff
            || trace() || crate::env_var!("KIRIKAE_SHADER_DUMP").is_some()
            || crate::nvn::exec::CHECK.load(Ordering::Relaxed)
            || crate::nvn::shadow::ON.load(Ordering::Relaxed)
            || crate::nvn::encode::ON.load(Ordering::Relaxed)
        {
            return false;
        }
        let instance = match first >> 26 & 3 {
            0 => 0,
            1 => engines.threed.draw.instance.wrapping_add(1),
            _ => engines.threed.draw.instance,
        };
        let Some(last) = instance.checked_add(instances - 1) else {
            return false;
        };
        self.flush_cb_upload(mem, engines);
        let regs = engines.regs.get_mut(&super::CLASS_3D).expect("3D registers");
        // Only these three methods occur in the recognized loop. They have no
        // upload/query/report side effects; retain their final register values.
        regs[reg::BEGIN as usize] = subsequent;
        let draw_method = if indexed { reg::DRAW_INDEX_BUFFER } else { reg::DRAW_VERTEX_ARRAY };
        regs[draw_method as usize] = count;
        regs[reg::END as usize] = 0;
        engines.threed.draw.topology = first & 0xffff;
        engines.threed.draw.pending = None;
        engines.threed.draw.instance = last;
        let draw = Draw {
            topology: topology(regs[reg::TOPOLOGY_CONTROL], regs[reg::TOPOLOGY_OVERRIDE], first & 0xffff),
            first: regs[if indexed { reg::INDEX_BUFFER + 5 } else { reg::VERTEX_ARRAY_START }],
            count,
            index_size: indexed.then(|| 1 << (regs[reg::INDEX_BUFFER + 4] & 3)),
            instance,
        };
        self.stats.draws.fetch_add(u64::from(instances), Ordering::Relaxed);
        let cbs = engines.threed.constant_buffers;
        self.with_renderer(|r| {
            r.draw_instances(self, mem, regs, &cbs, draw, instances, &mut engines.threed.stream_cursors)
        });
        true
    }
}
