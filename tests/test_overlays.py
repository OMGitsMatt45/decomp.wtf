"""PlayStation overlays (rom/overlays.py): code in other files of a disc, placed at the address it's loaded at from
its own calls, and split with the program, as a segment of its own."""

import struct

from decompnet.rom import overlays, split

NOP, JR_RA = 0, 0x03E00008


def _overlay(base: int, count: int) -> bytes:
    """`count` little functions at `base` (little-endian), each calling the next."""
    words = []
    for i in range(count):
        callee = base + ((i + 1) % count) * 32
        words += [0x27BDFFE8, 0xAFBF0014, 0x0C000000 | ((callee >> 2) & 0x03FFFFFF), NOP, 0x8FBF0014, 0x27BD0018,
                  JR_RA, NOP]
    return struct.pack(f"<{len(words)}I", *words)


def _resident_exe() -> bytes:
    """A complete PS-X EXE, without needing a period compiler to build a fixture."""
    header = bytearray(0x800)
    header[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", header, 0x10, 0x80010000, 0, 0x80010000, 0x800)
    return bytes(header) + _overlay(0x80010000, 40).ljust(0x800, b"\0")


def test_an_overlay_is_placed_at_its_load_address():
    data = bytes(64) + _overlay(0x80100040, 60)  # a little header before its code, as overlay files often have
    assert overlays.place(data, "psx", [(0x80010000, 0x80050000)]) == (0x80100000, 64)
    assert overlays.place(data, "psx", [(0x800F0000, 0x80120000)]) is None  # over the resident program: no


def test_ps2_elf_overlays_say_where_they_go():
    code = _overlay(0x00400000, 40)
    phoff = 52
    elf = bytearray(b"\x7fELF\x01\x01\x01" + bytes(9))
    elf += struct.pack("<HHIIIIIHHHHHH", 2, 8, 1, 0x00400000, phoff, 0, 0, 52, 32, 1, 0, 0, 0)
    elf += struct.pack("<8I", 1, 0x100, 0x00400000, 0x00400000, len(code), len(code), 5, 0x10)
    elf += bytes(0x100 - len(elf)) + code
    assert overlays._elf_segments(bytes(elf)) == [(0x00400000, code)]
    irx = bytearray(elf)
    irx[16:18] = struct.pack("<H", 0xFF80)  # an IOP module: relocatable, left out
    assert overlays._elf_segments(bytes(irx)) is None


def test_overlays_are_split_with_the_program(tmp_path):
    (tmp_path / "game.exe").write_bytes(_resident_exe())
    # two overlays that load at the same address (only one is in memory at a time)
    found = [("battle", _overlay(0x80180000, 30), 0x80180000, 0), ("field", _overlay(0x80180000, 20), 0x80180000, 0)]
    res = split.split_rom(tmp_path, "game.exe", log=lambda *_: None, overlays=found)
    battle = [f for f in res.functions if f.segment == "ovl_battle"]
    field = [f for f in res.functions if f.segment == "ovl_field"]
    assert len(battle) == 30 and len(field) == 20
    assert len({f.name for f in battle + field}) == 50  # same addresses, names of their own
    for functions in (battle, field):
        by_address = {f.vram: f for f in functions}
        expected = {0x80180000 + i * 32 for i in range(len(functions))}
        assert set(by_address) == expected
        for i, address in enumerate(sorted(expected)):
            callee = 0x80180000 + ((i + 1) % len(functions)) * 32
            call = by_address[address].lines[2]
            assert call.mnemonic == "jal" and call.operands == by_address[callee].name
    assert res.image == "game.overlays.exe"


def test_namespaced_overlay_local_jumps_preserve_targets_and_draft_labels(tmp_path):
    from decompnet.app.engine import RomNetwork
    from decompnet.rom import match

    listing = tmp_path / "overlay.s"
    listing.write_text("""glabel func_ovl_init_8014C58C
/* 000000 8014C58C 65310508 */ j .Lovl_init_8014C594
/* 000004 8014C590 00000000 */ nop
.Lovl_init_8014C594:
/* 000008 8014C594 0800E003 */ jr $ra
/* 00000C 8014C598 00000000 */ nop
""")
    function = split.parse_function(listing, "ovl_init", False)
    assert function.labels == {0x8014C594}
    assert function.lines[0].operands == ".L8014C594"
    source = RomNetwork._asm_source(function)
    assert "j          .L8014C594" in source and ".L8014C594:" in source
    function.lines[0].operands = ".Lovl_init_8014C594"
    target = match.target_from_split(function, lambda _: None, False)
    assert target.relocs == [(0, 4, 0x8014C594)]


def _iso(files: dict[str, bytes]) -> bytes:
    """The smallest ISO 9660 image the disc reader takes: a volume descriptor, a root directory, the files."""
    def both16(v):
        return struct.pack("<H", v) + struct.pack(">H", v)

    def both32(v):
        return struct.pack("<I", v) + struct.pack(">I", v)

    def record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
        rec = bytes([0, 0]) + both32(lba) + both32(size) + bytes(7) + bytes([2 if is_dir else 0, 0, 0]) + both16(1) \
            + bytes([len(name)]) + name
        rec += bytes(len(rec) % 2)
        return bytes([len(rec)]) + rec[1:]

    lba = 19
    places = {}
    for name, data in files.items():
        places[name] = (lba, len(data))
        lba += -(-len(data) // 2048)
    root = record(b"\0", 18, 2048, True) + record(b"\1", 18, 2048, True)
    for name, (at, size) in places.items():
        root += record(f"{name};1".encode(), at, size, False)
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[156:156 + 34] = record(b"\0", 18, 2048, True)
    image = bytearray(16 * 2048) + pvd + bytearray(b"\xffCD001\x01".ljust(2048, b"\0")) + bytearray(root.ljust(2048, b"\0"))
    for name, data in files.items():
        image += data + bytes(-len(data) % 2048)
    return bytes(image)


def test_a_disc_with_an_overlay_imports_both(tmp_path):
    from decompnet.app.engine import RomNetwork

    disc = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\DEMOQ_PS1.EXE;1\r\n", "DEMOQ_PS1.EXE": _resident_exe(),
                 "BATTLE.BIN": bytes(64) + _overlay(0x80180040, 40), "MUSIC.VAB": bytes(range(256)) * 32})
    (tmp_path / "game.iso").write_bytes(disc)
    net = RomNetwork(tmp_path / "app.db", tmp_path)
    said = []
    slug = net.import_rom(tmp_path / "game.iso", confirmed=True, log=said.append)
    assert any("overlay on the disc: battle at 0x80180000" in s for s in said), said
    rows = net.store.all("SELECT name, vram FROM functions WHERE project_id=?", net.project_row(slug)["id"])
    in_overlay = [r for r in rows if 0x80180000 <= r["vram"] < 0x80181000]
    assert len(in_overlay) == 40 and len(rows) > 40  # the program's functions and the overlay's
