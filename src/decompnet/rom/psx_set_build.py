#!/usr/bin/env python3
"""Build and verify every disc of this PS1 source project with one command."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def digest(path):
    sha, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while data := source.read(1 << 20):
            sha.update(data)
            size += len(data)
    return size, sha.hexdigest()


def build():
    meta = json.loads((ROOT / "disc-set.json").read_text(encoding="utf-8"))
    if meta.get("format") != 1 or not 2 <= len(meta.get("discs", [])) <= 16:
        raise ValueError("invalid PS1 disc-set manifest")
    outputs, artifacts_by_disc = [], []
    for number, disc in enumerate(meta["discs"], 1):
        if disc["project"] != f"discs/disc-{number}":
            raise ValueError("disc projects and outputs must use their original numbered paths")
        artifacts = disc.get("artifacts") or [{"output": disc["output"], "size": disc["original_size"], "sha256": disc["sha256"]}]
        artifacts_by_disc.append(artifacts)
        for item in artifacts:
            name = item["output"]
            path = ROOT / name
            if Path(name).as_posix() != name or ".." in Path(name).parts:
                raise ValueError("a disc output must use a normalized relative path")
            if not (name in (f"build/disc-{number}.iso", f"build/disc-{number}.bin") or name.startswith(f"build/disc-{number}/")):
                raise ValueError("a disc output must use its original numbered path")
            if ROOT / "build" not in path.resolve().parents or ROOT not in (ROOT / disc["project"]).resolve().parents:
                raise ValueError("a disc path is outside the combined project")
            if path in outputs:
                raise ValueError("duplicate combined disc output")
            outputs.append(path)
    report = ROOT / "build/disc-set-result.json"
    for path in [*outputs, report]:
        path.unlink(missing_ok=True)
    (ROOT / "build").mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix=".disc-set-") as temporary:
            for number, (disc, artifacts) in enumerate(zip(meta["discs"], artifacts_by_disc), 1):
                folder = ROOT / disc["project"]
                print(f"building disc {number} of {len(meta['discs'])}", flush=True)
                process = subprocess.run([sys.executable, "build.py"], cwd=folder)
                if process.returncode:
                    raise ValueError(f"disc {number} failed matching verification")
                child = json.loads((folder / "build.json").read_text(encoding="utf-8"))
                for item in artifacts:
                    original = folder / item.get("child", child["disc"]["output"])
                    if folder.resolve() not in original.resolve().parents:
                        raise ValueError("a child disc output is outside its project")
                    if digest(original) != (item["size"], item["sha256"]):
                        raise ValueError(f"disc {number} differs from the original full image or track set")
                    staged = Path(temporary) / Path(item["output"]).relative_to("build")
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, staged)
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
                (Path(temporary) / output.relative_to(ROOT / "build")).replace(output)
        report.write_text(json.dumps({"identical": True, "discs": [d["output"] for d in meta["discs"]]}, indent=2), encoding="utf-8")
        print(f"identical: all {len(meta['discs'])} discs rebuilt from one source project")
        return 0
    except BaseException:
        for path in [*outputs, report]:
            path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(build())
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"error: {error}")
