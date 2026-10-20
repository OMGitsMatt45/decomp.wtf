"""Require native C++ language features and agbcc code/relocation parity."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from decompnet import compiler, toolchains
from decompnet.elfobj import extract_function
from decompnet.project import compiler_config


def check(variant):
    package = Path(sys.argv[1]).resolve()
    tc = toolchains.require("agbcc")
    arm = toolchains.require("arm-gnu")
    suffix = ".exe" if sys.platform == "win32" else ""
    cfg = compiler_config(Path.cwd(), {"compiler": {"toolchain": "agbcc", "language": "c", "sandbox": "none"}})
    pipeline = [
        sys.executable, "-m", "decompnet.agbcc", "--cpp", str(arm / f"bin/arm-none-eabi-cpp{suffix}"),
        "--cc", str(tc / f"bin/{variant}{suffix}"), "--as", str(arm / f"bin/arm-none-eabi-as{suffix}"),
        "--builtin-include", str(tc / "include"), "--src", "{src}",
        "--obj", "{obj}", "--include", "{include}", "--", "-mthumb-interwork", "-O2"]
    cfg = replace(cfg, cmd=pipeline)
    cpp = replace(cfg, language="c++", c_linkage=True, cmd=[
        a.replace(str(tc / f"bin/{variant}{suffix}"), str(package / f"{variant}-cpp{suffix}"))
        for a in pipeline[:-3]] + ["--language", "c++", "--", "-mthumb-interwork", "-O2", "-fno-exceptions", "-fno-rtti"])
    if sys.platform == "win32":
        os.environ["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    start = subprocess.Popen

    def native_only(args, *positional, **kwargs):
        assert Path(args[0]).name.lower() not in ("wsl", "wsl.exe", "bash", "sh", "bash.exe", "sh.exe")
        return start(args, *positional, **kwargs)

    subprocess.Popen = native_only
    header = "extern int total;\nextern int callback(int);\n"
    c_source = "int probe(int x) { return callback(x + 1) + total; }\n"
    cpp_source = """template<class T> class Counter {
public: T value; Counter(T x) : value(x) {} T next() const { return value + 1; }
};
template<class T> inline T next(T x) { const Counter<T> c(x); const T &ref = c.value; return ref + 1; }
int probe(int x) { return callback(next(x)) + total; }
"""
    c, result = compiler.compile_source(cfg, header, c_source), compiler.compile_source(cpp, header, cpp_source)
    assert c.ok, c.log
    assert result.ok, result.log
    original, converted = extract_function(c.obj, "probe"), extract_function(result.obj, "probe")
    assert converted.code == original.code
    assert converted.relocs == original.relocs
    assert {r.symbol for r in converted.relocs} >= {"callback", "total"}
    assert not compiler.compile_source(cfg, header, cpp_source).ok, "C frontend accepted C++ syntax"
    assert not compiler.compile_source(cpp, "", "int broken() { int &ref = 1; return ref; }").ok
    print(f"Native {variant}-cpp: templates, constructors, classes and references; C code and relocation parity; invalid C++ rejected")


if __name__ == "__main__":
    for variant in ("agbcc", "old_agbcc"):
        check(variant)
