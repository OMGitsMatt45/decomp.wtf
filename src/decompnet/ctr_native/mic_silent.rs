//! Guest microphone service with a deterministic silent input source.
use crate::{
    kernel::{
        ipc::{CommandBuffer, Descriptor, Header},
        object::{KObject, ObjectId},
        sync::ResetType,
        thread::CPU_CLOCK_HZ,
    },
    System,
};
use zakuro_common::result::{Level, Module, ResultCode, Summary};

const INVALID: u32 = ResultCode::new(Level::Usage, Summary::InvalidArgument, Module::Mic, 1005).0;
const RATES: [u32; 4] = [32728, 16364, 10909, 8182];

#[derive(Default, serde::Serialize, serde::Deserialize)]
pub struct MicState {
    memory: Option<(ObjectId, u32)>,
    event: Option<ObjectId>,
    sampling: Option<Sampling>,
    gain: u8,
    power: bool,
    clamp: bool,
    allow_shell_closed: bool,
    legacy: bool,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct Sampling {
    offset: u32,
    size: u32,
    cursor: u32,
    encoding: u8,
    rate: u32,
    repeat: bool,
    last_cycle: u64,
    fraction: u64,
}

pub fn handle(system: &mut System, buffer: &CommandBuffer, header: Header) -> bool {
    let command = header.command_id();
    let value = if header.normal_params() != 0 { buffer.get(&mut system.memory, 1) } else { 0 };
    let mut response = None;
    let valid = match header.0 {
        0x0001_0042 => {
            let descriptor = buffer.get(&mut system.memory, 2);
            let handle = buffer.get(&mut system.memory, 3);
            let object = system.kernel.resolve(handle).filter(|&id| {
                matches!(system.kernel.objects.get(id), Some(KObject::SharedMemory(block))
                    if (5..=block.size).contains(&value))
            });
            if let Some(id) = object.filter(|_| descriptor == Descriptor::handles(1)) {
                system.kernel.objects.add_ref(id);
                unmap(system);
                system.services.mic.memory = Some((id, value));
                true
            } else {
                false
            }
        }
        0x0002_0000 => {
            unmap(system);
            true
        }
        0x0003_0140 => {
            let rate = buffer.get(&mut system.memory, 2);
            let offset = buffer.get(&mut system.memory, 3);
            let size = buffer.get(&mut system.memory, 4);
            let repeat = buffer.get(&mut system.memory, 5) & 1 != 0;
            start(system, value, rate, offset, size, repeat)
        }
        0x0004_0040 => {
            if let Some(&rate) = RATES.get(value as usize) {
                tick(system);
                if let Some(sampling) = &mut system.services.mic.sampling {
                    sampling.rate = rate;
                }
                true
            } else {
                false
            }
        }
        0x0005_0000 => {
            tick(system);
            system.services.mic.sampling = None;
            true
        }
        0x0006_0000 => {
            tick(system);
            response = Some(u32::from(system.services.mic.sampling.is_some()));
            true
        }
        0x0007_0000 => {
            const NAME: &str = "MIC buffer full";
            let handle = if let Some(id) = system.services.mic.event {
                system.kernel.handles.create(&mut system.kernel.objects, id, NAME)
            } else {
                let (id, handle) = system.kernel.create_event(ResetType::OneShot, NAME);
                system.kernel.objects.add_ref(id);
                system.services.mic.event = Some(id);
                handle
            };
            buffer.set(&mut system.memory, 0, Header::new(command, 1, 2).0);
            buffer.set(&mut system.memory, 1, 0);
            buffer.set(&mut system.memory, 2, Descriptor::handles(1));
            buffer.set(&mut system.memory, 3, handle);
            return true;
        }
        0x0008_0040 => { system.services.mic.gain = value as u8; true }
        0x0009_0000 => { response = Some(u32::from(system.services.mic.gain)); true }
        0x000a_0040 => { system.services.mic.power = value & 1 != 0; true }
        0x000b_0000 => { response = Some(u32::from(system.services.mic.power)); true }
        0x000d_0040 => { system.services.mic.clamp = value & 1 != 0; true }
        0x000e_0000 => { response = Some(u32::from(system.services.mic.clamp)); true }
        0x000f_0040 => { system.services.mic.allow_shell_closed = value & 1 != 0; true }
        0x0010_0040 => { system.services.mic.legacy = value == 0; true }
        _ => return false,
    };
    if valid {
        buffer.reply(&mut system.memory, command, response.as_slice());
    } else {
        buffer.reply_error(&mut system.memory, command, INVALID);
    }
    true
}

fn unmap(system: &mut System) {
    system.services.mic.sampling = None;
    if let Some((id, _)) = system.services.mic.memory.take() {
        system.kernel.objects.release(id);
    }
}

fn start(system: &mut System, encoding: u32, rate: u32, offset: u32, size: u32, repeat: bool) -> bool {
    let Some((id, mapped_size)) = system.services.mic.memory else { return false; };
    let Some(&rate) = RATES.get(rate as usize) else { return false; };
    let sample_size = (encoding & 1) + 1;
    if encoding > 3 || size == 0 || size % sample_size != 0 || offset % sample_size != 0
        || offset.checked_add(size).is_none_or(|end| end > mapped_size - 4) {
        return false;
    }
    let Some(KObject::SharedMemory(block)) = system.kernel.objects.get(id) else { return false; };
    if !system.memory.write_physical(block.paddr + mapped_size - 4, &[0; 4]) {
        return false;
    }
    system.services.mic.sampling = Some(Sampling {
        offset, size, cursor: 0, encoding: encoding as u8, rate, repeat,
        last_cycle: system.cpu.cycles, fraction: 0,
    });
    true
}

pub fn tick(system: &mut System) {
    let mic = &mut system.services.mic;
    let Some(sampling) = &mut mic.sampling else { return; };
    let Some((id, mapped_size)) = mic.memory else { return; };
    let Some(KObject::SharedMemory(block)) = system.kernel.objects.get(id) else { return; };
    let elapsed = system.cpu.cycles.saturating_sub(sampling.last_cycle);
    let scaled = elapsed.saturating_mul(u64::from(sampling.rate)).saturating_add(sampling.fraction);
    sampling.last_cycle = system.cpu.cycles;
    sampling.fraction = scaled % CPU_CLOCK_HZ;
    let sample_size = u64::from((sampling.encoding & 1) + 1);
    let count = scaled / CPU_CLOCK_HZ * sample_size;
    if count == 0 { return; }

    // Unsigned PCM silence is the midpoint. For 16-bit PCM it is little endian.
    let mut silence = [0; 512];
    match sampling.encoding {
        0 => silence.fill(0x80),
        1 => silence[1..].iter_mut().step_by(2).for_each(|byte| *byte = 0x80),
        _ => {}
    }
    let next = u64::from(sampling.cursor) + count;
    let first_count = count.min(u64::from(sampling.size - sampling.cursor)) as u32;
    let wrapped_count = if sampling.repeat {
        (count - u64::from(first_count)).min(u64::from(sampling.size)) as u32
    } else {
        0
    };
    let address = block.paddr + sampling.offset;
    for (offset, count) in [(sampling.cursor, first_count), (0, wrapped_count)] {
        for chunk in (0..count).step_by(silence.len()) {
            let len = (count - chunk).min(silence.len() as u32) as usize;
            if !system.memory.write_physical(address + offset + chunk, &silence[..len]) {
                mic.sampling = None;
                return;
            }
        }
    }
    let filled = next >= u64::from(sampling.size);
    sampling.cursor = if sampling.repeat {
        (next % u64::from(sampling.size)) as u32
    } else {
        next.min(u64::from(sampling.size)) as u32
    };
    system.memory.write_physical(block.paddr + mapped_size - 4, &sampling.cursor.to_le_bytes());
    if filled {
        if let Some(event) = mic.event {
            system.kernel.signal_event(event);
        }
        if !sampling.repeat {
            mic.sampling = None;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::object::SharedMemory;
    use crate::memory::MemoryRegion;

    #[test]
    fn sampling_writes_silence_and_signals_when_the_buffer_fills() {
        let mut system = System::new(crate::Config::default());
        let block = system.memory.phys.allocate(MemoryRegion::Base, 0x1000).unwrap();
        let id = system.kernel.objects.insert(KObject::SharedMemory(SharedMemory {
            name: "MIC test".into(),
            address: 0,
            size: block.size,
            paddr: block.addr,
            mapped_at: None,
        }));
        let (event, _) = system.kernel.create_event(ResetType::OneShot, "MIC test");
        system.services.mic.memory = Some((id, block.size));
        system.services.mic.event = Some(event);

        assert!(!start(&mut system, 1, 0, block.size - 4, 2, false));
        assert!(start(&mut system, 1, 0, 4, 4, false));
        system.cpu.cycles += CPU_CLOCK_HZ / 100;
        tick(&mut system);
        assert!(system.services.mic.sampling.is_none());
        assert!(matches!(system.kernel.objects.get(event), Some(KObject::Event(event)) if event.signaled));
        let mut samples = [0; 4];
        assert!(system.memory.read_physical(block.addr + 4, &mut samples));
        assert_eq!(samples, [0, 128, 0, 128]);
        let mut cursor = [0; 4];
        assert!(system.memory.read_physical(block.addr + block.size - 4, &mut cursor));
        assert_eq!(u32::from_le_bytes(cursor), 4);

        assert!(start(&mut system, 3, 0, 4, 4, true));
        system.cpu.cycles += 3 * CPU_CLOCK_HZ / u64::from(RATES[0]) + 1;
        tick(&mut system);
        assert_eq!(system.services.mic.sampling.as_ref().unwrap().cursor, 2);
        assert!(system.memory.read_physical(block.addr + 4, &mut samples));
        assert_eq!(samples, [0; 4]);
    }
}

