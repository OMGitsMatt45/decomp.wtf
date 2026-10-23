"""Bounded generic gzip streams; code classification stays in the native analyzer."""

import zlib

MAX_OUTPUT = 32 * 1024 * 1024
MAX_INPUT = 8 * 1024 * 1024


def stream(image, offset):
    decoder = zlib.decompressobj(31)
    chunks, total, used = [], 0, 0
    available = min(len(image) - offset, MAX_INPUT)
    try:
        while used < available and not decoder.eof:
            end = min(used + 65536, available)
            decoded = decoder.decompress(memoryview(image)[offset + used:offset + end], MAX_OUTPUT - total + 1)
            chunks.append(decoded)
            total += len(decoded)
            used = end
            if total > MAX_OUTPUT:
                return None
        if decoder.eof:
            return b"".join(chunks), used - len(decoder.unused_data)
    except zlib.error:
        pass
    return None


def code_blocks(image):
    from . import _n64_native as native
    at = 0
    while (at := image.find(b"\x1f\x8b\x08", at)) >= 0:
        decoded = stream(image, at)
        if decoded is None:
            at += 3
            continue
        data, used = decoded
        # The native classifier expects a cartridge header. A zero prefix
        # gives it the entire decoded payload without interpreting data here.
        if len(data) >= 0x1000 and native.find_segments(bytes(0x1000) + data, []):
            yield at, data
        at += used
