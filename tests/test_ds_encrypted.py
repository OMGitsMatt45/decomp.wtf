"""Original encrypted DS fixtures: private keys, strict rebuilds and real Thumb matching.

The generated 16 KiB file is deterministic test data, with no console BIOS code
or Nintendo key table. dsd uses it to encrypt and decrypt our own demo only.
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from elftools.elf.elffile import ELFFile
from starlette.testclient import TestClient

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.forks import drafts, scratch_dsd
from decompnet.forks.project import ForkProject

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "projects/demo-ds"
ROM = DEMO / "build/demoquest.nds"

pytestmark = pytest.mark.skipif(
    any(toolchains.installed(t) is None for t in ("mwccarm", "dsd", "objdiff-cli"))
    or (toolchains.get("wibo").supported and toolchains.installed("wibo") is None),
    reason="needs CodeWarrior for DS, ds-decomp and objdiff")


@pytest.fixture(scope="module")
def encrypted(tmp_path_factory):
    if not ROM.exists():
        subprocess.run([sys.executable, str(DEMO / "build.py")], check=True)
    work = tmp_path_factory.mktemp("encrypted DS fixture")
    bios = work / "original test key.bin"
    bios.write_bytes(hashlib.shake_256(b"decomp.wtf original non-console test key").digest(0x4000))
    dsd = str(toolchains.binary("dsd"))
    seed = work / "seed"
    subprocess.run([dsd, "rom", "extract", "--rom", str(ROM), "--output-path", str(seed)], check=True,
                   capture_output=True)
    config = seed / "arm9/arm9.yaml"
    text = config.read_text(encoding="utf-8")
    assert "encrypted: false" in text
    config.write_text(text.replace("encrypted: false", "encrypted: true"), encoding="utf-8")
    # Two mutually exclusive ARM9 overlays share a runtime address; an ARM7
    # overlay is retained as original data. Each includes unused data and the
    # Nitro-style constructor terminator and aligned BSS extent.
    config = seed / "config.yaml"
    text = config.read_text(encoding="utf-8")
    for cpu, file_ids, address in (("arm9", [0, 1], 0x02200000), ("arm7", [2], 0x02390000)):
        overlays = []
        for index, file_id in enumerate(file_ids):
            data = struct.pack("<III", 0xE2800001 + index, 0xE12FFF1E, 0x12345678 + index) + bytes(20)
            name = f"ov{index:03}.bin"
            (seed / cpu / name).write_bytes(data)
            overlays.append({"id": index, "base_address": address, "code_size": len(data), "bss_size": 32,
                             "ctor_start": address + 28, "ctor_end": address + 32, "file_id": file_id,
                             "compressed": False, "signed": False, "file_name": name})
        (seed / cpu / "overlays.yaml").write_text(json.dumps({"table_signed": False, "overlays": overlays}),
                                                  encoding="utf-8")
        text = text.replace(f"{cpu}_overlays: null", f"{cpu}_overlays: {cpu}/overlays.yaml")
    config.write_text(text, encoding="utf-8")
    game = work / "encrypted.nds"
    subprocess.run([dsd, "rom", "build", "--config", str(seed / "config.yaml"), "--rom", str(game),
                    "--arm7-bios", str(bios)], check=True, capture_output=True)
    assert game.read_bytes()[0x4000:0x4800] != ROM.read_bytes()[0x4000:0x4800]
    return game, bios


@pytest.fixture(params=["2.0/sp1p5", "2.0/sp1p6"])
def imported(encrypted, tmp_path, request):
    game, bios = encrypted
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{request.param}", confirmed=True, log=lambda *_: None)
    deadline = time.monotonic() + 10
    while net.forks._linking.get(slug, {}).get("running") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not net.forks._linking.get(slug, {}).get("running")
    return net, slug, game, bios


def test_encrypted_rom_rebuilds_every_byte_and_keeps_bios_private(imported):
    net, slug, game, bios = imported
    overview = net.overview(slug)
    root = Path(net.project_row(slug)["root"])
    assert overview["rebuild"] == {"identical": True, "detail": "identical"}
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    assert struct.unpack_from("<I", game.read_bytes(), 0x54)[0] == 64
    assert struct.unpack_from("<I", game.read_bytes(), 0x5C)[0] == 32
    dsd = str(toolchains.binary("dsd"))
    config = "config/adqe/arm9/config.yaml"
    for args in (["check", "modules", "--config-path", config, "--fail"],
                 ["check", "symbols", "--config-path", config, "--elf-path", "build/adqe/arm9.o", "--fail"]):
        result = subprocess.run([dsd, *args], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    private = root / "extract/arm7_bios.bin"
    assert private.read_bytes() == bios.read_bytes()
    if sys.platform != "win32":
        assert private.stat().st_mode & 0o077 == 0
    tracked = subprocess.run(["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True).stdout.splitlines()
    assert tracked and not any(p.startswith(("extract/", "build/")) or "bios" in p for p in tracked)


@pytest.mark.parametrize("bss_size", [0, 4, 20, 36])
@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
def test_overlay_bss_extents_are_not_rounded(encrypted, tmp_path, monkeypatch, bss_size, compiler):
    game, bios = encrypted
    seed = tmp_path / "seed"
    shutil.copytree(game.parent / "seed", seed)
    config = seed / "arm9/overlays.yaml"
    overlays = json.loads(config.read_text(encoding="utf-8"))
    for overlay in overlays["overlays"]:
        overlay["bss_size"] = bss_size
    config.write_text(json.dumps(overlays), encoding="utf-8")
    game = tmp_path / "bss.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                    "--rom", str(game), "--arm7-bios", str(bios)], check=True, capture_output=True)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    assert net.overview(slug)["rebuild"]["identical"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    if bss_size:
        # A real linked BSS change must still fail the complete-image check.
        config = root / "config/adqe/arm9/overlays/ov000/delinks.txt"
        before = config.read_text(encoding="utf-8")
        old_end = 0x02200020 + bss_size
        config.write_text(before.replace(f"end:0x{old_end:08x}", f"end:0x{old_end + 4:08x}"), encoding="utf-8")
        result = net.forks.check_rom(slug, log=lambda *_: None)
        assert not result["identical"] and "overlay table" in result["detail"]
        assert not (root / "build/adqe/rom.ok").exists()


@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
@pytest.mark.parametrize("retained_checksum", [False, True])
def test_plain_rom_rebuilds_when_a_bios_is_configured(encrypted, tmp_path, compiler, retained_checksum):
    encrypted_game, bios = encrypted
    game = ROM
    if retained_checksum:
        seed = tmp_path / "decrypted seed"
        shutil.copytree(encrypted_game.parent / "seed", seed)
        config = seed / "arm9/arm9.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("encrypted: true", "encrypted: false"),
                          encoding="utf-8")
        game = tmp_path / "decrypted.nds"
        subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                        "--rom", str(game), "--arm7-bios", str(bios)], check=True, capture_output=True)
    assert bool(struct.unpack_from("<H", game.read_bytes(), 0x6C)[0]) == retained_checksum
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    net.forks.background_links = False
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    overview = net.overview(slug)
    assert overview["rebuild"]["identical"], overview["rebuild"]
    root = Path(net.project_row(slug)["root"])
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    assert ("--arm7-bios" in (root / "build.ninja").read_text(encoding="utf-8")) == retained_checksum
    standalone = tmp_path / "plain standalone with spaces"
    shutil.copytree(root, standalone, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json",
                                                                   ".ninja_*", ".decomp-wtf"))
    shutil.rmtree(standalone / "extract/adqe")
    fp = ForkProject(standalone)
    assert fp.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
    ok, log = fp.run(["ninja"], timeout=120)
    assert ok, log
    assert (standalone / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


def test_thumb_claim_match_restores_mode_and_keeps_strict_rebuild(imported):
    net, slug, _, _ = imported
    root = Path(net.project_row(slug)["root"])
    with (DEMO / "build/demoq_ds.elf").open("rb") as stream:
        table = ELFFile(stream).get_section_by_name(".symtab")
        address = next(s["st_value"] for s in table.iter_symbols() if s.name == "ds_thumb_step") & ~1
    symbol = f"func_{address:08x}"
    fn = net.store.one("SELECT unit FROM functions WHERE name=?", symbol)
    assert fn is not None
    agent, _ = net.local_agent("ds-mode-owner")
    code = f"int {symbol}(int value) {{ return value + 3; }}"
    wrong_mode = net.attempt(agent, symbol, code, slug)
    assert not wrong_mode["matched"]
    source = drafts.ds_mode_source(root, fn["unit"], symbol, code)
    assert "#pragma thumb on" in source
    result = net.attempt(agent, symbol, source, slug)
    assert result["matched"], result["text"]
    assert not net.store.one("SELECT 1 FROM claims WHERE agent_id=?", agent.id)
    assert scratch_dsd.check_rom(root, "adqe", log=lambda *_: None)["identical"]


def test_overlays_at_the_same_address_have_separate_judging_and_claims(imported):
    net, slug, _, _ = imported
    functions = sorted((row for row in net.store.all("SELECT name, unit, meta FROM functions")
                        if row["unit"].startswith("src/auto/ov") and row["name"].endswith("_02200000")),
                       key=lambda row: row["unit"])
    assert len(functions) == 2 and functions[0]["name"] != functions[1]["name"]
    agent, _ = net.local_agent("overlay-owner")
    symbol = json.loads(functions[1]["meta"])["symbol"]
    wrong = net.attempt(agent, functions[1]["name"], f"int {symbol}(int x) {{ return x + 1; }}", slug)
    assert not wrong["matched"]
    net.release(agent, functions[1]["name"], "", slug)
    for index, fn in enumerate(functions):
        symbol = json.loads(fn["meta"])["symbol"]
        result = net.attempt(agent, fn["name"], f"int {symbol}(int x) {{ return x + {index + 1}; }}", slug)
        assert result["matched"], result["text"]
    assert not net.store.one("SELECT 1 FROM claims WHERE agent_id=?", agent.id)


@pytest.mark.parametrize("compiler", [
    "1.2/base", "1.2/sp2", "1.2/sp2p3", "1.2/sp3", "1.2/sp4",
    "2.0/base", "2.0/sp1", "2.0/sp1p2", "2.0/sp1p7", "2.0/sp2", "2.0/sp2p2", "2.0/sp2p3", "2.0/sp2p4",
    "dsi/1.1", "dsi/1.1p1", "dsi/1.2", "dsi/1.2p1", "dsi/1.2p2", "dsi/1.3", "dsi/1.3p1",
    "dsi/1.6sp1", "dsi/1.6sp2",
])
def test_other_registered_ds_compilers_link_matching_source(encrypted, tmp_path, monkeypatch, compiler):
    """A DSi-branded compiler can build ordinary DS code; this does not enable TWL containers."""
    game, bios = encrypted
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    fn = next(row for row in net.store.all("SELECT name, unit, meta FROM functions")
              if row["unit"].startswith("src/auto/ov000"))
    symbol = json.loads(fn["meta"])["symbol"]
    agent, _ = net.local_agent("compiler-owner")
    result = net.attempt(agent, fn["name"], f"int {symbol}(int value) {{ return value + 1; }}", slug)
    assert result["matched"], result["text"]
    source = ForkProject(root).unit(fn["unit"]).source
    assert source in net.forks.link(slug, log=lambda *_: None)["linked"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
@pytest.mark.parametrize("bss_size", [0, 32])
def test_additional_runtime_autoload_is_linked(encrypted, tmp_path, monkeypatch, compiler, bss_size):
    game, bios = encrypted
    seed = tmp_path / "seed"
    shutil.copytree(game.parent / "seed", seed)
    config = seed / "config.yaml"
    paths = yaml.safe_load(config.read_text(encoding="utf-8"))
    paths["unknown_autoloads"] = [{"index": 2, "bin": "arm9/autoload_2.bin", "config": "arm9/autoload_2.yaml"}]
    config.write_text(yaml.safe_dump(paths), encoding="utf-8")
    (seed / "arm9/autoload_2.bin").write_bytes(struct.pack("<II", 0xE2800007, 0xE12FFF1E) + bytes(24))
    (seed / "arm9/autoload_2.yaml").write_text(
        f"base_address: 0x02280000\ncode_size: 32\nbss_size: {bss_size}\nkind: !Unknown 2\n", encoding="utf-8")
    game = tmp_path / "autoload.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(config),
                    "--rom", str(game), "--arm7-bios", str(bios)], check=True, capture_output=True)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    symbol = "func_02280000"
    fn = net.store.one("SELECT name, unit FROM functions WHERE name=?", symbol)
    assert fn is not None
    agent, _ = net.local_agent("runtime-autoload-owner")
    result = net.attempt(agent, symbol, f"int {symbol}(int value) {{ return value + 7; }}", slug)
    assert result["matched"], result["text"]
    source = ForkProject(root).unit(fn["unit"]).source
    assert source in net.forks.link(slug, log=lambda *_: None)["linked"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


@pytest.mark.parametrize("language", ["c", "c++"])
def test_matching_overlay_source_is_linked_and_changes_are_rejected(imported, monkeypatch, language):
    net, slug, game, _ = imported
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    root = Path(net.project_row(slug)["root"])
    fp = ForkProject(root)
    fn = next(row for row in net.store.all("SELECT name, unit, meta FROM functions")
              if row["unit"].startswith("src/auto/ov000"))
    source = fp.unit(fn["unit"]).source
    if language == "c++":
        cpp = Path(source).with_suffix(".cpp").as_posix()
        config = root / "config/adqe/arm9/overlays/ov000/delinks.txt"
        config.write_text(config.read_text(encoding="utf-8").replace(source + ":", str(Path(cpp)) + ":"), encoding="utf-8")
        (root / source).rename(root / cpp)
        assert fp.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
        assert fp.build_all()[0]
        assert fp.run(["ninja", "objdiff.json"])[0]
        net.forks.check(slug, log=lambda *_: None)
        source = cpp
    agent, _ = net.local_agent("linked-overlay-owner")
    symbol = json.loads(fn["meta"])["symbol"]
    code = f"int {symbol}(int value) {{ return value + 1; }}"
    if language == "c++":
        with (root / source).open("a", encoding="utf-8") as stream:
            stream.write(f'\nextern "C" int {symbol}(int value);\n')
        code = code.replace("return value", "return static_cast<int>(value)")
    result = net.attempt(agent, fn["name"], code, slug)
    assert result["matched"], result["text"]
    linked = net.forks.link(slug, log=lambda *_: None)
    assert source in linked["linked"], (linked, fp.link_states(),
                                       [u for u in fp.report()["units"] if u["name"] == fn["unit"]])
    assert fp.link_states()[source][0] == "Matching"
    objects = (root / "build/adqe/objects.txt").read_text(encoding="utf-8").replace("\\", "/")
    assert f'"build/adqe/{Path(source).with_suffix(".o").as_posix()}"' in objects
    assert f'"build/adqe/delinks/{Path(source).with_suffix(".o").as_posix()}"' not in objects
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    assert "LINKED" in net.forks.file_status(slug, source)
    original = (root / source).read_text(encoding="utf-8")
    rejected = net.attempt(agent, fn["name"], code.replace("+ 1", "+ 7"), slug)
    assert not rejected["matched"]
    assert (root / source).read_text(encoding="utf-8") == original
    # Prove the ROM consumes compiled source, not the retained target object.
    (root / source).write_text(original.replace("+ 1", "+ 7"), encoding="utf-8")
    assert not scratch_dsd.check_rom(root, "adqe", log=lambda *_: None)["identical"]
    assert not (root / "build/adqe/rom.ok").exists()
    (root / source).write_text(original, encoding="utf-8")
    assert scratch_dsd.check_rom(root, "adqe", log=lambda *_: None)["identical"]


def test_linker_exception_restores_the_ds_configuration(imported, monkeypatch):
    net, slug, _, _ = imported
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    root = Path(net.project_row(slug)["root"])
    fp = ForkProject(root)
    fn = next(row for row in net.store.all("SELECT name, unit, meta FROM functions")
              if row["unit"].startswith("src/auto/ov000"))
    agent, _ = net.local_agent("rollback-owner")
    symbol = json.loads(fn["meta"])["symbol"]
    assert net.attempt(agent, fn["name"], f"int {symbol}(int x) {{ return x + 1; }}", slug)["matched"]
    for index, path in enumerate(fp.link_config_paths()):
        data = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(data.replace(b"\n", b"\r\n") if index % 2 else data)
    before = {p: p.read_bytes() for p in fp.link_config_paths()}
    real_verify = ForkProject.verify

    def interrupted(project, *a, **kw):
        if project.root == root and any(state[0] == "Matching" for state in project.link_states().values()):
            raise RuntimeError("simulated linker interruption")
        return real_verify(project, *a, **kw)

    monkeypatch.setattr(ForkProject, "verify", interrupted)
    with pytest.raises(RuntimeError, match="simulated linker interruption"):
        net.forks.link(slug, log=lambda *_: None)
    assert {p: p.read_bytes() for p in before} == before
    assert real_verify(fp)[0]


@pytest.mark.parametrize("module", ["main-thumb", "itcm"])
@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
def test_matching_main_and_autoload_sources_enter_the_rom(encrypted, tmp_path, monkeypatch, module, compiler):
    game, bios = encrypted
    if module == "itcm":
        seed = tmp_path / "seed"
        shutil.copytree(game.parent / "seed", seed)
        (seed / "arm9/itcm.bin").write_bytes(struct.pack("<II", 0xE2800005, 0xE12FFF1E) + bytes(24))
        game = tmp_path / "autoload.nds"
        subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                        "--rom", str(game), "--arm7-bios", str(bios)], check=True, capture_output=True)
        symbol = "func_01ff8000"
        source = f"int {symbol}(int value) {{ return value + 5; }}"
    else:
        monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 16)
        with (DEMO / "build/demoq_ds.elf").open("rb") as stream:
            table = ELFFile(stream).get_section_by_name(".symtab")
            address = next(s["st_value"] for s in table.iter_symbols() if s.name == "ds_thumb_step") & ~1
        symbol = f"func_{address:08x}"
        source = f"int {symbol}(int value) {{ return value + 3; }}"
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    fp = ForkProject(root)
    fn = net.store.one("SELECT name, unit FROM functions WHERE name=?", symbol)
    assert fn is not None
    source = drafts.ds_mode_source(root, fn["unit"], symbol, source)
    agent, _ = net.local_agent("linked-module-owner")
    result = net.attempt(agent, symbol, source, slug)
    assert result["matched"], result["text"]
    linked = net.forks.link(slug, log=lambda *_: None)
    assert fp.unit(fn["unit"]).source in linked["linked"], linked
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


@pytest.mark.parametrize("compression", ["arm9", "overlays", "both"])
@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
def test_compressed_modules_rebuild_with_linked_source(encrypted, tmp_path, monkeypatch, compression, compiler):
    game, bios = encrypted
    seed = tmp_path / "seed"
    shutil.copytree(game.parent / "seed", seed)
    if compression in ("arm9", "both"):
        config = seed / "arm9/arm9.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("compressed: false", "compressed: true"),
                          encoding="utf-8")
    if compression in ("overlays", "both"):
        for cpu in ("arm9", "arm7"):
            config = seed / cpu / "overlays.yaml"
            overlays = json.loads(config.read_text(encoding="utf-8"))
            for overlay in overlays["overlays"]:
                data = (seed / cpu / overlay["file_name"]).read_bytes()[:12] + bytes(500)
                (seed / cpu / overlay["file_name"]).write_bytes(data)
                overlay.update(compressed=True, code_size=len(data), bss_size=4,
                               ctor_start=overlay["base_address"] + 508, ctor_end=overlay["base_address"] + 512)
            config.write_text(json.dumps(overlays), encoding="utf-8")
    game = tmp_path / "compressed.nds"
    dsd = str(toolchains.binary("dsd"))
    subprocess.run([dsd, "rom", "build", "--config", str(seed / "config.yaml"), "--rom", str(game),
                    "--arm7-bios", str(bios)], check=True, capture_output=True)
    if compression in ("overlays", "both"):
        data = game.read_bytes()
        for offset in (0x50, 0x58):
            table = struct.unpack_from("<I", data, offset)[0]
            assert struct.unpack_from("<I", data, table + 28)[0] & (1 << 24)
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    with patch.dict(os.environ, {"DECOMP_ARM7_BIOS": str(bios)}):
        slug = net.import_rom(game, toolchain=f"DS/{compiler}", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    assert net.overview(slug)["rebuild"]["identical"]
    arm9_config = (root / "extract/adqe/arm9/arm9.yaml").read_text(encoding="utf-8")
    assert ("compressed: true" in arm9_config) == (compression in ("arm9", "both"))
    fn = next(row for row in net.store.all("SELECT name, unit, meta FROM functions")
              if row["unit"].startswith("src/auto/ov000"))
    symbol = json.loads(fn["meta"])["symbol"]
    agent, _ = net.local_agent("compressed-overlay-owner")
    result = net.attempt(agent, fn["name"], f"int {symbol}(int value) {{ return value + 1; }}", slug)
    assert result["matched"], result["text"]
    assert ForkProject(root).unit(fn["unit"]).source in net.forks.link(slug, log=lambda *_: None)["linked"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    assert subprocess.run([dsd, "check", "modules", "--config-path", "config/adqe/arm9/config.yaml", "--fail"],
                          cwd=root, capture_output=True).returncode == 0
    source = root / ForkProject(root).unit(fn["unit"]).source
    correct = source.read_text(encoding="utf-8")
    source.write_text(correct.replace("+ 1", "+ 7"), encoding="utf-8")
    assert not net.forks.check_rom(slug, log=lambda *_: None)["identical"]
    assert not (root / "build/adqe/rom.ok").exists()
    source.write_text(correct, encoding="utf-8")
    assert net.forks.check_rom(slug, log=lambda *_: None)["identical"]
    standalone = tmp_path / "linked standalone with spaces"
    shutil.copytree(root, standalone, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json",
                                                                   ".ninja_*", ".decomp-wtf"))
    shutil.rmtree(standalone / "extract/adqe")
    fp = ForkProject(standalone)
    assert fp.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()])[0]
    ok, log = fp.run(["ninja"], timeout=120)
    assert ok, log
    assert (standalone / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


def test_encrypted_project_rebuilds_from_a_clean_standalone_copy(imported, tmp_path):
    net, slug, game, _ = imported
    root = Path(net.project_row(slug)["root"])
    standalone = tmp_path / "standalone project with spaces"
    shutil.copytree(root, standalone, ignore=shutil.ignore_patterns(".git", "build", "build.ninja", "objdiff.json",
                                                                   ".ninja_*", ".decomp-wtf"))
    subprocess.run([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()],
                   cwd=standalone, check=True, capture_output=True)
    shutil.rmtree(standalone / "extract/adqe")
    ok, log = ForkProject(standalone).run(["ninja"], log=lambda *_: None, timeout=120)
    assert ok, log
    assert (standalone / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()


def test_failed_standalone_extraction_preserves_the_verified_reference(imported, tmp_path):
    net, slug, game, _ = imported
    root = Path(net.project_row(slug)["root"])
    reference = root / "extract/adqe"

    def contents():
        return {p.relative_to(reference): p.read_bytes() for p in reference.rglob("*") if p.is_file()}

    before = contents()
    bios = root / "extract/arm7_bios.bin"
    correct = bios.read_bytes()
    try:
        bios.write_bytes(bytes(0x4000))
        # The pinned raw toolkit exits successfully with this wrong key and
        # round-trips every byte except the eight-byte secure marker and two
        # checksums. Reject that misleading 12-byte failure before it can
        # replace the objects used as matching references.
        raw = tmp_path / "unguarded extraction"
        dsd = str(toolchains.binary("dsd"))
        result = subprocess.run([dsd, "rom", "extract", "--rom", str(game), "--output-path", str(raw),
                                 "--arm7-bios", str(bios)], capture_output=True, text=True)
        assert result.returncode == 0 and "Failed to decrypt secure area" in result.stdout + result.stderr
        rebuilt = tmp_path / "unguarded.nds"
        subprocess.run([dsd, "rom", "build", "--config", str(raw / "config.yaml"), "--rom", str(rebuilt),
                        "--arm7-bios", str(bios)], check=True, capture_output=True)
        original, output = game.read_bytes(), rebuilt.read_bytes()
        assert len(original) == len(output)
        assert {i for i, (a, b) in enumerate(zip(original, output)) if a != b} == {
            0x6C, 0x6D, 0x15E, 0x15F, *range(0x4000, 0x4008),
        }
        for _ in range(2):
            result = subprocess.run([sys.executable, "tools/extract.py", str(toolchains.binary("dsd")),
                                     "rom", "extract", "--rom", "extract/baserom.nds", "--output-path", "extract/adqe",
                                     "--arm7-bios", "extract/arm7_bios.bin"], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            assert result.returncode != 0 and "did not validate" in result.stderr
            assert contents() == before
            assert not list((root / "extract").glob(".adqe-extract-*"))
    finally:
        bios.write_bytes(correct)
    assert scratch_dsd.check_rom(root, "adqe", log=lambda *_: None)["identical"]


@pytest.mark.skipif(toolchains.installed("m2c") is None, reason="bounded pilot needs the registered m2c tool")
def test_bounded_pilot_cli_uses_the_private_key_and_reports_strict_rebuild(encrypted, tmp_path):
    game, bios = encrypted
    work = tmp_path / "pilot with spaces"
    result = subprocess.run([sys.executable, str(ROOT / "tools/ds_pilot.py"), "--rom", str(game),
                             "--arm7-bios", str(bios), "--work", str(work), "--own-copy", "--drafts", "2",
                             "--sample", "spread", "--compiler", "DS/2.0/sp1p6"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((work / "pilot-result.json").read_text(encoding="utf-8"))
    assert report["compiler"] == "DS/2.0/sp1p6" and report["sample_attempts"] == 2
    assert sum(report["outcomes"].values()) == 2 and len(report["results"]) == 2
    assert report["rebuild"]["identical"]


@pytest.mark.skipif(toolchains.installed("m2c") is None, reason="bounded pilot needs the registered m2c tool")
@pytest.mark.parametrize("compiler", ["2.0/sp1p5", "2.0/sp1p6"])
def test_bounded_pilot_finishes_source_linking_before_exit(encrypted, tmp_path, compiler):
    game, bios = encrypted
    work = tmp_path / "linked pilot"
    remaining = tmp_path / "remaining.csv"
    remaining.write_text("analysis_name\nfunc_ov000_02200000\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "tools/ds_pilot.py"), "--rom", str(game),
                             "--arm7-bios", str(bios), "--work", str(work), "--own-copy", "--drafts", "1",
                             "--remaining-report", str(remaining), "--compiler", f"DS/{compiler}"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((work / "pilot-result.json").read_text(encoding="utf-8"))
    assert report["outcomes"] == {"match": 1}
    assert report["link"]["linked"] == ["src/auto/ov000_02200000.c"]
    root = work / report["project"]
    assert ForkProject(root).link_states()["src/auto/ov000_02200000.c"][0] == "Matching"
    assert report["rebuild"]["identical"]
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    assert scratch_dsd.check_rom(root, "adqe", log=lambda *_: None)["identical"]


def test_pilot_cli_rejects_a_private_work_directory_inside_the_checkout(encrypted):
    game, _ = encrypted
    result = subprocess.run([sys.executable, str(ROOT / "tools/ds_pilot.py"), "--rom", str(game),
                             "--work", str(ROOT), "--own-copy"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 2 and "--work must be outside this checkout" in result.stderr


@pytest.mark.parametrize("key", ["missing", "wrong", "correct"])
def test_encrypted_http_import_reports_key_failures_before_registering_a_project(encrypted, tmp_path, monkeypatch, key):
    game, bios = encrypted
    if key == "missing":
        monkeypatch.delenv("DECOMP_ARM7_BIOS", raising=False)
    elif key == "wrong":
        wrong = tmp_path / "wrong key.bin"
        wrong.write_bytes(bytes(0x4000))
        monkeypatch.setenv("DECOMP_ARM7_BIOS", str(wrong))
    else:
        monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    home = tmp_path / "app"
    state = home / ".decomp"
    state.mkdir(parents=True)
    net = RomNetwork(state / "app.db", home)
    mcp, _, security = build(net, state, 6499, "original-fixture-test")
    client = TestClient(mcp.streamable_http_app(transport_security=security, host="127.0.0.1"),
                        base_url="http://127.0.0.1:6499")
    client.cookies.set("decomp_live", "original-fixture-test")
    headers = {"X-Decomp": "1"}
    client.post("/api/settings", json={"autopilot": False}, headers=headers).raise_for_status()
    response = client.post("/api/import", params={"path": str(game), "confirmed": "1"}, headers=headers)
    response.raise_for_status()
    job = response.json()["job"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = client.get("/api/job", params={"id": job}).json()
        if status["state"] != "running":
            break
        time.sleep(0.02)
    assert status["state"] != "running", status
    if key == "correct":
        assert status["state"] == "done", status
        overview = net.overview(status["result"]["slug"])
        assert overview["ready"] and overview["rebuild"]["identical"]
    else:
        assert status["state"] == "error", status
        diagnostic = json.dumps(status)
        assert ("DECOMP_ARM7_BIOS" if key == "missing" else "did not validate") in diagnostic
        assert not net.store.all("SELECT id FROM projects")
        assert not list(home.glob("*/extract/arm7_bios.bin"))
