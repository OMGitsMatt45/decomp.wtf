#!/usr/bin/env python3
"""Write build.ninja for this Nintendo DS decompilation, then run `ninja`.

    python tools/configure.py VERSION --dsd PATH --compilers DIR [--wibo PATH]

`ninja` builds everything and checks the ROM; `ninja prepare` only what decompiling needs; `ninja rom` the ROM check.
The build extracts your copy of the game (extract/baserom.nds), delinks its code into objects with ds-decomp (dsd),
compiles src/ with CodeWarrior for DS, links everything with CodeWarrior's linker, rebuilds the ROM and checks it
against your copy, byte for byte. objdiff.json (for objdiff and decomp.wtf) compares every source file with the
original. Made by decomp.wtf, modeled on the build of AetiasHax's Princess Maker 4 decomp (CC0).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import ninja_syntax

# Settings (decomp.wtf wrote these for this game; change them if the game was built differently)
GAME = "game"
MWCC_VERSION = "2.0/sp1p5"
USE_ARM7_BIOS = True  # decomp.wtf selects this from the input's encryption and secure-checksum metadata
INPUT_FORMAT = "auto"  # an explicit decrypted input retains its supplied secure bytes and checksum metadata
CC_FLAGS = ["-O4,p", "-enum", "int", "-char", "signed", "-str", "noreuse", "-proc", "arm946e", "-gccext,on", "-fp",
            "soft", "-inline", "noauto", "-Cpp_exceptions", "off", "-RTTI", "off", "-interworking", "-w", "off",
            "-sym", "on", "-gccinc", "-nolink", "-msgstyle", "gcc"]
# Keep unused original sections too: their bytes and exported overlay entry points belong to the reference ROM.
LD_FLAGS = ["-proc", "arm946e", "-nodead", "-nostdlib", "-interworking", "-map", "closure,unused", "-msgstyle", "gcc"]
ARM7_MANIFEST = Path("config")  # resolved after the version is parsed

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
parser = argparse.ArgumentParser(description="Writes build.ninja")
parser.add_argument("version", help="game version (a directory in config/)")
parser.add_argument("--dsd", required=True, help="path to ds-decomp's dsd")
parser.add_argument("--compilers", required=True, help="CodeWarrior for DS directory (holds 2.0/sp1p5/mwccarm.exe, ...)")
parser.add_argument("--wibo", default="", help="runs the Windows compilers on Linux and macOS")
parser.add_argument("--arm-binutils", default="", help="directory containing native arm-none-eabi-as and ld")
args = parser.parse_args()

VERSION = args.version
CONFIG = Path("config") / VERSION / "arm9" / "config.yaml"
BUILD = Path("build") / VERSION
BASEROM = Path("extract") / "baserom.nds"
ARM7_BIOS = Path("extract") / "arm7_bios.bin"
EXTRACT = Path("extract") / VERSION
ARM7_MANIFEST = Path("config") / VERSION / "arm7" / "units.json"
CC = str(Path(args.compilers) / MWCC_VERSION / "mwccarm.exe")
LD = str(Path(args.compilers) / MWCC_VERSION / "mwldarm.exe")
WRAP = f'"{args.wibo}" ' if args.wibo and sys.platform != "win32" else ""
# Windows: ninja starts commands without a shell, so a rule with && runs through cmd; and CodeWarrior's license check
# only looks in C:\flexlm unless LM_LICENSE_FILE points at the license.dat next to the compilers
SH = "cmd /c " if sys.platform == "win32" else ""
LICENSE = Path(args.compilers).resolve() / "license.dat"
if sys.platform == "win32" and LICENSE.exists():
    WRAP = f'cmd /c set "LM_LICENSE_FILE={LICENSE}" && '
DSD = f'"{args.dsd}"'
PY = f'"{sys.executable}"'


def q(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def sources() -> list[Path]:
    return sorted(p for p in Path("src").rglob("*") if p.suffix in (".c", ".cpp"))


def main() -> None:
    import arm7_build

    arm7 = arm7_build.load(ARM7_MANIFEST) if ARM7_MANIFEST.exists() else {"units": [], "modules": {}}
    arm7_sources = {unit["source"] for unit in arm7["units"]}
    if arm7_sources and not args.arm_binutils:
        raise ValueError("ARM7 source units need --arm-binutils (the pinned ARM GNU bin directory)")
    delinks = json.loads(subprocess.run([args.dsd, "json", "delinks", "--config-path", str(CONFIG)], check=True,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout)
    files = delinks["files"]
    dsd_configs = [str(p) for p in Path("config", VERSION).rglob("*.txt")]
    rom = BUILD / f"{GAME}.nds"
    with open("build.ninja", "w", encoding="utf-8") as f:
        n = ninja_syntax.Writer(f)
        # Host CPU counts can exceed a container's memory/process allocation.
        n.pool("ds_tools", 4)
        bios_arg = f" --arm7-bios {ARM7_BIOS}" if USE_ARM7_BIOS and ARM7_BIOS.is_file() else ""
        format_arg = " --input-format decrypted" if INPUT_FORMAT == "decrypted" else ""
        n.rule("extract", f"{PY} tools/extract.py {DSD} rom extract --rom $in --output-path {EXTRACT}{bios_arg}{format_arg}")
        n.rule("delink", f"{DSD} delink --config-path {CONFIG}")
        n.rule("mwcc", f"{WRAP}\"{CC}\" {q(CC_FLAGS)} -i include $cflags -MD -c $in -o $basedir"
               + ("" if sys.platform == "win32" else f" && {PY} tools/transform_dep.py $basefile.d $basefile.d"),
               depfile="$basefile.d", pool="ds_tools")
        arm7_flags = ["arm7tdmi" if flag == "arm946e" else flag for flag in CC_FLAGS]
        n.rule("mwcc_arm7", f"{WRAP}\"{CC}\" {q(arm7_flags)} -i include $cflags -MD -c $in -o $out"
               + f" && {PY} tools/transform_dep.py $dependency $basefile.d",
               depfile="$basefile.d", pool="ds_tools")
        suffix = ".exe" if sys.platform == "win32" else ""
        assembler, linker = [str(Path(args.arm_binutils) / (f"arm-none-eabi-{name}" + suffix)) for name in ("as", "ld")]
        arm7_command = f"{PY} tools/arm7_build.py $action --manifest {ARM7_MANIFEST} --build {BUILD}"
        arm7_tools = q(["--assembler", assembler, "--linker", linker])
        n.rule("arm7_unit", f"{arm7_command} --source $source {arm7_tools}", pool="ds_tools")
        n.rule("arm7_merge", f"{arm7_command} --rom-config $in --output $out")
        n.rule("lcf", f"{DSD} lcf -c {CONFIG}")
        n.rule("mwld", f"{WRAP}\"{LD}\" {q(LD_FLAGS)} -m Entry @$objects $lcf -o $out")
        n.rule("rom_config", f"{PY} tools/rom_config.py {DSD} --elf $in --config {CONFIG}")
        reference_arg = f" --decrypted-reference {BASEROM}" if INPUT_FORMAT == "decrypted" else ""
        n.rule("rom_build", f"{PY} tools/build_rom.py {DSD} --config $in --rom $out{bios_arg}{reference_arg}")
        n.rule("same", f"{PY} tools/same.py $in {BASEROM} $out")
        # A cmd /c chain beginning with a quoted executable loses its first
        # quote when later commands add more quoted paths. Let Python launch dsd
        # with an argument list, then append ARM7 units in the same process.
        objdiff_command = (f"{arm7_command.replace('$action', 'objdiff')} --output objdiff.json "
                           f"--dsd {DSD} --dsd-config {CONFIG}" if arm7_sources else
                           f"{SH}{DSD} objdiff --config-path {CONFIG} --custom-make ninja")
        n.rule("objdiff", objdiff_command)
        n.rule("check", f"{SH}{DSD} check modules --config-path {CONFIG} --fail && {PY} tools/same.py --touch $out")
        n.rule("configure", f"{PY} tools/configure.py {q(sys.argv[1:])}", generator=True)

        n.build(str(EXTRACT / "config.yaml"), "extract", str(BASEROM),
                implicit=["tools/extract.py", "tools/nds_input.py", *([str(ARM7_BIOS)] if bios_arg else [])],
                implicit_outputs=sorted({m["binary"] for m in arm7["modules"].values()}) if arm7_sources else None)
        targets = sorted({x["delink_file"] for x in files})
        n.build(targets or ["delink"], "delink", [*dsd_configs, str(EXTRACT / "config.yaml")])
        objs = []
        for src in sources():
            if src.as_posix() in arm7_sources:
                continue
            obj = BUILD / src.with_suffix(".o")
            lang = "-lang=c++" if src.suffix == ".cpp" else "-lang=c"
            n.build(str(obj), "mwcc", str(src), variables={"cflags": lang, "basefile": str(obj.with_suffix("")),
                                                           "basedir": str(obj.parent)})
            objs.append(str(obj))
        arm7_targets, arm7_linked = [], []
        for unit in arm7["units"]:
            target, base, raw = arm7_build.paths(BUILD, unit)
            source = unit["source"]
            n.build(str(raw), "mwcc_arm7", source, variables={
                "cflags": "-lang=c++" if Path(source).suffix == ".cpp" else "-lang=c",
                "basefile": str(raw.with_suffix("")), "basedir": str(raw.parent),
                "dependency": Path(source).stem + ".d"})
            n.build(str(base), "arm7_unit", str(raw), implicit=[str(ARM7_MANIFEST), "tools/arm7_build.py"],
                    variables={"action": "link", "source": source}, implicit_outputs=[str(base.with_suffix(".linked.elf"))])
            module = arm7["modules"][unit["module"]]
            n.build(str(target), "arm7_unit", module["binary"], implicit=[str(ARM7_MANIFEST), "tools/arm7_build.py"],
                    variables={"action": "target", "source": source})
            arm7_targets.append(str(target))
            objs.append(str(base))
            if unit["complete"]:
                arm7_linked.append(str(base))
        lcf, objects = delinks["arm9_lcf_file"], delinks["arm9_objects_file"]
        n.build([lcf, objects], "lcf", [*dsd_configs, str(EXTRACT / "config.yaml")])
        linked = sorted({x["object_to_link"] for x in files})
        n.build(str(BUILD / "arm9.o"), "mwld", [*linked, lcf, objects], variables={"lcf": lcf, "objects": objects})
        rom_config = BUILD / "build" / "rom_config.yaml"
        n.build(str(rom_config), "rom_config", str(BUILD / "arm9.o"), implicit=["tools/rom_config.py"])
        if arm7_sources:
            merged_config = rom_config.with_name("with-arm7.yaml")
            n.build(str(merged_config), "arm7_merge", str(rom_config),
                    implicit=[str(ARM7_MANIFEST), str(ARM7_MANIFEST.with_name("delinks.txt")), "tools/arm7_build.py",
                              *arm7_linked], variables={"action": "merge"})
            rom_config = merged_config
        n.build(str(rom), "rom_build", str(rom_config),
                implicit=["tools/build_rom.py", "tools/nds_input.py", str(BASEROM),
                          *([str(ARM7_BIOS)] if bios_arg else [])])
        n.build(str(BUILD / "rom.ok"), "same", str(rom))
        n.build(str(BUILD / "check.ok"), "check", str(BUILD / "arm9.o"))
        n.build("objdiff.json", "objdiff", [*dsd_configs, *([str(ARM7_MANIFEST)] if arm7_sources else [])])
        n.build("rom", "phony", str(BUILD / "rom.ok"))
        # what decompiling needs (each function is judged against its delinked original): `ninja prepare`; every
        # source file's object, keeping going past work in progress: `ninja -k 0 all_source`
        n.build("all_source", "phony", objs)
        n.build("prepare", "phony", ["objdiff.json", *targets, *arm7_targets, *objs])
        n.build("build.ninja", "configure", [__file__, *dsd_configs,
                                               *([str(ARM7_MANIFEST)] if arm7_sources else []),
                                               *[str(s) for s in sources()]])
        n.default(["objdiff.json", str(BUILD / "rom.ok"), *objs])


if __name__ == "__main__":
    main()
