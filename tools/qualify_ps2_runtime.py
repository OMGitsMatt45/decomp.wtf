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
import re
import shutil
import subprocess
import struct
import tempfile

from tests.fixtures.ps2_native import BASE, cases, program, reference, MASK64, r
from decompnet.ps2_native.reports import generation_report
from decompnet.ps2_native.codegen import guard_generated
from decompnet.ps2_native.registry import isolate, registry

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
    variant_image, variant_code = bytearray(image), bytearray(code)
    # Original second module at the same addresses: word add becomes wide add,
    # and the common helper uses OR. The independent byte oracle supports both.
    for address, word in ((entries['word_add'], r(0x2D, 4, 5, 2)), (entries['helper'], r(0x25, 4, 5, 2))):
        struct.pack_into('<I', variant_code, address - BASE, word)
        struct.pack_into('<I', variant_image, 0x100 + address - BASE, word)
    variant_image, variant_code = bytes(variant_image), bytes(variant_code)
    (fixture / 'original.elf').write_bytes(image)
    (fixture / 'original_program.h').write_text('#pragma once\n#include <cstdint>\n'
        'inline constexpr unsigned char original_program[] = {' + ','.join(map(str, code)) + '};\n'
        'inline constexpr unsigned char variant_program[] = {' + ','.join(map(str, variant_code)) + '};\n'
        f'inline constexpr uint32_t original_helper = {entries["helper"]};\n')
    shutil.copyfile(ROOT / 'tools/ps2_runtime/runner.cpp', fixture / 'runner.cpp')
    shutil.copyfile(ROOT / 'tools/ps2_runtime/Probe.cmake', fixture / 'ProbeTargets.cmake')
    shutil.copyfile(sdk / 'LICENSE', destination / 'PS2Recomp-LICENSE.txt')
    # Archive pins avoid cloning unrelated history and test submodules, whose
    # paths exceed Windows limits. Every dependency has an immutable revision
    # and a verified archive checksum; no mutable tag selects build inputs.
    deps = '\n'.join('FetchContent_Declare(' + dep['name'] + '\n'
        '  URL "' + dep['url'] + '"\n'
        '  URL_HASH SHA256=' + dep['archive_sha256'] + '\n  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)'
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
    generation = run([recompiler, 'config.toml'], fixture, destination / 'generation.log')
    statistics = generation_report(generation, expected_functions=len(entries))
    if not list((fixture / 'generated').glob('*.cpp')): raise ValueError('candidate emitted no source')
    guards = guard_generated(fixture / 'generated', image, expected_functions=statistics['recompiled'])
    module_a = isolate(fixture / 'generated', guards)
    variant = fixture / 'variant'; variant.mkdir()
    (variant / 'original.elf').write_bytes(variant_image)
    shutil.copyfile(fixture / 'config.toml', variant / 'config.toml')
    variant_statistics = generation_report(run([recompiler, 'config.toml'], variant,
        destination / 'variant-generation.log'), expected_functions=len(entries))
    variant_guards = guard_generated(variant / 'generated', variant_image,
        expected_functions=variant_statistics['recompiled'])
    module_b = isolate(variant / 'generated', variant_guards)
    registry_report = registry([module_a, module_b], fixture / 'module_registry.cpp')
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
    variant_checks = []
    for name in ('word_add', 'direct_call', 'indirect_call'):
        a = b = 0x80000000
        result_path = fixture / f'variant-{name}.json'
        run([native, f'{entries[name]:x}', f'{a:x}', '0', f'{b:x}', '0', result_path, 'module-b'], fixture,
            destination / f'variant-{name}.log', timeout=30)
        if json.loads(result_path.read_text()) != reference(variant_code, entries[name], a, b, entries):
            raise ValueError('original/native variant mismatch: ' + name)
        variant_checks.append(name)
    cycle = fixture / 'module-cycle.json'
    run([native, f'{entries["word_add"]:x}', '80000000', '0', '80000000', '0', cycle, 'module-cycle'],
        fixture, destination / 'module-cycle.log', timeout=30)
    expected_cycle = dict(states=[reference(c, entries['word_add'], 0x80000000, 0x80000000, entries)
        for c in (code, variant_code, code)], mixed_rejected=True)
    if json.loads(cycle.read_text()) != expected_cycle: raise ValueError('resident module switch or mixed-code rejection failed')
    for name, entry in entries.items():
        tampered = fixture / f'tampered-{name}.json'
        run([native, f'{entry:x}', '0', '0', '0', '0', tampered, 'cpu', 'tamper'],
            fixture, destination / f'tampered-{name}.log', timeout=30)
        if json.loads(tampered.read_text()) != {'native_rejected': True}:
            raise ValueError('generated function did not reject changed module bytes: ' + name)
    if identity(sdk) != original_identity: raise ValueError('qualification changed the pinned source checkout')
    compiler_file = next((build / 'CMakeFiles').glob('*/CMakeCXXCompiler.cmake'))
    compiler_info = compiler_file.read_text(encoding='utf-8')
    compiler = {key: re.search(r'set\(CMAKE_CXX_COMPILER_' + key.upper() + r' "([^"]+)"\)', compiler_info).group(1)
                for key in ('id', 'version')}
    report = dict(schema='decomp.wtf.ps2-candidate/v1', candidate=original_identity, compiler=compiler,
        cmake=run(['cmake', '--version'], destination, destination / 'cmake-version.log').splitlines()[0],
        original_elf_sha256=hashlib.sha256(image).hexdigest(), checks=checks,
        variant_elf_sha256=hashlib.sha256(variant_image).hexdigest(),
        generated_cpp_files=len(list((fixture / 'generated').glob('*.cpp'))) + len(list((variant / 'generated').glob('*.cpp'))) + 1,
        functions_recompiled=len(entries) * 2, functions_per_module=len(entries),
        stubs=0, skipped_functions=0, decode_failures=0,
        generation_statistics=statistics, variant_generation_statistics=variant_statistics,
        module_registry=registry_report, variant_checks=variant_checks, resident_switch_order=['a', 'b', 'a'],
        native_original_state_comparisons=len(checks) + len(variant_checks) + 3,
        generated_sources={p.relative_to(fixture).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in (fixture / 'generated', variant / 'generated') for p in sorted(folder.iterdir()) if p.is_file()},
        execution_model='static-recompiled', interpreter_fallback=False, runtime_code_generation=False,
        changed_code_guard='module-registry-and-function-entry', code_guards=guards,
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
