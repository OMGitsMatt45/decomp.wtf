"""Original host sentinels check module selection, ambiguity and side effects.

EE semantics are tested separately by the generated/native candidate fixture.
These sentinels test registry behavior rather than replacing EE instructions.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native.registry import isolate, registry
from tools.qualify_ps2_runtime import executable


def test_bad_dense_mapping_leaves_generated_module_untouched(tmp_path):
    identity = '1' * 64; namespace = 'decomp_ps2_module_' + identity
    (tmp_path / (namespace + '.hpp')).write_text('// original guard\n')
    (tmp_path / 'ps2_recompiled_functions.h').write_text('void original(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime);\n')
    (tmp_path / 'register_functions.cpp').write_text('extern const uint32_t g_ps2RecompiledFunctionTableBase = 0x100000u;\n'
        'extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = 4u;\n'
        'g_ps2RecompiledFunctionTable[0] = original; // 0x100004\n')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(PCError, match='dense-table'):
        isolate(tmp_path, dict(original_elf_sha256=identity, guarded_functions=1))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_duplicate_modules_and_existing_registry_are_preserved(tmp_path):
    module = dict(identity='1' * 64)
    output = tmp_path / 'registry.cpp'
    with pytest.raises(PCError, match='unique'): registry([module, module], output)
    assert not output.exists()
    output.write_text('existing user work')
    with pytest.raises(PCError, match='existing'): registry([], output)
    assert output.read_text() == 'existing user work'


def test_native_registry_selects_bytes_rejects_ambiguity_and_preserves_nested_failures(tmp_path):
    if not shutil.which('cmake'):
        if os.environ.get('DECOMP_REQUIRE_PS2_CANDIDATE') == '1': pytest.fail('required CMake is missing')
        pytest.skip('native module registry probe requires CMake and a C++20 compiler')
    (tmp_path / 'ps2_runtime.h').write_text('''#pragma once
#include <cstdint>
struct R5900Context { unsigned calls=0, value=0; bool throw_inside=false; };
class PS2Runtime { public: using RecompiledFunction=void(*)(uint8_t*, R5900Context*, PS2Runtime*); };
''')
    common = Path(__file__).parents[1] / 'src/decompnet/ps2_native/code_guard.hpp'
    modules = []
    for number, byte in ((1, 0x12), (2, 0x34), (3, 0x12)):
        folder = tmp_path / f'module{number}'; folder.mkdir()
        identity = hashlib.sha256(f'original-host-module-{number}'.encode()).hexdigest()
        namespace = 'decomp_ps2_module_' + identity
        function = namespace + '_entry'; header = namespace + '_functions.h'
        shutil.copyfile(common, folder / 'ps2_code_guard.hpp')
        (folder / (namespace + '.hpp')).write_text(f'''#pragma once
#include "ps2_code_guard.hpp"
namespace {namespace} {{
inline constexpr uint8_t expected[]={{{byte}}};
inline void check(const uint8_t *ram) {{ decomp_ps2::check_code(ram, 0x100000, expected, "{identity}"); }}
}}
''')
        (folder / header).write_text(f'''#pragma once
#include "ps2_runtime.h"
#include "ps2_code_guard.hpp"
inline void {function}(uint8_t*, R5900Context *ctx, PS2Runtime*) {{
    ctx->calls++; ctx->value={number};
    if(ctx->throw_inside) throw decomp_ps2::CodeMismatch("nested failure");
}}
''')
        modules.append(dict(path=str(folder), identity=identity, namespace=namespace,
            functions_header=header, entries=[dict(address=0x100000, function=function)]))
    registry(modules[:2], tmp_path / 'distinct.cpp')
    registry([modules[0], modules[2]], tmp_path / 'ambiguous.cpp')
    (tmp_path / 'main.cpp').write_text('''#include "ps2_runtime.h"
#include "module1/ps2_code_guard.hpp"
#include <vector>
#include <string>
extern PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[];
int main() {
    std::vector<uint8_t> ram(32*1024*1024); R5900Context ctx;
    ram[0x100000]=0x12;
#ifdef TEST_AMBIGUOUS
    try { g_ps2RecompiledFunctionTable[0](ram.data(), &ctx, nullptr); }
    catch(const std::runtime_error &error) {
        return ctx.calls==0 && std::string(error.what())=="ambiguous PS2 resident code identity" ? 0 : 1;
    }
    return 2;
#else
    g_ps2RecompiledFunctionTable[0](ram.data(), &ctx, nullptr);
    if(ctx.calls!=1 || ctx.value!=1) return 3;
    ram[0x100000]=0x34;
    g_ps2RecompiledFunctionTable[0](ram.data(), &ctx, nullptr);
    if(ctx.calls!=2 || ctx.value!=2) return 4;
    ram[0x100000]=0x77; bool rejected=false;
    try { g_ps2RecompiledFunctionTable[0](ram.data(), &ctx, nullptr); }
    catch(const decomp_ps2::CodeMismatch &) { rejected=true; }
    if(!rejected || ctx.calls!=2) return 5;
    ram[0x100000]=0x34; ctx.throw_inside=true; rejected=false;
    try { g_ps2RecompiledFunctionTable[0](ram.data(), &ctx, nullptr); }
    catch(const decomp_ps2::CodeMismatch &error) {
        rejected=std::string(error.what()).find("nested failure")!=std::string::npos;
    }
    return rejected && ctx.calls==3 && ctx.value==2 ? 0 : 6;
#endif
}
''')
    (tmp_path / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(OriginalRegistry LANGUAGES CXX)
add_executable(distinct_probe main.cpp distinct.cpp)
add_executable(ambiguous_probe main.cpp ambiguous.cpp)
target_compile_definitions(ambiguous_probe PRIVATE TEST_AMBIGUOUS=1)
foreach(target distinct_probe ambiguous_probe)
  target_compile_features(${target} PRIVATE cxx_std_20)
  target_include_directories(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
endforeach()
''')
    build = tmp_path / 'build'
    for name, command in (('configure', ['cmake', '-S', tmp_path, '-B', build]),
                          ('build', ['cmake', '--build', build, '--config', 'Release', '--parallel', '2'])):
        result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        (tmp_path / (name + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    for name in ('distinct_probe', 'ambiguous_probe'):
        result = subprocess.run([executable(build, name)], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
