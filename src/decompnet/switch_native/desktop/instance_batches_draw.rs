
impl Renderer {
    /// Preparation can narrow an unsafe batch to its first ordinary draw.
    /// Continue the remaining instances through exactly the existing draw path.
    #[allow(clippy::too_many_arguments)]
    pub fn draw_instances(
        &mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32],
        cbufs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], mut draw: Draw,
        mut remaining: u32, cursors: &mut [u64; 4],
    ) {
        let start = std::time::Instant::now();
        let mut instances = remaining;
        while remaining != 0 {
            let result = self.try_draw(gpu, mem, regs, cbufs, draw, &mut instances, cursors);
            if let Err(why) = result {
                // No draw was issued on failure. Preserve the original number
                // of attempts, since later resource preparation can succeed.
                self.stats.skipped += 1;
                crate::decomp::gpu_failure(0, &why);
                if self.stats.skip_reasons.len() < 64 || self.stats.skip_reasons.contains_key(&why) {
                    *self.stats.skip_reasons.entry(why).or_default() += 1;
                }
                instances = 1;
            } else {
                self.stats.draws += u64::from(instances);
            }
            remaining -= instances;
            draw.instance = draw.instance.wrapping_add(instances);
        }
        self.stats.draw_time += start.elapsed();
    }
}
