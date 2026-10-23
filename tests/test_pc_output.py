import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet import pc


def generate(project, root):
    # Original host fixture: validates adapter/export/build plumbing, not a DS runtime.
    (root/'main.cpp').write_text('#include <cstdio>\nint main(){ unsigned char ram[4]={1,2,3,4}; '
        'unsigned value=ram[0]|ram[1]<<8|ram[2]<<16|ram[3]<<24; '
        'if(value!=0x04030201u)return 1; puts("pc-fixture-pass"); return 0; }\n')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(PCFixture LANGUAGES CXX)\nadd_executable(pc_fixture main.cpp)\n')
    manifest=dict(schema=pc.SCHEMA, platform='nds',backend=dict(id='original-fixture',revision='1'),
        execution_model='native-source',runtime=dict(id='original-host-fixture',revision='1'),
        inputs=[dict(sha256=hashlib.sha256(b'original fixture').hexdigest())],
        build=dict(system='cmake',target='pc_fixture'),
        fallback=dict(interpreter=False,runtime_compilation=False),
        files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('main.cpp','CMakeLists.txt')})
    (root/'pc-project.json').write_text(json.dumps(manifest))


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(pc,'BACKENDS',{'original-fixture':pc.Backend('original-fixture','nds','1',generate)})


def test_missing_backend_never_substitutes_console_export(tmp_path):
    assert pc.status('nds')['available'] is False
    with pytest.raises(pc.PCError,match='No PC-project backend'):
        pc.export(dict(platform='nds'),tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_generated_project_builds_and_executes_on_host(tmp_path,backend):
    if not shutil.which('cmake'):
        pytest.fail('CMake is required for the PC-output contract qualification')
    output=tmp_path/'PC project with spaces'
    result=pc.export(dict(platform='nds'),output)
    assert result['integrity_verified'] and not result['host_build_verified'] and not result['gameplay_verified']
    subprocess.run(['cmake','-S',str(output),'-B',str(output/'build'),'-DCMAKE_BUILD_TYPE=Release'],check=True,capture_output=True)
    subprocess.run(['cmake','--build',str(output/'build'),'--config','Release'],check=True,capture_output=True)
    paths=[output/'build/pc_fixture',output/'build/pc_fixture.exe',output/'build/Release/pc_fixture.exe']
    executable=next(path for path in paths if path.is_file())
    ran=subprocess.run([str(executable)],check=True,capture_output=True,text=True)
    assert ran.stdout.strip() == 'pc-fixture-pass'


def test_existing_work_preserved(tmp_path,backend):
    output=tmp_path/'output'
    output.mkdir()
    (output/'user.cpp').write_text('user changes')
    with pytest.raises(pc.PCError,match='existing work'):
        pc.export(dict(platform='nds'),output)
    assert (output/'user.cpp').read_text() == 'user changes'


def test_invalid_generated_project_never_published(tmp_path,monkeypatch):
    def bad(project,root):
        generate(project,root)
        (root/'main.cpp').write_text('changed after hashing')
    monkeypatch.setattr(pc,'BACKENDS',{'bad':pc.Backend('original-fixture','nds','1',bad)})
    with pytest.raises(pc.PCError,match='hash differs'):
        pc.export(dict(platform='nds'),tmp_path/'output')
    assert not (tmp_path/'output').exists()
    assert not list(tmp_path.glob('.pc-export-*'))


@pytest.mark.parametrize('change', ['path','source','runtime','fallback','platform'])
def test_manifest_rejects_incomplete_or_misleading_pc_output(tmp_path,change):
    generate({},tmp_path)
    path=tmp_path/'pc-project.json';data=json.loads(path.read_text())
    if change=='path':data['files']['../outside.cpp']='0'*64
    elif change=='source':data['files'].pop('main.cpp')
    elif change=='runtime':data.pop('runtime')
    elif change=='fallback':data['fallback']['interpreter']=True
    elif change=='platform':data['platform']='n64'
    path.write_text(json.dumps(data))
    with pytest.raises(pc.PCError):pc.verify(tmp_path)
