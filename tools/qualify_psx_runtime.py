"""Assess the optional PSXRecomp candidate with original native CPU probes.

This developer tool is not a PS1 PC backend. No retail game is used, no product
capability is enabled, and the full hardware runtime is not qualified here.
Run from this repository: python -m tools.qualify_psx_runtime OUTPUT --sdk-root PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import tarfile

from tests.fixtures.psx_native import cases,program,reference

COMMIT='31df2e1e0e0a6525733e68ff70e72ecbef84bb09'
ARCHIVE_SHA256='3376c1bf0509ca7045e92d0673ecbc9245084e017ffaa66d954c77519972d171'
SOURCE_SHA256='28937b3662e511935ecf986e7f0c1374a10d5068842504ef9c3a6731383b8a5b'
URL='https://codeload.github.com/RetroPortingToolKit/psxrecomp/tar.gz/'+COMMIT
LICENSE='PolyForm-Noncommercial-1.0.0'
CODEGEN_HASH='115b1739'
ROOT=Path(__file__).resolve().parent.parent


def fingerprint(sdk):
    paths=[sdk/name for name in ('LICENSE','runtime/codegen_hash_sources.cmake','runtime/hash_codegen.cmake')]
    for folder in ('recompiler','runtime/include'):
        paths.extend(p for p in (sdk/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    digest=hashlib.sha256()
    for path in sorted(paths,key=lambda p:p.relative_to(sdk).as_posix()):
        digest.update(path.relative_to(sdk).as_posix().encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def download(destination):
    """Fetch only the immutable candidate archive, checking it before extraction."""
    destination=Path(destination)
    if destination.exists():raise ValueError('choose a new SDK directory; existing work is preserved')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.psx-source-',dir=destination.parent) as temporary:
        work=Path(temporary);archive=work/'source.tar.gz';digest=hashlib.sha256();size=0
        with urllib.request.urlopen(URL,timeout=60) as source,archive.open('wb') as output:
            while chunk:=source.read(1024*1024):
                size+=len(chunk)
                if size>128*1024*1024:raise ValueError('candidate archive exceeds its download bound')
                digest.update(chunk);output.write(chunk)
        if digest.hexdigest()!=ARCHIVE_SHA256:raise ValueError('PS1 candidate archive checksum differs')
        with tarfile.open(archive) as source:source.extractall(work,filter='data')
        tree=work/('psxrecomp-'+COMMIT)
        if fingerprint(tree)!=SOURCE_SHA256:raise ValueError('PS1 candidate source fingerprint differs')
        tree.rename(destination)
    return destination


def run(command,cwd,log):
    result=subprocess.run(list(map(str,command)),cwd=cwd,capture_output=True,text=True,
        encoding='utf-8',errors='replace',timeout=600)
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise ValueError(f'{Path(str(command[0])).name} failed; see {log}: '+(result.stdout+result.stderr)[-3000:])
    return result.stdout


def qualify(sdk,destination,*,recompiler=None):
    sdk=Path(sdk).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('choose a new qualification directory; existing work is preserved')
    if destination.is_relative_to(sdk) or sdk.is_relative_to(destination):
        raise ValueError('qualification output and SDK source must be separate directories')
    if fingerprint(sdk)!=SOURCE_SHA256:raise ValueError('PS1 candidate sources differ from the pinned assessment revision')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.psx-proof-',dir=destination.parent) as temporary:
        work=Path(temporary);stage=work/'proof';stage.mkdir()
        if recompiler is None:
            build=work/'recompiler-build'
            run(['cmake','-S',sdk/'recompiler','-B',build,'-DCMAKE_BUILD_TYPE=Release',
                '-DBUILD_TESTING=OFF','-DPSXRECOMP_ENABLE_CHD=OFF'],stage,stage/'configure.log')
            run(['cmake','--build',build,'--target','psxrecomp-game','--config','Release','--parallel','2'],stage,stage/'recompiler-build.log')
            recompiler=next(p for p in (build/'psxrecomp-game',build/'psxrecomp-game.exe',build/'Release/psxrecomp-game.exe') if p.is_file())
        else:recompiler=Path(recompiler).resolve()
        codegen=run([recompiler,'--codegen-hash'],stage,stage/'codegen.log').strip()
        if codegen!=CODEGEN_HASH:raise ValueError('recompiler codegen hash differs from the pinned candidate')
        image,entries=program();exe=stage/'original.exe';exe.write_bytes(image)
        (stage/'seeds.txt').write_text('\n'.join(hex(a) for a in entries.values())+'\n')
        generated=stage/'generated'
        run([recompiler,exe,'--seeds',stage/'seeds.txt','--out-dir',generated,'--strict',
            '--project-root',sdk],stage,stage/'generation.log')
        source=sorted(generated.glob('*_full_*.c'))+sorted(generated.glob('*_dispatch.c'))
        if len(source)<2:raise ValueError('candidate emitted no native source/dispatch')
        shutil.copyfile(ROOT/'tests/fixtures/psx-native/runner.c',stage/'runner.c')
        quote=lambda path:json.dumps(path.as_posix())
        (stage/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
            'project(PS1NativeProbe LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
            f'set(PSX_CANDIDATE_ROOT {quote(sdk)} CACHE PATH "Pinned external candidate source")\n'
            'add_executable(native_probe runner.c '+ ' '.join(quote(p.relative_to(stage)) for p in source)+')\n'
            'target_include_directories(native_probe PRIVATE "${PSX_CANDIDATE_ROOT}/runtime/include")\n'
            'target_compile_definitions(native_probe PRIVATE PSX_NO_DEBUG_TOOLS)\n')
        shutil.copyfile(sdk/'LICENSE',stage/'PSXRecomp-LICENSE.txt')
        (stage/'README.md').write_text(
            '# Original PS1 CPU probe\n\n'
            'This assessment is not a game project or a hardware runtime. It links\n'
            'generated C against an original bounded-RAM host with IRQs disabled.\n'
            'The original program and runner are CC0; generated candidate helpers\n'
            'and external headers retain the terms in PSXRecomp-LICENSE.txt.\n\n'
            'Rebuild with the pinned candidate source retained at PSX_CANDIDATE_ROOT:\n\n'
            '```sh\ncmake -S . -B build -DPSX_CANDIDATE_ROOT=/path/to/pinned/source\n'
            'cmake --build build --config Release --parallel 2\n```\n\n'
            'assessment.json records the tested inputs and execution boundaries.\n',encoding='utf-8')
        build=stage/'build'
        run(['cmake','-S',stage,'-B',build,'-DCMAKE_BUILD_TYPE=Release'],stage,stage/'native-configure.log')
        run(['cmake','--build',build,'--config','Release','--parallel','2'],stage,stage/'native-build.log')
        native=next(p for p in (build/'native_probe',build/'native_probe.exe',build/'Release/native_probe.exe') if p.is_file())
        checks=[]
        for index,(name,a,b) in enumerate(cases()):
            actual=json.loads(run([native,exe,hex(entries[name]),hex(a),hex(b)],stage,stage/f'case-{index}.log'))
            expected=reference(image,entries[name],a,b)
            if any(actual[key]!=value for key,value in expected.items()):
                raise ValueError(f'native/original-byte mismatch in {name}({a:#x},{b:#x})')
            checks.append(dict(function=name,a=a,b=b,native_dispatches=actual['native_dispatches']))
        rejected=json.loads(run([native,exe,hex(entries['return_delay']),'0','0','--tamper'],stage,stage/'changed-code.log'))
        if rejected!={'native_rejected':True}:raise ValueError('changed original code was accepted for native dispatch')
        report=dict(schema='decomp.wtf.ps1-runtime-assessment/v1',scope='original-cpu-probes',
            candidate=dict(repository='RetroPortingToolKit/psxrecomp',commit=COMMIT,archive_sha256=ARCHIVE_SHA256,
                qualification_source_sha256=SOURCE_SHA256,codegen_hash=codegen,license=LICENSE,
                default_execution_model='hybrid',interpreter_fallback=True,runtime_compilation=True),
            original_sha256=hashlib.sha256(image).hexdigest(),checks=checks,changed_code_rejected=True,
            fixture_execution_model='static-recompiled',fixture_interpreter_fallback=False,
            hardware_runtime_qualified=False,retail_qualified=False,pc_backend_registered=False)
        (stage/'assessment.json').write_text(json.dumps(report,indent=2)+'\n')
        # Discard staging caches. Relative source paths allow a fresh rebuild.
        shutil.rmtree(build)
        stage.rename(destination)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--sdk-root',required=True,type=Path)
    parser.add_argument('--download-sdk',action='store_true',help='download the pinned noncommercial candidate to the new SDK directory')
    parser.add_argument('--recompiler',type=Path,help='reuse an already-built tool from the pinned source')
    args=parser.parse_args()
    try:
        if args.download_sdk:download(args.sdk_root)
        result=qualify(args.sdk_root,args.output,recompiler=args.recompiler)
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        parser.exit(1,str(error)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
