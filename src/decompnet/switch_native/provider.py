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
        replace_once(patched / 'src/module.rs',
                     '            if l.at(a).ends_block() {\n                s.external.insert(a + 4);',
                     '            if l.at(a).ends_block() || matches!(l.at(a), Insn::BCond(_, _)) {\n                s.external.insert(a + 4);')
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
