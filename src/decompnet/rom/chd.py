"""CHD disc images (MAME's "Compressed Hunks of Data", version 5): what many people keep their PlayStation discs as.

A CHD is the disc cut into hunks (here 8 CD frames of 2352 bytes + 96 of subcode each), every hunk compressed on
its own (LZMA, zlib; FLAC for audio), with a map saying where each hunk is and how it's stored (compressed with one
of four codecs, stored as is, or a copy of another hunk), itself Huffman-coded. `Chd` reads it like a file of the
uncompressed disc, decompressing only the hunks that are read: the app never needs the whole disc in memory.

Written from the format as libchdr (BSD-3-Clause) implements it. Only what the app needs: version 5, the CD codecs
(cdlz, cdzl, cdfl), and lzma, zlib for DVD images. All decoded bytes, including
audio, subcode and restored sector parity, are checked against hunk CRCs.
"""

from __future__ import annotations

import lzma
import binascii
import hashlib
import struct
import zlib
from pathlib import Path

from .n64 import RomError

MAGIC = b"MComprHD"
CD_FRAME, CD_DATA, CD_SUB = 2448, 2352, 96
# map entry compression types
TYPE_0, TYPE_3, NONE, SELF, PARENT, RLE_SMALL, RLE_LARGE = 0, 3, 4, 5, 6, 7, 8
SELF_0, SELF_1, PARENT_SELF, PARENT_0, PARENT_1 = 9, 10, 11, 12, 13


def is_chd(head: bytes) -> bool:
    return head[:8] == MAGIC


class _Bits:
    """MSB-first bit reader; past the end it reads zeros."""

    def __init__(self, data: bytes, strict=False):
        self.data, self.pos, self.strict = data, 0, strict  # pos in bits

    def peek(self, n: int) -> int:
        if n == 0:
            return 0
        byte, bit = divmod(self.pos, 8)
        width = (bit + n + 7) // 8
        chunk = int.from_bytes(self.data[byte:byte + width].ljust(width, b"\0"), "big")
        return (chunk >> (width * 8 - bit - n)) & ((1 << n) - 1)

    def read(self, n: int) -> int:
        if n < 0 or self.strict and self.pos + n > len(self.data) * 8:
            raise RomError("this CHD's map is truncated")
        v = self.peek(n)
        self.pos += n
        return v


class _Huffman:
    """libchdr's canonical Huffman decoder, with the tree imported in its RLE form (as the CHD map stores it)."""

    def __init__(self, bits: _Bits, numcodes: int = 16, maxbits: int = 8):
        self.maxbits = maxbits
        width = 5 if maxbits >= 16 else 4 if maxbits >= 8 else 3
        lengths: list[int] = []
        while len(lengths) < numcodes:
            n = bits.read(width)
            if n > maxbits:
                raise RomError("this CHD's Huffman tree is damaged")
            if n != 1:
                lengths.append(n)
                continue
            n = bits.read(width)
            if n > maxbits:
                raise RomError("this CHD's Huffman tree is damaged")
            if n == 1:
                lengths.append(1)
            else:
                lengths += [n] * (bits.read(width) + 3)
        if len(lengths) != numcodes:
            raise RomError("this CHD's map is damaged")
        single = lengths.count(1) == 1 and sum(bool(n) for n in lengths) == 1
        if not single and sum(1 << (maxbits - n) for n in lengths if n) != 1 << maxbits:
            raise RomError("this CHD's Huffman tree is incomplete or oversubscribed")
        histo = [0] * 33
        for n in lengths:
            histo[n] += 1
        start = 0
        for length in range(32, 0, -1):  # canonical codes, longest first
            nxt = (start + histo[length]) >> 1
            histo[length], start = start, nxt
        self.lookup = [0] * (1 << maxbits)
        for code, n in enumerate(lengths):
            if n:
                value = histo[n]
                histo[n] += 1
                shift = maxbits - n
                for i in range(value << shift, (value + 1) << shift):
                    self.lookup[i] = (code << 5) | n

    def decode(self, bits: _Bits) -> int:
        entry = self.lookup[bits.peek(self.maxbits)]
        if not entry & 0x1F:
            raise RomError("this CHD's Huffman code is invalid")
        bits.read(entry & 0x1F)
        return entry >> 5


class Chd:
    """A CHD v5 image, read as the disc it holds (seek/read/tell, like a file)."""

    def __init__(self, path: Path | str):
        self.f = open(path, "rb")
        try:
            self._open()
        except BaseException:
            self.f.close()
            raise

    def _open(self):
        self.f.seek(0, 2)
        self.physical_size = self.f.tell()
        self.f.seek(0)
        head = self._read(124)
        self.header = head
        if not is_chd(head) or int.from_bytes(head[8:12], "big") != 124:
            raise RomError("this isn't a CHD image")
        version = struct.unpack(">I", head[12:16])[0]
        if version != 5:
            raise RomError(f"this CHD is version {version}: convert it with `chdman copy` (version 5), or use the .bin/.cue")
        self.codecs = [head[16 + 4 * i:20 + 4 * i] for i in range(4)]
        self.logical = struct.unpack(">Q", head[32:40])[0]
        map_offset = struct.unpack(">Q", head[40:48])[0]
        if not 124 <= map_offset <= self.physical_size:
            raise RomError("this CHD's map offset is outside the image")
        self.hunkbytes, self.unitbytes = struct.unpack(">II", head[56:64])
        if not 0 < self.hunkbytes <= 16 << 20 or not 0 < self.unitbytes <= self.hunkbytes or not 0 < self.logical <= 16 << 30:
            raise RomError("invalid CHD logical, hunk or unit size")
        if any(head[84 + 20:84 + 40]):  # parent SHA-1: it only holds what differs from another image
            raise RomError("this CHD needs its parent image (a delta of another CHD): use a standalone one")
        self.hunks = -(-self.logical // self.hunkbytes)
        if self.hunks > 1 << 20:
            raise RomError("CHD map exceeds the supported hunk count")
        self.crcs = []
        self.map = self._read_map(map_offset) if any(any(codec) for codec in self.codecs) else None
        self.raw_map = None
        if self.map is None:
            # v5 uncompressed maps contain one big-endian hunk block number
            # per logical hunk. Block zero represents a zero-filled hunk.
            self.f.seek(map_offset)
            raw_map = self._read(self.hunks * 4)
            if len(raw_map) != self.hunks * 4:
                raise RomError("this CHD's uncompressed map is truncated")
            self.raw_map = struct.unpack(f">{self.hunks}I", raw_map)
            if any(block and block * self.hunkbytes + self.hunkbytes > self.physical_size for block in self.raw_map):
                raise RomError("this CHD's uncompressed hunk is truncated")
        self.metadata = self._metadata(int.from_bytes(head[48:56], "big"))
        if any(head[84:104]) and overall_sha1(head[64:84], self.metadata) != head[84:104]:
            raise RomError("this CHD's metadata SHA-1 differs")
        self.pos = 0
        self._cache: dict[int, bytes] = {}

    def _read(self, length):
        if not 0 <= length <= self.physical_size - self.f.tell():
            raise RomError("this CHD is truncated")
        data = self.f.read(length)
        if len(data) != length:
            raise RomError("this CHD is truncated")
        return data

    def _metadata(self, offset):
        entries, seen, total = [], set(), 0
        while offset:
            if not 124 <= offset <= self.physical_size - 16:
                raise RomError("this CHD's metadata offset is outside the image")
            if offset in seen or len(seen) >= 10000:
                raise RomError("this CHD's metadata chain is damaged")
            seen.add(offset)
            self.f.seek(offset)
            head = self._read(16)
            length = int.from_bytes(head[5:8], "big")
            total += length
            if total > 16 << 20:
                raise RomError("this CHD's metadata exceeds 16 MiB")
            entries.append((head[:4], head[4], self._read(length)))
            offset = int.from_bytes(head[8:16], "big")
        return entries

    def _read_map(self, offset: int) -> list[tuple[int, int, int]]:
        """(type, length, offset) per hunk."""
        self.f.seek(offset)
        hdr = self._read(16)
        mapbytes = struct.unpack(">I", hdr[0:4])[0]
        first = int.from_bytes(hdr[4:10], "big")
        lengthbits, selfbits, parentbits = hdr[12], hdr[13], hdr[14]
        if lengthbits > 24 or selfbits > 32 or parentbits > 48 or mapbytes > self.hunks * 16 + 256:
            raise RomError("this CHD's map dimensions are invalid")
        bits = _Bits(self._read(mapbytes), strict=True)
        huff = _Huffman(bits)
        types, last, rep = [], 0, 0
        for _ in range(self.hunks):
            if rep:
                types.append(last)
                rep -= 1
                continue
            v = huff.decode(bits)
            if v == RLE_SMALL:  # this hunk and `rep` more are like the last one
                rep = 2 + huff.decode(bits)
                types.append(last)
            elif v == RLE_LARGE:
                rep = 2 + 16 + (huff.decode(bits) << 4)
                rep += huff.decode(bits)
                types.append(last)
            else:
                last = v
                types.append(v)
        if rep:
            raise RomError("this CHD's map run exceeds its hunk count")
        out, cur, last_self, last_parent, rawmap = [], first, 0, 0, bytearray()
        for n, t in enumerate(types):
            length, off, crc = 0, cur, 0
            if t <= TYPE_3:
                length = bits.read(lengthbits)
                cur += length
                crc = bits.read(16)
            elif t == NONE:
                length = self.hunkbytes
                cur += length
                crc = bits.read(16)
            elif t == SELF:
                last_self = off = bits.read(selfbits)
            elif t == PARENT:
                last_parent = off = bits.read(parentbits)
            elif t in (SELF_0, SELF_1):
                last_self += t == SELF_1
                t, off = SELF, last_self
            elif t == PARENT_SELF:
                t, off = PARENT, n * self.hunkbytes // self.unitbytes
                last_parent = off
            elif t in (PARENT_0, PARENT_1):
                if t == PARENT_1:
                    last_parent += self.hunkbytes // self.unitbytes
                t, off = PARENT, last_parent
            else:
                raise RomError("this CHD's map has an invalid compression type")
            if t <= NONE and (not length or off + length > self.physical_size):
                raise RomError("this CHD's compressed hunk is truncated")
            if t == SELF and off >= self.hunks:
                raise RomError("this CHD's self-reference is outside its map")
            out.append((t, length, off))
            self.crcs.append(crc)
            rawmap += bytes([t]) + length.to_bytes(3, "big") + off.to_bytes(6, "big") + crc.to_bytes(2, "big")
        if binascii.crc_hqx(rawmap, 0xFFFF) != int.from_bytes(hdr[10:12], "big"):
            raise RomError("this CHD's map checksum differs")
        return out

    # ------------------------------------------------------------------ hunks

    def hunk(self, n: int) -> bytes:
        if n in self._cache:
            return self._cache[n]
        data = self._hunk(n, 0)
        if len(self._cache) > 64:
            self._cache.pop(next(iter(self._cache)))
        self._cache[n] = data
        return data

    def _hunk(self, n: int, depth: int) -> bytes:
        if not 0 <= n < self.hunks:
            raise RomError("a CHD hunk is outside the image")
        if self.map is None:  # uncompressed image
            block = self.raw_map[n]
            if not block:
                return bytes(self.hunkbytes)
            self.f.seek(block * self.hunkbytes)
            data = self.f.read(self.hunkbytes)
            if len(data) != self.hunkbytes:
                raise RomError("this CHD's uncompressed hunk is truncated")
            return data
        t, length, off = self.map[n]
        if t == SELF:
            if depth > 8 or off == n:
                raise RomError("this CHD's map is damaged")
            return self.hunk(off) if off in self._cache else self._hunk(off, depth + 1)
        if t == PARENT:
            raise RomError("this CHD needs its parent image")
        self.f.seek(off)
        raw = self._read(length)
        if t == NONE:
            data = raw
        else:
            try:
                data = self._decode(self.codecs[t], raw)
            except RomError:
                raise
            except (zlib.error, lzma.LZMAError, IndexError, ValueError) as exc:
                raise RomError("this CHD's compressed hunk is damaged") from exc
        if len(data) != self.hunkbytes or binascii.crc_hqx(data, 0xFFFF) != self.crcs[n]:
            raise RomError("this CHD's hunk checksum differs")
        return data

    def _decode(self, codec: bytes, src: bytes) -> bytes:
        size = self.hunkbytes
        if codec == b"zlib":
            return _inflate(src, size)
        if codec == b"lzma":
            return _lzma(src, size)
        if codec in (b"cdlz", b"cdzl", b"cdfl"):
            if size % CD_FRAME:
                raise RomError("a CD CHD hunk must contain whole frames")
            frames = size // CD_FRAME
            n_len = 2 if size < 65536 else 3
            ecc = (frames + 7) // 8
            if codec == b"cdfl":
                from .chd_flac import decode
                data, end = decode(src, frames * CD_DATA // 4)
            else:
                base_len = int.from_bytes(src[ecc:ecc + n_len], "big")
                start = ecc + n_len
                if not 0 < base_len < len(src) - start:
                    raise RomError("invalid CHD CD codec lengths")
                end = start + base_len
                data = _lzma(src[start:end], frames * CD_DATA) if codec == b"cdlz" else _inflate(src[start:end], frames * CD_DATA)
            sub = _inflate(src[end:], frames * CD_SUB)
            out = bytearray()
            for i in range(frames):
                sector = data[i * CD_DATA:(i + 1) * CD_DATA]
                if codec != b"cdfl" and src[i // 8] & (1 << (i % 8)):
                    from .psx_sector import restore_parity
                    sector = restore_parity(b"\0" + b"\xff" * 10 + b"\0" + sector[12:])
                out += sector + sub[i * CD_SUB:(i + 1) * CD_SUB]
            return bytes(out)
        raise RomError(f"this CHD uses the {codec.decode('ascii', 'replace')} codec, which decomp.wtf can't read "
                       "yet: convert it with `chdman extractcd` to .bin/.cue")

    # ------------------------------------------------------------------ file-like

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence not in (0, 1, 2):
            raise RomError("invalid CHD seek mode")
        self.pos = pos if whence == 0 else self.pos + pos if whence == 1 else self.logical + pos
        if self.pos < 0:
            raise RomError("negative CHD seek")
        return self.pos

    def tell(self) -> int:
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self.logical - self.pos
        n = min(n, max(0, self.logical - self.pos))
        out = bytearray()
        while n > 0 and self.pos < self.logical:
            h, at = divmod(self.pos, self.hunkbytes)
            chunk = self.hunk(h)[at:at + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def close(self) -> None:
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _lzma(src: bytes, size: int) -> bytes:
    """CHD's LZMA: raw LZMA1 (lc 3, lp 0, pb 2), no end marker, decoded to the hunk's size."""
    dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2,
                                                            "dict_size": 1 << 24}])
    result = dec.decompress(src, max_length=size)
    if len(result) != size:
        raise RomError("this CHD's LZMA hunk has the wrong decoded size")
    return result


def _inflate(src, size):
    decoder = zlib.decompressobj(-15)
    result = decoder.decompress(src, size + 1)
    if len(result) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise RomError("this CHD's deflate hunk has the wrong decoded size")
    return result


def overall_sha1(raw_sha1, metadata):
    hashed = sorted(tag + hashlib.sha1(data).digest() for tag, flags, data in metadata if flags & 1)
    return hashlib.sha1(raw_sha1 + b"".join(hashed)).digest()
