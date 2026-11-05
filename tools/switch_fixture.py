"""Original Switch NSO/NRO fixture, with independent instruction/data expectations."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

BASE = 0x7100000000
FIXTURE = Path(__file__).parent / 'fixtures'


def fixture(*, nro=False, compressed=False):
    text = bytes.fromhex((FIXTURE / 'switch-cpu.hex').read_text())
    ro = b'Original Switch CPU fixture\0'
    data = bytes(64)
    if nro:
        raw = bytearray(0x2040)
        raw[:len(text)] = text
        raw[0x10:0x14] = b'NRO0'
        struct.pack_into('<II', raw, 0x18, len(raw), 0)
        for i, (off, payload) in enumerate(((0, text), (0x1000, ro), (0x2000, data))):
            struct.pack_into('<II', raw, 0x20 + i * 8, off, len(payload))
        struct.pack_into('<I', raw, 0x38, 0x100)
        raw[0x1000:0x1000 + len(ro)] = ro
        return bytes(raw)
    raw = bytearray(0x100)
    raw[:4] = b'NSO0'
    struct.pack_into('<I', raw, 0xc, 0x38 | (7 if compressed else 0))
    struct.pack_into('<I', raw, 0x3c, 0x100)
    raw[0x40:0x60] = hashlib.sha256(b'decomp.wtf original Switch fixture').digest()
    for i, (off, payload) in enumerate(((0, text), (0x1000, ro), (0x2000, data))):
        packed = payload
        if compressed:
            # Independently encode a literal-only raw LZ4 block, no library.
            n = len(payload)
            packed = bytes([min(n, 15) << 4])
            if n >= 15:
                count = n - 15
                packed += b'\xff' * (count // 255) + bytes([count % 255])
            packed += payload
        struct.pack_into('<III', raw, 0x10 + i * 0x10, len(raw), off, len(payload))
        struct.pack_into('<I', raw, 0x60 + i * 4, len(packed))
        raw[0xa0 + 32 * i:0xc0 + 32 * i] = hashlib.sha256(payload).digest()
        raw.extend(packed)
    return bytes(raw)


def conditional_target_fixture():
    """An indirect computed branch enters a conditional branch's fallthrough."""
    raw = bytearray(fixture(nro=True))
    struct.pack_into('<I', raw, 0, 0x14000020)  # b entry at 0x80
    text_size = struct.unpack_from('<I', raw, 0x24)[0]
    for offset in range(0x80, text_size, 4):
        struct.pack_into('<I', raw, offset, 0xd503201f)  # nop
    # adr x9, entry; mov x10, #16; add x9, x9, x10; cbz xzr, dispatch;
    # fallthrough: mov x0, #42; ret; dispatch: br x9.
    words = (0x10000009, 0xd280020a, 0x8b0a0129, 0xb400007f,
             0xd2800540, 0xd65f03c0, 0xd61f0120)
    struct.pack_into('<7I', raw, 0x80, *words)
    return bytes(raw)


def changed_code_fixture():
    """Overwrite a discovered entry in guest memory, then branch to it."""
    raw = bytearray(conditional_target_fixture())
    # adr x9, target (0xa0); str wzr, [x9]; br x9; padding;
    # target: mov x0, #42; ret. The written word is not the translated code.
    words = [0x10000109, 0xb900013f, 0xd61f0120] + [0xd503201f] * 5
    words += [0xd2800540, 0xd65f03c0]
    struct.pack_into('<10I', raw, 0x80, *words)
    return bytes(raw)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--nro', action='store_true')
    parser.add_argument('--compressed', action='store_true')
    args = parser.parse_args()
    with args.output.open('xb') as stream:
        stream.write(fixture(nro=args.nro, compressed=args.compressed))


def reference(path):
    """Execute the original machine code in independent Unicorn, for tests only."""
    import unicorn as uc
    from unicorn import arm64_const as arm
    from decompnet.switch_native.media import load
    loaded = load(path, include_image=True)
    mu = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
    mu.mem_map(BASE, len(loaded['image']))
    mu.mem_write(BASE, loaded['image'])
    stack = 0x7200000000
    mu.mem_map(stack, 0x10000)
    mu.reg_write(arm.UC_ARM64_REG_SP, stack + 0x10000)
    mu.reg_write(arm.UC_ARM64_REG_CPACR_EL1, 0x300000)
    mu.emu_start(BASE, 0, count=10000)
    if mu.reg_read(arm.UC_ARM64_REG_PC) != 0:
        raise ValueError('original fixture did not return within the reference instruction bound')
    vectors = [mu.reg_read(arm.UC_ARM64_REG_Q0 + i) for i in range(32)]
    data = loaded['segments'][2]
    return dict(x=[mu.reg_read(arm.UC_ARM64_REG_X0 + i) for i in range(29)] +
                   [mu.reg_read(arm.UC_ARM64_REG_X29), mu.reg_read(arm.UC_ARM64_REG_X30)],
                nzcv=mu.reg_read(arm.UC_ARM64_REG_NZCV),
                v=[[value & ((1 << 64) - 1), value >> 64] for value in vectors],
                data_hex=bytes(mu.mem_read(BASE + data['offset'], min(data['size'], 64))).hex())


if __name__ == '__main__':
    main()
