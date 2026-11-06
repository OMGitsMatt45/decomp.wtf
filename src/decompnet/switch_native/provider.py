"""Offline, dependency-free build of the pinned nxport/LASRecomp source emitter."""
from __future__ import annotations

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


def _recover_halfword_tables(lifter, replace_once):
    jt = lifter / 'src/jt.rs'
    replace_once(jt, '''pub fn resolve(mem: &dyn Memory, entry: u64, pc: u64, r: u32) -> Option<Vec<u64>> {
    let Sym::Target''', '''pub fn resolve(mem: &dyn Memory, entry: u64, pc: u64, r: u32) -> Option<Vec<u64>> {
    resolve_with_base(mem, entry, pc, r, |_, _| None)
}

pub fn constant_at(mem: &dyn Memory, entry: u64, definition: u64, r: u32) -> Option<u64> {
    match value(mem, entry, definition + 4, r, 0)? {
        Sym::Const(address) => Some(address),
        _ => None,
    }
}

pub fn resolve_with_base(
    mem: &dyn Memory, entry: u64, pc: u64, r: u32,
    recover: impl FnOnce(u64, u32) -> Option<u64>,
) -> Option<Vec<u64>> {
    let Sym::Target''')
    replace_once(jt, '    let raw = mem.bytes(table?, (count as usize) * size as usize)?;', '''    let table = match table {
        Some(table) => table,
        None if size == 2 && !signed && shift == 2 && base == pc + 4 => {
            recover(at, bits(mem.word(at)?, 5, 5))?
        }
        None => return None,
    };
    let raw = mem.bytes(table, (count as usize) * size as usize)?;''')
    module = lifter / 'src/module.rs'
    replace_once(module, 'reaching_defs(l, entry, preds, br_pc, r)', 'reaching_defs(l, entry, preds, br_pc, r, 512)')
    replace_once(module, 'pc: u64, r: u32) -> Option<Vec<u64>> {\n    let (mut defs, mut seen, mut work)',
                 'pc: u64, r: u32, limit: usize) -> Option<Vec<u64>> {\n    let (mut defs, mut seen, mut work)')
    replace_once(module, 'if seen.len() > 512 {', 'if seen.len() > limit {')
    replace_once(module, 'Some(Table::All { known: Vec::new(), reach: vec![range], blocks: false })',
                 'Some(Table::All { known: recover_table(l, entry, br_pc, r), reach: vec![range], blocks: false })')
    replace_once(module, '            reach.push(range);',
                 '            known.extend(recover_table(l, entry, d + 4, r));\n            reach.push(range);')
    replace_once(module, '/// How the `br` at `br_pc` is emitted,', '''fn recover_table(l: &Lifted, entry: u64, pc: u64, r: u32) -> Vec<u64> {
    jt::resolve_with_base(l.m, entry, pc, r, |load, reg| {
        if !jt::callee_saved(reg) { return None; }
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
    }).unwrap_or_default()
}

/// How the `br` at `br_pc` is emitted,''')


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
        if binary.is_file() and marker.is_file() and json.loads(marker.read_text()) == dict(
                key=key, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest()):
            return binary
        raise pc.PCError('Switch emitter cache differs; preserve edits and choose a new cache.')
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
// and w9, w8, #mask; cmp w9, #limit; b.hi default; and x8, x8, #mask.
// Require adjacent instructions, an exit past the load, and identical masks
// and sources so that the unsigned bound applies to the loaded index.
fn masked_alias_bound(mem: &dyn Memory, entry: u64, load_pc: u64, at: u64, index: u32) -> Option<u64> {
    let (source, mask) = masked_index(index)?;
    let alias_at = at.checked_sub(12).filter(|&addr| addr >= entry)?;
    let alias = mem.word(alias_at)?;
    let compare = mem.word(alias_at + 4)?;
    let branch_pc = alias_at + 8;
    let branch = mem.word(branch_pc)?;
    let reg = bits(alias, 0, 5);
    if source == 31 || reg == 31 || masked_index(alias) != Some((source, mask))
        || compare & 0x7f80_001f != 0x7100_001f || bits(compare, 5, 5) != reg
        || branch & 0xff00_001f != 0x5400_0008
        || branch_pc.wrapping_add_signed(sext(bits(branch, 5, 19) as u64, 19) * 4) <= load_pc
    {
        return None;
    }
    let limit = (bits(compare, 10, 12) as u64) << (bits(compare, 22, 1) * 12);
    Some(limit.min(mask) + 1)
}

fn masked_index(w: u32) -> Option<(u32, u64)> {
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
        _recover_halfword_tables(patched, replace_once)
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
        work.rename(destination)
    return binary
