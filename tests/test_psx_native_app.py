"""Application routes preserve the ordered PS1 inputs and native export choice."""
import argparse
import json
import time
from pathlib import Path

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from decompnet import pc_cli
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from decompnet.network import NetworkError
from .test_nds_native_app import _chat_tools
from .fixtures.psx_hardware import disc


def finish(client,response):
    assert response.status_code==200,response.text
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        result=client.get('/api/job',params={'id':response.json()['job']}).json()
        if result['state']!='running':return result
        time.sleep(.01)
    pytest.fail('native export route timed out')


def test_browser_routes_ordered_ps1_discs_without_ds_save_or_screen_options(tmp_path,monkeypatch):
    net=RomNetwork(tmp_path/'db',tmp_path/'projects');calls=[]
    def generate(paths,**kwargs):
        calls.append((paths,kwargs))
        return dict(path=str(tmp_path/'native'),format='pc',integrity_verified=True,gameplay_verified=False)
    monkeypatch.setattr(net,'generate_psx_pc',generate)
    monkeypatch.setattr(net,'generate_ds_pc',lambda *_a,**_k:pytest.fail('PS1 must not use DS generation'))
    one=tmp_path/'disc1.iso';two=tmp_path/'disc2.iso';one.write_bytes(disc());two.write_bytes(disc(2))
    mcp,manager,security=build(net,tmp_path/'home',6499,'secret')
    app=mcp.streamable_http_app(transport_security=security,host='127.0.0.1')
    try:
        with TestClient(app,base_url='http://127.0.0.1:6499') as client:
            h={'X-Decomp':'1'}
            q=dict(path=str(one),output='pc',confirmed='1',pc_platform='psx',discs=json.dumps([str(two)]),renderer='opengl')
            assert client.post('/api/import',params=q,headers=h).status_code==401
            client.cookies.set('decomp_live','secret')
            result=finish(client,client.post('/api/import',params=q,headers=h))
            assert result['state']=='done',result
            assert calls[0][0]==[one,two]
            assert calls[0][1]['renderer']=='opengl'
            assert 'save_type' not in calls[0][1] and 'screen_mode' not in calls[0][1]
            bad=finish(client,client.post('/api/import',params={**q,'discs':'{}'},headers=h))
            assert bad['state']=='error' and len(calls)==1
            assert one.read_bytes()==disc() and two.read_bytes()==disc(2)
    finally:manager.stop()


def test_connected_agent_routes_ps1_disc_set_and_requires_ownership(tmp_path,monkeypatch):
    registered,net,jobs,settings,ctx=_chat_tools(tmp_path);calls=[]
    one=tmp_path/'disc1.iso';two=tmp_path/'disc2.iso';one.write_bytes(disc());two.write_bytes(disc(2))
    def generate(paths,**kwargs):
        calls.append((paths,kwargs));return dict(path=str(tmp_path/'native'),format='pc',
            integrity_verified=True,gameplay_verified=False,manifest=dict(qualification=dict(experimental=True)))
    monkeypatch.setattr(net,'generate_psx_pc',generate)
    fn=registered['generate_pc_project']
    with pytest.raises(ToolError,match='own legally obtained'):
        anyio.run(lambda:fn(ctx,str(one),platform='psx',disc_paths=[str(two)]))
    result=anyio.run(lambda:fn(ctx,str(one),True,platform='psx',disc_paths=[str(two)],renderer='opengl'))
    assert str(tmp_path/'native') in result
    assert calls[0][0]==[one,two] and calls[0][1]['confirmed']
    assert 'screen_mode' not in calls[0][1]


def test_direct_generation_checks_ownership_before_reading_media(tmp_path):
    net=RomNetwork(tmp_path/'db',tmp_path/'projects')
    with pytest.raises(NetworkError,match='legally obtained'):
        net.generate_psx_pc([tmp_path/'missing.iso'])
    assert not (tmp_path/'projects').exists()


def test_existing_combined_project_exports_all_ordered_retained_inputs(tmp_path,monkeypatch):
    from decompnet.rom.psx_set import configure
    net=RomNetwork(tmp_path/'db',tmp_path/'projects');calls=[]
    for index in (1,2):
        root=tmp_path/f'disc{index}';root.mkdir();(root/'user.cpp').write_text('keep')
        cfg=dict(platform='psx',kind='fork',psx_disc=dict(supported=True,sha256=str(index)*64),
                 psx_modules={'reviewed_module':{'code_start':0,'code_end':16}})
        with net.store.tx() as db:
            db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
                       (f'disc{index}',f'Disc {index}',str(root),json.dumps(cfg)))
    configure(net,'disc1',['disc2','disc1'],'One ordered game')
    def publish(project,destination,backend):
        calls.append(project);return dict(path=str(destination))
    monkeypatch.setattr('decompnet.pc.export_backend',publish)
    result=net.export_rom('disc1',format='pc',renderer='opengl')
    assert result['path']==str(tmp_path/'disc1/pc-source')
    assert [Path(row['root']).name for row in calls[0]['native_inputs']]==['disc2','disc1']
    assert calls[0]['title']=='One ordered game' and calls[0]['renderer']=='opengl'
    assert all(row['psx_modules']['reviewed_module']['code_end']==16 for row in calls[0]['native_inputs'])
    assert (tmp_path/'disc1/user.cpp').read_text()=='keep'


def test_cli_retains_disc_order_and_separate_output_path(tmp_path,monkeypatch,capsys):
    parser=argparse.ArgumentParser();pc_cli.add_parser(parser.add_subparsers(dest='action'))
    args=parser.parse_args(['pc','psx-native','first.cue','second.cue',str(tmp_path/'output'),'--experimental'])
    calls=[]
    def export(inputs,output,**kwargs):calls.append((inputs,output));return dict(path=str(output))
    monkeypatch.setattr('decompnet.psx_native.export',export)
    pc_cli.run(args)
    assert calls==[([Path('first.cue'),Path('second.cue')],tmp_path/'output')]
