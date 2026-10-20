"""Exercise original classic template prelinking across translation units."""
from pathlib import Path
import os
import time

from decompnet import compiler, ido_prelink
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
        # Use the same Windows temporary-directory contract as application
        # compilation. The original C driver expands a relative TMPDIR to its
        # space-containing cwd before constructing internal phase commands.
        cfg = compiler.CompilerConfig([], sandbox="none", relative_paths=True)
        proc = compiler._exec(cfg, work, list(map(str, command)), 90)
        log = proc.stdout + proc.stderr
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
    binutils = tc.parent / 'binutils-mips'
    execute([binutils / ('mips-ps2-decompals-ld' + suffix), '-melf32ebmip', '-r', '-o', 'combined.o',
             'left.o', 'right.o', outputs[0]])
    undefined = execute([binutils / ('mips-ps2-decompals-nm' + suffix), '-u', 'combined.o'])
    assert 'Counter__pt__' not in undefined, undefined
    assert {'left', 'right', 'next__16Counter__pt__2_iCFv'} <= set(describe_functions((work / 'combined.o').read_bytes()))
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
    # The user-facing native prelink adapter supplies control files and commits
    # its linked output only after successful instantiation and linking.
    path.write_text(DEFINITION, encoding='utf-8', newline='\n')
    os.utime(path, (future + 10, future + 10))
    linked = work / 'combined-api.o'
    ido_prelink.prelink(work, tc, ['left.o', 'right.o'], linked, flags=flags)
    previous = linked.read_bytes()
    assert {'left', 'right', 'next__16Counter__pt__2_iCFv'} <= set(describe_functions(previous))
    path.write_text(DEFINITION.replace('value + 1', 'value + ;'), encoding='utf-8', newline='\n')
    os.utime(path, (future + 15, future + 15))
    try:
        ido_prelink.prelink(work, tc, ['left.o', 'right.o'], linked, flags=flags)
    except RuntimeError:
        pass
    else:
        raise AssertionError('The prelink adapter accepted an invalid template definition')
    assert linked.read_bytes() == previous, 'A failed prelink overwrote the previous output'
    return dict(functions=functions, changed_functions=describe_functions(changed), outputs=outputs)
