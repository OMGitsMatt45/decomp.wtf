"""Export a ROM project as a rebuildable source tree: the base for ports and mods.

The tree is a normal decomp project. splat's assembly for every function and all data (with the project's names),
the matched functions as C or C++, a linker script and a build script that rebuilds the game's image and checks it against
the original byte for byte. Each function is its own object: a matched one is compiled exactly the way decomp.wtf
verified it, the rest are assembled. Data stays labeled assembly; a matched function's own constants (strings,
jump tables) are mapped onto the game's copy at the addresses the matcher verified, so nothing is duplicated.

Anyone can keep working on it outside decomp.wtf: edit src/, run build.py, and the build says whether it still
matches.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from .. import cpp, toolchains
from ..limits import capped
from ..project import function_config
from . import match, split
from .symbols import AUTO_NAME

AS_FLAGS = {
    "n64": ["-EB", "-march=vr4300", "-mabi=32"],
    "psx": ["-EL", "-march=r3000", "-mabi=32"],
    "ps2": ["-EL", "-march=r5900", "-mabi=eabi"],
}
LD_ENDIAN = {"n64": "-EB", "psx": "-EL", "ps2": "-EL"}
IMAGE_EXT = {"n64": ".z64", "psx": ".exe", "ps2": ".bin"}
_ADDR_COMMENT = re.compile(r"/\*\s*([0-9A-F]+)\s+([0-9A-F]{8})\b")
_BSS_COMMENT = re.compile(r"/\*\s*([0-9A-F]{8})\s*\*/\s*\.space")
_DEFINES = re.compile(r"^\s*(?:glabel|dlabel|jlabel|alabel|ehlabel)\s+(\w+)|^\s*\.globl\s+(\w+)|^\s*(\w+):", re.M)
DISCARD = ["*(.reginfo)", "*(.MIPS.abiflags)", "*(.MIPS.options)", "*(.pdr)", "*(.comment)", "*(.mdebug*)",
           "*(.gnu.attributes)", "*(.note*)", "*(.gptab.*)"]


class ExportError(RuntimeError):
    pass


def _first_address(path: Path) -> tuple[int | None, int | None]:
    """(ROM offset, VRAM) of the first instruction or data word in a splat assembly file."""
    text = path.read_text(errors="replace", encoding="utf-8")
    m = _ADDR_COMMENT.search(text)
    if m:
        return int(m.group(1), 16), int(m.group(2), 16)
    m = _BSS_COMMENT.search(text)
    if m:
        return None, int(m.group(1), 16)
    return None, None


def _symbol_lines(net, proj) -> list[str]:
    """symbol_addrs.txt entries for every function and every named symbol, so splat writes the project's names."""
    syms = net.symbols(proj["id"])
    funcs = net.store.all("SELECT name, vram, size, rom_offset FROM functions WHERE project_id=?", proj["id"])
    addresses = {r["vram"] for r in funcs}
    lines = []
    modules = net.cfg(proj).get("symbol_modules", {})
    for r in sorted(funcs, key=lambda r: (r["vram"], r["rom_offset"] or 0)):
        hint = f" rom:0x{r['rom_offset']:X}" if r["rom_offset"] is not None else ""
        lines.append(f"{r['name']} = 0x{r['vram']:08X}; // type:func{hint}")
    for s in sorted(syms.by_name.values(), key=lambda s: s.address):
        if s.address in addresses or AUTO_NAME.match(s.name):
            continue
        hint = f" // segment:{modules[s.name]}" if s.name in modules else ""
        lines.append(f"{s.name} = 0x{s.address:08X};{hint}")
    return lines


def _segments(config: dict) -> list[dict]:
    """Segments in ROM order with start/end offsets."""
    raw = config.get("segments", [])
    starts = []
    for seg in raw:
        starts.append(seg[0] if isinstance(seg, list) else seg.get("start"))
    out = []
    for i, seg in enumerate(raw):
        start = starts[i]
        end = next((s for s in starts[i + 1:] if s is not None), None)
        if isinstance(seg, list):
            if len(seg) == 1:
                continue  # the end marker
            seg = {"start": seg[0], "type": seg[1], "name": seg[2] if len(seg) > 2 else f"{seg[0]:X}"}
        out.append(dict(seg) | {"start": start, "end": end})
    return out


def export_rom(net, slug: str, out: Path, log=print, *, format="matching") -> dict:
    """Write the rebuildable tree to `out`, build it once and report: {"path", "identical", "matched", ...}."""
    proj = net._project(slug)
    cfg = net.cfg(proj)
    language = cpp.language(cfg)
    extension = "cpp" if language == "c++" else "c"
    platform = cfg.get("platform", "n64")
    if platform not in AS_FLAGS:
        raise ExportError(f"exporting a rebuildable project isn't supported for {platform} yet")
    if format not in ("matching", "shiftable") or (format == "shiftable" and platform != "n64"):
        raise ExportError("choose matching, or shiftable for an N64 cartridge")
    work = Path(proj["root"])
    configs = sorted(work.glob("*.yaml"))
    if not configs:
        raise ExportError("this project has no splat configuration to export from")
    image_name = cfg["rom"]["file"]
    image = (work / image_name).read_bytes()
    disc = cfg.get("psx_disc") if platform == "psx" else None
    if disc and disc.get("supported"):
        from .psx_disc import analysis
        disc_path = (work / disc["file"]).resolve()
        if work.resolve() not in disc_path.parents:
            raise ExportError("PS1 original disc path is outside the project")
        if analysis(disc_path, disc) != image:
            raise ExportError("PS1 analysis image differs from the original disc programs")
    container = None
    provenance_path = work / "n64-provenance.json"
    if platform == "n64" and provenance_path.is_file():
        from .n64_layout import working_image
        metadata = json.loads(provenance_path.read_text(encoding="utf-8"))
        if metadata["blocks"]:
            original_path = (work / metadata["original_file"]).resolve()
            if work.resolve() not in original_path.parents:
                raise ExportError("N64 original cartridge path is outside the project")
            original = original_path.read_bytes()
            if working_image(original, metadata) != image:
                raise ExportError("N64 analysis image differs from the original compressed modules")
            container = {"image": "baserom.z64", "output": "build/game.z64", "layout": metadata}

    if out.exists():
        keep = {".git"}
        for child in out.iterdir():
            if child.name not in keep:
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)

    # 1. splat again, with the project's names
    log("writing the assembly with the project's names (splat)")
    shutil.copyfile(configs[0], out / "splat.yaml")
    config = yaml.safe_load((out / "splat.yaml").read_text(encoding="utf-8"))
    has_overlays = split.overlay_contexts(config)
    bss_changed = False
    if platform == "ps2" and (program := cfg["rom"].get("program")) and (work / program).is_file():
        from . import ps2
        bss_changed = ps2.bss_layout(config, (work / program).read_bytes())
    if platform == "n64":
        # A ROM title can contain NULs, quotes or whitespace. Splat's string
        # form can change those bytes or produce assembly GAS cannot read.
        config.setdefault("options", {})["header_encoding"] = "word"
    if platform == "n64" or has_overlays or bss_changed:
        (out / "splat.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    shutil.copyfile(work / image_name, out / image_name)
    for extra in ("reloc_addrs.txt",):
        if (work / extra).exists():
            shutil.copyfile(work / extra, out / extra)
    (out / "symbol_addrs.txt").write_text("\n".join(_symbol_lines(net, proj)) + "\n", encoding="utf-8")
    res = subprocess.run([sys.executable, "-m", "splat", "split", "splat.yaml"], cwd=out, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise ExportError("splat failed:\n" + (res.stdout + res.stderr)[-1500:])
    if has_overlays:
        split.namespace_overlay_labels(out)
    if platform == "psx":
        from .psx_modules import literal_gp
        literal_gp(out)
    for generated in (out / "src").glob("*.c"):
        generated.unlink()  # splat's INCLUDE_ASM files: this tree builds one object per function instead
    for ld in out.glob("*.ld"):
        ld.rename(out / f"splat-{ld.name}")

    # 2. which function is where, and which are matched
    rows = {(r["rom_offset"], r["vram"]): r for r in net.store.all("SELECT * FROM functions WHERE project_id=?", proj["id"])}
    units = net._unit_contexts(proj["id"])
    header = net._context(proj["id"])["header"]
    (out / "include").mkdir(exist_ok=True)
    (out / "include" / "common.h").write_text(header, encoding="utf-8", newline="\n")
    for u in units:
        (out / "include" / f"common_{u}.h").write_text(net._context(proj["id"], u)["header"], encoding="utf-8", newline="\n")
    functions, other_assembly = [], []
    source_segments = _segments(config)
    for path in sorted((out / "asm" / "nonmatchings").glob("**/*.s")):
        rom_off, vram = _first_address(path)
        if vram is None:
            continue
        label = re.search(r"^\s*glabel\s+(\w+)", path.read_text(encoding="utf-8"), re.M)
        if label is None:
            other_assembly.append(path)
            continue
        owner = next((s["name"] for s in source_segments if s.get("type") == "code" and rom_off is not None and
                      s["start"] <= rom_off < (s["end"] or len(image))), path.parent.name)
        functions.append({"name": label[1] if label else path.stem, "seg": owner, "vram": vram, "rom": rom_off,
                          "asm": path.relative_to(out).as_posix()})
    functions.sort(key=lambda f: f["vram"])

    objects, private, as_fallback = [], [], []
    for f in functions:
        row = rows.get((f["rom"], f["vram"]))
        f["obj_asm"] = f"build/{Path(f['asm']).with_suffix('.o').as_posix()}"
        if row is None or row["status"] != "matched" or not row["matched_source"]:
            f["kind"] = "asm"
            continue
        unit = net._effective_unit(row, units)
        hdr = net._context(proj["id"], unit)["header"]
        compiled = net._compile(proj, hdr, row["matched_source"], row)
        if not compiled.ok:
            as_fallback.append((f["name"], "doesn't compile any more"))
            f["kind"] = "asm"
            continue
        linked = match.link(compiled.obj, row["name"], net._rom_target(row), net.symbols(proj["id"]), net.reader(proj, row))
        if not linked.exact:
            as_fallback.append((f["name"], "no longer matches"))
            f["kind"] = "asm"
            continue
        bases, ok = {}, True
        for section, offsets in linked.placements.items():
            base = {addr - off for off, addr in offsets.items()}
            if len(base) != 1:
                ok = False
                break
            bases[section] = base.pop()
        if not ok:
            as_fallback.append((f["name"], "its own data isn't laid out like the game's"))
            f["kind"] = "asm"
            continue
        selected = function_config(cfg, row["name"])
        fn_language = cpp.language(selected)
        extension = "cpp" if fn_language == "c++" else "c"
        convert = cpp.game_abi if fn_language == "c++" else lambda text: text
        src = out / "src" / f["seg"] / f"{f['name']}.{extension}"
        src.parent.mkdir(parents=True, exist_ok=True)
        include = "common.h" if not unit else f"common_{unit}.h"
        src.write_text(f'#include "{include}"\n\n{convert(row["matched_source"]).strip()}\n', encoding="utf-8", newline="\n")
        f["kind"] = "c"
        f["src"] = src.relative_to(out).as_posix()
        f["obj"] = f"build/src/{f['seg']}/{f['name']}.o"
        private += [(f["obj"], section, base) for section, base in bases.items()]

    # 3. everything else splat wrote: entry code, data, bss, binary blobs
    config = yaml.safe_load((out / "splat.yaml").read_text(encoding="utf-8"))
    segments = _segments(config)
    pieces = []  # (segment name, vram or None, rom offset or None, object, sections)
    for path in sorted((out / "asm").glob("*.s")) + sorted((out / "asm" / "data").glob("**/*.s")) + other_assembly:
        rom_off, vram = _first_address(path)
        obj = f"build/{path.relative_to(out).with_suffix('.o').as_posix()}"
        objects.append({"kind": "asm", "src": path.relative_to(out).as_posix(), "obj": obj,
                        "preamble": path in other_assembly})
        pieces.append((path, vram, rom_off, obj))
    blobs = []
    for seg in segments:
        if seg.get("type") == "bin":
            name = seg.get("name") or f"{seg['start']:X}"
            blob = out / "assets" / f"{name}.bin"
            if not blob.exists():
                blob.parent.mkdir(exist_ok=True)
                blob.write_bytes(image[seg["start"]:seg["end"] or len(image)])
            stub = f"asm/bin/{name}.s"
            obj = f"build/asm/bin/{name}.o"
            objects.append({"kind": "asm", "src": stub, "obj": obj})
            blobs.append((seg, obj, stub, f"assets/{name}.bin"))

    # 4. what the linker needs: segments, pieces, functions, symbols (build.py writes game.ld from it)
    defined = set()
    for path in (out / "asm").glob("**/*.s"):
        defined.update(next(x for x in m.groups() if x) for m in _DEFINES.finditer(path.read_text(errors="replace",
                                                                                                  encoding="utf-8")))
    defined.update(f["name"] for f in functions)
    module_symbols = {}
    for path in (out / "asm").glob("**/*.s"):
        text = path.read_text(encoding="utf-8", errors="replace")
        rom_off, vram = _first_address(path)
        owner = next((s.get("name") for s in segments if s.get("type") == "code" and rom_off is not None
                      and s["start"] <= rom_off < (s["end"] or len(image))), None)
        if owner is None and vram is not None:
            owner = next((s.get("name") for s in segments if s.get("type") == "code"
                          and s.get("bss_size", 0) and s["vram"] + s["end"] - s["start"] <= vram
                          < s["vram"] + s["end"] - s["start"] + s["bss_size"]), None)
        if owner is None:
            continue
        for label in _DEFINES.finditer(text):
            address, bss_address = _ADDR_COMMENT.search(text, label.end()), _BSS_COMMENT.search(text, label.end())
            if address or bss_address:
                name = next(x for x in label.groups() if x)
                value = address[2] if address and (not bss_address or address.start() < bss_address.start()) else bss_address[1]
                module_symbols.setdefault(owner, {})[name] = int(value, 16)
    layout = []
    for seg in segments:
        kind = seg.get("type")
        name = re.sub(r"\W", "_", str(seg.get("name") or f"{seg['start']:X}"))
        if kind == "header" or (kind == "hasm" and "vram" not in seg):
            layout.append({"name": name, "kind": "raw", "start": seg["start"], "objects": [f"build/asm/{seg.get('name', 'header')}.o"]})
        elif kind == "bin":
            _, obj, stub, blob = next(b for b in blobs if b[0] is seg)
            layout.append({"name": name, "kind": "raw", "start": seg["start"], "objects": [obj], "stub": stub,
                           "incbin": blob})
        elif kind == "code":
            vram, start, end = int(seg["vram"]), int(seg["start"]), seg["end"] if seg["end"] is not None else len(image)
            data, bss = [], []
            bss_vram = next((int(sub["vram"]) for sub in seg.get("subsegments", [])
                             if isinstance(sub, dict) and sub.get("type") in ("bss", "sbss") and "vram" in sub), None)
            bss_start = bss_vram if bss_vram is not None else vram + end - start
            bss_end = vram + end - start + int(seg.get("bss_size") or 0)
            for path, pv, prom, obj in pieces:
                if prom is not None and start <= prom < end:
                    data.append({"vram": pv, "obj": obj})
                elif (prom is None and pv is not None and bss_start <= pv < bss_end
                      and path.name.endswith((".bss.s", ".sbss.s"))
                      and (len(path.relative_to(out / "asm" / "data").parts) == 1
                           or path.relative_to(out / "asm" / "data").parts[0] == seg["name"])):
                    bss.append({"vram": pv, "obj": obj})
            layout.append({"name": name, "kind": "code", "start": start, "end": seg["end"], "vram": vram,
                           "bss_vram": bss_vram, "bss_size": max(0, bss_end - bss_start),
                           "pieces": sorted(data, key=lambda d: d["vram"]), "bss": sorted(bss, key=lambda d: d["vram"])})
    syms = net.symbols(proj["id"])
    absolute = {s.name: s.address for s in syms.by_name.values() if s.name not in defined}
    # Splat can emit a branch into another function as .L<address>. Each
    # function is a separate object, so that object's local label is hidden
    # from the caller. Keep the original address available to the linker.
    for path in (out / "asm").glob("**/*.s"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, address in re.findall(r"(\.L([0-9A-F]{8}))\b", text):
            absolute.setdefault(label, int(address, 16))
        # The disassembler can name an external hardware/RSP address without
        # creating an undefined-symbol file. These automatic names encode
        # their exact original address, as SymbolTable.resolve already does.
        for label in set(re.findall(r"\b[A-Za-z_]\w*\b", text)) - defined:
            if address := AUTO_NAME.fullmatch(label):
                absolute.setdefault(label, int(address[1], 16))
    for auto in ("undefined_syms_auto.txt", "undefined_funcs_auto.txt"):
        p = out / auto
        if p.exists():
            for m in re.finditer(r"^\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+)\s*;", p.read_text(encoding="utf-8"), re.M):
                if m.group(1) not in defined:
                    absolute.setdefault(m.group(1), int(m.group(2), 16))
    fn_json = []
    for f in functions:
        entry = {"name": f["name"], "seg": f["seg"], "vram": f["vram"], "rom": f["rom"], "asm": f["asm"]}
        if f["name"] in cfg.get("function_compilers", {}):
            entry["compiler"] = cfg["function_compilers"][f["name"]]
        if f["kind"] == "c":
            entry["source"] = f["src"]
            entry["own"] = {sec: base for (obj, sec, base) in private if obj == f["obj"]}
        fn_json.append(entry)

    # 5. build description, build script, objdiff, docs
    ext = IMAGE_EXT[platform]
    base = f"baserom{ext}"
    (out / image_name).rename(out / base)
    yml = out / "splat.yaml"
    yml.write_text(re.sub(r"(^\s*target_path:\s*).*$", rf"\g<1>{base}", yml.read_text(encoding="utf-8"), count=1, flags=re.M),
                   encoding="utf-8")
    build = {
        "format": format,
        "title": proj["name"], "platform": platform, "image": base, "output": f"build/game{ext}",
        "sha1": hashlib.sha1(image).hexdigest(),
        "compiler": {**cfg["compiler"], "language": language,
                     **({"cpp_frontend": cpp.ido_frontend(cfg)} if cpp.ido_frontend(cfg) else {})},
        "gp": cfg.get("gp") or 0,
        "psx_modules": cfg.get("psx_modules", {}),
        "big_endian": platform == "n64",
        "as_flags": [*AS_FLAGS[platform], "-G0", "-no-pad-sections", "-I", "include"],
        "ld_flags": [LD_ENDIAN[platform], "--no-check-sections"],
        "assembly": objects, "segments": layout, "functions": fn_json,
        "module_symbols": module_symbols,
        "symbols": {k: v for k, v in sorted(absolute.items(), key=lambda kv: kv[1])},
    }
    if container:
        (out / base).rename(out / "analysis.z64")
        shutil.copyfile(original_path, out / "baserom.z64")
        build.update(image="analysis.z64", output="build/analysis.z64", container=container)
        yml.write_text(re.sub(r"(^\s*target_path:\s*).*$", r"\g<1>analysis.z64", yml.read_text(encoding="utf-8"),
                             count=1, flags=re.M), encoding="utf-8")
    if disc and disc.get("supported"):
        disc = json.loads(json.dumps(disc))
        media = disc.get("media")
        disc_ext = ".chd" if media and media["kind"] == "chd" else ".iso" if disc["sector_size"] == 2048 else ".bin"
        shutil.copyfile(disc_path, out / ("baserom-disc" + disc_ext))
        build["disc"] = {"image": "baserom-disc" + disc_ext, "output": "build/disc" + disc_ext, "layout": disc}
        if media:
            from .psx_media import inside
            for item in media.get("companions", []):
                destination = inside(out / "baserom-media", item["name"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(inside(work / media["directory"], item["name"]), destination)
            media["directory"] = "baserom-media"
            if media["kind"] == "cue":
                build["disc"]["output"] = "build/disc-media/" + media["primary"]
                build["disc"]["companions_output"] = "build/disc-media"
            build["disc"]["artifacts"] = [{"output": build["disc"]["output"],
                "size": disc["original_size"], "sha256": disc["sha256"]}, *[
                {**item, "output": "build/disc-media/" + item["name"]} for item in media.get("companions", [])]]
    if platform == "n64" and (work / "n64-layout.json").is_file():
        from .n64_layout import number
        reviewed = json.loads((work / "n64-layout.json").read_text(encoding="utf-8"))
        build["reflow"] = {m["name"]: number(m["text_end"], "text_end") for m in reviewed["modules"] if "text_end" in m}
        build["exclusive_groups"] = {m["name"]: m["exclusive_group"] for m in reviewed["modules"] if m.get("exclusive_group")}
    if platform == "ps2" and (program := cfg["rom"].get("program")) and (work / program).is_file():
        original = (work / program).read_bytes()
        if original.startswith(b"\x7fELF"):
            shutil.copyfile(work / program, out / "baserom.elf")
            build["program"] = {"image": "baserom.elf", "output": "build/game-ps2.elf",
                                "sha1": hashlib.sha1(original).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("export_build.py"), out / "build.py")
    if platform == "psx":
        shutil.copyfile(Path(__file__).with_name("psx_mod_build.py"), out / "psx_mod.py")
    if format == "shiftable":
        shutil.copyfile(Path(__file__).with_name("export_shift.py"), out / "shiftable.py")
    units_json = []
    for f in functions:
        unit = {"name": f"{f['seg']}/{f['name']}", "target_path": f["obj_asm"],
                "metadata": {"complete": f["kind"] == "c", "source_path": f.get("src")}}
        if f["kind"] == "c":
            unit["base_path"] = f["obj"]
        units_json.append(unit)
    (out / "objdiff.json").write_text(json.dumps({"build_base": False, "build_target": False, "units": units_json}, indent=2),
                                      encoding="utf-8")
    matched = sum(1 for f in functions if f["kind"] == "c")
    source_languages = sorted({cpp.language(function_config(cfg, f["name"])) for f in functions if f["kind"] == "c"} or {language})
    _write_docs(out, proj["name"], platform, base, matched, len(functions), as_fallback,
                "mixed" if len(source_languages) > 1 else source_languages[0])
    if "disc" in build:
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write(f"\n## Complete PlayStation disc\n\nKeep your original disc as `{build['disc']['image']}` (ignored by Git). "
                       f"The build regenerates `{base}` from its program files, independently rebuilds the boot program "
                       "and discovered overlays, then writes those rebuilt bytes into their original disc extents. "
                       f"`{build['disc']['output']}` must match the entire input disc's SHA-256. All sector metadata, "
                       "filesystem records, unrelated files, padding and audio stay verbatim. File sizes and addresses "
                       "cannot change in this matching workflow. This does not qualify runtime-relocated overlays, "
                       "unknown code files or new PSY-Q assembler versions. CUE imports retain their validated "
                       "track references and every original track; CHD imports retain the original compressed "
                       "container after verifying its decoded programs. CHD recompression requires a separate "
                       "adapter. Audio stays opaque.\n")
    elif disc:
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write("\n## Disc coverage\n\nProgram payload export only: " + disc["reason"] + ".\n")
    if platform == "psx":
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write("\n## Modified source builds\n\nRun `python build.py mod` to compile source changes into fixed function slots. "
                       "An exact original-assembly baseline is required first. Function entry addresses, file extents "
                       "and headers stay fixed. Changed functions may call pinned functions/globals but cannot grow "
                       "past their original code size or introduce owned data/BSS/helpers without reviewed mod space. "
                       "Use `decompnet psx reserve PATH --module MODULE --start ADDRESS --size BYTES` to record "
                       "unused loaded zero bytes in `psx-mod-space.json`. Larger bodies, helpers and new data then "
                       "link there; entry jumps keep callers and function pointers at their original addresses. "
                       "The range must be reviewed as unused; zero padding alone does not establish that. "
                       "Interior references need layout review. Outputs and hashes are in `build/psx-mod-result.json`. ISO/BIN and CUE track "
                       "sets support modified programs; changed raw sectors receive new EDC/ECC. Nonstandard "
                       "mastering/protection and CHD recompression require dedicated authoring adapters. Reviewed "
                       "zlib/gzip modules can recompress within declared capacity and update a declared archive "
                       "length field; original loader fixup words must remain unchanged. Normal `python build.py` "
                       "remains a strict matching check.\n")
    if format == "shiftable":
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write("\n## Shiftable source builds\n\n`python build.py` keeps the exact original reconstruction check. "
                       "`python build.py inventory` verifies the original assembly baseline and inventories ELF relocations. "
                       "Edit function sources, then run `python build.py mod` to emit `build/mod.z64`. Function sizes may "
                       "change within the reviewed trailing zero reserve before data. Data, BSS, file extents and the boot "
                       "entry stay fixed; moving functions cannot add owned data/BSS. Unknown references, unsupported "
                       "relocations and exhausted reserve fail instead of producing a mod. `build/relocations.json` and "
                       "`build/shiftable-result.json` record the fixups, addresses and size budget. Cartridge checksums "
                       "are updated for the verified CIC; use `--cic` only when you have established its family yourself. "
                       "Modules and mutually exclusive overlays link independently; `--module NAME` selects one "
                       "reviewed moving window. Edited reviewed Yaz0, Rare 1172/1173 and gzip streams recompress "
                       "inside their pinned cartridge allocations and are decoded again for verification. "
                       "Exhausting compressed storage also fails and removes any previous mod output.\n")
    if container:
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write("\n## Compressed cartridge modules\n\nKeep the original cartridge as `baserom.z64`. "
                       "The build regenerates private decoded views, checks every source-built decoded byte, "
                       "then emits the original cartridge container as `build/game.z64`. Original compressed "
                       "streams are retained only after their decoded views match exactly. A changed decoded "
                       "module fails matching verification. In the shiftable format, reviewed module codecs "
                       "can re-encode changed code within the original storage allocation. Automatic joined-page "
                       "detections require an explicit reviewed layout before recompression.\n")
    if "program" in build:
        with (out / "README.md").open("a", encoding="utf-8") as docs:
            docs.write("\n## PS2 executable\n\nAlso keep your original main ELF as `baserom.elf` (ignored by Git). "
                       "The build checks the flat payload, then reconstructs `build/game-ps2.elf` using the rebuilt "
                       "sections and the original ELF headers and metadata. Both must match byte for byte. "
                       "Separate overlays and disc images are not repacked.\n")
    # everything made from the game itself stays local: build.py regenerates it from your copy
    (out / ".gitignore").write_text("build/\nbaserom*\nanalysis.z64\nasm/\nassets/\n*.ld\n*_auto.txt\n.splat/\n*.d\n",
                                    encoding="utf-8")
    # Period frontends reject CR characters. Preserve LF when Git for Windows
    # checks out this project with core.autocrlf enabled.
    (out / ".gitattributes").write_text("*.c text eol=lf\n*.cpp text eol=lf\n*.h text eol=lf\n*.hpp text eol=lf\n",
                                       encoding="utf-8", newline="\n")

    # 6. prove it
    log("building the exported project to check it rebuilds the game byte for byte")
    proc = subprocess.run(capped([sys.executable, "build.py"]), cwd=out, capture_output=True, text=True, timeout=3600,
                          encoding="utf-8", errors="replace")
    identical = proc.returncode == 0 and "identical" in proc.stdout
    if not identical:
        log((proc.stdout + proc.stderr)[-3000:])
    result = {"path": str(out), "format": format, "language": language, "identical": identical, "matched": matched,
              "source_languages": source_languages,
              "functions": len(functions), "fallback": as_fallback, "log": (proc.stdout + proc.stderr)[-3000:]}
    if disc:
        result.update(scope="disc" if "disc" in build else "program", disc={
            "supported": disc["supported"], "reason": disc.get("reason"),
            "output": build.get("disc", {}).get("output"), "programs": len(disc.get("maps", []))})
    if format == "shiftable" and identical:
        audit = subprocess.run(capped([sys.executable, "build.py", "inventory"]), cwd=out, capture_output=True,
                               text=True, timeout=3600, encoding="utf-8", errors="replace")
        result["shiftable"] = {"ready": audit.returncode == 0, "detail": (audit.stdout + audit.stderr)[-2000:]}
    return result


def _write_docs(out: Path, title: str, platform: str, base: str, matched: int, total: int, fallback, language: str = "c") -> None:
    lang, extension = ("C/C++", "{c,cpp}") if language == "mixed" else ("C++", "cpp") if language == "c++" else ("C", "c")
    names = {"n64": "Nintendo 64", "psx": "PlayStation", "ps2": "PlayStation 2"}
    notes = "".join(f"\n- `{n}`: kept as assembly, {why}" for n, why in fallback)
    (out / "README.md").write_text(f"""# {title} (decompilation)

A matching decompilation of {title} for the {names[platform]}, started with [decomp.wtf](https://decomp.wtf).
{matched} of {total} functions are {lang} that compiles to exactly the original code; the rest are still assembly.
`build.py` rebuilds the game from this tree and checks it against your original, byte for byte.
Compiler defaults are in `build.json`; a function's `compiler` object overrides
its toolchain, flags, language and C++ frontend. Mixed profiles build together.

## Build

1. Put your own copy of the game here as `{base}` (it is in `.gitignore`; never commit it).
2. `python build.py` (needs decomp.wtf installed for the period compiler and assembler).

## Layout

| Path | What it is |
| :-- | :-- |
| `src/<segment>/<function>.{extension}` | Decompiled functions, one per file, each matching the original. |
| `asm/nonmatchings/` | Assembly of every function (the target for the decompiled ones). |
| `asm/data/`, `asm/*.s`, `assets/` | Data, start-up code and binary parts, still as assembly or binary. |
| `include/common.h` | Types, structs and prototypes worked out so far. |
| `game.ld` | Places every function and data block at its original address. |
| `build.json`, `build.py` | How each file is built, and the build. |
| `objdiff.json` | Per-function units for [objdiff](https://github.com/encounter/objdiff). |

Keep going with any tool: write a function in {lang} under `src/`, add it to `build.json` (see the existing entries),
run `build.py`. When it says *identical*, the function matches. This is the base for ports and mods: once
everything is {lang}, the game can be rebuilt, changed and moved to other platforms.

The game's code and data belong to their rights holder: keep this tree to yourself unless you have the right to
share it.{chr(10) + chr(10) + '## Notes' + notes if notes else ''}
""", encoding="utf-8")
    (out / "AGENTS.md").write_text("""# Working on this decompilation

- Goal: SOURCE_LANGUAGE that the original compiler turns into exactly the original bytes. `python build.py` must end with
  "identical".
- Pick a function from `asm/nonmatchings/`, write it as `src/<segment>/<name>.SOURCE_EXTENSION` (one function,
  `#include "common.h"` first), then run `python build.py check <name>` and `python build.py`.
  The build discovers that filename automatically; its function entry in `build.json` records custom paths.
- C++ game entry points and external game declarations use `extern "C"` to retain the game's symbol names.
  Templates, classes and C++ helpers can keep C++ linkage.
- Shared types and prototypes go in `include/common.h`. Never edit `baserom*`, `asm/` or the addresses in
  `game.ld` to force a match.
""".replace("SOURCE_LANGUAGE", lang).replace("SOURCE_EXTENSION", extension), encoding="utf-8")
