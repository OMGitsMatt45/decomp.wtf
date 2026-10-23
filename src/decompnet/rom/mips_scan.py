"""Generic MIPS frame/call placement used by PlayStation disc overlays."""
import collections
import struct
JR_RA = 0x03E00008
BLOCK = 0x400
REGIONS = ((0x80000000, 0x80200000),)

def _frame(word: int) -> bool:
    return (word & 0xFFFF8000) == 0x27BD8000  # addiu $sp, $sp, -N

def _jal_targets(words: tuple[int, ...], region: int = 0x80000000) -> list[int]:
    return [((w & 0x03FFFFFF) << 2) | (region & 0xF0000000) for w in words if (w >> 26) == 3]

def _place(rom: bytes, lo: int, hi: int, floor: int, calls: list[int],
           known: list[tuple[int, int]] = (), regions=REGIONS) -> tuple[int, int, int, int] | None:
    """(start, end, vram, calls that landed on a function start) for one stretch of code, or None."""
    words = struct.unpack(f">{(hi - lo) // 4}I", rom[lo:hi])
    frames = [i * 4 for i, w in enumerate(words) if _frame(w)]
    returns = [i * 4 for i, w in enumerate(words) if w == JR_RA]
    if len(frames) < 8 or len(returns) < 8:
        return None
    best: tuple[int, int, set[int]] | None = None  # (hits, base, the calls' targets)
    for lo_addr, hi_addr in regions:
        own = set(_jal_targets(words, lo_addr))
        votes: collections.Counter = collections.Counter()
        for t in own:
            for f in frames:
                base = t - f
                if lo_addr <= base < hi_addr and base % 4 == 0:
                    votes[base] += 1
        if votes:
            base, hits = votes.most_common(1)[0]
            if best is None or hits > best[0]:
                best = (hits, base, own)
    if best is None:
        return None
    hits, base, own = best  # the address ROM `lo` is loaded at
    if hits < max(8, len(frames) // 10):
        return None
    # the first function: the lowest address called in it (from itself or the known code). Every function returns,
    # so code before `lo` is at most a little: a stray "call" from data words can't drag the start further back.
    back = max(floor, lo - 2 * BLOCK) - lo
    called = [t - base for t in own | set(calls) if back <= t - base < hi - lo
              and not any(a <= t < b for a, b in known)]  # a call into known code says nothing about this one
    first = min([frames[0], *called])
    start = lo + first
    end = lo + returns[-1] + 8  # the last return and its delay slot
    end = min((end + 0xF) & ~0xF, len(rom))
    return (start, end, base + first, hits)
