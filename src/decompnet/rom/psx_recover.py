"""Agent-free console recovery: real C/C++ candidates, accepted by the full judge."""

import struct
import time
import json

from ..network import NetworkError


def leaf_candidates(code, name):
    """Straight-line integer/memory leaves; m2c handles richer control flow."""
    if len(code) % 4 or not 8 <= len(code) <= 128:
        return []
    words = struct.unpack(f"<{len(code) // 4}I", code)
    if words[-2] != 0x03E00008 or any(w >> 26 in (1, 2, 3, 4, 5, 6, 7) for w in words):
        return []
    registers = {0: "0", **{i + 4: f"a{i}" for i in range(4)}}
    used = set()
    def value(index):
        if index not in registers:
            raise ValueError()
        if 4 <= index <= 7:
            used.add(index - 4)
        return registers[index]
    def binary(a, operator, b):
        if b == "0" and operator in ("+", "-", "|", "^"):
            return a
        if a == "0" and operator in ("+", "|", "^"):
            return b
        return f"({a} {operator} {b})"
    changed, statements = False, []
    try:
        for index, word in enumerate(words):
            if not word or index == len(words) - 2:
                continue
            opcode, rs, rt, rd, shift, funct = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word >> 6 & 31, word & 63
            immediate = word & 65535
            signed = immediate - (65536 if immediate & 32768 else 0)
            target = rt
            if opcode in (32, 33, 35, 36, 37, 40, 41, 43):
                address = f"((unsigned char *)({value(rs)}) + ({signed}))"
                kind = {32: "signed char", 33: "short", 35: "int", 36: "unsigned char", 37: "unsigned short",
                        40: "unsigned char", 41: "unsigned short", 43: "int"}[opcode]
                location = f"*(({kind} *){address})"
                if opcode in (40, 41, 43):
                    statements.append(f"{location} = {value(rt)};")
                    continue
                expression = f"loaded{index}"
                statements.append(f"int {expression} = {location};")
            elif opcode == 9:
                expression = binary(value(rs), "+", str(signed))
            elif opcode in (12, 13, 14):
                expression = binary(value(rs), {12: "&", 13: "|", 14: "^"}[opcode], str(immediate))
            elif opcode == 15 and not rs:
                expression = f"0x{immediate << 16:X}U"
            elif opcode == 0 and funct in (0, 2, 3, 33, 35, 36, 37, 38, 39, 42, 43):
                target = rd
                if funct in (0, 2, 3):
                    a = value(rt)
                    if funct == 2:
                        a = f"(unsigned int){a}"
                    expression = a if not shift else f"({a} {'<<' if funct == 0 else '>>'} {shift})"
                else:
                    a, b = value(rs), value(rt)
                    if funct == 43:
                        a, b = f"(unsigned int){a}", f"(unsigned int){b}"
                    expression = binary(a, {33: "+", 35: "-", 36: "&", 37: "|", 38: "^", 39: "|", 42: "<", 43: "<"}[funct], b)
                    if funct == 39:
                        expression = f"~{expression}"
            else:
                return []
            # A leaf may not clobber stack, global, return or callee-saved state.
            if target not in (0, 1, 2, 3, *range(4, 16), 24, 25):
                return []
            if target:
                registers[target] = expression
                changed = True
            if len(expression) > 4096:
                return []
    except ValueError:
        return []
    if not changed and not statements:
        return [f"void {name}(void) {{}}"]
    if 2 not in registers and not statements:
        return []
    parameters = ", ".join(f"int a{i}" for i in range(max(used, default=-1) + 1)) or "void"
    returns = "int" if 2 in registers else "void"
    body = " ".join(statements + ([f"return {registers[2]};"] if 2 in registers else []))
    return [f"{returns} {name}({parameters}) {{ {body} }}"]


def installed_profiles(selected):
    """Period compiler, optimization, small-data and installed assembler choices."""
    from .. import toolchains
    from .psx_modules import profile
    flags, skip = [], False
    for flag in selected["flags"]:
        if skip:
            skip = False
        elif flag == "-G":
            skip = True
        elif not flag.startswith(("-O", "-G")):
            flags.append(flag)
    maspsx_available = toolchains.installed("maspsx") is not None
    assemblers = [selected.get("assembler"), None]
    if maspsx_available:
        assemblers += [{"tool": "maspsx", "version": version} for version in ("2.56", "2.86")]
    seen = set()
    languages = list(dict.fromkeys([selected.get("language", "c++"), "c++", "c"]))
    for assembler in assemblers:
        if assembler and not maspsx_available:
            continue
        for name in dict.fromkeys([selected["toolchain"], "gcc-2.7.2-psx", "gcc-2.8.1-psx"]):
            if toolchains.installed(name) is None:
                continue
            for level in ("-O2", "-O1", "-O0"):
                for small_data in ("-G8", "-G0"):
                    for language in languages:
                        override = profile(selected, {"toolchain": name, "flags": [level, small_data, *flags],
                                                      "assembler": assembler, "language": language})
                        key = json.dumps(override, sort_keys=True)
                        if key not in seen:
                            seen.add(key)
                            yield override


def _profile_search(net, slug, agent, fn, machine_drafts):
    """Probe installed period compilers; persist a profile only after exact linking."""
    from .. import seeds
    from ..project import function_config
    project = net.project_row(slug)
    selected_config = function_config(net.cfg(project), fn["name"])
    selected = selected_config["compiler"]
    context = net._context(project["id"], fn["unit"])
    sources = leaf_candidates(fn["target"], fn["name"])
    if fn["best_source"] and fn["best_source"] not in sources:
        sources.append(fn["best_source"])
    elif not fn["best_source"]:
        failed = net.store.one("SELECT source FROM attempts WHERE function_id=? AND context_version=? AND compiled=0 "
                               "AND source IS NOT NULL ORDER BY id DESC LIMIT 1", fn["id"], context["version"])
        if failed:
            sources.append(failed["source"])
    if machine_drafts and seeds.available():
        data = "\n".join(net._jtbl_asm(project, fn)) if "jtbl_" in (fn["asm"] or "") else None
        draft = net._machine_draft(fn, project, context["header"], data, valid=True)
        if draft:
            sources.append(seeds.M2C_MACROS + "\n" + draft)
    from .psx_candidates import recovery_candidates
    sources = list(dict.fromkeys(candidate for source in sources
                                for candidate in recovery_candidates(source, fn["name"], context["header"])))
    from ..psx_bios import candidates as bios_candidates
    sources.extend(source for source in bios_candidates(fn["target"], fn["name"], context["header"])
                   if source not in sources)
    if not sources:
        return None
    now = time.time()
    with net.store.tx() as db:
        net._expire_claims(db)
        current = db.execute("SELECT * FROM functions WHERE id=?", (fn["id"],)).fetchone()
        if db.execute("SELECT 1 FROM claims WHERE function_id=?", (fn["id"],)).fetchone() or \
                current is None or current["status"] != "open":
            return None
        if any(current[key] != fn[key] for key in ("name", "target", "relocs", "unit", "vram", "rom_offset")):
            return None
        db.execute("INSERT INTO claims VALUES(?,?,?,?)", (fn["id"], agent.id, now, now + 300))
    try:
        for override in installed_profiles(selected):
            cfg = net.cfg(net.project_row(slug))
            cfg["function_compilers"] = dict(cfg.get("function_compilers", {}), **{fn["name"]: override})
            candidate_project = dict(project) | {"config": json.dumps(cfg)}
            for source in sources:
                with net.store.tx() as db:
                    held = db.execute("SELECT agent_id FROM claims WHERE function_id=?", (fn["id"],)).fetchone()
                    if held is None or held["agent_id"] != agent.id:
                        return None
                    db.execute("UPDATE claims SET expires_at=? WHERE function_id=?", (time.time() + 300, fn["id"]))
                compiled = net._compile(candidate_project, context["header"], source, fn)
                if not compiled.ok:
                    continue
                candidate, exact, _ = net._evaluate(fn, candidate_project, compiled.obj)
                if candidate is None or exact is not True:
                    continue
                net.set_function_compiler(slug, fn["name"], override)
                net._record(fn, agent, 0, source, context["version"], matched=True)
                return override
    finally:
        with net.store.tx() as db:
            db.execute("DELETE FROM claims WHERE function_id=? AND agent_id=?", (fn["id"], agent.id))
    return None


def recover(net, slug, *, limit=0, max_insns=0, machine_drafts=True, search_profiles=False, log=lambda message: None):
    if limit < 0 or max_insns < 0:
        raise NetworkError("recovery limits must be nonnegative")
    project = net.project_row(slug)
    if net.cfg(project).get("platform") != "psx" or slug in net.links:
        raise NetworkError("choose a local PS1 project for console recovery")
    if net.autopilot_status(slug) and net.autopilot_status(slug)["state"] == "running":
        raise NetworkError("stop this project's browser autopilot before console recovery")
    from .. import seeds
    available = seeds.available()
    functions = net.store.all("SELECT * FROM functions WHERE project_id=? AND status='open' ORDER BY n_insns,vram,id", project["id"])
    fragments = sum(not any(fn["target"]) for fn in functions)
    eligible = [fn for fn in functions if any(fn["target"]) and (not max_insns or fn["n_insns"] <= max_insns)]
    agent, _ = net.local_agent("console-recovery")
    result = {"project": slug, "eligible": len(eligible), "tried": 0, "matched": [], "near": 0, "failed": 0,
              "claimed": 0, "m2c_available": available, "interrupted": False, "profile_matches": {}, "assembly_fragments": fragments}
    started = time.monotonic()
    try:
        for fn in eligible:
            if limit and result["tried"] >= limit:
                break
            current = net.store.one("SELECT status FROM functions WHERE id=?", fn["id"])
            if current["status"] != "open":
                continue
            if net.store.one("SELECT 1 FROM claims WHERE function_id=?", fn["id"]):
                result["claimed"] += 1
                continue
            result["tried"] += 1
            outcome = "fail"
            try:
                for source in leaf_candidates(fn["target"], fn["name"]):
                    if net.try_quietly(agent, project, fn, source)["matched"]:
                        outcome = "match"
                        break
                if outcome != "match" and machine_drafts and available:
                    outcome = net._autopilot_one(agent, project, fn["id"], prepare_seed=False)
                if outcome != "match" and search_profiles:
                    if selected := _profile_search(net, slug, agent, fn, machine_drafts):
                        result["profile_matches"][fn["name"]] = selected
                        outcome = "match"
            except (OSError, ValueError, RuntimeError, NetworkError) as error:
                log(f"{fn['name']}: {error}")
            if outcome == "match":
                result["matched"].append(fn["name"])
            elif outcome == "near":
                result["near"] += 1
            else:
                result["failed"] += 1
            log(f"{result['tried']}: {fn['name']}: {outcome}")
    except KeyboardInterrupt:
        result["interrupted"] = True
    result["remaining"] = net.store.one("SELECT COUNT(*) n FROM functions WHERE project_id=? AND status='open'", project["id"])["n"]
    result["seconds"] = round(time.monotonic() - started, 3)
    return result
