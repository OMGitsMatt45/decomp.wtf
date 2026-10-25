"""GBA native routes preserve the owner cartridge and bypass matching compilers."""
import argparse
import json

from starlette.testclient import TestClient

from decompnet import pc, pc_cli
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from .fixtures.gba_native import hardware
from .test_psx_native_app import finish


def test_browser_detects_gba_and_routes_native_export(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path/'db', tmp_path/'projects'); calls = []
    def generate(path, **kwargs):
        calls.append((path, kwargs))
        return dict(path=str(tmp_path/'native'), format='pc', integrity_verified=True, gameplay_verified=False)
    monkeypatch.setattr(net, 'generate_gba_pc', generate)
    def wrong(*args, **kwargs):
        raise AssertionError('GBA must not use another console or matching compiler')
    for method in ('generate_ds_pc', 'generate_psx_pc', 'generate_ps2_pc', 'import_rom'):
        monkeypatch.setattr(net, method, wrong)
    data, _ = hardware(); rom = tmp_path/'original.gba'; rom.write_bytes(data)
    mcp, manager, security = build(net, tmp_path/'home', 6499, 'secret')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    try:
        with TestClient(app, base_url='http://127.0.0.1:6499') as client:
            q = dict(path=str(rom), output='pc', renderer='opengl')
            headers = {'X-Decomp': '1'}
            assert client.post('/api/import', params=q, headers=headers).status_code == 401
            client.cookies.set('decomp_live', 'secret')
            assert client.post('/api/import', params=q, headers=headers).status_code == 400
            result = finish(client, client.post('/api/import', params={**q, 'confirmed': '1'}, headers=headers))
            assert result['state'] == 'done', result
            assert calls[0][0] == rom and calls[0][1]['renderer'] == 'opengl'
            assert calls[0][1]['save_type'] == 'auto'
            assert 'screen_mode' not in calls[0][1] and rom.read_bytes() == data
    finally:
        manager.stop()


def test_gba_capability_and_cli_do_not_install_optional_tools(tmp_path, monkeypatch):
    from decompnet import toolchains
    def forbidden(*args, **kwargs):
        raise AssertionError('status must not download sources')
    monkeypatch.setattr(toolchains, 'ensure', forbidden)
    assert pc.status('gba')['available'] and pc.status('gba')['experimental']
    assert pc.input_platform(tmp_path/'owner.GBA') == 'gba'
    parser = argparse.ArgumentParser(); pc_cli.add_parser(parser.add_subparsers(dest='action'))
    args = parser.parse_args(['pc', 'gba-native', str(tmp_path/'owner.gba'), str(tmp_path/'new'),
                              '--renderer', 'opengl', '--experimental'])
    assert args.pc_action == 'gba-native' and args.profile is None and args.rtc == 'auto'


def test_existing_gba_reconstruction_exports_its_retained_cartridge(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path/'db', tmp_path/'projects'); calls = []
    root = tmp_path/'existing'; root.mkdir()
    data, _ = hardware(); (root/'game.gba').write_bytes(data)
    (root/'user.cpp').write_text('keep my work')
    cfg = dict(platform='gba', kind='fork', rom=dict(file='game.gba'))
    with net.store.tx() as db:
        db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
                   ('original', 'Original', str(root), json.dumps(cfg)))
    def export(rom, destination, **kwargs):
        calls.append((rom, destination, kwargs)); return dict(path=str(destination))
    monkeypatch.setattr('decompnet.gba_native.export_game', export)
    result = net.export_rom('original', format='pc', renderer='opengl')
    assert result['path'] == str(root/'pc-source')
    assert calls[0][:2] == (root/'game.gba', root/'pc-source')
    assert calls[0][2]['save_type'] == 'auto' and calls[0][2]['renderer'] == 'opengl'
    assert (root/'user.cpp').read_text() == 'keep my work'


def test_connected_chat_routes_gba_without_ds_screen_or_ps1_disc_options(tmp_path, monkeypatch):
    import anyio
    import pytest
    from mcp.server.mcpserver.exceptions import ToolError
    from .test_nds_native_app import _chat_tools
    registered, net, jobs, settings, ctx = _chat_tools(tmp_path); calls = []
    data, _ = hardware(); rom = tmp_path/'unnamed.bin'; rom.write_bytes(data)
    assert pc.input_platform(rom) == 'gba'
    def generate(path, **kwargs):
        calls.append((path, kwargs))
        return dict(path=str(tmp_path/'native'), format='pc', integrity_verified=True, gameplay_verified=False)
    monkeypatch.setattr(net, 'generate_gba_pc', generate)
    fn = registered['generate_pc_project']
    with pytest.raises(ToolError, match='own legally obtained'):
        anyio.run(lambda: fn(ctx, str(rom)))
    result = anyio.run(lambda: fn(ctx, str(rom), True, renderer='opengl'))
    assert str(tmp_path/'native') in result and calls[0][0] == rom
    assert calls[0][1]['save_type'] == 'auto' and 'screen_mode' not in calls[0][1]
    with pytest.raises(ToolError, match='additional discs apply to PS1'):
        anyio.run(lambda: fn(ctx, str(rom), True, disc_paths=[str(rom)]))
    assert len(calls) == 1
