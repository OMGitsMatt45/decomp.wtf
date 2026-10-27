"""Original CPU-only source fixture for adapter, routing and project-management tests."""
import hashlib
import json
from pathlib import Path

from decompnet import pc


def generate(project, root):
    (root/'main.cpp').write_text('#include <cstdio>\nint main(){ unsigned char ram[4]={1,2,3,4}; '
        'unsigned value=ram[0]|ram[1]<<8|ram[2]<<16|ram[3]<<24; '
        'if(value!=0x04030201u)return 1; puts("pc-fixture-pass"); return 0; }\n')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(PCFixture LANGUAGES CXX)\nadd_executable(pc_fixture main.cpp)\n')
    manifest=dict(schema=pc.SCHEMA,output_kind='cpu-probe',qualification=dict(graphics=False,retail=False),
        platform=project.get('platform','nds'),backend=dict(id='original-fixture',revision='1'),
        execution_model='native-source',runtime=dict(id='original-host-fixture',revision='1'),
        inputs=[dict(sha256=hashlib.sha256(b'original fixture').hexdigest())],
        build=dict(system='cmake',target='pc_fixture'),fallback=dict(interpreter=False,runtime_compilation=False),
        files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('main.cpp','CMakeLists.txt')})
    (root/'pc-project.json').write_text(json.dumps(manifest))


def result(root, platform):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    generate(dict(platform=platform),root)
    return dict(format='pc',path=str(root),**pc.verify(root))
