"""Exported projects rebuild the game byte for byte: the base for ports and mods.

For each homemade PlayStation or PlayStation 2 fixture, match the game's functions the way an agent would,
export the project, build it, then build it again from a clean tree (as from a fresh clone: only the sources and
your own copy of the game), and check that nothing made from the game would be committed.
"""

import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.forks import csource

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "projects" / "shared-game" / "original"
FUNCTIONS = ["clamp_s32", "abs_s32", "player_take_damage", "rng_next", "count_alive_entities", "entity_update_physics",
             "entity_default_hp", "entity_spawn", "add_score", "lerp", "checksum_save", "entity_collides", "game_tick"]
DEMOS = {
    "psx": (ROOT / "projects/demo-psx/build/DEMOQ_PS1.EXE", ROOT / "projects/demo-psx/build/demoq_ps1.elf",
            "gcc-2.7.2-psx", ROOT / "projects/demo-psx/build.py"),
    "ps2": (ROOT / "projects/demo-ps2/build/SLUS_999.99", ROOT / "projects/demo-ps2/build/demoq_ps2.elf",
            "ee-gcc-2.96", ROOT / "projects/demo-ps2/build.py"),
}


def _ready(platform: str) -> bool:
    _, _, tc, _ = DEMOS[platform]
    return (toolchains.installed(tc) is not None and toolchains.installed("binutils-mips") is not None
            and (platform in ("psx", "ps2") or shutil.which("ld.lld") is not None))


def _decompile(tmp: Path, platform: str):
    game, elf, _, build = DEMOS[platform]
    if not elf.exists() or not game.exists():
        subprocess.run([sys.executable, str(build)], check=True)
    net = RomNetwork(tmp / "app.db", tmp)
    slug = net.import_rom(game, confirmed=True, log=lambda *_: None)
    if platform in ("psx", "ps2"):  # legacy C exports remain rebuildable after the default changes
        proj = net.project_row(slug)
        cfg = net.cfg(proj)
        cfg["compiler"].update(language="c", sandbox="none")
        with net.store.tx() as db:
            db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    agent, _ = net.local_agent("agent")
    syms = {s.name: s["st_value"] for s in ELFFile(open(elf, "rb")).get_section_by_name(".symtab").iter_symbols()}
    pid = net.project_row(slug)["id"]
    for name in FUNCTIONS:  # functions the splitter merged into the one before (after one that never returns)
        row = net.store.one("SELECT name, vram FROM functions WHERE project_id=? AND vram<=? AND vram+size>?",
                            pid, syms[name], syms[name])
        if row and row["vram"] != syms[name]:
            net.split_function(agent, slug, row["name"], f"0x{syms[name]:08X}", name)
    header = "\n".join(l for l in (GAME / "game.h").read_text().splitlines()
                       if not l.startswith("#include") and not re.match(r"typedef \w+( \w+)? [su]\d+;|typedef \w+ f\d+;", l))
    # Small globals are $gp-relative: tentative definitions, not extern.
    header = re.sub(r"^extern (s32|u32) (g_\w+);", r"\1 \2;", header, flags=re.M)
    assert net.edit_context(agent, slug, "", header, "the game's types").startswith("✅")
    table = net.symbols(pid)
    for name in FUNCTIONS + ["g_player", "g_entities", "g_score", "g_frame_count", "g_rng_state",
                             "__subsf3", "__mulsf3", "__addsf3", "__muldi3"]:
        if name in syms:
            current, offset = table.name_at(syms[name])
            if offset:
                current = f"D_{syms[name]:08X}"
            if current != name:
                net.rename_symbol(agent, slug, current, name)
                table = net.symbols(pid)
    source = (GAME / "game.c").read_text()
    for name in FUNCTIONS:
        code = csource.get(source, name)
        result = net.attempt(agent, name, code, slug)
        assert result["matched"], (name, result)
    return net, slug


@pytest.mark.parametrize("platform", ["psx", "ps2"])
def test_export_rebuilds_the_game(tmp_path, platform):
    if not _ready(platform):
        pytest.skip(f"needs the {platform} toolchain and binutils-mips")
    net, slug = _decompile(tmp_path, platform)
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["identical"], out["log"]
    assert out["matched"] == len(FUNCTIONS) and not out["fallback"]
    tree = Path(out["path"])
    extension = "c"
    assert len(list((tree / "src").glob(f"*/*.{extension}"))) == len(FUNCTIONS)

    # a fresh clone: no assembly, assets or build output, only the sources and your copy of the game
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    res = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
    assert "identical" in res.stdout, res.stdout + res.stderr

    # nothing made from the game would be committed
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=tree, check=True)
        subprocess.run(["git", "add", "-A"], cwd=tree, check=True)
        files = subprocess.run(["git", "ls-files", "--cached"], cwd=tree, capture_output=True, text=True).stdout.split()
        assert not [f for f in files if f.startswith(("asm/", "assets/", "build/", "baserom"))], files
        assert "build.py" in files and "build.json" in files


def test_check_records_a_function_written_outside(tmp_path):
    if not _ready("psx"):
        pytest.skip("needs the PS1 toolchain and binutils-mips")
    net, slug = _decompile(tmp_path, "psx")
    tree = Path(net.export_rom(slug, log=lambda *_: None)["path"])
    py = lambda *a: subprocess.run([sys.executable, "build.py", *a], cwd=tree, capture_output=True, text=True)
    (tree / "src" / "main" / "lerp.c").unlink()  # back to assembly
    assert "identical" in py().stdout
    (tree / "src" / "main" / "lerp.c").write_text('#include "common.h"\n\nf32 lerp(f32 a, f32 b, f32 t) {\n    return a;\n}\n')
    failed = py()
    assert failed.returncode != 0 and "not identical" in failed.stdout + failed.stderr
    assert py("check", "lerp").returncode == 1
    (tree / "src" / "main" / "lerp.c").write_text('#include "common.h"\n\n' + csource.get((GAME / "game.c").read_text(), "lerp"))
    assert py("check", "lerp").returncode == 0
    assert "identical" in py().stdout


@pytest.mark.parametrize("title", [b"\0" * 20, b"  ORIGINAL PS1".ljust(20, b" ")])
def test_assembly_export_preserves_raw_title_without_a_compiler(tmp_path, monkeypatch, title):
    if toolchains.installed("binutils-mips") is None:
        pytest.skip("needs binutils-mips")
    binutils = toolchains.path("binutils-mips")
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copytree(binutils, tools / "binutils-mips")
    monkeypatch.setenv("DECOMPNET_TOOLCHAINS", str(tools))
    assert toolchains.installed("gcc-2.7.2-psx") is None

    from .test_overlays import _resident_exe
    rom = bytearray(_resident_exe())
    assert len(title) == 20
    rom[0x4C:0x60] = title
    workspace = tmp_path / "app"
    workspace.mkdir()
    net = RomNetwork(workspace / "app.db", workspace)
    slug = net.import_rom(bytes(rom), confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["matched"] == 0, result["log"]
    tree = Path(result["path"])
    assert (tree / "build/game.exe").read_bytes() == rom

    # A fresh checkout must regenerate the same header and assembly.
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / "build/game.exe").read_bytes() == rom


def test_assembly_export_links_branches_into_other_functions(tmp_path, monkeypatch):
    if toolchains.installed("binutils-mips") is None:
        pytest.skip("needs binutils-mips")
    binutils = toolchains.path("binutils-mips")
    tools = tmp_path / "tools"
    shutil.copytree(binutils, tools / "binutils-mips")
    monkeypatch.setenv("DECOMPNET_TOOLCHAINS", str(tools))
    assert toolchains.installed("gcc-2.7.2-psx") is None

    # Two called functions share a tail: the second branches into the first
    # at +4. The disassembler names that interior target .L80010044.
    base = 0x80010000
    code = bytearray(0x800)
    def words(offset, values):
        struct.pack_into("<" + "I" * len(values), code, offset, *values)
    words(0, [0x27BDFFF0, 0xAFBF000C, 0x0C004010, 0, 0x0C004018, 0,
              0x8FBF000C, 0x27BD0010, 0x03E00008, 0])
    words(0x40, [0x24020001, 0x24420001, 0x03E00008, 0])
    words(0x60, [0x0401FFF8, 0])
    # Enough varied instructions for splat's text-section detector.
    words(0x80, [0x24420001, 0x00441026] * 20 + [0x03E00008, 0])
    header = bytearray(0x800)
    header[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", header, 0x10, base, 0, base, len(code))
    original = bytes(header + code)
    workspace = tmp_path / "app"
    workspace.mkdir()
    net = RomNetwork(workspace / "app.db", workspace)
    slug = net.import_rom(original, confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["functions"] >= 3
    assert result["identical"] and result["matched"] == 0, result["log"]
    tree = Path(result["path"])
    assert json.loads((tree / "build.json").read_text())["symbols"][".L80010044"] == base + 0x44
    assert (tree / "build/game.exe").read_bytes() == original

    # Regenerate assembly without relying on symbols from the first build.
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / "build/game.exe").read_bytes() == original
