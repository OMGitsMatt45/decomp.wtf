"""Generate a native port's reference with its pinned Linux compiler.

DECOMPNET_TOOLCHAINS=/path/to/linux/toolchains uv run python tests/fixtures/generate_native_compiler_parity.py
"""

import hashlib
import json
import argparse
from io import BytesIO
from pathlib import Path

from elftools.elf.elffile import ELFFile

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


def describe_data(obj):
    elf = ELFFile(BytesIO(obj))
    return {section.name: section.data().hex() for section in elf.iter_sections()
            if section.name in (".data", ".rdata", ".rodata", ".sdata")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", default=TOOLCHAIN)
    parser.add_argument("--output", type=Path, default=EXPECTED)
    parser.add_argument("--psx-modern-as", action="store_true",
                        help="Assemble GCC 2.8.1's $L labels with the pinned binutils-mips toolchain")
    args = parser.parse_args()
    if toolchains.current_platform() != "linux-x86_64":
        raise SystemExit("Generate this reference with the pinned Linux x86-64 compiler")
    config = project.compiler_config(HERE, {"compiler": {"toolchain": args.toolchain, "sandbox": "none"}})
    if args.psx_modern_as:
        prefix = (toolchains.require("binutils-mips") / "mips-ps2-decompals-").as_posix()
        config.cmd.insert(2, "-B" + prefix)
        config.cmd = ["-Wa,-EL,-mips1,-mabi=32" if arg == "-Wa,-EL" else arg for arg in config.cmd]
    source = SOURCE.read_text(encoding="utf-8")
    result = compiler.compile_source(config, "", source, trusted=True)
    if not result.ok:
        raise SystemExit(result.log)
    snapshot = {
        "toolchain": args.toolchain,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "flags": toolchains.get(args.toolchain).flags,
        "functions": describe_functions(result.obj),
    }
    if args.psx_modern_as:
        snapshot["assembler"] = {"toolchain": "binutils-mips", "flags": ["-EL", "-mips1", "-mabi=32"]}
    if args.toolchain.endswith("-psx"):
        snapshot["data_sections"] = describe_data(result.obj)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(snapshot['functions'])} Linux-reference functions to {args.output.name}")


if __name__ == "__main__":
    main()
