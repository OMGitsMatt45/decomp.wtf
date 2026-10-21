"""Exercise the shipped native DLL from short-lived Python worker threads."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("operation", ["normalize", "inspect", "invalid", "segments"])
def test_native_analyzer_worker_lifetimes(operation):
    # Isolate a native crash so CI retains the exception and the offending operation.
    source = r'''
from concurrent.futures import ThreadPoolExecutor
import sys
from decompnet.rom import _n64_native as native
image = bytearray(0x40000)
image[:4] = bytes.fromhex('80371240')
image[8:12] = (0x80000400).to_bytes(4, 'big')
image[0x1000:0x1004] = bytes.fromhex('70000000')  # an invalid MIPS word stops after one callback
image = bytes(image)
operation = sys.argv[1]
def work(index):
    if operation == 'normalize':
        assert native.normalize(image)[0] == image
    elif operation == 'inspect':
        assert native.normalize(image, inspect=True)[0] == image
    elif operation == 'invalid':
        try:
            native.normalize(b'bad')
        except ValueError as error:
            assert 'N64 ROM' in str(error)
        else:
            raise AssertionError('invalid input accepted')
    else:
        assert native.find_segments(image, []) == []
for generation in range(20):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(8)))
print(operation, 'worker lifetimes OK', flush=True)
'''
    run = subprocess.run([sys.executable, "-X", "faulthandler", "-c", source, operation],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    assert run.returncode == 0, f"{operation}: native worker exit {run.returncode}\n{run.stdout}\n{run.stderr}"
