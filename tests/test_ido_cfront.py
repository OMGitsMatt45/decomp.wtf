"""Required native classic IDO 5.3 checks; run after building its optional overlay."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from decompnet import compiler, elfobj, project, toolchains
from .fixtures.generate_native_compiler_parity import describe_functions
from .test_ido_cpp import CPP_ADD, C_FUNCTIONS, HEADER, config, native_only
from . import test_ido_cpp as shared

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_IDO_CFRONT") != "1", reason="requires the optional classic IDO 5.3 overlay")
FIXTURES = Path(__file__).parent / "fixtures"


def classic(root):
    cfg = project.compiler_config(root, {"kind": "rom", "platform": "n64", "compiler": {
        "toolchain": "ido-5.3", "cpp_frontend": "cfront", "language": "c++", "sandbox": "none"}})
    assert not cfg.wsl and cfg.language == "c++"
    assert "ido_cfront.py" in cfg.cmd[2]
    assert not any(Path(arg).stem in ("NCC", "edgcpfe") for arg in cfg.cmd)
    return cfg


@pytest.mark.parametrize("source,reference", [
    ("native_compiler_parity.c", "ido53_cfront_compiler_parity.json"),
    ("ido_cpp_features.cpp", "ido53_cfront_features_parity.json"),
])
def test_classic_code_and_relocations_match_the_original_irix_frontend(tmp_path, source, reference):
    text = (FIXTURES / source).read_text(encoding="utf-8")
    expected = json.loads((FIXTURES / reference).read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode()).hexdigest() == expected["source_sha256"]
    assert toolchains.get("ido-5.3").flags == expected["flags"]
    result = compiler.compile_source(classic(tmp_path), "", text)
    assert result.ok, result.log
    assert describe_functions(result.obj) == expected["functions"]


def test_classic_template_class_and_reference_match_a_c_origin_function(tmp_path):
    cpp = compiler.compile_source(classic(tmp_path), HEADER, CPP_ADD)
    c = compiler.compile_source(config(tmp_path, "c", "ido-5.3"), HEADER, C_FUNCTIONS["ido_add"])
    assert cpp.ok, cpp.log
    assert c.ok, c.log
    actual, target = (elfobj.extract_function(r.obj, "ido_add") for r in (cpp, c))
    assert actual.code == target.code and actual.relocs == target.relocs == []


def test_classic_invalid_source_fails_without_an_object(tmp_path):
    result = compiler.compile_source(classic(tmp_path), "", "template<class T class Broken {;\n")
    assert not result.ok and result.obj is None and "error" in result.log.lower()


def test_classic_cpp_export_rebuilds_a_c_origin_rom_from_a_clean_tree(tmp_path):
    shared.test_cpp_export_rebuilds_a_c_origin_rom_from_a_clean_tree(tmp_path, "ido-5.3", frontend="cfront")


def test_classic_m2c_cpp_draft_matches_a_c_origin_function(tmp_path):
    shared.test_real_cpp_draft_compiles_and_matches_the_c_target(tmp_path, "ido-5.3", frontend="cfront")
