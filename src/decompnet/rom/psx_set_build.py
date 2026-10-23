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


def build(mod=False):
    if mod:
        shutil.rmtree(ROOT / "build/mod", ignore_errors=True)
    meta = json.loads((ROOT / "disc-set.json").read_text(encoding="utf-8"))
    if meta.get("format") != 1 or not 2 <= len(meta.get("discs", [])) <= 16:
        raise ValueError("invalid PS1 disc-set manifest")
    outputs, artifacts_by_disc = [], []
    for number, disc in enumerate(meta["discs"], 1):
        if disc["project"] != f"discs/disc-{number}":
            raise ValueError("disc projects and outputs must use their original numbered paths")
        artifacts = disc.get("artifacts") or [{"output": disc["output"], "size": disc["original_size"], "sha256": disc["sha256"]}]
        artifacts = [dict(item) for item in artifacts]
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
            if mod:
                item["output"] = "build/mod/" + name.removeprefix("build/")
                path = ROOT / item["output"]
            if path in outputs:
                raise ValueError("duplicate combined disc output")
            if ROOT / "build" not in path.resolve().parents:
                raise ValueError("a disc output is outside the combined project")
            outputs.append(path)
    report = ROOT / ("build/mod/disc-set-result.json" if mod else "build/disc-set-result.json")
    for path in [*outputs, report]:
        path.unlink(missing_ok=True)
    (ROOT / "build").mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix=".disc-set-") as temporary:
            for number, (disc, artifacts) in enumerate(zip(meta["discs"], artifacts_by_disc), 1):
                folder = ROOT / disc["project"]
                print(f"building disc {number} of {len(meta['discs'])}", flush=True)
                process = subprocess.run([sys.executable, "build.py", *(["mod"] if mod else [])], cwd=folder)
                if process.returncode:
                    raise ValueError(f"disc {number} failed {'modified build' if mod else 'matching verification'}")
                child = json.loads((folder / "build.json").read_text(encoding="utf-8"))
                modified = None
                if mod:
                    modified = json.loads((folder / "build/psx-mod-result.json").read_text(encoding="utf-8"))
                    if modified.get("format") != 1 or modified.get("mode") != "fixed-slots" or modified.get("baseline_identical") is not True:
                        raise ValueError("a modified child must verify its original assembly baseline")
                    if len(modified["artifacts"]) != len(artifacts):
                        raise ValueError("a modified child lost a retained disc track or CUE")
                published = []
                for item in artifacts:
                    original = folder / item.get("child", child["disc"]["output"])
                    expected = (item["size"], item["sha256"])
                    if mod:
                        media = child["disc"]["layout"].get("media", {})
                        name = ("disc/" + original.relative_to(folder / "build/disc-media").as_posix()) if media.get("kind") == "cue" else "disc" + original.suffix
                        original = folder / "build/psx-mod" / name
                        entry = next((a for a in modified["artifacts"] if a["output"] == original.relative_to(folder).as_posix()), None)
                        if entry is None or entry["size"] != item["size"]:
                            raise ValueError("a modified child changed its pinned disc/track sizes")
                        expected = (entry["size"], entry["sha256"])
                    if folder.resolve() not in original.resolve().parents:
                        raise ValueError("a child disc output is outside its project")
                    if digest(original) != expected:
                        raise ValueError(f"disc {number} differs from its {'modified build report' if mod else 'original full image or track set'}")
                    published.append({"output": item["output"], "size": expected[0], "sha256": expected[1]})
                    staged = Path(temporary) / Path(item["output"]).relative_to("build")
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, staged)
                if mod:
                    disc["modified"] = {"artifacts": published, "changed_functions": modified["changed_functions"]}
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
                (Path(temporary) / output.relative_to(ROOT / "build")).replace(output)
        result = ({"format": 1, "baseline_identical": True, "mode": "fixed-slots", "discs": [d["modified"] for d in meta["discs"]]}
                  if mod else {"identical": True, "discs": [d["output"] for d in meta["discs"]]})
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{'modified' if mod else 'identical'}: all {len(meta['discs'])} discs rebuilt from one source project")
        return 0
    except BaseException:
        for path in [*outputs, report]:
            path.unlink(missing_ok=True)
        if mod:
            shutil.rmtree(ROOT / "build/mod", ignore_errors=True)
        raise


if __name__ == "__main__":
    try:
        if sys.argv[1:] not in ([], ["mod"]):
            raise ValueError("usage: python build.py [mod]")
        raise SystemExit(build(mod=sys.argv[1:] == ["mod"]))
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"error: {error}")
