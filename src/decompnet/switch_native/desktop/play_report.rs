//! Desktop play-report service: bounded, process-local storage, no upload.
//! 10100/10101 are the original SaveReport / SaveReportWithUser ABI.
use std::{collections::VecDeque, sync::Mutex};
use crate::{Cpu, services::{Buf, Reply, Request, Service}};

const MAX_BYTES: usize = 1024 * 1024;
const MAX_REPORTS: usize = 16;
const INVALID: u32 = 0x3e;

#[derive(Debug, PartialEq)]
struct Report { user: Option<[u8; 16]>, pid: u64, room: Vec<u8>, payload: Vec<u8> }
#[derive(Default)]
struct Reports { queue: VecDeque<Report>, bytes: usize }
impl Reports {
    fn push(&mut self, report: Report) {
        let size = report.room.len() + report.payload.len();
        while self.queue.len() >= MAX_REPORTS || self.bytes + size > MAX_BYTES {
            let old = self.queue.pop_front().expect("bounded report size");
            self.bytes -= old.room.len() + old.payload.len();
        }
        self.bytes += size;
        self.queue.push_back(report);
    }
}

pub struct PlayReport;
impl Service for PlayReport {
    fn name(&self) -> String { "prepo:u".into() }
    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        if !matches!(req.cmd, 10100 | 10101) {
            return crate::services::stub::unimplemented("prepo:u", c, req);
        }
        let with_user = req.cmd == 10101;
        let pid_at = if with_user { 16 } else { 0 };
        if req.data.len() != pid_at + 8 || req.a.len() != 1 || req.x.len() != 1 {
            return Reply::err(INVALID);
        }
        let read = |b: Buf| {
            (b.size <= MAX_BYTES as u64).then(|| c.process().memory.read(b.addr, b.size)).flatten()
        };
        let (Some(room), Some(payload)) = (read(req.x[0]), read(req.a[0])) else { return Reply::err(INVALID); };
        if room.len() + payload.len() > MAX_BYTES || room.is_empty() || payload.is_empty() {
            return Reply::err(INVALID);
        }
        let report = Report { user: with_user.then(|| req.data[..16].try_into().unwrap()),
            pid: req.u64(pid_at), room, payload };
        c.process().service_state("prepo.reports", || Mutex::new(Reports::default()))
            .lock().unwrap().push(report);
        Reply::ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{abi::Entry, services::harness};

    #[test]
    fn first_save_report_copies_guest_buffers_and_rejects_bad_requests() {
        extern "C" fn probe(c: &mut Cpu) {
            c.process().memory.map(0x300000, 0x1000).unwrap();
            assert!(c.process().memory.write(0x300000, b"room\0payload"));
            let mut req = Request { cmd: 10101, data: [vec![7;16], 42u64.to_le_bytes().to_vec()].concat(),
                x: vec![Buf { addr: 0x300000, size: 5 }], a: vec![Buf { addr: 0x300005, size: 7 }], ..Default::default() };
            assert_eq!(super::super::open("prepo:u").call(c, &req).result, 0);
            assert!(c.process().memory.write(0x300000, &[0;12]));
            let state = c.process().service_state("prepo.reports", || Mutex::new(Reports::default()));
            let state = state.lock().unwrap();
            assert_eq!(state.queue[0], Report { user: Some([7;16]), pid:42, room:b"room\0".to_vec(), payload:b"payload".to_vec() });
            drop(state);
            req.a[0].size = MAX_BYTES as u64 + 1;
            assert_eq!(PlayReport.call(c, &req).result, INVALID);
            req.a[0] = Buf { addr: 0x700000, size: 4 };
            assert_eq!(PlayReport.call(c, &req).result, INVALID);
            req.data.clear();
            assert_eq!(PlayReport.call(c, &req).result, INVALID);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
    }

    #[test]
    fn queue_is_bounded_by_both_count_and_bytes() {
        let mut reports = Reports::default();
        for i in 0..100 { reports.push(Report { user:None, pid:i, room:vec![0], payload:vec![0;100] }); }
        assert_eq!(reports.queue.len(), MAX_REPORTS);
        reports.push(Report { user:None, pid:100, room:vec![0], payload:vec![0;MAX_BYTES-1] });
        assert_eq!(reports.queue.len(), 1);
        assert_eq!(reports.bytes, MAX_BYTES);
    }
}
