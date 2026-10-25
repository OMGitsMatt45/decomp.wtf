"""Explicitly reviewed PS1 function-boundary repairs, with original evidence."""

import hashlib
import json
from pathlib import Path
import re
import struct
import time

from ..network import NetworkError
from . import split


def _json_row(row):
    return {key: {"encoding": "hex", "data": value.hex()} if isinstance(value, bytes) else value
            for key, value in dict(row).items()}


def _branches(code, address):
    for offset, (word,) in enumerate(struct.iter_unpack("<I", code)):
        pc = address + offset * 4
        opcode = word >> 26
        if opcode in (2, 3):
            yield offset * 4, (pc + 4) & 0xF0000000 | (word & 0x3FFFFFF) << 2, opcode == 3
        elif opcode in (1, 4, 5, 6, 7):
            immediate = word & 0xFFFF
            if immediate & 0x8000:
                immediate -= 0x10000
            yield offset * 4, pc + 4 + immediate * 4, opcode == 1 and (word >> 16 & 31) in (16, 17)


def _constant_references(code):
    """Simple absolute address formation, including unannotated LUI pairs."""
    values = {0: 0}
    for word, in struct.iter_unpack("<I", code):
        opcode, rs, rt, rd, funct = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word & 63
        immediate = word & 0xFFFF
        signed = immediate - (0x10000 if immediate & 0x8000 else 0)
        if opcode in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2B, 0x2E) and rs in values:
            yield (values[rs] + signed) & 0xFFFFFFFF
        destination, value = None, None
        if opcode == 15:
            destination, value = rt, immediate << 16
        elif opcode in (8, 9, 13):
            destination = rt
            if rs in values:
                value = ((values[rs] | immediate) if opcode == 13 else values[rs] + signed) & 0xFFFFFFFF
        elif opcode == 0 and funct in (33, 37):
            destination = rd
            if rs in values and rt in values:
                value = ((values[rs] + values[rt]) if funct == 33 else values[rs] | values[rt]) & 0xFFFFFFFF
        elif opcode == 0 and funct not in (8, 12, 13, 17, 19, 24, 25, 26, 27):
            destination = rd
        elif 8 <= opcode <= 14 or 0x20 <= opcode <= 0x27 or opcode in (16, 17, 18):
            destination = rt
        if destination:
            values.pop(destination, None)
            if value is not None:
                values[destination] = value
                yield value
        if opcode in (1, 2, 3, 4, 5, 6, 7) or opcode == 0 and funct in (8, 9):
            values = {0: 0}


def _external_references(db, project, head, tail, image, segments):
    start, stop = tail["vram"], tail["vram"] + tail["size"]
    rows = db.execute("SELECT * FROM functions WHERE project_id=?", (project["id"],)).fetchall()
    name = re.compile(r"\b" + re.escape(tail["name"]) + r"\b")
    for row in rows:
        if row["id"] in (head["id"], tail["id"]):
            continue
        if any(start <= reference[2] < stop for reference in json.loads(row["relocs"] or "[]")) or any(
                start <= address < stop for _, address, _ in _branches(row["target"], row["vram"])) or any(
                start <= address < stop for address in _constant_references(row["target"])):
            raise NetworkError(f"{row['name']} references the proposed tail; keep its boundary")
        if any(name.search(row[field] or "") for field in ("asm", "matched_source", "best_source", "seed")):
            raise NetworkError(f"{row['name']} names the proposed tail; review that reference first")
    for context in db.execute("SELECT header FROM context_versions WHERE project_id=?", (project["id"],)):
        if name.search(context["header"] or ""):
            raise NetworkError("the context names the proposed tail; review its declaration first")
    code_ranges = sorted((row["rom_offset"], row["rom_offset"] + row["size"]) for row in rows
                         if row["rom_offset"] is not None)
    for segment in segments:
        cursor = 0
        for offset in range(segment.rom_start + (-segment.vram % 4), segment.rom_end - 3, 4):
            while cursor < len(code_ranges) and code_ranges[cursor][1] <= offset:
                cursor += 1
            if cursor < len(code_ranges) and code_ranges[cursor][0] <= offset < code_ranges[cursor][1]:
                continue
            pointer = struct.unpack_from("<I", image, offset)[0]
            if start <= pointer < stop:
                raise NetworkError(f"data at ROM offset 0x{offset:X} points into the proposed tail")


def merge_reviewed(net, slug, head_name, tail_name, *, agent, reason):
    """Merge two explicitly reviewed open ranges; this does not recover source.

    Both old rows and their attempts remain verbatim in an append-only review
    record. The tail leaves the active function table only after that snapshot;
    the surviving head starts open, without scores for the old shorter target.
    """
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        raise NetworkError("provide the reviewed evidence for this boundary merge")
    project = net.project_row(slug)
    if slug in net.links or not net.is_rom(project) or net.cfg(project).get("platform") != "psx":
        raise NetworkError("reviewed boundary merges require a local PS1 ROM project")
    with net.store.tx() as db:
        project = db.execute("SELECT * FROM projects WHERE id=?", (project["id"],)).fetchone()
        if project is None:
            raise NetworkError("the PS1 project is no longer available")
        cfg = net.cfg(project)
        if cfg.get("kind") != "rom" or cfg.get("platform") != "psx":
            raise NetworkError("reviewed boundary merges require a local PS1 ROM project")
        if cfg.get("big_endian", True):
            raise NetworkError("PS1 boundary merges require little-endian original code")
        net._expire_claims(db)
        rows = [db.execute("SELECT * FROM functions WHERE project_id=? AND name=?", (project["id"], name)).fetchone()
                for name in (head_name, tail_name)]
        if any(row is None for row in rows) or rows[0]["id"] == rows[1]["id"]:
            raise NetworkError("choose two distinct existing PS1 function ranges")
        head, tail = rows
        ids = (head["id"], tail["id"])
        if any(row["status"] != "open" for row in rows):
            raise NetworkError("both reviewed ranges must be open; matched source is preserved")
        if db.execute("SELECT 1 FROM claims WHERE function_id IN (?,?)", ids).fetchone():
            raise NetworkError("a reviewed range is claimed; finish or release its work first")
        if head["unit"] != tail["unit"] or any(row["vram"] is None or row["rom_offset"] is None for row in rows) or \
                head["vram"] + head["size"] != tail["vram"] or head["rom_offset"] + head["size"] != tail["rom_offset"]:
            raise NetworkError("reviewed ranges must be adjacent in the same module, RAM and ROM")
        for row in rows:
            if not row["size"] or row["size"] % 4 or len(row["target"] or b"") != row["size"] or row["n_insns"] * 4 != row["size"]:
                raise NetworkError("a reviewed range has inconsistent original byte boundaries")
        overlap = db.execute("SELECT 1 FROM functions WHERE project_id=? AND unit=? AND id NOT IN (?,?) "
                             "AND vram < ? AND vram+size > ?", (project["id"], head["unit"], *ids,
                              tail["vram"] + tail["size"], head["vram"])).fetchone()
        if overlap:
            raise NetworkError("another function overlaps the proposed merged range")
        try:
            image = (Path(project["root"]) / cfg["rom"]["file"]).read_bytes()
            segments = [split.Segment(**segment) for segment in cfg["segments"]]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise NetworkError("the original PS1 image and module map must be available") from error
        if any(segment.rom_start < 0 or segment.rom_end > len(image) or segment.rom_end < segment.rom_start for segment in segments):
            raise NetworkError("the PS1 module map exceeds the original image")
        code = head["target"] + tail["target"]
        if not any(segment.rom_start <= head["rom_offset"] and tail["rom_offset"] + tail["size"] <= segment.rom_end
                   and segment.vram + head["rom_offset"] - segment.rom_start == head["vram"] for segment in segments) or \
                image[head["rom_offset"]:head["rom_offset"] + len(code)] != code:
            raise NetworkError("reviewed targets differ from their contiguous original ROM bytes")
        _external_references(db, project, head, tail, image, segments)
        parsed = [net._parse_asm(row["name"], row["asm"], row["unit"]) for row in rows]
        for row, function in zip(rows, parsed):
            if b"".join(line.word.to_bytes(4, "little") for line in function.lines) != row["target"] or any(
                    line.vram != row["vram"] + index * 4 or line.rom != row["rom_offset"] + index * 4
                    for index, line in enumerate(function.lines)):
                raise NetworkError("a stored assembly listing differs from its original bytes or coordinates")
        lines = parsed[0].lines + parsed[1].lines
        labels = parsed[0].labels | parsed[1].labels
        for offset, destination, call in _branches(code, head["vram"]):
            if head["vram"] <= destination < tail["vram"] + tail["size"]:
                if call:
                    if tail["vram"] <= destination:
                        raise NetworkError("a call enters the proposed tail; preserve that function entry")
                    continue
                labels.add(destination)
                line = lines[offset // 4]
                line.operands = re.sub(r"[^,\s]+\s*$", f".L{destination:08X}", line.operands)
        merged = split.RomFunction(head["name"], head["vram"], head["rom_offset"], head["unit"], lines, Path(), labels)
        assembly = net._asm_source(merged)
        if head["vram"] in labels:
            assembly = assembly.replace(f"glabel {head_name}\n", f"glabel {head_name}\n.L{head['vram']:08X}:\n", 1)
        relocs = json.loads(head["relocs"] or "[]") + [[head["size"] + offset, kind, address]
                  for offset, kind, address in json.loads(tail["relocs"] or "[]")]
        attempts = db.execute("SELECT * FROM attempts WHERE function_id IN (?,?) ORDER BY id", ids).fetchall()
        notes = db.execute("SELECT * FROM notes WHERE function_id IN (?,?) ORDER BY id", ids).fetchall()
        symbols = db.execute("SELECT * FROM symbols WHERE project_id=? AND (name IN (?,?) OR address BETWEEN ? AND ?)",
                             (project["id"], head_name, tail_name, head["vram"], tail["vram"] + tail["size"] - 1)).fetchall()
        misses = db.execute("SELECT * FROM twin_misses WHERE function_id IN (?,?)", ids).fetchall()
        evidence = {"format": 1, "head": _json_row(head), "tail": _json_row(tail),
                    "attempts": [_json_row(row) for row in attempts], "notes": [_json_row(row) for row in notes],
                    "symbols": [_json_row(row) for row in symbols], "twin_misses": [_json_row(row) for row in misses],
                    "compiler": cfg.get("compiler"),
                    "function_compilers": {name: cfg.get("function_compilers", {}).get(name) for name in (head_name, tail_name)},
                    "symbol_modules": {name: cfg.get("symbol_modules", {}).get(name) for name in (head_name, tail_name)},
                    "image_sha256": hashlib.sha256(image).hexdigest(), "merged_sha256": hashlib.sha256(code).hexdigest()}
        db.execute("CREATE TABLE IF NOT EXISTS psx_boundary_reviews(id INTEGER PRIMARY KEY, "
                   "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
                   "agent_id INTEGER, created_at REAL NOT NULL, head_id INTEGER NOT NULL, tail_id INTEGER NOT NULL, "
                   "reason TEXT NOT NULL, evidence TEXT NOT NULL)")
        review = db.execute("INSERT INTO psx_boundary_reviews(project_id,agent_id,created_at,head_id,tail_id,reason,evidence) "
                            "VALUES(?,?,?,?,?,?,?)", (project["id"], agent.id, time.time(), *ids, reason.strip(), json.dumps(evidence))).lastrowid
        db.execute("DELETE FROM attempts WHERE function_id IN (?,?)", ids)
        db.execute("DELETE FROM twin_misses WHERE function_id IN (?,?)", ids)
        db.execute("UPDATE notes SET function_id=? WHERE function_id=?", ids)
        db.execute("UPDATE functions SET size=?,n_insns=?,target=?,relocs=?,asm=?,seed=NULL,best_score=NULL,best_source=NULL,"
                   "best_agent_id=NULL,matched_source=NULL,matched_agent_id=NULL,matched_at=NULL,attempts=0,abandons=0,"
                   "fingerprint=NULL,boost=0 WHERE id=?", (len(code), len(lines), code, json.dumps(relocs), assembly, head["id"]))
        db.execute("DELETE FROM functions WHERE id=?", (tail["id"],))
        db.execute("DELETE FROM symbols WHERE project_id=? AND name=?", (project["id"], tail_name))
        db.execute("UPDATE symbols SET size=? WHERE project_id=? AND name=?", (len(code), project["id"], head_name))
        for mapping in ("function_compilers", "symbol_modules"):
            cfg.get(mapping, {}).pop(tail_name, None)
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), project["id"]))
        net._event(db, project["id"], agent.id, "merge", f"{head_name} + {tail_name}; review {review}: {reason.strip()}")
    for cache in (net._syms, net._xrefs, net._ops):
        cache.pop(project["id"], None)
    for key in list(net._diffs):
        if key[0] in ids:
            net._diffs.pop(key, None)
    net.twins.forget(project)
    return {"project": slug, "function": head_name, "retired": tail_name, "review": review,
            "size": len(code), "sha256": hashlib.sha256(code).hexdigest(), "status": "open"}
