import json
from pathlib import Path
import struct

import pytest

from decompnet import platforms, toolchains
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.rom import boot, detect
from decompnet.rom.errors import RomError


def retired_images():
    images = [magic+bytes(0x440) for magic in
              (b'\x80\x37\x12\x40', b'\x37\x80\x40\x12', b'\x40\x12\x37\x80',
               b'RVZ\x01', b'WIA\x01', b'WBFS', b'CISO', b'\x01\xc0\x0b\xb1')]
    for at, magic in ((0x1c, 0xc2339f3d), (0x18, 0x5d1c9ea3)):
        raw = bytearray(0x440)
        struct.pack_into('>I', raw, at, magic)
        images.append(bytes(raw))
    dol = bytearray(0x120)
    for at, value in ((0, 0x100), (72, 0x80003100), (144, 0x20), (0xe0, 0x80003100)):
        struct.pack_into('>I', dol, at, value)
    for flag in (0,0x80,0xc0):
        raw=bytearray(0x8000)
        raw[0x104:0x10c]=bytes.fromhex('ceed6666cc0d000b')
        raw[0x143]=flag
        images.append(bytes(raw))
    return images+[bytes(dol)]


@pytest.mark.parametrize('raw', retired_images(),
                         ids=lambda raw: platforms.removed_input(raw[:0x440],len(raw)))
def test_retired_inputs_rejected_before_writing_or_starting_tools(tmp_path, raw, monkeypatch):
    net = RomNetwork(tmp_path/'app.db', tmp_path/'projects')
    monkeypatch.setattr(net, '_community_layout', lambda *_: pytest.fail('must reject before generation'))
    with pytest.raises(NetworkError, match='removed'):
        net.import_rom(raw, confirmed=True)
    path = tmp_path/'input.bin'
    path.write_bytes(raw)
    with pytest.raises(NetworkError, match='removed'):
        net.import_rom(path, confirmed=True)
    with pytest.raises(RomError, match='removed'):
        detect.identify(path)
    assert not net.store.all('SELECT * FROM projects')
    assert not (tmp_path/'projects').exists()


@pytest.mark.parametrize('platform',['n64','gb','gbc'])
def test_old_projects_stay_on_disk_but_cannot_resume(tmp_path,platform):
    net = RomNetwork(tmp_path/'app.db', tmp_path)
    original = tmp_path/'retained.txt'
    original.write_text('user edits')
    with net.store.tx() as db:
        db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
                   ('old-project','Old',str(tmp_path),json.dumps({'platform':platform,'kind':'rom'})))
    for action in (lambda: net.overview('old-project'), lambda: net.start_autopilot('old-project'),
                   lambda: net.export_rom('old-project')):
        with pytest.raises(NetworkError, match='removed'):
            action()
    assert original.read_text() == 'user edits'
    assert len(net.store.all('SELECT * FROM projects')) == 1


@pytest.mark.parametrize('platform', ['n64','Nintendo 64','gc','GameCube','wii','gcwii',
                                     'gb','gbc','Game Boy','Game Boy Color','GameBoyColor','cgb'])
def test_public_project_target_rejected_before_clone(tmp_path, platform, monkeypatch):
    net = RomNetwork(tmp_path/'app.db',tmp_path)
    monkeypatch.setattr('subprocess.run', lambda *_a, **_k: pytest.fail('must not clone'))
    with pytest.raises(NetworkError, match='removed'):
        net.forks.open_local('https://github.com/example/game', platform=platform)


def test_tool_setup_does_not_offer_retired_platforms():
    assert not platforms.REMOVED_TOOLS.intersection(r['id'] for r in toolchains.status())
    with pytest.raises(toolchains.ToolchainError, match='removed'):
        toolchains.install('gcc-2.7.2-kmc')
    with pytest.raises(toolchains.ToolchainError, match='removed'):
        toolchains.install('rgbds')
    assert 'rgbds' not in toolchains.registry()


def test_project_cannot_hide_n64_behind_another_platform(tmp_path):
    (tmp_path/'game.splat.yaml').write_text('options:\n  platform: n64\n')
    with pytest.raises(ValueError, match='removed'):
        platforms.project_platform(tmp_path,'psx')


def test_n64_cli_is_not_registered(capsys):
    from decompnet.cli import main
    with pytest.raises(SystemExit) as error:
        main(['n64','scan','input.z64'])
    assert error.value.code == 2
    assert 'invalid choice' in capsys.readouterr().err


def test_gb_cli_and_implementation_are_not_registered(capsys):
    import importlib.util
    from decompnet.cli import main
    with pytest.raises(SystemExit) as error:
        main(['gb','inspect','input.gb'])
    assert error.value.code==2 and 'invalid choice' in capsys.readouterr().err
    for name in ['rom.gb','rom.gb_cli','rom.sm83','rom.match_gb','rom.export_gb','rom.export_gb_build','app.gbengine']:
        assert importlib.util.find_spec('decompnet.'+name) is None


@pytest.mark.parametrize('extension',['.gb','.gbc','.bin'])
def test_native_output_rejects_retired_cartridges_before_inspecting_other_platforms(tmp_path,extension,monkeypatch):
    from decompnet import pc
    raw=bytearray(0x8000);raw[0x104:0x10c]=bytes.fromhex('ceed6666cc0d000b')
    path=tmp_path/('original'+extension);path.write_bytes(raw)
    monkeypatch.setattr('decompnet.ps2_native.media.inspect',lambda *_a,**_k:pytest.fail('must reject before media inspection'))
    with pytest.raises(pc.PCError,match='removed'):
        pc.input_platform(path)
    assert path.read_bytes()==raw


@pytest.mark.parametrize('trusted',[False,True])
def test_retired_assembler_dialect_cannot_run_a_compiler(trusted,monkeypatch):
    from decompnet import compiler
    monkeypatch.setattr(compiler,'_exec',lambda *_a,**_k:pytest.fail('retired assembler must not run'))
    cfg=compiler.CompilerConfig(cmd=['rgbasm'],language='asm',assembly_dialect='rgbds')
    result=compiler.compile_source(cfg,'','ret',trusted=trusted)
    assert not result.ok and 'only GNU assembly' in result.log


def test_browser_rejects_retired_cartridges_and_keeps_gba():
    import shutil
    import subprocess
    node=shutil.which('node')
    if not node:
        pytest.skip('browser behavior check requires Node.js')
    script=Path(__file__).resolve().parents[1]/'src/decompnet/app/static/app.js'
    subprocess.run([node,'-e',r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('const PLATFORM_NAME =');
const stop = source.indexOf('async function pickFile(', start);
assert(start >= 0 && stop > start);
eval(source.slice(start, stop) + `
assert.deepEqual(Object.keys(PLATFORM_NAME).sort(), ['3ds','gba','nds','playstation','ps2','psx']);
for (const flag of [0, 0x80, 0xc0]) {
  const raw = new Uint8Array(0x8000);
  raw.set([0xce,0xed,0x66,0x66,0xcc,0x0d,0x00,0x0b], 0x104);
  raw[0x143] = flag;
  for (const name of ['game.gb','game.gbc','unnamed.bin']) {
    const file = {name, size:raw.length};
    assert.equal(identifyHead(raw, file), null);
    assert.match(notSupported(raw, file), /support has been removed/);
  }
}
const gba = new Uint8Array(0x8000);
gba[3] = 0xea; gba[0xb2] = 0x96; gba[0xbd] = (-(0x96 + 0x19)) & 0xff;
assert.equal(identifyHead(gba, {name:'game.gba',size:gba.length}).platform, 'gba');
assert.equal(notSupported(gba, {name:'game.gba'}), null);
for (const magic of ['NCCH','NCSD']) {
  const raw = new Uint8Array(0x440); raw.set(Array.from(magic, c => c.charCodeAt(0)), 0x100);
  assert.equal(identifyHead(raw, {name:'unnamed.bin',size:raw.length}).platform, '3ds');
}
`);
''',str(script)],check=True)


def test_retired_boot_utility_cannot_bypass_import(tmp_path):
    path=tmp_path/'main.dol'
    path.write_bytes(retired_images()[-1])
    with pytest.raises(RomError, match='removed'):
        boot.identify(path)


def test_api_scope_and_retired_demo(tmp_path):
    from starlette.testclient import TestClient
    from decompnet.app.server import build
    home=tmp_path/'home'
    home.mkdir()
    net=RomNetwork(home/'app.db',home)
    mcp, manager, security=build(net,home,6499,'test-secret')
    client=TestClient(mcp.streamable_http_app(transport_security=security,host='127.0.0.1'),
                      base_url='http://127.0.0.1:6499')
    client.cookies.set('decomp_live','test-secret')
    state=client.get('/api/state').json()
    assert set(state['platform_status']) == set(platforms.NAMES)
    assert state['pc_output']['nds']['available'] is True
    assert state['pc_output']['nds']['experimental'] is True
    result=client.post('/api/import?demo=1',headers={'X-Decomp':'1'})
    assert result.status_code == 400 and 'removed' in result.json()['error']
    assert client.post('/api/n64/layout',headers={'X-Decomp':'1'}).status_code == 404
    assert not net.store.all('SELECT * FROM projects')
    manager.stop()
