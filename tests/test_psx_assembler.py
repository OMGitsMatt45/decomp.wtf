"""Pinned original GCC + maspsx profiles, native builds and real MIPS execution."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet import compiler, elfobj, project, toolchains, wsl
from decompnet.app.engine import RomNetwork
from decompnet.psx_compiler import ASPSX_VERSIONS, assembler_profile, small_data_limit
from decompnet.rom import match
from decompnet.rom.psx_modules import profile
from decompnet.rom.symbols import Symbol, SymbolTable
from .test_overlays import _iso, _resident_exe


REAL = pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and maspsx")


def test_assembler_profile_is_portable_and_explicit_reset_preserves_gnu():
    selected = {"toolchain": "gcc-2.7.2-psx", "flags": ["-O2", "-G0"]}
    for version in ASPSX_VERSIONS:
        result = profile(selected, {"assembler": {"tool": "maspsx", "version": version}})
        assert result["assembler"] == {"tool": "maspsx", "version": version}
        assert profile(result, {})["assembler"] == result["assembler"]
        assert profile(result, {"assembler": None})["assembler"] is None
    assert "assembler" not in profile(selected, {})
    for value in ("maspsx", {}, {"tool": "maspsx", "version": "2.79"},
                  {"tool": "other", "version": "2.56"}, {"tool": "maspsx", "version": "2.56", "cmd": []}):
        with pytest.raises(ValueError, match="assembler"):
            assembler_profile(value)
    assert small_data_limit([]) == 8
    assert small_data_limit(["-G0", "-O2", "-G", "8"]) == 8
    assert small_data_limit(["-G", "8", "-G0"]) == 0
    for flags in (["-G"], ["-G-1"], ["-Geight"], ["-G2147483648"]):
        with pytest.raises(ValueError, match="-G"):
            small_data_limit(flags)


@pytest.fixture
def native_processes(monkeypatch):
    def no_wsl(*args, **kwargs):
        pytest.fail("PS1 assembler profiles must run natively without WSL")
    monkeypatch.setattr(wsl, "status", no_wsl)
    monkeypatch.setattr(wsl, "run", no_wsl)
    original = subprocess.Popen
    def start(args, *a, **kw):
        assert Path(str(args[0])).name.lower() not in ("sh", "sh.exe", "bash", "bash.exe", "wsl", "wsl.exe")
        return original(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", start)


def config(root, tcid, version, language="c++", limit=0):
    assert all(toolchains.installed(t) for t in (tcid, "binutils-mips", "maspsx"))
    return project.compiler_config(root, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": tcid, "language": language, "flags": ["-O2", "-G" + str(limit)], "sandbox": "none",
        "assembler": {"tool": "maspsx", "version": version}}})


def execute(code, address, *, argument=0, gp=0, value=0):
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
    from unicorn.mips_const import UC_MIPS_REG_A0, UC_MIPS_REG_GP, UC_MIPS_REG_RA, UC_MIPS_REG_V0
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
    uc.mem_map(0, 0x200000)
    uc.mem_write(address & 0x1FFFFFFF, code)
    uc.mem_write(0x12000, struct.pack("<I", value))
    uc.reg_write(UC_MIPS_REG_A0, argument)
    uc.reg_write(UC_MIPS_REG_GP, gp)
    uc.reg_write(UC_MIPS_REG_RA, 0x80011000)
    uc.emu_start(address, 0x80011000, count=100)
    return uc.reg_read(UC_MIPS_REG_V0), struct.unpack("<I", uc.mem_read(0x12000, 4))[0]


@REAL
@pytest.mark.parametrize("tcid", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("language", ["c", "c++"])
@pytest.mark.parametrize("version", ASPSX_VERSIONS)
def test_original_frontend_profiles_match_authored_setters_and_execute(tmp_path, tcid, language, version, native_processes):
    cfg = config(tmp_path / "source project with spaces", tcid, version, language)
    result = compiler.compile_source(cfg, "extern volatile int value;",
        "void set_value(int x) { value = x; } int identity(int x) { return x; }")
    assert result.ok, result.log
    address, data = 0x80010500, 0x80012000
    if tcid == "gcc-2.7.2-psx":
        # Ordinary C setter, using ASPSX's unscheduled jump delay slot.
        words, lo = (0x3C018001, 0xAC242000, 0x03E00008, 0), 4
    else:
        # The later original GCC uses $v0; the volatile write precedes the jump.
        words, lo = (0x3C028001, 0xAC442000, 0x03E00008, 0), 4
    target = match.RomTarget("set_value", address, struct.pack("<%dI" % len(words), *words),
                             [(0, 5, data), (lo, 6, data)], False)
    linked = match.link(result.obj, "set_value", target, SymbolTable([Symbol("value", data)]), lambda *_: None)
    assert linked.exact, linked.problems
    assert execute(target.code, address, argument=0x12345678)[1] == 0x12345678
    identity = elfobj.extract_function(result.obj, "identity")
    assert not identity.relocs
    assert 0x00801021 in struct.unpack("<%dI" % (len(identity.code) // 4), identity.code)  # ADDU, not OR alias
    assert execute(identity.code, address, argument=37)[0] == 37


@REAL
@pytest.mark.parametrize("tcid", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
@pytest.mark.parametrize("version", ASPSX_VERSIONS)
def test_gp_common_symbols_keep_original_address_and_execute(tmp_path, tcid, version, native_processes):
    result = compiler.compile_source(config(tmp_path, tcid, version, limit=8), "int value;",
                                     "int read_value(void) { return value; }")
    assert result.ok, result.log
    address, data, gp = 0x80010500, 0x80012000, 0x80018000
    target = match.RomTarget("read_value", address, struct.pack("<3I", 0x8F82A000, 0x03E00008, 0),
                             [(0, 7, data)], False, gp)
    linked = match.link(result.obj, "read_value", target, SymbolTable([Symbol("value", data)]), lambda *_: None)
    assert linked.exact, linked.problems
    assert execute(target.code, address, gp=gp, value=71)[0] == 71


@REAL
@pytest.mark.parametrize("tcid", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_profile_survives_exact_judge_and_clean_standalone_disc_export(tmp_path, tcid, native_processes):
    cfg = config(tmp_path, tcid, "2.56")
    source = "int identity(int x) { return x; }"
    result = compiler.compile_source(cfg, "", source)
    assert result.ok, result.log
    fn = elfobj.extract_function(result.obj, "identity")
    assert not fn.relocs
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(fn.code)] = fn.code
    original = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "source projects with spaces")
    slug = net.import_rom(original, toolchain=tcid, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    p = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", p["id"], 0x80010500)
    selected = {"assembler": {"tool": "maspsx", "version": "2.56"}}
    net.set_function_compiler(slug, fn["name"], selected)
    agent, _ = net.local_agent("profile-recovery")
    authored = f"int {fn['name']}(int x) {{ return x; }}"
    assert not net.attempt(agent, fn["name"], authored.replace("return x;", "return x + 1;"), slug)["matched"]
    assert net.attempt(agent, fn["name"], authored, slug)["matched"]
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"] and not exported["fallback"], exported
    tree = Path(exported["path"])
    meta = json.loads((tree / "build.json").read_text())
    saved = next(f for f in meta["functions"] if f["vram"] == 0x80010500)
    assert saved["compiler"]["assembler"] == selected["assembler"]
    for folder in ("asm", "assets", ".splat", "build"):
        shutil.rmtree(tree / folder, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=180)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / meta["disc"]["output"]).read_bytes() == original
