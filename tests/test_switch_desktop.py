"""Desktop exports preserve exact inputs, full runtime provenance and coverage."""
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from decompnet import pc
from decompnet.switch_native import provider
from decompnet.switch_native.desktop import project, sdk
from tools.switch_fixture import fixture


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


def test_stripped_unwind_callback_is_in_the_export_dispatch_table(tmp_path, emission_env):
    import struct
    from tests.test_switch_discovery import original as unwind_fixture

    image, _ = unwind_fixture()
    struct.pack_into('<I', image, 0, 0x140000c0)  # b 0x300, skipping metadata
    struct.pack_into('<I', image, 0x300, 0xd65f03c0)  # ret
    image[0x10:0x14] = b'NRO0'
    struct.pack_into('<II', image, 0x18, len(image), 0)
    for i, (offset, size) in enumerate(((0, 0x400), (0x1000, 0x200), (0x2000, 0x80))):
        struct.pack_into('<II', image, 0x20 + 8 * i, offset, size)
    path = tmp_path / 'stripped.nro'; path.write_bytes(image)
    out = tmp_path / 'source'
    project.export(path, out)
    # Neither callback is called or address-materialized by the entry program.
    entries = {int(v) for v in (out / 'main-entries.txt').read_text().splitlines()}
    assert {0x08000200, 0x08000240} <= entries
    table = (out / 'game/guest0_table.c').read_text()
    assert 'f_8000200' in table and 'f_8000240' in table


def test_computed_branch_can_enter_a_conditional_fallthrough(tmp_path, emission_env):
    from tools.switch_fixture import conditional_target_fixture, reference
    path = tmp_path / 'conditional-target.nro'
    path.write_bytes(conditional_target_fixture())
    assert reference(path)['x'][0] == 42
    out = tmp_path / 'source'
    project.export(path, out)
    table = (out / 'game/guest0_table.c').read_text()
    assert 'f_8000090' in table


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
