"""Original MIT two-module ExeFS with independent symbol/relocation expectations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

FIXTURES = Path(__file__).parent / 'fixtures'
SYMBOLS = json.loads((FIXTURES / 'switch-module-symbols.json').read_text())
BASE = 0x7100000000
SDK_BASE = BASE + 0x10000


def module(name, *, gnu_hash=False, sdk_startup=False):
    text, ro, data = [bytearray.fromhex((FIXTURES / ('switch-module-' + name + section + '.hex')).read_text())
                      for section in ('.text', '.rodata', '.data')]
    ro.extend(bytes(0x800 - len(ro)))
    labels = SYMBOLS[name]
    strings = bytearray(b'\0')

    def string(value):
        offset = len(strings); strings.extend(value.encode() + b'\0'); return offset

    if name == 'main':
        entries = [('shared_counter', 0x11, 1, labels['shared_counter'], 8),
                   ('fixture_add', 0x12, 0, 0, 0), ('optional', 0x20, 0, 0, 0),
                   ('main_init', 0x02, 1, labels['main_init'], 20)]
        relocs = [(labels['got_sdk'], (2 << 32) | 1026, 0),
                  (labels['main_array'], 1027, labels['main_init']),
                  (labels['weak_slot'], (3 << 32) | 257, 9)]
        tags = [(1, string('fixture-sdk')), (14, string('fixture-main')),
                (25, labels['main_array']), (27, 8), (36, 0x1580), (35, 8), (37, 8)]
        struct.pack_into('<Q', ro, 0x580, labels['relative_result'])
    else:
        entries = [('fixture_add', 0x12, 1, labels['fixture_add'], 20),
                   ('shared_counter', 0x11, 0, 0, 0), ('sdk_init', 0x02, 1, labels['sdk_init'], 20)]
        relocs = [(labels['counter_ptr'], (2 << 32) | 1025, 0),
                  (labels['sdk_array'], 1027, labels['sdk_init'])]
        tags = [(14, string('fixture-sdk')), (25, labels['sdk_array']), (27, 8)]
    if sdk_startup:
        if name == 'sdk':
            # Original ABI fixture: call SDK callback, main callback, then
            # return fixture_add(30). Constructors leave shared_counter=12.
            # See fixtures/switch-sdk-start.s for the assembly.
            text.extend(bytes(max(0, 0x1a0 - len(text))))
            struct.pack_into('<8I', text, 0x180, 0xa9bf7bf3, 0xaa0303f3,
                             0xd63f0040, 0xd63f0260, 0xd28003c0, 0x97ffffdb,
                             0xa8c17bf3, 0xd65f03c0)
            entries.append(('_ZN2nn4init5StartEmmPFvvES2_', 0x12, 1, 0x180, 32))
        else:
            # A Nintendo-style DT_INIT owns its init_array. Calling both would
            # run this fixture's main constructor twice and return 47, not 42.
            tags.append((12, labels['main_init']))
    symbol_bytes = bytearray(24)
    for sym_name, info, section, value, size in entries:
        symbol_bytes.extend(struct.pack('<IBBHQQ', string(sym_name), info, 0, section, value, size))
    ro[0x340:0x340 + len(symbol_bytes)] = symbol_bytes
    ro[0x500:0x500 + len(strings)] = strings
    count = len(entries) + 1
    if gnu_hash:
        hash_bytes = struct.pack('<IIIIQ', 1, 1, 1, 0, 0) + struct.pack('<I', 1)
        hash_bytes += struct.pack('<' + str(count - 1) + 'I', *([2] * (count - 2) + [3]))
        hash_tag = 0x6ffffef5
    else:
        hash_bytes = struct.pack('<II', 1, count) + struct.pack('<I', 1) + bytes(count * 4)
        hash_tag = 4
    ro[0x300:0x300 + len(hash_bytes)] = hash_bytes
    for i, reloc in enumerate(relocs):
        struct.pack_into('<QQq', ro, 0x200 + i * 24, *reloc)
    tags += [(5, 0x1500), (10, len(strings)), (6, 0x1340), (11, 24), (hash_tag, 0x1300),
             (7, 0x1200), (8, len(relocs) * 24), (9, 24), (0, 0)]
    for i, tag in enumerate(tags):
        struct.pack_into('<QQ', ro, i * 16, *tag)
    return pack_module(text, ro, data)


def pack_module(text, ro, data):
    raw = bytearray(0x100)
    raw[:4] = b'NSO0'
    struct.pack_into('<I', raw, 0xc, 0x38)
    struct.pack_into('<I', raw, 0x3c, 0x100)
    raw[0x40:0x60] = hashlib.sha256(bytes(text) + bytes(ro) + bytes(data)).digest()
    for i, (offset, payload) in enumerate(((0, text), (0x1000, ro), (0x2000, data))):
        struct.pack_into('<III', raw, 0x10 + i * 16, len(raw), offset, len(payload))
        struct.pack_into('<I', raw, 0x60 + 4 * i, len(payload))
        raw[0xa0 + i * 32:0xc0 + i * 32] = hashlib.sha256(payload).digest()
        raw.extend(payload)
    return bytes(raw)


def segments(raw):
    parts = []
    for i in range(3):
        offset, _, size = struct.unpack_from('<III', raw, 0x10 + i * 16)
        parts.append(bytearray(raw[offset:offset + size]))
    return parts


def fixture(root, *, gnu_hash=False, sdk_startup=False):
    root = Path(root); root.mkdir(parents=True)
    for name in ('main', 'sdk'):
        (root / name).write_bytes(module(name, gnu_hash=gnu_hash, sdk_startup=sdk_startup))
    npdm = bytearray(0x80); npdm[:4] = b'META'
    struct.pack_into('<I', npdm, 0x1c, 0x10000)
    (root / 'main.npdm').write_bytes(npdm)
    return root


def expected_images(root):
    """Apply only this fixture's known relocations; no production linker reuse."""
    from decompnet.switch_native.media import load
    main = bytearray(load(Path(root) / 'main', include_image=True)['image'])
    sdk = bytearray(load(Path(root) / 'sdk', include_image=True)['image'])
    for offset, value in [(0x2080, SDK_BASE + SYMBOLS['sdk']['fixture_add']),
                          (0x2088, BASE + 0x2008), (0x2090, BASE + SYMBOLS['main']['main_init']), (0x2098, 9)]:
        struct.pack_into('<Q', main, offset, value)
    struct.pack_into('<Q', sdk, 0x2000, BASE + 0x2000)
    struct.pack_into('<Q', sdk, 0x2008, SDK_BASE + SYMBOLS['sdk']['sdk_init'])
    return bytes(main), bytes(sdk)


def reference(root):
    """Run original fixture code in Unicorn with independent known SVC replies."""
    import unicorn as uc
    from unicorn import arm64_const as arm
    machine = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
    for base, image in zip((BASE, SDK_BASE), expected_images(root)):
        machine.mem_map(base, len(image)); machine.mem_write(base, image)
    stack, heap, tls = 0x7200000000, 0x7300000000, 0x7400000000
    for base, size in ((stack, 0x10000), (heap, 0x400000), (tls, 0x1000)):
        machine.mem_map(base, size)
    handles = {}; calls = {}; ipc_calls = 0; debug = bytearray()

    def get(n): return machine.reg_read(arm.UC_ARM64_REG_X0 + n)
    def put(n, value): machine.reg_write(arm.UC_ARM64_REG_X0 + n, value)

    def svc(mu, number, data):
        nonlocal ipc_calls
        pc = mu.reg_read(arm.UC_ARM64_REG_PC)
        word = int.from_bytes(mu.mem_read(pc - 4, 4), 'little')
        imm = word >> 5 & 0xffff
        calls[str(imm)] = calls.get(str(imm), 0) + 1
        if imm == 1:
            if get(1) == 0x200000: put(0, 0); put(1, heap)
            else: put(0, 0xca01); put(1, 0)
        elif imm == 0x25:
            assert get(1) == 0xffff8000
            put(0, 0); put(1, 0x51)
        elif imm == 0x10: put(0, 0)
        elif imm == 0x1f:
            assert bytes(mu.mem_read(get(1), 4)) == b'sm:\0'
            handles[0x100] = 'sm'; put(0, 0); put(1, 0x100)
        elif imm in (0x21, 0x22):
            h = get(0) if imm == 0x21 else get(2)
            if h not in handles:
                put(0, 0xe401); return
            address = tls if imm == 0x21 else get(0)
            request = bytes(mu.mem_read(address, 256))
            special = bool(int.from_bytes(request[4:8], 'little') >> 31)
            cmif = 32 if special else 16
            assert request[cmif:cmif + 4] == b'SFCI'
            command, token = struct.unpack_from('<II', request, cmif + 8)
            moved = 0; payload = b''
            if handles[h] == 'sm':
                if command == 1:
                    assert request[cmif + 16:cmif + 24] == b'set\0\0\0\0\0'
                    handles[0x101] = 'set'; moved = 0x101
                else: assert command == 0
            else:
                assert command == 0
                payload = b'en-US\0\0\0'
            response = bytearray(256)
            struct.pack_into('<II', response, 0, 0, (8 + len(payload) // 4) | (0x80000000 if moved else 0))
            if moved: struct.pack_into('<II', response, 8, 0x20, moved)
            response[16:20] = b'SFCO'
            struct.pack_into('<III', response, 20, 0, 0, token)
            response[32:32 + len(payload)] = payload
            mu.mem_write(address, bytes(response)); put(0, 0); ipc_calls += 1
        elif imm == 0x16:
            assert get(0) in handles
            del handles[get(0)]; put(0, 0)
        elif imm == 0x1e: put(0, 777)  # Excluded from equality: native host time is monotonic.
        elif imm == 0x27:
            debug.extend(mu.mem_read(get(0), get(1))); put(0, 0)
        else: raise AssertionError('unexpected fixture SVC ' + hex(imm))

    machine.hook_add(uc.UC_HOOK_INTR, svc)
    for entry in (SDK_BASE + SYMBOLS['sdk']['sdk_init'], BASE + SYMBOLS['main']['main_init'], BASE):
        for i in range(29): machine.reg_write(arm.UC_ARM64_REG_X0 + i, 0)
        machine.reg_write(arm.UC_ARM64_REG_X29, 0); machine.reg_write(arm.UC_ARM64_REG_X30, 0)
        machine.reg_write(arm.UC_ARM64_REG_NZCV, 0)
        machine.reg_write(arm.UC_ARM64_REG_SP, stack + 0x10000)
        machine.reg_write(arm.UC_ARM64_REG_TPIDRRO_EL0, tls)
        machine.reg_write(arm.UC_ARM64_REG_TPIDR_EL0, tls)
        machine.reg_write(arm.UC_ARM64_REG_X1, 1)
        machine.emu_start(entry, 0, count=10000)
        assert machine.reg_read(arm.UC_ARM64_REG_PC) == 0
    return dict(x=[machine.reg_read(arm.UC_ARM64_REG_X0 + i) for i in range(29)] +
                   [machine.reg_read(arm.UC_ARM64_REG_X29), machine.reg_read(arm.UC_ARM64_REG_X30)],
                data=[bytes(machine.mem_read(base + 0x2000, size)) for base, size in ((BASE, 128), (SDK_BASE, 16))],
                svc_counts=calls, ipc_calls=ipc_calls, debug=bytes(debug))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--gnu-hash', action='store_true')
    args = parser.parse_args()
    fixture(args.output, gnu_hash=args.gnu_hash)


if __name__ == '__main__':
    main()
