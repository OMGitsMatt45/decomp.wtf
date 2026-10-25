"""Original stripped EE programs distinguish control flow from embedded data."""
import struct

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native.discovery import discover
from tests.fixtures.ps2_native import BASE, i, program, r


def stripped(words):
    original = bytearray(program()[0])
    # Remove section headers; keep the original executable PT_LOAD envelope.
    struct.pack_into('<I', original, 32, 0)
    struct.pack_into('<3H', original, 46, 0, 0, 0)
    struct.pack_into('<' + 'I' * len(words), original, 0x100, *words)
    return bytes(original)


def addresses(report):
    return {pc for span in report['code_ranges']
        for pc in range(span['address'], span['address'] + span['size'], 4)}


def test_reachable_branches_and_calls_exclude_plausible_embedded_instructions():
    data = stripped([i(0x15, 4, 5, 3), 0, 3 << 26 | (BASE + 32) >> 2, 0,
        r(8, rs=31), 0, 3 << 26 | (BASE + 0x300) >> 2, 0xFFFFFFFF,
        i(9, 0, 2, 7), r(8, rs=31), 0, 3 << 26 | (BASE + 0x400) >> 2])
    report = discover(data)
    assert report['mapping_source'] == 'executable-load-segments'
    assert addresses(report) == {BASE + n for n in (0, 4, 8, 12, 16, 20, 32, 36, 40)}
    assert [s['address'] for s in report['function_seeds']] == [BASE, BASE + 32]
    assert not report['invalid'] and not report['unresolved']
    assert not report['complete_function_map'] and not report['native_game_qualified']


def test_a_branch_target_into_a_delay_slot_still_follows_ordinary_fallthrough():
    report = discover(stripped([i(4, 0, 0, 0), i(9, 0, 2, 1), r(8, rs=31), 0]))
    assert addresses(report) == {BASE + n for n in (0, 4, 8, 12)}


def test_linked_unconditional_branch_follows_callee_and_return_continuation():
    report = discover(stripped([i(1, 0, 17, 3), 0, r(8, rs=31), 0,
        i(9, 0, 2, 5), r(8, rs=31), 0]))
    assert addresses(report) == {BASE + n for n in range(0, 28, 4)}
    assert report['direct_calls'] == [dict(pc=BASE, target=BASE + 16)]


def test_indirect_targets_remain_unresolved_and_are_not_invented():
    report = discover(stripped([r(9, rs=25, rd=31), 0, r(8, rs=31), 0]))
    assert report['unresolved'] == [dict(pc=BASE, kind='indirect-call', register=25)]
    assert addresses(report) == {BASE + n for n in (0, 4, 8, 12)}


def test_jalr_with_zero_link_register_does_not_invent_a_return_path():
    report = discover(stripped([r(9, rs=25, rd=0), 0, 3 << 26 | (BASE + 16) >> 2, 0]))
    assert report['unresolved'] == [dict(pc=BASE, kind='indirect-jump', register=25)]
    assert addresses(report) == {BASE, BASE + 4}


def test_statically_false_likely_branch_annuls_its_delay_slot_and_target():
    report = discover(stripped([i(21, 4, 4, 5), 0xFFFFFFFF, r(8, rs=31), 0,
        0, 0, 3 << 26 | (BASE + 0x300) >> 2, 0]))
    assert addresses(report) == {BASE, BASE + 8, BASE + 12}
    assert report['direct_calls'] == []


def test_statically_false_linked_branch_has_no_callee_seed():
    report = discover(stripped([i(1, 0, 16, 3), 0, r(8, rs=31), 0,
        3 << 26 | (BASE + 0x300) >> 2, 0]))
    assert report['direct_calls'] == []
    assert addresses(report) == {BASE + n for n in (0, 4, 8, 12)}


def test_external_module_call_keeps_the_call_site_and_target():
    report = discover(stripped([3 << 26 | 0x500000 >> 2, 0, r(8, rs=31), 0]))
    assert report['unresolved'] == [dict(pc=BASE, target=0x500000, kind='target-outside-executable')]
    assert report['direct_calls'] == [dict(pc=BASE, target=0x500000)]


def test_adjacent_virtual_code_with_discontinuous_file_offsets_retains_correct_hashes():
    import hashlib
    image = bytearray(program()[0])
    one = struct.pack('<2I', 2 << 26 | (BASE + 8) >> 2, 0)
    two = struct.pack('<2I', r(8, rs=31), 0)
    image[0x100:0x108] = one; image[0x200:0x208] = two
    struct.pack_into('<H', image, 44, 2)
    for index, (offset, address) in enumerate(((0x100, BASE), (0x200, BASE + 8))):
        struct.pack_into('<8I', image, 52 + 32 * index, 1, offset, address, address, 8, 8, 5, 1)
    table = len(image); image.extend(bytes(40))
    for offset, address in ((0x100, BASE), (0x200, BASE + 8)):
        image.extend(struct.pack('<10I', 0, 1, 6, address, offset, 8, 0, 0, 4, 0))
    struct.pack_into('<I', image, 32, table)
    struct.pack_into('<3H', image, 46, 40, 3, 0)
    report = discover(bytes(image))
    assert report['code_ranges'] == [
        dict(address=BASE, size=8, sha256=hashlib.sha256(one).hexdigest()),
        dict(address=BASE + 8, size=8, sha256=hashlib.sha256(two).hexdigest())]


def test_symbol_roots_find_original_functions_and_discovery_is_bounded():
    image, _, entries = program()
    report = discover(image)
    assert {r['address'] for r in report['function_seeds']} == set(entries.values())
    assert report['invalid'] == []
    with pytest.raises(PCError, match='bound'): discover(image, max_instructions=2)
    with pytest.raises(PCError, match='outside'): discover(image, roots=[0x500000])


def test_discovery_rejects_inconsistent_section_mapping():
    original = bytearray(program()[0])
    table = struct.unpack_from('<I', original, 32)[0]
    struct.pack_into('<I', original, table + 40 + 12, BASE + 0x10000)
    with pytest.raises(PCError, match='load mapping'): discover(original)


def test_reserved_extended_section_layout_is_explicitly_unsupported():
    original = bytearray(program()[0]); struct.pack_into('<H', original, 48, 0)
    with pytest.raises(PCError, match='extended section'): discover(original)


def test_cli_static_discovery_reports_limits_without_installing_a_runtime(tmp_path, capsys, monkeypatch):
    import argparse
    import json
    from decompnet import pc_cli
    monkeypatch.setattr('decompnet.toolchains.ensure', lambda *_a, **_k: pytest.fail('inspection must not install tools'))
    original = tmp_path / 'original.elf'; original.write_bytes(stripped([r(8, rs=31), 0]))
    parser = argparse.ArgumentParser()
    pc_cli.add_parser(parser.add_subparsers(dest='action'))
    args = parser.parse_args(['pc', 'ps2-inspect', str(original), '--quick', '--discover-code'])
    assert pc_cli.run(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['input']['identity_verified'] is False
    assert report['program']['code_discovery']['instructions'] == 2
    assert report['program']['code_discovery']['complete_function_map'] is False
    assert report['app_backend_registered'] is False
