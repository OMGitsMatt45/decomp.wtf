"""Lossless CHD v5 rewrite with fixed logical geometry and retained metadata.

Use the standard raw-deflate codec for whole hunks, including all 96 subcode
bytes. A simple canonical map deliberately favors portability over the smallest
possible container. Original matching builds still retain the input unchanged.
"""

import binascii
import hashlib
from pathlib import Path
import struct
import zlib

from .chd import Chd, MAGIC, overall_sha1
from .n64 import RomError


def rewrite(original, output, patches):
    """Write and independently reread output; patches address decoded bytes."""
    original, output = Path(original), Path(output)
    if original.resolve() == output.resolve() or output.exists() and output.samefile(original):
        raise RomError("a changed CHD must use a separate output path")
    try:
        return _rewrite(original, output, patches)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def _rewrite(original, output, patches):
    by_hunk, previous = {}, 0
    with Chd(original) as source:
        if source.unitbytes != 2448 or source.hunkbytes % 2448 or source.logical % 2448 or source.hunkbytes >= 1 << 24:
            raise RomError("modified CD CHDs require whole 2448-byte frames")
        for offset, data in sorted(patches.items()):
            if not data or offset < previous or offset + len(data) > source.logical:
                raise RomError("changed CHD patches overlap or exceed the logical image")
            previous = offset + len(data)
            at = 0
            while at < len(data):
                hunk, inside = divmod(offset + at, source.hunkbytes)
                count = min(len(data) - at, source.hunkbytes - inside)
                by_hunk.setdefault(hunk, []).append((inside, data[at:at + count]))
                at += count

        def patched(number, data):
            result = bytearray(data)
            for offset, replacement in by_hunk.get(number, []):
                result[offset:offset + len(replacement)] = replacement
            return bytes(result)

        raw_map, types, fields = bytearray(), bytearray(), bytearray()
        original_sha, raw_sha, decoded_sha256 = hashlib.sha1(), hashlib.sha1(), hashlib.sha256()
        # Four-bit map symbols followed by 24-bit compressed lengths and CRC16.
        # Padding the symbol stream once at the end keeps every field byte aligned.
        with output.open("w+b") as destination:
            destination.write(bytes(124))
            for number in range(source.hunks):
                old = source.hunk(number)
                data = patched(number, old)
                valid = min(source.hunkbytes, source.logical - number * source.hunkbytes)
                original_sha.update(old[:valid])
                raw_sha.update(data[:valid])
                decoded_sha256.update(data[:valid])
                compressor = zlib.compressobj(level=9, wbits=-15)
                encoded = compressor.compress(data) + compressor.flush()
                kind = 0
                if len(encoded) >= len(data):
                    kind, encoded = 4, data
                offset = destination.tell()
                destination.write(encoded)
                crc = binascii.crc_hqx(data, 0xFFFF)
                raw_map += bytes([kind]) + len(encoded).to_bytes(3, "big") + offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
                types.append(kind)
                if kind == 0:
                    fields += len(encoded).to_bytes(3, "big")
                fields += crc.to_bytes(2, "big")
            expected = source.header[64:84]
            if any(expected) and original_sha.digest() != expected:
                raise RomError("original CHD raw SHA-1 differs from its decoded frames")
            overall = source.header[84:104]
            if any(overall) and overall_sha1(source.header[64:84], source.metadata) != overall:
                raise RomError("original CHD metadata SHA-1 differs")
            # Every metadata tag, flag, payload and ordering survives. Only the
            # linked-list offsets change when the physical compressed size does.
            metadata_at = destination.tell() if source.metadata else 0
            for index, (tag, flags, data) in enumerate(source.metadata):
                next_at = destination.tell() + 16 + len(data) if index + 1 < len(source.metadata) else 0
                destination.write(tag + bytes([flags]) + len(data).to_bytes(3, "big") + next_at.to_bytes(8, "big") + data)
            map_at = destination.tell()
            # Use an even number of symbols so the following 40/16-bit fields
            # can be assembled as bytes; an odd count needs a four-bit shift.
            symbols = bytes((types[i] << 4) | (types[i + 1] if i + 1 < len(types) else 0) for i in range(0, len(types), 2))
            if len(types) % 2:
                # The last nibble of symbols belongs before fields, not after.
                combined = symbols[:-1] + bytes([(symbols[-1] & 0xF0) | (fields[0] >> 4)]) + bytes(
                    ((fields[i - 1] & 15) << 4) | (fields[i] >> 4) for i in range(1, len(fields))) + bytes([(fields[-1] & 15) << 4])
            else:
                combined = symbols + fields
            encoded_map = bytes([0x44]) * 8 + combined  # 16 code lengths, all four bits
            destination.write(struct.pack(">I", len(encoded_map)) + (124).to_bytes(6, "big") +
                              binascii.crc_hqx(raw_map, 0xFFFF).to_bytes(2, "big") + bytes([24, 0, 0, 0]) + encoded_map)
            head = bytearray(124)
            head[:8] = MAGIC
            struct.pack_into(">II", head, 8, 124, 5)
            head[16:20] = b"zlib"
            struct.pack_into(">QQQII", head, 32, source.logical, map_at, metadata_at, source.hunkbytes, source.unitbytes)
            head[64:84] = raw_sha.digest()
            head[84:104] = overall_sha1(raw_sha.digest(), source.metadata)
            destination.seek(0)
            destination.write(head)
        # Check the actual file, not only the intended encoder input. Compare
        # every decoded byte, including audio, padding and subcode, to its source.
        with Chd(output) as check:
            if (check.logical, check.hunkbytes, check.unitbytes, check.metadata) != (
                    source.logical, source.hunkbytes, source.unitbytes, source.metadata):
                raise RomError("changed CHD lost its geometry or track metadata")
            verified = hashlib.sha1()
            for number in range(source.hunks):
                data = check.hunk(number)
                if data != patched(number, source.hunk(number)):
                    raise RomError("changed CHD failed lossless decoded-byte verification")
                verified.update(data[:min(source.hunkbytes, source.logical - number * source.hunkbytes)])
            if verified.digest() != check.header[64:84]:
                raise RomError("changed CHD SHA-1 verification failed")
        return {"kind": "chd", "logical_size": source.logical, "hunk_size": source.hunkbytes,
                "unit_size": source.unitbytes, "decoded_sha256": decoded_sha256.hexdigest(),
                "metadata_sha256": hashlib.sha256(b"".join(tag + bytes([flags]) + len(data).to_bytes(3, "big") + data
                                                          for tag, flags, data in source.metadata)).hexdigest(),
                "lossless_verified": True}


def verify_geometry(original, output, report):
    """Aggregate builds permit container-size changes only with CHD verification."""
    if report.get("kind") != "chd" or report.get("lossless_verified") is not True:
        raise RomError("a changed CHD requires a lossless build report")
    with Chd(original) as source, Chd(output) as result:
        if (source.logical, source.hunkbytes, source.unitbytes, source.metadata) != (
                result.logical, result.hunkbytes, result.unitbytes, result.metadata):
            raise RomError("modified CHD changed its pinned geometry or track metadata")
        if (report["logical_size"], report["hunk_size"], report["unit_size"]) != (
                result.logical, result.hunkbytes, result.unitbytes):
            raise RomError("modified CHD geometry differs from its build report")
        sha = hashlib.sha256()
        while data := result.read(1 << 20):
            sha.update(data)
        if sha.hexdigest() != report["decoded_sha256"]:
            raise RomError("modified CHD decoded hash differs from its build report")
