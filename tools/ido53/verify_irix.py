"""Compare native IDO 5.3 C++ with the original IRIX frontend and 5.3 backend.

Run with the project Python, after installing ido-5.3 and its native C++ overlay:
python -m tools.ido53.verify_irix --irix-root PATH/ido/5.3 --qemu PATH/qemu-irix

The IRIX root needs libC.so (link its supplied libC.a using the original IRIX ld).
QEMU is a reference harness only, never a runtime dependency of the application.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

from decompnet import cpp, toolchains
from tests.fixtures.generate_native_compiler_parity import describe_functions


def run(argv, **kwargs):
    result = subprocess.run(list(map(str, argv)), capture_output=True, timeout=60, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result


def compare(root, qemu, tc, fixtures, source_name, output_name, write_reference):
    frontend = root / "usr/lib/DCC/edgcpfe"
    source = (fixtures / source_name).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="ido53-irix-") as temporary:
        work = Path(temporary)
        path, obj = work / "func.cpp", work / "func.o"
        path.write_text(cpp.game_abi(source), encoding="utf-8", newline="\n")
        cmd = [tc / "NCC", "-c", *toolchains.get("ido-5.3").flags, "-v", path, "-o", obj]
        result = run(cmd, cwd=work)
        native = describe_functions(obj.read_bytes())
        # Replay exactly the commands selected by the authentic 5.3 NCC driver,
        # executing the unmodified IRIX frontend under QEMU. The backend stays
        # the same pinned 5.3 uopt/ugen/as1 used by the application.
        stages = []
        for line in result.stderr.decode().splitlines():
            if line.startswith("/usr/lib/DCC/"):
                stages.append(shlex.split(line))
        assert [Path(s[0]).name for s in stages] == ["edgcpfe", "uopt", "ugen", "as1"], stages
        for stage in stages:
            name = Path(stage[0]).name
            if name == "edgcpfe":
                redirect = stage.index(">")
                compiled = run([qemu, "-L", root, frontend, *stage[1:redirect]], cwd=work)
                Path(stage[redirect + 1]).write_bytes(compiled.stdout)
                # IRIX and the native port may leave different unused padding
                # in Ucode strings/records. Final code/relocations are compared
                # in full below; no instruction or relocation bits are masked.
            else:
                run([tc / name, *stage[1:]], cwd=work)
        original = describe_functions(obj.read_bytes())
        assert original == native, "Native code or relocations differ from the IRIX frontend"
    snapshot = {
        "toolchain": "ido-5.3", "frontend": "SGI/EDG 2.19 (IDO 5.3)", "language": "c++",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "flags": toolchains.get("ido-5.3").flags,
        "irix_frontend_sha256": hashlib.sha256(frontend.read_bytes()).hexdigest(),
        "functions": original,
    }
    expected = fixtures / output_name
    if write_reference:
        expected.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        assert json.loads(expected.read_text()) == snapshot
    print(f"{len(original)} functions match the original IRIX 5.3 C++ frontend: exact code and relocations")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--irix-root", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--write-reference", action="store_true")
    args = parser.parse_args()
    root, qemu = args.irix_root.resolve(), args.qemu.resolve()
    tc = toolchains.require("ido-5.3")
    fixtures = Path(__file__).resolve().parents[2] / "tests/fixtures"
    for source, output in [("native_compiler_parity.c", "ido53_cpp_compiler_parity.json"),
                           ("ido_cpp_features.cpp", "ido53_cpp_features_parity.json")]:
        compare(root, qemu, tc, fixtures, source, output, args.write_reference)


if __name__ == "__main__":
    main()
