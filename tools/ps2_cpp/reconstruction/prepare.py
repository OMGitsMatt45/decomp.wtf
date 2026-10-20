"""Prepare the failed EE 2.96 reconstruction experiment, never a production toolchain.

Inputs stay external: pinned GNU sources, the available older EE source, and the
user's recovered SDK patch/installed headers. No SDK program is executed here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path: Path, expected: str) -> None:
    if digest(path) != expected:
        raise ValueError(f"Unexpected input SHA-256: {path}")


def initial_tree(archive: Path, ee: Path, sdk: Path, out: Path, pins: dict) -> Path:
    """Reproduce the state before our compatibility patch, retaining Sony rejects."""
    checked(archive, pins["gnu_archive"]["sha256"])
    checked(sdk / "sce-patch", pins["sony_patch_sha256"])
    for name, sha in pins["ee_files"].items():
        checked(ee / name, sha)
    for name, sha in pins["sdk_headers"].items():
        checked(sdk / name, sha)
    if out.exists():
        raise ValueError(f"Output already exists; use a fresh directory: {out}")
    out.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        prefix = "gcc-" + pins["gnu_archive"]["commit"]
        for member in members:
            parts = Path(member.name).parts
            if not parts or parts[0] != prefix or ".." in parts or Path(member.name).is_absolute():
                raise ValueError(f"Unexpected archive member: {member.name}")
        tar.extractall(out, filter="data")
    source = out / prefix
    for name in pins["ee_files"]:
        if name.startswith("config/mips/"):
            target = source / "gcc" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ee / name, target)
    (source / "gcc/config/mips/mips-protos.h").unlink(missing_ok=True)
    entry = '''\tmips64r5900*-*-elf*)
\t\ttarget_cpu_default="MASK_SINGLE_FLOAT | MASK_MIPS5900"
\t\ttm_file="mips/elf5900.h libgloss.h"
\t\ttmake_file=mips/t-r5900
\t\tuse_collect2=yes
\t\t;;
'''
    for name in ("configure", "configure.in"):
        path = source / "gcc" / name
        text = path.read_text()
        marker = "\tmips64-*-elf*)"
        if text.count(marker) != 1:
            raise ValueError(f"Target configuration context changed: {path}")
        path.write_text(text.replace(marker, entry + marker))
    for name in ("mips.h", "mips.c"):
        path = source / "gcc/config/mips" / name
        path.write_text("#ifndef PROTO\n#define PROTO(ARGS) PARAMS(ARGS)\n#endif\n" + path.read_text())
    version = source / "gcc/version.c"
    version.write_text(re.sub(r'"2\.96[^"\n]*"',
        '"2.96 20000914 (EE reconstruction experiment; NOT Sony 2.96-ee-001003-1)"',
        version.read_text()))
    # Select exactly the GCC sections. Binutils/newlib patches are outside this
    # frontend experiment. Keep failed hunks visible instead of dropping them.
    sections = re.split(r"(?m)(?=^Index: )", (sdk / "sce-patch").read_text())
    payload = "".join(s for s in sections if s.startswith("Index: GNUPro/src/gcc/"))
    selected = out / "sony-gcc.patch"
    selected.write_text(payload)
    checked(selected, pins["sony_gcc_patch_sha256"])
    result = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p3",
        "-d", str(source / "gcc"), "-i", str(selected)], capture_output=True, text=True)
    (out / "sony-patch.log").write_text(result.stdout + result.stderr)
    if result.returncode != 1:
        raise ValueError(f"Unexpected partial patch status: {result.returncode}")
    rejects = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob("*.rej"))}
    if rejects != pins["sony_rejects"]:
        raise ValueError("Sony patch rejects differ from the measured experiment")
    return source


def prepare(archive: Path, ee: Path, sdk: Path, out: Path) -> Path:
    pins = json.loads((HERE / "inputs.json").read_text())
    source = initial_tree(archive, ee, sdk, out, pins)
    shutil.copyfile(ee / "config/host_wint.h", source / "gcc/config/host_wint.h")
    for name in pins["sdk_headers"]:
        shutil.copyfile(sdk / name, source / "gcc/config/mips" / Path(name).name)
    subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1",
        "-d", str(source), "-i", str(HERE / "compat.patch")], check=True)
    actual = {name: digest(source / name) for name in pins["prepared_files"]}
    if actual != pins["prepared_files"]:
        raise ValueError("Prepared source differs from the measured experiment")
    (out / "prepared-files.json").write_text(json.dumps(actual, indent=2) + "\n")
    # Checked-in configure is edited alongside configure.in. Avoid invoking an
    # unavailable modern autoconf on this old tree, including with clock skew.
    for name in ("gcc/configure", "gcc/config.in", "gcc/cstamp-h.in"):
        (source / name).touch()
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gnu-archive", type=Path, required=True)
    parser.add_argument("--ee-source", type=Path, required=True, help="pinned checkout's ee/gcc directory")
    parser.add_argument("--sdk", type=Path, required=True, help="recovered sce/ee/gcc directory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.gnu_archive.resolve(), args.ee_source.resolve(), args.sdk.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
