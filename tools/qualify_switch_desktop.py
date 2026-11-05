"""Build/run original Switch C programs and the source runtime; no retail inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from decompnet.switch_native import revision
from decompnet import pc
from decompnet.switch_native.desktop import sdk
from decompnet.switch_native.desktop.project import export
from tools.switch_exefs_fixture import fixture as exefs_fixture
from tools.switch_fixture import fixture as cpu_fixture


def run(command, log, *, timeout=900, expect=0, env=None):
    result = subprocess.run(list(map(str, command)), capture_output=True, timeout=timeout, env=env)
    log.write_bytes(result.stdout + result.stderr)
    if result.returncode != expect:
        raise ValueError(f'{log.name}: exit {result.returncode}, expected {expect}\n' + log.read_text(errors='replace')[-4000:])
    return result.stdout.decode(errors='replace')


def fixtures(work, rustc):
    source = sdk.verify()
    libs = work / 'fixture-libs'; libs.mkdir()
    for name in ('a64', 'loader', 'testkit'):
        args = [rustc, '--edition=2024', '--crate-type=rlib', '--crate-name', 'kirikae_' + name,
                source / 'crates' / name / 'src/lib.rs', '-L', 'dependency=' + str(libs), '-o', libs / ('libkirikae_' + name + '.rlib')]
        if name == 'testkit':
            for dep in ('a64', 'loader'):
                args += ['--extern', 'kirikae_' + dep + '=' + str(libs / ('libkirikae_' + dep + '.rlib'))]
        run(args, work / (name + '-fixture-build.log'))
    binary = work / ('make-fixtures.exe' if os.name == 'nt' else 'make-fixtures')
    run([rustc, '--edition=2024', Path(__file__).with_name('switch_desktop_fixtures.rs'),
         '--extern', 'kirikae_testkit=' + str(libs / 'libkirikae_testkit.rlib'), '-L', 'dependency=' + str(libs), '-o', binary], work / 'fixtures-build.log')
    inputs = work / 'inputs'
    run([binary, inputs], work / 'fixtures.log')
    for name, words in (('missing', [0xd2900009, 0xf2a10009, 0xd61f0120]),
                        ('svc', [0xd4000fe1, 0xd40000e1]),
                        ('fault', [0xd2800009, 0xf9400120, 0xd40000e1])):
        raw = bytearray((inputs / 'hello.nro').read_bytes())
        for i, word in enumerate(words): struct.pack_into('<I', raw, 0x80 + i * 4, word)
        (inputs / (name + '.nro')).write_bytes(raw)
    exefs_fixture(inputs / 'exefs')
    exefs_fixture(inputs / 'sdk-startup', sdk_startup=True)
    (inputs / 'cpu.nro').write_bytes(cpu_fixture(nro=True))
    (inputs / 'cpu-nso.nso').write_bytes(cpu_fixture(compressed=True))
    raw = bytearray((inputs / 'hello.nro').read_bytes())
    exclusive = bytes.fromhex((Path(__file__).parent / 'fixtures/switch-exclusive.hex').read_text())
    raw[0x80:0x80 + len(exclusive)] = exclusive
    (inputs / 'exclusive.nro').write_bytes(raw)
    return inputs


def qualify(args):
    work = args.work.resolve()
    if work.exists() and not args.resume:
        raise ValueError('choose a new qualification directory, or --resume an unedited validation export')
    if not work.exists() and args.resume:
        raise ValueError('--resume requires an existing validation directory')
    work.mkdir(parents=True, exist_ok=True)
    os.environ['DECOMP_SWITCH_RUSTC'] = args.rustc
    inputs = work / 'inputs' if args.resume else fixtures(work, args.rustc)
    names = ['hello', 'threads', 'parallel-threads', 'exefs', 'sdk-startup', 'cpu', 'cpu-nso', 'exclusive', 'missing', 'svc', 'fault']
    sources = {}
    for name in names:
        source = work / (name + '-source')
        original = inputs / (name if name in ('exefs', 'sdk-startup') else name + ('.nso' if name == 'cpu-nso' else '.nro'))
        if args.resume:
            verified = pc.verify(source)['manifest']
            if verified['backend']['revision'] != revision():
                raise ValueError('validation sources use a different backend revision; preserve them and choose a new work directory')
            from decompnet.switch_native.desktop.project import snapshot
            if verified['inputs'] != snapshot(original)['inputs']:
                raise ValueError('validation input identity differs; existing files were preserved')
        else:
            export(original, source)
        sources[name] = source
    cache = args.cargo_target or work / 'cargo'
    env = dict(os.environ, CARGO_TARGET_DIR=str(cache))
    if args.offline: env['CARGO_NET_OFFLINE'] = 'true'
    runs = []
    for name, source in sources.items():
        build = work / (name + '-build')
        run([args.cmake, '-S', source, '-B', build, '-DCMAKE_C_COMPILER=' + args.cc,
             '-DCMAKE_BUILD_TYPE=Release', '-DSWITCH_CARGO_TARGET_DIR=' + str(cache), '-DCARGO=' + args.cargo], work / (name + '-configure.log'), env=env)
        run([args.cmake, '--build', build, '--config', 'Release', '--parallel', '2'], work / (name + '-build.log'), env=env)
        binary = build / 'switch_native'
        if os.name == 'nt': binary = next(build.rglob('switch_native.exe'))
        report = work / (name + '-run.json')
        expected = 2 if name in ('missing', 'svc') else 4 if name == 'fault' else 0
        output = run([binary, '--assets', source / 'assets', '--headless', '--report', report], work / (name + '-run.log'), timeout=45, expect=expected, env=env)
        data = json.loads(report.read_text())
        assert data['interpreter_instructions'] == 0 and data['runtime_compilation'] is False
        assert data['status'] == ('passed' if expected == 0 else 'failed'), data
        if name == 'hello': assert output == 'Hello from kirikae!\nsum(1..100) = 5050\nsquare(12) = 144\nswitch: abcd\nfib(15) = 610\n'
        if name in ('threads', 'parallel-threads'): assert output == 'threads: 40400\n'
        if name in ('exefs', 'sdk-startup'):
            assert data['initializers_run'] == 2 and data['final_cpu']['x'][0] == 42
        if name in ('cpu', 'cpu-nso'):
            assert data['final_cpu']['x'][0] == 150
            memory = bytes.fromhex(data['data_samples'][0]['hex'])
            assert struct.unpack_from('<Q', memory)[0] == 120
            assert struct.unpack_from('<f', memory, 16)[0] == 3.5
            assert struct.unpack_from('<4I', memory, 32) == (16, 16, 16, 16)
        if name == 'exclusive':
            assert data['final_cpu']['x'][4] == data['final_cpu']['x'][7] == 0
            assert struct.unpack_from('<2Q', bytes.fromhex(data['data_samples'][0]['hex'])) == (0x13, 0x24)
        if name in ('missing', 'svc', 'fault'):
            kind = {'missing':'missing-native-target', 'svc':'svc', 'fault':'guest-memory-fault'}[name]
            assert any(e['kind'] == kind for e in data['failures']), data
        runs.append(dict(name=name, status=data['status'], expected_exit=expected, interpreter_instructions=0,
                         report_sha256=hashlib.sha256(report.read_bytes()).hexdigest()))
        print(name + ': passed qualification', flush=True)
        if name == 'hello':
            asset = source / 'assets/main.bin'; raw = asset.read_bytes(); asset.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            negative = work / 'changed-asset.json'
            try:
                run([binary, '--assets', source / 'assets', '--headless', '--report', negative], work / 'changed-asset.log', expect=2, env=env)
                failure = json.loads(negative.read_text())
                assert failure['native_function_entries'] == 0 and 'identity differs' in failure['error']
            finally: asset.write_bytes(raw)
    source = sources['hello'] / 'sdk'
    output = run([args.cargo, 'test', '--locked', '--manifest-path', source / 'Cargo.toml', '-p', 'kirikae-rt', '--lib', '--no-default-features'], work / 'runtime-tests.log', env=env)
    summary = re.search(r'test result: ok\. (\d+) passed; 0 failed', output)
    assert summary, output[-2000:]
    rejected = run([args.cargo, 'check', '--locked', '--manifest-path', source / 'Cargo.toml', '-p', 'kirikae-rt',
                    '--no-default-features', '--features', 'decomp-native,diagnostic-interpreter'],
                   work / 'interpreter-rejected.log', expect=101, env=env)
    assert 'Native exports cannot include the guest CPU interpreter' in (work / 'interpreter-rejected.log').read_text()
    graphics = None
    if args.graphics:
        folder = work / 'graphics'
        run([args.cargo, 'run', '--locked', '--manifest-path', source / 'Cargo.toml', '-p', 'kirikae-rt', '--example', 'decomp-graphics', '--no-default-features', '--', folder], work / 'graphics.log', env=env)
        graphics = json.loads((folder / 'graphics-report.json').read_text())
    result = dict(schema='decomp.wtf.switch-desktop-qualification/v1', backend_revision=revision(),
        host=sys.platform, guest_cpu='static C, no interpreter or runtime compiler', runs=runs,
        changed_asset_rejected_before_execution=True, combined_interpreter_build_rejected=True,
        runtime_tests=int(summary[1]), graphics=graphics,
        retail=False, windows_qualified=False, adaptive_geometry_qualified=False,
        audio_evidence='upstream mixer/resampler/service unit tests; no physical playback qualification',
        input_evidence='upstream keyboard/controller/HID unit tests; no physical controller qualification',
        saves_evidence='upstream filesystem/RomFS/title-root unit tests')
    (work / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print('runtime tests: ' + summary[1] + ' passed', flush=True)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', required=True, type=Path)
    for name in ('rustc', 'cc', 'cmake', 'cargo'):
        p.add_argument('--' + name, default=shutil.which('clang' if name == 'cc' else name))
    p.add_argument('--cargo-target', type=Path)
    p.add_argument('--offline', action='store_true')
    p.add_argument('--resume', action='store_true', help='recheck unedited source/input identities, then resume builds and checks in an existing work directory')
    p.add_argument('--graphics', action='store_true', help='requires a Vulkan 1.3 CPU driver; renders real Maxwell shaders')
    a = p.parse_args(argv)
    if not all(getattr(a, n) for n in ('rustc', 'cc', 'cmake', 'cargo')): p.error('Rust, Cargo, Clang and CMake are required')
    try:
        result = qualify(a)
        print(json.dumps(result, indent=2)); return 0
    except (OSError, ValueError, AssertionError, subprocess.TimeoutExpired) as e:
        p.exit(1, str(e) + '\n')


if __name__ == '__main__': raise SystemExit(main())
