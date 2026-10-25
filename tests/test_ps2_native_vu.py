"""Independent rational arithmetic checks static VU lane values and flags."""
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from tools.qualify_ps2_runtime import executable

OPERATIONS = [(op, mask, fd, fs) for op in (0x28, 0x2C, 0x2A) for mask in (0, 1, 8, 14, 15)
              for fd, fs in ((3, 1),)] + [(0x2C, 15, 1, 1), (0x28, 15, 0, 1), (0x2C, 15, 3, 0)]
SENTINEL = [0xDEADBEEF] * 4
MAXIMUM = Fraction((1 << 24) - 1) * (1 << 104)
MINIMUM = Fraction(1, 1 << 126)


def operand(bits):
    exponent = (bits >> 23) & 255
    sign = -1 if bits >> 31 else 1
    if not exponent: return Fraction(0)
    if exponent == 255: return sign * MAXIMUM
    mantissa = (bits & 0x7FFFFF) | (1 << 23)
    power = exponent - 150
    return sign * Fraction(mantissa) * (Fraction(1 << power) if power >= 0 else Fraction(1, 1 << -power))


def lane(op, a, b):
    left, right = operand(a), operand(b)
    exact = left + right if op == 0x28 else left - right if op == 0x2C else left * right
    sign = int(exact < 0)
    if exact == 0:
        sign = (a >> 31) ^ (b >> 31) if op == 0x2A else int(left == right == 0 and (a >> 31) and
                ((b >> 31) if op == 0x28 else not (b >> 31)))
    flags = sign << 1
    magnitude = abs(exact)
    if not magnitude: return sign << 31, flags | 1
    if magnitude < MINIMUM: return sign << 31, flags | 5
    if magnitude > MAXIMUM: return (sign << 31) | 0x7F7FFFFF, flags | 8
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    scale = Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
    if magnitude < scale: exponent -= 1
    power = 23 - exponent
    significand = int(magnitude * (Fraction(1 << power) if power >= 0 else Fraction(1, 1 << -power)))
    return (sign << 31) | ((exponent + 127) << 23) | (significand - (1 << 23)), flags


def expected(operation, a, b, status):
    op, mask, fd, fs = operation
    left = [0, 0, 0, 0x3F800000] if fs == 0 else a
    values = a.copy() if fd == 1 else [0, 0, 0, 0x3F800000] if fd == 0 else SENTINEL.copy()
    mac, current = 0, 0
    for n in range(4):
        bit = 8 >> n
        if not mask & bit: continue
        value, flags = lane(op, left[n], b[n])
        if fd: values[n] = value
        current |= flags
        for group in range(4):
            if flags & (1 << group): mac |= bit << (4 * group)
    return dict(values=values, mac=mac if mask else 0xA55A,
        status=((status & ~15) | current | (current << 6)) if mask else status, rounding_restored=True)


@pytest.fixture(scope='module',params=('template','emitted'))
def vu_probe(tmp_path_factory,request):
    root = os.environ.get('DECOMP_PS2_PORT_SDK')
    if not root: pytest.skip('set DECOMP_PS2_PORT_SDK to validate the pinned portable runtime')
    from decompnet.ps2_native.provider import verify
    verify(root)
    if not shutil.which('cmake'): pytest.fail('VU qualification requires CMake and C++20')
    work = tmp_path_factory.mktemp('static VU source with spaces')
    shutil.copyfile(Path(__file__).parents[1] / 'src/decompnet/ps2_native/vu0.hpp', work / 'decomp_vu0.hpp')
    (work/'second module').mkdir()
    shutil.copyfile(work/'decomp_vu0.hpp',work/'second module/decomp_vu0.hpp')
    calls = []
    generated=[]
    if request.param=='emitted':
        emitter=os.environ.get('DECOMP_PS2_PATCHED_EMITTER')
        if not emitter:pytest.skip('set DECOMP_PS2_PATCHED_EMITTER to validate actual patched emission')
        from tests.fixtures.ps2_native import program,r,BASE
        from decompnet.ps2_native.runtime_patch import install_vu_header
        from decompnet.ps2_native.reports import generation_report
        raw=bytearray(program()[0]);table=struct.unpack_from('<I',raw,32)[0]
        symbols=struct.unpack_from('<I',raw,table+4*40+16)[0]
        for n,(op,mask,fd,fs) in enumerate(OPERATIONS):
            word=0x4A000000 | (mask<<21) | (2<<16) | (fs<<11) | (fd<<6) | op
            struct.pack_into('<3I',raw,0x100+n*0x100,word,r(8,rs=31),0)
            struct.pack_into('<I',raw,symbols+(n+1)*16+8,12)
        struct.pack_into('<I',raw,table+4*40+20,(len(OPERATIONS)+1)*16)
        (work/'original.elf').write_bytes(raw)
        (work/'fixture.toml').write_text('[general]\ninput="original.elf"\noutput="generated"\n'
            'single_file_output=false\noutput_worker_threads=1\npatch_syscalls=false\npatch_cop0=false\npatch_cache=false\nstubs=[]\nskip=[]\n')
        result=subprocess.run([emitter,'fixture.toml'],cwd=work,capture_output=True,text=True,timeout=60)
        (work/'emission.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stderr
        generation_report(result.stdout+result.stderr,expected_functions=len(OPERATIONS))
        install_vu_header(work/'generated')
        import re
        declarations=(work/'generated/ps2_recompiled_functions.h').read_text()
        names=re.findall(r'void (\w+)\(',declarations)
        for n in range(len(OPERATIONS)):
            name=next(name for name in names if name.endswith(f'_0x{BASE+n*0x100:x}'))
            generated.append(work/f'generated/{name}.cpp')
            calls.append(f'case {n}: {name}(nullptr,&ctx,nullptr); break;')
    for index, (op, mask, fd, fs) in enumerate(OPERATIONS):
        raw = 0x4A000000 | (mask << 21) | (2 << 16) | (fs << 11) | (fd << 6) | op
        if request.param=='template':calls.append(f'case {index}: decomp_ps2::vu_upper<0x{raw:08x}u>(ctx); break;')
    (work / 'main.cpp').write_text(('' if not generated else '#include "generated/ps2_recompiled_functions.h"\n')+'''#include "decomp_vu0.hpp"
#include "second module/decomp_vu0.hpp"
#include <cstdio>
#include <cstdlib>
int main(int argc,char **argv) {
 if(argc!=11) return 1;
 R5900Context ctx; uint32_t a[4],b[4],sentinel[4]={0xdeadbeef,0xdeadbeef,0xdeadbeef,0xdeadbeef};
 for(unsigned n=0;n<4;n++){a[n]=std::strtoul(argv[3+n],nullptr,16);b[n]=std::strtoul(argv[7+n],nullptr,16);}
 std::memcpy(&ctx.vu0_vf[1],a,16);std::memcpy(&ctx.vu0_vf[2],b,16);std::memcpy(&ctx.vu0_vf[3],sentinel,16);
 ctx.vu0_status=std::strtoul(argv[2],nullptr,16); ctx.vu0_mac_flags=0xa55a;
 const int previous=std::fegetround();
 const unsigned index=std::strtoul(argv[1],nullptr,10);
 switch(index) {''' + '\n'.join(calls) + '''default:return 2;}
 constexpr unsigned destinations[]={''' + ','.join(str(x[2]) for x in OPERATIONS) + '''};
 uint32_t words[4]; std::memcpy(words,&ctx.vu0_vf[destinations[index]],16);
 std::printf("{\\"values\\":[%u,%u,%u,%u],\\"mac\\":%u,\\"status\\":%u,\\"rounding_restored\\":%s}\\n",
 words[0],words[1],words[2],words[3],ctx.vu0_mac_flags,ctx.vu0_status,std::fegetround()==previous?"true":"false");
}
''', encoding='utf-8')
    runtime = Path(root) / 'thirdparty/PS2Recomp/ps2xRuntime'
    (work / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(StaticVu LANGUAGES CXX)
add_executable(static_vu main.cpp)
''' + ('target_sources(static_vu PRIVATE '+ ' '.join('"'+p.as_posix()+'"' for p in generated)+')\n' if generated else '')+'''
target_compile_features(static_vu PRIVATE cxx_std_20)
target_include_directories(static_vu PRIVATE
''' + '\n'.join(' "' + (runtime / p).as_posix() + '"' for p in ('include','include/runtime','src/lib/vu','src/lib/Kernel','../ps2xIOP/include')) + ''')
if(MSVC)
 target_compile_options(static_vu PRIVATE /O2 /fp:strict)
else()
 target_compile_options(static_vu PRIVATE -O2 -msse4.1 -ffp-contract=off -frounding-math)
endif()
''', encoding='utf-8')
    build = work / 'build'
    for label, command in (('configure',['cmake','-S',work,'-B',build]), ('build',['cmake','--build',build,'--config','Release','--parallel','2'])):
        result = subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=180)
        (work / (label + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    return executable(build,'static_vu')


def test_static_vector_values_masked_lanes_and_current_sticky_flags(vu_probe):
    vectors = [([0x3F800000,0xC0000000,0,0x80000000],[0x40000000,0x3F800000,0x80000000,0]),
               ([0x7F7FFFFF,0xFF7FFFFF,0x00800000,0x80800000],[0x7F7FFFFF,0x7F7FFFFF,0x3F000000,0xBF000000]),
               ([0x7FC00001,0xFF800000,1,0x80000001],[0x7F800000,0x7FC00000,0x00800000,0x00800000]),
               ([0x3F800001,0x3F800000,0x00800001,0x80000000],[0x33800000,0x3F7FFFFF,0x00800000,0x80000000])]
    for index, operation in enumerate(OPERATIONS):
        for a,b in vectors:
            for status in (0, 0xFF0):
                result = subprocess.run([vu_probe,str(index),f'{status:x}',*[f'{v:x}' for v in a+b]],capture_output=True,text=True,timeout=10)
                assert result.returncode == 0, result.stderr
                assert json.loads(result.stdout) == expected(operation,a,b,status), (operation,a,b,status,result.stdout)
