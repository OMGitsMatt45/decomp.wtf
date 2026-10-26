"""Original CC0 programs: automatic disc discovery and immutable overlay guards."""
import io
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

from decompnet.psx_native import codegen, media, module_discovery
from decompnet.rom import psx_lzss
from .fixtures.psx_hardware import executable

BASE = 0x80060000


def payload(increment=7):
    # Packed callback pointer, data prefix, framed function, then a short leaf.
    data = bytearray(b'\xff'*32)
    struct.pack_into('<I', data, 1, BASE+64)
    data += struct.pack('<8I', 0x27bdfff0, 0xafbf000c, 0x24820000 | increment,
                        0x8fbf000c, 0x27bd0010, 0x03e00008, 0x24420005, 0)
    data += struct.pack('<3I', 0x00041040, 0x03e00008, 0x24420002)
    return bytes(data)


def original_disc():
    import pycdlib
    first, second = payload(), payload(27)
    records = [(first, len(first)+128, BASE, 0, 31),
               (psx_lzss.encode(second), len(second), BASE, 0x500, 31),
               (first, len(first), BASE, 0, 31),  # duplicate bytes/address
               (first, len(first), BASE+0x10000, 0, 31),
               (b'original resource data'*8, 176, BASE, 0, 31),
               (first, len(first), 0, 0, 31),
               (first, len(first), BASE, 0, 14),
               (first, len(first), BASE, 0x46, 31),
               (first, len(first), 0x801ffff0, 0, 31)]
    table = b''.join(struct.pack('<IIIHH', len(data), size, load, flags, kind)
                     for data, size, load, flags, kind in records)
    body = b''.join(item[0] for item in records)
    sectors = (16+len(table)+len(body)+2047)//2048
    archive = (struct.pack('<4I', len(records), sectors, len(body), 1)+table+body).ljust(sectors*2048, b'\0')
    other = bytearray(executable())
    # A second complete executable may have a file trailer outside its RAM image.
    struct.pack_into('<I', other, 0x10, 0x80080000)
    struct.pack_into('<I', other, 0x18, 0x80080000)
    other += b'original file trailer'
    files = {'/SYSTEM.CNF;1': b'BOOT=cdrom:\\BOOT.EXE;1\r\n',
             '/BOOT.EXE;1': executable(), '/DATA/MODULES.BIN;1': archive,
             '/DATA/ALT.EXE;1': bytes(other), '/DATA/DUP.EXE;1': executable()}
    disc = pycdlib.PyCdlib();disc.new(interchange_level=3, vol_ident='ORIGINAL_MODULES')
    disc.add_directory('/DATA')
    for name, data in files.items():
        disc.add_fp(io.BytesIO(data), len(data), iso_path=name)
    output = io.BytesIO();disc.write_fp(output);disc.close()
    return output.getvalue()


@pytest.mark.parametrize('raw', [False, True])
def test_disc_programs_and_compressed_memory_modules_keep_independent_images(tmp_path, raw):
    image = original_disc()
    if raw:
        from .test_psx_modify import valid_raw
        image = valid_raw(image, 2352, 24)
    path = tmp_path/('original.bin' if raw else 'original.iso');path.write_bytes(image)
    disc = media.prepare([path])[0]
    modules = disc['modules']
    assert len(modules) == 4
    embedded = [item for item in modules if item['source']['format'] == 'hbd-memory']
    assert len(embedded) == 3
    assert [item['image'][2048:] for item in embedded] == [payload(), payload(27), payload()]
    assert [item['info']['load'] for item in embedded] == [BASE, BASE, BASE+0x10000]
    for item in embedded:
        low = item['info']['load']
        assert {low+32, low+64} <= set(codegen.seeds(item['image'], item['info']))
        assert low not in codegen.seeds(item['image'], item['info'])
    program = next(item for item in modules if item['source']['format'] == 'iso-program')
    assert program['source']['path'] == 'DATA/ALT.EXE'
    assert not program['image'].endswith(b'original file trailer')
    assert path.read_bytes() == image


def test_memory_candidates_require_code_and_bounded_ram_addresses():
    make = module_discovery.memory_image
    assert make(bytes(80), BASE, {}) is None
    assert make(payload(), 0x801ffff0, {}) is None
    assert make(payload(), BASE+1, {}) is None
    assert make(payload(), 0x1f800000, {}) is None
    alias = make(payload(), BASE | 0x20000000, {})
    assert alias['info']['load'] == BASE
    assert alias['info']['native_entries'] == [BASE+32, BASE+64]


def test_retained_import_also_discovers_archive_programs(tmp_path):
    from decompnet.rom import detect, psx_media
    original = original_disc()
    path = tmp_path/'original.iso';path.write_bytes(original)
    picked = detect.identify(path)
    root = tmp_path/'retained';root.mkdir()
    psx_media.snapshot(path,picked,root)
    project = dict(root=str(root),psx_disc={**picked.disc,'file':'original-disc.bin'})
    imported = media.project_input(project,1)
    assert len(imported['modules']) == 4
    assert sum(item.get('source',{}).get('format') == 'hbd-memory' for item in imported['modules']) == 3
    assert path.read_bytes() == original


def test_direct_export_records_automatically_discovered_sources(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned emitter execution runs in the dedicated PS1 workflow')
    from decompnet.psx_native import export
    original = original_disc()
    path = tmp_path/'original.iso';path.write_bytes(original)
    result = export([path],tmp_path/'source')
    assert result['integrity_verified']
    modules = result['manifest']['code_generation']
    assert len(modules) == 5
    assert [item['index'] for item in modules] == [1, 2, 3, 4, 5]
    assert all(item['disc'] == 1 for item in modules)
    assert sorted(item['source']['format'] for item in modules if 'source' in item) == [
        'hbd-memory', 'hbd-memory', 'hbd-memory', 'iso-program']
    assert result['manifest']['fallback'] == dict(interpreter=True, runtime_compilation=False)
    assert path.read_bytes() == original


def test_discovered_overlay_execution_matches_original_and_rejects_changed_bytes(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned emitter execution runs in the dedicated PS1 workflow')
    from decompnet.psx_native import _sdk, _recompiler, _run
    sdk = _sdk();recompiler = _recompiler(sdk)
    path = tmp_path/'original.iso';path.write_bytes(original_disc())
    modules = [item for item in media.prepare([path])[0]['modules']
               if item['source']['format'] == 'hbd-memory']
    generated = []
    for index, item in enumerate(modules, 1):
        generated.append(codegen.module(recompiler, dict(item, index=1, module_index=index),
                                        tmp_path/f'module{index}', _run, sdk))
    codegen.registry(generated, tmp_path/'registry.c')
    # Reuse the original bounded-RAM CPU host; load each module at its declared
    # address and initialize a real stack for its framed entry. No interpreter.
    host = (Path(__file__).parent/'fixtures/psx-native/runner.c').read_text()
    host = host.replace('static size_t original_size;',
                        'unsigned char *g_psx_ram=memory;\nstatic size_t original_size;')
    host = host.replace('memcpy(memory+0x10000,original,original_size);',
        'file=fopen(argv[1],"rb");if(!file)return 2;\n'
        'unsigned char header[2048];if(fread(header,1,2048,file)!=2048)return 2;fclose(file);\n'
        'uint32_t load=header[24]|((uint32_t)header[25]<<8)|((uint32_t)header[26]<<16)|((uint32_t)header[27]<<24);\n'
        'memcpy(memory+physical(load,original_size),original,original_size);')
    host = host.replace('CPUState cpu={0};', 'CPUState cpu={0};cpu.gpr[29]=0x801fe000u;')
    (tmp_path/'runner.c').write_text(host)
    sources = sorted(tmp_path.glob('module*/*_full_*.c'))+sorted(tmp_path.glob('module*/*_dispatch.c'))
    quote = lambda p: json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(OriginalModules LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(native_probe runner.c registry.c '+
        ' '.join(quote(p.relative_to(tmp_path)) for p in sources)+')\n'
        'target_include_directories(native_probe PRIVATE '+quote(sdk/'runtime/include')+')\n'
        'target_compile_definitions(native_probe PRIVATE PSX_NO_DEBUG_TOOLS)\n')
    for command in (['cmake', '-S', tmp_path, '-B', tmp_path/'build', '-DCMAKE_BUILD_TYPE=Release'],
                    ['cmake', '--build', tmp_path/'build', '--config', 'Release', '--parallel', '2']):
        _run(command, 'Build original module probe')
    binary = next(p for p in (tmp_path/'build/native_probe', tmp_path/'build/native_probe.exe',
                              tmp_path/'build/Release/native_probe.exe') if p.exists())
    import unicorn
    from unicorn import mips_const as mips
    for index, item in enumerate(modules, 1):
        image = tmp_path/f'module{index}'/item['boot']
        for offset in (32, 64):
            entry = item['info']['load']+offset
            args = [binary, image, hex(entry), '7', '9']
            actual = json.loads(_run(args, 'Execute discovered module'))
            cpu = unicorn.Uc(unicorn.UC_ARCH_MIPS, unicorn.UC_MODE_MIPS32 | unicorn.UC_MODE_LITTLE_ENDIAN)
            cpu.mem_map(0, 0x200000);cpu.mem_write(item['info']['load'] & 0x1fffffff, item['image'][2048:])
            for reg, value in ((mips.UC_MIPS_REG_A0, 7), (mips.UC_MIPS_REG_A1, 9),
                               (mips.UC_MIPS_REG_SP, 0x801fe000), (mips.UC_MIPS_REG_RA, 0x801fff00)):
                cpu.reg_write(reg, value)
            cpu.emu_start(entry, 0x801fff00, count=1000)
            expected = [cpu.reg_read(mips.UC_MIPS_REG_0+i) & 0xffffffff for i in range(32)]
            assert actual['registers'] == expected
            assert actual['pc'] == 0x801fff00 and actual['native_dispatches'] > 0
            assert json.loads(_run([*args, '--tamper'], 'Reject changed module')) == {'native_rejected': True}
            # The same physical word in another execution segment must not use
            # a body whose link addresses and instruction fetch tags differ.
            wrong = subprocess.run(list(map(str,[binary,image,hex(entry ^ 0x20000000),'7','9'])),
                                   capture_output=True,text=True,timeout=30)
            assert wrong.returncode == 4 and 'would require fallback' in wrong.stderr
