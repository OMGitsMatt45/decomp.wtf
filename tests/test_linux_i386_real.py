"""Reference parity through explicit QEMU inside the Docker compiler sandbox."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from decompnet import compiler, project, toolchains
from .fixtures.generate_native_compiler_parity import describe_functions

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_LINUX_I386") != "1",
                                reason="requires Linux, Docker and explicit qemu-i386")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("tc,platform,language,source,reference", [
    ("gcc-2.7.2-kmc", "n64", "c", "native_compiler_parity.c", "native_compiler_parity.json"),
    ("gcc-2.7.2-kmc", "n64", "c++", "native_compiler_parity.c", "native_cpp_compiler_parity.json"),
    ("gcc-2.7.2-psx", "psx", "c++", "psx_cpp_features.cpp", "psx272_cpp_parity.json"),
    ("gcc-2.8.1-psx", "psx", "c++", "psx_cpp_features.cpp", "psx281_cpp_parity.json"),
    ("ee-gcc-2.96", "ps2", "c++", "ps2_cpp_features.cpp", "ps2_cpp_parity.json"),
])
def test_pinned_compilers_match_references_and_reject_invalid_source(tmp_path, tc, platform, language, source, reference):
    expected = json.loads((FIXTURES / reference).read_text())
    settings = {"toolchain": tc, "language": language, "sandbox": "docker"}
    if "flags" in expected:
        settings["flags"] = expected["flags"]
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": platform, "compiler": settings})
    assert cfg.qemu_i386 and cfg.image and not cfg.wsl
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in toolchains.path(tc).rglob("*") if p.is_file()}
    result = compiler.compile_source(cfg, "", (FIXTURES / source).read_text())
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]
    rejected = compiler.compile_source(cfg, "", "int broken() { return missing_identifier; }")
    assert not rejected.ok and rejected.obj is None
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original} == original
