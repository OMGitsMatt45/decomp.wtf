"""Offline, dependency-free build of the pinned nxport/LASRecomp source emitter."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .. import pc, toolchains

ROOT = Path(__file__).parent


def sources():
    return json.loads((ROOT / 'sources.json').read_text())


def verify_vendor():
    root = ROOT / 'vendor/nxport-lifter'
    files = sources()['vendored']['files']
    for name, expected in files.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise pc.PCError('Switch emitter source differs from its pin: ' + name)
    return root


def _run(command, *, cwd=None):
    try:
        result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise pc.PCError('Switch emitter compiler could not run: ' + str(error)) from error
    if result.returncode:
        raise pc.PCError('Switch emitter build failed:\n' + result.stderr[-6000:])
    return result.stdout


def _recover_jump_tables(lifter, replace_once):
    jt = lifter / 'src/jt.rs'
    replace_once(jt, 'const WINDOW: u64 = 24;', 'pub(crate) const WINDOW: u64 = 24;')
    replace_once(jt, '''pub fn resolve(mem: &dyn Memory, entry: u64, pc: u64, r: u32) -> Option<Vec<u64>> {
    let Sym::Target''', '''pub fn resolve(mem: &dyn Memory, entry: u64, pc: u64, r: u32) -> Option<Vec<u64>> {
    resolve_with_recovery(mem, entry, pc, pc, r, |_, _| None, |_, _| None)
}

pub fn constant_at(mem: &dyn Memory, entry: u64, definition: u64, r: u32) -> Option<u64> {
    match value(mem, entry, definition + 4, r, 0)? {
        Sym::Const(address) => Some(address),
        _ => None,
    }
}

pub fn resolve_with_recovery(
    mem: &dyn Memory, entry: u64, pc: u64, branch: u64, r: u32,
    recover_base: impl FnOnce(u64, u32) -> Option<u64>,
    recover_bound: impl FnOnce(u64, u32) -> Option<u64>,
) -> Option<Vec<u64>> {
    let Sym::Target''')
    replace_once(jt, '    let count = bound(mem, entry, at, idx)?;', '''    // The value may have been formed before a later scheduled instruction.
    let adjacent_halfword = size == 2 && !signed && shift == 2 && base == branch + 4;
    let count = bound(mem, entry, at, idx).or_else(|| {
        // Only an unextended X index with a locally resolved table base.
        if adjacent_halfword && table.is_some() && bits(mem.word(at)?, 13, 3) == 3 {
            recover_bound(at, idx)
        } else {
            None
        }
    })?;''')
    replace_once(jt, '    let raw = mem.bytes(table?, (count as usize) * size as usize)?;', '''    // A byte-offset table can reuse a base register from an earlier block
    // and branch back to cases near the dispatch.
    let nearby_backward = size == 1 && base < branch && branch - base <= u8::MAX as u64 * 4;
    let table = match table {
        Some(table) => table,
        None if adjacent_halfword || (!signed && shift == 2 && nearby_backward) => {
            recover_base(at, bits(mem.word(at)?, 5, 5))?
        }
        None => return None,
    };
    let load = Load { table: Some(table), idx, size, signed, scale, at };
    let mut targets = table_targets(mem, base, load, shift, count)?;
    targets.sort_unstable();
    targets.dedup();
    Some(targets)
}

// Retain order and duplicate case destinations so a nested switch can
// recover which selectors enter its parent case.
pub(crate) fn ordered_halfword_cases(
    mem: &dyn Memory, entry: u64, branch: u64, r: u32,
    writes_register: impl Fn(u64, u32) -> bool,
    prove_bound: impl FnOnce(u64, u32, u64) -> Option<(u64, u64)>,
) -> Option<Vec<u64>> {
    let (load, anchor) = adjacent_halfword_table(mem, entry, branch, r, &writes_register)?;
    let (count, checked_start) = prove_bound(load.at, load.idx, anchor)?;
    if adjacent_halfword_table(mem, checked_start, branch, r, &writes_register)? != (load, anchor) { return None; }
    table_targets(mem, branch + 4, load, 2, count)
}

pub(crate) fn local_halfword_table(mem: &dyn Memory, start: u64, branch: u64, r: u32, at: u64,
                                   writes_register: impl Fn(u64, u32) -> bool) -> Option<()> {
    let (load, _) = adjacent_halfword_table(mem, start, branch, r, &writes_register)?;
    (load.at == at).then_some(())
}

fn adjacent_halfword_table(mem: &dyn Memory, start: u64, branch: u64, reg: u32,
                           writes_register: &impl Fn(u64, u32) -> bool) -> Option<(Load, u64)> {
    let Sym::Target { base, load, .. } = value(mem, start, branch, reg, 0)? else { return None };
    if base != branch + 4 || load.idx == 31 || load.table.is_none() { return None; }
    let last_writer = |before, r| (start..before).step_by(4).filter(|&pc| writes_register(pc, r)).last();
    let add = last_writer(branch, reg)?;
    let w = mem.word(add)?;
    if w & 0xffe0_fc00 != 0x8b00_0800 { return None; } // add Xd, Xn, Xm, lsl #2
    let anchor = last_writer(add, bits(w, 5, 5))?;
    if mem.word(anchor)? & 0x9f00_0000 != 0x1000_0000 // adr Xn, case
        || last_writer(add, bits(w, 16, 5))? != load.at
    {
        return None;
    }
    let ldrh = mem.word(load.at)?;
    if ldrh & 0xffe0_fc00 != 0x7860_7800 { return None; } // ldrh Wt, [Xn, Xm, lsl #1]
    let table = last_writer(load.at, bits(ldrh, 5, 5))?;
    let w = mem.word(table)?;
    // Require an untruncated local table pointer, as well as the local anchor.
    if w & 0x9f00_0000 != 0x1000_0000 {
        if w & 0xff80_0000 != 0x9100_0000 { return None; } // add Xd, Xn, #imm
        let page = last_writer(table, bits(w, 5, 5))?;
        if mem.word(page)? & 0x9f00_0000 != 0x9000_0000 { return None; } // adrp Xn, table
    }
    Some((load, anchor))
}

fn table_targets(mem: &dyn Memory, base: u64, load: Load, shift: u32, count: u64) -> Option<Vec<u64>> {
    if count == 0 || count > MAX_ENTRIES { return None; }
    let Load { table, size, signed, .. } = load;
    let raw = mem.bytes(table?, (count as usize) * size as usize)?;''')
    replace_once(jt, '''        out.push(target);
    }
    out.sort_unstable();
    out.dedup();
    Some(out)''', '''        out.push(target);
    }
    Some(out)''')
    module = lifter / 'src/module.rs'
    replace_once(module, '    pub chunk_instructions: usize,', '''    pub chunk_instructions: usize,
    /// Sole address-taking references used as local switch anchors.
    pub anchor_origins: BTreeSet<u64>,''')
    replace_once(module, 'Options { chunk_instructions: 40_000 }',
                 'Options { chunk_instructions: 40_000, anchor_origins: BTreeSet::new() }')
    replace_once(module, "    m: &'m Module<'a>,", "    m: &'m Module<'a>,\n    anchor_origins: &'m BTreeSet<u64>,")
    replace_once(module, "    fn new(m: &'m Module<'a>) -> Self {",
                 "    fn new(m: &'m Module<'a>, anchor_origins: &'m BTreeSet<u64>) -> Self {")
    replace_once(module, 'let l = Lifted::new(m);', 'let l = Lifted::new(m, &opts.anchor_origins);')
    replace_once(module, '    insns: Vec<Insn>,', '    insns: Vec<Insn>,\n    direct_edges: Vec<(u64, u64)>,')
    replace_once(module, '        let mut a = m.text.start;',
                 '        let mut direct_edges = Vec::new();\n        let mut a = m.text.start;')
    replace_once(module, '''                Ok(i) => i,''', '''                Ok(i) => {
                    if let Insn::B(target) | Insn::BCond(_, target) | Insn::Bl(target) = &i {
                        if m.text.contains(target) {
                            direct_edges.push((*target, a));
                        }
                    }
                    i
                },''')
    replace_once(module, '        Lifted { m, insns, unsupported }', '''        direct_edges.sort_unstable();
        Lifted { m, anchor_origins, insns, direct_edges, unsupported }''')
    replace_once(module, '    fn at(&self, a: u64) -> &Insn {', '''    fn direct_predecessors(&self, a: u64) -> &[(u64, u64)] {
        let start = self.direct_edges.partition_point(|&(target, _)| target < a);
        let end = start + self.direct_edges[start..].partition_point(|&(target, _)| target == a);
        &self.direct_edges[start..end]
    }

    fn at(&self, a: u64) -> &Insn {''')
    replace_once(module, 'reaching_defs(l, entry, preds, br_pc, r)', 'reaching_defs(l, entry, preds, br_pc, r, 512)')
    replace_once(module, 'pc: u64, r: u32) -> Option<Vec<u64>> {\n    let (mut defs, mut seen, mut work)',
                 'pc: u64, r: u32, limit: usize) -> Option<Vec<u64>> {\n    let (mut defs, mut seen, mut work)')
    replace_once(module, 'if seen.len() > 512 {', 'if seen.len() > limit {')
    replace_once(module, 'Some(Table::All { known: Vec::new(), reach: vec![range], blocks: false })',
                 'Some(Table::All { known: recover_table(l, entry, br_pc, br_pc, r), reach: vec![range], blocks: false })')
    replace_once(module, '            reach.push(range);',
                 '            known.extend(recover_table(l, entry, d + 4, br_pc, r));\n            reach.push(range);')
    replace_once(module, '/// How the `br` at `br_pc` is emitted,', '''fn guarded_table_bound(l: &Lifted, mut a: u64, idx: u32) -> Option<u64> {
    // The table block is locally straight-line. Its guard can be far away
    // but must be the only direct incoming edge into the table block.
    for _ in 0..jt::WINDOW {
        if a == l.m.text.start || l.m.seeds.contains(&a) { return None; }
        let previous = a - 4;
        match l.direct_predecessors(a) {
            [] if matches!(l.at(previous), Insn::Op(code) if !code.contains("rt_svc(c")) => {
                if jt::writes(jt::Memory::word(l.m, previous)?, idx) { return None; }
                a = previous;
            }
            &[(_, branch)] if matches!(l.at(previous), Insn::B(_) | Insn::Br(_) | Insn::Ret(_)) => {
                if l.m.seeds.contains(&branch) || !l.direct_predecessors(branch).is_empty() {
                    return None;
                }
                let guard = jt::Memory::word(l.m, branch)?;
                let compare_at = branch.checked_sub(4)?;
                let compare = jt::Memory::word(l.m, compare_at)?;
                if guard & 0xff00_001f != 0x5400_0009 // b.ls, taken into the table block
                    || compare & 0x7f80_001f != 0x7100_001f // cmp Widx or Xidx, #imm
                    || bits(compare, 5, 5) != idx || idx == 31
                {
                    return None;
                }
                if bits(compare, 31, 1) == 0 {
                    // CMP Widx only constrains the low half of Xidx. Require a
                    // preceding zero-extending load and no way to skip it.
                    let producer_at = compare_at.checked_sub(4)?;
                    if producer_at < l.m.text.start || l.m.seeds.contains(&compare_at)
                        || !l.direct_predecessors(compare_at).is_empty()
                    {
                        return None;
                    }
                    let producer = jt::Memory::word(l.m, producer_at)?;
                    if producer & 0xffc0_001f != (0xb940_0000 | idx) { // ldr Widx, [Xn, #imm]
                        return None;
                    }
                }
                let limit = (bits(compare, 10, 12) as u64) << (bits(compare, 22, 1) * 12);
                return Some(limit + 1);
            }
            _ => return None,
        }
    }
    None
}

fn prove_guarded_alias(l: &Lifted, entry: u64, compare: u64, index: u32, source: u32,
                       defines_alias: impl Fn(u32) -> bool) -> Option<()> {
    // The alias must have been defined on every path to the comparison, and
    // neither register may have changed since. Check all direct entrances.
    let start = entry.max(compare.saturating_sub(jt::WINDOW * 4));
    let mut pending = vec![compare];
    let mut seen = BTreeSet::new();
    while let Some(a) = pending.pop() {
        if !seen.insert(a) { continue; }
        if a <= start || l.m.seeds.contains(&a) { return None; }
        let previous = a - 4;
        let fallthrough = (!l.at(previous).ends_block()).then_some(previous);
        let direct = l.direct_predecessors(a);
        if direct.is_empty() && fallthrough.is_none() { return None; }
        for p in direct.iter().map(|&(_, from)| from).chain(fallthrough) {
            if !(start..a).contains(&p) { return None; }
            match l.at(p) {
                Insn::Op(code) if !code.contains("rt_svc(c") => {
                    let word = jt::Memory::word(l.m, p)?;
                    if defines_alias(word) { continue; }
                    if jt::writes(word, index) || jt::writes(word, source) { return None; }
                }
                Insn::B(_) | Insn::BCond(_, _) => {}
                _ => return None,
            }
            pending.push(p);
        }
    }
    Some(())
}

fn fallthrough_alias_bound(l: &Lifted, entry: u64, load: u64, branch: u64, index: u32) -> Option<u64> {
    // Walk the guarded fallthrough from the load to a CMP/B.HI pair. An
    // entrance after CMP would allow execution without the checked bound.
    let mut a = load;
    for _ in 0..jt::WINDOW {
        if a <= entry || l.m.seeds.contains(&a) || !l.direct_predecessors(a).is_empty() { return None; }
        let p = a - 4;
        let word = jt::Memory::word(l.m, p)?;
        match l.at(p) {
            Insn::Op(code) if !code.contains("rt_svc(c") => {
                if jt::writes(word, index) {
                    let guard = jt::masked_alias_guard(l.m, entry, branch, p, word)?;
                    // The checked fallthrough must be the only way into the
                    // final branch and remask, even when the alias is older.
                    if (guard.compare_at + 4..=p).step_by(4).any(|pc| {
                        l.m.seeds.contains(&pc) || !l.direct_predecessors(pc).is_empty()
                    }) {
                        return None;
                    }
                    prove_guarded_alias(l, entry, guard.compare_at, guard.checked, guard.source, |w| {
                        bits(w, 0, 5) == guard.checked && jt::masked_index(w) == Some((guard.source, guard.mask))
                    })?;
                    return Some(guard.count);
                }
                a = p;
            }
            Insn::BCond(_, target) if *target > branch && word & 0xff00_001f == 0x5400_0008 => {
                if p <= entry || l.m.seeds.contains(&p) || !l.direct_predecessors(p).is_empty() { return None; }
                let compare = p - 4;
                let word = jt::Memory::word(l.m, compare)?;
                let source = bits(word, 5, 5);
                if word & 0xff80_001f != 0x7100_001f || source == index || source == 31 || index == 31 {
                    return None;
                }
                // mov Windex, Wsource (orr with WZR, unshifted)
                prove_guarded_alias(l, entry, compare, index, source,
                                    |w| w == (0x2a00_03e0 | (source << 16) | index))?;
                let limit = (bits(word, 10, 12) as u64) << (bits(word, 22, 1) * 12);
                return Some(limit + 1);
            }
            _ => return None,
        }
    }
    None
}

fn nested_writes(l: &Lifted, pc: u64, r: u32) -> bool {
    // The matcher uses encoding-level writes, which may miss GPR destinations
    // such as fixed-point conversions and the second exclusive-pair result.
    jt::Memory::word(l.m, pc).is_some_and(|w| jt::writes(w, r))
        || matches!(l.at(pc), Insn::Op(code) if code.contains(&format!("c->x[{r}] =")))
}

fn nested_outer_bound(l: &Lifted, branch: u64, load: u64, index: u32, selector: u32) -> Option<(u64, u64)> {
    let word = |pc| jt::Memory::word(l.m, pc);
    let start = l.m.text.start.max(branch.saturating_sub(jt::WINDOW * 4));
    let index_copy = (start..load).step_by(4).filter(|&pc| nested_writes(l, pc, index)).last()?;
    let selector_copy = (load + 4..branch).step_by(4).filter(|&pc| nested_writes(l, pc, selector)).last()?;
    let mov_source = |pc| {
        let w = word(pc)?;
        (w & 0xffe0_ffe0 == 0x2a00_03e0).then(|| bits(w, 16, 5)) // mov Wd, Wm
    };
    let source = mov_source(index_copy)?;
    if source == index || source == selector || source == 31 || mov_source(selector_copy)? != source {
        return None;
    }
    let guard = index_copy.checked_sub(4).filter(|&pc| pc > start)?;
    let compare = word(guard - 4)?;
    if compare & 0xff80_001f != 0x7100_001f || bits(compare, 5, 5) != source
        || word(guard)? & 0xff00_001f != 0x5400_0008 // cmp Wsource, #limit; b.hi default
        || !matches!(l.at(guard), Insn::BCond(_, target) if *target > branch)
    {
        return None;
    }
    // Both copies are reached through the guard, with no independent entry
    // and with the same checked value. The W copies clear the upper bits.
    if (guard..=branch).step_by(4).any(|pc| l.m.seeds.contains(&pc) || !l.direct_predecessors(pc).is_empty()) {
        return None;
    }
    for pc in (index_copy..branch).step_by(4) {
        if !matches!(l.at(pc), Insn::Op(code) if !code.contains("rt_svc(c"))
            || (pc < selector_copy && nested_writes(l, pc, source))
        {
            return None;
        }
    }
    Some((((bits(compare, 10, 12) as u64) << (bits(compare, 22, 1) * 12)) + 1, index_copy))
}

fn nested_case_entry(l: &Lifted, sub: u64, selector: u32) -> Option<u64> {
    let start = l.m.text.start.max(sub.saturating_sub(0x800));
    let mut pending = vec![sub];
    let mut seen = BTreeSet::new();
    let mut case = None;
    while let Some(a) = pending.pop() {
        if !seen.insert(a) { continue; }
        if a <= start { return None; }
        let previous = a - 4;
        let direct = l.direct_predecessors(a);
        if matches!(l.at(previous), Insn::Br(_)) {
            // The sole accepted computed entrance is the first case, just
            // after its dispatch. Prove that table and its selector below.
            if !direct.is_empty() || case.is_some_and(|other| other != a) { return None; }
            case = Some(a);
            continue;
        }
        if l.m.seeds.contains(&a) { return None; }
        let fallthrough = (!l.at(previous).ends_block()).then_some(previous);
        if direct.is_empty() && fallthrough.is_none() { return None; }
        for &(_, from) in direct {
            if !(start..a).contains(&from) || !matches!(l.at(from), Insn::B(_) | Insn::BCond(_, _)) {
                return None;
            }
            pending.push(from);
        }
        if let Some(from) = fallthrough {
            match l.at(from) {
                Insn::Op(code) if !code.contains("rt_svc(c")
                    && !nested_writes(l, from, selector) => {}
                Insn::Bl(_) | Insn::Blr(_) if jt::callee_saved(selector) => {}
                Insn::BCond(_, _) => {}
                _ => return None,
            }
            pending.push(from);
        }
    }
    case
}

fn nested_table_bound(l: &Lifted, load: u64, inner_branch: u64, r: u32, index: u32) -> Option<u64> {
    if (load..=inner_branch).step_by(4).any(|pc| l.m.seeds.contains(&pc) || !l.direct_predecessors(pc).is_empty()) {
        return None;
    }
    let start = l.m.text.start.max(load.saturating_sub(jt::WINDOW * 4));
    let mut a = load;
    let (sub, selector, offset) = loop {
        if a <= start || l.m.seeds.contains(&a) || !l.direct_predecessors(a).is_empty() {
            return None;
        }
        a -= 4;
        if !matches!(l.at(a), Insn::Op(code) if !code.contains("rt_svc(c")) { return None; }
        let w = jt::Memory::word(l.m, a)?;
        if nested_writes(l, a, index) {
            if w & 0xffc0_0000 != 0x5100_0000 || bits(w, 0, 5) != index { return None; }
            break (a, bits(w, 5, 5), bits(w, 10, 12) as usize); // sub Windex, Wselector, #offset
        }
    };
    if selector == 31 || index == 31 { return None; }
    let writes_register = |pc, reg| nested_writes(l, pc, reg);
    jt::local_halfword_table(l.m, sub + 4, inner_branch, r, load, writes_register)?;
    let case = nested_case_entry(l, sub, selector)?;
    if (case..inner_branch).step_by(4).any(|pc| matches!(l.at(pc), Insn::Br(_))) { return None; }
    let branch = case - 4;
    let r = bits(jt::Memory::word(l.m, branch)?, 5, 5);
    let start = l.m.text.start.max(branch.saturating_sub(jt::WINDOW * 4));
    let targets = jt::ordered_halfword_cases(l.m, start, branch, r, writes_register, |load, index, anchor| {
        if l.m.seeds.contains(&case) && !l.anchor_origins.contains(&anchor) { return None; }
        nested_outer_bound(l, branch, load, index, selector)
    })?;
    if targets.iter().any(|&target| (case + 4..=inner_branch).contains(&target)) { return None; }
    let first = targets.iter().position(|&target| target == case)?;
    let last = targets.iter().rposition(|&target| target == case)?;
    (first == offset && targets[first..=last].iter().all(|&target| target == case))
        .then_some((last - first + 1) as u64)
}

fn recover_table(l: &Lifted, entry: u64, pc: u64, branch: u64, r: u32) -> Vec<u64> {
    jt::resolve_with_recovery(l.m, entry, pc, branch, r, |load, reg| {
        // The reaching-definition walk rejects paths that cross a call
        // without first finding a definition of a caller-saved base.
        // Include earlier partitions and local backward edges from later
        // case bodies, with the walk limited to this instruction window.
        let start = l.m.text.start.max(load.saturating_sub(0x800));
        let end = l.m.text.end.min(load.saturating_add(0x2000));
        let mut preds = BTreeMap::<u64, Vec<u64>>::new();
        for address in (start..end).step_by(4) {
            if let Insn::B(target) | Insn::BCond(_, target) = l.at(address) {
                if (start..end).contains(target) {
                    preds.entry(*target).or_default().push(address);
                }
            }
        }
        let limit = ((end - start) / 4) as usize;
        let mut definitions = reaching_defs(l, start, &preds, load, reg, limit)?.into_iter();
        let constant = |definition| jt::constant_at(l.m, start, definition, reg);
        let table = constant(definitions.next()?)?;
        definitions.all(|definition| constant(definition) == Some(table)).then_some(table)
    }, |load, idx| {
        guarded_table_bound(l, load, idx)
            .or_else(|| fallthrough_alias_bound(l, entry, load, branch, idx))
            .or_else(|| nested_table_bound(l, load, branch, r, idx))
    }).unwrap_or_default()
}

/// How the `br` at `br_pc` is emitted,''')


def _cached_binary(binary, marker, key):
    if binary.is_file() and marker.is_file() and json.loads(marker.read_text()) == dict(
            key=key, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest()):
        return binary
    raise pc.PCError('Switch emitter cache differs; preserve edits and choose a new cache.')


def build(*, desktop=False):
    vendor = verify_vendor()
    rustc = os.environ.get('DECOMP_SWITCH_RUSTC') or shutil.which('rustc')
    if not rustc:
        raise pc.PCError('Switch source export needs Rust 1.90+ on PATH (or DECOMP_SWITCH_RUSTC).')
    version = _run([rustc, '--version']).strip()
    adapter = ROOT / 'emitter.rs'
    patch_source = (ROOT / 'desktop/patches.py').read_bytes() if desktop else b''
    key = hashlib.sha256((json.dumps(sources()['vendored'], sort_keys=True) + version).encode()
                         + adapter.read_bytes() + Path(__file__).read_bytes() + patch_source).hexdigest()
    cache = Path(os.environ.get('DECOMP_SWITCH_BUILD_CACHE') or toolchains.root() / 'switch-emitter')
    destination = cache / key
    binary = destination / ('switch-emitter.exe' if os.name == 'nt' else 'switch-emitter')
    marker = destination / 'build.json'
    if destination.exists():
        return _cached_binary(binary, marker, key)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.switch-build-', dir=cache) as temp:
        work = Path(temp)
        # A computed branch may enter the fallthrough of a conditional branch.
        # Such an address must survive partitioning into dispatchable blocks.
        from .desktop.patches import replace_once
        patched = work / 'lifter'
        shutil.copytree(vendor, patched)
        jt = patched / 'src/jt.rs'
        replace_once(jt, '''            match mov_reg(w).or_else(|| zero_extend(w)) {
                Some(src) => idx = src,
                None => return None,
            }''',
                     '''            match mov_reg(w).or_else(|| zero_extend(w)) {
                Some(src) => idx = src,
                None if limit_cond.is_none() => return masked_alias_bound(mem, entry, load_pc, a, w),
                None => return None,
            }''')
        replace_once(jt, '/// The source register of `mov wd/xd, ws/xs`', '''// Clang may test a masked W alias, then separately mask the X index:
// and w9, w8, #mask; cmp w9, #limit; [stores]; b.hi default; and x8, x8, #mask.
// Require an exit past the load and identical masks and sources so that the
// unsigned bound applies to the loaded index.
fn masked_alias_bound(mem: &dyn Memory, entry: u64, load_pc: u64, at: u64, index: u32) -> Option<u64> {
    let guard = masked_alias_guard(mem, entry, load_pc, at, index)?;
    let alias_at = guard.compare_at.checked_sub(4).filter(|&addr| addr >= entry)?;
    let alias = mem.word(alias_at)?;
    (bits(alias, 0, 5) == guard.checked && masked_index(alias) == Some((guard.source, guard.mask)))
        .then_some(guard.count)
}

pub(crate) struct MaskedAliasGuard {
    pub compare_at: u64,
    pub checked: u32,
    pub source: u32,
    pub mask: u64,
    pub count: u64,
}

pub(crate) fn masked_alias_guard(mem: &dyn Memory, entry: u64, exit_after: u64, at: u64,
                                 index: u32) -> Option<MaskedAliasGuard> {
    let (source, mask) = masked_index(index)?;
    let branch_pc = at.checked_sub(4).filter(|&addr| addr >= entry)?;
    let branch = mem.word(branch_pc)?;
    if branch & 0xff00_001f != 0x5400_0008
        || branch_pc.wrapping_add_signed(sext(bits(branch, 5, 19) as u64, 19) * 4) <= exit_after
    {
        return None;
    }
    let mut compare_at = branch_pc;
    let compare = loop {
        compare_at = compare_at.checked_sub(4)
            .filter(|&addr| addr >= entry && branch_pc - addr <= WINDOW * 4)?;
        let word = mem.word(compare_at)?;
        // Scalar integer stores with an unsigned immediate offset preserve NZCV and registers.
        if word & 0x3fc0_0000 != 0x3900_0000 { break word; }
    };
    let checked = bits(compare, 5, 5);
    if source == 31 || checked == 31 || compare & 0x7f80_001f != 0x7100_001f { return None; }
    let limit = (bits(compare, 10, 12) as u64) << (bits(compare, 22, 1) * 12);
    Some(MaskedAliasGuard { compare_at, checked, source, mask, count: limit.min(mask) + 1 })
}

pub(crate) fn masked_index(w: u32) -> Option<(u32, u64)> {
    let wide = bits(w, 31, 1);
    let n = bits(w, 22, 1);
    if w & 0x7f80_0000 != 0x1200_0000 || n > wide {
        return None;
    }
    let (mask, _) = crate::bits::decode_bit_masks(n, bits(w, 10, 6), bits(w, 16, 6), 32 << wide, true)?;
    (mask <= u32::MAX as u64 && mask & (mask + 1) == 0).then_some((bits(w, 5, 5), mask))
}

/// The source register of `mov wd/xd, ws/xs`''')
        replace_once(patched / 'src/module.rs',
                     '            if l.at(a).ends_block() {\n                s.external.insert(a + 4);',
                     '            if l.at(a).ends_block() || matches!(l.at(a), Insn::BCond(_, _)) {\n                s.external.insert(a + 4);')
        replace_once(patched / 'src/module.rs', '''    for t in s.tables.values() {
        if let Table::All { known, reach, blocks } = t {
            s.external.extend(known);
            for r in reach {
                let (lo, hi) = ((*r.start()).max(entry), (*r.end()).min(end - 4));''',
                     '''    for (&branch, t) in &s.tables {
        if let Table::All { known, reach, blocks } = t {
            s.external.extend(known);
            for r in reach {
                // A scaled byte table can start at an adjacent ADR seed just
                // beyond this partition. Keep its at most 256 targets in text.
                let crosses_anchor = *r.start() == end && end == branch + 4
                    && r.start().checked_add(255 * 4) == Some(*r.end());
                let limit = if crosses_anchor { l.m.text.end } else { end };
                let (lo, hi) = ((*r.start()).max(entry), (*r.end()).min(limit - 4));''')
        _recover_jump_tables(patched, replace_once)
        # Propagate a restored guest stack through skipped native call frames.
        module = patched / 'src/module.rs'
        for call in ('{}(c);', 'rt_dispatch(c);',
                     '{{ GuestFn rt_f = rt_hit(c->pc); if (rt_f) rt_f(c); else rt_dispatch(c); }}'):
            # Read the spilled field. The parenthesized pointer prevents the
            # lifter from substituting a local whose liveness ended at SPILL.
            replace_once(module, 'SPILL ' + call + ' RELOAD RT_RETURNED(c, {ra})',
                         'SPILL {{ uint64_t rt_sp = (c)->sp; ' + call +
                         ' RT_RETURNED(c, {ra}, rt_sp) }} RELOAD ')
        replace_once(patched / 'runtime/cpu.h', '#define RT_RETURNED(c, ra)', '#define RT_RETURNED(c, ra, sp_before_call)')
        replace_once(patched / 'runtime/cpu.h', '        __attribute__((musttail)) return rt_dispatch(c);',
                     '        if ((c)->sp > (sp_before_call)) return;               \\\n'
                     '        __attribute__((musttail)) return rt_dispatch(c);')
        if desktop:
            from .desktop.patches import lifter
            lifter(patched)
        vendor = patched
        _run([rustc, '--edition=2021', '--crate-type=rlib', '--crate-name', 'nxport_lifter',
              vendor / 'src/lib.rs', '-O', '-o', work / 'libnxport_lifter.rlib'])
        _run([rustc, '--edition=2021', adapter, '--extern',
              'nxport_lifter=' + str(work / 'libnxport_lifter.rlib'), '-O', '-o', work / binary.name])
        (work / marker.name).write_text(json.dumps(dict(key=key,
            binary_sha256=hashlib.sha256((work / binary.name).read_bytes()).hexdigest())) + '\n')
        try:
            work.rename(destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not destination.exists():
                raise
            return _cached_binary(binary, marker, key)
    return binary
