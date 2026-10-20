"""Exercise original classic template prelinking across translation units."""
from pathlib import Path
import os
import subprocess
import time

from decompnet.elfobj import extract_function
from tests.fixtures.generate_native_compiler_parity import describe_functions

HEADER = '''#ifndef COUNTER_H
#define COUNTER_H
template<class T> class Counter { public: T value; Counter(T); T next() const; };
#endif
'''
DEFINITION = '''#include "counter.h"
template<class T> Counter<T>::Counter(T x): value(x) {}
template<class T> T Counter<T>::next() const { return value + 1; }
'''


def run(work: Path, tc: Path, *, ptlink: list[str] | None = None, nm: str = '/usr/bin/nm', cc: str = 'classic-CC', cpp: str = '/usr/lib/acpp') -> dict:
    work.mkdir(parents=True, exist_ok=True)
    suffix = '.exe' if os.name == 'nt' else ''
    flags = ['-O2', '-mips2', '-G0', '-non_shared', '-Xcpluscomm', '-Wab,-r4300_mul']
    (work / 'counter.h').write_text(HEADER, encoding='utf-8', newline='\n')
    (work / 'counter.c').write_text(DEFINITION, encoding='utf-8', newline='\n')
    for name, extra in [('left', ''), ('right', ' + 10')]:
        (work / (name + '.C')).write_text('#include "counter.h"\nextern "C" int ' + name +
            '(int x) { Counter<int> c(x); return c.next()' + extra + '; }\n', encoding='utf-8', newline='\n')
    def execute(command, *, success=True):
        proc = subprocess.run(list(map(str, command)), cwd=work, capture_output=True, timeout=90,
                              env={**os.environ, "TMPDIR": work.as_posix()})
        log = (proc.stdout + proc.stderr).decode(errors='replace')
        assert (proc.returncode == 0) == success, (command, proc.returncode, log)
        assert 'warning: nm' not in log, log
        return log
    execute([tc / ('classic-CC' + suffix), '-c', *flags, 'left.C', 'right.C'])
    (work / 'prelink-temp').mkdir()
    for name, text in dict(includes='-I.\n', objects='left.o\nright.o\n', options='\n'.join(flags) + '\n',
                           repositories='./ptrepository\n').items():
        (work / 'prelink-temp' / name).write_text(text, encoding='utf-8', newline='\n')
    command = [*(ptlink or [str(tc / ('ptlink' + suffix))]), './ptrepository', './prelink-temp', cc,
               './prelink-temp/includes', './prelink-temp/objects', './prelink-temp/output', 'defmap',
               './prelink-temp/options', './prelink-temp/repositories', cpp, nm, 'combined.o']
    execute(command)
    outputs = (work / 'prelink-temp/output').read_text().splitlines()
    assert outputs == ['./ptrepository/Counter__pt__2_i.o'], outputs
    obj = (work / outputs[0]).read_bytes()
    functions = describe_functions(obj)
    assert {f for f in functions} >= {'__ct__16Counter__pt__2_iFi', 'next__16Counter__pt__2_iCFv'}
    before = extract_function(obj, 'next__16Counter__pt__2_iCFv').code
    # Exercise dependency/checksum invalidation, not only an empty repository.
    path = work / 'counter.c'
    path.write_text(DEFINITION.replace('value + 1', 'value + 2'), encoding='utf-8', newline='\n')
    future = time.time() + 5
    os.utime(path, (future, future))
    execute(command)
    changed = (work / outputs[0]).read_bytes()
    assert extract_function(changed, 'next__16Counter__pt__2_iCFv').code != before
    # A bad re-instantiation must fail rather than silently reuse stale output.
    path.write_text(DEFINITION.replace('value + 1', 'value + ;'), encoding='utf-8', newline='\n')
    os.utime(path, (future + 5, future + 5))
    execute(command, success=False)
    return dict(functions=functions, changed_functions=describe_functions(changed), outputs=outputs)
