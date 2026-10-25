"""Streaming Heartbeat HBD block inventory and bounded member authoring.

Unknown sectors, STR sectors and original block locations remain opaque. A
member is addressed by its archive sector and table index, never a guessed name.
"""

import hashlib
import struct

from .errors import RomError
from . import psx_lzss


def upload_rectangle(stored, decoded, destination, flags, kind):
    """Type 1 packs x/y/width in +8, height across +12 and +8's top bits.

    DQVII's loader at 0x80076C78 unpacks these into a GPU upload RECT.
    The high byte at +13 is a separate encoding field and must be zero here.
    """
    if kind != 1 or flags >> 8:
        return None
    x, y, width = destination & 1023, destination >> 10 & 1023, destination >> 20 & 1023
    height = (flags & 255) | (destination >> 30 << 8)
    if not width or not height or x + width > 1024 or y + height > 512 or stored != decoded or stored != width * height * 2:
        return None
    return {"x": x, "y": y, "width_words": width, "height": height}


def block(read, size, sector):
    at = sector * 2048
    if not 0 <= at <= size - 16:
        return None
    head = read(at, 16)
    count, sectors, payload, reserved = struct.unpack("<4I", head)
    # US DQVII disc two stores 1 here; disc one stores 0. Preserve this tag.
    if reserved not in (0, 1) or not 1 <= count <= 1000 or not 1 <= sectors <= 16384 or at + sectors * 2048 > size:
        return None
    table_size = 16 + count * 16
    if (table_size + payload + 2047) // 2048 != sectors:
        return None
    table = read(at + 16, count * 16)
    members, cursor = [], at + table_size
    for index in range(count):
        stored, decoded, unknown, flags, kind = struct.unpack_from("<IIIHH", table, index * 16)
        if stored > 16 << 20 or decoded > 16 << 20 or cursor + stored > at + sectors * 2048:
            return None
        rectangle = upload_rectangle(stored, decoded, unknown, flags, kind)
        members.append({"index": index, "offset": cursor, "stored_size": stored, "size": decoded,
                        "unknown": unknown, "flags": flags, "type": kind,
                        "codec": "hbd-lzss" if flags == 0x500 else "raw" if rectangle or flags == 0 and kind != 1 else "unknown",
                        **({"upload": rectangle} if rectangle else {})})
        cursor += stored
    if cursor != at + table_size + payload:
        return None
    return {"sector": sector, "sectors": sectors, "payload_size": payload, "disc_tag": reserved, "members": members}


def inventory(read, size):
    if size % 2048 or size > 1 << 30:
        raise RomError("Heartbeat archives require whole sectors and at most 1 GiB")
    blocks, census, opaque, covered = [], {}, 0, 0
    # Scan every boundary: a video/opaque run can separate valid block groups.
    for sector in range(size // 2048):
        head = read(sector * 2048, 4)
        if head[1:] != bytes(3) or not head[0]:
            continue
        item = block(read, size, sector)
        if item is None:
            continue
        if sector < covered:
            raise RomError("ambiguous overlapping Heartbeat block headers")
        opaque += sector - covered
        covered = sector + item["sectors"]
        blocks.append(item)
        for member in item["members"]:
            entry = census.setdefault(str(member["type"]), {"members": 0, "compressed": 0, "unknown_codec": 0})
            entry["members"] += 1
            entry["compressed"] += member["codec"] == "hbd-lzss"
            entry["unknown_codec"] += member["codec"] == "unknown"
    opaque += size // 2048 - covered
    if not blocks:
        raise RomError("no structurally valid Heartbeat archive blocks found")
    return {"format": "hbd", "size": size, "blocks": blocks, "type_census": census, "opaque_sectors": opaque}


def decoded(read, member):
    data = read(member["offset"], member["stored_size"])
    if len(data) != member["stored_size"]:
        raise RomError("truncated Heartbeat member")
    if member["codec"] == "hbd-lzss":
        return psx_lzss.decode(data, member["size"])
    if member["codec"] != "raw":
        raise RomError("unknown Heartbeat member flags or raw size; loader review required")
    size = member["size"]
    if size <= len(data) <= size + 3 and not any(data[size:]):
        return data[:size]
    # Some uncompressed records declare a larger runtime allocation. Return
    # stored bytes, without inventing missing data or zero-filling that hint.
    return data


def replace(read, size, sector, replacements):
    item = block(read, size, sector)
    if item is None or set(replacements) - set(range(len(item["members"]))):
        raise RomError("choose an existing Heartbeat block and member index")
    original = read(sector * 2048, item["sectors"] * 2048)
    header_size = 16 + len(item["members"]) * 16
    table, payload, changes = bytearray(original[16:header_size]), bytearray(), []
    for member in item["members"]:
        index = member["index"]
        old = read(member["offset"], member["stored_size"])
        stored = old
        if index in replacements:
            data = replacements[index]
            baseline = decoded(read, member)
            if data != baseline:
                if member.get("upload") and len(data) != member["stored_size"]:
                    raise RomError("Heartbeat GPU uploads must retain their original rectangle and byte length")
                stored = psx_lzss.encode(data) if member["codec"] == "hbd-lzss" else data
                decoded_size = len(data)
                if member["codec"] == "raw":
                    if member["size"] > member["stored_size"]:
                        if len(data) != len(baseline):
                            raise RomError("resizing a raw Heartbeat allocation requires loader review")
                        decoded_size = member["size"]
                    else:
                        stored = data + bytes(-len(data) % 4)
                if member["codec"] == "hbd-lzss" and psx_lzss.decode(stored, len(data)) != data:
                    raise RomError("Heartbeat recompression verification failed")
                struct.pack_into("<II", table, index * 16, len(stored), decoded_size)
                changes.append({"index": index, "size": len(data), "stored_size": len(stored),
                                "sha256": hashlib.sha256(data).hexdigest()})
        payload += stored
    if not changes:
        return original, []
    end, old_end = header_size + len(payload), header_size + item["payload_size"]
    if end > len(original) or any(original[old_end:max(old_end, end)]):
        raise RomError("Heartbeat member growth exceeds its original zero-padded block; sector table review required")
    if (end + 2047) // 2048 != item["sectors"]:
        raise RomError("Heartbeat replacement changes the block's sector count; sector table review required")
    result = bytearray(original)
    result[16:header_size] = table
    result[header_size:end] = payload
    if end < old_end:
        result[end:old_end] = bytes(old_end - end)
    struct.pack_into("<I", result, 8, len(payload))
    # Preserve the block's sector count and position, and all unknown header words.
    return bytes(result), changes
