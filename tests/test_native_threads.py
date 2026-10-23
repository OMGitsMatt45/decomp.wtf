"""Exercise retained MIPS analysis and scope guards in short-lived worker threads."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("operation", ["normalize", "inspect", "invalid", "segments"])
def test_native_analyzer_worker_lifetimes(operation):
    # Isolate a native crash so CI retains the exception and the offending operation.
    source = r'''
from concurrent.futures import ThreadPoolExecutor
import struct
import sys
from decompnet.rom import mips_scan, overlays
from decompnet import platforms
words=[]
for i in range(8):
    words.extend([0x27bdfff0,0x0c000000|((0x80010000+i*16)&0x0fffffff)//4,0x03e00008,0])
image=struct.pack('>32I',*words)
operation=sys.argv[1]
def work(index):
    if operation=='normalize':
        assert mips_scan._frame(0x27bdfff0) and not mips_scan._frame(0)
    elif operation=='inspect':
        assert len(mips_scan._jal_targets(tuple(words)))==8
    elif operation=='invalid':
        try:platforms.require('n64')
        except ValueError:pass
        else:raise AssertionError('retired target accepted')
    else:
        assert mips_scan._place(image,0,len(image),0,[])[2]==0x80010000
for generation in range(20):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work,range(8)))
print(operation,'shared MIPS worker lifetimes OK',flush=True)
'''
    run = subprocess.run([sys.executable, "-X", "faulthandler", "-c", source, operation],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    assert run.returncode == 0, f"{operation}: shared MIPS worker exit {run.returncode}\n{run.stdout}\n{run.stderr}"
