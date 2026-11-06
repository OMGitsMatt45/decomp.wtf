"""Desktop exports preserve exact inputs, full runtime provenance and coverage."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from decompnet import pc
from decompnet.switch_native import provider
from decompnet.switch_native.desktop import project, sdk
from tools.switch_fixture import fixture


def test_plain_entry_guard_preserves_guest_fp_and_callbacks_use_host_fp(tmp_path):
    cc = os.environ.get('DECOMP_SWITCH_CC') or shutil.which('clang')
    if not cc:
        pytest.skip('original native entry guard check requires Clang')
    root = sdk.ROOT.parent
    source = Path(__file__).resolve().parents[1] / 'tools/fixtures/switch-entry-guard.c'
    binary = tmp_path / ('entry-guard.exe' if os.name == 'nt' else 'entry-guard')
    command = [cc, '-std=gnu11', '-O1', str(source), '-I', str(sdk.ROOT),
               '-I', str(root / 'vendor/nxport-lifter/runtime'), '-o', str(binary)]
    if os.name != 'nt': command.append('-lm')
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert 'plain entries: 10000; callbacks: 1; FP state preserved' in ran.stdout


@pytest.fixture
def original(tmp_path):
    path = tmp_path / 'owner module.nro'
    path.write_bytes(fixture(nro=True))
    return path


@pytest.fixture(scope='module')
def compiler(tmp_path_factory):
    rustc = os.environ.get('DECOMP_SWITCH_RUSTC') or shutil.which('rustc')
    if not rustc:
        pytest.skip('source emission requires Rust')
    return rustc


@pytest.fixture
def emission_env(monkeypatch, compiler, tmp_path_factory):
    monkeypatch.setenv('DECOMP_SWITCH_RUSTC', compiler)
    if not os.environ.get('DECOMP_SWITCH_BUILD_CACHE'):
        monkeypatch.setenv('DECOMP_SWITCH_BUILD_CACHE', str(tmp_path_factory.getbasetemp() / 'switch-emitter'))


def test_complete_runtime_sources_match_the_pinned_inventory():
    source = sdk.verify()
    assert (source / 'crates/rt/src/services/audio/mixer.rs').is_file()
    assert (source / 'crates/maxwell/src/translate.rs').is_file()


@pytest.mark.parametrize('change', ['edited', 'extra', 'symlink'])
def test_runtime_vendor_mutations_are_rejected_and_preserved(tmp_path, monkeypatch, change):
    origin = sdk.ROOT
    root = tmp_path / 'desktop'; root.mkdir()
    shutil.copyfile(origin / 'runtime-sources.json', root / 'runtime-sources.json')
    source = root.parent / 'vendor/kirikae-src'
    shutil.copytree(sdk.verify(), source)
    monkeypatch.setattr(sdk, 'ROOT', root)
    if change == 'edited':
        modified = source / 'crates/rt/src/process.rs'; modified.write_text('owner edits')
    elif change == 'extra':
        modified = source / 'crates/rt/build.rs'; modified.write_text('owner edits')
    else:
        modified = source / 'linked'
        try:
            modified.symlink_to(tmp_path, target_is_directory=True)
        except OSError as error:
            if getattr(error, 'winerror', None) != 1314:
                raise
            pytest.skip('Windows account cannot create symlinks')
    with pytest.raises(pc.PCError, match='differs from its pin'):
        sdk.verify()
    assert modified.exists()
    if change != 'symlink': assert modified.read_text() == 'owner edits'


def test_desktop_export_is_independent_and_privately_input_bound(original, tmp_path, emission_env):
    raw = original.read_bytes()
    out = tmp_path / 'editable source'
    result = project.export(original, out)
    assert result['integrity_verified'] and not result['gameplay_verified']
    assert not result['presentation_declared']
    manifest = result['manifest']
    assert manifest['inputs'] == [dict(name=original.name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())]
    assert manifest['fallback'] == dict(interpreter=False, runtime_compilation=False)
    assert manifest['qualification']['guest_thread_creation'] is True
    assert manifest['qualification']['retail'] is False
    assert (out / 'sdk/Cargo.lock').is_file()
    assert (out / 'sdk/crates/rt/examples/decomp-graphics.rs').is_file()
    assert original.read_bytes() == raw
    original.unlink()
    assert pc.verify(out)['integrity_verified']
    assert list((out / 'game').glob('guest0_*.c'))


def test_nro_layout_is_rebased_without_changing_original_bytes(original):
    loaded = project.inspect(original, images=True)
    assert loaded['entry'] == 0x08000000
    assert loaded['modules'][0]['base'] == 0x08000000
    assert loaded['modules'][0]['input']['sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert loaded['system_resource_size'] == 0


def test_desktop_export_preserves_npdm_system_resource_size(tmp_path, emission_env):
    from tools.switch_exefs_fixture import fixture as exefs_fixture
    original = exefs_fixture(tmp_path / 'exefs')
    npdm = original / 'main.npdm'
    raw = bytearray(npdm.read_bytes())
    struct.pack_into('<I', raw, 0x14, 0x1000000)
    npdm.write_bytes(raw)

    out = tmp_path / 'source'
    project.export(original, out)

    assert json.loads((out / 'analysis.json').read_text())['system_resource_size'] == 0x1000000
    assert 'sw_system_resource_size(void){return 16777216ull;}' in (out / 'runtime/modules.c').read_text()


@pytest.mark.parametrize('landing_pads', [False, True])
def test_stripped_unwind_entries_are_in_the_export_dispatch_table(tmp_path, emission_env, landing_pads):
    from tests.test_switch_discovery import landing_pad_fixture, original as unwind_fixture

    image, _ = landing_pad_fixture() if landing_pads else unwind_fixture()
    struct.pack_into('<I', image, 0, 0x140000c0)  # b 0x300, skipping metadata
    struct.pack_into('<I', image, 0x300, 0xd65f03c0)  # ret
    image[0x10:0x14] = b'NRO0'
    struct.pack_into('<II', image, 0x18, len(image), 0)
    for i, (offset, size) in enumerate(((0, 0x400), (0x1000, 0x200), (0x2000, 0x80))):
        struct.pack_into('<II', image, 0x20 + 8 * i, offset, size)
    path = tmp_path / 'stripped.nro'; path.write_bytes(image)
    out = tmp_path / 'source'
    project.export(path, out)
    # These roots are neither called nor address-materialized by the program.
    expected = {0x08000200, 0x08000240}
    if landing_pads:
        expected.update((0x08000220, 0x08000228))
    entries = {int(v) for v in (out / 'main-entries.txt').read_text().splitlines()}
    assert expected <= entries
    table = (out / 'game/guest0_table.c').read_text()
    assert all(f'f_{address:x}' in table for address in expected)


def test_computed_branch_can_enter_a_conditional_fallthrough(tmp_path, emission_env):
    from tools.switch_fixture import conditional_target_fixture, reference
    path = tmp_path / 'conditional-target.nro'
    path.write_bytes(conditional_target_fixture())
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    table = (out / 'game/guest0_table.c').read_text()
    assert 'f_8000090' in table


def test_compact_jump_table_can_enter_a_later_partition(tmp_path, emission_env):
    from tools.switch_fixture import compact_table_partition_fixture, reference
    path = tmp_path / 'compact-target.nro'
    path.write_bytes(compact_table_partition_fixture())
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x080000A0 in entries and 0x080000A4 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert 'f_80000a4' in table


@pytest.mark.parametrize(('simd_instruction', 'resolved'), [
    (None, True),
    (0x0e1404d8, True),   # dup v24.2s, v6.s[2]
    (0x1e270358, True),   # fmov s24, w26
    (0x0e143cd8, False),  # umov w24, v6.s[2]
    (0x4e142cd8, False),  # smov x24, v6.s[2]
    (0x1e2600d8, False),  # fmov w24, s6
    (0x1e18fc18, False),  # fcvtzs w24, s0, #1
])
def test_halfword_table_resolves_a_base_from_a_predecessor_partition(tmp_path, emission_env,
                                                                    simd_instruction, resolved):
    from tools.switch_fixture import halfword_table_partition_fixture, reference
    path = tmp_path / 'halfword-target.nro'
    image = bytearray(halfword_table_partition_fixture())
    if simd_instruction is not None:
        # Execute vector-only writes on the way to dispatch. Real clobbers
        # are on an alternate path so the reference can still use the table.
        struct.pack_into('<I', image, 0x90, 0x14000002 if resolved else 0xb5000088)
        struct.pack_into('<I', image, 0x98, simd_instruction)
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x080000A0, 0x080000B8} <= entries and 0x080000BC not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000bc' in table) == resolved
    assert 'f_80000c0' not in table


@pytest.mark.parametrize('call_after_base', [False, True])
def test_halfword_table_caller_saved_base_must_be_defined_after_the_call(tmp_path, emission_env, call_after_base):
    from tools.switch_fixture import caller_saved_halfword_table_fixture, reference
    path = tmp_path / 'caller-saved-table-target.nro'
    path.write_bytes(caller_saved_halfword_table_fixture(call_after_base=call_after_base))
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x080000A0, 0x080000BC} <= entries and 0x080000C0 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000c0' in table) == (not call_after_base)


@pytest.mark.parametrize('unknown_base', [False, True])
def test_backward_byte_table_requires_a_constant_base_on_each_path(tmp_path, emission_env, unknown_base):
    from tools.switch_fixture import backward_byte_table_fixture, reference
    path = tmp_path / 'backward-byte-target.nro'
    path.write_bytes(backward_byte_table_fixture(unknown_base=unknown_base))
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x080000A0, 0x080000C0} <= entries and 0x080000A8 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000a8' in table) == (not unknown_base)


@pytest.mark.parametrize('variant', ['guarded', 'wrong-source', 'skipped-compare', 'operand-entry', 'table-guard-entry'])
def test_backward_halfword_table_checks_every_guard_into_the_w_alias(tmp_path, emission_env, variant):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # CMP W0; B.HI default falls into MOV W8,W0. A distant B.LS enters
    # the same copy and creates a separate partition before the LDRH.
    words = (0x52800020, 0x1000028c, 0x350001e2, 0x35000241, 0x14000003, 0x52800020,
             0xd65f03c0, 0x7100041f, 0x54000128, 0x2a0003e8, 0xb000000b, 0x9100016b,
             0x10ffff29, 0x7868796a, 0x8b0a0929, 0x52800016, 0xd61f0120, 0x52800000,
             0xd65f03c0, 0x52800540, 0xd65f03c0, 0x7100041f, 0x54fffe69, 0x17fffffa)
    struct.pack_into(f'<{len(words)}I', image, 0x80, *words)
    if variant == 'wrong-source':
        struct.pack_into('<I', image, 0xd4, 0x7100043f)  # cmp w1, #1
    if variant == 'skipped-compare':
        struct.pack_into('<I', image, 0x8c, 0x35000261)  # cbnz w1, b.ls
    if variant == 'operand-entry':
        struct.pack_into('<I', image, 0xe0, 0x17fffff5)  # b to the load
    struct.pack_into('<2H', image, 0x1000, 17 if variant == 'table-guard-entry' else 0, 14)
    path = tmp_path / 'backward-halfword.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x08000094 in entries and 0x080000cc not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000cc' in table) == (variant == 'guarded')


@pytest.mark.parametrize(('producer', 'compare', 'alternate', 'resolved'), [
    (0xd2800028, 0xf100091f, 0xd503201f, True),   # full-width guard
    (0xd2800028, 0xf100091f, 0xb4000408, False),  # alternate branch to load
    (0xd2800028, 0xf100091f, 0xb4ffffe8, False),  # alternate branch to b.ls
    (0xd2800028, 0x7100091f, 0xd503201f, False),  # unsupported producer for W guard
    (0xb94000e8, 0x7100091f, 0xd503201f, True),   # ldr w8, [x7] clears the upper bits
    (0xf94000e8, 0x7100091f, 0xd503201f, False),  # ldr x8, [x7] can set upper bits
    (0xb94000e8, 0x7100091f, 0xb4ffffc8, False),  # alternate branch to compare
    (0xb94000e8, 0x7100091f, 0x10ffffcb, False),  # compare address materialized as a root
])
def test_halfword_table_requires_a_unique_proven_taken_guard(tmp_path, emission_env,
                                                            producer, compare, alternate, resolved):
    from tools.switch_fixture import distant_guard_table_fixture, reference
    path = tmp_path / 'distant-guard-target.nro'
    path.write_bytes(distant_guard_table_fixture(producer=producer, compare=compare, alternate=alternate))
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x08000118 in entries and 0x08000120 not in entries
    if alternate == 0x10ffffcb:
        assert 0x08000084 in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_8000120' in table) == resolved


@pytest.mark.parametrize(('scheduled', 'alternate', 'resolved'), [
    (0x390000df, 0xd503201f, True),   # strb wzr, [x6] preserves NZCV and W8
    (0x7200011f, 0xd503201f, False),  # tst w8, #1 sets NZCV
    (0xd2800028, 0xd503201f, False),  # mov x8, #1 overwrites the checked index
    (0x390000df, 0xb4ffffc8, False),  # cbz x8, 0x8c can bypass CMP
])
def test_halfword_table_accepts_scheduled_byte_store_after_taken_guard_compare(
        tmp_path, emission_env, scheduled, alternate, resolved):
    from tools.switch_fixture import reference, scheduled_taken_guard_table_fixture
    path = tmp_path / 'scheduled-taken-guard-target.nro'
    path.write_bytes(scheduled_taken_guard_table_fixture(scheduled=scheduled, alternate=alternate))
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_8000120' in table) == resolved


@pytest.mark.parametrize('variant', ['preserved', 'index-overwrite', 'alternate-entry'])
def test_halfword_table_checks_w_producer_before_scheduled_moves(tmp_path, emission_env, variant):
    from tools.switch_fixture import distant_guard_table_fixture, reference
    image = bytearray(distant_guard_table_fixture(compare=0x7100091f, alternate=0xd503201f))
    struct.pack_into('<I', image, 0, 0x1400001e)  # b 0x78
    struct.pack_into('<I', image, 0x78, 0xd2800021)  # mov x1, #1
    struct.pack_into('<Q', image, 0x1010, 2)
    # The W subtraction clears the upper index bits before the scheduled
    # argument copies. The taken guard is separated from the dispatcher.
    move = 0xaa0103e8 if variant == 'index-overwrite' else 0xaa0003f3
    alternate = 0xb5ffff60 if variant == 'alternate-entry' else 0xd503201f
    struct.pack_into('<9I', image, 0x80, 0xb94000e8, 0x51000508, 0x2a0203f5,
                     0x2a0103f4, move, 0x7100091f, 0x54000349, alternate, 0xd65f03c0)
    path = tmp_path / 'scheduled-guard-moves.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_8000120' in table) == (variant == 'preserved')


@pytest.mark.parametrize(('entrance', 'copy', 'between', 'resolved'), [
    (0xd503201f, 0x2a1503e9, 0xd503201f, True),   # Both paths preserve mov w9, w21.
    (0xb50000e0, 0x2a1503e9, 0xd503201f, False),  # A direct edge bypasses the copy.
    (0xb5000180, 0x2a1503e9, 0xd503201f, False),  # A direct edge bypasses the guard.
    (0xd503201f, 0xaa1503e9, 0xd503201f, False),  # mov x9, x21 can keep high bits.
    (0xd503201f, 0x2a1503e9, 0x52800055, False),  # One path overwrites W21.
    (0xd503201f, 0x2a1503e9, 0x52800049, False),  # One path overwrites W9.
])
def test_halfword_table_requires_zero_extended_alias_on_every_path(tmp_path, emission_env,
                                                                  entrance, copy, between, resolved):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # The two paths join at CMP W21, #2. The checked fallthrough loads an
    # unsigned halfword with X9 and branches across the seeded ADR anchor.
    words = (entrance, 0x52800055, copy, 0xb4000081, between, 0x14000002, 0xd65f03c0,
             0x71000abf, 0x54000188, 0xb000000b, 0x9100016b, 0x100000ac, 0x7869796a,
             0x8b0a098c, 0x52800028, 0xd61f0180, 0xd2800020, 0xd65f03c0, 0xd2800540,
             0xd65f03c0, 0xd2800060, 0xd65f03c0)
    struct.pack_into('<22I', image, 0x80, *words)
    struct.pack_into('<3H', image, 0x1000, 0, 4, 2)
    path = tmp_path / 'copied-index.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x080000C0 in entries and 0x080000C8 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000c8' in table) == resolved


@pytest.mark.parametrize(('checked_index', 'scheduled', 'resolved'), [
    (0x12003d09, (), True),                # and w9, w8, #0xffff
    (0x12003909, (), False),               # and w9, w8, #0x7fff
    (0x12003c09, (), False),               # and w9, w0, #0xffff
    (0x12003d09, (0x390033e8,), True),     # strb w8, [sp, #0xc]
    (0x12003d09, (0x2b1f03ff,), False),    # adds wzr, wzr, wzr
    (0x12003d09, (0x52800048,), False),    # mov w8, #2
])
def test_halfword_table_requires_matching_masked_alias(tmp_path, emission_env, checked_index, scheduled, resolved):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # x8 = 0x10002; cmp (w8 & 0xffff), #2; optional scheduled instruction;
    # b.hi default; mask X8, load an unsigned halfword, and branch to the scaled offset.
    words = (0xd10043ff, 0xd2800048, 0xf2a00028, checked_index, 0x7100093f, *scheduled, 0x54000188,
             0x92403d08, 0xb000000b, 0x9100016b, 0x10000089, 0x7868796a,
             0x8b0a0929, 0xd61f0120, 0xd2800020, 0xd65f03c0, 0xd2800540,
             0xd65f03c0, 0xd2800060, 0xd65f03c0)
    struct.pack_into(f'<{len(words)}I', image, 0x80, *words)
    struct.pack_into('<3H', image, 0x1000, 0, 4, 2)
    path = tmp_path / 'masked-index.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    translation = json.loads((out / 'main-translation.json').read_text())
    assert translation['jump_tables'] == int(resolved)
    assert translation['unresolved_computed'] == int(not resolved)


@pytest.mark.parametrize(('entrance', 'between', 'resolved'), [
    (0xd503201f, 0xd503201f, True),   # Both guards test the same masked alias.
    (0xb40000df, 0xd503201f, False),  # A direct edge enters the second comparison.
    (0xd503201f, 0x52800048, False),  # mov w8, #2 replaces the source.
    (0xd503201f, 0x52800049, False),  # mov w9, #2 replaces the alias.
])
def test_halfword_table_proves_masked_alias_across_an_earlier_guard(tmp_path, emission_env,
                                                                  entrance, between, resolved):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # The earlier guard allows 0..3, but the final guard only allows 0..2.
    # The second case lies after the independently discovered ADR anchor.
    words = (0xd10043ff, 0xd2800048, 0xf2a00028, entrance, 0x12003d09, 0x71000d3f,
             0x390033e8, 0x540001e8, between, 0x7100093f, 0x54000188, 0x92403d08,
             0xb000000b, 0x9100016b, 0x10000089, 0x7868796a, 0x8b0a0929, 0xd61f0120,
             0xd2800020, 0xd65f03c0, 0xd2800540, 0xd65f03c0, 0xd2800060, 0xd65f03c0)
    struct.pack_into('<24I', image, 0x80, *words)
    struct.pack_into('<4H', image, 0x1000, 0, 4, 2, 3)
    path = tmp_path / 'two-masked-guards.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000d0' in table) == resolved
    assert 'f_80000d4' not in table


@pytest.mark.parametrize('variant', [
    'preserved', 'foreign-case-branch', 'foreign-inner-branch', 'foreign-table-slot',
    'foreign-feedback-root', 'ambiguous-anchor', 'bypassed-anchor', 'clobber', 'fp-clobber', 'caller-saved',
])
def test_nested_halfword_table_requires_preserved_outer_selector(tmp_path, emission_env, variant):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # The guarded outer table selects 1..3 into its first case. That case
    # joins two paths, calls a leaf, and uses the saved selector minus one.
    nop = 0xd503201f
    entrance = {'foreign-case-branch': 0x35000160, 'foreign-inner-branch': 0x350002a0,
                'ambiguous-anchor': 0x1000016c, 'bypassed-anchor': 0x1000016a}.get(variant, nop)
    saved, inner_index = (0x2a0103e7, 0x510004e8) if variant == 'caller-saved' else (0x2a0103f5, 0x510006a8)
    clobber = {'clobber': 0x52800055, 'fp-clobber': 0x1e18fc15}.get(variant, nop)
    outer_anchor = nop if variant == 'bypassed-anchor' else 0x100000aa
    words = (0xaa1e03f3, 0x52800041, entrance, 0x7100103f, 0x54000368, 0x2a0103e8,
             0xb0000009, 0x91000129, outer_anchor, 0x7868792b, 0x8b0b094a, saved, 0xd61f0140,
             0x34000060, clobber, 0x14000002, 0xd503201f, 0x94000013, inner_index,
             0xb0000009, 0x91004129, 0x1000008a, 0x7868792b, 0x8b0b094a, 0xd61f0140,
             0xd2800140, 0xd65f0260, 0xd2800540, 0xd65f0260, 0xd2800180, 0xd65f0260,
             0xd2800000, 0xd65f0260)
    struct.pack_into(f'<{len(words)}I', image, 0x80, *words)
    struct.pack_into('<I', image, 0x110, 0xd65f03c0)  # called leaf
    if variant == 'bypassed-anchor':
        struct.pack_into('<I', image, 0x114, 0x17ffffde)  # independent branch to CMP
    other_case = 5 if variant == 'foreign-table-slot' else 18
    struct.pack_into('<5H', image, 0x1000, other_case, 0, 0, 0, 18)
    struct.pack_into('<3H', image, 0x1010, 0, 2, 4)
    path = tmp_path / 'nested-switch.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    feedback = []
    if variant == 'foreign-feedback-root':
        report = tmp_path / 'feedback.json'
        report.write_text(json.dumps(dict(schema='decomp.wtf.switch-native-run/v1',
            input_sha256=project.inspect(path)['input']['sha256'],
            failures=[dict(kind='missing-native-target', pc=0x080000b4)])))
        feedback.append(report)
    project.export(path, out, feedback=feedback)
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000ec' in table) == (variant == 'preserved')
    assert ('f_80000f4' in table) == (variant == 'preserved')


@pytest.mark.parametrize('variant', [
    'closed', 'loop-clobber', 'guard-bypass', 'foreign-entry', 'mutable-table',
    'mixed', 'mixed-mask-bypass', 'mixed-sparse-mask',
    'shared', 'shared-foreign-adr', 'shared-data-root',
])
def test_linked_halfword_tables_require_a_closed_control_flow_graph(tmp_path, emission_env, variant):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # Two distant bases are initialized together. Only the first table enters
    # the second dispatch, and the second table's first slot loops back to it.
    words = (0xb0000013, 0x91000273, 0xb0000015, 0x910042b5, 0x1000030c, 0x52800020,
             0x51000008, 0x7100051f, 0x54000248, 0x10000089, 0x78687a6a, 0x8b0a0929,
             0xd61f0120, 0x1400000d, 0x52800047, 0x510004e8, 0x7100051f, 0x54000128,
             0x10000089, 0x78687aaa, 0x8b0a0929, 0xd61f0120, 0xd503201f, 0x17fffff7,
             0x52800540, 0xd65f03c0, 0x52800000, 0xd65f03c0, 0xd65f03c0)
    struct.pack_into(f'<{len(words)}I', image, 0x80, *words)
    if variant == 'loop-clobber':
        struct.pack_into('<I', image, 0xd8, 0xaa0003f5)  # mov x21, x0 on the loop path
    if variant == 'foreign-entry':
        struct.pack_into('<I', image, 0xf4, 0x17ffffe6)  # branch from beyond the fence to the ADD
    if variant == 'mutable-table':
        struct.pack_into('<I', image, 0x88, 0xd0000015)  # materialize the data page instead
    fence = 0xf0
    if variant.startswith('mixed'):
        # Route the inner loop through a byte table, reusing the outer
        # table's first four bytes. Its anchor is beyond the inner result.
        struct.pack_into('<I', image, 0x90, 0x100003ec)  # adr x12, new fence
        struct.pack_into('<I', image, 0xdc, 0x14000006 if variant == 'mixed-mask-bypass' else 0x14000005)
        mask = 0x927f0008 if variant == 'mixed-sparse-mask' else 0x92400408
        struct.pack_into('<8I', image, 0xf0, mask, 0x10000089, 0x38686a6a, 0x8b0a0929,
                         0xd61f0120, 0x17ffffed, 0x17ffffec, 0xd65f03c0)
        fence = 0x10c
    if variant.startswith('shared'):
        # The inner loop can take either byte dispatch. The first has a
        # distant anchor shared with the second dispatch immediately before it.
        struct.pack_into('<I', image, 0x90, 0x1000048c)  # adr x12, new fence
        struct.pack_into('<2I', image, 0xd8, 0x35000161, 0x14000005)
        shared = (0x92400408, 0x10000129, 0x38686a6a, 0x8b0a0929, 0xd61f0120,
                  0x92400408, 0x10000089, 0x38686a6a, 0x8b0a0929, 0xd61f0120,
                  0x17ffffe8, 0x17ffffe7, 0xd65f03c0)
        struct.pack_into(f'<{len(shared)}I', image, 0xf0, *shared)
        if variant == 'shared-foreign-adr':
            struct.pack_into('<I', image, 0x124, 0x10ffffad)  # adr x13, shared anchor
        if variant == 'shared-data-root':
            struct.pack_into('<Q', image, 0x1008, 0x08000118)
        fence = 0x120
    struct.pack_into('<2H', image, 0x1000, 6 if variant == 'guard-bypass' else 0, 1)
    struct.pack_into('<2H', image, 0x2010 if variant == 'mutable-table' else 0x1010, 0, 2)
    path = tmp_path / 'linked-tables.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x080000b4, 0x080000d8, 0x08000000 + fence} <= entries and 0x080000e0 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000e0' in table) == (variant in ('closed', 'mixed', 'shared'))


@pytest.mark.parametrize('variant', ['closed', 'guard-bypass', 'independent-anchor'])
def test_linked_guarded_byte_table_with_forward_anchor(tmp_path, emission_env, variant):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    # Hoist X23 before a loop, then guard W9 and use an ADR anchor beyond
    # the instruction after BR. An unrelated ADR provides the function fence.
    words = (0xb0000017, 0x910002f7, 0x100002ae, 0x52800020,
             0x34000060, 0x51000400, 0x17fffffe, 0x11000409,
             0x7100093f, 0x540000a8, 0x100000aa, 0x38696aeb,
             0x8b0b094a, 0xd61f0140, 0x14000005, 0x52800280,
             0xd65f03c0, 0xd2800540, 0xd65f03c0, 0xd2800000,
             0xd65f03c0, 0xd2800640, 0xd65f03c0, 0xd65f03c0)
    struct.pack_into(f'<{len(words)}I', image, 0x80, *words)
    image[0x1000:0x1003] = bytes([0, 2, 6])
    if variant == 'guard-bypass':
        struct.pack_into('<I', image, 0x98, 0x350000a0)  # cbnz w0, load at 0xac
    if variant == 'independent-anchor':
        struct.pack_into('<Q', image, 0x1008, 0x080000bc)
    path = tmp_path / 'linked-guarded-byte.nro'
    path.write_bytes(image)
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x080000bc, 0x080000dc} <= entries and 0x080000c4 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_80000c4' in table) == (variant == 'closed')


@pytest.mark.parametrize('variant', ['full-width', 'narrow-alias', 'returning-wrapper'])
def test_halfword_table_preserves_base_through_full_width_aliases(tmp_path, emission_env, variant):
    from tools.switch_fixture import conditional_target_fixture, reference
    image = bytearray(conditional_target_fixture())
    struct.pack_into('<I', image, 0x24, 0x18c)
    words = {
        0x80: 0xb0000016, 0x84: 0x910002d6,  # adrp/add x22, table
        0x100: 0x52800008, 0x104: 0x11000108, 0x108: 0x7100051f, 0x10c: 0x54000268,
        0x110: 0x10000089, 0x114: 0x78687aca, 0x118: 0x8b0a0929, 0x11c: 0xd61f0120,
        0x120: 0xaa1603f7, 0x124: 0x52800016,  # Save x22 in x23, then overwrite w22.
        0x128: 0x2a1703f6 if variant == 'narrow-alias' else 0xaa1703f6,
        0x12c: 0x52800028, 0x130: 0x17fffff5,  # Second slot via the loop.
        0x134: 0xd503201f, 0x138: 0x52800540, 0x13c: 0xd65f03c0,
        0x158: 0xaa0003f6, 0x15c: 0x94000003, 0x160: 0x17ffffe8, 0x164: 0xd65f03c0,
        0x168: 0xa9bf7bfd, 0x16c: 0x910003fd, 0x170: 0x94000006,
        0x174: 0xd503201f if variant == 'returning-wrapper' else 0,
        0x178: 0xa8c17bfd, 0x17c: 0xd65f03c0, 0x188: 0xd65f03c0,
    }
    for offset in range(0x88, 0x100, 4):  # Keep the table base outside the local matcher window.
        struct.pack_into('<I', image, offset, 0xd503201f)
    for offset, word in words.items():
        struct.pack_into('<I', image, offset, word)
    struct.pack_into('<2H', image, 0x1000, 0, 6)
    struct.pack_into('<Q', image, 0x1010, 0x08000168)  # A separately discovered wrapper entry.
    path = tmp_path / 'aliased-table.nro'
    path.write_bytes(image)
    if variant == 'full-width':
        assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    entries = {int(entry) for entry in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x08000138 not in entries
    table = (out / 'game/guest0_table.c').read_text()
    assert ('f_8000138' in table) == (variant == 'full-width')


def test_magic_detection_and_status_expose_the_development_route(original, monkeypatch):
    monkeypatch.setattr(provider, 'build', lambda **_: pytest.fail('status cannot install or compile'))
    assert pc.input_platform(original) == 'switch'
    status = pc.status('switch')
    assert not status['available']
    assert 'switch-native' in status['development']['commands']
    assert 'switch-native --experimental' in status['reason']


def test_single_nso_uses_linker_and_rejects_missing_dependencies(tmp_path, monkeypatch):
    from tools.switch_exefs_fixture import module
    path = tmp_path / 'standalone.nso'; path.write_bytes(module('main'))
    monkeypatch.setattr(provider, 'build', lambda **_: pytest.fail('must link before compiling'))
    with pytest.raises(pc.PCError, match='missing DT_NEEDED'):
        project.export(path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_app_tracks_the_independent_runtime_export(original, tmp_path, emission_env):
    from decompnet.app.engine import RomNetwork
    out = tmp_path / 'source'; project.export(original, out)
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    tracked = net.pc_projects.add(out)
    assert tracked['platform'] == 'switch' and tracked['build']['target'] == 'switch_native'
    assert tracked['verification']['passed'] and tracked['output_kind'] == 'cpu-probe'


def test_romfs_identity_changes_feedback_scope(original, tmp_path):
    romfs = tmp_path / 'romfs.bin'; romfs.write_bytes(bytes(80))
    before = project.snapshot(original, romfs)
    romfs.write_bytes(bytes(79) + b'!')
    after = project.snapshot(original, romfs)
    assert before['input']['sha256'] != after['input']['sha256']
    assert before['inputs'][0] == after['inputs'][0]


@pytest.mark.parametrize('value', ['foreign-input', 'unaligned', 'outside-code', 'large'])
def test_bad_feedback_is_rejected_before_build(original, tmp_path, monkeypatch, value):
    report = dict(schema='decomp.wtf.switch-native-run/v1', input_sha256=project.inspect(original)['input']['sha256'],
                  failures=[dict(kind='missing-native-target', pc=0x08000080)])
    if value == 'foreign-input': report['input_sha256'] = '0' * 64
    elif value == 'unaligned': report['failures'][0]['pc'] += 1
    elif value == 'outside-code': report['failures'][0]['pc'] = 0x08008000
    path = tmp_path / 'feedback.json'; path.write_text(json.dumps(report))
    if value == 'large': path.write_bytes(bytes(4 * 1024 * 1024 + 1))
    monkeypatch.setattr(provider, 'build', lambda **_: pytest.fail('must validate before tools'))
    with pytest.raises(pc.PCError): project.export(original, tmp_path / 'out', feedback=[path])
    assert not (tmp_path / 'out').exists()


def test_feedback_expands_static_entries_for_this_input(original, tmp_path, emission_env):
    report = tmp_path / 'feedback.json'
    report.write_text(json.dumps(dict(schema='decomp.wtf.switch-native-run/v1',
        input_sha256=project.inspect(original)['input']['sha256'],
        failures=[dict(kind='missing-native-target', pc=0x08000004)])))
    out = tmp_path / 'out'
    project.export(original, out, feedback=[report])
    entries = {int(v) for v in (out / 'main-entries.txt').read_text().splitlines()}
    assert 0x08000004 in entries


def test_existing_edits_are_preserved_before_compiling(original, tmp_path, monkeypatch):
    out = tmp_path / 'out'; out.mkdir(); edited = out / 'game.c'; edited.write_text('owner edits')
    monkeypatch.setattr(provider, 'build', lambda **_: pytest.fail('must preserve before tools'))
    with pytest.raises(pc.PCError, match='existing work'): project.export(original, out)
    assert edited.read_text() == 'owner edits'


def test_source_changes_during_export_prevent_publication(original, tmp_path, emission_env, monkeypatch):
    export_sdk = sdk.export
    def changed(destination):
        export_sdk(destination)
        raw = bytearray(original.read_bytes()); raw[-1] ^= 1; original.write_bytes(raw)
    monkeypatch.setattr(sdk, 'export', changed)
    with pytest.raises(pc.PCError, match='changed during source export'):
        project.export(original, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()
    assert original.read_bytes()[-1] == 1


def test_cli_requires_explicit_experimental_mode(original, tmp_path, capsys):
    from decompnet.cli import main
    with pytest.raises(SystemExit) as error:
        main(['pc', 'switch-native', str(original), str(tmp_path / 'out')])
    assert error.value.code == 2
    assert '--experimental' in capsys.readouterr().err
