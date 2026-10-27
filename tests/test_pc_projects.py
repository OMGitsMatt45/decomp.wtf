"""Local native-project persistence, edited outputs, API boundaries and own-agent transport."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from starlette.testclient import TestClient

from decompnet.app import connect
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from .fixtures.pc_output import generate


@pytest.mark.parametrize('command',['share','host','join'])
def test_team_commands_are_removed(command):
    from decompnet.app.cli import main
    with pytest.raises(SystemExit) as error:
        main([command])
    assert error.value.code==2


@pytest.fixture
def native(tmp_path):
    root=tmp_path/'Native source with spaces';root.mkdir()
    generate({},root)
    (root/'README.md').write_text('# Original CPU fixture\nPrepare assets, then build.\n')
    return root


def test_native_outputs_survive_restart_and_keep_edits_and_saves(tmp_path,native):
    database=tmp_path/'app.db'
    net=RomNetwork(database,tmp_path/'workspace')
    project=net.pc_projects.add(native)
    assert project['verification']['passed'] and project['kind']=='pc'
    (native/'main.cpp').write_text('int main(){return 2;}\n')
    (native/'game.sav').write_bytes(b'owner save')
    reopened=RomNetwork(database,tmp_path/'workspace')
    assert reopened.pc_projects.list()[0]['id']==project['id']
    checked=reopened.pc_projects.verify(project['id'])
    assert not checked['verification']['passed']
    assert 'hash differs' in checked['verification']['error']
    assert reopened.pc_projects.add(native)['id']==project['id']
    assert len(reopened.pc_projects.list())==1
    reopened.pc_projects.forget(project['id'])
    assert not reopened.pc_projects.list()
    assert (native/'main.cpp').read_text()=='int main(){return 2;}\n'
    assert (native/'game.sav').read_bytes()==b'owner save'


def test_pc_readme_does_not_follow_external_symlinks(tmp_path,native):
    net=RomNetwork(tmp_path/'app.db',tmp_path/'workspace')
    project=net.pc_projects.add(native)
    outside=tmp_path/'private.txt';outside.write_text('private sentinel')
    (native/'README.md').unlink()
    try:(native/'README.md').symlink_to(outside)
    except OSError:pytest.skip('this host does not permit symlinks')
    assert 'private sentinel' not in net.pc_projects.readme(project['id'])


def test_local_api_tracks_pc_outputs_and_retires_public_and_room_routes(tmp_path,native,monkeypatch):
    net=RomNetwork(tmp_path/'app.db',tmp_path/'workspace')
    mcp,manager,security=build(net,tmp_path/'home',6499,'test-secret')
    app=mcp.streamable_http_app(transport_security=security,host='127.0.0.1')
    def finish(client,response):
        assert response.status_code==200,response.text
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            job=client.get('/api/job',params={'id':response.json()['job']}).json()
            if job['state']!='running':
                assert job['state']=='done',job
                return job['result']
            time.sleep(.01)
        pytest.fail('local project job did not finish')
    try:
        with TestClient(app,base_url='http://127.0.0.1:6499') as client:
            assert client.get('/api/pc-project',params={'id':'unknown'}).status_code==401
            client.cookies.set('decomp_live','test-secret')
            assert client.post('/api/pc-project/add',json={'path':str(native)}).status_code==403
            headers={'X-Decomp':'1'}
            project=finish(client,client.post('/api/pc-project/add',json={'path':str(native)},headers=headers))
            key=project['id']
            assert client.get('/api/projects').json()[0]['id']==key
            detail=client.get('/api/pc-project',params={'id':key}).json()
            assert detail['verification']['passed'] and '# Original CPU fixture' in detail['readme']
            assert not any(field in detail for field in ('matched','matched_bytes','functions'))
            (native/'main.cpp').write_text('int main(){return 1;}\n')
            checked=finish(client,client.post('/api/pc-project',json={'id':key,'action':'verify'},headers=headers))
            assert not checked['verification']['passed']
            for route in ('/api/catalog','/api/fork','/api/fork/setup','/api/collab','/api/collab/start','/api/collab/join'):
                assert client.get(route).status_code==404
                assert client.post(route,json={},headers=headers).status_code==404
            assert client.post('/api/pc-project',json={'id':key,'action':'forget'},headers=headers).status_code==200
            assert native.is_dir() and (native/'main.cpp').exists()
    finally:manager.stop()


@pytest.mark.parametrize('kind,flag',[('claude','-e'),('codex','--env'),('antigravity','-e')])
def test_agent_registration_keeps_workspace_as_one_argument(tmp_path,monkeypatch,kind,flag):
    root=tmp_path/"Work space $value 'quoted'"
    monkeypatch.setenv('DECOMP_HOME',str(root))
    monkeypatch.setattr(connect,'_which',lambda name:'/agent tools/'+name)
    command=connect.commands(kind)
    assert 'DECOMP_HOME='+str(root.resolve()) in command
    home=command.index('DECOMP_HOME='+str(root.resolve()))
    assert command[home-1]==flag
    assert command[command.index('--')+1:]==[sys.executable,'-m','decompnet.app.cli','mcp']


def test_opencode_connection_preserves_other_settings_and_rejects_invalid_shape(tmp_path,monkeypatch):
    monkeypatch.setenv('DECOMP_HOME',str(tmp_path/'Custom workspace'))
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setattr(connect,'_which',lambda name:'/agent tools/'+name)
    path=tmp_path/'config/opencode/opencode.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'model':'local/model','mcp':{'other':{'command':['existing']}}}))
    connect.connect('opencode')
    data=json.loads(path.read_text())
    assert data['model']=='local/model' and data['mcp']['other']['command']==['existing']
    assert data['mcp']['decomp']['environment']['DECOMP_HOME']==str((tmp_path/'Custom workspace').resolve())
    assert connect.status('opencode')
    for text in ('[]','{"mcp": []}','{broken json'):
        path.write_text(text)
        with pytest.raises(ValueError):connect.connect('opencode')
        assert path.read_text()==text
        assert not connect.status('opencode')


def test_manual_windows_connection_quotes_literal_paths(monkeypatch):
    monkeypatch.setattr(connect,'commands',lambda kind:['C:\\Agent Tools\\codex.cmd','mcp','add','--env',"DECOMP_HOME=C:\\My 'work' $folder"])
    monkeypatch.setattr(connect.sys,'platform','win32')
    shown=connect.shown('codex')
    assert shown.startswith("& 'C:\\Agent Tools\\codex.cmd'")
    assert "'DECOMP_HOME=C:\\My ''work'' $folder'" in shown


def test_opencode_jsonc_is_not_shadowed_by_a_new_config(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    monkeypatch.setattr(connect,'_which',lambda name:'/agent/'+name)
    path=tmp_path/'opencode/opencode.jsonc';path.parent.mkdir()
    original='// My provider settings\n{"model":"local/model"}\n';path.write_text(original)
    with pytest.raises(ValueError,match='add this yourself'):
        connect.connect('opencode')
    assert path.read_text()==original and not path.with_suffix('.json').exists()


def test_own_agent_stdio_bridge_opens_native_project_in_custom_workspace(tmp_path,native):
    """An actual MCP client starts the bridge/server and exercises its authenticated native tools."""
    from mcp import Client,StdioServerParameters
    home=tmp_path/'Agent workspace with spaces';internal=home/'.decomp';internal.mkdir(parents=True)
    net=RomNetwork(internal/'decomp.db',home)
    project=net.pc_projects.add(native)
    env={**os.environ,'DECOMP_HOME':str(home),'DECOMP_AGENT_NAME':'native-test','DECOMP_RUNTIME':'native',
         'DECOMP_UPDATES':'off','BROWSER':'true'}
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','decompnet.app.cli','mcp'],env=env)
        async with Client(params,read_timeout_seconds=90) as client:
            async def call(name,**args):
                result=await client.call_tool(name,args)
                text='\n'.join(getattr(item,'text','') for item in result.content)
                assert not result.is_error,text
                return text
            assert project['id'] in await call('list_projects')
            opened=await call('open_project',project=project['id'])
            metadata=json.loads(opened.split('\n\nProject README:',1)[0])
            assert Path(metadata['path']).resolve()==native.resolve()
            assert '# Original CPU fixture' in await call('inspect_pc_project',project=project['id'])
            assert '"passed": true' in await call('verify_pc_project',project=project['id'])
            assert '#/pc/'+project['id'] in await call('open_gui')
            result=await client.call_tool('start_agents',{'count':1})
            assert result.is_error and 'native PC project' in '\n'.join(getattr(item,'text','') for item in result.content)
    try:asyncio.run(run())
    finally:subprocess.run([sys.executable,'-m','decompnet.app.cli','stop'],env=env,capture_output=True,timeout=30)
