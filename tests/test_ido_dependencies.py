"""Classic templates must follow transitive content changes despite old mtimes."""

import os

import pytest

from decompnet import compiler, ido_prelink, toolchains
from decompnet.elfobj import extract_function

pytestmark = pytest.mark.skipif(os.environ.get("DECOMP_TEST_IDO_CFRONT") != "1", reason="requires pinned classic IDO")


def test_transitive_header_edit_and_failure_preserve_public_output(tmp_path):
    work = tmp_path / 'template dependencies with spaces'
    work.mkdir()
    (work / 'counter.h').write_text('#ifndef COUNTER_H\n#define COUNTER_H\n'
                                  'template<class T> class Counter { public: T next(T); };\n#endif\n')
    (work / 'counter.c').write_text('#include "counter.h"\n#include "policy.h"\n'
                                 'template<class T> T Counter<T>::next(T x) { return x + STEP; }\n')
    (work / 'policy.h').write_text('#include "policy_detail.h"\n')
    leaf = work / 'policy_detail.h'
    leaf.write_text('#define STEP 1\n')
    for name in ('left', 'right'):
        (work / (name + '.C')).write_text('#include "counter.h"\nextern "C" int ' + name +
                                        '(int x) { Counter<int> c; return c.next(x); }\n')
    tc = toolchains.require('ido-5.3')
    flags = toolchains.get('ido-5.3').flags
    cfg = compiler.CompilerConfig([], sandbox='none', relative_paths=True)
    suffix = '.exe' if os.name == 'nt' else ''
    result = compiler._exec(cfg, work, [str(tc / ('classic-CC' + suffix)), '-c', *flags, 'left.C', 'right.C'], 90)
    assert result.returncode == 0, result.stdout + result.stderr
    output = work / 'combined.o'
    def link():
        ido_prelink.prelink(work, tc, ['left.o', 'right.o'], output, flags=flags)
        return extract_function(output.read_bytes(), 'next__16Counter__pt__2_iFi').code
    before = link()
    # Set every source dependency older than the repository objects, then edit
    # only the leaf header while keeping its exact timestamp (e.g. restored ZIP).
    old = 946684800
    for path in work.iterdir():
        if path.suffix in ('.h', '.c', '.C'):
            os.utime(path, (old, old))
    leaf.write_text('#define STEP 2\n')
    os.utime(leaf, (old, old))
    after = link()
    assert before != after
    previous = output.read_bytes()
    leaf.write_text('#define STEP broken + ;\n')
    os.utime(leaf, (old, old))
    with pytest.raises(RuntimeError):
        link()
    assert output.read_bytes() == previous
    leaf.write_text('#define STEP 3\n')
    os.utime(leaf, (old, old))
    assert link() not in (before, after)


def test_repository_cannot_invalidate_files_outside_the_project(tmp_path):
    with pytest.raises(ValueError, match='subdirectory'):
        ido_prelink.prelink(tmp_path, toolchains.require('ido-5.3'), ['left.o'], tmp_path / 'combined.o', repository='..')
