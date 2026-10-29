"""Require successful Windows operational checks for the exact release commit."""

import argparse
import json
import os
import urllib.request
from pathlib import Path


REQUIRED = {
    ".github/workflows/pc-foundation.yml": "foundation (windows-2022)",
    ".github/workflows/ds-static.yml": "static (windows-2022)",
    ".github/workflows/psx-native.yml": "standalone (windows-2022)",
    ".github/workflows/ps2-native-port.yml": "standalone (windows-2022)",
    ".github/workflows/gba-native.yml": "translated-core (windows-2022)",
    ".github/workflows/3ds-native.yml": "native-source (windows-2022)",
}


def get(path):
    request = urllib.request.Request("https://api.github.com/" + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "decompnet-release-gate"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--notes", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    runs = get(f"repos/{repo}/actions/runs?head_sha={args.sha}&per_page=100")["workflow_runs"]
    pending = set(REQUIRED)
    seen = set()
    links = []
    for run in runs:
        path = run.get("path")
        if (path not in REQUIRED or path in seen or run["head_sha"] != args.sha
                or run.get("head_branch") != "main"
                or run.get("event") not in {"push", "workflow_dispatch"}):
            continue
        # API results are newest first. A later failure must supersede an old pass.
        seen.add(path)
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        jobs = get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        passed = {job["name"] for job in jobs if job["conclusion"] == "success"}
        if REQUIRED[path] in passed:
            pending.remove(path)
            links.append(run["html_url"])
    if pending:
        raise SystemExit("release blocked: the exact main commit needs successful Windows checks: "
                         + ", ".join(sorted(pending)))
    notes = args.notes.read_text(encoding="utf-8")
    notes += "\n\nWindows operational verification:\n" + "".join(f"- {url}\n" for url in links)
    notes += f"\nTested commit: `{args.sha}`.\n"
    args.output.write_text(notes, encoding="utf-8")
    print(f"release allowed: application and all five Windows native-output checks passed for {args.sha}")


if __name__ == "__main__":
    main()
