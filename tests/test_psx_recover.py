"""Console recovery saves genuine matching C/C++ and respects other work."""

import json
import os
from pathlib import Path
import struct

import pytest

from decompnet import compiler, elfobj, project
from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.rom.psx_recover import leaf_candidates
from .test_psx_set import fixtures
from .test_overlays import _iso, _resident_exe


def test_integer_leaf_candidates_refuse_side_effects_calls_and_unknown_inputs():
    pack = lambda *words: struct.pack(f"<{len(words)}I", *words)
    assert "a0 + 7" in leaf_candidates(pack(0x03E00008, 0x24820007), "leaf")[0]
    assert leaf_candidates(pack(0x03E00008, 0), "empty") == ["void empty(void) {}"]
    assert not leaf_candidates(pack(0x0C000000, 0, 0x03E00008, 0), "calls")
    assert not leaf_candidates(pack(0x03E00008, 0xAC820000), "stores")
    assert not leaf_candidates(pack(0x03E00008, 0x25020001), "uninitialized_t0")


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_console_recovery_judges_real_cpp_and_exports_exact_disc(tmp_path, capsys, toolchain):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    original = fixtures(tmp_path, toolchain)[0]
    slug = net.import_rom(original, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda cfg: cfg["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    function = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    other, _ = net.local_agent("another-local-user")
    net.claim_row(other, slug, function["name"])
    args = ["--db", str(tmp_path / "app.db"), "psx", "recover", slug, "--workspace", str(tmp_path / "projects"), "--leaves-only", "--max-insns", "8"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["claimed"] == 1 and function["name"] not in report["matched"]
    net.release(other, function["name"], "ready for console recovery", slug)
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert function["name"] in report["matched"]
    saved = net._function(function["name"], slug)
    assert "return" in saved["matched_source"] and "asm" not in saved["matched_source"]
    assert main(args) == 0
    assert function["name"] not in json.loads(capsys.readouterr().out)["matched"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"], exported
    tree = Path(exported["path"])
    meta = json.loads((tree / "build.json").read_text())
    assert (tree / meta["disc"]["output"]).read_bytes() == original


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools and m2c")
def test_console_machine_drafts_recover_a_branching_memory_function_beyond_templates(tmp_path, capsys):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.7.2-psx", "language": "c", "sandbox": "none"}})
    obj = compiler.compile_source(cfg, "", "int memory_leaf(int *p) { int value = 0; if (p) value = p[2]; return value; }")
    assert obj.ok, obj.log
    function = elfobj.extract_function(obj.obj, "memory_leaf")
    assert not function.relocs
    assert function and not leaf_candidates(function.code, "memory_leaf")
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(function.code)] = function.code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    assert main(["--db", str(tmp_path / "app.db"), "psx", "recover", slug, "--workspace", str(tmp_path / "projects"), "--max-insns", "12"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["m2c_available"] and fn["name"] in result["matched"]


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("body", ["void memory_leaf(int p, int v) { *(int *)(p + 4) = v; }",
    "int memory_leaf(int p) { return *(signed char *)(p + 3); }",
    "int memory_leaf(int p, int v) { int old = *(int *)p; *(int *)p = v; return old; }"],
    ids=["store", "signed-load", "load-before-store"])
def test_console_memory_templates_preserve_side_effects_and_load_order(tmp_path, capsys, toolchain, body):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none"}})
    obj = compiler.compile_source(cfg, "", body)
    assert obj.ok, obj.log
    code = elfobj.extract_function(obj.obj, "memory_leaf").code
    assert leaf_candidates(code, "memory_leaf")
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    assert main(["--db", str(tmp_path / "app.db"), "psx", "recover", slug, "--workspace", str(tmp_path / "projects"), "--leaves-only", "--max-insns", "12"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert fn["name"] in result["matched"]
    assert net.export_rom(slug, log=lambda *_: None)["identical"]


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools and m2c")
def test_profile_search_commits_only_a_verified_function_profile_and_export_rebuilds(tmp_path, capsys):
    from decompnet import toolchains
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.8.1-psx", "language": "c++", "sandbox": "none"}})
    compiled = compiler.compile_source(cfg, "", 'extern "C" int memory_leaf(int *p) { return p[2]; }')
    assert compiled.ok, compiled.log
    code = elfobj.extract_function(compiled.obj, "memory_leaf").code
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    flags = ["-O0", *[f for f in toolchains.get("gcc-2.7.2-psx").flags if not f.startswith("-O")]]
    slug = net.import_rom(original, flags=flags, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    args = ["--db", str(tmp_path / "app.db"), "psx", "recover", slug, "--workspace", str(tmp_path / "projects"), "--limit", "1", "--max-insns", "6"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert fn["name"] not in first["matched"]
    assert not net.cfg(net.project_row(slug)).get("function_compilers")
    assert main([*args, "--search-profiles"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert fn["name"] in second["matched"]
    selected = net.cfg(net.project_row(slug))["function_compilers"][fn["name"]]
    assert selected == second["profile_matches"][fn["name"]]
    assert "-O0" not in selected["flags"]
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"], result
