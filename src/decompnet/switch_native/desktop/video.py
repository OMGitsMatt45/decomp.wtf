"""Checked additions to the pinned Switch host1x video runtime."""


def vp8(rt, adapter):
    from .patches import replace_once

    host1x = rt / 'src/host1x'
    (host1x / 'decomp_vp8.rs').write_bytes((adapter / 'vp8.rs').read_bytes())
    replace_once(host1x / 'mod.rs', 'pub mod vp9;', 'pub mod vp9;\nmod decomp_vp8;')
    replace_once(host1x / 'mod.rs', '    pub fn write(&self, offset: u32, bytes:', '''    fn is_mapped(&self, offset: u32, len: usize) -> bool {
        self.iova.translate((offset as u64) << 8, len as u64)
            .is_some_and(|cpu| self.mem.is_mapped(cpu, len as u64))
    }

    pub fn write(&self, offset: u32, bytes:''')
    replace_once(host1x / 'mod.rs', '    pub fn map_buffer(&self,', '''    pub(crate) fn close_nvdec_channel(&self, context: u32) {
        self.engines.lock().unwrap().nvdec.close_vp8_channel(context);
    }

    pub fn map_buffer(&self,''')
    nvdec = host1x / 'nvdec.rs'
    replace_once(nvdec, '    vp9: Arc<Mutex<Vp9State>>,',
                 '    vp9: Arc<Mutex<Vp9State>>,\n    vp8: super::decomp_vp8::Vp8,')
    replace_once(nvdec, 'vp9: Arc::default(), pictures: 0',
                 'vp9: Arc::default(), vp8: Default::default(), pictures: 0')
    replace_once(nvdec, '    pub fn write(&mut self,', '''    pub(super) fn close_vp8_channel(&mut self, context: u32) {
        self.vp8.close(context);
    }

    pub fn write(&mut self,''')
    replace_once(nvdec, '                CODEC_VP8 => Err("NVDEC: VP8 is not supported".into()),',
                 '''                CODEC_VP8 => self.vp8.decode(dma, context,
                    self.regs[reg::DRV_PIC_SETUP as usize], self.regs[reg::IN_BUF_BASE as usize],
                    [self.regs[reg::PICTURE_LUMA as usize + 3], self.regs[reg::PICTURE_CHROMA as usize + 3]]),''')
    replace_once(rt / 'src/services/nvdrv.rs', '''                p.service_state("host1x", Host1x::default).drain();
                st.fds.lock().unwrap().remove(&req.u32(0));''', '''                let host1x = p.service_state("host1x", Host1x::default);
                host1x.drain();
                let fd = req.u32(0);
                let device = st.fds.lock().unwrap().remove(&fd);
                if matches!(device, Some(Device::Engine { class: CLASS_NVDEC })) {
                    host1x.close_nvdec_channel(fd);
                }''')
