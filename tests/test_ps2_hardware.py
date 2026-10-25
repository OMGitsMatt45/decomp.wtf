"""Physical hardware claims require the actual selected Vulkan device class."""
from tools.ps2_hardware import selected_device
import json
import pytest
from pathlib import PureWindowsPath


def test_vulkan_cpu_and_virtual_devices_do_not_qualify_as_physical():
    for kind in (0,3,4):
        assert not selected_device([dict(name='NVIDIA looking label',device_type=kind)],dict(gpu_device='NVIDIA looking label'))['physical']
    for kind in (1,2):
        assert selected_device([dict(name='arbitrary label',device_type=kind)],dict(gpu_device='arbitrary label'))['physical']


def test_an_unselected_or_ambiguous_gpu_cannot_qualify_a_software_run():
    inventory=[dict(name='real GPU',device_type=2),dict(name='software',device_type=4)]
    for name in ('software','unknown',''):
        assert not selected_device(inventory,dict(gpu_device=name))['physical']
    assert not selected_device(inventory+[dict(name='real GPU',device_type=4)],dict(gpu_device='real GPU'))['physical']


def test_interruption_preserves_a_report_without_claiming_hardware_success(tmp_path,monkeypatch):
    from tools import qualify_ps2_hardware as tool
    monkeypatch.setattr(tool,'vulkan_devices',lambda:[dict(name='original test GPU',device_type=2)])
    def interrupt(*args,**kwargs):raise KeyboardInterrupt
    monkeypatch.setattr(tool,'qualify',interrupt)
    out=tmp_path/'Interrupted validation'
    with pytest.raises(KeyboardInterrupt):tool.assess(out)
    report=json.loads((out/'hardware-assessment.json').read_text())
    assert report['interrupted'] and not report['hardware_qualified'] and not report['original_fixture_passed']
    assert 'interrupted before completion' in report['error']


def test_windows_user_temp_layout_leaves_room_for_long_compiler_sources():
    from tools.qualify_ps2_hardware import fixture_path
    from decompnet.ps2_native import emitter_directory,EMITTER_LONG_SOURCE
    destination=PureWindowsPath('C:/Users/Windows Validation User/AppData/Local/Temp/dwg-12345678')
    sdk=fixture_path(destination)/'Pinned source runtime'
    source=emitter_directory(sdk,'0'*64)/EMITTER_LONG_SOURCE.as_posix()
    assert len(str(source))<240,str(source)
