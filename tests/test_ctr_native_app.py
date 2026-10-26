"""3DS native app routes bypass matching compilers and preserve private images."""
import argparse
import json
from pathlib import Path

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from decompnet import pc, pc_cli, toolchains
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.network import NetworkError
from tools.ctr_fixture import fixture
from .test_nds_native_app import _chat_tools
from .test_psx_native_app import finish


def test_browser_recognizes_and_routes_decrypted_3ds_without_a_matching_project(tmp_path,monkeypatch):
    net=RomNetwork(tmp_path/'db',tmp_path/'projects');calls=[]
    def generate(path,**kwargs):
        calls.append((path,kwargs))
        return dict(path=str(tmp_path/'native'),format='pc',integrity_verified=True,gameplay_verified=False)
    monkeypatch.setattr(net,'generate_ctr_pc',generate)
    def wrong(*_a,**_k):pytest.fail('3DS native generation must bypass other consoles and matching')
    for method in ('generate_ds_pc','generate_psx_pc','generate_ps2_pc','generate_gba_pc','import_rom'):
        monkeypatch.setattr(net,method,wrong)
    rom=tmp_path/'unnamed.bin';raw=fixture();rom.write_bytes(raw)
    mcp,manager,security=build(net,tmp_path/'home',6499,'secret')
    app=mcp.streamable_http_app(transport_security=security,host='127.0.0.1')
    try:
        with TestClient(app,base_url='http://127.0.0.1:6499') as client:
            q=dict(path=str(rom),output='pc',renderer='vulkan');headers={'X-Decomp':'1'}
            assert client.post('/api/import',params=q,headers=headers).status_code==401
            client.cookies.set('decomp_live','secret')
            assert client.post('/api/import',params=q,headers=headers).status_code==400
            result=finish(client,client.post('/api/import',params={**q,'confirmed':'1'},headers=headers))
            assert result['state']=='done',result
            assert calls[0][0]==rom and calls[0][1]['renderer']=='vulkan'
            assert 'screen_mode' not in calls[0][1] and rom.read_bytes()==raw
            assert not net.store.all('SELECT * FROM projects')
    finally:manager.stop()


def test_engine_uses_fresh_destinations_and_preserves_source_and_edits(tmp_path,monkeypatch):
    net=RomNetwork(tmp_path/'db',tmp_path/'projects');calls=[]
    rom=tmp_path/'owner.cxi';raw=fixture();rom.write_bytes(raw)
    def export(path,destination,**kwargs):
        calls.append((path,destination,kwargs));destination.mkdir(parents=True)
        return dict(path=str(destination),format='pc')
    monkeypatch.setattr('decompnet.ctr_native.export_game',export)
    with pytest.raises(NetworkError,match='confirm'):net.generate_ctr_pc(rom)
    one=net.generate_ctr_pc(rom,confirmed=True,renderer='vulkan')
    (Path(one['path'])/'user.c').write_text('keep my edits')
    two=net.generate_ctr_pc(rom,confirmed=True)
    assert one['path']!=two['path'] and (Path(one['path'])/'user.c').read_text()=='keep my edits'
    assert calls[0][2]['renderer']=='vulkan' and rom.read_bytes()==raw


def test_connected_chat_routes_3ds_and_exact_input_feedback(tmp_path,monkeypatch):
    registered,net,jobs,_settings,ctx=_chat_tools(tmp_path);calls=[]
    rom=tmp_path/'unnamed.bin';rom.write_bytes(fixture())
    feedback=tmp_path/'owner-run.json';feedback.write_text('{}')
    def generate(path,**kwargs):
        calls.append((path,kwargs))
        return dict(path=str(tmp_path/'native'),format='pc',integrity_verified=True,gameplay_verified=False)
    monkeypatch.setattr(net,'generate_ctr_pc',generate)
    fn=registered['generate_pc_project']
    with pytest.raises(ToolError,match='own legally obtained'):anyio.run(lambda:fn(ctx,str(rom)))
    result=anyio.run(lambda:fn(ctx,str(rom),True,renderer='vulkan',feedback_paths=[str(feedback)]))
    assert str(tmp_path/'native') in result and calls[0][0]==rom
    assert calls[0][1]['feedback']==[feedback] and calls[0][1]['renderer']=='vulkan'
    assert 'screen_mode' not in calls[0][1]
    with pytest.raises(ToolError,match='additional discs apply to PS1'):
        anyio.run(lambda:fn(ctx,str(rom),True,disc_paths=[str(rom)]))
    assert len(calls)==1


def test_cli_and_status_install_nothing_and_expose_only_two_original_screens(tmp_path,monkeypatch):
    monkeypatch.setattr(toolchains,'ensure',lambda *_a,**_k:pytest.fail('status must not install tools'))
    assert pc.status('3ds')['available'] and pc.status('3ds')['experimental']
    parser=argparse.ArgumentParser();pc_cli.add_parser(parser.add_subparsers(dest='action'))
    args=parser.parse_args(['pc','ctr-native','owner.3ds','output','--experimental','--renderer','vulkan'])
    assert args.pc_action=='ctr-native' and args.renderer=='vulkan' and not hasattr(args,'screen_mode')
    for mode in ('unified','unknown'):
        from decompnet.ctr_native import export_game
        with pytest.raises(pc.PCError,match='screen mode must be dual'):
            export_game(tmp_path/'missing.cxi',tmp_path/'new',screen_mode=mode)
    assert not (tmp_path/'new').exists()
