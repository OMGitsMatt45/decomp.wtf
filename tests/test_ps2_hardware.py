"""Physical hardware claims require the actual selected Vulkan device class."""
from tools.ps2_hardware import selected_device


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
