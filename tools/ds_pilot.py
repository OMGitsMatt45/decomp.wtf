"""Run a bounded DS import/matching experiment without launching external model sessions.

Run with `uv run python tools/ds_pilot.py --help` from a source checkout.
Keep --work outside the checkout: it contains private game data and recovered source.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import time

from decompnet.app.engine import RomNetwork


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--arm7-bios", type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--compiler", default="DS/2.0/sp1p5")
    parser.add_argument("--own-copy", required=True, action="store_true")
    parser.add_argument("--drafts", type=int, default=64)
    parser.add_argument("--remaining-report", type=Path,
                        help="optional CSV restricting candidates to its analysis_name/name column")
    parser.add_argument("--min-instructions", type=int, default=1)
    parser.add_argument("--sample", choices=("smallest", "spread"), default="smallest",
                        help="choose the smallest eligible functions, or spread the sample across their sizes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.drafts < 0 or args.min_instructions < 1:
        parser.error("--drafts must be nonnegative; --min-instructions must be positive")
    work = args.work.expanduser().resolve()
    checkout = Path(__file__).resolve().parent.parent
    if work == checkout or checkout in work.parents:
        parser.error("--work must be outside this checkout (it contains private game files)")
    if args.arm7_bios:
        os.environ["DECOMP_ARM7_BIOS"] = str(args.arm7_bios.expanduser().resolve())
    work.mkdir(parents=True, exist_ok=True)
    output = args.output.expanduser().resolve() if args.output else work / "pilot-result.json"
    net = RomNetwork(work / "app.db", work)
    started = time.monotonic()
    slug = net.import_rom(args.rom.expanduser().resolve(), toolchain=args.compiler,
                          confirmed=args.own_copy, log=print)
    before = net.overview(slug)
    proj = net.project_row(slug)
    agent, _ = net.local_agent("ds-pilot")
    allowed = None
    if args.remaining_report:
        with args.remaining_report.open(newline="", encoding="utf-8-sig") as f:
            allowed = {row.get("analysis_name") or row.get("name") for row in csv.DictReader(f)}
    candidates = []
    for fid in net.forks.autopilot_prepare(slug) if args.drafts else []:
        fn = net.store.one("SELECT name, n_insns FROM functions WHERE id=?", fid)
        if fn["n_insns"] >= args.min_instructions and (allowed is None or fn["name"] in allowed):
            candidates.append((fid, fn["name"], fn["n_insns"]))
    if args.sample == "spread" and 1 < args.drafts < len(candidates):
        candidates = [candidates[i * (len(candidates) - 1) // (args.drafts - 1)] for i in range(args.drafts)]
    else:
        candidates = candidates[:args.drafts]
    results = []
    summary = {}

    def save() -> None:
        overview = net.overview(slug)
        summary.update({"project": slug, "compiler": args.compiler, "elapsed_seconds": time.monotonic() - started,
                        "sample": args.sample, "restricted_to_remaining_report": allowed is not None,
                        "functions_indexed": overview["functions"], "functions_matched_before": before["matched"],
                        "functions_matched_after": overview["matched"], "matched_bytes": overview["matched_bytes"],
                        "sample_attempts": len(results), "outcomes": dict(Counter(r["outcome"] for r in results)),
                        "results": results, "rebuild": overview.get("rebuild")})
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for fid, name, insns in candidates:
        start = time.monotonic()
        outcome = net.forks.autopilot_one(agent, proj, fid)
        result = {"name": name, "instructions": insns, "outcome": outcome,
                  "seconds": round(time.monotonic() - start, 3)}
        results.append(result)
        print(json.dumps(result), flush=True)
        save()
    summary["rebuild"] = net.forks.check_rom(slug, log=print)
    save()
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
