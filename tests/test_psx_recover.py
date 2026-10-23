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
from decompnet.seeds import _mips_parameter_slots
from .test_psx_set import fixtures
from .test_overlays import _iso, _resident_exe


def test_integer_leaf_candidates_refuse_side_effects_calls_and_unknown_inputs():
    pack = lambda *words: struct.pack(f"<{len(words)}I", *words)
    assert "a0 + 7" in leaf_candidates(pack(0x03E00008, 0x24820007), "leaf")[0]
    assert leaf_candidates(pack(0x03E00008, 0), "empty") == ["void empty(void) {}"]
    assert not leaf_candidates(pack(0x0C000000, 0, 0x03E00008, 0), "calls")
    assert not leaf_candidates(pack(0x03E00008, 0xAC820000), "stores")
    assert not leaf_candidates(pack(0x03E00008, 0x25020001), "uninitialized_t0")


def test_m2c_argument_repair_leaves_wide_and_reviewed_signatures_unchanged():
    for params in ("double arg0, int arg2", "s64 arg0, int arg2", "int *p, int value", "int arg2, int arg0"):
        source = f"int leaf({params}) {{ return 0; }}"
        assert _mips_parameter_slots(source, "leaf") == source
    source = "int leaf(int arg2) { return arg2; }"
    assert _mips_parameter_slots(source, "leaf", "int leaf(int arg2);") == source


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


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("body", [
    "int memory_leaf(int unused0, int unused1, int *p) { int value = 0; if (p) value = p[2]; return value; }",
    "int memory_leaf(int *p, int unused, int value) { if (p) value += p[2]; return value; }",
], ids=["unused-leading-arguments", "unused-middle-argument"])
def test_console_machine_drafts_keep_original_argument_registers(tmp_path, capsys, toolchain, body):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none"}})
    compiled = compiler.compile_source(cfg, "", body)
    assert compiled.ok, compiled.log
    function = elfobj.extract_function(compiled.obj, "memory_leaf")
    assert not function.relocs and not leaf_candidates(function.code, "memory_leaf")
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(function.code)] = function.code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    assert main(["--db", str(tmp_path / "app.db"), "psx", "recover", slug,
                 "--workspace", str(tmp_path / "projects"), "--max-insns", "20"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["m2c_available"] and fn["name"] in result["matched"]
    assert net.export_rom(slug, log=lambda *_: None)["identical"]


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_recovered_address_alias_survives_export_and_clean_disc_build(tmp_path, toolchain):
    import shutil
    import subprocess
    import sys
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none", "flags": ["-O2", "-G0"]}})
    compiled = compiler.compile_source(cfg, "", "extern volatile int original_data[1]; int global_leaf(void) { return original_data[0]; }")
    assert compiled.ok, compiled.log
    function = elfobj.extract_function(compiled.obj, "global_leaf")
    assert {r.type for r in function.relocs} == {5, 6}
    code = bytearray(function.code)
    for relocation in function.relocs:
        word = struct.unpack_from("<I", code, relocation.offset)[0]
        value = (0x80101000 + 0x8000) >> 16 if relocation.type == 5 else 0x1000
        struct.pack_into("<I", code, relocation.offset, word & 0xFFFF0000 | value & 0xFFFF)
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(code)] = code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    row = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", row["id"], 0x80010500)
    assert "B_80101000" not in fn["asm"]
    agent, _ = net.local_agent("alias-recovery")
    source = f"extern volatile int B_80101000[1]; int {fn['name']}(void) {{ return B_80101000[0]; }}"
    assert net.attempt(agent, fn["name"], source, slug)["matched"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    tree = Path(exported["path"])
    meta = json.loads((tree / "build.json").read_text())
    assert meta["symbols"]["B_80101000"] == 0x80101000
    for folder in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(tree / folder, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=120)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / meta["disc"]["output"]).read_bytes() == original


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


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
def test_profile_search_retains_saved_source_without_machine_drafts_or_leaf_templates(tmp_path):
    from decompnet.rom.psx_recover import _profile_search
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": "gcc-2.8.1-psx", "language": "c++", "sandbox": "none"}})
    body = "int original(int *p) { if (p) return p[2]; return 0; }"
    compiled = compiler.compile_source(cfg, "", body)
    assert compiled.ok, compiled.log
    target = elfobj.extract_function(compiled.obj, "original")
    assert not target.relocs and not leaf_candidates(target.code, "original")
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(target.code)] = target.code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, flags=["-O0", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    agent, _ = net.local_agent("saved-source-profile-test")
    source = body.replace("original(", fn["name"] + "(")
    assert not net.try_quietly(agent, proj, fn, source)["matched"]
    fn = net.store.one("SELECT * FROM functions WHERE id=?", fn["id"])
    assert fn["best_source"] == source
    selected = _profile_search(net, slug, agent, fn, machine_drafts=False)
    assert selected and "-O0" not in selected["flags"]
    saved = net._function(fn["name"], slug)
    assert saved["status"] == "matched" and saved["matched_source"] == source
    assert net.export_rom(slug, log=lambda *_: None)["identical"]
