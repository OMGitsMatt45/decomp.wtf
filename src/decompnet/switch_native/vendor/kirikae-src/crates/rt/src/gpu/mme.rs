pub trait Host {
    fn write(&mut self, method: u32, value: u32);
    fn read(&mut self, method: u32) -> u32;

    /// Replace the exact BEGIN/indexed-draw/END instance loop with equivalent
    /// work and register state. A declined batch must have no side effects.
    fn draw_indexed_instances(&mut self, _first_begin: u32, _subsequent_begin: u32, _index_count: u32, _instance_count: u32) -> bool {
        false
    }

    /// The corresponding non-indexed BEGIN/vertex-draw/END instance loop.
    fn draw_vertex_instances(&mut self, _first_begin: u32, _subsequent_begin: u32, _vertex_count: u32, _instance_count: u32) -> bool {
        false
    }
}

const STEP_LIMIT: usize = 1 << 20;

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    Undefined { pc: usize, word: u32 },
    OutOfBounds(usize),
    TooLong,
}

struct Machine<'a, H: Host> {
    regs: [u32; 8],
    carry: bool,
    method: u32,
    increment: u32,
    params: std::slice::Iter<'a, u32>,
    host: &'a mut H,
}

impl<H: Host> Machine<'_, H> {
    fn set(&mut self, r: u32, v: u32) {
        if r != 0 {
            self.regs[r as usize] = v;
        }
    }

    fn param(&mut self) -> u32 {
        self.params.next().copied().unwrap_or(0)
    }

    fn set_method(&mut self, v: u32) {
        self.method = v & 0xfff;
        self.increment = (v >> 12) & 0x3f;
    }

    fn send(&mut self, v: u32) {
        self.host.write(self.method, v);
        self.method = (self.method + self.increment) & 0xfff;
    }

    fn step(&mut self, pc: usize, w: u32) -> Result<(), Error> {
        let (dst, a, b) = ((w >> 8) & 7, self.regs[((w >> 11) & 7) as usize], self.regs[((w >> 14) & 7) as usize]);
        let imm = ((w as i32) >> 14) as u32;
        let (src_pos, size, dst_pos) = ((w >> 17) & 31, (w >> 22) & 31, (w >> 27) & 31);
        let mask = ((1u64 << size) - 1) as u32;
        let result = match w & 7 {
            0 => {
                let (r, c) = match (w >> 17) & 31 {
                    0 => add(a, b, false),
                    1 => add(a, b, self.carry),
                    2 => add(a, !b, true),
                    3 => add(a, !b, self.carry),
                    8 => (a ^ b, self.carry),
                    9 => (a | b, self.carry),
                    10 => (a & b, self.carry),
                    11 => (a & !b, self.carry),
                    12 => (!(a & b), self.carry),
                    _ => return Err(Error::Undefined { pc, word: w }),
                };
                self.carry = c;
                r
            }
            1 => a.wrapping_add(imm),
            2 => (a & !(mask << dst_pos)) | (((b >> src_pos) & mask) << dst_pos),
            3 => ((b >> (a & 31)) & mask) << dst_pos,
            4 => ((b >> src_pos) & mask) << (a & 31),
            5 => {
                let v = self.host.read(a.wrapping_add(imm) & 0xfff);
                self.set(dst, v);
                return Ok(());
            }
            _ => return Err(Error::Undefined { pc, word: w }),
        };
        match (w >> 4) & 7 {
            0 => {
                let p = self.param();
                self.set(dst, p);
            }
            1 => self.set(dst, result),
            2 => {
                self.set_method(result);
                self.set(dst, result);
            }
            3 => {
                self.send(result);
                let p = self.param();
                self.set(dst, p);
            }
            4 => {
                self.send(result);
                self.set(dst, result);
            }
            5 => {
                self.set_method(result);
                let p = self.param();
                self.set(dst, p);
            }
            6 => {
                self.set_method(result);
                self.set(dst, result);
                let p = self.param();
                self.send(p);
            }
            _ => {
                self.set_method(result);
                self.send((result >> 12) & 0x3f);
                self.set(dst, result);
            }
        }
        Ok(())
    }
}

fn add(a: u32, b: u32, carry: bool) -> (u32, bool) {
    let r = a as u64 + b as u64 + carry as u64;
    (r as u32, r >> 32 != 0)
}

pub fn run(code: &[u32], start: usize, params: &[u32], host: &mut impl Host) -> Result<(), Error> {
    let mut m = Machine { regs: [0; 8], carry: false, method: 0, increment: 0, params: params.iter(), host };
    m.regs[1] = m.param();
    run_machine(&mut m, code, start, STEP_LIMIT, true)
}

// Match every instruction, including the delayed branch and BEGIN mode update.
// These loops consume no parameters and change only r1, r2, their loop counter
// and method state.
const INDEXED_INSTANCE_LOOP: [u32; 9] = [
    0x01618021, 0x00000841, 0x017e0021, 0x00003041, 0x01614071,
    0xffffed11, 0x00004211, 0xfffe6817, 0xd0808912,
];
const INDEXED_INSTANCE_LOOP_30: [u32; 9] = [
    0x01618021, 0x00000841, 0x017e0021, 0x00002841, 0x01614071,
    0xffffe411, 0x00004211, 0xfffe6017, 0xd0808912,
];
const VERTEX_INSTANCE_LOOP: [u32; 9] = [
    0x01618021, 0x00000841, 0x00d78021, 0x00002041, 0x01614071,
    0xffffdb11, 0x00004211, 0xfffe5817, 0xd0808912,
];

fn run_machine(m: &mut Machine<'_, impl Host>, code: &[u32], start: usize, limit: usize, batch: bool) -> Result<(), Error> {
    let mut pc = start;
    let mut branch: Option<usize> = None;
    let mut exit = false;
    let mut steps = 0;
    while steps < limit {
        if batch && !exit && branch.is_none() && m.regs[0] == 0 && code.get(pc) == Some(&0x01618021) {
            let pattern = code.get(pc..pc.saturating_add(9));
            let registers = if pattern == Some(INDEXED_INSTANCE_LOOP.as_slice()) { Some((6,5,true)) }
                else if pattern == Some(INDEXED_INSTANCE_LOOP_30.as_slice()) { Some((5,4,true)) }
                else if pattern == Some(VERTEX_INSTANCE_LOOP.as_slice()) { Some((4,3,false)) }
                else { None };
            if let Some((count, counter, indexed)) = registers {
                let instances = m.regs[counter];
                if instances != 0 && instances as usize <= (limit - steps) / 9 {
                    let first = m.regs[1];
                    let subsequent = first & !(3 << 26) | 1 << 26;
                    let accepted = if indexed { m.host.draw_indexed_instances(first, subsequent, m.regs[count], instances) }
                        else { m.host.draw_vertex_instances(first, subsequent, m.regs[count], instances) };
                    if accepted {
                        steps += instances as usize * 9;
                        m.regs[1] = subsequent;
                        m.regs[2] = 1;
                        m.regs[counter] = 0;
                        m.set_method(0x585);
                        pc += 9;
                        continue;
                    }
                }
            }
        }
        steps += 1;
        let w = code.get(pc).copied().ok_or(Error::OutOfBounds(pc))?;
        let mut next = pc + 1;
        let (mut new_branch, mut new_exit) = (None, false);
        if w & 7 == 7 {
            let a = m.regs[((w >> 11) & 7) as usize];
            let taken = (a == 0) != (w & 0x10 != 0);
            let target = pc.wrapping_add_signed(((w as i32) >> 14) as isize);
            match (taken, w & 0x20 != 0) {
                (true, true) => next = target,
                (true, false) => new_branch = Some(target),
                (false, _) => new_exit = w & 0x80 != 0,
            }
        } else {
            m.step(pc, w)?;
            new_exit = w & 0x80 != 0;
        }
        if let Some(target) = branch.take() {
            next = target;
        }
        if exit {
            return Ok(());
        }
        (branch, exit, pc) = (new_branch, new_exit, next);
    }
    Err(Error::TooLong)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct Log {
        writes: Vec<(u32, u32)>,
        regs: std::collections::HashMap<u32, u32>,
    }

    impl Host for Log {
        fn write(&mut self, method: u32, value: u32) {
            self.writes.push((method, value));
        }
        fn read(&mut self, method: u32) -> u32 {
            self.regs.get(&method).copied().unwrap_or(0)
        }
    }

    const PARM: u32 = 0 << 4;
    const MOV: u32 = 1 << 4;
    const MADDR: u32 = 2 << 4;
    const SEND: u32 = 4 << 4;
        const EXIT: u32 = 0x80;

    fn alu(op: u32, asg: u32, d: u32, a: u32, b: u32) -> u32 {
        asg | (d << 8) | (a << 11) | (b << 14) | (op << 17)
    }
    fn addi(asg: u32, d: u32, a: u32, imm: i32) -> u32 {
        1 | asg | (d << 8) | (a << 11) | ((imm as u32) << 14)
    }
    fn braz(a: u32, off: i32, annul: bool) -> u32 {
        7 | ((annul as u32) << 5) | (a << 11) | ((off as u32) << 14)
    }
    fn branz(a: u32, off: i32, annul: bool) -> u32 {
        braz(a, off, annul) | 0x10
    }

    #[test]
    fn sends_parameters_to_consecutive_methods() {
        let code = [
            addi(MADDR, 0, 1, 0),
            addi(PARM, 2, 0, 0),
            addi(SEND, 0, 2, 0),
            addi(PARM, 2, 0, 0),
            addi(SEND, 0, 2, 0) | EXIT,
            addi(MOV, 3, 0, 7),
        ];
        let mut log = Log::default();
        run(&code, 0, &[0x1000 | 0x200, 0xaa, 0xbb], &mut log).unwrap();
        assert_eq!(log.writes, vec![(0x200, 0xaa), (0x201, 0xbb)]);
    }

    #[test]
    fn loop_with_delay_slot_and_carry() {
        let code = [
            addi(MADDR, 0, 0, 0x300),
            addi(MOV, 2, 0, 5),
            addi(SEND, 2, 2, 1),
            addi(MOV, 1, 1, -1),
            branz(1, -2, false),
            addi(MOV, 4, 0, 1),
            alu(0, MOV, 5, 0, 0) | EXIT,
            0,
        ];
        let mut log = Log::default();
        run(&code, 0, &[3], &mut log).unwrap();
        assert_eq!(log.writes, vec![(0x300, 6), (0x300, 7), (0x300, 8)]);
        let code = [
            addi(MOV, 2, 0, -1),
            addi(MOV, 3, 0, 1),
            alu(0, MOV, 4, 2, 3),
            alu(1, MOV, 5, 0, 0),
            addi(MADDR, 0, 0, 0x10),
            addi(SEND, 0, 5, 0) | EXIT,
            0,
        ];
        let mut log = Log::default();
        run(&code, 0, &[0], &mut log).unwrap();
        assert_eq!(log.writes, vec![(0x10, 1)]);
    }

    #[test]
    fn exit_in_the_delay_slot_of_a_taken_branch() {
        let code = [
            addi(MADDR, 0, 0, 0x30),
            addi(SEND, 0, 0, 1),
            braz(0, -1, false),
            addi(MOV, 2, 0, 0) | EXIT,
            0,
        ];
        let mut log = Log::default();
        run(&code, 0, &[0], &mut log).unwrap();
        assert_eq!(log.writes, vec![(0x30, 1), (0x30, 1)]);
    }

    #[test]
    fn bitfields_reads_and_annulled_branches() {
        let mut log = Log::default();
        log.regs.insert(0x123, 0xabcd_1234);
        let code = [
            5 | MOV | (2 << 8) | (0x123 << 14),
            4 | MOV | (3 << 8) | (2 << 14) | (8 << 17) | (8 << 22),
            braz(0, 3, true),
            addi(MOV, 3, 0, 0x7777),
            0,
            addi(MADDR, 0, 0, 0x20),
            addi(SEND, 0, 3, 0) | EXIT,
            0,
        ];
        run(&code, 0, &[0], &mut log).unwrap();
        assert_eq!(log.writes, vec![(0x20, 0x12)]);
    }

    // Captured indexed-instanced macro, including parameter reads, the loop,
    // and restoration of base vertex/instance and driver constant-buffer words.
    const INDEXED_MACRO: [u32; 31] = [
        0x00000601, 0x00000501, 0x0346c215, 0x017dc061, 0x01118451,
        0x00002041, 0x05434021, 0x00002331, 0x00001841, 0x0638c021,
        0x01900041, 0x00155510, 0x00002041, 0x0002e807, 0x00001841,
        0x01618021, 0x00000841, 0x017e0021, 0x00003041, 0x01614071,
        0xffffed11, 0x00004211, 0xfffe6817, 0xd0808912, 0x01118071,
        0x01434071, 0x01438071, 0x0638c021, 0x01900041, 0x000000c1,
        0x00000041,
    ];
    const INDEXED_MACRO_30: [u32; 23] = [
        0x00000501,0x0346c215,0x00000401,0x017dc061,0x01118351,
        0x00001841,0x05434021,0x00151410,0x00001a31,0x0002e007,
        0x00001041,0x01618021,0x00000841,0x017e0021,0x00002841,
        0x01614071,0xffffe411,0x00004211,0xfffe6017,0xd0808912,
        0x01118071,0x014340f1,0x01438071,
    ];
    const VERTEX_MACRO_27: [u32; 18] = [
        0x0346c215,0x00000401,0x00000301,0x0014d310,0x00d74061,
        0x0002d807,0x01438061,0x01618021,0x00000841,0x00d78021,
        0x00002041,0x01614071,0xffffdb11,0x00004211,0xfffe5817,
        0xd0808912,0x014380f1,0x00000011,
    ];

    #[derive(Clone, Debug, Default, PartialEq, Eq)]
    struct InstanceLog {
        writes: Vec<(u32, u32)>,
        reads: Vec<u32>,
        registers: std::collections::BTreeMap<u32, u32>,
        batches: Vec<(u32, u32, u32, u32)>,
        vertex_batches: Vec<(u32, u32, u32, u32)>,
        accept: bool,
    }
    impl Host for InstanceLog {
        fn write(&mut self, method: u32, value: u32) {
            self.writes.push((method, value));
            self.registers.insert(method, value);
        }
        fn read(&mut self, method: u32) -> u32 {
            self.reads.push(method);
            self.registers.get(&method).copied().unwrap_or(0)
        }
        fn draw_indexed_instances(&mut self, first: u32, subsequent: u32, count: u32, instances: u32) -> bool {
            if !self.accept { return false; }
            self.batches.push((first, subsequent, count, instances));
            // Expand the observable host protocol for comparison with the
            // reference interpreter; a real host may consolidate this work.
            for instance in 0..instances {
                self.write(0x586, if instance == 0 { first } else { subsequent });
                self.write(0x5f8, count);
                self.write(0x585, 0);
            }
            true
        }
        fn draw_vertex_instances(&mut self, first: u32, subsequent: u32, count: u32, instances: u32) -> bool {
            if !self.accept { return false; }
            self.vertex_batches.push((first, subsequent, count, instances));
            for instance in 0..instances {
                self.write(0x586, if instance == 0 { first } else { subsequent });
                self.write(0x35e, count);
                self.write(0x585, 0);
            }
            true
        }
    }
    #[derive(Debug, PartialEq, Eq)]
    struct Snapshot {
        result: Result<(), Error>,
        regs: [u32; 8],
        carry: bool,
        method: u32,
        increment: u32,
        parameters_left: Vec<u32>,
    }
    fn recorded_run(code: &[u32], regs: [u32; 8], carry: bool, params: &[u32], log: &mut InstanceLog, limit: usize, batch: bool) -> Snapshot {
        let mut m = Machine { regs, carry, method: 0x5ab, increment: 17, params: params.iter(), host: log };
        let result = run_machine(&mut m, code, 0, limit, batch);
        Snapshot { result, regs: m.regs, carry: m.carry, method: m.method, increment: m.increment, parameters_left: m.params.as_slice().to_vec() }
    }
    fn compare_runs(code: &[u32], regs: [u32; 8], carry: bool, params: &[u32], initial: InstanceLog, limit: usize) -> (Snapshot, InstanceLog) {
        let mut reference = initial.clone();
        let expected = recorded_run(code, regs, carry, params, &mut reference, limit, false);
        let mut fast = initial;
        let actual = recorded_run(code, regs, carry, params, &mut fast, limit, true);
        assert_eq!(actual, expected);
        assert_eq!(fast.writes, reference.writes);
        assert_eq!(fast.reads, reference.reads);
        assert_eq!(fast.registers, reference.registers);
        (actual, fast)
    }

    #[test]
    fn batches_captured_instance_macro_with_identical_state_and_writes() {
        let mut seed = 0x7a42_b9e1u32;
        let mut next = || { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; seed };
        for case in 0..512 {
            let mut regs = std::array::from_fn(|_| next());
            regs[0] = 0;
            let begin = next();
            regs[1] = begin;
            let instances = case % 65;
            let mask = next();
            let params = [next(), instances, next(), next(), next(), next(), next()];
            let mut initial = InstanceLog { accept: case & 1 == 0, ..InstanceLog::default() };
            initial.registers.insert(0xd1b, mask);
            initial.registers.insert(0x446, next());
            initial.registers.insert(0x586, next());
            let (state, fast) = compare_runs(&INDEXED_MACRO, regs, case & 2 != 0, &params, initial, 4096);
            assert_eq!(state.result, Ok(()));
            let count = instances & mask;
            assert_eq!(fast.batches.len(), usize::from(case & 1 == 0 && count != 0));
            if let Some(&(first, subsequent, _, actual_count)) = fast.batches.first() {
                assert_eq!(first, begin);
                assert_eq!(subsequent, begin & !(3 << 26) | 1 << 26);
                assert_eq!(actual_count, count);
            }
        }
    }

    #[test]
    fn batching_preserves_step_limit_and_declined_or_modified_loops() {
        for (template,count,counter) in [(INDEXED_INSTANCE_LOOP,6,5),(INDEXED_INSTANCE_LOOP_30,5,4),(VERTEX_INSTANCE_LOOP,4,3)] {
            let mut code = template.to_vec();
            code.extend([addi(MOV, 3, 0, 17) | EXIT, addi(SEND, 0, 2, 0)]);
            let mut regs = [0, 0xfc00_0003, 0x1234, 7, 0xfeed, 6, 42, 0xabcd];
            regs[count]=42; regs[counter]=6;
            let initial = InstanceLog { accept: true, ..InstanceLog::default() };
            for limit in [1, 8, 9, 17, 53, 54, 55, 56, 100] {
                let (state, _) = compare_runs(&code, regs, true, &[9, 8, 7], initial.clone(), limit);
                assert_eq!(state.result.is_ok(), limit >= 56);
            }
            let mut changed = code.clone();
            changed[0] ^= 1 << 14;
            let (_, fast) = compare_runs(&changed, regs, false, &[], initial.clone(), 100);
            assert!(fast.batches.is_empty() && fast.vertex_batches.is_empty());

            let mut delayed = vec![braz(0, 10, false)];
            delayed.extend_from_slice(&code);
            let (_, fast) = compare_runs(&delayed, regs, true, &[], initial.clone(), 100);
            assert!(fast.batches.is_empty() && fast.vertex_batches.is_empty());
            let mut exiting = vec![addi(MOV, 3, 0, 0) | EXIT];
            exiting.extend_from_slice(&code);
            let (_, fast) = compare_runs(&exiting, regs, false, &[], initial, 100);
            assert!(fast.batches.is_empty() && fast.vertex_batches.is_empty());
        }
    }

    #[test]
    fn batches_captured_indexed_30_and_vertex_27_macros() {
        let mut seed = 0xd41a_27c3u32;
        let mut next = || { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; seed };
        for (code,indexed) in [(INDEXED_MACRO_30.as_slice(),true),(VERTEX_MACRO_27.as_slice(),false)] {
            for case in 0..512 {
                let mut regs=std::array::from_fn(|_| next()); regs[0]=0;
                regs[1]=next();
                let instances=case%129;
                let mask=next();
                let params=[next(),instances,next(),next(),next(),next(),next()];
                let mut initial=InstanceLog { accept:case&1==0,..InstanceLog::default() };
                initial.registers.insert(0xd1b,mask);
                initial.registers.insert(0x35d,next());
                initial.registers.insert(0x5f7,next());
                let (state,fast)=compare_runs(code,regs,case&2!=0,&params,initial,4096);
                assert_eq!(state.result,Ok(()));
                let calls=usize::from(case&1==0 && instances&mask!=0);
                assert_eq!(fast.batches.len(),if indexed {calls}else{0});
                assert_eq!(fast.vertex_batches.len(),if indexed {0}else{calls});
            }
            for instances in [0,1,2,6,75,996,3393] {
                let regs=[0,4,0,0,0,0,0,0];
                let mut initial=InstanceLog { accept:true,..InstanceLog::default() };
                initial.registers.insert(0xd1b,u32::MAX);
                let params=[if indexed {1536}else{3},instances,0,0,0,0];
                let (state,fast)=compare_runs(code,regs,true,&params,initial,STEP_LIMIT);
                assert_eq!(state.result,Ok(()));
                assert_eq!(fast.writes.iter().filter(|(method,_)| *method==0x585).count(),instances as usize);
            }
        }
    }
}
