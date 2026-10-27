"""The local decomp.wtf server: the GUI, its API, and the MCP endpoint agents connect to.

It listens on 127.0.0.1 only. The GUI needs a per-launch secret (handed to the browser in the URL the
app opens, then kept in a same-site cookie); agents need their own bearer token. Host headers are
checked on every request, so web pages can't reach it through DNS rebinding.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import mimetypes
import re
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from importlib import resources
from pathlib import Path

import anyio
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import __version__, hostenv, toolchains
from ..network import NetworkError
from ..rom.errors import RomError
from . import agents, chat, connect, tools, updates
from .engine import COMPILERS, MW_VERSIONS, PLATFORM_STATUS, SHORT_NAMES, TOOLS, RomNetwork

COOKIE = "decomp_live"
MAX_DISC = 16 * 1024 * 1024 * 1024  # dual-layer DVD and then some


def file_log(path: Path) -> logging.Logger:
    """decomp.wtf's own log (logs/decomp.log in its data folder): every job, what it said, and every error with its
    traceback, so a failed import can be reported with the whole story."""
    logger = logging.getLogger("decomp.wtf")
    if not any(getattr(h, "baseFilename", None) == str(path) for h in logger.handlers):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(path, maxBytes=2 << 20, backupCount=2, encoding="utf-8")
        except OSError:
            return logger
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _tool_of(cmd) -> str:
    """The program a command ran (past a systemd-run wrapper), by name."""
    argv = [str(a) for a in cmd] if isinstance(cmd, (list, tuple)) else str(cmd).split()
    if "--" in argv and Path(argv[0]).name.startswith("systemd-run"):
        argv = argv[argv.index("--") + 1:]
    return Path(argv[0]).name if argv else "a tool"


def job_error(e: BaseException, log_path: Path | None = None) -> str:
    """What to tell the user when a job fails: why, in words, for every kind of failure."""
    if isinstance(e, subprocess.TimeoutExpired):
        mins = max(1, round((e.timeout or 0) / 60))
        return (f"{_tool_of(e.cmd)} took longer than {mins} minute{'s' if mins != 1 else ''} and was stopped. "
                "A very big game can need more: please report it, with the log")
    if isinstance(e, subprocess.CalledProcessError):
        said = e.stderr or e.output or ""  # what the command said, so the error shows why
        said = (said.decode("utf-8", "replace") if isinstance(said, bytes) else said).strip()
        return f"{_tool_of(e.cmd)} failed ({e.returncode})" + (f": {said[-400:]}" if said else "")
    if isinstance(e, MemoryError):
        return "this computer ran out of memory: close other programs and try again"
    if isinstance(e, (NetworkError, RomError, toolchains.ToolchainError, ValueError, RuntimeError, OSError)):
        return str(e) or type(e).__name__
    where = f" (the log: {hostenv.shown_path(log_path)})" if log_path else ""
    return (f"something went wrong inside decomp.wtf ({type(e).__name__}: {e}). That's a bug: please report it with "
            f"the log{where}")


class Jobs:
    """Background work the GUI can follow: imports and installs. A job always ends: done, or an error that says why
    (never `running` forever because of an error nobody caught). Everything goes to the log file too."""

    def __init__(self, log_path: Path | None = None):
        self.jobs: dict[str, dict] = {}
        self.log_path = log_path
        self.logger = file_log(log_path) if log_path else logging.getLogger("decomp.wtf")

    def start(self, kind: str, fn) -> str:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "kind": kind, "state": "running", "log": [], "result": None, "error": None, "t": time.time()}
        self.jobs[jid] = job
        logger = self.logger
        logger.info("job %s %s started", kind, jid)

        def log(line: str) -> None:
            job["log"].append(str(line))
            logger.info("[%s %s] %s", kind, jid[:6], line)

        def run():
            try:
                job["result"] = fn(log)
                job["state"] = "done"
                logger.info("job %s %s done in %.0fs", kind, jid, time.time() - job["t"])
            except BaseException as e:  # noqa: BLE001: a job must end, whatever went wrong
                if getattr(e, "details", None):  # what the tool said, in full
                    job["trace"] = str(e.details)[-6000:]
                elif not isinstance(e, (NetworkError, RomError, ValueError)):
                    job["trace"] = traceback.format_exc()[-4000:]
                job["error"] = job_error(e, self.log_path)
                job["state"] = "error"  # last: whoever sees the state sees the rest
                logger.error("job %s %s failed: %s\n%s", kind, jid, job["error"], traceback.format_exc())
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return jid


class Settings:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data.get("endpoints"), list):  # one saved "api" before 0.10.1: the first endpoint
            old = self.data.get("api") if isinstance(self.data.get("api"), dict) else {}
            self.data["endpoints"] = [agents.endpoint_entry(old | {"id": "e1"})] if old.get("base_url") or old.get("provider") else []

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- API endpoints: OpenAI-compatible servers for the built-in agent, each with its own address, model and key

    def endpoints(self) -> list[dict]:
        return [e for e in self.data.get("endpoints") or [] if isinstance(e, dict) and e.get("id")]

    def endpoint(self, eid: str) -> dict | None:
        return next((e for e in self.endpoints() if e["id"] == eid), None)

    def save_endpoint(self, data: dict) -> dict:
        """Add an endpoint (no id) or change one. A key is only replaced by a new one typed in (the masked one the
        GUI shows comes back unchanged)."""
        numbers = {}
        for k in ("context_tokens", "max_sessions"):  # the model's context in tokens (empty = find out); a box's limit
            if k in data:
                try:
                    numbers[k] = int(str(data[k] or "").strip() or 0)
                except ValueError:
                    raise ValueError("the context size is a number of tokens, like 16384" if k == "context_tokens"
                                     else "the session limit is a number, like 1") from None
        current = self.endpoint(str(data.get("id") or ""))
        if current is None:  # ids are never reused: a session resumed later can't end up on another machine
            ids = {e["id"] for e in self.endpoints()}
            n = max(int(self.data.get("endpoint_seq") or 0), len(ids)) + 1
            while f"e{n}" in ids:
                n += 1
            self.data["endpoint_seq"] = n
            current = {"id": f"e{n}"}
            self.data.setdefault("endpoints", []).append(current)
        for k in ("name", "provider", "base_url", "model"):
            if k in data:
                current[k] = str(data[k] or "").strip()
        for k, n in numbers.items():
            if n:
                current[k] = max(2048, n) if k == "context_tokens" else max(1, min(n, 32))
            else:
                current.pop(k, None)
        if data.get("api_key") and "•" not in str(data["api_key"]):
            current["api_key"] = str(data["api_key"]).strip()
        if data.get("clear_key"):
            current.pop("api_key", None)
        current.update(agents.endpoint_entry(current))
        return current

    def remove_endpoint(self, eid: str) -> None:
        self.data["endpoints"] = [e for e in self.endpoints() if e["id"] != eid]

    def public(self) -> dict:
        def masked(e: dict) -> dict:
            out = {k: v for k, v in e.items() if k != "api_key"}
            if e.get("api_key"):
                out["api_key"], out["has_key"] = "•" * 8 + e["api_key"][-4:], True
            return out

        eps = [masked(e) for e in self.endpoints()]
        return {"endpoints": eps, "api": eps[0] if eps else {},
                "per_session": self.data.get("per_session", agents.PER_SESSION), "last_project": self.data.get("last_project"),
                "autopilot": self.data.get("autopilot", True), "budget_usd": self.data.get("budget_usd") or 0,
                "auto_update": bool(self.data.get("auto_update")), "check_updates": self.data.get("check_updates", True) is not False,
                "launcher": _launcher(self.data.get("launcher") or {}), "recent_models": self.data.get("recent_models") or {}}


def _session_options(entry: dict) -> dict:
    """What a built-in agent session needs from its endpoint."""
    out = {"endpoint": entry.get("id") or "", "provider": entry["provider"], "base_url": entry["base_url"],
           "model": entry["model"], "provider_name": entry["name"]}
    return out | {k: entry[k] for k in ("api_key", "context_tokens") if entry.get(k)}


def _spread(settings: Settings, manager, picked: list[str], count: int, given: dict) -> list[tuple[dict, int]]:
    """(endpoint, sessions) for a start of `count` built-in agent sessions: spread over the endpoints picked, one
    at a time in turn, each up to its own limit of sessions at once (a small box serves one request at a time).
    A start without endpoints (an older GUI, or an address typed in) uses the first saved one, with what it
    changes; a saved key only ever goes to its own endpoint's address."""
    if not picked:
        first = settings.endpoints()[0] if settings.endpoints() else {}
        typed = {k: v for k, v in given.items() if k in ("provider", "base_url", "model", "context_tokens") and v}
        entry = agents.endpoint_entry(first | typed)
        if first and entry["base_url"].rstrip("/") != first["base_url"].rstrip("/"):
            entry.pop("api_key", None)
        if not entry.get("base_url") or not entry.get("model"):
            raise ValueError("add an API endpoint first (Agents & models): its address and model")
        return [(entry, count)]
    eps = [settings.endpoint(e) for e in picked]
    if any(e is None for e in eps):
        raise ValueError("an endpoint you picked isn't saved any more: pick again")
    busy = {e["id"]: sum(1 for x in manager.sessions.values() if x.kind == "api" and x.options.get("endpoint") == e["id"]
                         and x.state in ("starting", "working", "waiting") and not x.stop.is_set()) for e in eps}
    plan = {e["id"]: 0 for e in eps}
    for _ in range(count):
        room = [e for e in eps if not e.get("max_sessions") or busy[e["id"]] + plan[e["id"]] < int(e["max_sessions"])]
        if not room:
            break
        pick = min(room, key=lambda e: (busy[e["id"]] + plan[e["id"]], eps.index(e)))
        plan[pick["id"]] += 1
    if not any(plan.values()):
        raise ValueError("every endpoint you picked already runs as many sessions as you allowed it")
    return [(e, plan[e["id"]]) for e in eps if plan[e["id"]]]


def _launcher(saved: dict) -> dict:
    """The last launcher choice; one saved for Gemini CLI (retired) comes back as Antigravity with its default model."""
    if saved.get("kind") and agents.kind_id(saved["kind"]) != saved["kind"]:
        return {**saved, "kind": agents.kind_id(saved["kind"]), "model": ""}
    return saved


def _static(name: str) -> bytes | None:
    if ".." in name or name.startswith(("/", "\\")):
        return None
    try:
        return resources.files("decompnet.app").joinpath("static", name).read_bytes()
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None


def build(net: RomNetwork, home: Path, port: int, secret: str):
    mcp_url = f"http://127.0.0.1:{port}/mcp"
    build_id = (updates.installed().get("commit") or "")[:12]  # a branch install: the commit it came from
    manager = agents.Manager(net, home, mcp_url)
    jobs = Jobs(home / "logs" / "decomp.log")
    reviewed_layouts = {}  # short-lived reviewed metadata, consumed by one import
    settings = Settings(home / "settings.json")
    manager.budget = lambda: float(settings.data.get("budget_usd") or 0)

    def remember(running: list[dict]) -> None:
        settings.data["running_agents"] = running
        settings.save()
    manager.persist = remember
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def agent_of(ctx: Context):
        headers = ctx.headers or {}
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        agent = net.authenticate(auth.removeprefix("Bearer ").strip() or None)
        slug = manager.project_of(agent.id) or settings.data.get("last_project")
        if not slug:
            raise NetworkError("no project is open in decomp.wtf; open a ROM in the app first")
        if net.pc_projects.contains(slug):
            raise NetworkError('Native PC projects use inspect_pc_project; edit and build the exported folder with your own coding tools. Matching tools apply to console recovery.')
        return agent, slug

    # helpers that were working when the app last stopped carry on
    resume = [r for r in settings.data.get("running_agents", []) if isinstance(r, dict)]
    for r in resume:
        try:
            net.project_row(r["slug"])
            options = dict(r.get("options") or {})
            if r["kind"] == "api":
                saved = settings.endpoint(str(options.get("endpoint") or "")) if options.get("endpoint") else (
                    next((e for e in settings.endpoints() if e["base_url"] == options.get("base_url")), None))
                if saved is None and options.get("endpoint"):
                    continue  # its endpoint was removed since
                if saved is not None:  # as the endpoint is now, with its key
                    options.update(_session_options(saved))
            manager.start(r["kind"], r["slug"], 1, options)
        except (NetworkError, ValueError, KeyError):
            continue

    mcp = tools.build_mcp(net, agent_of)
    chat.register(mcp, net, manager, jobs, settings, port, secret)

    # Each agent sees the tools for its job: the agent you talk to sees everything; a helper only the work tools
    # for its project's kind (fewer tool definitions in every request, nothing it shouldn't call).
    from mcp_types import ListToolsResult, PaginatedRequestParams

    async def scoped_tools(ctx, params):
        everything = await mcp.list_tools()
        auth = (getattr(ctx.request, "headers", None) or {}).get("authorization", "")
        try:
            agent = net.authenticate(auth.removeprefix("Bearer ").strip() or None)
        except NetworkError:
            return ListToolsResult(tools=everything)
        if net.is_chat(agent):
            return ListToolsResult(tools=everything)
        slug = manager.project_of(agent.id) or settings.data.get("last_project")
        keep = set(tools.tool_names(bool(slug and net.fork_slug(slug))))
        return ListToolsResult(tools=[t for t in everything if t.name in keep])

    mcp._lowlevel_server.add_request_handler("tools/list", PaginatedRequestParams, scoped_tools)

    def guard(request: Request, write: bool = False) -> Response | None:
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"error": "bad host"}, status_code=403)
        if not secrets.compare_digest(request.cookies.get(COOKIE, ""), secret):
            return JSONResponse({"error": "open decomp.wtf from the app or the `decomp` command"}, status_code=401)
        if write and request.headers.get("x-decomp") != "1":
            return JSONResponse({"error": "missing header"}, status_code=403)
        return None

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    async def call(fn, *args):
        return await anyio.to_thread.run_sync(fn, *args)

    def fail(e: Exception, code: int = 400) -> JSONResponse:
        return JSONResponse({"error": str(e)}, status_code=code)

    # ------------------------------------------------------------------ pages

    @mcp.custom_route("/", methods=["GET"])
    async def index(request: Request) -> Response:
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"error": "bad host"}, status_code=403)
        key = request.query_params.get("k")
        if key:
            if not secrets.compare_digest(key, secret):
                return HTMLResponse("This link is from an earlier session. Open decomp.wtf again.", status_code=401)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(COOKIE, secret, httponly=True, samesite="strict", max_age=30 * 86400)
            return resp
        if not secrets.compare_digest(request.cookies.get(COOKIE, ""), secret):
            return HTMLResponse("<!doctype html><meta charset=utf-8><title>decomp.wtf</title>"
                                "<body style='font:16px system-ui;background:#0b0c0e;color:#e8e6e1;padding:3rem'>"
                                "Open decomp.wtf from its app icon or by running <code>decomp</code>.", status_code=401)
        return HTMLResponse(_static("index.html").decode(), headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/assets/{name:path}", methods=["GET"])
    async def asset(request: Request) -> Response:
        if request.headers.get("host") not in allowed_hosts:
            return Response(status_code=403)
        name = request.path_params["name"]
        data = _static(name)
        if data is None:
            return Response(status_code=404)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return Response(data, media_type=ctype, headers={"Cache-Control": "no-cache"})

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "app": "decomp-wtf", "version": __version__, "build": build_id})

    # ------------------------------------------------------------------ state

    def overviews() -> list[tuple[str, dict | None, str]]:
        """(slug, overview or None, why not) for every project. One that can't be read is still listed, with the
        reason: before, one odd project emptied the whole sidebar, or quietly went missing from it."""
        out = []
        for p in net.store.all("SELECT slug, name, config FROM projects ORDER BY id DESC"):
            from .. import platforms
            if not platforms.enabled(json.loads(p["config"]).get("platform", "")):
                continue
            try:
                out.append((p["slug"], net.overview(p["slug"]), ""))
            except Exception as e:  # noqa: BLE001
                jobs.logger.warning("project %s can't be read: %s", p["slug"], e, exc_info=not isinstance(e, NetworkError))
                out.append((p["slug"], {"slug": p["slug"], "title": p["name"] or p["slug"]}, job_error(e, jobs.log_path)))
        return out

    def state() -> dict:
        projects = [ov | ({"broken": why} if why else {}) for _, ov, why in overviews()]
        tcs = [t for t in toolchains.status() if t["id"] in COMPILERS or t["id"] in TOOLS]
        for t in tcs:
            t["use"] = COMPILERS.get(t["id"]) or TOOLS[t["id"]]
            t["name"] = SHORT_NAMES.get(t["id"], t["name"])
        return {"version": __version__, "build": build_id, "install": updates.installed(), **hostenv.info(),
                "platform": toolchains.current_platform(), "home": hostenv.shown_path(home.parent),
                "log_file": hostenv.shown_path(home / "logs" / "decomp.log"),
                "projects": net.pc_projects.list() + projects, "toolchains": tcs, "agents": agents.detect(),
                "api_presets": agents.API_PRESETS, "settings": settings.public(), "mcp_url": mcp_url,
                "platform_status": PLATFORM_STATUS,
                "pc_output": {p: __import__("decompnet.pc", fromlist=["status"]).status(p) for p in PLATFORM_STATUS},
                "codewarrior": {"installed": False,
                                "ds_installed": toolchains.installed("mwccarm") is not None, **MW_VERSIONS}}

    def autopilot(slug: str) -> None:
        """Free matches first, in the background, when the user wants that (the default): a game started from
        scratch, on any platform, as soon as it's ready. A project not set up for recovery says no."""
        if settings.data.get("autopilot", True):
            try:
                net.start_autopilot(slug)
            except NetworkError:
                pass

    def project_list() -> list[dict]:
        """The sidebar: every project with its progress and how many helper agents work on it right now."""
        running: dict[str, int] = {}
        for s in manager.sessions.values():
            if s.state in ("starting", "working", "waiting"):
                running[s.slug] = running.get(s.slug, 0) + 1
        out = []
        for slug, ov, why in overviews():
            out.append({k: ov.get(k) for k in ("slug", "title", "kind", "origin", "platform", "platform_name", "ready",
                                                "functions", "matched", "bytes", "matched_bytes", "last_activity", "progress_kind")}
                       | {"working": running.get(slug, 0),
                          "autopilot": (ov.get("autopilot") or {}).get("state")} | ({"broken": why} if why else {}))
        return net.pc_projects.list() + out

    @mcp.custom_route("/api/projects", methods=["GET"])
    async def api_projects(request: Request) -> Response:
        return guard(request) or JSONResponse(await call(project_list))

    @mcp.custom_route("/api/state", methods=["GET"])
    async def api_state(request: Request) -> Response:
        return guard(request) or JSONResponse(await call(state))

    @mcp.custom_route("/api/rom/layout", methods=["POST"])
    async def api_rom_layout(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        layout = data.get("layout")
        if not isinstance(layout, dict) or len(json.dumps(layout)) > 1024 * 1024:
            return fail(ValueError("choose a reviewed PS1 layout JSON file smaller than 1 MiB"))
        now = time.monotonic()
        for key, (created, _) in list(reviewed_layouts.items()):
            if now - created > 900:
                del reviewed_layouts[key]
        if len(reviewed_layouts) >= 32:
            del reviewed_layouts[next(iter(reviewed_layouts))]
        token = uuid.uuid4().hex
        reviewed_layouts[token] = (now, layout)
        return JSONResponse({"id": token})

    @mcp.custom_route("/api/import", methods=["POST"])
    async def api_import(request: Request) -> Response:
        """A game the user owns: the demo, an upload streamed to disk (discs are gigabytes), or a local path."""
        if (bad := guard(request, write=True)):
            return bad
        q = request.query_params
        toolchain = q.get("toolchain") or None
        layout = None
        layout_token = q.get("reviewed_layout")
        if layout_token:
            pending = reviewed_layouts.pop(layout_token, None)
            if pending is None or time.monotonic() - pending[0] > 900:
                return fail(ValueError("the reviewed layout expired; select it again"))
            layout = pending[1]
        if q.get("demo") == "1":
            return fail(ValueError("The N64 demo was removed. Use the preserved main branch in PR #27."))
        else:
            if q.get("confirmed") != "1":
                return fail(ValueError("confirm that this is your own legally obtained copy of the game"))
            if q.get("path"):
                try:
                    game = hostenv.local_path(q["path"])
                except ValueError as e:
                    return fail(e)
                if not game.is_file():
                    return fail(ValueError(f"no file at {game}"))
                name = game.name
            else:
                name = Path(q.get("name") or "game.bin").name
                upload_dir = home / "uploads" / uuid.uuid4().hex[:8]  # keeps the file's own name
                upload_dir.mkdir(parents=True, exist_ok=True)
                game = upload_dir / name
                size = 0
                with open(game, "wb") as f:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_DISC:
                            f.close()
                            game.unlink(missing_ok=True)
                            return fail(ValueError("that file is larger than any game disc"))
                        f.write(chunk)
                if size == 0:
                    game.unlink(missing_ok=True)
                    return fail(ValueError("the file was empty"))
        uploaded = isinstance(game, Path) and game.parent.parent == home / "uploads"

        def work(log):
            try:
                if q.get('output') == 'pc':
                    if layout is not None or toolchain:
                        raise NetworkError('Native PC output does not use a matching console compiler or reconstruction layout')
                    from .. import pc
                    target=q.get('pc_platform') or pc.input_platform(game)
                    if target=='3ds':
                        return net.generate_ctr_pc(game,confirmed=True,renderer=q.get('renderer','auto'),
                            log=log)
                    if target=='gba':
                        return net.generate_gba_pc(game,confirmed=True,save_type=q.get('save_type','auto'),renderer=q.get('renderer','auto'),log=log)
                    if target=='ps2':
                        profile=hostenv.local_path(q['ps2_profile']) if q.get('ps2_profile') else None
                        return net.generate_ps2_pc(game,confirmed=True,profile=profile,renderer=q.get('renderer','auto'),log=log)
                    if target=='psx':
                        try:extra=json.loads(q.get('discs','[]'))
                        except (TypeError,ValueError):raise NetworkError('additional discs must be an ordered list of paths')
                        if not isinstance(extra,list) or len(extra)>15 or any(not isinstance(path,str) for path in extra):
                            raise NetworkError('provide up to fifteen additional disc paths in order')
                        paths=[game,*[hostenv.local_path(path) for path in extra]]
                        return net.generate_psx_pc(paths,confirmed=True,renderer=q.get('renderer','auto'),log=log)
                    if target!='nds':raise NetworkError('native PC generation is available for DS, PS1, PS2, GBA and 3DS projects')
                    return net.generate_ds_pc(game,confirmed=True,input_format=q.get('ds_input_format','auto'),
                                              save_type=q.get('save_type','auto'),renderer=q.get('renderer','auto'),
                                              log=log)
                if q.get('output','matching') != 'matching':
                    raise NetworkError('choose matching console reconstruction or pc output')
                slug = net.import_rom(game, toolchain=toolchain, confirmed=True, name=name,
                                      ds_input_format=q.get("ds_input_format", "auto"), reviewed_layout=layout, log=log)
            finally:
                if uploaded:
                    shutil.rmtree(game.parent, ignore_errors=True)
            settings.data["last_project"] = slug
            settings.save()
            autopilot(slug)
            return {"slug": slug}
        return JSONResponse({"job": jobs.start("import", work)})

    MAP_KEYS = ("name", "vram", "size", "insns", "unit", "status", "best", "attempts", "agent", "matched_at", "matched_by")

    @mcp.custom_route("/api/map", methods=["GET"])
    async def api_map(request: Request) -> Response:
        """Every function, for the map and the table. `since`: the signature the GUI has; when nothing changed, the
        answer is just that (a big game's map is megabytes, and the GUI asks every few seconds). Rows go as arrays
        under `keys`, gzipped when the browser takes it."""
        if (bad := guard(request)):
            return bad
        slug = request.query_params.get("slug", "")

        def build() -> dict:
            sig = net.map_signature(slug)
            if request.query_params.get("since") == sig:
                return {"sig": sig, "same": True}
            rows = net.function_map(slug)
            return {"sig": sig, "keys": MAP_KEYS, "rows": [[r.get(k) for k in MAP_KEYS] for r in rows]}
        try:
            data = await call(build)
        except (NetworkError, ValueError) as e:
            return fail(e)
        raw = json.dumps(data, separators=(",", ":")).encode()
        if len(raw) > 4096 and "gzip" in request.headers.get("accept-encoding", ""):
            import gzip
            return Response(gzip.compress(raw, 1), media_type="application/json",
                            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        return Response(raw, media_type="application/json")

    @mcp.custom_route("/api/log", methods=["GET"])
    async def api_log(request: Request) -> Response:
        """The end of decomp.wtf's log, to read or attach to a bug report (the app's data folder isn't always at
        hand: in Docker it's inside the container)."""
        if (bad := guard(request)):
            return bad
        path = home / "logs" / "decomp.log"
        try:
            with open(path, "rb") as f:
                f.seek(max(0, path.stat().st_size - (512 << 10)))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            text = "(nothing logged yet)"
        return Response(text, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": 'inline; filename="decomp.log"'})

    @mcp.custom_route("/api/job", methods=["GET"])
    async def api_job(request: Request) -> Response:
        if (bad := guard(request)):
            return bad
        job = jobs.jobs.get(request.query_params.get("id", ""))
        return JSONResponse(job) if job else fail(ValueError("no such job"), 404)

    # ------------------------------------------------------------------ projects

    @mcp.custom_route("/api/export/archive", methods=["GET"])
    async def export_archive(request: Request) -> Response:
        if bad := guard(request):
            return bad
        try:
            proj = net.project_row(request.query_params.get("slug", ""))
            cfg = net.cfg(proj)
            from ..rom.psx_set import members
            rows = members(net, cfg.get("psx_disc_set") or {})
            expected = Path(rows[0][0]["root"]) / "source-set.zip"
            saved = cfg.get("export") or {}
            if not saved.get("identical") or saved.get("disc_set_id") != cfg["psx_disc_set"]["id"] or \
                    saved.get("archive") != str(expected) or not expected.is_file() or expected.is_symlink():
                return fail(ValueError("export and verify this combined game before downloading its ZIP"), 404)
            return FileResponse(expected, media_type="application/zip", filename="ps1-source-project.zip")
        except (NetworkError, ValueError, KeyError, OSError) as error:
            return fail(error)

    def with_project(fn):
        async def handler(request: Request) -> Response:
            if (bad := guard(request, write=request.method == "POST")):
                return bad
            data = await body(request) if request.method == "POST" else {}
            slug = data.get("slug") or request.query_params.get("slug", "")
            try:
                return JSONResponse(await call(lambda: fn(slug, request, data)))
            except (NetworkError, ValueError, toolchains.ToolchainError, OSError) as e:
                return fail(e)
        return handler

    def p_overview(slug, request, data):
        settings.data["last_project"] = slug
        settings.save()
        return net.overview(slug)

    def p_live(slug, request, data):
        q = request.query_params
        out = net.live(slug, int(q.get("e", 0) or 0), int(q.get("a", 0) or 0))
        try:
            since = json.loads(q.get("s") or "{}")
        except ValueError:
            since = {}
        out["sessions"] = [s for s in manager.snapshot(since) if s["slug"] == slug]
        return out

    def p_compiler(slug, request, data):
        if data.get("function"):
            net.set_function_compiler(slug, str(data["function"]), data.get("profile"))
        else:
            net.set_compiler(slug, str(data.get("toolchain", "")), data.get("flags") or None)
        return net.overview(slug)

    def p_export(slug, request, data):
        def work(log):
            res = net.export_rom(slug, format=str(data.get("format", "matching")),
                                 save_type=str(data.get('save_type','auto')),renderer=str(data.get('renderer','auto')),
                                 ps2_profile=hostenv.local_path(str(data['ps2_profile'])) if data.get('ps2_profile') else None,log=log)
            if res.get('format') == 'pc':
                res['project'] = net.pc_projects.remember(Path(res['path']),res['manifest'],verified=res.get('integrity_verified',False))
            return {k: v for k, v in res.items() if k != "log"} | {"log": res.get("log", "")[-1500:]}
        return {"job": jobs.start("export", work)}

    def p_open(slug, request, data):
        why = hostenv.open_folder(Path(net.project_row(slug)["root"]))
        return {"ok": why is None, "message": why}

    def p_delete(slug, request, data):
        manager.stop()
        proj = net.project_row(slug)
        net.remove_project(slug)
        if data.get("files"):
            shutil.rmtree(proj["root"], ignore_errors=True)
        if settings.data.get("last_project") == slug:
            settings.data["last_project"] = None
            settings.save()
        return {"ok": True}

    def p_manual(slug, request, data):
        name = f"manual-{secrets.token_hex(2)}"
        agent, token = net.local_agent(name)
        manager.assignments[agent.id] = slug
        return {"agent": name, "url": mcp_url, "token": token,
                "claude": f'claude mcp add --transport http decomp {mcp_url} --header "Authorization: Bearer {token}"',
                "json": json.dumps({"mcpServers": {"decomp": {"type": "http", "url": mcp_url,
                                                              "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2)}

    def p_try(slug, request, data):
        """You, editing a function in the GUI: judged like an agent's attempt (and credited to "you")."""
        agent, _ = net.local_agent("you")
        res = net.attempt(agent, str(data.get("name", "")), str(data.get("source", "")), slug)
        return {"score": res["score"], "matched": res["matched"], "text": res["text"][-4000:]}

    def p_release(slug, request, data):
        agent, _ = net.local_agent("you")
        try:
            net.release(agent, str(data.get("name", "")), "", slug)
        except NetworkError:
            pass  # not yours (any more): nothing to give back
        return {"ok": True}

    def p_instructions(slug, request, data):
        net.set_instructions(slug, str(data.get("text", "")))
        return net.overview(slug)

    def p_priority(slug, request, data):
        return {"priority": net.set_priority(slug, str(data.get("name", "")), bool(data.get("on", True)))}

    def p_note(slug, request, data):
        """A note from you on a function (or the whole project): agents read notes when they claim it."""
        agent, _ = net.local_agent("you")
        text = str(data.get("text", "")).strip()
        if not text:
            raise ValueError("write the note first")
        return {"message": net.add_note(agent, slug, text[:2000], str(data.get("function", "")) or None)}

    def p_autopilot(slug, request, data):
        if data.get("action") == "stop":
            net.stop_autopilot(slug)
        else:
            net.start_autopilot(slug)
        return net.overview(slug)

    routes = {
        "/api/project": (p_overview, ["GET"]),
        "/api/live": (p_live, ["GET"]),
        "/api/function": (lambda s, r, d: net.function_detail(s, r.query_params.get("name", "")), ["GET"]),
        "/api/diff": (lambda s, r, d: net.function_diff(s, r.query_params.get("name", ""),
                                                        r.query_params.get("which", "latest")), ["GET"]),
        "/api/compiler": (p_compiler, ["POST"]), "/api/export": (p_export, ["POST"]), "/api/open": (p_open, ["POST"]),
        "/api/psx/disc-set": (lambda s, r, d: net.set_psx_disc_set(s, d.get("projects"), d.get("title", "")), ["POST"]),
        "/api/delete": (p_delete, ["POST"]), "/api/agents/manual": (p_manual, ["POST"]),
        "/api/try": (p_try, ["POST"]), "/api/release": (p_release, ["POST"]),
        "/api/autopilot": (p_autopilot, ["POST"]), "/api/instructions": (p_instructions, ["POST"]),
        "/api/priority": (p_priority, ["POST"]), "/api/note": (p_note, ["POST"]),
        "/api/stats": (lambda s, r, d: net.stats(s), ["GET"]),
    }
    for path, (fn, methods) in routes.items():
        mcp.custom_route(path, methods=methods)(with_project(fn))

    # ------------------------------------------------------------------ local native PC projects

    mcp.custom_route('/api/recovery/check', methods=['POST'])(with_project(
        lambda slug, request, data: {'job': jobs.start('recovery-check',lambda log: net.forks.check(slug,log=log))}))
    mcp.custom_route('/api/recovery/rom-check', methods=['POST'])(with_project(
        lambda slug, request, data: {'job': jobs.start('rom-check',lambda log: net.forks.check_rom(slug,log=log))}))

    @mcp.custom_route('/api/pc-project/add', methods=['POST'])
    async def api_pc_project_add(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        try:
            root = hostenv.local_path(str(data.get('path') or ''))
            if not str(data.get('path') or '').strip():
                raise ValueError('choose the folder containing pc-project.json')
        except ValueError as error:
            return fail(error)
        return JSONResponse({'job': jobs.start('pc-project-add', lambda log: net.pc_projects.add(root))})

    @mcp.custom_route('/api/pc-project', methods=['GET', 'POST'])
    async def api_pc_project(request: Request) -> Response:
        if (bad := guard(request, write=request.method == 'POST')):
            return bad
        data = await body(request) if request.method == 'POST' else request.query_params
        key = str(data.get('id') or '')
        try:
            project = net.pc_projects.get(key)
            if request.method == 'GET':
                settings.data['last_project'] = key
                settings.save()
                return JSONResponse(project | {'readme': net.pc_projects.readme(key)})
            action = data.get('action')
            if action == 'verify':
                return JSONResponse({'job': jobs.start('pc-project-verify', lambda log: net.pc_projects.verify(key))})
            if action == 'open':
                why = hostenv.open_folder(Path(project['path']))
                return JSONResponse({'ok': why is None, 'message': why})
            if action == 'forget':
                net.pc_projects.forget(key)
                if settings.data.get('last_project') == key:
                    settings.data.pop('last_project',None)
                    settings.save()
                return JSONResponse({'ok': True})
            raise ValueError('choose open, verify or forget')
        except (ValueError, OSError) as error:
            return fail(error)

    # ------------------------------------------------------------------ installs, agents, settings

    @mcp.custom_route("/api/toolchain", methods=["POST"])
    async def api_toolchain(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        tid, accept = str(data.get("id", "")), bool(data.get("accept_license"))
        return JSONResponse({"job": jobs.start("toolchain", lambda log: (toolchains.install(tid, accept_license=accept, log=log)
                                                                         and {"id": tid}))})

    @mcp.custom_route("/api/agents/install", methods=["POST"])
    async def api_agent_install(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        kind = agents.KINDS.get(agents.kind_id(str((await body(request)).get("kind", ""))))
        if kind is None or not kind.install:
            return fail(ValueError("nothing to install"))
        cmd = kind.install["windows" if sys.platform == "win32" else "unix"]
        env = None
        if sys.platform == "win32":
            env = dict(os.environ, PATH=agents.search_path())  # Node.js installed since the app started counts
            if cmd.startswith("npm ") and not shutil.which("npm", path=env["PATH"]):
                return fail(ValueError(f"{kind.name} is installed with npm: install Node.js from https://nodejs.org "
                                       "first (the LTS version), then try again"))

        def work(log):
            log(f"$ {cmd}")
            if sys.platform == "win32":
                # Node.js's npm is a PowerShell script (npm.ps1) that Windows' default execution policy won't run;
                # output as UTF-8 so it reads right here; never wait at a prompt nobody sees
                argv = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                        f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; {cmd}"]
            else:
                argv = ["bash", "-lc", cmd]
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", env=env)
            for line in proc.stdout:
                log(line.rstrip())
            if proc.wait() != 0:
                raise RuntimeError(f"the installer exited with code {proc.returncode}")
            agents._versions.pop(kind.id, None)
            return {"kind": kind.id}
        return JSONResponse({"job": jobs.start("agent-install", work)})

    @mcp.custom_route("/api/agents/start", methods=["POST"])
    async def api_agents_start(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        kind, slug = str(data.get("kind", "")), str(data.get("slug", ""))
        given = data.get("options") or {}
        options = {k: v for k, v in given.items() if k in ("model", "per_session")}
        options.setdefault("per_session", settings.data.get("per_session", agents.PER_SESSION))
        count = max(1, min(int(data.get("count", 1)), 8))
        picked: list[str] = []
        try:
            net.project_row(slug)
            if kind == "api":
                picked = [str(e) for e in (given.get("endpoints") or ([given["endpoint"]] if given.get("endpoint") else []))]
                plan = _spread(settings, manager, picked, count, given)
                ids = [sid for entry, n in plan for sid in manager.start(kind, slug, n, options | _session_options(entry))]
            else:
                ids = manager.start(kind, slug, count, options)
        except (NetworkError, ValueError) as e:
            return fail(e)
        # remembered, so the next start is one click; models typed in come back as suggestions
        model = str(options.get("model") or "")
        settings.data["launcher"] = {"kind": kind, "model": model, "count": count} | ({"endpoints": picked} if picked else {})
        if model and kind != "api":
            recent = settings.data.setdefault("recent_models", {}).setdefault(kind, [])
            settings.data["recent_models"][kind] = [model] + [m for m in recent if m != model][:7]
        settings.save()
        return JSONResponse({"started": ids})

    @mcp.custom_route("/api/connect", methods=["GET", "POST"])
    async def api_connect(request: Request) -> Response:
        """Your agents (Claude Code, Codex, ...) with decomp.wtf's tools: whether they have them, and adding them."""
        if (bad := guard(request, write=request.method == "POST")):
            return bad
        if request.method == "POST":
            kind = str((await body(request)).get("id", ""))
            try:
                msg = await anyio.to_thread.run_sync(lambda: connect.connect(kind))
            except (ValueError, OSError, subprocess.TimeoutExpired) as e:
                return fail(e)
            return JSONResponse({"ok": True, "message": msg})

        def rows():
            from concurrent.futures import ThreadPoolExecutor

            found = [a for a in agents.detect() if a["id"] in connect.LABEL]
            with ThreadPoolExecutor(len(found) or 1) as pool:  # each agent's own CLI answers; ask them all at once
                linked = list(pool.map(lambda a: a["installed"] and connect.status(a["id"]), found))
            return [{"id": a["id"], "name": a["name"], "installed": a["installed"], "connected": ok,
                     "command": connect.shown(a["id"])} for a, ok in zip(found, linked)]
        if (host := hostenv.host_bridge()) is not None:  # the user's agents live outside decomp.wtf's Linux
            return JSONResponse({"agents": [], "bridge": host, "host_bridge": host, **hostenv.info()})
        return JSONResponse({"agents": await anyio.to_thread.run_sync(rows), "bridge": connect.bridge_command(), "environment": connect.environment()})

    @mcp.custom_route("/api/agents/token", methods=["POST"])
    async def api_agents_token(request: Request) -> Response:
        """An identity for an agent the user talks to, connecting through `decomp mcp`."""
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        try:
            agent, token = net.chat_agent(str(data.get("name") or "chat"))
        except NetworkError as e:
            return fail(e)
        return JSONResponse({"agent": agent.name, "token": token, "url": mcp_url})

    @mcp.custom_route("/api/agents/stop", methods=["POST"])
    async def api_agents_stop(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        if data.get("remove"):
            manager.remove(str(data.get("id")))
        elif data.get("slug"):  # every helper on one project
            for s in list(manager.sessions.values()):
                if s.slug == data["slug"] and s.state in ("starting", "working", "waiting"):
                    manager.stop(s.id)
        else:
            manager.stop(data.get("id") or None)
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/settings", methods=["POST"])
    async def api_settings(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad
        data = await body(request)
        if isinstance(data.get("api"), dict):  # (before 0.10.1: the one endpoint there was) the first one
            first = settings.endpoints()[0]["id"] if settings.endpoints() else ""
            settings.save_endpoint(data["api"] | {"id": first})
        if isinstance(data.get("endpoint"), dict):
            settings.save_endpoint(data["endpoint"])
        if data.get("remove_endpoint"):
            settings.remove_endpoint(str(data["remove_endpoint"]))
            for sid, sess in list(manager.sessions.items()):  # its sessions stop with it
                if sess.kind == "api" and sess.options.get("endpoint") == str(data["remove_endpoint"]):
                    manager.stop(sid)
        if "per_session" in data:
            settings.data["per_session"] = max(1, min(int(data["per_session"]), 20))
        if "autopilot" in data:
            settings.data["autopilot"] = bool(data["autopilot"])
        if "budget_usd" in data:
            settings.data["budget_usd"] = max(0.0, float(data["budget_usd"] or 0))
        if "auto_update" in data:
            settings.data["auto_update"] = bool(data["auto_update"])
        if "check_updates" in data:
            settings.data["check_updates"] = bool(data["check_updates"])
        settings.save()
        return JSONResponse(settings.public())

    # ------------------------------------------------------------------ updates (updates.py)

    @mcp.custom_route("/api/update", methods=["GET", "POST"])
    async def api_update(request: Request) -> Response:
        """Whether a newer decomp.wtf is out (checked now and then; ?refresh=1 now) and, POSTed, installing it."""
        if (bad := guard(request, write=request.method == "POST")):
            return bad
        if request.method == "POST":
            try:
                await call(updater.apply)
            except ValueError as e:
                return fail(e)
        refresh = request.query_params.get("refresh") == "1"
        if not refresh and not checking():  # the user turned checks off: only "Check now" asks
            return JSONResponse({"disabled": True, "available": False, "current": updates.installed(),
                                 "job": updater.job, "runtime": hostenv.runtime()})
        return JSONResponse(await call(lambda: updater.status(refresh)))

    def checking() -> bool:
        return settings.data.get("check_updates", True) is not False and os.environ.get("DECOMP_UPDATES") != "off"

    def watch_updates() -> None:
        """Check now and then; with "install updates automatically" on, install one while no helper is working."""
        time.sleep(20)
        while True:
            if not checking():
                time.sleep(300)
                continue
            try:
                st = updater.status()
                busy = any(s.state in ("starting", "working") for s in manager.sessions.values())
                if st.get("available") and st.get("can_apply") and settings.data.get("auto_update") and not busy:
                    updater.apply()
            except (ValueError, OSError):
                pass
            time.sleep(300)

    @mcp.custom_route("/api/quit", methods=["POST"])
    async def api_quit(request: Request) -> Response:
        if (bad := guard(request, write=True)):
            return bad

        def bye():
            manager.stop()
            manager.on_stop()
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=bye, daemon=True).start()
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/service", methods=["GET", "POST"])
    async def api_service(request: Request) -> Response:
        """Run decomp.wtf as a service that starts with the computer."""
        from . import service

        if (bad := guard(request, write=request.method == "POST")):
            return bad
        if request.method == "POST":
            action = str((await body(request)).get("action", ""))
            try:
                msg = await anyio.to_thread.run_sync(service.install if action == "install" else service.remove)
            except (RuntimeError, OSError) as e:
                return fail(e)
            return JSONResponse({"message": msg, "installed": service.installed()})
        return JSONResponse({"installed": await anyio.to_thread.run_sync(service.installed)})



    def before_restart() -> None:  # what quitting does: helpers stop now and resume in the new version
        manager.stop()
        manager.on_stop()
    updater = updates.Updater(before_restart, port, secret)
    threading.Thread(target=watch_updates, daemon=True, name="updates").start()

    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=sorted(allowed_hosts),
                                         allowed_origins=[f"http://{h}" for h in sorted(allowed_hosts)])
    return mcp, manager, security
