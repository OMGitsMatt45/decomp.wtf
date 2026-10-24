"""Browser and connected-agent tools generate native sources without matching setup."""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from decompnet import pc,toolchains
from decompnet.app.engine import RomNetwork
from decompnet.app import chat
from decompnet.app.server import Jobs, Settings, build
from decompnet.network import NetworkError
from decompnet import nds_native
from .fixtures.nds_native import hardware


def test_browser_generates_standalone_ds_sources_and_preserves_prior_work(tmp_path,monkeypatch):
    if toolchains.installed('dsr-sdk') is None:
        if os.environ.get('DECOMP_REQUIRE_DS_NATIVE')=='1':pytest.fail('install dsr-sdk first')
        pytest.skip('DS source runtime is not installed')
    raw,reviewed=hardware()
    ensure=toolchains.ensure
    def source_only(name,**kwargs):
        assert name=='dsr-sdk','PC generation must not request a console matching compiler'
        return ensure(name,**kwargs)
    monkeypatch.setattr(toolchains,'ensure',source_only)
    formats=[]
    def analyze(rom,work,sdk,reader,input_format,bios):
        # Explicit original-code ranges replace retail SDK-ABI inference here.
        # The real pinned emitter, hardware runtime and publishing path execute.
        formats.append(input_format)
        assert bios is None
        return nds_native._reviewed(rom.read_bytes(),reviewed,work)
    monkeypatch.setattr(nds_native,'_analyze',analyze)
    net=RomNetwork(tmp_path/'app.db',tmp_path/'projects')
    mcp,manager,security=build(net,tmp_path/'home',6499,'test-secret')
    app=mcp.streamable_http_app(transport_security=security,host='127.0.0.1')
    def finish(client,response):
        assert response.status_code==200,response.text
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            result=client.get('/api/job',params={'id':response.json()['job']}).json()
            if result['state']!='running':return result
            time.sleep(.02)
        pytest.fail('native source generation job timed out')
    try:
        with TestClient(app,base_url='http://127.0.0.1:6499') as client:
            h={'X-Decomp':'1'}
            assert client.post('/api/import?confirmed=1&output=pc',content=raw,headers=h).status_code==401
            client.cookies.set('decomp_live','test-secret')
            assert client.post('/api/import?output=pc',content=raw,headers=h).status_code==400
            query=dict(confirmed='1',output='pc',ds_input_format='decrypted',save_type='eeprom8k',name='My game.nds')
            first=finish(client,client.post('/api/import',params=query,content=raw,headers=h))
            assert first['state']=='done',first
            result=first['result'];root=Path(result['path'])
            assert result['format']=='pc' and result['integrity_verified'] and not result['gameplay_verified']
            assert pc.verify(root)['manifest']['save_type']=='eeprom8k'
            assert (root/'game/arm9/fn_table.cpp').is_file()
            assert formats==['decrypted'] and not net.store.all('SELECT * FROM projects')
            assert not list((tmp_path/'home/uploads').glob('*'))
            (root/'user-edits.cpp').write_text('keep my edits')
            again=finish(client,client.post('/api/import',params=query,content=raw,headers=h))
            assert again['state']=='done' and again['result']['path']!=str(root)
            assert (root/'user-edits.cpp').read_text()=='keep my edits'
            bad=finish(client,client.post('/api/import',params={**query,'save_type':'bad-chip'},content=raw,headers=h))
            assert bad['state']=='error' and 'save type' in bad['error']
            assert len(list((tmp_path/'projects').iterdir()))==2
            assert not list((tmp_path/'home/uploads').glob('*'))
            # Existing DS reconstruction projects use the same exporter and
            # preserve their recorded decrypted-input setting and original ROM.
            project=tmp_path/'matching';(project/'extract').mkdir(parents=True)
            source=project/'extract/baserom.nds';source.write_bytes(raw)
            (project/'.decomp.wtf.json').write_text(json.dumps(dict(ds_input_format='decrypted')))
            with net.store.tx() as db:
                db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
                    ('original-ds','Original DS',str(project),json.dumps(dict(platform='nds',kind='fork',origin='scratch'))))
            exported=finish(client,client.post('/api/export',json=dict(slug='original-ds',format='pc',save_type='eeprom8k'),headers=h))
            assert exported['state']=='done',exported
            assert Path(exported['result']['path'])==project/'pc-source'
            assert source.read_bytes()==raw and formats[-1]=='decrypted'
            with pytest.raises(NetworkError,match='existing work'):
                net.export_rom('original-ds',format='pc',save_type='eeprom8k')
    finally:
        manager.stop()


def test_direct_application_generation_checks_ownership_before_reading_input(tmp_path):
    net=RomNetwork(tmp_path/'app.db',tmp_path/'projects')
    with pytest.raises(NetworkError,match='legally obtained'):
        net.generate_ds_pc(tmp_path/'missing.nds')
    assert not (tmp_path/'projects').exists()


def _chat_tools(tmp_path):
    """Register the actual connected-agent tools without a network transport."""
    registered={}
    class Collector:
        def tool(self,**kwargs):
            def register(fn):
                registered[fn.__name__]=fn
                return fn
            return register
    net=RomNetwork(tmp_path/'app.db',tmp_path/'projects')
    manager=SimpleNamespace(assignments={},project_of=lambda agent:None)
    jobs=Jobs();settings=Settings(tmp_path/'settings.json')
    chat.register(Collector(),net,manager,jobs,settings,6499,'test-secret')
    _,token=net.chat_agent('test-chat')
    ctx=SimpleNamespace(headers={'Authorization':'Bearer '+token})
    return registered,net,jobs,settings,ctx


def test_connected_agent_native_generation_requires_chat_identity_and_ownership(tmp_path):
    registered,net,jobs,settings,ctx=_chat_tools(tmp_path)
    generate=registered['generate_pc_project']
    with pytest.raises(ToolError,match='missing API token'):
        anyio.run(lambda:generate(SimpleNamespace(headers={}),str(tmp_path/'missing.nds'),True))
    _,helper=net.local_agent('helper')
    with pytest.raises(ToolError,match='helper agents only'):
        anyio.run(lambda:generate(SimpleNamespace(headers={'Authorization':'Bearer '+helper}),
            str(tmp_path/'missing.nds'),True))
    with pytest.raises(ToolError,match='own legally obtained'):
        anyio.run(lambda:generate(ctx,str(tmp_path/'missing.nds')))
    with pytest.raises(ToolError,match='no such job'):
        anyio.run(lambda:registered['import_status'](ctx,'missing'))
    assert not jobs.jobs and not (tmp_path/'projects').exists()


def test_connected_agent_generates_and_exports_native_sources_without_matching(tmp_path,monkeypatch):
    if toolchains.installed('dsr-sdk') is None:
        if os.environ.get('DECOMP_REQUIRE_DS_NATIVE')=='1':pytest.fail('install dsr-sdk first')
        pytest.skip('DS source runtime is not installed')
    raw,reviewed=hardware();formats=[]
    def analyze(rom,work,sdk,reader,input_format,bios):
        formats.append(input_format)
        assert bios is None
        return nds_native._reviewed(rom.read_bytes(),reviewed,work)
    monkeypatch.setattr(nds_native,'_analyze',analyze)
    ensure=toolchains.ensure
    def source_only(name,**kwargs):
        assert name=='dsr-sdk','native generation must not install a console matching compiler'
        return ensure(name,**kwargs)
    monkeypatch.setattr(toolchains,'ensure',source_only)
    registered,net,jobs,settings,ctx=_chat_tools(tmp_path)
    def no_matching(*args,**kwargs):pytest.fail('native generation must not start matching or agents')
    monkeypatch.setattr(net,'import_rom',no_matching)
    monkeypatch.setattr(net,'start_autopilot',no_matching)
    rom=tmp_path/'Original game.nds';rom.write_bytes(raw)
    result=anyio.run(lambda:registered['generate_pc_project'](ctx,str(rom),True,'eeprom8k','decrypted'))
    output=next(iter(jobs.jobs.values()))['result'];root=Path(output['path'])
    assert str(root) in result and 'Native PC source project' in result and 'experimental' in result
    assert 'Imported as' not in result and 'Source integrity verified' in result
    assert pc.verify(root)['manifest']['save_type']=='eeprom8k'
    assert not net.store.all('SELECT * FROM projects') and formats==['decrypted']
    job=next(iter(jobs.jobs))
    assert anyio.run(lambda:registered['import_status'](ctx,job))==result
    with pytest.raises(ToolError,match='pc-export failed:.*save type'):
        anyio.run(lambda:registered['generate_pc_project'](ctx,str(rom),True,'bad-chip','decrypted'))
    assert len(list((tmp_path/'projects').iterdir()))==1
    # An existing reconstruction retains its original ROM/input format and uses
    # the same generator, while export_project() keeps its matching default.
    project=tmp_path/'matching';(project/'extract').mkdir(parents=True)
    source=project/'extract/baserom.nds';source.write_bytes(raw)
    (project/'.decomp.wtf.json').write_text(json.dumps(dict(ds_input_format='decrypted')))
    with net.store.tx() as db:
        db.execute('INSERT INTO projects(slug,name,root,config) VALUES(?,?,?,?)',
            ('original-ds','Original DS',str(project),json.dumps(dict(platform='nds',kind='fork',origin='scratch'))))
    settings.data['last_project']='original-ds'
    matching=anyio.run(lambda:registered['export_project'](ctx))
    assert 'already a source tree' in matching and str(project) in matching
    prior_jobs=len(jobs.jobs)
    with pytest.raises(ToolError,match='choose matching'):
        anyio.run(lambda:registered['export_project'](ctx,'unknown'))
    assert len(jobs.jobs)==prior_jobs
    exported=anyio.run(lambda:registered['export_project'](ctx,'pc','eeprom8k'))
    assert str(project/'pc-source') in exported and formats==['decrypted','decrypted']
    assert pc.verify(project/'pc-source')['manifest']['save_type']=='eeprom8k'
    assert source.read_bytes()==raw
    (project/'pc-source/user-edit.cpp').write_text('keep my edit')
    with pytest.raises(ToolError,match='pc-export failed:.*existing work'):
        anyio.run(lambda:registered['export_project'](ctx,'pc','eeprom8k'))
    assert (project/'pc-source/user-edit.cpp').read_text()=='keep my edit'
