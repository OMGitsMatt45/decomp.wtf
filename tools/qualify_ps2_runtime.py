"""Build and execute an optional PS2 candidate using original R5900 programs.

Developer assessment only: it neither registers an app backend nor qualifies
graphics, IOP, VU, audio, saves, BIOS replacement or a retail game. The complete
upstream runtime is linked; no substitute implementation of EE operations is
used. The independent Python oracle decodes the fixture's original bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from tests.fixtures.ps2_native import cases, program, reference, MASK64

ROOT = Path(__file__).resolve().parent.parent
INPUTS = json.loads((ROOT / 'tools/ps2_runtime/inputs.json').read_text())
COMMIT = INPUTS['candidate']['commit']
TREE = INPUTS['candidate']['tree']
REPOSITORY = INPUTS['candidate']['repository']


def run(command, cwd, log, timeout=1200):
    """Keep complete diagnostics, including timed-out builds, outside the SDK."""
    try:
        result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=timeout)
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
    except subprocess.TimeoutExpired as error:
        log.write_bytes((error.stdout or b'') + (error.stderr or b''))
        raise ValueError(f'command timed out; see {log}') from error
    if result.returncode:
        raise ValueError(f'{command[0]} failed; see {log}: ' + (result.stdout + result.stderr)[-2500:])
    return result.stdout.strip()


def identity(sdk):
    """Verify the immutable Git tree and reject changed or extra source files."""
    sdk = Path(sdk).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(sdk), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != COMMIT or git('rev-parse', 'HEAD^{tree}') != TREE:
        raise ValueError('PS2 candidate checkout is not the pinned commit/tree')
    if git('status', '--porcelain', '--untracked-files=all', '--ignored'):
        raise ValueError('PS2 candidate has modified, extra or ignored files; use a clean source checkout')
    digest = hashlib.sha256()
    # Git index identities retain executable modes on Windows as well as Linux.
    for record in git('ls-files', '--stage').splitlines():
        metadata, name = record.split('\t', 1)
        mode, expected, stage = metadata.split()
        path = sdk / name
        if mode not in ('100644', '100755') or stage != '0' or path.is_symlink() or not path.is_file():
            raise ValueError('PS2 candidate contains an unsupported Git entry')
        data = path.read_bytes()
        # core.autocrlf must be disabled when fetching the pinned source.
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if blob != expected:
            raise ValueError(f'PS2 candidate file bytes differ: {name}')
        digest.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
    return dict(commit=COMMIT, tree=TREE, source_sha256=digest.hexdigest())


def download(destination):
    """Fetch the exact public source commit, preserving any existing directory."""
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('choose a new SDK directory; existing work is preserved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ps2-source-', dir=destination.parent) as temporary:
        work = Path(temporary); sdk = work / 'source'
        run(['git', 'init', sdk], work, work / 'init.log')
        run(['git', '-C', sdk, 'config', 'core.autocrlf', 'false'], work, work / 'config.log')
        run(['git', '-C', sdk, 'fetch', '--depth', '1', 'https://github.com/' + REPOSITORY + '.git', COMMIT],
            work, work / 'fetch.log')
        run(['git', '-C', sdk, 'checkout', '--detach', 'FETCH_HEAD'], work, work / 'checkout.log')
        identity(sdk)
        sdk.rename(destination)
    return destination


def executable(build, name):
    paths = list(build.rglob(name + '.exe')) if os.name == 'nt' else list(build.rglob(name))
    return next(p for p in paths if p.is_file() and '_deps' not in p.parts)


def qualify(sdk, destination):
    sdk, destination = Path(sdk).resolve(), Path(destination).resolve()
    if destination.exists(): raise ValueError('choose a new assessment destination; existing work is preserved')
    if destination.is_relative_to(sdk) or sdk.is_relative_to(destination):
        raise ValueError('source and assessment directories must be separate')
    original_identity = identity(sdk)
    # Keep failed builds and their logs reviewable instead of discarding evidence.
    destination.mkdir(parents=True)
    (destination / 'inputs.json').write_text(json.dumps(INPUTS, indent=2) + '\n')
    fixture = destination / 'probe'; fixture.mkdir()
    image, code, entries = program()
    (fixture / 'original.elf').write_bytes(image)
    (fixture / 'original_program.h').write_text('#pragma once\n#include <cstdint>\n'
        'inline constexpr unsigned char original_program[] = {' + ','.join(map(str, code)) + '};\n'
        f'inline constexpr uint32_t original_helper = {entries["helper"]};\n')
    shutil.copyfile(ROOT / 'tools/ps2_runtime/runner.cpp', fixture / 'runner.cpp')
    shutil.copyfile(ROOT / 'tools/ps2_runtime/Probe.cmake', fixture / 'ProbeTargets.cmake')
    shutil.copyfile(sdk / 'LICENSE', destination / 'PS2Recomp-LICENSE.txt')
    deps = '\n'.join('FetchContent_Declare(' + dep['name'] + '\n'
        '  GIT_REPOSITORY https://github.com/' + dep['repo'] + '.git\n'
        '  GIT_TAG ' + dep['sha'] + '\n  GIT_CONFIG core.autocrlf=false)'
        for dep in INPUTS['dependencies'])
    hook = destination / 'pinned-dependencies.cmake'
    hook.write_text('include(FetchContent)\n' + deps + '\n'
        'if(DECOMP_PS2_PROBE_DIR)\n'
        '  cmake_language(DEFER CALL include "${DECOMP_PS2_PROBE_DIR}/ProbeTargets.cmake")\n'
        'endif()\n')
    build = destination / 'build'
    config = ['cmake', '-S', sdk, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_PROJECT_PS2RetroX_INCLUDE=' + hook.as_posix(),
        '-DPS2X_BUILD_ANALYZER=OFF', '-DPS2X_BUILD_TEST=OFF', '-DPS2X_BUILD_STUDIO=OFF',
        '-DPS2X_ENABLE_DEBUG_UI=OFF', '-DPS2X_ENABLE_FFMPEG=OFF', '-DPS2X_ENABLE_SCCACHE=OFF',
        '-DPS2X_ENABLE_RUNTIME_LOGS=OFF', '-DPS2X_ENABLE_AGRESSIVE_LOGS=OFF',
        '-DPS2X_ENABLE_IOP_RPC_TRACE=OFF', '-DBUILD_TESTING=OFF']
    if os.name != 'nt': config += ['-DCMAKE_CXX_FLAGS=-msse4.1', '-DCMAKE_C_FLAGS=-msse4.1']
    run(config, destination, destination / 'configure.log')
    run(['cmake', '--build', build, '--target', 'ps2_recomp', '--config', 'Release', '--parallel', '2'],
        destination, destination / 'emitter-build.log')
    recompiler = executable(build, 'ps2_recomp')
    (fixture / 'config.toml').write_text('[general]\ninput = "original.elf"\noutput = "generated"\n'
        'single_file_output = false\noutput_worker_threads = 1\n'
        'patch_syscalls = false\npatch_cop0 = false\npatch_cache = false\nstubs = []\nskip = []\n')
    run([recompiler, 'config.toml'], fixture, destination / 'generation.log')
    if not list((fixture / 'generated').glob('*.cpp')): raise ValueError('candidate emitted no source')
    run(config + ['-DDECOMP_PS2_PROBE_DIR=' + fixture.as_posix()], destination, destination / 'native-configure.log')
    run(['cmake', '--build', build, '--target', 'ps2_cpu_probe', '--config', 'Release', '--parallel', '2'],
        destination, destination / 'native-build.log')
    native = executable(build, 'ps2_cpu_probe')
    checks = []
    for index, (name, a, b) in enumerate(cases()):
        result_path = fixture / f'case-{index}.json'
        run([native, f'{entries[name]:x}', f'{a & MASK64:x}', f'{a >> 64:x}',
            f'{b & MASK64:x}', f'{b >> 64:x}', result_path, 'cpu'], fixture,
            destination / f'case-{index}.log', timeout=30)
        actual = json.loads(result_path.read_text())
        expected = reference(code, entries[name], a, b, entries)
        if actual != expected:
            (fixture / f'case-{index}-expected.json').write_text(json.dumps(expected, indent=2))
            raise ValueError(f'original/native mismatch: {name}, case {index}; inspect case JSON')
        checks.append(dict(function=name, a=f'{a:032x}', b=f'{b:032x}'))
    tampered = fixture / 'tampered.json'
    run([native, f'{entries["word_add"]:x}', '0', '0', '0', '0', tampered, 'cpu', 'tamper'],
        fixture, destination / 'tampered.log', timeout=30)
    if json.loads(tampered.read_text()) != {'native_rejected': True}:
        raise ValueError('assessment host did not reject changed original bytes')
    if identity(sdk) != original_identity: raise ValueError('qualification changed the pinned source checkout')
    report = dict(schema='decomp.wtf.ps2-candidate/v1', candidate=original_identity,
        compiler=run(['cmake', '--version'], destination, destination / 'cmake-version.log').splitlines()[0],
        original_elf_sha256=hashlib.sha256(image).hexdigest(), checks=checks,
        generated_cpp_files=len(list((fixture / 'generated').glob('*.cpp'))),
        execution_model='static-recompiled', interpreter_fallback=False, runtime_code_generation=False,
        changed_code_guard='assessment-host-only',
        qualification=dict(cpu=True, graphics=False, iop=False, vu=False, audio=False, saves=False, retail=False),
        app_backend_registered=False, ffmpeg_enabled=False)
    (destination / 'assessment.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sdk-root', type=Path)
    args = parser.parse_args()
    sdk = args.sdk_root or download(args.output.parent / ('PS2Recomp-' + COMMIT))
    report = qualify(sdk, args.output)
    print(json.dumps(dict(output=str(args.output), checks=len(report['checks']), qualification=report['qualification'])))


if __name__ == '__main__': main()
