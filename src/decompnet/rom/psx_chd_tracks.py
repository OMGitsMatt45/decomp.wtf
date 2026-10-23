"""CHD CD track geometry for reviewed first-data-track growth."""

from bisect import bisect_right
import hashlib
import re

from .errors import RomError


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
                       "padded": (frames + 3) // 4 * 4, "number": int(match[1]), "subtype": match[3],
                       "pregap": int(match[5]), "pgtype": match[6], "pgsub": match[7], "postgap": int(match[8])})
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


def audio_retimer(source, new_frames):
    """Map CHD frame offsets to actual CD time, excluding four-frame padding."""
    from .psx_subcode import retime
    info = tracks(source)
    starts, layout, chd_at, disc_at = [], [], 0, 150
    shift = new_frames - info[0]["frames"]
    for item in info:
        stored_gap = item["pregap"] if item["pgtype"].startswith(b"V") else 0
        if stored_gap > item["frames"]:
            raise RomError("stored CHD pregap exceeds its track")
        if not stored_gap:
            disc_at += item["pregap"]
        starts.append(chd_at)
        layout.append((item, disc_at, stored_gap))
        chd_at += item["padded"]
        disc_at += item["frames"] + item["postgap"]
    def frame(number, data):
        if not any(data[2352:]):
            return data
        index = bisect_right(starts, number) - 1
        item, absolute, gap = layout[index]
        offset = number - starts[index]
        if offset >= item["frames"]:
            return data  # CHD alignment padding is not part of the CD timeline.
        in_gap = offset < gap
        subtype = item["pgsub"] if in_gap else item["subtype"]
        if index == 0 or info[0]["pregap"] or subtype != b"RW_RAW" or in_gap and item["pgtype"] != b"VAUDIO":
            raise RomError("moving this raw subcode geometry requires mastering/protection review")
        relative = gap - offset if in_gap else offset - gap
        return data[:2352] + retime(data[2352:], shift, number=item["number"], absolute=absolute + offset,
                                    relative=relative, pregap=in_gap)
    return frame


def retimed_tail_digest(source, new_frames):
    """Preflight every retained audio frame and hash its intended retimed bytes."""
    cut = tracks(source)[0]["padded"]
    retime = audio_retimer(source, new_frames)
    sha = hashlib.sha256()
    for start in range(cut * 2448, source.logical, 256 * 2448):
        source.seek(start)
        data = source.read(min(256 * 2448, source.logical - start))
        for offset in range(0, len(data), 2448):
            sha.update(retime((start + offset) // 2448, data[offset:offset + 2448]))
    return source.logical - cut * 2448, sha.hexdigest()


def image(source, cut, new_frames, patches, raw_sector):
    info = tracks(source)
    if cut != info[0]["padded"]:
        raise RomError("CHD data-track insertion boundary differs")
    extra = (new_frames + 3) // 4 * 4 - cut
    retime = audio_retimer(source, new_frames)
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
                if old >= cut:
                    data = retime(old, data)
            result += data[inside:inside + take]
            offset += take
            count -= take
        return bytes(result)
    return source.logical + extra * 2448, metadata(source, new_frames), read
