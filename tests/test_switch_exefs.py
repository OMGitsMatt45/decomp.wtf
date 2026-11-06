"""Original linked modules exercise real native dispatch and bounded Horizon IPC."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet import pc
from decompnet.switch_native import discovery, exefs, provider, runtime_project
from tools.switch_exefs_fixture import BASE, SDK_BASE, SYMBOLS, expected_images, fixture, pack_module, reference, segments


def change(path, edit):
    text, ro, data = segments(path.read_bytes())
    edit(text, ro, data)
    path.write_bytes(pack_module(text, ro, data))


def tag(ro, key, value):
    for at in range(0, 0x200, 16):
        current, _ = struct.unpack_from('<QQ', ro, at)
        if current in (key, 0):
            struct.pack_into('<QQ', ro, at, key, value)
            return
    raise AssertionError('fixture dynamic table is full')


def declare_ro_module_name(path, name):
    """Original module-path record, with the dynamic table moved out of its way."""
    def edit(text, ro, data):
        table = bytearray()
        for at in range(0, 0x200, 16):
            key, value = struct.unpack_from('<QQ', ro, at)
            table.extend(struct.pack('<QQ', 0x60000001 if key == 14 else key, value))
            if key == 0:
                break
        ro.extend(bytes(0x200))
        ro[0x800:0x800 + len(table)] = table
        mod0 = struct.unpack_from('<I', text, 4)[0]
        struct.pack_into('<i', text, mod0 + 4, 0x1800 - mod0)
        encoded = name.encode('utf-8')
        ro[:8 + len(encoded) + 1] = struct.pack('<II', 0, len(encoded)) + encoded + b'\0'
    change(path, edit)


@pytest.mark.parametrize('needed', ['fixture-sdk.nss', r'C:/SDK/Library\\fixture-sdk.nss'])
def test_ro_module_name_resolves_nss_dependencies_without_soname(tmp_path, needed):
    root = fixture(tmp_path / 'exefs')
    declare_ro_module_name(root / 'sdk', 'fixture-sdk')
    def edit(text, ro, data):
        ro[0x5e0:0x5e8] = ro[0x580:0x588]
        tag(ro, 36, 0x15e0)
        encoded = needed.encode() + b'\0'
        ro[0x570:0x570 + len(encoded)] = encoded
        tag(ro, 1, 0x70)
        tag(ro, 10, 0x70 + len(encoded))
    change(root / 'main', edit)
    result = exefs.load(root, include_images=True)
    sdk = result['modules'][1]
    assert sdk['module_name'] == 'fixture-sdk' and sdk['dynamic']['soname'] is None
    assert result['modules'][0]['dynamic']['imports'][0]['module'] == 'sdk'
    assert result['initializers'][0] == SDK_BASE + SYMBOLS['sdk']['sdk_init']


def test_colliding_module_path_records_are_rejected(tmp_path):
    root = fixture(tmp_path / 'exefs')
    for name in ('main', 'sdk'):
        declare_ro_module_name(root / name, 'duplicate')
    with pytest.raises(pc.PCError, match='ambiguous'):
        exefs.load(root)


@pytest.mark.parametrize('gnu', [False, True], ids=['sysv-hash', 'gnu-hash'])
def test_linked_images_match_independent_relocations_and_constructor_order(tmp_path, gnu):
    root = fixture(tmp_path / 'owner' / 'ExeFS', gnu_hash=gnu)
    result = exefs.load(root.parent, include_images=True)
    assert [m['name'] for m in result['modules']] == ['main', 'sdk']
    for i, image in enumerate(expected_images(root)):
        assert result['modules'][i]['image'] == image
    assert result['initializers'] == [SDK_BASE + SYMBOLS['sdk']['sdk_init'], BASE + SYMBOLS['main']['main_init']]
    assert result['entry'] == BASE and result['stack_size'] == 0x10000
    assert result['modules'][0]['dynamic']['imports'] == [
        {'name': 'fixture_add', 'address': SDK_BASE + 0x100, 'module': 'sdk'},
        {'name': 'optional', 'address': 9, 'module': None}]
    assert len(result['inputs']) == 3 and exefs.identify_inputs(root) == result['inputs']
    assert not result['native_game_backend_available']


def test_relr_bitmap_relocates_bss_and_preserves_other_pointers(tmp_path):
    root = fixture(tmp_path / 'exefs')
    def edit(text, ro, data):
        tag(ro, 35, 16)
        struct.pack_into('<Q', ro, 0x588, 1 | (1 << 3) | (1 << 5))
    change(root / 'main', edit)
    image = exefs.load(root, include_images=True)['modules'][0]['image']
    assert struct.unpack_from('<Q', image, 0x2088)[0] == BASE + 0x2008
    assert struct.unpack_from('<Q', image, 0x20a0)[0] == BASE
    assert struct.unpack_from('<Q', image, 0x20b0)[0] == BASE


def test_rtld_is_loaded_for_symbols_but_main_remains_host_startup(tmp_path):
    from tools.switch_fixture import fixture as cpu_fixture
    root = fixture(tmp_path / 'exefs')
    (root / 'rtld').write_bytes(cpu_fixture())
    result = exefs.load(root)
    assert [m['name'] for m in result['modules']] == ['rtld', 'main', 'sdk']
    assert [m['base'] for m in result['modules']] == [BASE, BASE + 0x10000, BASE + 0x20000]
    assert result['entry'] == BASE + 0x10000


def test_dependency_cycle_initializes_each_module_once(tmp_path):
    root = fixture(tmp_path / 'exefs')
    def edit(text, ro, data):
        ro[0x570:0x57d] = b'fixture-main\0'
        tag(ro, 10, 0x7d)
        tag(ro, 1, 0x70)
    change(root / 'sdk', edit)
    result = exefs.load(root)
    assert result['initializers'] == [SDK_BASE + 0x114, BASE + SYMBOLS['main']['main_init']]


def test_npdm_stack_is_input_bound(tmp_path):
    root = fixture(tmp_path / 'exefs')
    before = exefs.load(root)
    raw = bytearray((root / 'main.npdm').read_bytes())
    struct.pack_into('<I', raw, 0x1c, 0x20000); (root / 'main.npdm').write_bytes(raw)
    after = exefs.load(root)
    assert after['stack_size'] == 0x20000 and after['input']['sha256'] != before['input']['sha256']
    struct.pack_into('<I', raw, 0x1c, 0xffffffff); (root / 'main.npdm').write_bytes(raw)
    with pytest.raises(pc.PCError, match='stack'): exefs.load(root)


@pytest.mark.parametrize('local', ['weak-default', 'symbolic-tag', 'symbolic-flag', 'hidden', 'protected'])
def test_symbol_preemption_and_local_visibility(tmp_path, local):
    root = fixture(tmp_path / 'exefs')
    def edit(text, ro, data):
        # Define the SDK's own weak shared_counter. A strong global in main
        # preempts it unless the SDK explicitly requests a local binding.
        struct.pack_into('<BBHQQ', ro, 0x340 + 2 * 24 + 4, 0x21,
                         2 if local == 'hidden' else 3 if local == 'protected' else 0, 1, 0x2000, 8)
        if local == 'symbolic-tag': tag(ro, 16, 0)
        if local == 'symbolic-flag': tag(ro, 30, 2)
    change(root / 'sdk', edit)
    sdk = exefs.load(root, include_images=True)['modules'][1]['image']
    assert struct.unpack_from('<Q', sdk, 0x2000)[0] == (BASE if local == 'weak-default' else SDK_BASE) + 0x2000


def test_dt_init_and_array_constructors_share_dependency_order(tmp_path):
    root = fixture(tmp_path / 'exefs')
    def edit(text, ro, data):
        for offset in range(0, 0x200, 16):
            if struct.unpack_from('<Q', ro, offset)[0] == 25:
                struct.pack_into('<QQ', ro, offset, 12, SYMBOLS['sdk']['sdk_init']); break
        tag(ro, 27, 0)
    change(root / 'sdk', edit)
    assert exefs.load(root)['initializers'] == [SDK_BASE + 0x114, BASE + SYMBOLS['main']['main_init']]


def test_sdk_startup_defers_constructors_and_selects_dt_init_once(tmp_path):
    root = fixture(tmp_path / 'exefs', sdk_startup=True)
    result = exefs.load(root)
    assert result['startup'] == dict(model='nn-sdk-start', entry=SDK_BASE + 0x180,
        sdk_initializers=[SDK_BASE + SYMBOLS['sdk']['sdk_init']],
        main_initializers=[BASE + SYMBOLS['main']['main_init']])
    assert SDK_BASE + 0x180 in result['modules'][1]['roots']


def test_five_argument_sdk_startup_initializes_and_finalizes_modules_in_order(tmp_path):
    root = fixture(tmp_path / 'exefs', sdk_startup_with_finalizers=True)
    result = exefs.load(root)
    assert result['startup'] == dict(model='nn-sdk-start', entry=SDK_BASE + 0x180,
        sdk_initializers=[], main_initializers=[SDK_BASE + SYMBOLS['sdk']['sdk_init'],
                                               BASE + SYMBOLS['main']['main_init']],
        finalizers=[BASE + 0x300, SDK_BASE + 0x1c4])
    assert BASE + 0x300 in result['modules'][0]['roots']
    assert SDK_BASE + 0x1c4 in result['modules'][1]['roots']


@pytest.mark.parametrize('case', ['mod0', 'missing-dependency', 'missing-import', 'strong-optional',
    'hidden-export', 'rela-size', 'rela-kind', 'rela-symbol', 'rela-target', 'rela-overlap',
    'relative-symbol', 'relr-without-base', 'string-offset', 'hash-count', 'symbol-value',
    'symbol-null', 'initializer-target', 'initializer-size', 'metadata-range', 'symbol-version'])
def test_malformed_or_unresolved_exefs_fails_before_compiler_and_output(tmp_path, monkeypatch, case):
    root = fixture(tmp_path / 'exefs')
    def edit(text, ro, data):
        if case == 'mod0': text[0x80:0x84] = b'BAD0'
        elif case == 'missing-dependency': ro[0x501:0x50c] = b'unknown-sdk'
        elif case == 'strong-optional': ro[0x340 + 3 * 24 + 4] = 0x10
        elif case == 'rela-size': tag(ro, 8, 25)
        elif case == 'rela-kind': struct.pack_into('<Q', ro, 0x208, (2 << 32) | 1028)
        elif case == 'rela-symbol': struct.pack_into('<Q', ro, 0x208, (999 << 32) | 1026)
        elif case == 'rela-target': struct.pack_into('<Q', ro, 0x200, 0x4000)
        elif case == 'rela-overlap': struct.pack_into('<Q', ro, 0x218, 0x2080)
        elif case == 'relative-symbol': struct.pack_into('<Q', ro, 0x220, (1 << 32) | 1027)
        elif case == 'relr-without-base': struct.pack_into('<Q', ro, 0x580, 3)
        elif case == 'string-offset': struct.pack_into('<I', ro, 0x340 + 24, 0xffffffff)
        elif case == 'hash-count': struct.pack_into('<I', ro, 0x304, 0xffffffff)
        elif case == 'symbol-value': struct.pack_into('<Q', ro, 0x340 + 24 + 8, 0xffffffff)
        elif case == 'symbol-null': ro[0x340] = 1
        elif case == 'initializer-target': struct.pack_into('<q', ro, 0x228, 0x2000)
        elif case == 'initializer-size': tag(ro, 27, 7)
        elif case == 'metadata-range': tag(ro, 6, 0x3000)
        elif case == 'symbol-version': tag(ro, 0x6ffffff0, 0x1400)
    if case == 'missing-import':
        def missing(text, ro, data):
            at = ro.index(b'fixture_add\0'); ro[at:at + 11] = b'missing_add'
        change(root / 'sdk', missing)
    elif case == 'hidden-export':
        change(root / 'sdk', lambda text, ro, data: struct.pack_into('<B', ro, 0x340 + 24 + 5, 2))
    else: change(root / 'main', edit)
    monkeypatch.setattr(provider, 'build', lambda: pytest.fail('invalid source must not run a compiler'))
    with pytest.raises(pc.PCError): runtime_project.export(root, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_duplicate_modules_source_symlinks_and_output_inside_source_are_rejected(tmp_path):
    root = fixture(tmp_path / 'exefs')
    shutil.copyfile(root / 'main', root / 'main.nso')
    with pytest.raises(pc.PCError, match='duplicate'): exefs.load(root)
    (root / 'main.nso').unlink()
    with pytest.raises(pc.PCError, match='outside'): runtime_project.export(root, root / 'generated')
    if os.name != 'nt':
        original = tmp_path / 'module'; (root / 'sdk').rename(original); (root / 'sdk').symlink_to(original)
        with pytest.raises(pc.PCError, match='regular file'): exefs.load(root)


def test_source_changes_during_generation_preserve_the_edit_and_prevent_publication(tmp_path, monkeypatch):
    root = fixture(tmp_path / 'exefs')
    monkeypatch.setattr(provider, 'build', lambda: Path('unused-emitter'))
    changed = False
    def emit(*args, **kwargs):
        nonlocal changed
        if not changed:
            change(root / 'sdk', lambda text, ro, data: data.__setitem__(0, 1))
            changed = True
    monkeypatch.setattr(runtime_project, 'emit', emit)
    with pytest.raises(pc.PCError, match='inputs changed'): runtime_project.export(root, tmp_path / 'output')
    assert segments((root / 'sdk').read_bytes())[2][0] == 1
    assert not (tmp_path / 'output').exists()


def test_existing_runtime_source_is_preserved_before_compiler(tmp_path, monkeypatch):
    root = fixture(tmp_path / 'exefs')
    output = tmp_path / 'existing'; output.mkdir(); (output / 'owner.c').write_text('owner edits')
    monkeypatch.setattr(provider, 'build', lambda: pytest.fail('must not replace existing work'))
    with pytest.raises(pc.PCError, match='existing work'): runtime_project.export(root, output)
    assert (output / 'owner.c').read_text() == 'owner edits'


def test_exefs_cli_inspection_is_distinct_from_game_support(tmp_path, capsys):
    from decompnet.cli import main
    root = fixture(tmp_path / 'exefs')
    assert main(['pc', 'switch-inspect', str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['format'] == 'exefs' and len(result['modules']) == 2
    assert result['scope'] == 'host-linked-module-runtime-development'
    assert not pc.status('switch')['available']


@pytest.fixture(scope='module')
def runtime_tools():
    cc = os.environ.get('DECOMP_SWITCH_CC') or shutil.which('clang')
    rust = os.environ.get('DECOMP_SWITCH_RUSTC') or shutil.which('rustc')
    cmake = os.environ.get('DECOMP_SWITCH_CMAKE') or shutil.which('cmake')
    if not cmake:
        possible = Path(sys.executable).parent / ('cmake.exe' if os.name == 'nt' else 'cmake')
        if possible.exists(): cmake = str(possible)
    if not (cc and rust and cmake): pytest.skip('runtime execution needs Rust, Clang and CMake')
    return cc, cmake


def build_runtime(root, cc, cmake):
    output = root / 'source'; runtime_project.export(root / 'owner', output)
    build = root / 'build'
    result = subprocess.run([cmake, '-S', str(output), '-B', str(build), '-DCMAKE_C_COMPILER=' + cc,
        '-DCMAKE_BUILD_TYPE=Release'], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([cmake, '--build', str(build), '--config', 'Release', '--parallel', '2'],
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    binary = build / 'switch_runtime'
    if os.name == 'nt': binary = next(build.rglob('switch_runtime.exe'))
    return output, binary


@pytest.fixture(scope='module')
def native_runtime(tmp_path_factory, runtime_tools):
    root = tmp_path_factory.mktemp('switch module runtime with spaces')
    fixture(root / 'owner' / 'exefs')
    output, binary = build_runtime(root, *runtime_tools)
    return root, output, binary


def run_runtime(root, output, binary, *, name='run', flag=None):
    report = root / (name + '.json')
    args = [str(binary), str(output / 'assets'), str(report)] + ([flag] if flag else [])
    result = subprocess.run(args, capture_output=True, timeout=30)
    return result, json.loads(report.read_text())


def test_setjmp_plt_return_site_is_a_native_entry(tmp_path, runtime_tools):
    root = fixture(tmp_path / 'owner' / 'exefs')

    def rename_import(ro):
        at = ro.index(b'fixture_add\0')
        ro[at:at + 8] = b'_setjmp\0'

    def caller(text, ro, data):
        rename_import(ro)
        # The top-level caller adds 40 to the protected call's result. Its
        # return site is an ordinary instruction in the middle of the function.
        struct.pack_into('<5I', text, 0x100, 0xa9bf7bfd, 0x9400001f, 0x1100a000, 0xa8c17bfd, 0xd65f03c0)
        # Save LR, call setjmp through PLT, then call a deeper frame on the
        # first return. The second return skips that call and returns 2.
        struct.pack_into('<7I', text, 0x180, 0xa9bf7bfd, 0x9400000f, 0x35000040,
                         0x94000015, 0x52800040, 0xa8c17bfd, 0xd65f03c0)
        struct.pack_into('<4I', text, 0x1c0, 0xd0000010, 0xf9404211, 0x91020210, 0xd61f0220)
        # Allocate a stack frame, call longjmp, and trap if it returns here.
        struct.pack_into('<3I', text, 0x1e0, 0xd10043ff, 0x94000007, 0xd4200000)
        struct.pack_into('<3I', text, 0x200, 0x9100029f, 0x52800020, 0xd65f0260)  # mov sp, x20; mov w0, #1; ret x19

    def callee(text, ro, data):
        rename_import(ro)
        struct.pack_into('<4I', text, 0x100, 0xaa1e03f3, 0x910003f4, 0x52800000, 0xd65f03c0)

    change(root / 'main', caller)
    change(root / 'sdk', callee)
    main = exefs.load(root, include_images=True)['modules'][0]
    assert main['returns_twice']['slots'] == [BASE + 0x2080]
    assert BASE + 0x188 in discovery.entries(main['image'], main)
    output, binary = build_runtime(tmp_path, *runtime_tools)
    # A call's SPILL has already synchronized the Cpu field. Reading a
    # promoted gsp after SPILL can use an uninitialized C local.
    code = (output / 'game/guest0_000.c').read_text()
    assert 'uint64_t rt_sp = (c)->sp;' in code and 'uint64_t rt_sp = gsp;' not in code
    result, actual = run_runtime(tmp_path, output, binary)
    assert result.returncode == 0 and actual['x'][0] == 42, actual


def test_cross_module_calls_constructors_and_service_results_match_original_execution(native_runtime):
    root, output, binary = native_runtime
    result, actual = run_runtime(root, output, binary)
    assert result.returncode == 0 and actual['status'] == 'passed', actual
    expected = reference(root / 'owner' / 'exefs')
    assert actual['x'] == expected['x'] and actual['x'][0] == 42
    for i, module in enumerate(actual['modules']):
        data = bytes.fromhex(module['data_hex'])
        want = expected['data'][i]
        if i == 0:
            # Only the host-clock timestamp differs from the deterministic reference hook.
            assert data[:88] + data[96:] == want[:88] + want[96:]
            assert struct.unpack_from('<Q', data, 88)[0] > 0
            assert struct.unpack_from('<Q', data, 0)[0] == 12
            assert struct.unpack_from('<Q', data, 72)[0] == 0xca01
        else: assert data == want
        assert module['native_entries'] >= 2
    assert actual['initializers_run'] == 2 and actual['native_function_entries'] >= 4
    assert actual['svc_counts'] == expected['svc_counts']
    assert actual['ipc_calls'] == 4 and actual['debug_bytes'] == len(expected['debug']) == 22
    assert actual['heap_size'] == 0x200000
    assert actual['interpreter_instructions'] == 0 and not actual['runtime_compilation']
    assert not actual['graphics'] and not actual['retail']
    verified = pc.verify(output)
    assert verified['integrity_verified'] and verified['manifest']['qualification']['kernel_services']
    assert not verified['manifest']['qualification']['guest_thread_creation']


@pytest.mark.parametrize('flag,reason', [('--tamper-code', 'changed-code'), ('--missing-target', 'missing-native-target')])
def test_second_module_code_guard_and_native_target_failure(native_runtime, flag, reason):
    root, output, binary = native_runtime
    result, actual = run_runtime(root, output, binary, name=reason, flag=flag)
    assert result.returncode == 1 and actual['failure'] == reason
    assert actual['interpreter_instructions'] == 0
    if reason == 'changed-code': assert actual['miss_pc'] == SDK_BASE + SYMBOLS['sdk']['sdk_init']


def test_all_module_assets_are_verified_before_constructor_execution(native_runtime, tmp_path):
    root, output, binary = native_runtime
    fake = tmp_path / 'modified'; shutil.copytree(output / 'assets', fake / 'assets')
    raw = bytearray((fake / 'assets/sdk.bin').read_bytes()); raw[0] ^= 1
    (fake / 'assets/sdk.bin').write_bytes(raw)
    result, actual = run_runtime(tmp_path, fake, binary, name='asset-failed')
    assert result.returncode == 1 and actual['failure'] == 'asset-identity-mismatch'
    assert actual['native_function_entries'] == actual['initializers_run'] == 0


@pytest.mark.parametrize('case,reason', [('svc', 'unsupported-svc'), ('command', 'unsupported-ipc-command'),
    ('descriptors', 'unsupported-ipc-descriptors'), ('malformed', 'malformed-ipc'), ('pointer', 'invalid-guest-memory')])
def test_unsupported_runtime_operations_are_reported_without_fake_success(tmp_path, runtime_tools, case, reason):
    owner = fixture(tmp_path / 'owner' / 'exefs')
    def edit(text, ro, data):
        if case == 'svc': struct.pack_into('<I', text, 0x100, 0xd4000001 | (0x77 << 5))
        elif case == 'command': struct.pack_into('<I', ro, SYMBOLS['main']['ipc_language'] - 0x1000 + 24, 99)
        elif case == 'descriptors': struct.pack_into('<I', ro, SYMBOLS['main']['ipc_get_service'] - 0x1000, 4 | (1 << 20))
        elif case == 'malformed': struct.pack_into('<I', ro, SYMBOLS['main']['ipc_language'] - 0x1000 + 4, 0)
        elif case == 'pointer':
            # Replace ADR x0,debug_message with MOV x0,0 while keeping the real SVC.
            target = SYMBOLS['main']['debug_message']
            for pc_offset in range(0x100, len(text), 4):
                word = struct.unpack_from('<I', text, pc_offset)[0]
                imm = ((word >> 5 & 0x7ffff) << 2) | (word >> 29 & 3)
                if imm & (1 << 20): imm -= 1 << 21
                if word & 0x9f00001f == 0x10000000 and pc_offset + imm == target:
                    struct.pack_into('<I', text, pc_offset, 0xd2800000); return
            raise AssertionError('fixture debug pointer instruction not found')
    change(owner / 'main', edit)
    output, binary = build_runtime(tmp_path, *runtime_tools)
    result, actual = run_runtime(tmp_path, output, binary)
    assert result.returncode == 1 and actual['failure'] == reason
    assert actual['interpreter_instructions'] == 0 and not actual['runtime_compilation']


@pytest.mark.parametrize('case', ['exit', 'pointer-buffer-query'])
def test_process_exit_and_explicit_zero_pointer_buffer_capacity(tmp_path, runtime_tools, case):
    owner = fixture(tmp_path / 'owner' / 'exefs')
    def edit(text, ro, data):
        if case == 'exit': struct.pack_into('<I', text, 0x100, 0xd4000001 | (7 << 5))
        else:
            at = SYMBOLS['main']['ipc_language'] - 0x1000
            struct.pack_into('<I', ro, at, 5)
            struct.pack_into('<I', ro, at + 24, 3)
    change(owner / 'main', edit)
    output, binary = build_runtime(tmp_path, *runtime_tools)
    result, actual = run_runtime(tmp_path, output, binary)
    assert result.returncode == 0 and actual['status'] == 'passed'
    if case == 'exit':
        assert actual['exited'] and actual['initializers_run'] == 2 and actual['svc_counts'] == {'7': 1}
        assert actual['debug_bytes'] == actual['ipc_calls'] == 0
    else:
        data = bytes.fromhex(actual['modules'][0]['data_hex'])
        assert struct.unpack_from('<Q', data, 40)[0] == 0  # First query's returned capacity.
        assert struct.unpack_from('<Q', data, 80)[0] == 0  # User-buffer query's returned capacity.
        assert actual['last_ipc'] == 3 and actual['ipc_calls'] == 4
    assert actual['interpreter_instructions'] == 0
