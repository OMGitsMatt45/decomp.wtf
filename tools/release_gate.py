"""Require successful Windows operational checks for the exact release commit."""

import argparse
import json
import os
import urllib.request
from pathlib import Path


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
    runs = get(f"repos/{repo}/actions/runs?head_sha={args.sha}&event=push&per_page=100")["workflow_runs"]
    required = {"core (windows-2022)"}
    for run in runs:
        if run["name"] != "Full operational check" or run["head_sha"] != args.sha:
            continue
        jobs = get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        passed = {job["name"] for job in jobs if job["conclusion"] == "success"}
        if required <= passed:
            notes = args.notes.read_text(encoding="utf-8")
            notes += f"\n\nOperational verification: {run['html_url']}\n\nTested commit: `{args.sha}`.\n"
            args.output.write_text(notes, encoding="utf-8")
            print(f"release allowed: Windows operational checks passed for {args.sha}")
            return
    raise SystemExit("release blocked: the exact commit needs successful full Windows operational checks")


if __name__ == "__main__":
    main()
