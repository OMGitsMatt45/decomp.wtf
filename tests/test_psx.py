"""PlayStation ROM projects: split a homemade PS-X EXE and prove the matcher on it.

Demo Quest PS1 (projects/demo-psx) is the Demo Quest game built for the PlayStation with GCC 2.7.2 at -O2 -G8,
little-endian, small globals $gp-relative, like PSY-Q-era games. The executable carries no symbols, so the test
does what an agent does: give addresses names, declare the game's types, then write each function. Every one of
them must match byte for byte.
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

from decompnet import toolchains, wsl
from decompnet.app.engine import RomNetwork
from decompnet.forks import csource

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "projects" / "demo-psx"
EXE = DEMO / "build" / "DEMOQ_PS1.EXE"
ELF = DEMO / "build" / "demoq_ps1.elf"
GAME = ROOT / "projects" / "demo-n64" / "original"
GIT = shutil.which("git")
FUNCTIONS = ["clamp_s32", "abs_s32", "player_take_damage", "rng_next", "count_alive_entities", "entity_update_physics",
             "entity_default_hp", "entity_spawn", "add_score", "lerp", "checksum_save", "entity_collides", "game_tick"]

REQUIRED = os.environ.get("DECOMP_TEST_PSX_CPP") == "1"
pytestmark = pytest.mark.skipif(not REQUIRED and any(toolchains.installed(t) is None for t in
    ("gcc-2.7.2-psx", "gcc-2.8.1-psx", "binutils-mips")), reason="needs the pinned PS1 compilers and MIPS binutils")


@pytest.fixture(autouse=True)
def native_execution(monkeypatch):
    monkeypatch.setenv("DECOMP_RUNTIME", "native")
    if sys.platform == "win32":
        monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32"))

    def no_wsl(*args, **kwargs):
        pytest.fail("PS1 matching and exports must run without WSL")

    monkeypatch.setattr(wsl, "status", no_wsl)
    monkeypatch.setattr(wsl, "run", no_wsl)
    start = subprocess.Popen

    def native_process(args, *positional, **kwargs):
        assert Path(str(args[0])).name.lower() not in ("wsl", "wsl.exe", "sh", "sh.exe", "bash", "bash.exe")
        return start(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", native_process)


@pytest.fixture(scope="module", params=[(tc, language) for tc in ("gcc-2.7.2-psx", "gcc-2.8.1-psx") for language in ("c", "c++")])
def psx(tmp_path_factory, request):
    tc, language = request.param
    assert all(toolchains.installed(t) is not None for t in (tc, "binutils-mips"))
    work = tmp_path_factory.mktemp("PS1 project with spaces")
    original = work / "original"
    subprocess.run([sys.executable, str(DEMO / "build.py"), "--toolchain", tc, "--output", str(original)], check=True)
    elf, image = original / "demoq_ps1.elf", original / "DEMOQ_PS1.EXE"
    net = RomNetwork(work / "app.db", work)
    slug = net.import_rom(image.read_bytes(), toolchain=tc, confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    assert net.overview(slug)["compiler"]["language"] == "c++"
    cfg = net.cfg(proj)
    cfg["compiler"].update(language=language, sandbox="none")
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    return net, slug, elf, image


def test_import(psx):
    net, slug, elf, image = psx
    ov = net.overview(slug)
    assert ov["platform"] == "psx" and ov["compiler"]["toolchain"] in ("gcc-2.7.2-psx", "gcc-2.8.1-psx") and ov["functions"] > 60
    assert "WITHOUT" in net.get_context(slug)  # the gp-relative globals advice


def test_every_game_function_matches(psx):
    net, slug, elf, image = psx
    agent, _ = net.local_agent("psx-agent")
    syms = {s.name: s["st_value"] for s in ELFFile(open(elf, "rb")).get_section_by_name(".symtab").iter_symbols()}
    header = (GAME / "game.h").read_text()
    header = "\n".join(l for l in header.splitlines()
                       if not l.startswith("#include") and not re.match(r"typedef \w+( \w+)? [su]\d+;|typedef \w+ f\d+;", l))
    header = re.sub(r"^extern (s32|u32) (g_\w+);", r"\1 \2;", header, flags=re.M)  # small globals: no extern
    if net.overview(slug)["compiler"]["language"] == "c++":
        header = header.replace("#define NULL ((void *)0)", "#define NULL 0")
    assert net.edit_context(agent, slug, "", header, "the game's types").startswith("✅")
    table = net.symbols(net.project_row(slug)["id"])
    for name in FUNCTIONS + ["g_player", "g_entities", "g_score", "g_frame_count", "g_rng_state",
                             "__subsf3", "__mulsf3", "__addsf3", "__divsf3", "__ltsf2", "__gtsf2", "__fixsfsi", "__floatsisf"]:
        if name in syms:
            current, offset = table.name_at(syms[name])
            if offset:  # inside a bigger data symbol (adjacent globals): name the address itself
                current = f"D_{syms[name]:08X}"
            if current != name:
                net.rename_symbol(agent, slug, current, name)
                table = net.symbols(net.project_row(slug)["id"])
    source = (GAME / "game.c").read_text()
    pid = net.project_row(slug)["id"]
    context = net._context(pid)
    with net.store.tx() as db:
        db.execute("UPDATE functions SET unit='spawn' WHERE project_id=? AND name='entity_spawn'", (pid,))
        db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                   "VALUES(?,?,?,?,?,?,?)", (pid, net._next_version(db, pid), context["header"] + "\n#define PS1_NO_ENTITY 0\n",
                                            agent.id, "unit-only null constant", context["created_at"], "spawn"))
    scores = {}
    for name in FUNCTIONS:
        code = csource.get(source, name)
        if net.overview(slug)["compiler"]["language"] == "c++":
            if name == "abs_s32":
                code = """template<class T> struct PS1Traits { enum { zero = 0 }; };
s32 abs_s32(s32 value) { if (value < PS1Traits<s32>::zero) value = -value; return value; }
"""
            if name in ("entity_spawn", "game_tick"):
                code = code.replace("s32 i;", "s32 i; Entity *e;").replace("Entity *e = &g_entities[i];", "e = &g_entities[i];")
        if name == "entity_spawn":
            code = code.replace("return NULL;", "return PS1_NO_ENTITY;")
        result = net.attempt(agent, name, code, slug)
        scores[name] = result
        if not result["matched"]:
            net.release(agent, name, "", slug)
    assert all(r["matched"] for r in scores.values()), {n: r for n, r in scores.items() if not r["matched"]}


def test_wrong_code_does_not_match(psx):
    net, slug, elf, image = psx
    agent, _ = net.local_agent("psx-agent-2")
    fn = net.store.one("SELECT name FROM functions WHERE status='open' AND n_insns > 8 ORDER BY n_insns LIMIT 1")
    res = net.attempt(agent, fn["name"], f"int {fn['name']}(int a) {{ return a * 3; }}", slug)
    assert not res["matched"]
    net.release(agent, fn["name"], "", slug)


def test_export_rebuilds_from_clean_sources_and_rejects_changed_code(psx):
    net, slug, elf, image = psx
    language = net.overview(slug)["compiler"]["language"]
    extension = "cpp" if language == "c++" else "c"
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["identical"] and out["matched"] == len(FUNCTIONS) and not out["fallback"], out["log"]
    tree = Path(out["path"])
    assert len(list((tree / "src").rglob(f"*.{extension}"))) == len(FUNCTIONS)
    spawn = next((tree / "src").rglob(f"entity_spawn.{extension}"))
    assert '#include "common_spawn.h"' in spawn.read_text()
    assert "PS1_NO_ENTITY" in (tree / "include/common_spawn.h").read_text()
    build = json.loads((tree / "build.json").read_text())
    assert build["compiler"]["language"] == language
    if language == "c":
        build["compiler"].pop("language")  # exports made before C++ became the default
        (tree / "build.json").write_text(json.dumps(build))
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated, ignore_errors=True)
    assert GIT
    subprocess.run([GIT, "init", "-q"], cwd=tree, check=True)
    subprocess.run([GIT, "-c", "core.autocrlf=true", "add", "-A"], cwd=tree, check=True, capture_output=True)
    sources = [*(tree / "src").rglob(f"*.{extension}"), *(tree / "include").rglob("*.h")]
    for source in sources:
        source.unlink()
    subprocess.run([GIT, "-c", "core.autocrlf=true", "checkout-index", "-a", "-f"], cwd=tree, check=True)
    assert all(b"\r" not in source.read_bytes() for source in sources)

    def run(*args):
        return subprocess.run([sys.executable, "build.py", *args], cwd=tree, capture_output=True, text=True)

    result = run()
    assert result.returncode == 0 and "identical" in result.stdout, result.stdout + result.stderr
    assert (tree / build["output"]).read_bytes() == image.read_bytes()
    source = next((tree / "src").rglob(f"clamp_s32.{extension}"))
    original = source.read_text()
    source.write_text('#include "common.h"\ns32 clamp_s32(s32 v, s32 lo, s32 hi) { return v + 3; }\n')
    assert run("check", "clamp_s32").returncode != 0
    assert run().returncode != 0
    source.write_text(original)
    assert run("check", "clamp_s32").returncode == 0
    assert run().returncode == 0
