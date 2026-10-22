"""Compare original-fixture execution in a separately installed melonDS libretro core.

Accepts owner-supplied bios7.bin, bios9.bin and firmware.bin, or an explicit
--builtin-bios request for the core's replacements. Each ROM runs in a fresh
process with a private runtime directory. This checks CPU execution
and watched game state; it is not a physical-console or firmware-menu test.
"""

from __future__ import annotations

import argparse
import ctypes as ct
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

PREFIX = "DECOMP_DS_BOOT "


class Variable(ct.Structure):
    _fields_ = [("key", ct.c_char_p), ("value", ct.c_char_p)]


class Game(ct.Structure):
    _fields_ = [("path", ct.c_char_p), ("data", ct.c_void_p), ("size", ct.c_size_t), ("meta", ct.c_char_p)]


def execute(core_path: Path, system: Path, rom: Path, watched: dict[str, int], frames: int) -> dict:
    # Keep callbacks and their returned byte strings alive until deinit.
    defaults = {b"melonds_console_mode": b"DS", b"melonds_boot_directly": b"enabled",
                b"melonds_jit_enable": b"disabled", b"melonds_use_fw_settings": b"enabled"}
    directory = os.fsencode(system)

    @ct.CFUNCTYPE(ct.c_bool, ct.c_uint, ct.c_void_p)
    def environment(command, data):
        if command in (9, 31):  # system/save directory
            ct.cast(data, ct.POINTER(ct.c_char_p))[0] = directory
        elif command == 52:  # request legacy core-option interface
            ct.cast(data, ct.POINTER(ct.c_uint))[0] = 0
        elif command == 16:  # legacy option defaults
            variables, index = ct.cast(data, ct.POINTER(Variable)), 0
            while variables[index].key:
                option = variables[index]
                defaults.setdefault(option.key, option.value.split(b"; ", 1)[1].split(b"|", 1)[0])
                index += 1
        elif command == 15:
            variable = ct.cast(data, ct.POINTER(Variable)).contents
            variable.value = defaults.get(variable.key)
            return variable.value is not None
        elif command == 17:
            ct.cast(data, ct.POINTER(ct.c_bool))[0] = False
        elif command == 10:  # XRGB8888 software rendering
            return ct.cast(data, ct.POINTER(ct.c_int))[0] == 1
        elif command == 39:
            ct.cast(data, ct.POINTER(ct.c_uint))[0] = 1  # English
        else:
            return False
        return True

    callbacks = {
        "environment": environment,
        "video_refresh": ct.CFUNCTYPE(None, ct.c_void_p, ct.c_uint, ct.c_uint, ct.c_size_t)(lambda *a: None),
        "audio_sample": ct.CFUNCTYPE(None, ct.c_int16, ct.c_int16)(lambda *a: None),
        "audio_sample_batch": ct.CFUNCTYPE(ct.c_size_t, ct.c_void_p, ct.c_size_t)(lambda data, n: n),
        "input_poll": ct.CFUNCTYPE(None)(lambda: None),
        "input_state": ct.CFUNCTYPE(ct.c_int16, ct.c_uint, ct.c_uint, ct.c_uint, ct.c_uint)(lambda *a: 0),
    }
    dll_directory = os.add_dll_directory(str(core_path.parent)) if sys.platform == "win32" else None
    try:
        core = ct.CDLL(str(core_path))
        for name, callback in callbacks.items():
            setter = getattr(core, f"retro_set_{name}")
            setter.argtypes, setter.restype = [type(callback)], None
            setter(callback)
        for name in ("init", "deinit", "run", "unload_game"):
            function = getattr(core, f"retro_{name}")
            function.argtypes, function.restype = [], None
        core.retro_load_game.argtypes, core.retro_load_game.restype = [ct.POINTER(Game)], ct.c_bool
        core.retro_get_memory_data.argtypes, core.retro_get_memory_data.restype = [ct.c_uint], ct.c_void_p
        core.retro_get_memory_size.argtypes, core.retro_get_memory_size.restype = [ct.c_uint], ct.c_size_t
        core.retro_init()
        loaded = False
        try:
            image = rom.read_bytes()
            buffer = ct.create_string_buffer(image)
            game = Game(os.fsencode(rom), ct.cast(buffer, ct.c_void_p), len(image), None)
            loaded = core.retro_load_game(ct.byref(game))
            if not loaded:
                raise ValueError("melonDS rejected the ROM or runtime inputs")
            ram, size = core.retro_get_memory_data(2), core.retro_get_memory_size(2)
            if not ram or any(not 0 <= address - 0x02000000 <= size - 4 for address in watched.values()):
                raise ValueError("watched symbols must fit inside exported main RAM")
            samples = []
            checkpoints = {frames // 12 - 1, frames // 4 - 1, frames // 2 - 1, frames - 1}
            for frame in range(frames):
                core.retro_run()
                if frame in checkpoints:
                    samples.append({name: ct.c_uint32.from_address(ram + address - 0x02000000).value
                                    for name, address in watched.items()})
            for counter in ("g_frame_count", "arm7_counter"):
                if len({sample[counter] for sample in samples}) < 2:
                    raise ValueError(f"the original fixture's {counter} did not advance")
            return {"rom": str(rom), "frames": frames, "samples": samples}
        finally:
            if loaded:
                core.retro_unload_game()
            core.retro_deinit()
    finally:
        if dll_directory is not None:
            dll_directory.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True, help="melonDS libretro .dll/.so/.dylib")
    parser.add_argument("--bios-dir", type=Path, help="directory containing your three DS runtime files")
    parser.add_argument("--builtin-bios", action="store_true", help="use the core's built-in BIOS/firmware replacements")
    parser.add_argument("--symbols", type=Path, default=Path("projects/demo-ds/build/demoq_ds.elf"))
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("roms", nargs="+", type=Path)
    args = parser.parse_args()
    if not args.worker and len(args.roms) < 2:
        parser.error("provide the original fixture and at least one rebuilt ROM")
    if args.frames < 12 or args.frames > 3600:
        parser.error("--frames must be between 12 and 3600")
    if not args.builtin_bios:
        if args.bios_dir is None:
            parser.error("provide --bios-dir or explicitly choose --builtin-bios")
        for name, sizes in (("bios7.bin", (16384,)), ("bios9.bin", (4096,)), ("firmware.bin", (131072, 262144, 524288))):
            file = args.bios_dir / name
            if not file.is_file() or file.stat().st_size not in sizes:
                parser.error(f"{name} is missing or has an unexpected size")
    elif args.bios_dir is not None and not args.worker:
        parser.error("choose either your runtime files or --builtin-bios")
    with args.symbols.open("rb") as stream:
        table = ELFFile(stream).get_section_by_name(".symtab")
        watched = {name: table.get_symbol_by_name(name)[0]["st_value"]
                   for name in ("g_frame_count", "debug_status", "debug_crc", "g_score")}
    watched["arm7_counter"] = 0x0238FFF0  # original ARM7 loop in projects/demo-ds/build.py
    if args.worker:
        try:
            report = execute(args.core.resolve(), args.bios_dir.resolve(), args.roms[0].resolve(), watched, args.frames)
        except (OSError, ValueError) as error:
            print(PREFIX + json.dumps({"error": str(error)}), flush=True)
            raise SystemExit(1)
        print(PREFIX + json.dumps(report), flush=True)
        return
    reports = []
    for rom in args.roms:
        with tempfile.TemporaryDirectory(prefix="decomp-ds-boot-") as temporary:
            system = Path(temporary)
            if not args.builtin_bios:
                for name in ("bios7.bin", "bios9.bin", "firmware.bin"):
                    shutil.copyfile(args.bios_dir / name, system / name)
                    (system / name).chmod(0o600)
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--core", str(args.core.resolve()),
                       "--bios-dir", str(system), "--symbols", str(args.symbols.resolve()), "--frames", str(args.frames),
                       str(rom.resolve())]
            if args.builtin_bios:
                command.append("--builtin-bios")
            result = subprocess.run(command, capture_output=True, text=True, timeout=600,
                                    encoding="utf-8", errors="replace")
            report = next((line.removeprefix(PREFIX) for line in result.stdout.splitlines()
                           if line.startswith(PREFIX)), None)
            if result.returncode or report is None:
                # Core logs can include firmware profile information; do not echo them.
                detail = json.loads(report).get("error", "no execution report") if report else "no execution report"
                raise SystemExit(f"DS execution failed for {rom.name} (worker exit {result.returncode}): {detail}")
            reports.append(json.loads(report))
    if any(report["samples"] != reports[0]["samples"] for report in reports[1:]):
        raise SystemExit("original and rebuilt game-state traces differ")
    report = {"identical_traces": True, "execution": "melonDS direct boot, interpreter, no input",
              "runtime": "core built-in replacements" if args.builtin_bios else "owner-supplied BIOS/firmware",
              "roms": reports}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
