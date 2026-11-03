"""Qualify DMA snapshots and allocation reuse against a built PS2 runtime."""
import json
import os
import subprocess

import pytest


def test_large_vif1_snapshots_reuse_capacity_after_completion():
    baseline=os.environ.get('DECOMP_PS2_DMA_BASELINE_PROBE')
    reuse=os.environ.get('DECOMP_PS2_DMA_REUSE_PROBE')
    if not baseline or not reuse:
        pytest.skip('link fixtures/ps2_graphics_dma.cpp with the pinned original and patched PS2 runtimes')

    def run(probe,*args):
        done=subprocess.run([probe,*args],capture_output=True,text=True,timeout=30)
        assert done.returncode==0,done.stdout+done.stderr
        return json.loads(done.stdout)

    for probe in (baseline,reuse):
        assert run(probe)==dict(vif1_chains=2048,gif_chains=2048,payload_order_and_irqs_preserved=True)
    original=run(baseline,'--large-chain')
    retained=run(reuse,'--large-chain')
    for result in (original,retained):
        assert result['chains']==8 and result['bytes_per_chain']==3*1024*1024
    assert original['large_allocations_after_warmup']>=8
    assert retained['large_allocations_after_warmup']==0
