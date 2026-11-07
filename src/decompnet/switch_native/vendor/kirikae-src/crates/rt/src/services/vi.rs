use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use crate::cpu::Cpu;
use crate::display::{self, Frame};
use crate::process::Process;
use crate::services::stub::{unimplemented, Stub};
use crate::services::{Reply, Request, Service};

const WIDTH: u32 = 1280;
const HEIGHT: u32 = 720;
const BINDER_ID: i32 = 1;
const SLOTS: usize = 16;

pub struct Vi {
    pub name: &'static str,
}

impl Service for Vi {
    fn name(&self) -> String {
        self.name.into()
    }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        match (self.name, req.cmd) {
            ("vi:u", 0) | ("vi:s", 1) | ("vi:m", 2) => Reply::ok().object(Arc::new(DisplayService)),
            _ => unimplemented(self.name, c, req),
        }
    }
}

#[derive(Clone, Debug, Default)]
struct Slot {
    flattened: Vec<u8>,
    nvmap: u32,
    offset: u64,
    width: u32,
    height: u32,
    format: u32,
    pitch: u32,
    block_linear: bool,
    block_height_log2: u32,
}

#[derive(Default)]
struct Queue {
    slots: Vec<Option<Slot>>,
    next: usize,
}

struct State {
    queue: Mutex<Queue>,
    buffer_event: u32,
    vsync_event: u32,
    vsync_started: AtomicBool,
}

fn state(c: &Cpu) -> Arc<State> {
    let p = c.process();
    p.service_state("vi", || State {
        queue: Mutex::new(Queue { slots: vec![None; SLOTS], next: 0 }),
        buffer_event: p.create_event(true),
        vsync_event: p.create_event(false),
        vsync_started: AtomicBool::new(false),
    })
}

fn start_vsync(p: &'static Process, st: &State) {
    if st.vsync_started.swap(true, Ordering::Relaxed) {
        return;
    }
    let event = st.vsync_event;
    let _ = std::thread::Builder::new().name("kirikae-vsync".into()).spawn(move || {
        let period = std::time::Duration::from_nanos(1_000_000_000 / 60);
        let epoch = *VSYNC_EPOCH.get_or_init(std::time::Instant::now);
        let past = (epoch.elapsed().as_nanos() / period.as_nanos()) as u32;
        let mut next = epoch + period * past;
        loop {
            next += period;
            std::thread::sleep(next.saturating_duration_since(std::time::Instant::now()));
            if p.sched.exiting.load(Ordering::Relaxed) {
                return;
            }
            p.set_event(event, true);
        }
    });
}

struct DisplayService;

impl Service for DisplayService {
    fn name(&self) -> String {
        "vi/IApplicationDisplayService".into()
    }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        let p = c.process();
        match req.cmd {
            100 | 103 => Reply::ok().object(Arc::new(Binder)),
            101 => Reply::ok().object(Arc::new(Stub::new("vi/ISystemDisplayService"))),
            102 => Reply::ok().object(Arc::new(Stub::new("vi/IManagerDisplayService"))),
            1000 => {
                if let Some(b) = req.out_buf(0) {
                    let mut info = [0u8; 0x60];
                    info[..7].copy_from_slice(b"Default");
                    info[0x40] = 1;
                    info[0x48..0x50].copy_from_slice(&1u64.to_le_bytes());
                    info[0x50..0x58].copy_from_slice(&(WIDTH as u64).to_le_bytes());
                    info[0x58..0x60].copy_from_slice(&(HEIGHT as u64).to_le_bytes());
                    p.memory.write(b.addr, &info[..(b.size as usize).min(0x60)]);
                }
                Reply::ok().u64(1)
            }
            1010 | 1011 => Reply::ok().u64(0),
            1020 | 1101 | 2021 | 2031 | 2101 => Reply::ok(),
            1102 => Reply::ok().u64(WIDTH as u64).u64(HEIGHT as u64),
            2020 | 2030 => {
                let parcel = native_window();
                if let Some(b) = req.out_buf(0) {
                    p.memory.write(b.addr, &parcel[..parcel.len().min(b.size as usize)]);
                }
                let title = format!("kirikae - {:016x}", p.title_id);
                display::start(p, title);
                start_vsync(p, &state(c));
                p.log_ipc(format!("vi: layer opened (cmd {})", req.cmd));
                let r = Reply::ok();
                let r = if req.cmd == 2030 { r.u64(1) } else { r };
                r.u64(parcel.len() as u64)
            }
            2102 => Reply::ok().u64(req.u32(0).min(4) as u64),
            5202 | 5203 => Reply::ok().copy_handle(state(c).vsync_event),
            _ => unimplemented("vi/IApplicationDisplayService", c, req),
        }
    }
}

fn native_window() -> Vec<u8> {
    let mut w = ParcelWriter::default();
    w.i32(2);
    w.i32(0);
    w.i64(BINDER_ID as i64);
    w.i64(0);
    w.bytes(b"dispdrv\0");
    w.bytes(&[0; 8]);
    w.finish_with_objects(&[0])
}

struct Binder;

impl Service for Binder {
    fn name(&self) -> String {
        "vi/IHOSBinderDriver".into()
    }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        let p = c.process();
        match req.cmd {
            0 | 3 => {
                let (id, code) = (req.u32(0) as i32, req.u32(4));
                let input = req.in_buf(0).and_then(|b| p.memory.read(b.addr, b.size)).unwrap_or_default();
                let reply = transact(c, id, code, &input);
                if let Some(b) = req.out_buf(0) {
                    p.memory.write(b.addr, &reply[..reply.len().min(b.size as usize)]);
                }
                Reply::ok()
            }
            1 => Reply::ok(),
            2 => Reply::ok().copy_handle(state(c).buffer_event),
            _ => unimplemented("vi/IHOSBinderDriver", c, req),
        }
    }
}

const REQUEST_BUFFER: u32 = 1;
const SET_BUFFER_COUNT: u32 = 2;
const DEQUEUE_BUFFER: u32 = 3;
const QUEUE_BUFFER: u32 = 7;
const CANCEL_BUFFER: u32 = 8;
const QUERY: u32 = 9;
const CONNECT: u32 = 10;
const DISCONNECT: u32 = 11;
const SET_PREALLOCATED_BUFFER: u32 = 14;

fn transact(c: &Cpu, id: i32, code: u32, input: &[u8]) -> Vec<u8> {
    let p = c.process();
    let st = state(c);
    let mut r = ParcelReader::new(input);
    r.skip_interface_token();
    let mut w = ParcelWriter::default();
    if id != BINDER_ID {
        p.warn_once(format!("vi: transaction {code} to unknown binder {id}"));
    }
    let known = [REQUEST_BUFFER, SET_BUFFER_COUNT, DEQUEUE_BUFFER, QUEUE_BUFFER, CANCEL_BUFFER, QUERY, CONNECT, DISCONNECT, SET_PREALLOCATED_BUFFER];
    if known.contains(&code) {
        crate::usage::command(c, "vi/IGraphicBufferProducer", code as u64, crate::usage::Status::Implemented, "", input);
    }
    match code {
        REQUEST_BUFFER => {
            let slot = r.i32() as usize;
            let q = st.queue.lock().unwrap();
            match q.slots.get(slot).and_then(|s| s.as_ref()) {
                Some(s) => {
                    w.i32(1);
                    w.bytes(&s.flattened);
                }
                None => w.i32(0),
            }
        }
        SET_BUFFER_COUNT | DISCONNECT => {}
        DEQUEUE_BUFFER => {
            let mut q = st.queue.lock().unwrap();
            let filled: Vec<usize> = (0..SLOTS).filter(|&i| q.slots[i].is_some()).collect();
            let slot = if filled.is_empty() { 0 } else { filled[q.next % filled.len()] };
            q.next += 1;
            w.i32(slot as i32);
            w.i32(1);
            w.i32(0x24);
            w.i32(0);
            w.bytes(&[0; 0x24]);
        }
        QUEUE_BUFFER => {
            let slot = r.i32() as usize;
            let raw = r.flattenable();
            let word = |at: usize| raw.as_ref().and_then(|raw| raw.get(at..at + 4)).map(|b| u32::from_le_bytes(b.try_into().unwrap()));
            let transform = word(40).unwrap_or(0);
            let asked = word(52);
            let interval = asked.unwrap_or(1).min(4);
            static LAST_ASKED: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(u32::MAX);
            if let Some(a) = asked
                && LAST_ASKED.swap(a, Ordering::Relaxed) != a
                && std::env::var_os("KIRIKAE_STATS").is_some()
            {
                eprintln!("kirikae: vi: swap interval {a} from frame {}", crate::display::FRAMES.load(Ordering::Relaxed));
            }
            let s = st.queue.lock().unwrap().slots.get(slot).cloned().flatten();
            match s {
                Some(s) => crate::sched::without_gil(c, || {
                    let prof = crate::prof::enter(crate::prof::Cat::Present);
                    present(p, &s, transform);
                    drop(prof);
                    let _prof = crate::prof::enter(crate::prof::Cat::Sleep);
                    pace(crate::games::pace_interval(p, interval));
                    crate::games::presented(p);
                    crate::gpu::frame_presented();
                }),
                None => p.warn_once(format!("vi: queued slot {slot} has no buffer")),
            }
            p.set_event(st.buffer_event, true);
            queue_buffer_output(&mut w);
        }
        CANCEL_BUFFER => {}
        QUERY => {
            let v = match r.i32() {
                0 => WIDTH as i32,
                1 => HEIGHT as i32,
                2 => 1,
                _ => 0,
            };
            w.i32(v);
        }
        CONNECT => queue_buffer_output(&mut w),
        SET_PREALLOCATED_BUFFER => {
            let slot = r.i32() as usize;
            let present = r.i32() != 0;
            let parsed = if present { r.flattenable().map(parse_graphic_buffer) } else { None };
            if let Some(s) = &parsed {
                p.log_ipc(format!(
                    "vi: slot {slot}: {}x{} format {} pitch {} {} (block height {}) at nvmap {} + {:#x}",
                    s.width,
                    s.height,
                    s.format,
                    s.pitch,
                    if s.block_linear { "block linear" } else { "pitch linear" },
                    1 << s.block_height_log2,
                    s.nvmap,
                    s.offset
                ));
            }
            if let Some(entry) = st.queue.lock().unwrap().slots.get_mut(slot) {
                *entry = parsed;
            }
        }
        _ => {
            p.warn_once(format!("vi: IGraphicBufferProducer transaction {code} is stubbed"));
            crate::usage::command(c, "vi/IGraphicBufferProducer", code as u64, crate::usage::Status::Stub, "unimplemented", input);
        }
    }
    w.i32(0);
    w.finish()
}

fn queue_buffer_output(w: &mut ParcelWriter) {
    w.i32(WIDTH as i32);
    w.i32(HEIGHT as i32);
    w.i32(0);
    w.i32(0);
}

fn parse_graphic_buffer(raw: Vec<u8>) -> Slot {
    let u = |o: usize| raw.get(8 + o..12 + o).map_or(0, |b| u32::from_le_bytes(b.try_into().unwrap()));
    let nv = 0x28;
    let surface = nv + 0x34;
    Slot {
        nvmap: u(nv + 0x4),
        offset: u(surface + 0x1c) as u64,
        width: u(surface),
        height: u(surface + 0x4),
        format: u(0x10),
        pitch: u(surface + 0x14),
        block_linear: u(surface + 0x10) == 3,
        block_height_log2: u(surface + 0x24).min(5),
        flattened: raw,
    }
}

const TRANSFORM_FLIP_H: u32 = 1;
const TRANSFORM_FLIP_V: u32 = 2;

fn transformed(mut frame: Frame, transform: u32) -> Frame {
    let (w, h) = (frame.width as usize, frame.height as usize);
    if transform & TRANSFORM_FLIP_V != 0 {
        for y in 0..h / 2 {
            let (top, bottom) = frame.pixels.split_at_mut((h - 1 - y) * w);
            top[y * w..(y + 1) * w].swap_with_slice(&mut bottom[..w]);
        }
    }
    if transform & TRANSFORM_FLIP_H != 0 {
        for row in frame.pixels.chunks_mut(w) {
            row.reverse();
        }
    }
    frame
}

fn present(p: &Process, s: &Slot, transform: u32) {
    if transform & !(TRANSFORM_FLIP_H | TRANSFORM_FLIP_V) != 0 {
        p.warn_once(format!("vi: buffer transform {transform:#x} is shown without rotation"));
    }
    let Some(m) = p.gpu.nvmap(s.nvmap) else {
        p.warn_once(format!("vi: buffer uses unknown nvmap handle {}", s.nvmap));
        return;
    };
    if s.format != 1 {
        p.warn_once(format!("vi: pixel format {} is shown as RGBA8888", s.format));
    }
    if let Some(dir) = std::env::var_os("KIRIKAE_TARGET_DUMP") {
        let n = display::FRAMES.load(std::sync::atomic::Ordering::Relaxed) + 1;
        let every = std::env::var("KIRIKAE_TARGET_DUMP_EVERY").ok().and_then(|v| v.parse().ok()).unwrap_or(60u64).max(1);
        if n % every == 1 % every {
            p.gpu.dump_images(std::path::Path::new(&dir), n);
        }
    }
    let cpu = m.addr + s.offset;
    let (flip_h, flip_v) = (transform & TRANSFORM_FLIP_H != 0, transform & TRANSFORM_FLIP_V != 0);
    let dump = display::dump_due() || crate::usage::frame_wanted();
    let read_back = |p: &Process| p.gpu.read_pixels(cpu, s.width, s.height).map(|pixels| transformed(Frame { width: s.width, height: s.height, pixels }, transform));
    if !display::headless() && p.gpu.present(cpu, s.width, s.height, flip_h, flip_v) == crate::gpu::vulkan::Presented::Shown {
        let frame = if dump { read_back(p) } else { None };
        display::presented(p, frame.as_ref());
        return;
    }
    if display::headless() && !dump && p.gpu.rendered(cpu, s.width, s.height) {
        display::presented(p, None);
        return;
    }
    if let Some(frame) = read_back(p) {
        display::present(p, frame);
        return;
    }
    let (w, h) = (s.width as u64, s.height as u64);
    let row_bytes = if s.block_linear { (w * 4).div_ceil(64) * 64 } else { (s.pitch as u64).max(w * 4) };
    let gob_rows = 8u64 << s.block_height_log2;
    let size = if s.block_linear { row_bytes * h.div_ceil(gob_rows) * gob_rows } else { row_bytes * h };
    let Some(bytes) = p.memory.read(m.addr + s.offset, size) else {
        p.warn_once(format!("vi: buffer at {:#x} is not readable", m.addr + s.offset));
        return;
    };
    let mut pixels = vec![0u32; (w * h) as usize];
    for y in 0..h {
        for x in 0..w {
            let o = if s.block_linear {
                crate::gpu::block_linear_offset(x * 4, y, row_bytes, s.block_height_log2)
            } else {
                y * row_bytes + x * 4
            } as usize;
            let px = &bytes[o..o + 4];
            pixels[(y * w + x) as usize] = (px[0] as u32) << 16 | (px[1] as u32) << 8 | px[2] as u32;
        }
    }
    let frame = transformed(Frame { width: s.width, height: s.height, pixels }, transform);
    if !display::headless() && p.gpu.present_pixels(frame.width, frame.height, &frame.pixels) == crate::gpu::vulkan::Presented::Shown {
        display::presented(p, Some(&frame));
        return;
    }
    display::present(p, frame);
}

static VSYNC_EPOCH: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();

const ONE_BLANK: std::time::Duration = std::time::Duration::from_nanos(16_666_667);
const HYBRID_SPIN_TAIL: std::time::Duration = std::time::Duration::from_micros(400);

#[derive(Clone, Copy)]
struct Deadline {
    next_blank: u64,
    last_release: std::time::Duration,
}

impl Deadline {
    fn start(released: std::time::Duration) -> Self {
        Self { next_blank: blank_at(released) + 2, last_release: released }
    }

    fn wait(self, now: std::time::Duration) -> std::time::Duration {
        blank_time(self.next_blank).max(self.last_release + ONE_BLANK).saturating_sub(now)
    }

    fn advance(self, released: std::time::Duration, max_debt_periods: u64) -> (Self, bool) {
        let next_blank = self.next_blank + 2;
        // Change the rebase bound while keeping each nominal step at two blanks.
        if released > blank_time(self.next_blank + 2 * max_debt_periods) {
            (Self::start(released), true)
        } else {
            (Self { next_blank, last_release: released }, false)
        }
    }
}

fn blank_time(blank: u64) -> std::time::Duration {
    std::time::Duration::new(blank / 60, ((blank % 60) * 1_000_000_000 / 60) as u32)
}

fn blank_at(elapsed: std::time::Duration) -> u64 {
    // Invert the rounded-down blank_time, including its exact boundaries.
    (((elapsed.as_nanos() + 1) * 60 - 1) / 1_000_000_000) as u64
}

fn deadline_mode(deadline: &mut Option<Deadline>, interval: u32, uncapped: bool) -> bool {
    let active = interval == 2 && !uncapped;
    if !active {
        *deadline = None;
    }
    active
}

fn hybrid_coarse_sleep(remaining: std::time::Duration) -> std::time::Duration {
    remaining.saturating_sub(HYBRID_SPIN_TAIL)
}

#[derive(Debug, Eq, PartialEq)]
enum HybridTail {
    Done,
    Sleep(std::time::Duration),
    Spin,
}

fn hybrid_tail(remaining: std::time::Duration) -> HybridTail {
    if remaining.is_zero() {
        HybridTail::Done
    } else if remaining > HYBRID_SPIN_TAIL {
        HybridTail::Sleep(remaining)
    } else {
        HybridTail::Spin
    }
}

fn hybrid_wait_until(target: std::time::Instant) -> Option<std::time::Duration> {
    use std::time::Instant;

    let coarse = hybrid_coarse_sleep(target.saturating_duration_since(Instant::now()));
    if !coarse.is_zero() {
        std::thread::sleep(coarse);
    }
    let started = Instant::now();
    match hybrid_tail(target.saturating_duration_since(started)) {
        HybridTail::Done => None,
        HybridTail::Sleep(remaining) => {
            std::thread::sleep(remaining);
            None
        }
        HybridTail::Spin => loop {
            // A scheduler pause consumes the remaining wall-time budget.
            let now = Instant::now();
            if now >= target {
                return Some(now.saturating_duration_since(started));
            }
            std::hint::spin_loop();
        },
    }
}

#[derive(Default)]
struct DeadlineStats {
    releases: u64,
    sleep_calls: u64,
    sleep_requested_ns: u128,
    sleep_elapsed_ns: u128,
    hybrid_spin_calls: u64,
    hybrid_spin_wall_ns: u128,
    starts: u64,
    rebases: u64,
    extra_period_releases: u64,
    max_retained_debt_ns: u128,
}

struct PaceState {
    last: Option<u64>,
    deadline: Option<Deadline>,
    stats: Option<DeadlineStats>,
}

fn pace_deadline(state: &mut PaceState, epoch: std::time::Instant) {
    let diagnostics = crate::env_var!("KIRIKAE_VI_DEADLINE_STATS").is_some_and(|value| value == "1");
    let max_debt_periods = if crate::env_var!("KIRIKAE_VI_DEADLINE_MAX_DEBT_PERIODS") == Some(std::ffi::OsStr::new("2")) {
        2
    } else {
        1
    };
    let now = epoch.elapsed();
    let previous = state.deadline;
    let wait = match previous {
        Some(deadline) => deadline.wait(now),
        None => state.last.map_or(std::time::Duration::ZERO, |last| blank_time(last + 2).saturating_sub(now)),
    };
    let (sleep_started, spin_wall) = if wait.is_zero() {
        (None, None)
    } else {
        crate::display::PACED_NS.fetch_add(wait.as_nanos() as u64, Ordering::Relaxed);
        let started = diagnostics.then(|| epoch.elapsed());
        let spin_wall = if cfg!(windows)
            && crate::env_var!("KIRIKAE_VI_HYBRID_WAIT").is_some_and(|value| value == "1")
        {
            hybrid_wait_until(epoch + (now + wait))
        } else {
            std::thread::sleep(wait);
            None
        };
        (started, spin_wall)
    };
    let released = epoch.elapsed();
    let (next, rebased) = previous.map_or_else(
        || (Deadline::start(released), false),
        |deadline| deadline.advance(released, max_debt_periods),
    );
    state.deadline = Some(next);
    state.last = Some(blank_at(released));
    if diagnostics {
        let stats = state.stats.get_or_insert_with(DeadlineStats::default);
        stats.releases += 1;
        if let Some(started) = sleep_started {
            stats.sleep_calls += 1;
            stats.sleep_requested_ns += wait.as_nanos();
            stats.sleep_elapsed_ns += (released - started).as_nanos();
        }
        if let Some(elapsed) = spin_wall {
            stats.hybrid_spin_calls += 1;
            stats.hybrid_spin_wall_ns += elapsed.as_nanos();
        }
        stats.starts += previous.is_none() as u64;
        stats.rebases += rebased as u64;
        if let Some(deadline) = previous.filter(|_| !rebased) {
            stats.extra_period_releases += (released > blank_time(deadline.next_blank + 2)) as u64;
            stats.max_retained_debt_ns = stats.max_retained_debt_ns
                .max(released.saturating_sub(blank_time(deadline.next_blank)).as_nanos());
        }
        if stats.releases.is_multiple_of(256) {
            eprintln!("kirikae: vi deadline: releases={} sleep_calls={} requested_ns={} elapsed_ns={} starts={} rebases={} max_retained_debt_ns={} max_debt_periods={} extra_period_releases={} hybrid_spin_calls={} hybrid_spin_wall_ns={}",
                stats.releases, stats.sleep_calls, stats.sleep_requested_ns, stats.sleep_elapsed_ns,
                stats.starts, stats.rebases, stats.max_retained_debt_ns, max_debt_periods, stats.extra_period_releases,
                stats.hybrid_spin_calls, stats.hybrid_spin_wall_ns);
        }
    }
}

fn pace(interval: u32) {
    static LAST: Mutex<PaceState> = Mutex::new(PaceState { last: None, deadline: None, stats: None });
    let absolute = crate::env_var!("KIRIKAE_VI_ABSOLUTE_DEADLINE").is_some_and(|value| value == "1");
    if std::env::var_os("KIRIKAE_NO_FRAME_LIMIT").is_some() {
        if absolute {
            deadline_mode(&mut LAST.lock().unwrap().deadline, interval, true);
        }
        return;
    }
    let epoch = *VSYNC_EPOCH.get_or_init(std::time::Instant::now);
    let mut state = LAST.lock().unwrap();
    if absolute && deadline_mode(&mut state.deadline, interval, false) {
        pace_deadline(&mut state, epoch);
        return;
    }
    let blank = |n: u64| epoch + std::time::Duration::from_nanos(n * 1_000_000_000 / 60);
    let last = &mut state.last;
    let now = std::time::Instant::now();
    let current = (now.duration_since(epoch).as_nanos() * 60 / 1_000_000_000) as u64;
    match last.map(|l| l + interval as u64) {
        Some(target) if blank(target) > now => {
            let wait = blank(target) - now;
            crate::display::PACED_NS.fetch_add(wait.as_nanos() as u64, std::sync::atomic::Ordering::Relaxed);
            std::thread::sleep(wait);
            *last = Some(target);
        }
        _ => *last = Some(current),
    }
}

#[cfg(test)]
mod deadline_tests {
    use super::{Deadline, HYBRID_SPIN_TAIL, HybridTail, ONE_BLANK, blank_at, blank_time, deadline_mode, hybrid_coarse_sleep, hybrid_tail};
    use std::time::Duration;

    #[test]
    fn on_time_deadlines_follow_exact_30_hz_phase() {
        let mut deadline = Deadline::start(blank_time(1));
        for frame in 1..=300 {
            let target = blank_time(1 + 2 * frame);
            let ready = target - Duration::from_millis(1);
            let released = ready + deadline.wait(ready);
            assert_eq!(released, target);
            assert_eq!(blank_at(released), 1 + 2 * frame);
            let (next, rebased) = deadline.advance(released, 1);
            assert!(!rebased);
            deadline = next;
        }
        assert_eq!(deadline.last_release - blank_time(1), Duration::from_secs(10));
    }

    #[test]
    fn sub_blank_lateness_can_recover_next_nominal_release() {
        let deadline = Deadline::start(blank_time(2));
        let late = blank_time(4) + Duration::from_millis(8);
        assert_eq!(deadline.wait(late), Duration::ZERO);
        let (next, rebased) = deadline.advance(late, 1);
        assert!(!rebased);
        let ready = late + Duration::from_millis(8);
        assert_eq!(ready + next.wait(ready), blank_time(6));
    }

    #[test]
    fn one_period_late_preserves_phase_and_full_blank_spacing() {
        let deadline = Deadline::start(blank_time(2));
        let late = blank_time(6);
        let (next, rebased) = deadline.advance(late, 1);
        assert!(!rebased);
        assert_eq!(next.next_blank, 6);
        assert_eq!(next.wait(late), ONE_BLANK);
        let (third, rebased) = next.advance(late + ONE_BLANK, 1);
        assert!(!rebased);
        assert_eq!(third.next_blank, 8);
        assert_eq!(late + ONE_BLANK + third.wait(late + ONE_BLANK), late + ONE_BLANK * 2);
    }

    #[test]
    fn sustained_slow_work_rebases_without_building_more_than_one_period_of_debt() {
        let mut deadline = Deadline::start(blank_time(2));
        let mut rebases = 0;
        for _ in 0..60 {
            let previous = deadline.last_release;
            let ready = previous + Duration::from_millis(40);
            let released = ready + deadline.wait(ready);
            let target = deadline.next_blank;
            let (next, rebased) = deadline.advance(released, 1);
            assert!(released - previous >= ONE_BLANK);
            assert!(next.next_blank > target);
            if rebased {
                assert_eq!(next.next_blank, blank_at(released) + 2);
                rebases += 1;
            } else {
                assert!(released <= blank_time(next.next_blank));
            }
            deadline = next;
        }
        assert!(rebases > 0);
    }

    #[test]
    fn observed_oversleep_past_bound_rebases_at_actual_release() {
        let deadline = Deadline::start(blank_time(2));
        let ready = blank_time(3);
        assert_eq!(ready + deadline.wait(ready), blank_time(4));
        for released in [blank_time(6) + Duration::from_nanos(1), blank_time(180)] {
            let (next, rebased) = deadline.advance(released, 1);
            assert!(rebased);
            assert_eq!(next.next_blank, blank_at(released) + 2);
            assert_eq!(next.last_release, released);
        }
    }

    #[test]
    fn other_intervals_and_uncapped_clear_deadline() {
        for (interval, uncapped) in [(0, false), (1, false), (3, false), (4, false), (2, true)] {
            let mut deadline = Some(Deadline::start(blank_time(2)));
            assert!(!deadline_mode(&mut deadline, interval, uncapped));
            assert!(deadline_mode(&mut deadline, 2, false));
            assert!(deadline.is_none());
        }
    }

    #[test]
    fn two_period_boundary_is_inclusive_and_catch_up_keeps_blank_spacing() {
        let deadline = Deadline::start(blank_time(2));
        let late = blank_time(8);
        assert!(deadline.advance(late, 1).1);
        let (next, rebased) = deadline.advance(late, 2);
        assert!(!rebased);
        assert_eq!(next.next_blank, 6);
        assert_eq!(next.wait(late), ONE_BLANK);
        assert_eq!(next.advance(late + ONE_BLANK, 2).0.next_blank, 8);

        let (next, rebased) = deadline.advance(late + Duration::from_nanos(1), 2);
        assert!(rebased);
        assert_eq!(next.next_blank, 10);
        assert_eq!(next.wait(next.last_release), blank_time(10) - next.last_release);
    }

    #[test]
    fn jitter_trace_recovers_a_period_before_the_larger_stall() {
        let work_ms = [29, 28, 29, 59, 55, 24, 25, 29, 28, 29, 30, 30, 29, 29, 27, 30, 150, 24, 29];
        let run = |max_debt_periods| {
            let mut deadline = Deadline::start(blank_time(2));
            let mut releases = Vec::new();
            let mut rebases = Vec::new();
            for (frame, work) in work_ms.into_iter().enumerate() {
                let ready = deadline.last_release + Duration::from_millis(work);
                let wait = deadline.wait(ready);
                let oversleep = if !wait.is_zero() && matches!(frame, 1 | 12) {
                    Duration::from_micros(400)
                } else {
                    Duration::ZERO
                };
                let released = ready + wait + oversleep;
                assert!(released - deadline.last_release >= ONE_BLANK);
                assert!(released >= blank_time(deadline.next_blank));
                let (next, rebased) = deadline.advance(released, max_debt_periods);
                assert!(next.next_blank >= deadline.next_blank + 2);
                if rebased {
                    rebases.push(frame + 1);
                }
                releases.push(released.as_nanos());
                deadline = next;
            }
            (releases, rebases)
        };
        let (one, one_rebases) = run(1);
        let (two, two_rebases) = run(2);
        assert_eq!(one, [
            66_666_666, 100_400_000, 133_333_333, 192_333_333, 247_333_333, 271_333_333,
            300_000_000, 333_333_333, 366_666_666, 400_000_000, 433_333_333, 466_666_666,
            500_400_000, 533_333_333, 566_666_666, 600_000_000, 750_000_000, 783_333_333, 816_666_666,
        ]);
        assert_eq!(two, [
            66_666_666, 100_400_000, 133_333_333, 192_333_333, 247_333_333, 271_333_333,
            296_333_333, 325_333_333, 353_333_333, 382_333_333, 412_333_333, 442_333_333,
            471_333_333, 500_333_333, 533_333_333, 566_666_666, 716_666_666, 750_000_000, 783_333_333,
        ]);
        assert_eq!(one_rebases, [5, 17]);
        assert_eq!(two_rebases, [17]);
    }

    #[test]
    fn hybrid_coarse_sleep_preserves_the_absolute_tail() {
        assert_eq!(hybrid_coarse_sleep(Duration::from_millis(1)), Duration::from_micros(600));
        for remaining in [Duration::ZERO, Duration::from_micros(120), HYBRID_SPIN_TAIL] {
            assert_eq!(hybrid_coarse_sleep(remaining), Duration::ZERO);
        }
    }

    #[test]
    fn hybrid_tail_spins_only_inside_the_bound_after_wake() {
        let target = Duration::from_millis(1);
        for (wake, action) in [
            (Duration::from_micros(500), HybridTail::Sleep(Duration::from_micros(500))),
            (Duration::from_micros(600) - Duration::from_nanos(1), HybridTail::Sleep(HYBRID_SPIN_TAIL + Duration::from_nanos(1))),
            (Duration::from_micros(600), HybridTail::Spin),
            (Duration::from_micros(970), HybridTail::Spin),
            (target, HybridTail::Done),
            (Duration::from_micros(1040), HybridTail::Done),
        ] {
            assert_eq!(hybrid_tail(target.saturating_sub(wake)), action);
        }
    }
}

struct ParcelReader<'a> {
    payload: &'a [u8],
    pos: usize,
}

impl<'a> ParcelReader<'a> {
    fn new(parcel: &'a [u8]) -> Self {
        let u = |o: usize| parcel.get(o..o + 4).map_or(0, |b| u32::from_le_bytes(b.try_into().unwrap())) as usize;
        let (size, offset) = (u(0), u(4));
        let payload = parcel.get(offset..offset.saturating_add(size)).unwrap_or(&[]);
        ParcelReader { payload, pos: 0 }
    }

    fn i32(&mut self) -> i32 {
        let v = self.payload.get(self.pos..self.pos + 4).map_or(0, |b| i32::from_le_bytes(b.try_into().unwrap()));
        self.pos += 4;
        v
    }

    fn skip_interface_token(&mut self) {
        self.i32();
        let len = self.i32();
        if len > 0 {
            self.pos += ((len as usize + 1) * 2).next_multiple_of(4);
        }
    }

    fn flattenable(&mut self) -> Option<Vec<u8>> {
        let start = self.pos;
        let len = self.i32() as usize;
        let fds = self.i32() as usize;
        let end = self.pos + (len + fds * 4).next_multiple_of(4);
        let raw = self.payload.get(start..end)?.to_vec();
        self.pos = end;
        Some(raw)
    }
}

#[derive(Default)]
struct ParcelWriter {
    payload: Vec<u8>,
}

impl ParcelWriter {
    fn i32(&mut self, v: i32) {
        self.payload.extend_from_slice(&v.to_le_bytes());
    }

    fn i64(&mut self, v: i64) {
        self.payload.extend_from_slice(&v.to_le_bytes());
    }

    fn bytes(&mut self, b: &[u8]) {
        self.payload.extend_from_slice(b);
        while !self.payload.len().is_multiple_of(4) {
            self.payload.push(0);
        }
    }

    fn finish(self) -> Vec<u8> {
        self.finish_with_objects(&[])
    }

    fn finish_with_objects(self, objects: &[u32]) -> Vec<u8> {
        let size = self.payload.len() as u32;
        let objects_size = objects.len() as u32 * 4;
        let mut out = Vec::new();
        for v in [size, 0x10, objects_size, 0x10 + size] {
            out.extend_from_slice(&v.to_le_bytes());
        }
        out.extend_from_slice(&self.payload);
        for o in objects {
            out.extend_from_slice(&o.to_le_bytes());
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn presentation_flips() {
        let frame = || Frame { width: 3, height: 2, pixels: vec![1, 2, 3, 4, 5, 6] };
        assert_eq!(transformed(frame(), 0).pixels, [1, 2, 3, 4, 5, 6]);
        assert_eq!(transformed(frame(), TRANSFORM_FLIP_V).pixels, [4, 5, 6, 1, 2, 3]);
        assert_eq!(transformed(frame(), TRANSFORM_FLIP_H).pixels, [3, 2, 1, 6, 5, 4]);
        assert_eq!(transformed(frame(), TRANSFORM_FLIP_H | TRANSFORM_FLIP_V).pixels, [6, 5, 4, 3, 2, 1]);
    }

    #[test]
    fn parcel_round_trip() {
        let mut w = ParcelWriter::default();
        w.i32(0x100);
        let name: Vec<u16> = "android.gui.IGraphicBufferProducer".encode_utf16().collect();
        w.i32(name.len() as i32);
        let mut s: Vec<u8> = name.iter().flat_map(|c| c.to_le_bytes()).collect();
        s.extend_from_slice(&[0, 0]);
        w.bytes(&s);
        w.i32(7);
        w.i32(0x10);
        w.i32(0);
        w.bytes(&[0xab; 0x10]);
        let parcel = w.finish();
        let mut r = ParcelReader::new(&parcel);
        r.skip_interface_token();
        assert_eq!(r.i32(), 7);
        let f = r.flattenable().unwrap();
        assert_eq!(f.len(), 8 + 0x10);
        assert_eq!(f[8], 0xab);
    }
}
