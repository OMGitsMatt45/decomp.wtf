"""Require real C++ and original-IRIX code/relocation parity, without WSL/MSYS PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from decompnet import compiler, toolchains
from tests.fixtures.generate_native_compiler_parity import describe_functions


def main():
    tc = toolchains.require("ido-5.3")
    for path in Path(sys.argv[1]).iterdir():
        if path.is_file():
            shutil.copy2(path, tc / path.name)
    suffix = ".exe" if sys.platform == "win32" else ""
    cfg = compiler.CompilerConfig(
        [str(tc / f"NCC{suffix}"), "-c", *toolchains.get("ido-5.3").flags,
         "-I{include}", "{src}", "-o", "{obj}"],
        language="c++", c_linkage=True, sandbox="none", relative_paths=sys.platform == "win32")
    fixtures = Path(__file__).resolve().parents[2] / "tests/fixtures"
    if sys.platform == "win32":
        os.environ["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    start = subprocess.Popen
    def native_only(args, *positional, **kwargs):
        assert Path(args[0]).name.lower() not in ("wsl", "wsl.exe")
        return start(args, *positional, **kwargs)
    subprocess.Popen = native_only
    for source, reference in [("native_compiler_parity.c", "ido53_cpp_compiler_parity.json"),
                              ("ido_cpp_features.cpp", "ido53_cpp_features_parity.json")]:
        result = compiler.compile_source(cfg, "", (fixtures / source).read_text())
        assert result.ok, result.log
        expected = json.loads((fixtures / reference).read_text())
        assert describe_functions(result.obj) == expected["functions"], source
        print(f"Native IDO 5.3 C++: {len(expected['functions'])} functions match IRIX, including relocations")


if __name__ == "__main__":
    main()
