"""Physical qualification requires rendered results and the actual device."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from tools import qualify_ctr_hardware as tool


def reports():
    scenes=dict(schema='decomp.wtf.3ds-gpu-scenes/v1',passed=True,renderer='vulkan',device='actual GPU',
                scenes=4,resized_scales=[1,2,3,1],framebuffer_preserved=True)
    players={}
    for name,screen in [('stacked','stacked')]:
        players[name]=dict(schema='decomp.wtf.3ds-runtime-run/v1',gpu_rendering=True,stop='window-frame-limit',
            interpreted_instructions=0,rejected_instructions=0,native_instructions=100,static_misses=[],
            unimplemented_svcs=[],unimplemented_services=[],window=dict(device='actual GPU',
            presented_frames=2,screens=screen,drawable=[1920,1080]))
    return scenes,players


def test_a_physical_inventory_cannot_qualify_an_unselected_or_software_renderer():
    scenes,players=reports()
    for kind in (0,3,4):
        selected=tool.verify(scenes,players,[dict(name='actual GPU',device_type=kind)])
        assert not any(row['physical'] for row in selected.values())
    inventory=[dict(name='actual GPU',device_type=2)]
    assert all(row['physical'] for row in tool.verify(scenes,players,inventory).values())
    players['stacked']['window']['device']='a different GPU'
    assert not tool.verify(scenes,players,inventory)['stacked']['physical']


@pytest.mark.parametrize('case',['resize','picture','interpreter','miss','window','layout','device'])
def test_incomplete_rendering_or_unknown_identity_cannot_qualify(case):
    scenes,players=reports()
    if case=='resize':scenes['resized_scales']=[1]
    elif case=='picture':scenes['framebuffer_preserved']=False
    elif case=='interpreter':players['stacked']['interpreted_instructions']=1
    elif case=='miss':players['stacked']['static_misses']=[0]
    elif case=='window':players['stacked']['window']['presented_frames']=0
    elif case=='layout':players['stacked']['window']['screens']='single'
    else:
        players['stacked']['window']['device']=''
        assert not tool.verify(scenes,players,[dict(name='actual GPU',device_type=1)])['stacked']['physical']
        return
    with pytest.raises(ValueError):tool.verify(scenes,players,[dict(name='actual GPU',device_type=1)])


def test_interruption_and_software_rejection_preserve_failed_reports(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'vulkan_devices',lambda:[dict(name='software',device_type=4)])
    with pytest.raises(ValueError,match='no integrated'):tool.assess(tmp_path/'software')
    result=json.loads((tmp_path/'software/hardware-assessment.json').read_text())
    assert not result['hardware_qualified'] and not result['original_fixture_passed']
    monkeypatch.setattr(tool,'vulkan_devices',lambda:[dict(name='physical',device_type=1)])
    monkeypatch.setattr(tool.shutil,'which',lambda _: 'cmake')
    def interrupt(*_a,**_k):raise KeyboardInterrupt
    monkeypatch.setattr(tool,'export_game',interrupt)
    with pytest.raises(KeyboardInterrupt):tool.assess(tmp_path/'interrupted')
    result=json.loads((tmp_path/'interrupted/hardware-assessment.json').read_text())
    assert result['interrupted'] and not result['hardware_qualified']


def test_windows_launcher_finds_the_project_from_an_unrelated_directory(tmp_path):
    if os.name!='nt':return
    script=Path(__file__).parents[1]/'tools/qualify-3ds-hardware.ps1'
    result=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-CheckTools'],
        cwd=tmp_path,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    found=json.loads(result.stdout)
    assert Path(found['uv']).is_file() and Path(found['cmake']).is_file() and Path(found['rustc']).is_file()
