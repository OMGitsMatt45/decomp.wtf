#!/usr/bin/env python3
"""Build the old-gcc 0.17 PSX GCC 2.7.2 C compiler as native Win32 PE.

Inputs: GNU GCC 2.7.2 sources (or AzureFlute/gcc-2.7.2 commit
2d758772bde54b0161ad380d11da13efdebfd261), old-gcc 0.17 patch directory,
and an i686-w64-mingw32 cross compiler. No compiler optimization passes are changed.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess

SPAWN = r'''/* Windows CRT argument quoting. Host compatibility only. */
#include <process.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static int spawn_quoted(int search, int mode, const char *program, char **argv) {
  int n, i, result; char **quoted;
  for (n=0; argv[n]; ++n) {}
  quoted = (char **) calloc(n+1, sizeof(char *));
  if (!quoted) { errno=ENOMEM; return -1; }
  for (i=0; i<n; ++i) {
    const char *src=argv[i]; char *dst;
    quoted[i]=(char *)malloc(2*strlen(src)+3);
    if (!quoted[i]) { result=-1; errno=ENOMEM; goto done; }
    dst=quoted[i]; *dst++='"';
    while (*src) {
      int slashes=0;
      while (*src=='\\') { ++slashes; ++src; }
      if (*src=='"' || !*src) { slashes*=2; }
      while (slashes--) *dst++='\\';
      if (!*src) break;
      if (*src=='"') *dst++='\\';
      *dst++=*src++;
    }
    *dst++='"'; *dst=0;
  }
  result=(int)(search ? _spawnvp(mode,program,(const char *const *)quoted) : _spawnv(mode,program,(const char *const *)quoted));
done:
  for (i=0;i<n;++i) free(quoted[i]); free(quoted); return result;
}
int windows_spawnv(int mode,const char *program,char **argv){return spawn_quoted(0,mode,program,argv);}
int windows_spawnvp(int mode,const char *program,char **argv){return spawn_quoted(1,mode,program,argv);}
'''


def edit(path, before, after, count=1):
    text=path.read_text()
    if text.count(before) != count:
        raise RuntimeError(f'{path}: expected {count} occurrences of {before!r}')
    path.write_text(text.replace(before, after))


def build(source: Path, patches: Path, work: Path, output: Path, mingw_bin: Path, jobs: int, with_cpp: bool = False):
    if work.exists():
        raise RuntimeError(f'build directory already exists: {work}')
    shutil.copytree(source, work, ignore=shutil.ignore_patterns('.git'))
    env=dict(os.environ, PATH=str(mingw_bin)+os.pathsep+os.environ['PATH'])
    def run(argv, **kwargs):
        subprocess.run([str(a) for a in argv], cwd=work, env=env, check=True, **kwargs)
    for p in (work.rglob('*.c') if with_cpp else work.glob('*.c')):
        p.write_text(p.read_text().replace('include <varargs.h>', 'include <stdarg.h>'))
    # Restore the original expression when using the mirror import, which
    # contains an incomplete host obstack change; then apply the upstream fix.
    p=work/'obstack.h'; text=p.read_text()
    begin=text.index('#define obstack_ptr_grow(OBSTACK,datum)')
    end=text.index('#define obstack_int_grow(OBSTACK,datum)', begin)
    block=text[begin:end]
    if '*((void **)__o->next_free)++ = ((void *)datum);' not in block:
        import re
        block=re.sub(r'     \*\(\(void \*\*\)__o->next_free\) = \(\(void \*\)datum\);.*?\n     __o->next_free \+= sizeof \(void \*\);[^\n]*\n', '     *((void **)__o->next_free)++ = ((void *)datum);\t\t\t\\\n', block, flags=re.S)
        if '*((void **)__o->next_free)++ = ((void *)datum);' not in block:
            raise RuntimeError('unrecognized obstack source')
        p.write_text(text[:begin]+block+text[end:])
    # Git checkouts can make grammar inputs newer than release-generated files.
    for generated in ['c-parse.c','c-parse.h','c-gperf.h','cexp.c']:
        os.utime(work/generated,None)
    if with_cpp:
        for generated in ['cp/parse.c', 'cp/parse.h', 'cp/hash.h']:
            os.utime(work/generated, None)
    for name, patch in [('obstack.h','obstack-2.7.2.h.patch'),('configure','configure.patch'),('config.sub','config.sub.patch'),('config/mips/mips.h','mipsel-2.7.patch')]:
        run(['patch','-u','-p1',name,'-i',patches/patch])
    with (patches/'psx-2.5.7.patch').open() as inp:
        run(['patch','-su','-p1'],stdin=inp)
    edit(work/'gcc.c', 'int __spawnv ();\nint __spawnvp ();', '#define __spawnv windows_spawnv\n#define __spawnvp windows_spawnvp\nextern int windows_spawnv ();\nextern int windows_spawnvp ();')
    edit(work/'gcc.c', 'pid = cwait (&status, commands[i].pid, WAIT_CHILD);', 'pid = _cwait (&status, commands[i].pid, _WAIT_CHILD);\n        status = status ? (MIN_FATAL_STATUS << 8) : 0;')
    # HAVE_STRERROR makes these obsolete CRT data imports unnecessary.
    edit(work/'gcc.c', 'if (errno < sys_nerr)', 'if (errno >= 0)', count=3)
    p=work/'config/mips/mips.c'
    edit(p, '  int len;\n\n  if (base == (char *)0)\n', '''  int len;

#ifdef _WIN32
  if (base == (char *)0 || *base == 0)
    base = getenv ("TEMP");
  if (base == (char *)0 || *base == 0)
    base = getenv ("TMP");
  if (base == (char *)0 || *base == 0)
    base = ".";
#endif

  if (base == (char *)0)
''')
    edit(p, '#ifndef __MSDOS__\n  /* In MSDOS, we cannot unlink', '#if !defined(__MSDOS__) && !defined(_WIN32)\n  /* In MSDOS and Windows, we cannot unlink')
    edit(p, '#ifdef __MSDOS__\n      unlink (temp_filename);', '#if defined(__MSDOS__) || defined(_WIN32)\n      unlink (temp_filename);')
    (work/'windows_spawn.c').write_text(SPAWN)
    with (work/'configure-windows.log').open('w') as log:
        run(['./configure','--host=i386-pc-winnt3.5','--build=i386-pc-linux','--target=mips-sony-psx','--with-endian-little','--with-gnu-as','--prefix=/decompnet'], stdout=log, stderr=subprocess.STDOUT)
    run(['i686-w64-mingw32-gcc','-c','windows_spawn.c','-o','windows_spawn.o'])
    with (work/'build-windows.log').open('w') as log:
        run(['make',f'-j{jobs}','CC=i686-w64-mingw32-gcc','HOST_CC=gcc','HOST_PREFIX=build-','HOST_PREFIX_1=build-','HOST_CFLAGS=-std=gnu89 -O2 -w','HOST_LDFLAGS=','CFLAGS=-std=gnu89 -O2 -w -DHAVE_STRERROR','LDFLAGS=-static windows_spawn.o','cpp','cc1','xgcc'],stdout=log,stderr=subprocess.STDOUT)
        if with_cpp:
            flags = [f'-j{jobs}', 'CC=i686-w64-mingw32-gcc', 'HOST_CC=gcc', 'HOST_PREFIX=build-',
                     'HOST_PREFIX_1=build-', 'HOST_CFLAGS=-std=gnu89 -O2 -w', 'HOST_LDFLAGS=',
                     'CFLAGS=-std=gnu89 -O2 -w -DHAVE_STRERROR', f'LDFLAGS=-static {work / "windows_spawn.o"}']
            run(['make', *flags, 'stamp-objlist'], stdout=log, stderr=subprocess.STDOUT)
            inventory = work / 'stamp-objlist'
            inventory.write_text(inventory.read_text().replace('.obj', '.o'))
            run(['make', *flags, 'cc1plus'], stdout=log, stderr=subprocess.STDOUT)
    output.mkdir(parents=True,exist_ok=True)
    for src,dst in [('xgcc.exe','gcc.exe'),('cpp.exe','cpp.exe'),('cc1.exe','cc1.exe'),('COPYING','COPYING')]:
        shutil.copyfile(work/src,output/dst)
    if with_cpp:
        shutil.copyfile(work/'cc1plus.exe', output/'cc1plus.exe')
    (output/'SOURCE.txt').write_text('GCC 2.7.2, GPL-2.0-or-later.\nTarget patches: https://github.com/decompals/old-gcc/tree/cf70ec58bce58128732062bc9930045c82904cbb/patches\nBase source: GNU gcc-2.7.2.tar.gz, SHA256 7cd8bce5c3aeec59a72ecc2d3d5123864a817b14cdbd0680b1a969c3bccc5da5\nBuildable mirror import: https://github.com/AzureFlute/gcc-2.7.2/tree/2d758772bde54b0161ad380d11da13efdebfd261\nHost changes and build command: build_psx272.py distributed with corresponding source.\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ['source','patches','work','output','mingw-bin']:
        parser.add_argument('--'+arg,required=True,type=lambda p:Path(p).resolve())
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--with-cpp', action='store_true', help='also build the original GCC 2.7.2 C++ frontend')
    args=parser.parse_args()
    build(args.source,args.patches,args.work,args.output,args.mingw_bin,args.jobs,args.with_cpp)

if __name__=='__main__':
    main()
