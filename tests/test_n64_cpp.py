"""Real period C++ compilation; required on the native Windows and Linux CI jobs."""
from io import BytesIO
import json
import os
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import compiler, elfobj, project, toolchains
from .fixtures.generate_native_compiler_parity import describe_functions

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_N64_CPP") != "1", reason="requires the pinned N64 C++ toolchain")
FIXTURES = Path(__file__).parent / "fixtures"


def config(tmp_path, language="c++"):
    assert toolchains.installed("gcc-2.7.2-kmc") is not None
    return project.compiler_config(tmp_path, {"kind": "rom", "platform": "n64", "compiler": {
        "toolchain": "gcc-2.7.2-kmc", "language": language, "sandbox": "none"}})


def test_real_cpp_templates_classes_and_references_preserve_game_symbol(tmp_path):
    source = '''#ifndef __cplusplus
#error This translation unit must be compiled as C++
#endif
template<class T> class Counter { public: T value; };
int cpp_game_probe(int value) {
    Counter<int> counter;
    int &reference = counter.value;
    reference = value * 3;
    return counter.value;
}
'''
    result = compiler.compile_source(config(tmp_path), "", source)
    assert result.ok, result.log
    actual = elfobj.extract_function(result.obj, "cpp_game_probe")
    assert actual.arch == "mips" and actual.big_endian
    assert actual.code and not actual.relocs  # template members and references need no C++ runtime calls
    assert ELFFile(BytesIO(result.obj))["e_machine"] == "EM_MIPS"


def test_cpp_frontend_matches_the_pinned_cpp_code_and_relocation_reference(tmp_path):
    source = (FIXTURES / "native_compiler_parity.c").read_text(encoding="utf-8")
    expected = json.loads((FIXTURES / "native_cpp_compiler_parity.json").read_text(encoding="utf-8"))
    result = compiler.compile_source(config(tmp_path), "", source)
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]
