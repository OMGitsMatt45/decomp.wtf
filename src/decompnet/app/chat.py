"""Tools for the agent the user talks to: Claude Code, Codex, Antigravity CLI or opencode in the user's own terminal,
connected with `decomp mcp`. They let that agent do what the user would do in the app: list and open projects,
import the user's game, start helper agents, follow progress, export, and show the live view. Helper agents the app
starts itself only get the work tools (a helper can't start more helpers)."""

from __future__ import annotations

import time
from pathlib import Path

import anyio
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from .. import hostenv
from ..network import NetworkError
from . import agents, tools

CHAT_INSTRUCTIONS = """\
You are connected to decomp.wtf on the user's computer. Native PC source output and original-console
reconstruction are separate workflows. Use the user's own game and keep derived code/assets private.

For a DS native PC project, use generate_pc_project(path, own_copy=true, save_type=the game's chip,
ds_input_format="auto" or "decrypted"). This experimental path analyzes the ROM and generates a standalone
C++ project with a source-shipped runtime. It does not require matching every function or installing a
console compiler. For an existing DS reconstruction, use export_project(format="pc", save_type=...).
For PS1, use generate_pc_project(path, own_copy=true, platform="psx", disc_paths=[additional discs in order]).
An M3U can list the whole game. The output is one C/C++ project with adaptive OpenGL rendering and shared
memory cards. PS1 uses one screen. Its optional runtime has noncommercial terms and hybrid execution;
unknown code is interpreted, and runtime guest-code compilation is disabled. Existing imported PS1 disc
sets can use export_project(format="pc"). DS save-chip names and unified-screen options apply only to DS.
For PS2, use generate_pc_project(path, own_copy=true, platform="ps2", renderer="vulkan").
Exact-hash bundled maps are selected automatically. Closed stripped programs can be mapped automatically;
unresolved code/callbacks need ps2_profile=the local reviewed JSON map path. PS2 outputs ship a GPL-3.0 runtime and disclose IOP/VU interpretation.
For GBA, use generate_pc_project(path, own_copy=true, platform="gba"). It generates an independent
C/C++ project with raw-state OpenGL rendering, audio, keyboard/gamepad input and automatic cartridge
save/RTC detection. Uncovered ARM/Thumb code is interpreted and reported; runtime compilation is disabled.
Read the generated README for host building and controls. Report source integrity, host execution and
gameplay acceptance separately; a successful export does not certify a full game. Gameplay acceptance
is owner-run. Helpers are optional; start them only when the user requests them.

For matching console reconstruction:
1. list_projects(). If it's there, open_project(it). Otherwise import_game(path) with the path to the user's file
   (ROM, disc image or program). Use the user's existing ownership confirmation, or obtain it if missing.
   decomp.wtf only works with the user's own copy.
2. open_gui() so the user can watch: the map lights up as functions match.
3. Work: claim_function -> compile_and_diff, repeat (guide("workflow") has the loop).
   progress() shows the matching work. start_agents(count) is available when helpers are requested.
4. export_project() defaults to original-console reconstruction. Never describe matching progress as PC readiness.
Report reconstruction progress in terms of functions and % of code matched. Never publish the game's code.
"""


def register(mcp, net, manager, jobs, settings, port: int, secret: str) -> None:
    def chat_agent(ctx: Context):
        headers = ctx.headers or {}
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        try:
            agent = net.authenticate(auth.removeprefix("Bearer ").strip() or None)
        except NetworkError as e:
            raise ToolError(str(e)) from None
        if not net.is_chat(agent):
            raise ToolError("this tool is for the agent the user talks to; helper agents only decompile functions")
        return agent

    def current(agent) -> str:
        slug = manager.project_of(agent.id) or settings.data.get("last_project")
        if not slug:
            raise ToolError("no project is open: list_projects() and open_project(), or import_game(path)")
        return slug

    def resolve(name: str) -> str:
        rows = net.store.all("SELECT slug, name FROM projects ORDER BY id DESC")
        q = name.strip().lower()
        for r in rows:
            if r["slug"] == q:
                return r["slug"]
        hits = [r["slug"] for r in rows if q and (q in r["slug"].lower() or q in (r["name"] or "").lower())]
        if len(hits) == 1:
            return hits[0]
        raise ToolError(f"no single project matches {name!r}; list_projects() shows them" if not hits else
                        f"{name!r} matches several projects: {', '.join(hits)}")

    def line(ov: dict) -> str:
        pct = 100 * ov["matched_bytes"] / (ov["bytes"] or 1)
        kind = "public decomp" if ov.get("kind") == "fork" and ov.get("origin") != "scratch" else "from scratch"
        return (f"- {ov['slug']}: {ov['title']} ({ov.get('platform_name') or ov.get('platform') or '?'}, {kind}) "
                f"{ov['matched']}/{ov['functions']} functions, {pct:.1f}% of code")

    def opened(agent, slug: str) -> None:
        manager.assignments[agent.id] = slug
        settings.data["last_project"] = slug
        settings.save()

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def list_projects(ctx: Context) -> str:
        """The games in decomp.wtf on this computer, with progress. Open one with open_project."""
        agent = chat_agent(ctx)
        rows = net.store.all("SELECT slug FROM projects ORDER BY id DESC")
        out = []
        for r in rows:
            try:
                out.append(line(net.overview(r["slug"])))
            except (NetworkError, OSError, KeyError):
                continue
        cur = manager.project_of(agent.id) or settings.data.get("last_project")
        if not out:
            return "No projects yet. import_game(path) starts one from the user's own copy of a game."
        return "\n".join(out) + (f"\nOpen now: {cur}" if cur else "\nNone is open: open_project(slug).")

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def open_project(ctx: Context, project: str) -> str:
        """Work on this project (slug or part of its title). The work tools then act on it."""
        agent = chat_agent(ctx)
        slug = resolve(project)
        opened(agent, slug)
        info = await anyio.to_thread.run_sync(lambda: tools.project_info(net, slug))
        return f"{info}\nShow the user the live view with open_gui()."

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def import_game(ctx: Context, path: str, own_copy: bool = False, compiler: str = "") -> str:
        """Start decompiling a game from scratch: the user's own ROM, disc image or program file on this computer
        (PlayStation 1/2, Game Boy Advance, DS, Game Boy/Color). Discovers supported code and selects the
        configured console toolchain. Console reconstruction and native PC output have separate readiness.

        Args:
            path: the game file on this computer
            own_copy: true only after the user confirmed it's their own legally obtained copy
            compiler: optional compiler id; leave empty to let decomp.wtf pick
        """
        agent = chat_agent(ctx)
        if not own_copy:
            raise ToolError("ask the user to confirm this is their own legally obtained copy of the game, then call "
                            "import_game again with own_copy=true")
        try:
            game = hostenv.local_path(path)
        except ValueError as e:
            raise ToolError(str(e)) from None
        if not game.is_file():
            hint = {"wsl": " (decomp.wtf runs in WSL: Windows drives are under /mnt, e.g. C:\\ is /mnt/c)",
                    "docker": " (decomp.wtf runs in Docker and sees your home folder only)"}.get(hostenv.runtime(), "")
            raise ToolError(f"no file at {game}{hint}")

        def work(log):
            slug = net.import_rom(game, toolchain=compiler or None, confirmed=True, name=game.name, log=log)
            if settings.data.get("autopilot", True):  # free matches first (a public decomp says no)
                try:
                    net.start_autopilot(slug)
                except NetworkError:
                    pass
            opened(agent, slug)
            return {"slug": slug}

        return await _follow(jobs.start("import", work))

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def generate_pc_project(ctx: Context, path: str, own_copy: bool = False,
                                  save_type: str = "auto", ds_input_format: str = "auto",
                                  renderer: str = "auto", screen_mode: str = "dual",
                                  platform: str = "auto", disc_paths: list[str] | None = None,
                                  ps2_profile: str = "") -> str:
        """Generate a DS, PS1, PS2 or GBA native PC source repository from original inputs.

        No matching project or console compiler is needed. Select the cartridge save chip for a new game;
        auto infers only from an existing raw save. Use decrypted for an already-decrypted ROM.
        Set own_copy only when ownership was confirmed. The resulting README explains building/running.
        renderer: auto, opengl or software. screen_mode: dual or unified (one extended 3D camera, requires OpenGL).
        PS1 uses one screen; disc_paths lists additional discs in game order, sharing one build and memory cards.
        platform: auto, nds, psx, ps2 or gba. GBA cartridges auto-detect their save chip and RTC.
        PS1 CUE files require their companion tracks; M3U playlists are supported.
        PS2 uses Vulkan (renderer=auto, vulkan or software). ps2_profile is an optional local reviewed
        code-map path, needed for unresolved code/callbacks without a bundled exact-hash profile.
        """
        chat_agent(ctx)
        if not own_copy:
            raise ToolError("confirm this is the user's own legally obtained copy, then use own_copy=true")
        try:
            game = hostenv.local_path(path)
        except ValueError as error:
            raise ToolError(str(error)) from None
        from .. import pc
        target=platform if platform!='auto' else pc.input_platform(game)
        if target=='gba':
            if disc_paths:raise ToolError('additional discs apply to PS1')
            return await _follow(jobs.start('pc-export',lambda log:net.generate_gba_pc(game,
                confirmed=True,save_type=save_type,renderer=renderer,log=log)))
        if target=='ps2':
            if disc_paths:raise ToolError('additional discs apply to PS1')
            try:profile=hostenv.local_path(ps2_profile) if ps2_profile else None
            except ValueError as error:raise ToolError(str(error)) from None
            return await _follow(jobs.start('pc-export',lambda log:net.generate_ps2_pc(game,
                confirmed=True,profile=profile,renderer=renderer,log=log)))
        if target=='psx':
            try:games=[game,*[hostenv.local_path(value) for value in (disc_paths or [])]]
            except ValueError as error:raise ToolError(str(error)) from None
            return await _follow(jobs.start('pc-export',lambda log: net.generate_psx_pc(games,
                confirmed=True,renderer=renderer,log=log)))
        if target!='nds' or disc_paths:raise ToolError('select nds, psx, ps2 or gba; additional discs apply to PS1')
        return await _follow(jobs.start("pc-export", lambda log: net.generate_ds_pc(game,
            confirmed=True, input_format=ds_input_format, save_type=save_type,
            renderer=renderer,screen_mode=screen_mode,log=log)))

    async def _follow(jid: str, wait: float = 55) -> str:
        job = jobs.jobs[jid]
        t0 = time.time()
        while job["state"] == "running" and time.time() - t0 < wait:
            await anyio.sleep(0.5)
        if job["state"] == "running":
            tail = job["log"][-1] if job["log"] else "working"
            return f"Still working ({tail}). Call import_status(job=\"{jid}\") to keep waiting."
        if job["state"] == "error":
            raise ToolError(f"{job.get('kind','import')} failed: {job['error']}")
        if job["result"].get("format") == "pc":
            return (f"Native PC source project: {job['result']['path']}. Source integrity verified. "
                    "Read its README for building and controls. This backend is experimental; gameplay acceptance is separate.")
        slug = job["result"]["slug"]
        info = await anyio.to_thread.run_sync(lambda: tools.project_info(net, slug))
        ov = net.overview(slug)
        ap = " Autopilot is trying every function's machine draft in the background." if ov.get("autopilot") else ""
        return (f"Imported as {slug}.{ap}\n{info}\nNext: open_gui() so the user can watch, then claim_function(), "
                f"with start_agents() available if the user requests helpers.")

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def import_status(ctx: Context, job: str) -> str:
        """Keep waiting for a game import or native PC generation job that was still running."""
        chat_agent(ctx)
        if job not in jobs.jobs:
            raise ToolError("no such job")
        return await _follow(job)

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def open_gui(ctx: Context) -> str:
        """Open decomp.wtf's live view of the current project in the user's browser: the function map, what every
        agent is doing, diffs, progress. Do this once when you start, so the user can watch."""
        agent = chat_agent(ctx)
        slug = manager.project_of(agent.id) or settings.data.get("last_project")
        url = f"http://127.0.0.1:{port}/?k={secret}" + (f"#/p/{slug}" if slug else "")
        ok = await anyio.to_thread.run_sync(lambda: hostenv.open_url(url))
        where = f"http://127.0.0.1:{port}/" + (f"#/p/{slug}" if slug else "")
        if ok:
            return f"Opened the live view in the user's browser ({where})."
        if hostenv.runtime() == "docker":  # the container can't reach the user's browser: hand them the link
            return f"Give the user this link to open the live view (it signs their browser in): {url}"
        return f"Couldn't open a browser here; the user can run `decomp` to open the app ({where})."

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def start_agents(ctx: Context, count: int = 1, kind: str = "", per_session: int = 0) -> str:
        """Start helper agents that decompile the current project in parallel with you (headless, shown live in
        the app). `kind`: claude, codex, antigravity or opencode (default: the first one installed)."""
        agent = chat_agent(ctx)
        slug = current(agent)
        if not kind:
            kind = next((a["id"] for a in agents.detect() if a["installed"] and a["id"] != "api"), "")
            if not kind:
                raise ToolError("no agent CLI is installed for helpers (Claude Code, Codex, Antigravity CLI or opencode)")
        options = {"per_session": per_session or settings.data.get("per_session", agents.PER_SESSION)}
        try:
            ids = manager.start(kind, slug, max(1, min(int(count), 8)), options)
        except ValueError as e:
            raise ToolError(str(e)) from None
        return (f"Started {', '.join(ids)} on {slug}. They claim functions you aren't working on; progress() and "
                f"the live view show their work. stop_agents() stops them.")

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def stop_agents(ctx: Context) -> str:
        """Stop the helper agents working on the current project."""
        agent = chat_agent(ctx)
        slug = current(agent)
        stopped = [s.id for s in list(manager.sessions.values()) if s.slug == slug and s.state in ("starting", "working", "waiting")]
        for sid in stopped:
            manager.stop(sid)
        return f"Stopped {', '.join(stopped)}." if stopped else "No helper agents were running on this project."

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def progress(ctx: Context) -> str:
        """Where the current project stands: matched code, who is working on what, autopilot, recent matches."""
        agent = chat_agent(ctx)
        slug = current(agent)

        def build() -> str:
            ov = net.overview(slug)
            live = net.live(slug)
            out = [line(ov).lstrip("- ")]
            ap = ov.get("autopilot")
            if ap:
                out.append(f"autopilot: {ap['state']}, {ap['tried']}/{ap['total']} drafts tried, {ap['matched']} matched")
            working = [f"{c['agent']} on {c['name']}" for c in live["claims"] if c["agent"] != "autopilot"]
            out.append("working now: " + (", ".join(working) if working else "nobody"))
            helpers = [f"{s.id} ({s.state})" for s in manager.sessions.values() if s.slug == slug]
            if helpers:
                out.append("helper agents: " + ", ".join(helpers))
            matches = [e for e in live["events"] if e["kind"] == "match"][-8:]
            if matches:
                out.append("recent matches: " + ", ".join(f"{e['detail']} ({e['agent']})" for e in matches))
            return "\n".join(out)

        return await anyio.to_thread.run_sync(build)

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def run_autopilot(ctx: Context) -> str:
        """Try every open function's machine draft again (free matches). Worth it after types and names improved."""
        agent = chat_agent(ctx)
        slug = current(agent)
        try:
            st = net.start_autopilot(slug)
        except NetworkError as e:
            raise ToolError(str(e)) from None
        return f"Autopilot is trying {st['total']} functions' machine drafts in the background; progress() shows it."

    @mcp.tool(meta=tools.ALWAYS_LOAD)
    async def export_project(ctx: Context, format: str = "matching", save_type: str = "auto",
                             renderer: str = "auto", screen_mode: str = "dual") -> str:
        """Export the current project: matching console reconstruction by default, or experimental native PC
        sources with format=pc on DS/PS1. Choose the cartridge save chip for DS; a PS1 disc set shares
        one executable and memory cards. Returns the output path;
        source integrity and matching-console verification do not certify gameplay.
        """
        agent = chat_agent(ctx)
        slug = current(agent)
        if format not in ("matching","pc"):
            raise ToolError("choose matching console reconstruction or pc output")
        if format == "pc":
            return await _follow(jobs.start("pc-export", lambda log: net.export_rom(slug,
                format="pc",save_type=save_type,renderer=renderer,screen_mode=screen_mode,log=log)))
        try:
            res = await anyio.to_thread.run_sync(lambda: net.export_rom(slug, log=lambda *_: None))
        except (NetworkError, RuntimeError, OSError) as e:
            raise ToolError(str(e)) from None
        if res.get("identical") is None:
            return f"This project is already a source tree: {res['path']} (every match is committed to git)."
        verdict = "rebuilds the game byte for byte" if res["identical"] else "does NOT rebuild identically yet"
        return f"Exported to {res['path']}: {res.get('matched')} of {res.get('functions')} functions are C; it {verdict}."
