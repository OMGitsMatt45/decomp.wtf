"""Identify supported cartridges, PlayStation executables and disc images."""

from __future__ import annotations

from dataclasses import dataclass, field

import struct
from pathlib import Path

from . import chd, gba, overlays, ps2, psx
from .. import platforms
from .errors import RomError

PLATFORMS = platforms.NAMES
SMALL = 64 * 1024 * 1024  # ROMs and programs are read whole; disc images are read from disk


@dataclass
class Picked:
    platform: str
    data: bytes  # the supported cartridge image, PS-X EXE or PS2 ELF to split
    filename: str  # name to store it under in the project folder
    info: dict
    big_endian: bool
    overlays: list = field(default_factory=list)  # (name, bytes, load address): code in other files on the disc
    disc: dict | None = None  # PS1 full-disc reconstruction provenance, or an explicit unsupported reason


def _program(data: bytes, name: str = "") -> Picked | None:
    platforms.require(platforms.removed_input(data[:0x440], len(data)), RomError)
    _development_input(data)
    if gba.is_gba(data):
        return Picked("gba", data, "rom.gba", gba.read_info(data), False)
    if data[:8] == b"PS-X EXE":
        exe, info = psx.read_exe(data, name)
        return Picked("psx", exe, "game.exe", info, False)
    if ps2.is_mips_elf(data):
        elf, info = ps2.read_elf(data, name)
        return Picked("ps2", elf, "game.elf", info, False)
    return None


def _development_input(head):
    from ..ctr_native.media import recognizable
    if recognizable(head):
        raise RomError('3DS support is in development. Use decomp pc ctr-inspect or the explicit experimental pc ctr-probe; a playable 3DS game export is not available yet.')


def identify(src: bytes | Path, name: str = "") -> Picked:
    """What the user picked: a ROM or program (bytes or a file), or a disc image (read from the file in place)."""
    if isinstance(src, (str, Path)):
        path = Path(src)
        name = name or path.name
        with path.open('rb') as source:
            head = source.read(0x440)
            platforms.require(platforms.removed_input(head, path.stat().st_size), RomError)
            _development_input(head)
        if path.suffix.lower() == ".cue":
            from . import psx_media
            media = psx_media.cue(path)
            primary = psx_media.inside(path.parent, media["primary"])
            with psx_media.decoded(primary, media) as source:
                picked = _from_disc(source)
            if picked.platform != "psx":
                raise RomError("CUE track-set matching currently requires a PS1 disc")
            if picked.disc.get("supported") and (picked.disc["sector_size"] != media["sector_size"] or
                    picked.disc["skip"] != {"MODE1/2048": 0, "MODE1/2352": 16, "MODE2/2352": 24}[media["mode"]]):
                raise RomError("the CUE data-track mode disagrees with its disc sectors")
            picked.disc = psx_media.wrap(picked.disc, primary, media)
            return picked
        with open(path, "rb") as f:
            head = f.read(8)
        if chd.is_chd(head):  # a compressed disc image: read in place, a hunk at a time
            with chd.Chd(path) as disc:
                if psx.is_disc(disc):
                    picked = _from_disc(disc)
                    if picked.platform == "psx":
                        from .psx_media import wrap
                        picked.disc = wrap(picked.disc, path, {"kind": "chd", "companions": []})
                    return picked
            raise RomError("this CHD doesn't hold a PlayStation disc this app can read")
        if path.stat().st_size <= SMALL:
            return identify(path.read_bytes(), name)
        with open(path, "rb") as f:
            if psx.is_disc(f):
                return _from_disc(f)
        raise RomError("this file is too big for a ROM and isn't a disc image this app can read")
    picked = _program(src, name)
    if picked is not None:
        return picked
    if psx.is_disc(src):
        return _from_disc(src)
    if src[:4] == b"\x7fELF":
        raise RomError("this ELF program isn't for a console decomp.wtf can split from scratch yet")
    raise RomError("pick a supported DS/GBA ROM, a PlayStation 1 or 2 disc image "
                   "(.bin, .iso, .chd) or its program file")


def _from_disc(src) -> Picked:
    raw, boot, platform = psx.from_disc(src)
    picked = _program(raw, boot.rsplit("/", 1)[-1])
    if picked is None:
        raise RomError(f"the disc's program {boot} isn't a PlayStation executable this app can read")
    if picked.platform == "psx":
        main = (picked.info["load"], picked.info["load"] + picked.info["size"] - 0x800)
    else:
        segs = overlays._elf_segments(raw) or []
        main = (min((a for a, _ in segs), default=0), max((a + len(d) for a, d in segs), default=0))
    sources, warning = {}, None
    try:
        picked.overlays = overlays.find(psx._Disc(src), boot, picked.platform, main, sources=sources)
    except (RomError, struct.error, IndexError):  # an odd disc: the program alone still works
        picked.overlays = []
        warning = "the disc filesystem could not be fully inventoried; only the boot program was imported"
    if picked.platform == "psx":
        from .psx_disc import describe
        picked.disc = describe(src, boot, picked.data, picked.overlays, sources)
        if warning:
            picked.disc.update(supported=False, reason=warning)
    return picked
