from .fixtures.pc_output import result as pc_result
"""PS2 native routes retain the owner/profile and never choose a DS/PS1 backend."""
import argparse
import json

import pytest
from starlette.testclient import TestClient

from decompnet import pc,pc_cli
from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from .fixtures.ps2_port import original
from .test_psx_native_app import finish


def test_browser_routes_owner_ps2_and_optional_profile_without_console_compilers(tmp_path,monkeypatch):
    net=RomNetwork(tmp_path/'db',tmp_path/'projects');calls=[]
    def generate(path,**kwargs):
        calls.append((path,kwargs));return pc_result(tmp_path / 'native','ps2')
    monkeypatch.setattr(net,'generate_ps2_pc',generate)
    monkeypatch.setattr(net,'generate_ds_pc',lambda *_a,**_k:pytest.fail('PS2 routed to DS'))
    monkeypatch.setattr(net,'generate_psx_pc',lambda *_a,**_k:pytest.fail('PS2 routed to PS1'))
    owner=tmp_path/'original.elf';owner.write_bytes(original())
    profile=tmp_path/'reviewed.json';profile.write_text('{}')
    mcp,manager,security=build(net,tmp_path/'home',6499,'secret')
    app=mcp.streamable_http_app(transport_security=security,host='127.0.0.1')
    try:
        with TestClient(app,base_url='http://127.0.0.1:6499') as client:
            query=dict(path=str(owner),output='pc',pc_platform='ps2',ps2_profile=str(profile),renderer='vulkan')
            headers={'X-Decomp':'1'}
            assert client.post('/api/import',params=query,headers=headers).status_code==401
            client.cookies.set('decomp_live','secret')
            assert client.post('/api/import',params=query,headers=headers).status_code==400
            result=finish(client,client.post('/api/import',params={**query,'confirmed':'1'},headers=headers))
            assert result['state']=='done',result
            assert calls[0][0]==owner and calls[0][1]['profile']==profile and calls[0][1]['renderer']=='vulkan'
            assert 'save_type' not in calls[0][1] and 'screen_mode' not in calls[0][1]
            assert owner.read_bytes()==original()
    finally:manager.stop()


def test_ps2_capability_and_cli_require_no_optional_download(tmp_path,monkeypatch):
    from decompnet.ps2_native import provider
    monkeypatch.setattr(provider,'download',lambda *_a,**_k:pytest.fail('status must not download runtime sources'))
    assert pc.status('ps2')['available'] and pc.status('ps2')['experimental']
    owner=tmp_path/'original.elf';owner.write_bytes(original())
    assert pc.input_platform(owner)=='ps2'
    parser=argparse.ArgumentParser();pc_cli.add_parser(parser.add_subparsers(dest='action'))
    args=parser.parse_args(['pc','ps2-native',str(owner),str(tmp_path/'new'),'--renderer','vulkan','--experimental'])
    assert args.pc_action=='ps2-native' and args.profile is None
