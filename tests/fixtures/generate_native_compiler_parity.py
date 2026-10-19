"""Generate the native port's reference with a pinned Linux period compiler.

DECOMPNET_TOOLCHAINS=/path/to/linux/toolchains uv run python tests/fixtures/generate_native_compiler_parity.py
"""

import hashlib
import argparse
import json
from pathlib import Path

from decompnet import compiler, elfobj, project, toolchains

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "native_compiler_parity.c"
EXPECTED = HERE / "native_compiler_parity.json"
TOOLCHAIN = "gcc-2.7.2-kmc"


def describe_functions(obj):
    result = {}
    for name in sorted(elfobj.list_functions(obj)):
        function = elfobj.extract_function(obj, name)
        result[name] = {
            "arch": function.arch,
            "big_endian": function.big_endian,
            "code": function.code.hex(),
            "relocations": [reloc.to_json() for reloc in function.relocs],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=["c", "c++"], default="c")
    parser.add_argument("--toolchain", choices=[TOOLCHAIN, "ido-7.1"], default=TOOLCHAIN)
    args = parser.parse_args()
    if toolchains.current_platform() != "linux-x86_64":
        raise SystemExit("Generate this reference with the pinned Linux x86-64 compiler")
    config = project.compiler_config(HERE, {"kind": "rom", "platform": "n64", "compiler": {
        "toolchain": args.toolchain, "language": args.language, "sandbox": "none"}})
    source = SOURCE.read_text(encoding="utf-8")
    result = compiler.compile_source(config, "", source, trusted=True)
    if not result.ok:
        raise SystemExit(result.log)
    snapshot = {
        "toolchain": args.toolchain,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "flags": toolchains.get(args.toolchain).flags,
        "language": args.language,
        "functions": describe_functions(result.obj),
    }
    expected = HERE / "native_cpp_compiler_parity.json" if args.language == "c++" else EXPECTED
    if args.toolchain == "ido-7.1":
        expected = HERE / ("ido71_cpp_compiler_parity.json" if args.language == "c++" else "ido71_compiler_parity.json")
    expected.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(snapshot['functions'])} Linux-reference functions to {expected.name}")


if __name__ == "__main__":
    main()
