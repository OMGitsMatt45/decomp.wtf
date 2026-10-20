"""Instantiate classic IDO 5.3 templates and link N64 objects natively.

First compile the translation units with classic-CC in a shared repository.
This command supplies the original ptlink's control files and uses the pinned
N64 GNU linker for a relocatable object, without an IRIX executable environment.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
import sys

from . import compiler, ido_cfront, toolchains


def prelink(work: Path, tc: Path, objects: list[str], output: Path, *,
            repository: str = 'ptrepository', includes: list[str] | None = None,
            flags: list[str] | None = None) -> None:
    work, tc, output = work.resolve(), tc.resolve(), output.resolve()
    includes = includes or ['.']
    flags = toolchains.get('ido-5.3').flags if flags is None else flags
    if why := ido_cfront.manifest_error(tc):
        raise ValueError(why)
    # Original ptlink constructs phase command strings. Relative names may
    # contain directories, but must remain representable by that old grammar.
    if not objects or any(any(c.isspace() for c in arg) for arg in [repository, *objects, *includes, *flags]):
        raise ValueError('Classic prelink needs object, repository, include and flag arguments without whitespace; the working directory itself may contain spaces')
    suffix = '.exe' if os.name == 'nt' else ''
    cfg = compiler.CompilerConfig([], sandbox='none', relative_paths=True)
    def execute(command):
        result = compiler._exec(cfg, work, list(map(str, command)), 120)
        if result.returncode or 'warning: nm' in result.stderr:
            raise RuntimeError(result.stdout + result.stderr or f'Classic prelink failed with exit {result.returncode}')
    with tempfile.TemporaryDirectory(prefix='.ido-prelink-', dir=work) as directory:
        temporary = Path(directory)
        relative = temporary.name
        data = dict(includes='\n'.join('-I' + p for p in includes), objects='\n'.join(objects),
                    options='\n'.join(flags), repositories=repository)
        for name, text in data.items():
            (temporary / name).write_text(text + '\n', encoding='utf-8', newline='\n')
        execute([tc / ('ptlink' + suffix), repository, relative, 'classic-CC',
                 relative + '/includes', relative + '/objects', relative + '/output', 'defmap',
                 relative + '/options', relative + '/repositories', '/usr/lib/acpp', '/usr/bin/nm', output.name])
        instantiated = (temporary / 'output').read_text(encoding='utf-8').splitlines()
        linker = tc.parent / 'binutils-mips' / ('mips-ps2-decompals-ld' + suffix)
        execute([linker, '-melf32ebmip', '-r', '-o', relative + '/linked.o', *objects, *instantiated])
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary / 'linked.o', output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path.cwd())
    parser.add_argument('--repository', default='ptrepository')
    parser.add_argument('--include', action='append')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('objects', nargs='+')
    argv = list(sys.argv[1:] if argv is None else argv)
    flags = None
    if '--' in argv:
        separator = argv.index('--')
        flags, argv = argv[separator + 1:], argv[:separator]
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else args.work / args.output
    try:
        prelink(args.work, toolchains.require('ido-5.3'), args.objects, output,
                repository=args.repository, includes=args.include, flags=flags or None)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
