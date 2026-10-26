"""Original CC0 relocation probes, without a guest interpreter in the host."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

from decompnet.psx_native import copies


def original_bodies():
    # Loop with nontrivial delay slots; memory load/store; a PC-like LUI literal.
    words=[
        [0x00001021,0x00804021,0x2508ffff,0x1d00fffe,0x24420003,0x03e00008,0x00451021],
        [0x3c088002,0xad040000,0x8d020000,0,0x03e00008,0x00451026],
        [0x3c08a01e,0x25080004,0x01001021,0x03e00008,0],
    ]
    return [struct.pack('<'+'I'*len(body),*body) for body in words]


def test_copy_discovery_finds_closed_loops_and_requires_complete_delay_slots():
    from capstone import Cs,CS_ARCH_MIPS,CS_MODE_MIPS32,CS_MODE_LITTLE_ENDIAN
    decoder=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    for body in original_bodies():
        assert copies._body(body,0,decoder)==body
    assert copies._body(original_bodies()[0][:-4],0,decoder) is None
    # An escaping direct jump and a branch in a delay slot have no PIC proof.
    assert copies._body(struct.pack('<4I',0x08004000,0,0,0),0,decoder) is None
    assert copies._body(struct.pack('<4I',0x10000001,0x1000ffff,0x03e00008,0),0,decoder) is None


@pytest.fixture(scope='module')
def native_copies(tmp_path_factory):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned copied-routine emitter runs in the dedicated PS1 workflow')
    from decompnet.psx_native import _sdk,_recompiler,_run
    root=tmp_path_factory.mktemp('original relocated MIPS routines')
    sdk=_sdk();compiler=_recompiler(sdk);items=[]
    for index,data in enumerate(original_bodies(),1):
        item=dict(data=data,sha256=hashlib.sha256(data).hexdigest(),source={'fixture':index})
        meta=copies.emit_body(compiler,sdk,item,root/f'body{index}',index,_run)
        items.append((item,meta))
    copies.registry(items,root/'copies.c')
    host=(Path(__file__).parent/'fixtures/psx-native/runner.c').read_text()
    host=host.replace('static size_t original_size;',
        'unsigned char *g_psx_ram=memory;\nuint64_t decomp_native_dispatches;\nstatic size_t original_size;')
    host=host.replace('int g_psx_cps_mode;','int g_psx_cps_mode=1;')
    host=host.replace('memcpy(memory+0x10000,original,original_size);',
        'file=fopen(argv[1],"rb");if(!file)return 2;\n'
        'unsigned char header[2048];if(fread(header,1,2048,file)!=2048)return 2;fclose(file);\n'
        'uint32_t load=header[24]|((uint32_t)header[25]<<8)|((uint32_t)header[26]<<16)|((uint32_t)header[27]<<24);\n'
        'memcpy(memory+physical(load,original_size),original,original_size);')
    host+='\nextern int decomp_psx_dispatch_copy(CPUState*,uint32_t);\n'
    host+='int psx_dispatch_game_compiled(CPUState *cpu,uint32_t address){return decomp_psx_dispatch_copy(cpu,address);}\n'
    (root/'runner.c').write_text(host)
    sources=sorted(root.glob('body*/*_full_*.c'))
    quote=lambda p:json.dumps(p.as_posix())
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(OriginalCopies LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(native_probe runner.c copies.c '+
        ' '.join(quote(p.relative_to(root)) for p in sources)+')\n'
        'target_include_directories(native_probe PRIVATE '+quote(sdk/'runtime/include')+')\n'
        'target_compile_definitions(native_probe PRIVATE PSX_NO_DEBUG_TOOLS)\n')
    for command in (['cmake','-S',root,'-B',root/'build','-DCMAKE_BUILD_TYPE=Release'],
                    ['cmake','--build',root/'build','--config','Release','--parallel','2']):
        _run(command,'Build original copied-routine host')
    binary=next(p for p in (root/'build/native_probe',root/'build/native_probe.exe',
                            root/'build/Release/native_probe.exe') if p.exists())
    return root,binary,items


def test_copies_match_original_registers_and_memory_at_relocated_segment_addresses(native_copies):
    import unicorn
    from unicorn import mips_const as mips
    root,binary,items=native_copies
    for index,(item,meta) in enumerate(items):
        for base in (0x80070000,0xa000800c,0x00090004):
            for offset in sorted({entry['offset'] for entry in meta['entries']}):
                for a,b in ((0,3),(1,7),(7,9),(0xffffffff,0x80000000)):
                    entry=base+offset
                    image=root/'actual-placement.exe'
                    header=bytearray(2048);header[:8]=b'PS-X EXE'
                    struct.pack_into('<4I',header,0x10,entry,0,base,len(item['data']))
                    image.write_bytes(header+item['data'])
                    args=list(map(str,[binary,image,hex(entry),hex(a),hex(b)]))
                    done=subprocess.run(args,capture_output=True,text=True,timeout=30)
                    assert done.returncode==0,done.stdout+done.stderr
                    actual=json.loads(done.stdout)
                    cpu=unicorn.Uc(unicorn.UC_ARCH_MIPS,unicorn.UC_MODE_MIPS32|unicorn.UC_MODE_LITTLE_ENDIAN)
                    cpu.mem_map(0,0x200000);cpu.mem_write(base&0x1fffffff,item['data'])
                    for reg,value in ((mips.UC_MIPS_REG_A0,a),(mips.UC_MIPS_REG_A1,b),(mips.UC_MIPS_REG_RA,0x801fff00)):
                        cpu.reg_write(reg,value)
                    cpu.emu_start(entry,0x801fff00,count=1000)
                    assert cpu.reg_read(mips.UC_MIPS_REG_PC)==0x801fff00
                    assert actual['registers']==[cpu.reg_read(mips.UC_MIPS_REG_0+i)&0xffffffff for i in range(32)]
                    assert actual['memory']==struct.unpack('<I',cpu.mem_read(0x20000,4))[0]
                    assert actual['native_dispatches']>0
                    changed=subprocess.run([*args,'--tamper'],capture_output=True,text=True,timeout=30)
                    assert changed.returncode==0 and json.loads(changed.stdout)=={'native_rejected':True}
