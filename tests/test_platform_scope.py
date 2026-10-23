import json
from pathlib import Path
import struct

import pytest

from decompnet import platforms, toolchains
from decompnet.app.engine import RomNetwork
from decompnet.forks import catalog
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
    return images+[bytes(dol)]


@pytest.mark.parametrize('raw', retired_images())
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


def test_old_projects_stay_on_disk_but_cannot_resume(tmp_path):
    net = RomNetwork(tmp_path/'app.db', tmp_path)
    original = tmp_path/'retained.txt'
    original.write_text('user edits')
    with net.store.tx() as db:
        db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
                   ('old-n64','Old',str(tmp_path),json.dumps({'platform':'n64','kind':'rom'})))
    for action in (lambda: net.overview('old-n64'), lambda: net.start_autopilot('old-n64'),
                   lambda: net.export_rom('old-n64')):
        with pytest.raises(NetworkError, match='removed'):
            action()
    assert original.read_text() == 'user edits'
    assert len(net.store.all('SELECT * FROM projects')) == 1


@pytest.mark.parametrize('platform', ['n64','Nintendo 64','gc','GameCube','wii','gcwii'])
def test_public_project_target_rejected_before_clone(tmp_path, platform, monkeypatch):
    net = RomNetwork(tmp_path/'app.db',tmp_path)
    monkeypatch.setattr('subprocess.run', lambda *_a, **_k: pytest.fail('must not clone'))
    with pytest.raises(NetworkError, match='removed'):
        net.forks.clone('https://github.com/example/game', platform=platform)


def test_catalog_and_tool_setup_do_not_offer_retired_platforms():
    rows = catalog.normalize({'projects': [dict(owner='a',repo=p,platform=p) for p in
        ('nds','n64','gc','wii','gba','ps')]})
    assert {r['platform'] for r in rows} == {'nds','gba','ps'}
    assert not platforms.REMOVED_TOOLS.intersection(r['id'] for r in toolchains.status())
    with pytest.raises(toolchains.ToolchainError, match='removed'):
        toolchains.install('gcc-2.7.2-kmc')


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
    assert state['pc_output']['nds']['available'] is False
    result=client.post('/api/import?demo=1',headers={'X-Decomp':'1'})
    assert result.status_code == 400 and 'removed' in result.json()['error']
    assert client.post('/api/n64/layout',headers={'X-Decomp':'1'}).status_code == 404
    assert not net.store.all('SELECT * FROM projects')
    manager.stop()
