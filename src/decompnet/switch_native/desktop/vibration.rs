//! Vibration state/readback for the virtual HID devices. No physical actuator
//! is claimed: keyboard/virtual controllers retain the requested values.
use std::collections::HashMap;
use std::sync::Mutex;
use crate::{Cpu, services::{Reply, Request}};

struct State { permitted: bool, values: HashMap<u32, [u8; 16]> }
impl Default for State {
    fn default() -> Self { Self { permitted: true, values: HashMap::new() } }
}
fn neutral() -> [u8; 16] {
    let mut bytes = [0; 16];
    bytes[4..8].copy_from_slice(&160.0f32.to_le_bytes());
    bytes[12..16].copy_from_slice(&320.0f32.to_le_bytes());
    bytes
}
fn valid(bytes: &[u8; 16]) -> bool {
    let f = |at| f32::from_le_bytes(bytes[at..at + 4].try_into().unwrap());
    (0.0..=1.0).contains(&f(0)) && (0.0..=1.0).contains(&f(8)) &&
        f(4).is_finite() && f(4) >= 0.0 && f(12).is_finite() && f(12) >= 0.0
}
impl State {
    fn set(&mut self, handle: u32, bytes: [u8; 16]) {
        self.values.insert(handle, if self.permitted { bytes } else { neutral() });
    }
    fn get(&self, handle: u32) -> [u8; 16] { self.values.get(&handle).copied().unwrap_or_else(neutral) }
    fn permit(&mut self, enabled: bool) {
        self.permitted = enabled;
        if !enabled { for value in self.values.values_mut() { *value = neutral(); } }
    }
}

pub(super) fn call(c: &mut Cpu, req: &Request) -> Option<Reply> {
    if !matches!(req.cmd, 201 | 202 | 204 | 205 | 206) { return None; }
    let state = c.process().service_state("hid.vibration", || Mutex::new(State::default()));
    let mut state = state.lock().unwrap();
    match req.cmd {
        201 => {
            let bytes: [u8; 16] = req.data.get(4..20)?.try_into().ok()?;
            if !valid(&bytes) { return None; }
            state.set(req.u32(0), bytes);
            Some(Reply::ok())
        }
        202 => Some(Reply::ok().bytes(&state.get(req.u32(0)))),
        204 => {
            let flag = *req.data.first()?;
            if flag > 1 { return None; }
            state.permit(flag != 0); Some(Reply::ok())
        }
        205 => Some(Reply::ok().u8(state.permitted as u8)),
        206 => {
            let read = |i, max| match req.in_buf(i) {
                Some(b) if b.size <= max => c.process().memory.read(b.addr, b.size),
                None => Some(Vec::new()), _ => None,
            };
            let handles = read(0, 0x100)?;
            let values = read(1, 0x400)?;
            if handles.len() % 4 != 0 || values.len() != handles.len() * 4 { return None; }
            let pairs: Vec<(u32, [u8; 16])> = handles.chunks_exact(4).zip(values.chunks_exact(16))
                .map(|(h, v)| (u32::from_le_bytes(h.try_into().unwrap()), v.try_into().unwrap())).collect();
            if !pairs.iter().all(|(_, v)| valid(v)) { return None; }
            for (handle, value) in pairs { state.set(handle, value); }
            Some(Reply::ok())
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requested_values_are_independent_per_device() {
        let mut state = State::default(); let mut value = neutral();
        value[..4].copy_from_slice(&0.75f32.to_le_bytes());
        assert!(valid(&value)); state.set(1, value);
        assert_eq!(state.get(1), value); assert_eq!(state.get(2), neutral());
    }
    #[test]
    fn disabling_vibration_clears_and_blocks_output() {
        let mut state = State::default(); let mut value = neutral(); value[..4].copy_from_slice(&1.0f32.to_le_bytes());
        state.set(1, value); state.permit(false); assert_eq!(state.get(1), neutral());
        state.set(2, value); assert_eq!(state.get(2), neutral());
        state.permit(true); state.set(1, value); assert_eq!(state.get(1), value);
    }
    #[test]
    fn nonfinite_or_out_of_range_requests_are_rejected() {
        for (at, f) in [(0, f32::NAN), (8, 1.5), (4, f32::INFINITY), (12, -1.0)] {
            let mut bytes = neutral(); bytes[at..at + 4].copy_from_slice(&f.to_le_bytes()); assert!(!valid(&bytes));
        }
    }
}
