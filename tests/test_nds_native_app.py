"""The browser can generate native sources without a matching project/compiler."""
import json
import os
from pathlib import Path
import time

import pytest
from starlette.testclient import TestClient

from decompnet import pc,toolchains
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
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
