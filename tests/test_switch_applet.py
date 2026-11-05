"""Exercise foreground-session applet policy without a retail executable."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.switch_native.desktop import sdk


def test_applet_policy_runs_its_native_state_regressions(tmp_path):
    compiler = os.environ.get('DECOMP_SWITCH_RUSTC') or shutil.which('rustc')
    if not compiler:
        pytest.skip('original applet policy checks require Rust')
    source = tmp_path / 'policy.rs'
    # A module wrapper preserves pub(super), as in the exported runtime.
    path = (sdk.ROOT / 'applet_control.rs').as_posix()
    source.write_text(f'#[path = "{path}"] mod policy;\n')
    binary = tmp_path / ('policy.exe' if os.name == 'nt' else 'policy')
    result = subprocess.run([compiler, '--edition=2024', '--test', str(source), '-o', str(binary)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '4 passed; 0 failed' in result.stdout
