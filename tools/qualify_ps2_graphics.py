"""Assess a pinned standalone Vulkan GS renderer using original GIF packets.

This is separate from a game backend: EE/IOP/VU, host window adaptation, audio,
input and saves are not qualified. A software Vulkan device is reported as such.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

from tools.qualify_ps2_runtime import run, executable

ROOT = Path(__file__).resolve().parent.parent
INPUTS_PATH = ROOT / 'tools/ps2_gs/inputs.json'


def fingerprint(root):
    digest = hashlib.sha256()
    # WindowsPath ordering folds case. Pin the same POSIX byte order on every
    # host so identical, checksum-verified archives have one source identity.
    for path in sorted(Path(root).rglob('*'), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def download(destination):
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('choose a new GS source directory; existing work is preserved')
    inputs = json.loads(INPUTS_PATH.read_text())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ps2-gs-source-', dir=destination.parent) as temp:
        stage = Path(temp); source = stage / 'source'; source.mkdir()
        for n, item in enumerate(inputs['archives']):
            archive = stage / f'{n}.tar.gz'
            digest = hashlib.sha256(); total = 0
            with urllib.request.urlopen(item['url'], timeout=60) as response, archive.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 64 * 1024 * 1024: raise ValueError('GS source archive exceeds its download bound')
                    digest.update(chunk); output.write(chunk)
            if digest.hexdigest() != item['sha256']: raise ValueError('GS archive checksum differs: ' + item['name'])
            unpack = stage / f'unpack-{n}'; unpack.mkdir()
            with tarfile.open(archive) as tar: tar.extractall(unpack, filter='data')
            trees = list(unpack.iterdir())
            if len(trees) != 1 or not trees[0].is_dir(): raise ValueError('GS archive has an unexpected layout')
            shutil.copytree(trees[0], source / item['prefix'], dirs_exist_ok=True)
        actual = fingerprint(source)
        if inputs.get('source_sha256') and inputs['source_sha256'] != actual:
            raise ValueError('assembled GS sources differ from the pinned fingerprint')
        source.rename(destination)
    return dict(path=str(destination), source_sha256=actual)


def qualify(sdk, output, *, execute=True):
    sdk, output = Path(sdk).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('choose a new GS assessment directory; existing work is preserved')
    if output.is_relative_to(sdk) or sdk.is_relative_to(output): raise ValueError('GS sources and assessment must be separate')
    inputs = json.loads(INPUTS_PATH.read_text())
    actual = fingerprint(sdk)
    if actual != inputs.get('source_sha256'): raise ValueError('GS source fingerprint differs from the pinned inputs')
    output.mkdir(parents=True)
    shutil.copyfile(ROOT / 'tools/ps2_gs/probe.cpp', output / 'probe.cpp')
    shutil.copyfile(ROOT / 'tools/ps2_gs/Probe.cmake', output / 'ProbeTargets.cmake')
    (output / 'hook.cmake').write_text('cmake_language(DEFER CALL include "${DECOMP_PS2_GS_PROBE}/ProbeTargets.cmake")\n')
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    build = output / 'build'
    run(['cmake', '-S', sdk, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
        '-DPARALLEL_GS_STANDALONE=ON', '-DGRANITE_TOOLS=OFF', '-DGRANITE_INSTALL_TARGETS=OFF',
        '-DCMAKE_PROJECT_parallel-gs_INCLUDE=' + (output / 'hook.cmake').as_posix(),
        '-DDECOMP_PS2_GS_PROBE=' + output.as_posix()], output, output / 'configure.log')
    run(['cmake', '--build', build, '--target', 'decomp_ps2_gs_probe', '--config', 'Release', '--parallel', '2'],
        output, output / 'build.log')
    native = executable(build, 'decomp_ps2_gs_probe')
    result = None
    if execute:
        result = json.loads(run([native], output, output / 'run.log', timeout=90))
        if result['red_pixels'] != [1176, 4656] or result['image_pixels'] != [4, 4] or not result['passed']:
            raise ValueError('GS rendering differs from the original command fixture')
    if fingerprint(sdk) != actual: raise ValueError('GS assessment modified its source inputs')
    report = dict(schema='decomp.wtf.ps2-gs-candidate/v1', source_sha256=actual,
        native_build=True, vulkan_executed=execute, result=result,
        game_runtime_qualified=False, host_drawable_adaptation_qualified=False, retail_qualified=False,
        descriptor_backend='sets', interpreter_used=False, glsl_runtime_compiler=False)
    (output / 'assessment.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sdk-root', type=Path)
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    sdk = args.sdk_root
    if sdk is None:
        sdk = args.output.parent / 'PS2-GS-source'
        download(sdk)
    print(json.dumps(qualify(sdk, args.output, execute=not args.build_only), indent=2))


if __name__ == '__main__': main()
