"""Build pinned donor tests and compare LAS/nxrecomp scalar C on original cases.

The GPL donor and its emitted comparison source stay in the separate work
directory. This is bounded CPU evidence, not graphics or retail qualification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from decompnet.switch_native.provider import sources
from decompnet.switch_native.sources import pull


def run(command, log):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(f'comparison command failed ({result.returncode}); see {log}')
    return result.stdout


def compare(donors, work, cc):
    # Import only the standalone instruction lifters from the verified trees.
    # No upstream installers, game configs or runtimes run here.
    sys.path.insert(0, str(donors / 'lasrecomp/tools'))
    from lifter import Lifter
    spec = importlib.util.spec_from_file_location('nx_scalar_oracle', donors / 'nxrecomp/recomp/nxrecomp/lift/a64.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    las = Lifter(0, simd='c')
    nx = module.Fn(0x1000, 0x2000, None)
    instructions = [
        (0x8b010002, 'add64', lambda a, b: a + b, 64),
        (0xcb010002, 'sub64', lambda a, b: a - b, 64),
        (0x9b017c02, 'mul64', lambda a, b: a * b, 64),
        (0xca010002, 'xor64', lambda a, b: a ^ b, 64),
        (0x8a010002, 'and64', lambda a, b: a & b, 64),
        (0xaa010002, 'or64', lambda a, b: a | b, 64),
        (0x0b010002, 'add32', lambda a, b: a + b, 32),
        (0x4b010002, 'sub32', lambda a, b: a - b, 32),
        (0x1b017c02, 'mul32', lambda a, b: a * b, 32),
    ]
    values = [0, 1, 2, 31, 32, 63, 64, 255, 0xffffffff, 0x100000000,
              0x7fffffff, 0x80000000, 0x7fffffffffffffff, 0x8000000000000000,
              0xfffffffffffffffe, 0xffffffffffffffff]
    text = ['// Local comparison only: emitted from MIT LASRecomp and GPL nxrecomp.\n',
            '#include <stdint.h>\n#include <stdio.h>\n', 'typedef struct {uint64_t x[32];} Cpu;\n']
    cases = []
    for i, (word, name, expected, bits) in enumerate(instructions):
        lowered = las.lift(word, 0x1000)
        if lowered.kind != 'op': raise ValueError('comparison instruction is not scalar')
        text += [f'static void las{i}(Cpu*c){{{lowered.code}}}\n',
                 f'static void nx{i}(Cpu*c){{{nx.lift(word, 0x1000)}}}\n']
        mask = (1 << bits) - 1
        for a in values:
            for b in values:
                want = expected(a & mask, b & mask) & mask
                cases.append(f'{{{i},{a}ull,{b}ull,{want}ull}}')
    text += ['typedef void (*Fn)(Cpu*);\n',
             'static Fn las[]={' + ','.join('las' + str(i) for i in range(len(instructions))) + '};\n',
             'static Fn nx[]={' + ','.join('nx' + str(i) for i in range(len(instructions))) + '};\n',
             'static struct {unsigned op;uint64_t a,b,want;} cases[]={' + ',\n'.join(cases) + '};\n',
             'int main(void){for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);++i){'
             'Cpu a={0},b={0};a.x[0]=b.x[0]=cases[i].a;a.x[1]=b.x[1]=cases[i].b;'
             'las[cases[i].op](&a);nx[cases[i].op](&b);'
             'if(a.x[2]!=cases[i].want||b.x[2]!=cases[i].want){printf("failed case %u\\n",i);return 1;}}'
             'puts("all scalar comparisons passed");return 0;}\n']
    source = work / 'scalar-comparison.c'; source.write_text(''.join(text))
    binary = work / ('scalar-comparison.exe' if sys.platform == 'win32' else 'scalar-comparison')
    run([cc, '-std=c11', '-O2', source, '-o', binary], work / 'scalar-build.log')
    run([binary], work / 'scalar-run.log')
    return dict(status='passed', instructions=[v[1] for v in instructions],
                input_pairs=len(values) ** 2, cases=len(cases),
                references=['lasrecomp', 'nxrecomp', 'independent Python unsigned arithmetic'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--rustc', default=shutil.which('rustc'))
    parser.add_argument('--cc', default=shutil.which('clang'))
    args = parser.parse_args(argv)
    if not args.rustc or not args.cc: parser.error('provide --rustc and --cc')
    if args.work.exists(): parser.error('choose a new work directory; existing results are preserved')
    args.work.mkdir(parents=True)
    try:
        pins = [pull(args.sources, d) for d in sources()['donors']]
        checks = []
        for donor, path, edition in [('nxport', 'crates/lifter/src/lib.rs', '2021'),
                                      ('kirikae', 'crates/loader/src/lib.rs', '2024')]:
            binary = args.work / (donor + '-tests' + ('.exe' if sys.platform == 'win32' else ''))
            run([args.rustc, '--edition=' + edition, '--test', args.sources / donor / path, '-o', binary],
                args.work / (donor + '-build.log'))
            output = run([binary], args.work / (donor + '-tests.log'))
            summary = re.search(r'test result: ok\. (\d+) passed; (\d+) failed', output)
            if not summary or summary[2] != '0': raise ValueError('missing passing donor-test summary')
            checks.append(dict(donor=donor, passed=int(summary[1]), failed=0))
        result = dict(schema='decomp.wtf.switch-donor-validation/v1',
            scope='pinned donor tests and original scalar translation comparisons',
            sources=pins, unit_tests=checks, scalar_comparison=compare(args.sources, args.work, args.cc),
            retail=False, graphics=False)
        (args.work / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
