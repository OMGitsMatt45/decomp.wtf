//! Stationary virtual IMU lifecycle and per-handle policy.
use super::*;

#[derive(Default)]
pub(super) struct State {
    stopped: [u8; 10],
    fusion: HashMap<u32, bool>,
    drift: HashMap<u32, u32>,
}
impl State {
    pub(super) fn running(&self, index: usize, lifo: usize) -> bool { self.stopped[index] & (1 << lifo) == 0 }
    fn set_running(&mut self, index: usize, lifo: usize, active: bool) {
        if active { self.stopped[index] &= !(1 << lifo); } else { self.stopped[index] |= 1 << lifo; }
    }
}
fn decode(handle: u32) -> Option<(usize, usize)> {
    if handle >> 24 != 0 { return None; }
    let index = npad_index((handle >> 8) & 0xff)?;
    let lifo = match (handle & 0xff, (handle >> 16) & 0xff) {
        (3, 2) => 0, (4, 2) => 1, (5, 0) => 2, (5, 1) => 3, (6, 0) => 4, (7, 1) => 5,
        _ => return None,
    };
    Some((index, lifo))
}
pub(super) fn call(c: &mut Cpu, req: &Request) -> Option<Reply> {
    if !matches!(req.cmd, 66 | 67 | 68 | 69 | 79 | 80 | 81 | 82) { return None; }
    let handle = req.u32(if req.cmd == 69 { 4 } else { 0 });
    let (index, lifo) = decode(handle)?;
    let n = npads(c);
    let mut state = n.inner.lock().unwrap();
    let result = match req.cmd {
        66 | 67 => { state.sensors.set_running(index, lifo, req.cmd == 66); Reply::ok() }
        68 => Reply::ok().u8(state.sensors.fusion.get(&handle).copied().unwrap_or(true) as u8),
        69 => {
            let flag = *req.data.first()?; if flag > 1 { return None; }
            state.sensors.fusion.insert(handle, flag != 0); Reply::ok()
        }
        79 => {
            let mode = req.u32(4); if mode > 2 { return None; }
            state.sensors.drift.insert(handle, mode); Reply::ok()
        }
        80 => Reply::ok().u32(state.sensors.drift.get(&handle).copied().unwrap_or(0)),
        81 => { state.sensors.drift.remove(&handle); Reply::ok() }
        82 => Reply::ok().u8(1), // Virtual IMUs have zero angular velocity.
        _ => return None,
    };
    drop(state); n.tick(c.process()); Some(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{abi::Entry, services::harness};
    #[test]
    fn handle_fields_select_the_documented_npad_lifos() {
        assert_eq!(decode(0x20003), Some((0, 0)));
        assert_eq!(decode(0x22004), Some((8, 1)));
        assert_eq!(decode(5), Some((0, 2)));
        assert_eq!(decode(0x10005), Some((0, 3)));
        assert_eq!(decode(6), Some((0, 4)));
        assert_eq!(decode(0x10007), Some((0, 5)));
        assert_eq!(decode(0), None); assert_eq!(decode(0x10000006), None);
    }
    #[test]
    fn sensor_start_stop_calls_update_the_selected_handle() {
        extern "C" fn probe(c: &mut Cpu) {
            let n = npads(c);
            let handle = 0x20003u32.to_le_bytes().to_vec();
            let start = call(c, &Request { cmd: 66, data: handle.clone(), ..Default::default() }).unwrap();
            let active = n.inner.lock().unwrap().sensors.running(0, 0);
            let stop = call(c, &Request { cmd: 67, data: handle, ..Default::default() }).unwrap();
            let stopped = n.inner.lock().unwrap().sensors.running(0, 0);
            harness::record("hid/sensor_lifecycle", &[start.result as u64, active as u64, stop.result as u64, stopped as u64]);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
        assert_eq!(harness::observed("hid/sensor_lifecycle"), vec![0, 1, 0, 0]);
    }
}
