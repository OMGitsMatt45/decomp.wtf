"""Build source/install assets and checksums beside uv's wheel and sdist."""

import argparse
import hashlib
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert args.tag == f"v{version}" and re.fullmatch(r"\d+\.\d+\.\d+", version), "release tag/version mismatch"
    assert f'__version__ = "{version}"' in (root / "src/decompnet/__init__.py").read_text(encoding="utf-8")
    out = root / "dist"
    assert (out / f"decompnet-{version}-py3-none-any.whl").is_file(), "build the wheel first"
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    with zipfile.ZipFile(out / f"decompnet-{version}-windows.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            if not name or not (root / name).is_file():
                continue
            data = (root / name).read_bytes()
            if name.endswith(".cmd"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            archive.writestr(f"decompnet-{version}/{name}", data)
    for name in ("install.ps1", "install.sh"):
        shutil.copyfile(root / "site/public" / name, out / name)
    checksums = []
    for path in sorted(out.iterdir()):
        if path.is_file() and not path.name.startswith('.') and path.name != "SHA256SUMS":
            checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (out / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print("\n".join(checksums))


if __name__ == "__main__":
    main()
