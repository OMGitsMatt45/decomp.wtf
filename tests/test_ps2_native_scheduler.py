"""The actual scheduler reuses retired stacks while owners remain alive."""
import json
import os
import subprocess

import pytest


def test_actual_scheduler_retires_completed_callback_stacks():
    probe=os.environ.get('DECOMP_PS2_SCHEDULER_PROBE')
    if not probe:pytest.skip('set DECOMP_PS2_SCHEDULER_PROBE to the native scheduler probe')
    result=subprocess.run([probe],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    record=json.loads(result.stdout.splitlines()[-1])
    assert record==dict(success=True,living_owners=48,nested_callbacks=48,completion_callbacks=48)
