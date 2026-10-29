"""CI runs on Windows; Linux remains available for manual builds."""
from pathlib import Path

import pytest
import yaml


WORKFLOWS=Path(__file__).resolve().parents[1]/'.github/workflows'


@pytest.mark.parametrize('path',sorted(WORKFLOWS.glob('*.yml')),ids=lambda path:path.name)
def test_workflow_jobs_use_windows_runners(path):
    workflow=yaml.safe_load(path.read_text())
    assert workflow.get('jobs'),path
    for name,job in workflow['jobs'].items():
        if 'uses' in job:
            assert job['uses'].startswith('./.github/workflows/'),(path,name)
            continue
        runner=job['runs-on']
        if runner=='${{ matrix.os }}':
            matrix=job['strategy']['matrix']
            runners=matrix.get('os',[entry['os'] for entry in matrix.get('include',[])])
        else:
            runners=[runner]
        assert runners,(path,name)
        assert all(isinstance(label,str) and label.startswith('windows-') for label in runners),(path,name,runners)
