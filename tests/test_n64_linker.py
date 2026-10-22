"""Standalone links must handle retail object lists beyond Windows' argv limit."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.rom import export


def test_standalone_link_handles_long_arguments_and_library_paths_with_spaces(tmp_path):
    if toolchains.installed('binutils-mips') is None:
        pytest.skip('requires pinned MIPS binutils')
    root = tmp_path / 'standalone project with spaces'
    (root / 'build/dependency libraries with spaces').mkdir(parents=True)
    shutil.copyfile(Path(export.__file__).with_name('export_build.py'), root / 'build.py')
    (root / 'build.json').write_text(json.dumps({'compiler': {}}))
    spec = importlib.util.spec_from_file_location('large_export_builder', root / 'build.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    (root / 'entry.s').write_text('.set noreorder\n.text\n.globl entrypoint\n'
                                  '.ent entrypoint\nentrypoint:\njr $ra\nnop\n.end entrypoint\n', newline='\n')
    tools = toolchains.binary('binutils-mips').parent
    suffix = '.exe' if sys.platform == 'win32' else ''
    subprocess.run([str(tools / ('mips-ps2-decompals-as' + suffix)), '-EB', '-march=vr4300',
                    '-o', 'build/entry.o', 'entry.s'], cwd=root, check=True, capture_output=True)
    archive = 'build/dependency libraries with spaces/empty library.a'
    (root / archive).write_bytes(b'!<arch>\n')
    # Empty archives exercise GNU ld's real response parser cheaply. Repeating
    # them exceeds CreateProcess's limit without requiring thousands of compiles.
    args = [str(tools / ('mips-ps2-decompals-ld' + suffix)), '-EB', '-Ttext', '0x80000400',
            '-e', 'entrypoint', '-o', 'build/large.elf', 'build/entry.o', *([archive] * 2000)]
    assert len(subprocess.list2cmdline(args)) > 32767
    builder.run(args)
    response = (root / 'build/large.rsp').read_text()
    assert response.count('"' + archive + '"') == 2000
    with (root / 'build/large.elf').open('rb') as stream:
        elf = ELFFile(stream)
        assert elf['e_entry'] == 0x80000400
        assert elf.get_section_by_name('.text').data()[:8] == bytes.fromhex('03E0000800000000')


def test_thousands_of_exact_object_placements_link_without_cubic_file_searches(tmp_path):
    if toolchains.installed('binutils-mips') is None:
        pytest.skip('requires pinned MIPS binutils')
    root = tmp_path / 'large standalone project'
    (root / 'build/objects').mkdir(parents=True)
    count, base = 4000, 0x80000400
    shutil.copyfile(Path(export.__file__).with_name('export_build.py'), root / 'build.py')
    (root / 'image.bin').write_bytes(bytes(count * 4))
    (root / 'nop.s').write_text('.set noreorder\n.text\nnop\n', newline='\n')
    tools = toolchains.binary('binutils-mips').parent
    suffix = '.exe' if sys.platform == 'win32' else ''
    subprocess.run([str(tools / ('mips-ps2-decompals-as' + suffix)), '-EB', '-march=vr4300',
                    '-no-pad-sections', '-o', 'build/nop.o', 'nop.s'], cwd=root, check=True, capture_output=True)
    data = (root / 'build/nop.o').read_bytes()
    functions, provides = [], {}
    for index in range(count):
        name = f'function_{index:05d}'
        obj = f'build/objects/{name}.o'
        (root / obj).write_bytes(data)
        provides[name] = obj
        functions.append({'name': name, 'seg': 'main', 'vram': base + index * 4, 'rom': index * 4})
    metadata = {'compiler': {}, 'symbols': {}, 'image': 'image.bin', 'functions': functions, 'segments': [
        {'name': 'main', 'kind': 'code', 'vram': base, 'start': 0, 'end': count * 4,
         'pieces': [], 'bss': [], 'bss_size': 0}]}
    (root / 'build.json').write_text(json.dumps(metadata))
    (root / 'provides.json').write_text(json.dumps(provides))
    args = [str(tools / ('mips-ps2-decompals-ld' + suffix)), '-EB', '-T', 'build/large.ld',
            '-e', hex(base), '-o', 'build/large.elf', *provides.values()]
    assert len(subprocess.list2cmdline(args)) > 32767
    (root / 'arguments.json').write_text(json.dumps(args))
    (root / 'link.py').write_text('import json\nfrom pathlib import Path\nimport build\n'
        'p=json.loads(Path("provides.json").read_text())\n'
        'Path("build/large.ld").write_text(build.linker_script(p, []))\n'
        'build.run(json.loads(Path("arguments.json").read_text()))\n', newline='\n')
    linked = subprocess.run([sys.executable, 'link.py'], cwd=root, capture_output=True, text=True, timeout=60)
    assert linked.returncode == 0, linked.stdout + linked.stderr
    with (root / 'build/large.elf').open('rb') as stream:
        elf = ELFFile(stream)
        assert elf['e_entry'] == base
        assert elf.get_section_by_name('.main').data() == bytes(count * 4)
