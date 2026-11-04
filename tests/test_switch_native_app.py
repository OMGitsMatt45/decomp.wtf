"""Unqualified Switch uploads cannot accidentally use another console backend."""
import time
import pytest

from starlette.testclient import TestClient

from decompnet.app.engine import RomNetwork
from decompnet.app.server import build
from tools.switch_fixture import fixture


@pytest.mark.parametrize('override', ['', 'psx'])
def test_switch_upload_explains_the_explicit_source_workflow(tmp_path, monkeypatch, override):
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    def wrong(*args, **kwargs):
        raise AssertionError('Switch must not use another console generator')
    for name in ('generate_ds_pc', 'generate_psx_pc', 'generate_ps2_pc', 'generate_gba_pc', 'generate_ctr_pc', 'import_rom'):
        monkeypatch.setattr(net, name, wrong)
    original = tmp_path / 'unnamed.bin'; raw = fixture(nro=True); original.write_bytes(raw)
    mcp, manager, security = build(net, tmp_path / 'home', 6499, 'test-secret')
    try:
        with TestClient(mcp.streamable_http_app(transport_security=security, host='127.0.0.1'), base_url='http://127.0.0.1:6499') as client:
            client.cookies.set('decomp_live', 'test-secret')
            response = client.post('/api/import', params=dict(path=str(original), output='pc', confirmed='1', pc_platform=override), headers={'X-Decomp':'1'})
            assert response.status_code == 200
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = client.get('/api/job', params={'id':response.json()['job']}).json()
                if job['state'] != 'running': break
                time.sleep(.01)
            assert job['state'] == 'error' and 'switch-native --experimental' in job['error']
            assert original.read_bytes() == raw
            assert not net.pc_projects.list() and not net.store.all('SELECT * FROM projects')
    finally:
        manager.stop()
