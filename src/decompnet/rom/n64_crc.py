"""N64 cartridge CRC1/CRC2 for the standard CIC checksum families."""

import struct
import zlib

SEEDS = {6101: 0xF8CA4DDC, 6102: 0xF8CA4DDC, 6103: 0xA3886759, 6105: 0xDF26F436, 6106: 0x1FEA617A}
BOOT_CRC = {0x6170A4A1: 6101, 0x90BB6CB5: 6102, 0x0B050EE0: 6103, 0x98BC2C86: 6105, 0xACC8580A: 6106}


def calculate(image, cic):
    if cic not in SEEDS or len(image) < 0x101000:
        raise ValueError("N64 CIC checksums need a supported CIC and the full 1 MiB checksum region")
    t1 = t2 = t3 = t4 = t5 = t6 = SEEDS[cic]
    mask = 0xFFFFFFFF
    for at in range(0x1000, 0x101000, 4):
        value = int.from_bytes(image[at:at + 4], "big")
        total = (t6 + value) & mask
        t4 = (t4 + int(total < t6)) & mask
        t6 = total
        t3 ^= value
        rotate = value & 31
        rotated = ((value << rotate) | (value >> ((32 - rotate) & 31))) & mask
        t5 = (t5 + rotated) & mask
        t2 ^= rotated if t2 > value else t6 ^ value
        extra = int.from_bytes(image[0x750 + (at & 255):0x754 + (at & 255)], "big") if cic == 6105 else t5
        t1 = (t1 + (extra ^ value)) & mask
    if cic == 6103:
        return ((t6 ^ t4) + t3) & mask, ((t5 ^ t2) + t1) & mask
    if cic == 6106:
        return (t6 * t4 + t3) & mask, (t5 * t2 + t1) & mask
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def identify(image, selected=None):
    if len(image) < 0x101000:
        raise ValueError("N64 CIC checksums need the full 1 MiB checksum region")
    known = BOOT_CRC.get(zlib.crc32(image[0x40:0x1000]))
    if selected is not None:
        if selected not in SEEDS:
            raise ValueError("choose CIC 6101, 6102, 6103, 6105 or 6106")
        if known is not None and SEEDS[selected] != SEEDS[known]:
            raise ValueError("the selected CIC differs from the original IPL3 fingerprint")
        return selected
    if known is not None:
        return known
    stored = struct.unpack_from(">2I", image, 0x10)
    for cic in (6102, 6103, 6105, 6106):
        if calculate(image, cic) == stored:
            return cic
    raise ValueError("the cartridge CIC is unverified; supply --cic from your hardware/layout analysis")


def update(image, cic):
    result = bytearray(image)
    struct.pack_into(">2I", result, 0x10, *calculate(image, cic))
    return bytes(result)
