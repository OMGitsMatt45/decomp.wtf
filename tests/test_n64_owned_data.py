"""A matching export cannot hide changed private constants behind original data."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from decompnet import compiler, project, toolchains
from decompnet.app.engine import RomNetwork
from .test_n64code import _code


@pytest.mark.parametrize('toolchain,frontend', [('gcc-2.7.2-kmc', ''), ('ido-5.3', 'edg'),
                                               ('ido-5.3', 'cfront'), ('ido-7.1', 'edg')])
def test_default_export_revalidates_owned_constants(tmp_path, toolchain, frontend):
    if toolchains.installed(toolchain) is None:
        pytest.skip('requires the pinned N64 compilers')
    source = 'int entrypoint(int index) { static const int values[8] = {3,5,7,11,13,17,23,47}; return values[index & 7]; }\n'
    settings = {'toolchain': toolchain, 'language': 'c++', 'sandbox': 'none',
                **({'cpp_frontend': frontend} if frontend else {})}
    cfg = project.compiler_config(tmp_path, {'kind': 'rom', 'platform': 'n64', 'compiler': settings})
    obj = compiler.compile_source(cfg, '', source)
    assert obj.ok, obj.log
    (tmp_path / 'original.o').write_bytes(obj.obj)
    (tmp_path / 'layout.ld').write_text('SECTIONS { .text 0x80000400 : { *(.text) } '
                                       '.rodata 0x80001000 : { *(.rodata) *(.rdata) *(.data) } '
                                       '/DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.mdebug*) } }')
    tools = toolchains.binary('binutils-mips').parent
    suffix = '.exe' if sys.platform == 'win32' else ''
    def command(tool, *args):
        subprocess.run([str(tools / ('mips-ps2-decompals-' + tool + suffix)), *args], cwd=tmp_path,
                       check=True, capture_output=True)
    command('ld', '-EB', '-T', 'layout.ld', '-o', 'original.elf', 'original.o')
    command('objcopy', '-O', 'binary', 'original.elf', 'original.bin')
    body = (tmp_path / 'original.bin').read_bytes()
    image = bytearray(0x40000)
    image[:16] = struct.pack('>4I', 0x80371240, 0xF, 0x80000400, 0x1449)
    image[0x20:0x34] = b'OWNED N64 DATA TEST'.ljust(20, b' ')
    image[0x1000:0x1000 + len(body)] = body
    code = _code(0x80000600, 40)
    image[0x1200:0x1200 + len(code)] = code
    layout = {'format': 1, 'sha256': hashlib.sha256(image).hexdigest(), 'modules': [
        {'name': 'main', 'rom_start': 0x1000, 'rom_end': 0x1000 + len(body), 'vram': 0x80000400,
         'sections': [{'offset': 0, 'type': 'code'}, {'offset': 0xC00, 'type': 'rodata'}]}]}
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(bytes(image), reviewed_layout=layout, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    row = net.project_row(slug)
    config = net.cfg(row)
    config['compiler'].update(settings)
    with net.store.tx() as db:
        db.execute('UPDATE projects SET config=? WHERE id=?', (json.dumps(config), row['id']))
    agent, _ = net.local_agent('test')
    attempt = net.attempt(agent, 'entrypoint', source, slug)
    assert attempt['matched'], attempt
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'] and result['matched'] == 1 and not result['fallback'], result['log']
    tree = Path(result['path'])
    path = tree / 'src/main/entrypoint.cpp'
    text = path.read_text()
    assert '47' in text
    path.write_text(text.replace('47', '48'))
    failed = subprocess.run([sys.executable, 'build.py'], cwd=tree, capture_output=True, text=True)
    assert failed.returncode != 0 and 'differs' in failed.stdout, failed.stdout + failed.stderr
    assert not (tree / 'build/game.z64').exists()
