"""Atomic test input remains bounded and tolerates a real Windows reader lock."""
import ctypes
from ctypes import wintypes
import os
import threading

import pytest

from decompnet.ps2_native.send_pad_command import send


def test_command_sender_validates_and_atomically_replaces(tmp_path):
    path=tmp_path/'input file.txt'
    assert send(path,'cross',8)=='1 CROSS 8\n'
    assert send(path,'UP+LEFT',30)=='2 UP+LEFT 30\n'
    assert path.read_text()=='2 UP+LEFT 30\n'
    for buttons,ticks in [('CROSS',0),('CROSS',3601),('NONE+CROSS',8),('UP+',8),('INVALID',8)]:
        with pytest.raises(ValueError):send(path,buttons,ticks)
    assert path.read_text()=='2 UP+LEFT 30\n'
    assert list(tmp_path.glob('*.next'))==[]


@pytest.mark.skipif(os.name!='nt',reason='Windows file-sharing semantics')
def test_command_sender_retries_windows_reader_lock(tmp_path):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    path=tmp_path/'input file.txt';path.write_text('1 DOWN 10\n')
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    assert handle!=ctypes.c_void_p(-1).value
    released=threading.Event()
    def release():
        released.set();kernel.CloseHandle(handle)
    timer=threading.Timer(0.15,release);timer.start()
    try:
        assert send(path,'UP',10)=='2 UP 10\n'
        assert released.is_set()
        assert path.read_text()=='2 UP 10\n'
        assert list(tmp_path.glob('*.next'))==[]
    finally:
        timer.join()
