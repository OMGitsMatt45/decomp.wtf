"""Compare actual optimized VU pipeline state across budgets and repeated calls."""
import json
import os
import subprocess

import pytest

from tests.fixtures.ps2_vu_native import programs


@pytest.mark.parametrize('program_index',range(4))
@pytest.mark.parametrize('unit',(0,1))
def test_specialized_vector_pipeline_preserves_native_state(tmp_path,program_index,unit):
    baseline=os.environ.get('DECOMP_PS2_VU_BASELINE_PROBE')
    specialized=os.environ.get('DECOMP_PS2_VU_SPECIALIZED_PROBE')
    if not baseline or not specialized:
        pytest.skip('set baseline and specialized native VU probe paths')
    original=tmp_path/'program.bin';original.write_bytes(programs()[program_index])
    for seed,budget,mode,iterations in ((0,4,'original',1),(3,32,'original',1),
                                        (7,4,'changed',1),(3,32,'original',1000)):
        states=[];counts=[]
        for label,probe in (('baseline',baseline),('specialized',specialized)):
            output=tmp_path/(label+'.bin')
            result=subprocess.run([probe,str(unit),str(seed),str(budget),str(original),str(output),mode,str(iterations)],
                capture_output=True,text=True,timeout=30)
            assert result.returncode==0,(label,result.stdout,result.stderr)
            states.append(output.read_bytes())
            if iterations>1:
                metrics=json.loads(next(line for line in result.stderr.splitlines() if line.startswith('{')))
                assert metrics['iterations']==iterations and metrics['elapsed_ns']>0
                counts.append(metrics['native_pairs'])
        assert states[0]==states[1],(program_index,unit,seed,budget,mode,iterations)
        if counts:assert counts[0]==counts[1] and counts[0]>0
