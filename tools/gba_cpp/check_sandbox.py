"""Check that a managed Python and the GBA pipeline work inside bubblewrap."""

from pathlib import Path
import shutil

from decompnet import compiler, elfobj, project


def main():
    assert shutil.which("bwrap"), "bubblewrap must be installed for this check"
    cfg = project.compiler_config(Path.cwd(), {"kind": "rom", "platform": "gba", "compiler": {
        "toolchain": "agbcc", "sandbox": "bwrap"}})
    assert compiler._sandbox_mode(cfg) == "bwrap"
    source = """template<class T> T next(T value) { return value + 1; }
int sandbox_probe(int value) { return next(value); }
"""
    result = compiler.compile_source(cfg, "", source)
    assert result.ok, result.log
    fn = elfobj.extract_function(result.obj, "sandbox_probe")
    assert fn.arch == "thumb" and fn.code == bytes.fromhex("01307047")
    print("GBA C++ compiles inside bubblewrap with read-only Python, pipeline and toolchain paths")


if __name__ == "__main__":
    main()
