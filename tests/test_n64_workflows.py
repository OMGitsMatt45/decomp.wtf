"""Browser/CLI reviewed imports, module-specific claims and failed exports."""

import json
from pathlib import Path
import time

import pytest
from starlette.testclient import TestClient

from decompnet.app.engine import RomNetwork
from decompnet.app.collab import Room
from decompnet.app.server import build
from decompnet.cli import main
from decompnet.network import NetworkError
from .test_n64_layouts import fixture
from .test_n64_shiftable import fixture as shift_fixture


def await_job(client, response):
    assert response.status_code == 200, response.text
    job_id = response.json()['job']
    for _ in range(200):
        job = client.get('/api/job', params={'id': job_id}).json()
        if job['state'] != 'running':
            return job
        time.sleep(0.02)
    pytest.fail('reviewed import/export did not finish')


def test_browser_layout_security_single_use_failures_and_exports(tmp_path):
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    mcp, _, security = build(net, tmp_path / 'home', 6499, 'test-secret')
    app = mcp.streamable_http_app(transport_security=security, host='127.0.0.1')
    with TestClient(app, base_url='http://127.0.0.1:6499') as client:
        original, layout = fixture('yaz0')
        assert client.post('/api/n64/layout', json={'layout': layout}).status_code == 401
        client.cookies.set('decomp_live', 'test-secret')
        assert client.post('/api/n64/layout', json={'layout': layout}).status_code == 403
        headers = {'X-Decomp': '1'}
        assert client.post('/api/n64/layout', json={'layout': []}, headers=headers).status_code == 400
        assert client.post('/api/n64/layout', json={'layout': {'x': 'x' * 1048576}}, headers=headers).status_code == 400
        client.post('/api/settings', json={'autopilot': False}, headers=headers)
        token = client.post('/api/n64/layout', json={'layout': layout}, headers=headers).json()['id']
        params = {'confirmed': '1', 'name': 'reviewed.z64', 'n64_layout': token}
        job = await_job(client, client.post('/api/import', params=params, content=original, headers=headers))
        assert job['state'] == 'done', job
        slug = job['result']['slug']
        assert client.post('/api/import', params=params, content=original, headers=headers).status_code == 400
        exported = await_job(client, client.post('/api/export', params={'slug': slug}, json={}, headers=headers))
        assert exported['state'] == 'done' and exported['result']['identical'], exported
        failed = await_job(client, client.post('/api/export', params={'slug': slug}, json={'format': 'shiftable'}, headers=headers))
        assert failed['state'] == 'error' and 'uncompressed resident' in failed['error'], failed
        assert (Path(exported['result']['path']) / 'build/game.z64').read_bytes() == original
        bad_layout = dict(layout, sha256='0' * 64)
        token = client.post('/api/n64/layout', json={'layout': bad_layout}, headers=headers).json()['id']
        bad = await_job(client, client.post('/api/import', params=dict(params, n64_layout=token), content=original, headers=headers))
        assert bad['state'] == 'error' and 'SHA-256' in bad['error'], bad
        assert net.store.one('SELECT COUNT(*) AS n FROM projects')['n'] == 1
        assert not list((tmp_path / 'home/uploads').glob('*/*'))


def test_cli_layout_inspection_import_and_both_exports(tmp_path, capsys):
    original, layout = shift_fixture()
    rom = tmp_path / 'fixture.z64'
    manifest = tmp_path / 'layout.json'
    rom.write_bytes(original)
    manifest.write_text(json.dumps(layout))
    base = ['--db', str(tmp_path / 'app.db'), 'n64']
    assert main([*base, 'inspect', str(rom), '--layout', str(manifest)]) == 0
    assert json.loads(capsys.readouterr().out)['compressed_modules'] == 0
    workspace = str(tmp_path / 'projects')
    command = [*base, 'import', str(rom), '--layout', str(manifest), '--workspace', workspace, '--own-copy', '--toolchain', 'ido-5.3']
    assert main([*command, '--optimization', 'O0']) == 0
    slug = json.loads(capsys.readouterr().out)['project']
    net = RomNetwork(tmp_path / 'app.db', Path(workspace))
    flags = net.cfg(net.project_row(slug))['compiler']['flags']
    assert '-O0' in flags and '-O2' not in flags
    assert main([*command, '--optimization', 'O0']) == 0
    assert json.loads(capsys.readouterr().out)['project'] == slug
    assert main([*command, '--optimization', 'O2']) == 0
    optimized = json.loads(capsys.readouterr().out)['project']
    assert optimized != slug
    assert '-O2' in net.cfg(net.project_row(optimized))['compiler']['flags']
    assert net.store.one('SELECT COUNT(*) AS n FROM projects')['n'] == 2
    outputs = []
    for format in ('matching', 'shiftable'):
        assert main([*base, 'export', slug, '--workspace', workspace, '--format', format]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['identical'], result
        outputs.append(result['path'])
        if format == 'shiftable':
            assert result['shiftable']['ready'], result['shiftable']
    assert outputs[0] != outputs[1]
    manifest.write_text(json.dumps(dict(layout, sha256='0' * 64)))
    assert main([*base, 'inspect', str(rom), '--layout', str(manifest)]) == 1
    assert 'SHA-256' in capsys.readouterr().err


def test_overlay_claims_and_reads_remain_module_specific(tmp_path):
    original, layout = fixture()
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    project = net.project_row(slug)
    functions = net.store.all('SELECT * FROM functions WHERE project_id=? AND vram=? ORDER BY rom_offset', project['id'], 0x7F000000)
    assert len(functions) == 2
    first, _ = net.local_agent('one')
    second, _ = net.local_agent('two')
    for agent, function, value in zip((first, second), functions, (7, 8)):
        assert net.claim_row(agent, slug, function['name'])['id'] == function['id']
        assert int.from_bytes(net.reader(project, function)(0x7F000500, 4), 'big') == value
        assert function['name'] in net.get_function(function['name'], slug, agent)
    with pytest.raises(NetworkError, match='module-qualified'):
        net._function('0x7F000000', slug)
    with pytest.raises(NetworkError, match='cannot share reviewed N64 layouts'):
        Room(net, slug)
    with pytest.raises(NetworkError, match='cannot share reviewed N64 layouts'):
        net.link_project(slug, {})
    assert 'link' not in net.cfg(project)
    net.release(first, functions[0]['name'], 'reviewed', slug)
    assert net.store.one('SELECT function_id FROM claims WHERE agent_id=?', second.id)['function_id'] == functions[1]['id']
