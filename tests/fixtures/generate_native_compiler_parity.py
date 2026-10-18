"""Generate the native port's reference with the pinned Linux KMC compiler.

DECOMPNET_TOOLCHAINS=/path/to/linux/toolchains uv run python tests/fixtures/generate_native_compiler_parity.py
"""

import hashlib
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
    if toolchains.current_platform() != "linux-x86_64":
        raise SystemExit("Generate this reference with the pinned Linux x86-64 KMC compiler")
    config = project.compiler_config(HERE, {"compiler": {"toolchain": TOOLCHAIN, "sandbox": "none"}})
    source = SOURCE.read_text(encoding="utf-8")
    result = compiler.compile_source(config, "", source, trusted=True)
    if not result.ok:
        raise SystemExit(result.log)
    snapshot = {
        "toolchain": TOOLCHAIN,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "flags": toolchains.get(TOOLCHAIN).flags,
        "functions": describe_functions(result.obj),
    }
    EXPECTED.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(snapshot['functions'])} Linux-reference functions to {EXPECTED.name}")


if __name__ == "__main__":
    main()
