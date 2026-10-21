"""Game Boy assembly foundations: banks, code discovery, and RGBDS as an encoding oracle."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from decompnet import toolchains
from decompnet.cli import main
from decompnet.rom import gb, sm83
from decompnet.rom.export_gb import export
from decompnet.rom.export_gb_build import BuildError, build


def cartridge(*, cgb=False, banks=4, mapper=1):
    """Original homebrew bytes: two routines share $4000, and ROM0 changes banks."""
    data = bytearray((i * 17 + i // 256) & 255 for i in range(banks * gb.BANK_SIZE))
    data[0x100:0x104] = bytes.fromhex("00 c3 50 01")
    data[0x104:0x134] = gb.LOGO
    data[0x134:0x144] = b"OWN CODE".ljust(16, b"\0")
    data[0x143] = 0x80 if cgb else 0
    data[0x147] = mapper
    data[0x148] = {72: 0x52, 80: 0x53, 96: 0x54}.get(banks, banks.bit_length() - 2)
    data[0x150:0x158] = bytes.fromhex("3e 02 ea 00 20 c3 00 40")
    data[0x200] = 0xC9
    data[0x4000:0x4006] = bytes.fromhex("3e 11 cd 00 02 c9")
    if banks > 2:
        data[0x8000:0x8003] = bytes.fromhex("3e 22 c9")
    if banks > 3:
        data[0xC000:0xC004] = bytes.fromhex("00 3c 18 fc")
    fix_header(data)
    return bytes(data)


def fix_header(data):
    data[0x14D] = (-sum(data[0x134:0x14D]) - 25) & 255
    data[0x14E:0x150] = b"\0\0"
    data[0x14E:0x150] = (sum(data) & 0xFFFF).to_bytes(2, "big")


@pytest.fixture
def rgbds():
    if toolchains.installed("rgbds") is None:
        if os.environ.get("DECOMP_TEST_GB_ASM") == "1":
            pytest.fail("required RGBDS integration tests need the pinned installation")
        pytest.skip("needs `decompnet toolchain install rgbds`")
    return toolchains.require("rgbds")


@pytest.mark.parametrize("cgb", [False, True])
def test_header(cgb):
    raw = cartridge(cgb=cgb)
    info = gb.read_info(raw)
    assert info["platform"] == ("gbc" if cgb else "gb")
    assert info["title"] == "OWN CODE" and info["banks"] == 4
    assert info["arch"] == "sm83" and info["language"] == "asm"
    assert info["mapper"] == "MBC1"
    assert info["header_checksum_valid"] and info["global_checksum_valid"]
    assert info["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.__setitem__(0x104, 0), "logo"),
    (lambda d: d.__setitem__(0x134, 0), "header checksum"),
    (lambda d: d.pop(), "declares 4 banks"),
])
def test_bad_header_or_size_rejected(mutate, message):
    raw = bytearray(cartridge())
    mutate(raw)
    with pytest.raises(gb.CartridgeError, match=message):
        gb.read_info(raw)


def test_nonstandard_sizes_and_global_checksum_are_preserved():
    raw = bytearray(cartridge(banks=72))
    assert gb.read_info(raw)["banks"] == 72
    raw[0x14F] ^= 1
    assert not gb.read_info(raw)["global_checksum_valid"]
    raw[0x148] = 0x55
    fix_header(raw)
    with pytest.raises(gb.CartridgeError, match="unknown.*size code"):
        gb.read_info(raw)


def test_bank_identity_and_resolution():
    one, two = gb.Address.parse("01:4000"), gb.Address.parse("02:4000")
    assert one != two and one.offset == 0x4000 and two.offset == 0x8000
    assert gb.Address.from_offset(0x8000) == two
    assert str(two) == "02:4000"
    info = gb.read_info(cartridge())
    assert gb.resolve(two, 0x4000, info) == two
    assert gb.resolve(two, 0x200, info) == gb.Address(0, 0x200)
    assert gb.resolve(gb.Address(0, 0x155), 0x4000, info) is None
    assert gb.resolve(two, 0xC000, info) is None
    assert gb.resolve(gb.Address(0, 0x155), 0x4000, gb.read_info(cartridge(banks=2, mapper=0))) == one


@pytest.mark.parametrize("text", ["4000", "1:0000", "0:4000", "200:4000", "-1:4000", "1:8000"])
def test_invalid_bank_addresses(text):
    with pytest.raises(gb.CartridgeError):
        gb.Address.parse(text)


def test_discovery_stops_at_mapper_write_and_accepts_explicit_banks():
    raw = cartridge()
    regions, notes = gb.discover(raw)
    assert [r.to_dict() for r in regions] == [
        {"bank": 0, "cpu": 0x100, "offset": 0x100, "size": 4},
        {"bank": 0, "cpu": 0x150, "offset": 0x150, "size": 5},
    ]
    assert any("mapper write" in note for note in notes)
    regions, notes = gb.discover(raw, [gb.Address(0, 0x100), gb.Address(1, 0x4000), gb.Address(2, 0x4000)])
    by_start = {r.start: r for r in regions}
    assert by_start[gb.Address(1, 0x4000)].size == 6
    assert by_start[gb.Address(2, 0x4000)].size == 3
    assert by_start[gb.Address(0, 0x200)].size == 1
    with pytest.raises(gb.CartridgeError, match="beyond"):
        gb.discover(raw, [gb.Address(4, 0x4000)])
    with pytest.raises(gb.CartridgeError, match="header"):
        gb.discover(raw, [gb.Address(0, 0x104)])


def test_indirect_and_overlapping_paths_stay_visible():
    raw = bytearray(cartridge())
    raw[0x150:0x153] = bytes.fromhex("20 ff e9")  # taken JR enters its own operand; fallthrough JP HL
    regions, notes = gb.discover(raw)
    assert any("operand" in note for note in notes)
    assert any("indirect" in note for note in notes)
    assert next(r for r in regions if r.start.cpu == 0x150).size == 3
    raw[0x150] = 0xD3
    regions, notes = gb.discover(raw)
    assert all(r.start.cpu != 0x150 for r in regions)
    assert any("invalid" in note for note in notes)


@pytest.mark.parametrize("encoded,text", [
    ("08 34 12", "ld [$1234], sp"), ("2a", "ld a, [hl+]"),
    ("e2", "ldh [$ff00+c], a"), ("f0 80", "ldh a, [$ff80]"),
    ("e8 80", "add sp, -128"), ("f8 ff", "ld hl, sp-1"),
    ("cb 7e", "bit 7, [hl]"), ("cb 36", "swap [hl]"),
    ("76", "halt"), ("10 00", "stop"), ("10 01", "db $10, $01"),
    ("cd 00 40", "call $4000"), ("ea 00 c0", "ld [$c000], a"),
    ("dd", "db $dd"), ("01 42", "db $01, $42"),
])
def test_known_instructions(encoded, text):
    assert sm83.decode(bytes.fromhex(encoded), 0x150).text == text


def test_export_does_not_overwrite_edited_sources(tmp_path):
    out = tmp_path / "export"
    export(cartridge(), out)
    source = out / "src/bank_000_0100.asm"
    source.write_text("; edited\n")
    with pytest.raises(gb.CartridgeError, match="not empty"):
        export(cartridge(), out)
    assert source.read_text() == "; edited\n"


def test_invalid_export_ranges(tmp_path):
    with pytest.raises(gb.CartridgeError, match="overlap"):
        export(cartridge(), tmp_path / "overlap", ranges=[gb.CodeRange(gb.Address(0, 0x100), 4)])
    with pytest.raises(gb.CartridgeError, match="beyond"):
        export(cartridge(), tmp_path / "beyond", ranges=[gb.CodeRange(gb.Address(4, 0x4000), 4)])
    with pytest.raises(gb.CartridgeError, match="inside one"):
        gb.CodeRange.parse("02:7fff:8001")


def test_cli_inspect_and_export_without_creating_database(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "own.gbc"
    rom.write_bytes(cartridge(cgb=True))
    assert main(["gb", "inspect", str(rom), "--entry", "02:4000"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["rom"]["platform"] == "gbc" and result["code_ranges"][-1]["bank"] == 2
    out = tmp_path / "project"
    assert main(["gb", "export", str(rom), str(out), "--range", "03:4000:4004"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["code_ranges"][-1]["bank"] == 3
    assert not (tmp_path / "decompnet.db").exists()
    assert not list(out.rglob("*.gb*"))
    assert main(["gb", "export", str(rom), str(tmp_path / "reviewed"), "--no-discover",
                 "--range", "02:4000:4003"]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["assembly_bytes"] == 3 and len(reviewed["code_ranges"]) == 1
    assert main(["gb", "inspect", str(rom), "--no-discover", "--entry", "02:4000"]) == 1
    assert "cannot be combined" in capsys.readouterr().err
    rom.write_bytes(b"bad")
    assert main(["gb", "inspect", str(rom)]) == 1
    assert "cartridge header" in capsys.readouterr().err


def test_every_opcode_round_trips_through_rgbds(rgbds, tmp_path):
    # Independent assembler checks every documented base and CB encoding,
    # all nonzero STOP paddings, plus signed immediate/relative edge cases.
    inputs = [bytes([op, 0xA5, 0x5A]) for op in range(256)]
    inputs += [bytes([0xCB, op]) for op in range(256)]
    inputs += [bytes([0x10, padding]) for padding in range(256)]
    inputs += [bytes([op, imm]) for op in (0x18, 0x20, 0x28, 0x30, 0x38, 0xE8, 0xF8)
               for imm in (0, 1, 127, 128, 255)]
    position, expected, text = 0x200, bytearray(), ['SECTION "all_opcodes", ROM0[$0200]']
    for raw in inputs:
        insn = sm83.decode(raw, position)
        text.append("    " + insn.text)
        expected.extend(insn.data)
        position += len(insn.data)
    asm = tmp_path / "opcodes.asm"
    asm.write_text("\n".join(text), encoding="utf-8")
    suffix = ".exe" if sys.platform == "win32" else ""
    for command in ([str(rgbds / ("rgbasm" + suffix)), "-o", "opcodes.o", str(asm)],
                    [str(rgbds / ("rgblink" + suffix)), "-o", "opcodes.gb", "opcodes.o"]):
        result = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "opcodes.gb").read_bytes()[0x200:position] == expected


@pytest.mark.parametrize("cgb,banks", [(False, 4), (True, 4), (False, 72)])
def test_clean_standalone_export_is_exact(rgbds, tmp_path, monkeypatch, cgb, banks):
    raw = bytearray(cartridge(cgb=cgb, banks=banks))
    # Exercise a relative PC wrap and deliberately nonstandard global checksum.
    raw[0:2] = bytes.fromhex("18 80")
    raw[0x14E] ^= 1
    base = tmp_path / "owner copy with spaces.gbc"
    base.write_bytes(raw)
    out = tmp_path / "assembly project with spaces"
    manifest = export(raw, out, entries=[gb.Address(0, 0x100), gb.Address(1, 0x4000), gb.Address(2, 0x4000)],
                      ranges=[gb.CodeRange(gb.Address(0, 0), 2), gb.CodeRange(gb.Address(3, 0x4000), 4)])
    assert manifest["assembly_bytes"] + manifest["base_bytes"] == len(raw)
    assert not manifest["rom"]["global_checksum_valid"]
    loop = (out / "src/bank_003_4000.asm").read_text()
    assert ".L4000:" in loop and "jr .L4000" in loop
    # No shell, WSL, compiler suite or Unix tools may be involved in the build.
    monkeypatch.setenv("PATH", str(Path(os.environ["SystemRoot"]) / "System32") if sys.platform == "win32" else "")
    if sys.platform == "win32":
        for name in ("rgbasm.exe", "rgblink.exe"):
            assert (rgbds / name).read_bytes().startswith(b"MZ")
    assert not toolchains.get("rgbds").via_wsl
    result = subprocess.run([sys.executable, "-I", "-S", str(out / "build.py"), str(base), "--rgbds", str(rgbds)],
                            cwd=tmp_path, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    built = json.loads(result.stdout)
    assert built["matched"] and Path(built["output"]).read_bytes() == raw
    assert built["tools"] == ["rgbasm v1.0.4", "rgblink v1.0.4"]


def test_rebuild_rejects_wrong_base_changed_code_size_and_bank(rgbds, tmp_path):
    raw = cartridge()
    base = tmp_path / "base.gb"
    base.write_bytes(raw)
    out = tmp_path / "export"
    export(raw, out, entries=[gb.Address(0, 0x100), gb.Address(2, 0x4000)])
    base.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(BuildError, match="base ROM.*SHA-256"):
        build(out, base, rgbds=rgbds)
    base.write_bytes(raw)
    source = out / "src/bank_002_4000.asm"
    original = source.read_text()
    for wrong in (original.replace("$22", "$23"), original.replace("ret", "ret\n    nop"),
                  original.replace("BANK[$2]", "BANK[$1]")):
        source.write_text(wrong)
        with pytest.raises(BuildError, match="mismatch|failed"):
            build(out, base, rgbds=rgbds)
        assert not (out / "build").exists()
    source.write_text(original)
    matched = build(out, base, rgbds=rgbds)
    assert Path(matched["output"]).read_bytes() == raw
    with pytest.raises(BuildError, match="overwrite"):
        build(out, base, rgbds=rgbds, output=base)
    with pytest.raises(BuildError, match="overwrite"):
        build(out, base, rgbds=rgbds, output=out / "README.md")


def test_rgbds_registry_has_native_pinned_builds(monkeypatch):
    tc = toolchains.get("rgbds")
    assert tc.kind == "tool" and tc.arch == "sm83"
    assert tc.parts_for("linux-x86_64") and tc.parts_for("windows-x86_64")
    assert not tc.requires and all(len(p["sha256"]) == 64 for p in tc.parts)
    monkeypatch.setattr(toolchains, "current_platform", lambda: "windows-x86_64")
    assert tc.supported and not tc.via_wsl
