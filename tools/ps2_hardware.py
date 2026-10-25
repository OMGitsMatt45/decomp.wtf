"""Read Vulkan's device class; renderer names alone cannot prove hardware use."""
import ctypes as c
from ctypes.util import find_library
import os


def vulkan_devices():
    loader=c.WinDLL('vulkan-1.dll') if os.name=='nt' else c.CDLL(find_library('vulkan') or 'libvulkan.so.1')
    class CreateInfo(c.Structure):
        _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('flags',c.c_uint32),
            ('application',c.c_void_p),('layerCount',c.c_uint32),('layers',c.c_void_p),
            ('extensionCount',c.c_uint32),('extensions',c.c_void_p)]
    create=loader.vkCreateInstance;create.argtypes=[c.POINTER(CreateInfo),c.c_void_p,c.POINTER(c.c_void_p)];create.restype=c.c_int32
    destroy=loader.vkDestroyInstance;destroy.argtypes=[c.c_void_p,c.c_void_p];destroy.restype=None
    enumerate_=loader.vkEnumeratePhysicalDevices;enumerate_.argtypes=[c.c_void_p,c.POINTER(c.c_uint32),c.POINTER(c.c_void_p)];enumerate_.restype=c.c_int32
    properties=loader.vkGetPhysicalDeviceProperties;properties.argtypes=[c.c_void_p,c.c_void_p];properties.restype=None
    instance=c.c_void_p();info=CreateInfo();info.sType=1
    status=create(c.byref(info),None,c.byref(instance))
    if status:raise RuntimeError(f'Vulkan instance creation failed: {status}')
    try:
        count=c.c_uint32();status=enumerate_(instance,c.byref(count),None)
        if status or not 0<count.value<=128:raise RuntimeError('Vulkan device inventory unavailable or exceeds its bound')
        devices=(c.c_void_p*count.value)();status=enumerate_(instance,c.byref(count),devices)
        if status:raise RuntimeError(f'Vulkan device enumeration changed or failed: {status}')
        result=[]
        for device in devices[:count.value]:
            # Vulkan 1.0 VkPhysicalDeviceProperties has a fixed ABI. Oversized,
            # 8-byte-aligned storage accommodates the complete limits structure;
            # the standardized scalar/name/UUID prefix is identical on both hosts.
            storage=(c.c_uint64*512)();properties(device,storage)
            raw=bytes(storage);prefix=(c.c_uint32*5).from_buffer_copy(raw[:20])
            result.append(dict(name=raw[20:276].split(b'\0',1)[0].decode('utf-8','replace'),
                api_version=prefix[0],driver_version=prefix[1],vendor_id=prefix[2],device_id=prefix[3],
                device_type=prefix[4],pipeline_uuid=raw[276:292].hex()))
        return result
    finally:destroy(instance,None)


def selected_device(inventory,run):
    """Match the name from the actual SDL device to this driver's inventory.

    The string is used only for exact identity matching, never vendor/type
    inference. Missing/ambiguous identity or CPU/virtual devices fail physical
    hardware qualification. Duplicate names qualify only if all matches are
    physical; the complete candidate inventory stays in the report.
    """
    matches=[d for d in inventory if run.get('gpu_device') and d['name']==run['gpu_device']]
    physical=bool(matches) and all(d['device_type'] in (1,2) for d in matches)
    return dict(physical=physical,candidates=matches,
        reason='integrated/discrete Vulkan device' if physical else 'selected device is unverified, virtual or software')
