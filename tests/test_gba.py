"""Game Boy Advance from scratch: a homemade ROM built like GBA games (agbcc, pret-style), split by luvdis plus
decomp.wtf's pass for code nothing calls, and judged byte for byte by the ARM/Thumb matcher.

Demo Quest GBA (projects/demo-gba) is stripped of symbols in the ROM, so the test does what an agent does: split
off a function the finder merged, add one it didn't find, name things, write the C. Every function must match.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.forks import csource

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "projects" / "demo-gba"
ROM, ELF = DEMO / "build" / "demoquest.gba", DEMO / "build" / "demoq_gba.elf"
GAME = ROOT / "projects" / "demo-n64" / "original"
FUNCTIONS = ["abs_s32", "player_take_damage", "count_alive_entities", "entity_update_physics", "entity_default_hp",
             "entity_spawn", "add_score", "checksum_save", "entity_collides", "game_tick", "clamp_s32", "lerp", "rng_next"]

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_GBA_CPP") != "1" and
                                any(toolchains.installed(t) is None for t in ("agbcc", "arm-gnu", "luvdis")),
                                reason="needs agbcc, the Arm GNU toolchain and luvdis")


@pytest.fixture(scope="module", params=["c", "c++"])
def gba(tmp_path_factory, request):
    assert all(toolchains.installed(t) is not None for t in ("agbcc", "arm-gnu", "luvdis"))
    if not ROM.exists():
        subprocess.run([sys.executable, str(DEMO / "build.py")], check=True)
    work = tmp_path_factory.mktemp("gba")
    net = RomNetwork(work / "app.db", work)
    slug = net.import_rom(ROM, confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    assert net.overview(slug)["compiler"]["language"] == "c++"
    cfg = net.cfg(proj)
    cfg["compiler"].update(language=request.param, sandbox="none")
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    return net, slug


def test_import_finds_the_functions(gba):
    net, slug = gba
    ov = net.overview(slug)
    assert ov["platform"] == "gba" and ov["compiler"]["toolchain"] == "agbcc"
    real = {s["st_value"] & ~1 for s in ELFFile(open(ELF, "rb")).get_section_by_name(".symtab").iter_symbols()
            if s["st_info"]["type"] == "STT_FUNC"}
    found = {r["vram"] for r in net.store.all("SELECT vram FROM functions")}
    assert len(found & real) >= 110 and not found - real  # most functions, and no false starts


def test_every_game_function_matches(gba):
    net, slug = gba
    agent, _ = net.local_agent("gba-agent")
    syms = {s.name: s["st_value"] & ~1 for s in ELFFile(open(ELF, "rb")).get_section_by_name(".symtab").iter_symbols() if s.name}
    header = "\n".join(l for l in (GAME / "game.h").read_text().splitlines()
                       if not l.startswith("#include") and not re.match(r"typedef \w+( \w+)? [su]\d+;|typedef \w+ f\d+;", l))
    # Keep one RAM global unnamed: the judge accepts address names and the
    # exported C/C++ must link them without a rename_symbol workaround.
    score_name = f"D_{syms['g_score']:08X}"
    header = header.replace("g_score", score_name)
    if net.overview(slug)["compiler"]["language"] == "c++":
        header = header.replace("#define NULL ((void *)0)", "#define NULL 0")
    assert net.edit_context(agent, slug, "", header, "the game's types").startswith("✅")
    pid = net.project_row(slug)["id"]
    for name in FUNCTIONS:  # merged into the function before, or never found: split it off / add it
        row = net.store.one("SELECT name, vram FROM functions WHERE project_id=? AND vram<=? ORDER BY vram DESC LIMIT 1",
                            pid, syms[name])
        if row["vram"] != syms[name]:
            assert net.split_function(agent, slug, row["name"], f"0x{syms[name]:08X}", name).startswith("✅")
    table = net.symbols(pid)
    for name in FUNCTIONS + ["g_player", "g_entities", "g_frame_count", "g_rng_state", "__mulsf3", "__addsf3",
                             "__subsf3", "__divsi3", "__modsi3", "__floatsisf", "__fixsfsi", "__ltsf2", "__gtsf2"]:
        if name in syms:
            current, offset = table.name_at(syms[name])
            if offset:
                current = f"D_{syms[name]:08X}"
            if current != name:
                net.rename_symbol(agent, slug, current, name)
                table = net.symbols(pid)
    source = (GAME / "game.c").read_text().replace("g_score", score_name)
    context = net._context(pid)
    with net.store.tx() as db:
        db.execute("UPDATE functions SET unit='spawn' WHERE project_id=? AND name='entity_spawn'", (pid,))
        db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                   "VALUES(?,?,?,?,?,?,?)", (pid, net._next_version(db, pid), context["header"] + "\n#define GBA_NO_ENTITY 0\n",
                                            agent.id, "unit-only null constant", context["created_at"], "spawn"))
    scores = {}
    for name in FUNCTIONS:
        candidate = csource.get(source, name)
        if name == "abs_s32" and net.overview(slug)["compiler"]["language"] == "c++":
            candidate = """template<class T> class Magnitude {
public: T value; Magnitude(T v) : value(v) {} T get() const { const T &v = value; return v < 0 ? -v : v; }
};
s32 abs_s32(s32 v) { return Magnitude<s32>(v).get(); }
"""
        if name == "entity_spawn" and net.overview(slug)["compiler"]["language"] == "c++":
            # C++ boolean negation lowers differently; this equivalent comparison
            # preserves the original C game's instructions and register allocation.
            candidate = candidate.replace("!(e->flags & ENTITY_FLAG_ACTIVE)", "(e->flags & ENTITY_FLAG_ACTIVE) == 0")
        if name == "entity_spawn":
            candidate = candidate.replace("return NULL;", "return GBA_NO_ENTITY;")
        result = net.attempt(agent, name, candidate, slug)
        scores[name] = result
        if result["score"] != 0:
            net.release(agent, name, "", slug)
    assert all(result["score"] == 0 for result in scores.values()), {n: r for n, r in scores.items() if r["score"] != 0}


def test_drafts_and_look_alikes(gba):
    net, slug = gba
    row = net.store.one("SELECT name FROM functions WHERE status='open' AND n_insns > 20 LIMIT 1")
    brief = net.get_function(row["name"], slug)
    assert "thumb_func_start" in brief or "push" in brief
    assert net.find_similar(slug, row["name"]).startswith(("Functions that look like", "No look-alikes"))


def test_export_rebuilds_the_rom(gba):
    """The exported tree (luvdis assembly + the matched C) rebuilds the ROM byte for byte, also from a fresh clone."""
    net, slug = gba
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["identical"], out["log"]
    assert out["matched"] == len(FUNCTIONS) and not out["fallback"]
    root = Path(out["path"])
    language = net.overview(slug)["compiler"]["language"]
    extension = "cpp" if language == "c++" else "c"
    source = (root / "src" / f"player_take_damage.{extension}").read_text()
    assert "g_player" in source
    assert out["language"] == language
    assert '#include "common_spawn.h"' in (root / "src" / f"entity_spawn.{extension}").read_text()
    assert "GBA_NO_ENTITY" in (root / "include/common_spawn.h").read_text()
    if language == "c++":
        assert 'extern "C" void player_take_damage' in source
        assert 'extern "C" Player g_player;' in (root / "include/common.h").read_text()
        assert not list((root / "src").glob("*.c"))
    linked = (root / "build" / "game.ld").read_text()  # a matched function links its C, not its assembly
    assert "build/src/game_tick.o(.text)" in linked and "build/asm/game_tick.o" not in linked
    assert (root / "asm" / "game_tick.s").exists()  # the assembly stays as the reference
    # a fresh copy: what git keeps (no build/, asm/ or ROM), plus your ROM
    fresh = root.parent / "fresh"
    shutil.copytree(root, fresh, ignore=shutil.ignore_patterns("build", "asm", "baserom*"))
    shutil.copyfile(root / "baserom.gba", fresh / "baserom.gba")
    res = subprocess.run([sys.executable, "build.py"], cwd=fresh, capture_output=True, text=True, timeout=900)
    assert res.returncode == 0 and "identical" in res.stdout, res.stdout + res.stderr
    assert "13 of" in subprocess.run([sys.executable, "build.py", "status"], cwd=fresh, capture_output=True,
                                     text=True).stdout
    assert subprocess.run([sys.executable, "build.py", "check", "lerp"], cwd=fresh, capture_output=True,
                          text=True).returncode == 0

    if language == "c++":
        subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "add", "."], cwd=fresh, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Export"], cwd=fresh, check=True)
        clone = root.parent / "fresh Windows checkout"
        subprocess.run(["git", "-c", "core.autocrlf=true", "clone", "-q", str(fresh), str(clone)], check=True)
        shutil.copyfile(ROM, clone / "baserom.gba")
        assert not (clone / "build").exists() and not (clone / "asm").exists()
        result = subprocess.run([sys.executable, "build.py"], cwd=clone, capture_output=True, text=True, timeout=900)
        assert result.returncode == 0 and "functions in C++" in result.stdout, result.stdout + result.stderr
        assert (clone / "build/game.gba").read_bytes() == ROM.read_bytes()
        # Full builds must reject changed code and changed relocation targets,
        # even when the relocation occupies otherwise identical instruction bytes.
        for filename, old, new in (("abs_s32.cpp", "return v < 0 ? -v : v;", "return v + 1;"),
                                   ("game_tick.cpp", "add_score(10)", "player_take_damage(10)")):
            path = clone / "src" / filename
            text = path.read_text()
            assert old in text
            path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            result = subprocess.run([sys.executable, "build.py"], cwd=clone, capture_output=True, text=True, timeout=900)
            assert result.returncode != 0 and "not identical" in result.stderr, result.stdout + result.stderr
            path.write_text(text, encoding="utf-8", newline="\n")
    else:
        # Pre-conversion manifests used `c` paths and had no language field.
        manifest = json.loads((fresh / "build.json").read_text())
        del manifest["compiler"]["language"]
        for fn in manifest["functions"]:
            if "source" in fn:
                fn["c"] = fn.pop("source")
        (fresh / "build.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run([sys.executable, "build.py"], cwd=fresh, capture_output=True, text=True, timeout=900)
        assert result.returncode == 0 and "functions in C)" in result.stdout, result.stdout + result.stderr


def test_luvdis_survives_code_that_pops_more_than_it_pushed(tmp_path):
    """luvdis's stack model indexed outside its list after pops past the start (Spyro: Attack of the Rhynocs ended
    with "IndexError: list assignment index out of range"): such code is disassembled now."""
    from decompnet.rom import gba

    rom = bytearray(ROM.read_bytes())
    at = gba.BASE + len(rom)
    rom += bytes.fromhex("ffbc ffbc ffbc 00b5 00bd 0000")  # pop {r0-r7} x3; push {lr}; pop {pc}
    (tmp_path / "rom.gba").write_bytes(rom)
    (tmp_path / "in.cfg").write_text(f"thumb_func 0x{at:X}\n")
    asm, found = gba._luvdis(tmp_path / "rom.gba", tmp_path, tmp_path / "in.cfg")
    assert at in found and "func_start" in asm


def test_a_helper_linked_twice_gets_two_names(tmp_path, monkeypatch):
    """Two copies of libgcc's _call_via_r3 (Spyro Orange) broke the import on the functions' unique names."""
    from decompnet.rom import gba

    thunk = bytes.fromhex("1847c046")  # bx r3; nop
    fns = [gba.GbaFunction(f"sub_{a:08X}", a, a - gba.BASE, thunk, f"\tthumb_func_start sub_{a:08X}\n", 2, True, [],
                           gba.call_via(thunk)) for a in (0x08000200, 0x08000300)]
    monkeypatch.setattr(gba, "split", lambda *a, **k: fns)
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    slug = net.import_rom(ROM, confirmed=True, log=lambda *_: None)
    names = [r["name"] for r in net.store.all("SELECT name FROM functions WHERE project_id=? ORDER BY vram",
                                              net.project_row(slug)["id"])]
    assert names == ["_call_via_r3", "_call_via_r3_08000300"]
