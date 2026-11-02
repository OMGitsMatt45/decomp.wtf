"""Bound local profiles and compare static programs with the fixed-pair path."""
import hashlib
import json
import os
import struct
import subprocess

import pytest
from decompnet.ps2_native import vu_programs
from tests.fixtures.ps2_vu_native import programs


def test_profile_images_are_content_deduplicated(tmp_path):
    code=bytes(16384)
    for name in ('ab','cd'):(tmp_path/f'vu1-{name}.code').write_bytes(code)
    (tmp_path/'entries.txt').write_text('ab 0\ncd 0\nab 8\n')
    images,entries=vu_programs.read_profiles([tmp_path,tmp_path])
    digest=hashlib.sha256(code).hexdigest()
    assert images=={digest:code} and entries=={(digest,0),(digest,8)}


@pytest.mark.parametrize('line',('../ab 0','ab -8','ab 1','ab 4000','ab 0 extra','ab nope'))
def test_profiles_reject_paths_and_invalid_entry_points(tmp_path,line):
    (tmp_path/'entries.txt').write_text(line)
    with pytest.raises(ValueError):vu_programs.read_profiles([tmp_path])


def test_profiles_reject_truncated_images_and_image_limit(tmp_path,monkeypatch):
    (tmp_path/'entries.txt').write_text('ab 0\n')
    (tmp_path/'vu1-ab.code').write_bytes(bytes(8))
    with pytest.raises(ValueError,match='16384'):vu_programs.read_profiles([tmp_path])
    (tmp_path/'vu1-ab.code').write_bytes(bytes(16384))
    monkeypatch.setattr(vu_programs,'MAX_IMAGES',0)
    with pytest.raises(ValueError,match='Too many'):vu_programs.read_profiles([tmp_path])


def probe(tmp_path,code,unit,seed,budget,enabled,mode='single',iterations=2):
    executable=os.environ.get('DECOMP_PS2_VU_PROGRAM_PROBE')
    if not executable:pytest.skip('set the qualified native VU program probe path')
    source=tmp_path/'program.bin';source.write_bytes(code);output=tmp_path/'state.bin'
    env=os.environ.copy();env['DECOMP_PS2_VU_PROGRAMS']='1' if enabled else '0'
    result=subprocess.run([executable,str(unit),str(seed),str(budget),str(source),str(output),mode,str(iterations)],
        env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,(result.stdout,result.stderr)
    counters=json.loads(next(line for line in result.stderr.splitlines() if line.startswith('{')))
    return output.read_bytes(),counters


@pytest.mark.parametrize('seed',(0,3,7))
def test_whole_program_preserves_exceptional_values_and_partial_budgets(tmp_path,seed):
    for code in [*programs(),vu_programs.qualification_inputs()['long-loop']]:
        for budget in (1,7,4095,4096,4097,8192,65536):
            slow,reference=probe(tmp_path,code,1,seed,budget,False)
            fast,compiled=probe(tmp_path,code,1,seed,budget,True)
            assert slow==fast,(seed,budget)
            assert reference['native_pairs']==compiled['native_pairs']>0
            if budget==65536:
                assert compiled['native_programs']>0 and compiled['native_program_pairs']>0
            if budget<4096:assert compiled['native_programs']==0


@pytest.mark.parametrize('unit',(0,1))
def test_register_jump_reaches_target_before_end_bit(tmp_path,unit):
    state,_=probe(tmp_path,vu_programs.qualification_inputs()['register-jump'],unit,3,65536,True)
    # VF[32][4], then VI[16], ACC[4], Q/P/I/R, PC. VU0 and VU1 use this ABI.
    assert struct.unpack_from('<I',state,512+3*4)[0]==7
    assert struct.unpack_from('<I',state,608)[0]==88


def test_unknown_program_word_stops_without_interpreter(tmp_path):
    _,counts=probe(tmp_path,programs()[0],1,3,65536,True,'changed')
    assert counts['native_pairs']==counts['native_program_pairs']==0
