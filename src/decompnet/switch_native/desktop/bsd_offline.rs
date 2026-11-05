//! The guest can initialize its BSD client while the desktop network is offline.
use std::sync::atomic::{AtomicBool, Ordering::Relaxed};

use crate::{Cpu, horizon::{RESULT_INVALID_HANDLE, RESULT_INVALID_SIZE, RESULT_INVALID_STATE},
    kernel::KObject, services::{Reply, Request, Service, stub::unimplemented}};

const ENETDOWN: u32 = 100;

pub struct OfflineBsd;

impl Service for OfflineBsd {
    fn name(&self) -> String { "bsd:u".into() }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        let process = c.process();
        let registered = process.service_state("bsd.offline-registered", AtomicBool::default);
        match req.cmd {
            0 => {
                let [handle] = req.copy_handles.as_slice() else {
                    return Reply::err(RESULT_INVALID_HANDLE as u32);
                };
                let Some(KObject::TransferMemory { size, .. }) = process.handles.lock().unwrap().get(*handle) else {
                    return Reply::err(RESULT_INVALID_HANDLE as u32);
                };
                if req.pid.is_none() || req.data.len() < 48 || req.u64(40) == 0 || req.u64(40) > size {
                    return Reply::err(RESULT_INVALID_SIZE as u32);
                }
                registered.store(true, Relaxed);
                // The SDK checks the inline registration status as an s32.
                Reply::ok().u64(0)
            }
            1 if registered.load(Relaxed) && req.pid.is_some() && req.data.len() >= 8 => Reply::ok(),
            2 | 3 if registered.load(Relaxed) && req.data.len() >= 12 => Reply::ok().u32(u32::MAX).u32(ENETDOWN),
            1..=3 => Reply::err(RESULT_INVALID_STATE as u32),
            _ => unimplemented("bsd:u", c, req),
        }
    }
}

#[cfg(test)]
#[test]
fn bsd_registration_can_be_monitored_while_offline() {
    use crate::{abi::Entry, services::harness};
    extern "C" fn probe(c: &mut Cpu) {
        let handle = c.process().handles.lock().unwrap().insert(KObject::TransferMemory { addr: 0, size: 4096 });
        let mut data = vec![0; 40];
        data.extend_from_slice(&4096u64.to_le_bytes());
        let registered = OfflineBsd.call(c, &Request { cmd: 0, pid: Some(0), data,
            copy_handles: vec![handle], ..Default::default() });
        let monitored = OfflineBsd.call(c, &Request { cmd: 1, pid: Some(0),
            data: vec![0; 8], ..Default::default() });
        let socket = OfflineBsd.call(c, &Request { cmd: 2, data: vec![0; 12], ..Default::default() });
        harness::record("bsd/offline", &[registered.result as u64,
            u64::from_le_bytes(registered.data.try_into().unwrap()), monitored.result as u64,
            socket.result as u64, u64::from_le_bytes(socket.data.try_into().unwrap())]);
        c.halt();
    }
    harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
    assert_eq!(harness::observed("bsd/offline"), vec![0, 0, 0, 0, (ENETDOWN as u64) << 32 | u32::MAX as u64]);
}
