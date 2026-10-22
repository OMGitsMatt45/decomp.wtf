"""Read TWL containers without decrypting, authenticating or rebuilding them.

Offsets follow the public DS/DSi header format, also documented by ds-rom's
raw::Header. Stored program bytes and authentication metadata remain opaque.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

from ..forks.scratch_dsd import crc16


@dataclass(frozen=True)
class Region:
    name: str
    offset: int
    size: int
    load_address: int | None = None
    entrypoint: int | None = None

    @property
    def end(self) -> int:
        return self.offset + self.size


def _range(name: str, offset: int, size: int, file_size: int, *, minimum: int = 0) -> Region:
    if size and (offset < minimum or offset + size > file_size):
        raise ValueError(f"{name} range is outside the ROM or overlaps its header")
    return Region(name, offset, size)


def parse_header(header: bytes, file_size: int) -> dict:
    """Validate stored ranges; header CRC validation is not TWL authentication."""
    if len(header) < 0x1000 or file_size < len(header):
        raise ValueError("the TWL header is truncated")
    if header[0x12] not in (2, 3):
        raise ValueError("expected a DSi-enhanced or DSi-exclusive container")
    if crc16(header[:0x15E]) != struct.unpack_from("<H", header, 0x15E)[0]:
        raise ValueError("the DS/TWL header checksum is invalid")
    u32 = lambda offset: struct.unpack_from("<I", header, offset)[0]
    header_size, declared_size = u32(0x84), u32(0x210)
    if not 0x1000 <= header_size <= file_size:
        raise ValueError("the declared TWL header size is invalid")
    if not header_size <= declared_size <= file_size:
        raise ValueError("the declared TWL image size is outside the ROM")
    regions = [Region("header", 0, header_size)]
    for name, offset in (("arm9", 0x20), ("arm7", 0x30), ("arm9i", 0x1C0), ("arm7i", 0x1D0)):
        stored, entry, load, size = struct.unpack_from("<4I", header, offset)
        if not size:
            continue
        region = _range(name, stored, size, declared_size, minimum=header_size)
        if load + size > 0x100000000:
            raise ValueError(f"{name} load address overflows the address space")
        # The second word of ARM9i/ARM7i descriptors is reserved, not an entrypoint.
        if name in ("arm9", "arm7") and not load <= (entry & ~1) < load + size:
            raise ValueError(f"{name} entrypoint is outside its loaded program")
        regions.append(Region(name, region.offset, region.size, load, entry if not name.endswith("i") else None))
    for name, offset in (("digest_ds_area", 0x1E0), ("digest_dsi_area", 0x1E8),
                         ("digest_sector_table", 0x1F0), ("digest_block_table", 0x1F8)):
        start, size = struct.unpack_from("<2I", header, offset)
        if size:
            regions.append(_range(name, start, size, declared_size, minimum=header_size))
    modcrypt = []
    for index, offset in enumerate((0x220, 0x228), 1):
        start, size = struct.unpack_from("<2I", header, offset)
        if size:
            modcrypt.append(_range(f"modcrypt_{index}", start, size, declared_size, minimum=header_size))
    flags = header[0x1C]
    return {"platform": "dsi", "kind": "enhanced" if header[0x12] == 2 else "exclusive",
            "title": header[:12].split(b"\0", 1)[0].decode("ascii", "replace"),
            "game_code": header[12:16].decode("ascii", "replace"), "header_size": header_size,
            "declared_size": declared_size, "file_size": file_size,
            "modcrypt_enabled": bool(flags & 2), "modcrypt_debug_key": bool(flags & 4),
            "modcrypt_ranges": [asdict(region) for region in modcrypt],
            "authentication_verified": False, "header_crc_valid": True,
            "regions": [asdict(region) | {"modcrypted": bool(flags & 2) and any(
                region.offset < area.end and area.offset < region.end for area in modcrypt)} for region in regions]}


def inspect(path: Path) -> dict:
    with path.open("rb") as stream:
        header = stream.read(0x1000)
        info = parse_header(header, os.fstat(stream.fileno()).st_size)
    return info


def extract_stored(path: Path, destination: Path) -> dict:
    """Copy stored ranges and the full header to a new private directory.

    Neither digest/HMAC/signature verification nor Modcrypt decryption is implied.
    Enclosing digest ranges may overlap programs; each gets its own stored copy.
    """
    if destination.exists():
        raise FileExistsError(f"output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with path.open("rb") as source:
        header = source.read(0x1000)
        info = parse_header(header, os.fstat(source.fileno()).st_size)
        with tempfile.TemporaryDirectory(prefix=".twl-extract-", dir=destination.parent) as temporary:
            stage = Path(temporary) / "output"
            stage.mkdir(mode=0o700)
            for region in info["regions"]:
                filename = f"{region['name']}.stored.bin"
                target = stage / filename
                source.seek(region["offset"])
                digest, remaining = hashlib.sha256(), region["size"]
                with target.open("xb") as output:
                    target.chmod(0o600)
                    while remaining:
                        block = source.read(min(1 << 20, remaining))
                        if not block:
                            raise ValueError("ROM changed or was truncated during extraction")
                        output.write(block)
                        digest.update(block)
                        remaining -= len(block)
                region.update({"file": filename, "sha256": digest.hexdigest()})
            manifest = stage / "container.json"
            manifest.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
            manifest.chmod(0o600)
            stage.rename(destination)
    return info
