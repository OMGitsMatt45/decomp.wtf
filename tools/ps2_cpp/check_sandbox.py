"""Check that a managed Python and the PS2 C++ driver work inside bubblewrap."""

from pathlib import Path
from dataclasses import replace
import shutil

from decompnet import compiler, elfobj, project


def main():
    assert shutil.which("bwrap"), "bubblewrap must be installed for this check"
    cfg = project.compiler_config(Path.cwd(), {"kind": "rom", "platform": "ps2", "compiler": {
        "toolchain": "ee-gcc-2.96", "sandbox": "bwrap"}})
    assert compiler._sandbox_mode(cfg) == "bwrap"
    source = """template<class T> T next(T value) { return value + 1; }
int sandbox_probe(int value) { return next(value); }
"""
    result = compiler.compile_source(cfg, "", source)
    assert result.ok, result.log
    native = compiler.compile_source(replace(cfg, sandbox="none"), "", source)
    assert native.ok, native.log
    fn = elfobj.extract_function(result.obj, "sandbox_probe")
    reference = elfobj.extract_function(native.obj, "sandbox_probe")
    assert fn.arch == "mips" and fn.code == reference.code and fn.relocs == reference.relocs
    print("Original EE-GCC 2.96 C++ compiles inside bubblewrap with the pinned i386 runtime")


if __name__ == "__main__":
    main()
