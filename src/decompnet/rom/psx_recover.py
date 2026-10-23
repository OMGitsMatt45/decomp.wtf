"""Agent-free console recovery: real C/C++ candidates, accepted by the full judge."""

import struct
import time
import json

from ..network import NetworkError


def leaf_candidates(code, name):
    """Straight-line integer leaves only; m2c handles richer control flow later."""
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
    changed = False
    try:
        for index, word in enumerate(words):
            if not word or index == len(words) - 2:
                continue
            opcode, rs, rt, rd, shift, funct = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word >> 6 & 31, word & 63
            immediate = word & 65535
            signed = immediate - (65536 if immediate & 32768 else 0)
            target = rt
            if opcode == 9:
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
    if not changed:
        return [f"void {name}(void) {{}}"]
    if 2 not in registers:
        return []
    parameters = ", ".join(f"int a{i}" for i in range(max(used, default=-1) + 1)) or "void"
    return [f"int {name}({parameters}) {{ return {registers[2]}; }}"]


def _profile_search(net, slug, agent, fn, machine_drafts):
    """Probe installed period compilers; persist a profile only after exact linking."""
    from .. import cpp, seeds, toolchains
    from ..project import function_config
    from .psx_modules import profile
    project = net.project_row(slug)
    selected_config = function_config(net.cfg(project), fn["name"])
    selected = selected_config["compiler"]
    context = net._context(project["id"], fn["unit"])
    sources = leaf_candidates(fn["target"], fn["name"])
    if machine_drafts and seeds.available():
        data = "\n".join(net._jtbl_asm(project, fn)) if "jtbl_" in (fn["asm"] or "") else None
        draft = seeds.generate_from_asm(net._asm_text(fn, project), fn["name"], selected["toolchain"],
                                        context["header"], data, valid=True, language=cpp.language(selected_config))
        if draft:
            sources.append(seeds.M2C_MACROS + "\n" + draft)
    if not sources:
        return None
    now = time.time()
    with net.store.tx() as db:
        net._expire_claims(db)
        if db.execute("SELECT 1 FROM claims WHERE function_id=?", (fn["id"],)).fetchone() or \
                db.execute("SELECT status FROM functions WHERE id=?", (fn["id"],)).fetchone()["status"] != "open":
            return None
        db.execute("INSERT INTO claims VALUES(?,?,?,?)", (fn["id"], agent.id, now, now + 300))
    try:
        flags = [flag for flag in selected["flags"] if not flag.startswith("-O")]
        for name in dict.fromkeys([selected["toolchain"], "gcc-2.7.2-psx", "gcc-2.8.1-psx"]):
            if toolchains.installed(name) is None:
                continue
            for optimization in ("-O2", "-O1", "-O0"):
                override = profile(selected, {"toolchain": name, "flags": [optimization, *flags]})
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
    eligible = [fn for fn in functions if not max_insns or fn["n_insns"] <= max_insns]
    agent, _ = net.local_agent("console-recovery")
    result = {"project": slug, "eligible": len(eligible), "tried": 0, "matched": [], "near": 0, "failed": 0,
              "claimed": 0, "m2c_available": available, "interrupted": False, "profile_matches": {}}
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
                    outcome = net._autopilot_one(agent, project, fn["id"])
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
