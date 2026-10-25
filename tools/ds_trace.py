"""Trace owner-supplied DS ROMs in a software melonDS core, with scripted joypad input.

This records observations, not a gameplay certification. Screenshots and all
runtime inputs stay in the chosen private output directory. Firmware menus and
touchscreen input require an interactive emulator frontend.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.ds_boot import execute

PREFIX = "DECOMP_DS_TRACE "


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--bios-dir", type=Path)
    parser.add_argument("--builtin-bios", action="store_true")
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--inputs", type=Path, help='JSON events: [{"start": 120, "end": 125, "buttons": ["a"]}]')
    parser.add_argument("--output", type=Path, required=True, help="private directory for report and screenshots")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("roms", type=Path, nargs="+")
    args = parser.parse_args()
    if not 12 <= args.frames <= 36000:
        parser.error("--frames must be between 12 and 36000")
    if not args.builtin_bios:
        if args.bios_dir is None:
            parser.error("provide --bios-dir or explicitly choose --builtin-bios")
        for name, sizes in (("bios7.bin", (16384,)), ("bios9.bin", (4096,)), ("firmware.bin", (131072, 262144, 524288))):
            file = args.bios_dir / name
            if not file.is_file() or file.stat().st_size not in sizes:
                parser.error(f"{name} is missing or has an unexpected size")
    elif args.bios_dir is not None and not args.worker:
        parser.error("choose either supplied runtime files or --builtin-bios")
    events = json.loads(args.inputs.read_text(encoding="utf-8")) if args.inputs else []
    valid = {"a", "b", "x", "y", "start", "select", "up", "down", "left", "right", "l", "r"}
    if not isinstance(events, list) or any(not isinstance(e, dict) or
            not isinstance(e.get("start"), int) or not isinstance(e.get("end"), int) or
            not 0 <= e["start"] < e["end"] <= args.frames or not isinstance(e.get("buttons"), list) or
            any(b not in valid for b in e["buttons"]) for e in events):
        parser.error("invalid input timeline")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.worker:
        try:
            report = execute(args.core.resolve(), args.bios_dir.resolve(), args.roms[0].resolve(), {}, args.frames,
                             inputs=events, screenshots=args.output, trace=True)
        except (OSError, ValueError) as error:
            print(PREFIX + json.dumps({"error": str(error)}), flush=True)
            raise SystemExit(1)
        print(PREFIX + json.dumps(report), flush=True)
        return
    reports = []
    for index, rom in enumerate(args.roms):
        with tempfile.TemporaryDirectory(prefix="decomp-ds-trace-") as temporary:
            system = Path(temporary)
            if not args.builtin_bios:
                for name in ("bios7.bin", "bios9.bin", "firmware.bin"):
                    shutil.copyfile(args.bios_dir / name, system / name)
                    (system / name).chmod(0o600)
            output = args.output.resolve() / f"rom-{index}"
            command = [sys.executable, "-m", "tools.ds_trace", "--worker", "--core", str(args.core.resolve()),
                       "--bios-dir", str(system), "--frames", str(args.frames), "--output", str(output), str(rom.resolve())]
            if args.inputs:
                command += ["--inputs", str(args.inputs.resolve())]
            if args.builtin_bios:
                command.append("--builtin-bios")
            result = subprocess.run(command, capture_output=True, text=True, timeout=1800,
                                    encoding="utf-8", errors="replace")
            output.mkdir(parents=True, exist_ok=True)
            log = output / "core.log"
            log.write_text(result.stdout + result.stderr, encoding="utf-8")
            log.chmod(0o600)
            position = result.stdout.find(PREFIX)
            observed = json.JSONDecoder().raw_decode(result.stdout[position + len(PREFIX):])[0] if position >= 0 else None
            if result.returncode or observed is None:
                # Firmware profile information can appear in native core logs.
                error = observed.get("error", "no trace") if observed else "no trace"
                raise SystemExit(f"DS trace failed for {rom.name} (worker exit {result.returncode}): {error}")
            reports.append(observed)
    observations = [{**item, "traces": [{k: v for k, v in t.items() if k != "ram_sha256"} for t in item["traces"]]}
                    for item in reports]
    same = all(item["traces"] == observations[0]["traces"] for item in observations[1:]) if len(reports) > 1 else None
    report = {"execution": "melonDS direct boot, interpreter, scripted joypad", "roms": reports,
              "identical_video_audio": same,
              "identical_ram": all(item["traces"] == reports[0]["traces"] for item in reports[1:]) if len(reports) > 1 else None}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"roms": len(reports), "frames_each": args.frames, "identical_video_audio": same,
                      "report": str(args.output / "report.json")}))
    if same is False:
        raise SystemExit("original and rebuilt video/audio observations differ; inspect the private trace")


if __name__ == "__main__":
    main()
