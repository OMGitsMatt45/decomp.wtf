"""Home-made boot programs exercise the same unusual layouts as real utilities."""

import hashlib
import json
import struct
from pathlib import Path

import pytest

from decompnet import toolchains
from decompnet.app import tools
from decompnet.app.engine import RomNetwork
from decompnet.compiler import CompilerConfig, compile_source, _wrap
from decompnet.network import NetworkError
from decompnet.rom import boot, boot_build
from decompnet.rom.errors import RomError
from decompnet.forks.scratch_dsd import crc16


def ds_utility():
    raw = bytearray(0x800)
    raw[:12] = b"TEST UTILITY"
    raw[12:16] = b"TSTE"
    struct.pack_into("<IIII", raw, 0x20, 0x400, 0x02000000, 0x02000000, 0x14)
    struct.pack_into("<IIII", raw, 0x30, 0x600, 0x03800000, 0x03800000, 8)
    struct.pack_into("<IIII", raw, 0x400, 0xFA000002, 0xE12FFF1E, 0xE1A00000, 0xE1A00000)
    raw[0x410:0x414] = bytes.fromhex("07207047")  # Thumb: movs r0,7; bx lr
    struct.pack_into("<II", raw, 0x600, 0xE3A00003, 0xE12FFF1E)
    struct.pack_into("<H", raw, 0x15E, crc16(raw[:0x15E]))
    return bytes(raw)


def gc_utility():
    raw = bytearray(0x2480)
    raw[:6] = b"TSTe01"  # homebrew/utility IDs can contain lowercase
    raw[0x20:0x2C] = b"TEST UTILITY"
    struct.pack_into(">I", raw, 0x1C, 0xC2339F3D)
    struct.pack_into(">III", raw, 0x2450, 0x81200000, 12, 20)
    raw[0x2460:0x246C] = bytes.fromhex("38600001480000044e800020")  # li r3,1; b next; blr
    return bytes(raw)


@pytest.mark.parametrize("platform,make,tid", [("nds", ds_utility, "binutils-arm")])
def test_import_export_and_edited_instructions_are_actually_checked(tmp_path, platform, make, tid):
    if toolchains.installed(tid) is None:
        pytest.skip(f"requires {tid}")
    original = make()
    path = tmp_path / ("utility.nds" if platform == "nds" else "utility.iso")
    path.write_bytes(original)
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    slug = net.import_rom(path, confirmed=True, log=lambda *_: None)
    proj = net.project_row(slug)
    ov = net.overview(slug)
    assert ov["compiler"]["language"] == "asm" and ov["assembly_dialect"] == "gnu"
    assert ov["progress_kind"] == "assembly" and ov["matched_bytes"] == 0
    assert ov["base_bytes"] + ov["assembly_bytes"] == ov["bytes"]
    assert "GNU assembly" in tools.project_info(net, slug)
    agent, _ = net.local_agent("reviewer")
    brief = net.claim_many(agent, slug, 4)
    assert "GNU" in brief and "RGBDS" not in brief and "m2c:" not in brief
    assert len(net.store.all("SELECT * FROM claims")) == 1
    assert "context.inc" in net.get_context(slug)
    with pytest.raises(NetworkError, match="review"):
        net.start_autopilot(slug)
    out = net.export_rom(slug, log=lambda *_: None)
    assert out["identical"] and out["scope"] == ("cartridge" if platform == "nds" else "apploader")
    root = Path(out["path"])
    manifest = json.loads((root / "build.json").read_text())
    assert manifest["input_sha256"] == hashlib.sha256(original).hexdigest()
    assert boot_build.build(root)["identical"]  # standalone reassembly from editable instructions
    region = manifest["ranges"][0]
    src = root / region["source"]
    source = src.read_text()
    src.write_text(source.replace(region["name"], "wrong_label"))
    with pytest.raises(ValueError, match="function label"):
        boot_build.build(root)
    src.write_text(source)
    if platform == "nds":
        source = source.replace("bx lr", "bx r0")
    else:
        source = source.replace("r3, 1", "r3, 2")
    assert source != src.read_text()
    src.write_text(source)
    with pytest.raises(ValueError, match="differs"):
        boot_build.build(root)
    assert not (root / "build" / manifest["output"]).exists()




@pytest.mark.parametrize("source", ['.incbin "/secret"', '.include "x"', '.macro x', '.altmacro',
                                   '.irp x, a', '.mri 1', 'mov r0, #0; .incbin "x"', r'.i\()ncbin "x"'])
def test_gnu_submissions_cannot_read_files_or_generate_directives(source):
    cfg = CompilerConfig(["must-not-run"], language="asm", assembly_dialect="gnu")
    result = compile_source(cfg, "", source)
    assert not result.ok and "self-contained" in result.log


def test_ds_program_ranges_are_validated_before_reading(tmp_path):
    raw = bytearray(ds_utility())
    struct.pack_into("<I", raw, 0x2C, len(raw))
    struct.pack_into("<H", raw, 0x15E, crc16(raw[:0x15E]))
    path = tmp_path / "bad.nds"
    path.write_bytes(raw)
    with pytest.raises(RomError, match="ARM9 program range|arm9 program range"):
        boot.identify(path)


def test_docker_sandbox_mounts_pinned_tools_and_runtime_read_only(tmp_path):
    cfg = CompilerConfig(["/tools/as"], sandbox="docker", image="compiler-image",
                         ro_paths=("/tools", "/tools"), runtime32="/runtime32")
    argv = _wrap(cfg, tmp_path, cfg.cmd)
    assert argv.count("/tools:/tools:ro") == 1
    assert "/runtime32:/opt/rt32:ro" in argv
    assert "/runtime32/ld-linux.so.2:/lib/ld-linux.so.2:ro" in argv
    assert argv[-2:] == ["compiler-image", "/tools/as"]
    assert "--read-only" in argv and "--network" in argv and "none" in argv


def test_removed_disc_utilities_are_rejected_before_tool_setup(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path / 'app.db', tmp_path)
    monkeypatch.setattr(toolchains, 'ensure', lambda *a, **k: pytest.fail('removed backend started tools'))
    raw = gc_utility()
    for suffix in ('.iso', '.bin'):
        path = tmp_path / ('utility' + suffix)
        path.write_bytes(raw)
        with pytest.raises(NetworkError, match='removed'):
            net.import_rom(path, confirmed=True, log=lambda *_: None)
