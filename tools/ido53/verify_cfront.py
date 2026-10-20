"""Check classic cfront against its unmodified IRIX frontend (QEMU is reference-only)."""

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

from decompnet import compiler, project, toolchains
from tests.fixtures.generate_native_compiler_parity import describe_functions

FRONTEND_SHA256 = "9ebe0d0aa3827f8d671ac6fcee7bd1cc7698b8e35af2905e4b19e3baaec54651"
SOURCES = ("native_compiler_parity.c", "ido_cpp_features.cpp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--irix-root", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--write-reference", action="store_true")
    args = parser.parse_args()
    root, qemu = args.irix_root.resolve(), args.qemu.resolve()
    frontend = root / "usr/lib/c++/cfront"
    assert hashlib.sha256(frontend.read_bytes()).hexdigest() == FRONTEND_SHA256
    fixtures = Path(__file__).resolve().parents[2] / "tests/fixtures"
    cfg = project.compiler_config(Path.cwd(), {"kind": "rom", "platform": "n64", "compiler": {
        "toolchain": "ido-5.3", "cpp_frontend": "cfront", "sandbox": "none"}})
    tc = toolchains.require("ido-5.3")
    with tempfile.TemporaryDirectory(prefix="ido53-irix-cfront-") as temporary:
        # The original CC driver and 5.3 backend stay identical. Only the
        # candidate cfront process is replaced by the unmodified IRIX program.
        reference = Path(temporary)
        for name in ("classic-CC", "cc", "acpp", "cfe", "uopt", "ugen", "as1", "ptcomp", "markc++", "err.english.cc"):
            shutil.copy2(tc / name, reference / name)
        wrapper = reference / "cfront"
        # Fit QEMU's guest reservation inside the application's normal 2 GiB
        # limit. This affects the reference harness, never the native compiler.
        command = [qemu, "-R", "0x60000000", "-L", root, frontend]
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(list(map(str, command))) + ' "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        ref_cmd = cfg.cmd.copy()
        ref_cmd[ref_cmd.index("--driver") + 1] = str(reference / "classic-CC")
        original_cfg = dataclasses.replace(cfg, cmd=ref_cmd)
        for name in SOURCES:
            source = (fixtures / name).read_text(encoding="utf-8")
            native = compiler.compile_source(cfg, "", source)
            original = compiler.compile_source(original_cfg, "", source)
            assert native.ok, native.log
            assert original.ok, original.log
            functions = describe_functions(original.obj)
            assert functions and describe_functions(native.obj) == functions, name
            snapshot = {
                "toolchain": "ido-5.3", "cpp_frontend": "cfront", "language": "c++",
                "irix_frontend_sha256": FRONTEND_SHA256,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "flags": toolchains.get("ido-5.3").flags, "functions": functions,
            }
            path = fixtures / ("ido53_cfront_compiler_parity.json" if name.endswith(".c") else "ido53_cfront_features_parity.json")
            if args.write_reference:
                path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
            else:
                assert json.loads(path.read_text(encoding="utf-8")) == snapshot
            print(f"Classic IDO 5.3: {len(functions)} functions match IRIX exactly, including relocations ({name})")
        # Also compare the intermediate C text; no normalization or bit masks.
        source = fixtures / "ido_cpp_features.cpp"
        preprocessed = subprocess.run([tc / "classic-CC", "-E", source], capture_output=True, check=True).stdout
        commands = [[tc / "cfront", "+n", "+ffeatures.C"], [*command, "+n", "+ffeatures.C"]]
        translations = [subprocess.run(c, input=preprocessed, capture_output=True, check=True).stdout for c in commands]
        assert translations[0] == translations[1]
        print("Classic cfront C translation matches the original IRIX output byte for byte")
        from tools.ido53.prelink_probe import run, DEFINITION
        work = reference / "cross-unit"
        run(work, tc)
        (work / "counter.c").write_text(DEFINITION, encoding="utf-8", newline="\n")
        generated = "ptrepository/Counter__pt__2_i.c"
        preprocessed = subprocess.run([tc / "classic-CC", "-E", "-I.", generated], cwd=work,
                                      capture_output=True, check=True).stdout
        options = ["+n", "+fCounter__pt__2_i.c", "+Tprelink-temp/instfile"]
        translations = [subprocess.run([*c, *options], cwd=work, input=preprocessed,
                                        capture_output=True, check=True).stdout
                        for c in ([tc / "cfront"], command)]
        assert translations[0] == translations[1]
        assert b"next__16Counter__pt__2_iCFv" in translations[0]
        print("Cross-unit template instantiation C translation matches original IRIX byte for byte")



if __name__ == "__main__":
    main()
