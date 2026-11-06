"""Size native audren work buffers with the guest SDK's renderer calculation."""


def apply(root):
    from .patches import replace_once

    audio = root / 'crates/rt/src/services/audio/mod.rs'
    replace_once(audio, 'pub struct AudioRendererManager;', '''#[cfg(feature = "decomp-native")]
fn native_work_buffer_size(c: &mut Cpu, data: &[u8]) -> Option<u64> {
    const CALCULATE: &str = "_ZN2nn5audio6server17AudioRenderSystem17GetWorkBufferSizeERKNS0_6detail30AudioRendererParameterInternalE";
    let p = c.process();
    let address = p.symbol(CALCULATE)?;
    p.lookup_compiled(address)?;
    let data = data.get(..0x34)?;
    let scratch = c.sp.checked_sub(0x40)? & !0xf;
    let original = p.memory.read(scratch, 0x40)?;
    let mut parameter = [0; 0x40];
    parameter[..data.len()].copy_from_slice(data);
    if !p.memory.write(scratch, &parameter) { return None; }
    // The server-side calculator is a normal SDK function. Preserve the
    // caller's IPC context while it reads the copied parameter on the stack.
    let saved = (c.x, c.v, c.sp, c.pc, c.nzcv, c.tpidr_el0, c.tpidrro_el0,
        c.fpcr, c.fpsr, c.excl_addr, c.excl_lo, c.excl_hi);
    c.sp = scratch;
    c.x[0] = scratch;
    crate::hle::call_guest(c, address, false);
    let size = c.x[0];
    (c.x, c.v, c.sp, c.pc, c.nzcv, c.tpidr_el0, c.tpidrro_el0,
        c.fpcr, c.fpsr, c.excl_addr, c.excl_lo, c.excl_hi) = saved;
    p.memory.write(scratch, &original);
    (!c.halted && size != 0).then_some(size)
}

pub struct AudioRendererManager;''')
    replace_once(audio, '            1 => Reply::ok().u64(0x10_0000),', '''            1 => {
                #[cfg(feature = "decomp-native")]
                if let Some(size) = native_work_buffer_size(c, &req.data) {
                    return Reply::ok().u64(size);
                }
                Reply::ok().u64(0x10_0000)
            }''')
