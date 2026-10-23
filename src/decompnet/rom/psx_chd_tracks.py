"""CHD CD track geometry for reviewed first-data-track growth."""

import re

from .n64 import RomError


def tracks(source):
    result = []
    for index, (tag, flags, data) in enumerate(source.metadata):
        if tag not in (b"CHT2", b"CHTR"):
            continue
        if tag != b"CHT2":
            raise RomError("CHD track growth requires CHT2 track metadata")
        match = re.fullmatch(rb"TRACK:(\d+) TYPE:(\S+) SUBTYPE:(\S+) FRAMES:(\d+) PREGAP:(\d+) PGTYPE:(\S+) PGSUB:(\S+) POSTGAP:(\d+)\x00?", data)
        if not match or int(match[1]) != len(result) + 1:
            raise RomError("unsupported or unordered CHD track metadata")
        frames = int(match[4])
        if not frames:
            raise RomError("empty CHD track")
        result.append({"metadata_index": index, "type": match[2], "frames": frames,
                       "padded": (frames + 3) // 4 * 4})
    if not result or sum(t["padded"] for t in result) * 2448 != source.logical or \
            result[0]["type"] not in (b"MODE1_RAW", b"MODE2_RAW") or any(t["type"] != b"AUDIO" for t in result[1:]):
        raise RomError("CHD growth requires one first raw data track and optional audio tracks")
    return result


def metadata(source, new_frames):
    info = tracks(source)
    if new_frames < info[0]["frames"]:
        raise RomError("CHD data-track growth cannot remove original frames")
    result = list(source.metadata)
    index = info[0]["metadata_index"]
    tag, flags, data = result[index]
    result[index] = tag, flags, re.sub(rb"(?<= FRAMES:)\d+", str(new_frames).encode(), data, count=1)
    return result


def check_moved_subcode(source, cut):
    """Opaque subcode with absolute Q timing cannot be moved without retiming."""
    for start in range(cut * 2448, source.logical, source.hunkbytes):
        source.seek(start)
        data = source.read(min(source.hunkbytes, source.logical - start))
        for offset in range(2352, len(data), 2448):
            if any(data[offset:offset + 96]):
                raise RomError("moving CHD audio with raw subcode requires mastering/protection review")


def image(source, cut, new_frames, patches, raw_sector):
    info = tracks(source)
    if cut != info[0]["padded"]:
        raise RomError("CHD data-track insertion boundary differs")
    extra = (new_frames + 3) // 4 * 4 - cut
    check_moved_subcode(source, cut)
    first_frames = info[0]["frames"]
    # Original track padding becomes usable data space. Require zero padding
    # before promoting it to ordinary, error-corrected data frames.
    for frame in range(first_frames, cut):
        source.seek(frame * 2448)
        if any(source.read(2448)):
            raise RomError("nonzero original CHD track padding requires review")
    def read(offset, count):
        result = bytearray()
        while count:
            frame, inside = divmod(offset, 2448)
            take = min(count, 2448 - inside)
            if frame in patches:
                if frame < first_frames:
                    from .psx_sector import replace
                    source.seek(frame * 2448)
                    data = replace(source.read(2448), patches[frame])
                else:
                    data = raw_sector(patches[frame], frame)
            elif first_frames <= frame < new_frames:
                data = raw_sector(bytes(2048), frame)
            elif new_frames <= frame < cut + extra:
                data = bytes(2448)  # four-frame CHD track alignment
            else:
                old = frame if frame < cut else frame - extra
                source.seek(old * 2448)
                data = source.read(2448)
            result += data[inside:inside + take]
            offset += take
            count -= take
        return bytes(result)
    return source.logical + extra * 2448, metadata(source, new_frames), read
