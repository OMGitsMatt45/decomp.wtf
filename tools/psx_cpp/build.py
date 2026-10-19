"""Build the original PS1 GCC C++ frontends as standalone native Windows programs.

The source inputs are complete GPL source distributions accompanying the already
published C ports. Versions and PSX target patches are kept distinct.
"""

import argparse
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

INPUTS = {
    "2.7.2": (
        "https://raw.githubusercontent.com/OMGitsMatt45/decomp.wtf/0bc677de652e56dbf4e1679f2c2a3a65a13fd51c/toolchains/windows/v1/gcc-2.7.2-psx-windows-x86_64-v2.zip",
        "4326ee391705dd30ca4abcacaaf88f4ac041e269e02e43ec6b0cd600aec38653",
        "psx-272-corresponding-source.tar.gz"),
    "2.8.1": (
        "https://raw.githubusercontent.com/OMGitsMatt45/decomp.wtf/b491bf3f8d89554a0d009bf53a4aea57b79999e7/toolchains/windows/v1/gcc-2.8.1-psx-windows-i686.zip",
        "537a94a7b33c4be8ef504094b3522f1f137069391453def60c75199eec21c47d",
        "corresponding-source.tar.gz"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=INPUTS, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mingw-bin", type=Path, default=Path("/usr/bin"))
    args = parser.parse_args()
    work, output = args.work.resolve(), args.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    short = args.version.replace(".", "")
    cached = work / f"psx-{short}-c.zip"
    url, digest, source_name = INPUTS[args.version]
    if not cached.exists():
        urllib.request.urlretrieve(url, cached)
    if hashlib.sha256(cached.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Source package checksum mismatch")
    source = work / "source"
    source.mkdir(exist_ok=False)
    with zipfile.ZipFile(cached) as package:
        source_bytes = package.read(source_name)
        with tarfile.open(fileobj=io.BytesIO(source_bytes)) as archive:
            archive.extractall(source, filter="data")
    recipe = Path(__file__).resolve().parent
    script = recipe.parent / "windows" / f"build-psx{short}.py"
    source_arg = source / ("gcc-2.7.2" if args.version == "2.7.2" else "gcc-2.8.1.tar.gz")
    built = work / "built"
    subprocess.run([sys.executable, str(script), "--source", str(source_arg), "--patches", str(source / "old-gcc-patches"),
        "--work", str(work / "compiler"), "--output", str(built), "--mingw-bin", str(args.mingw_bin.resolve()),
        "--jobs", "4", "--with-cpp"], check=True)
    package = work / "package"
    (package / "cpp-source" / "recipe" / "windows").mkdir(parents=True)
    shutil.copytree(recipe, package / "cpp-source/recipe/psx_cpp", ignore=shutil.ignore_patterns("__pycache__"))
    for name in (script.name, "windows_spawn.c"):
        shutil.copyfile(script.parent / name, package / "cpp-source/recipe/windows" / name)
    (package / "cpp-source" / source_name).write_bytes(source_bytes)
    # 2.7.2 overlays its existing C suite. 2.8.1 adds the whole native suite,
    # which main previously lacked; the separate PlayStation PR is not merged.
    binaries = ["cc1plus.exe"] if args.version == "2.7.2" else ["gcc.exe", "cpp.exe", "cc1.exe", "cc1plus.exe"]
    strip = args.mingw_bin / "i686-w64-mingw32-strip"
    for name in binaries:
        shutil.copyfile(built / name, package / name)
        subprocess.run([str(strip), "--strip-all", str(package / name)], check=True)
    shutil.copyfile(built / "COPYING", package / "COPYING-CPP")
    (package / "CPP-SOURCE.txt").write_text(f"""Original GCC {args.version} PS1 C++ frontend, native Windows PE32.
Target patches: decompals/old-gcc cf70ec58bce58128732062bc9930045c82904cbb (release 0.17).
No target optimization or code-generation algorithms are changed. No compiler version is substituted.
Host fixes: modern varargs headers, Windows CRT quoting/wait status and temporary files.
GPL-2.0-or-later. Complete corresponding source, target patches and recipe are in cpp-source/.
Build on Linux with Python, GCC, make, patch and i686 MinGW:
python cpp-source/recipe/psx_cpp/build.py --version {args.version} --work NEW_WORK --output OUTPUT
Source input: {url}
SHA256: {digest}
Windows execution needs no WSL, MSYS or Cygwin runtime.
""", encoding="utf-8")
    archive = output / f"psx-{args.version}-cpp-windows.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(package.iterdir()):
            tar.add(path, arcname=path.name)
    print(archive.name, hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
