"""Qualify an optional PS1 candidate without advertising a PC game backend."""
import io
import json
import os
from pathlib import Path

import pytest

from decompnet import pc
from tools import qualify_psx_runtime as candidate


def test_assessment_does_not_enable_product_export(monkeypatch):
    monkeypatch.setattr(pc,'BACKENDS',{})
    assert not pc.status('psx')['available']


def test_existing_work_is_preserved(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'owner.txt'
    marker.write_text('keep my work')
    with pytest.raises(ValueError, match='existing work is preserved'):
        candidate.qualify(tmp_path / 'missing-sdk', output)
    assert marker.read_text() == 'keep my work'


def test_output_cannot_modify_candidate_sources(tmp_path):
    sdk = tmp_path / 'sdk'
    sdk.mkdir()
    with pytest.raises(ValueError, match='separate directories'):
        candidate.qualify(sdk, sdk / 'proof')
    assert list(sdk.iterdir()) == []


def test_unverified_download_is_not_extracted(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'changed archive'))
    output = tmp_path / 'sdk'
    with pytest.raises(ValueError, match='archive checksum differs'):
        candidate.download(output)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_changed_sources_are_not_qualified(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, 'fingerprint', lambda sdk: 'changed')
    with pytest.raises(ValueError, match='sources differ'):
        candidate.qualify(tmp_path / 'sdk', tmp_path / 'proof')
    assert not (tmp_path / 'proof').exists()


def test_wrong_emitter_is_rejected_before_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, 'fingerprint', lambda sdk: candidate.SOURCE_SHA256)
    commands = []

    def wrong_tool(command, cwd, log):
        commands.append(command)
        return 'wrong hash\n'

    monkeypatch.setattr(candidate, 'run', wrong_tool)
    with pytest.raises(ValueError, match='codegen hash differs'):
        candidate.qualify(tmp_path / 'sdk', tmp_path / 'proof', recompiler=tmp_path / 'wrong-tool')
    assert len(commands) == 1 and commands[0][-1] == '--codegen-hash'
    assert not (tmp_path / 'proof').exists()


def test_generated_native_code_matches_original_execution(tmp_path):
    before=pc.status('psx')
    sdk = os.environ.get('DECOMP_PSX_CANDIDATE_ROOT')
    if not sdk:
        if os.environ.get('DECOMP_REQUIRE_PSX_CANDIDATE') == '1':
            pytest.fail('DECOMP_PSX_CANDIDATE_ROOT must contain the pinned candidate')
        pytest.skip('optional noncommercial PS1 runtime candidate is not installed')
    output = tmp_path / 'retained proof with spaces'
    report = candidate.qualify(sdk, output, recompiler=os.environ.get('DECOMP_PSX_CANDIDATE_RECOMPILER'))
    assert report == json.loads((output / 'assessment.json').read_text())
    assert len(report['checks']) == 20
    assert all(check['native_dispatches'] > 0 for check in report['checks'])
    assert report['changed_code_rejected']
    assert report['startup_mode_verified']
    assert [patch['id'] for patch in report['generated_patches']] == ['msvc-cps-initializer-retention-v1']
    assert report['fixture_execution_model'] == 'static-recompiled'
    assert not report['fixture_interpreter_fallback']
    assert not report['hardware_runtime_qualified'] and not report['retail_qualified']
    assert report['candidate']['default_execution_model'] == 'hybrid'
    assert report['candidate']['license'] == 'PolyForm-Noncommercial-1.0.0'
    assert pc.status('psx')==before
    assert (output / 'PSXRecomp-LICENSE.txt').read_bytes() == (Path(sdk) / 'LICENSE').read_bytes()

    # Reconfigure after staged publication: no deleted staging paths may remain.
    build = output / 'rebuilt'
    candidate.run(['cmake', '-S', output, '-B', build, '-DCMAKE_BUILD_TYPE=Release'], output, output / 'rebuild-configure.log')
    candidate.run(['cmake', '--build', build, '--config', 'Release', '--parallel', '2'], output, output / 'rebuild.log')
    native = next(p for p in (build / 'native_probe', build / 'native_probe.exe', build / 'Release/native_probe.exe') if p.is_file())
    result = json.loads(candidate.run([native, output / 'original.exe', '0x80010000', '7', '0'], output, output / 'rebuild-run.log'))
    assert result['registers'][2] == 19 and result['native_dispatches'] > 0
    assert result['cps_mode'] == 1
