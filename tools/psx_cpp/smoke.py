"""Verify candidate Windows C++ frontends against pinned Linux code and relocations."""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from decompnet import compiler, toolchains
from tests.fixtures.generate_native_compiler_parity import describe_functions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("2.7.2", "2.8.1"), required=True)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    windows = sys.platform == "win32"
    tcid = f"gcc-{args.version}-psx"
    if windows and args.version == "2.8.1":
        root = args.package.resolve()
    else:
        root = toolchains.require(tcid)
        if windows:
            shutil.copyfile(args.package / "cc1plus.exe", root / "cc1plus.exe")
    suffix = ".exe" if windows else ""
    command = [str(root / f"gcc{suffix}"), f"-B{root.as_posix()}/"]
    if args.version == "2.8.1":
        tools = toolchains.require("binutils-mips")
        command += [f"-B{tools.as_posix()}/mips-ps2-decompals-"]
    command += ["-c", "-Wa,-EL" if args.version == "2.7.2" else "-Wa,-EL,-mips1,-mabi=32", "-O2", "-G8"]
    cfg = compiler.CompilerConfig(command + ["-I{include}", "{src}", "-o", "{obj}"], sandbox="none")
    cfg = replace(cfg, language="c++", c_linkage=True, cmd=[*cfg.cmd[:1], "-fconserve-space", "-x", "c++",
        "-fno-handle-exceptions" if args.version == "2.7.2" else "-fno-exceptions", "-fno-rtti", *cfg.cmd[1:]])
    if windows:
        os.environ["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    start = subprocess.Popen

    def native_only(argv, *positional, **kwargs):
        assert Path(argv[0]).name.lower() not in ("wsl", "wsl.exe", "bash", "bash.exe", "sh", "sh.exe")
        return start(argv, *positional, **kwargs)

    subprocess.Popen = native_only
    fixtures = Path(__file__).resolve().parents[2] / "tests/fixtures"
    result = compiler.compile_source(cfg, "", (fixtures / "psx_cpp_features.cpp").read_text())
    assert result.ok, result.log
    reference = json.loads((fixtures / f"psx{args.version.replace('.', '')}_cpp_parity.json").read_text())
    assert describe_functions(result.obj) == reference["functions"]
    assert not compiler.compile_source(cfg, "", "int broken() { return no_such_identifier; }").ok
    print(f"{'Windows' if windows else 'Linux'} PS1 GCC {args.version} C++: "
          "templates, classes, constructors, references, overloads, floats, data and relocations match Linux")


if __name__ == "__main__":
    main()
