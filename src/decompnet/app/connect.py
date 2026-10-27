"""Make decomp.wtf available inside the AI agents the user already uses: register `decomp mcp` with Claude Code,
Codex, Antigravity CLI and opencode (their own `mcp add` commands; opencode's config file). After that, asking the
agent to generate a native PC project: it finds decomp.wtf's tools and the app shows its work.
Only done when the user clicks Connect (or runs `decomp connect`)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from .agents import KINDS, _which, argv, kind_id

NAME = "decomp"
LABEL = {"claude": "claude-code", "codex": "codex", "antigravity": "antigravity", "opencode": "opencode"}


def bridge_command() -> list[str]:
    """Use this installation's interpreter, rather than an unrelated decomp on PATH."""
    return [sys.executable, "-m", "decompnet.app.cli", "mcp"]


def environment(name: str = 'chat') -> dict[str, str]:
    from .cli import home_dir
    return {'DECOMP_AGENT_NAME': name, 'DECOMP_HOME': str(home_dir().resolve())}


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run an agent's own CLI (on Windows an npm .cmd through node, see agents.argv), reading its output as UTF-8."""
    return subprocess.run(argv(cmd), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _opencode_config() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    directory = base / 'opencode'
    plain = directory / 'opencode.json'
    commented = directory / 'opencode.jsonc'
    return commented if not plain.exists() and commented.exists() else plain


def commands(kind: str) -> list[str] | None:
    """The command that registers decomp.wtf with this agent (None: done through a config file)."""
    exe = _which(KINDS[kind].command) or KINDS[kind].command
    env = [f'{key}={value}' for key,value in environment(LABEL[kind]).items()]
    bridge = bridge_command()
    if kind == "claude":
        return [exe, "mcp", "add", "-s", "user", NAME, *[part for item in env for part in ('-e',item)], "--", *bridge]
    if kind == "codex":
        return [exe, "mcp", "add", *[part for item in env for part in ('--env',item)], NAME, "--", *bridge]
    if kind == "antigravity":  # flags before the name; `--` because the bridge may be `python -m ...`
        return [exe, "mcp", "add", *[part for item in env for part in ('-e',item)], NAME, "--", *bridge]
    return None


def shown(kind: str) -> str:
    """The same, as text a user could run themselves."""
    cmd = commands(kind)
    if cmd is None:
        entry = {"type": "local", "command": bridge_command(), "enabled": True, "environment": environment(LABEL[kind])}
        return "add " + json.dumps({"mcp": {NAME: entry}}) + " to " + str(_opencode_config())
    if sys.platform == 'win32':
        return '& ' + ' '.join("'"+arg.replace("'","''")+"'" for arg in cmd)
    return shlex.join(cmd)


def status(kind: str) -> bool:
    """Whether decomp.wtf is already registered with this agent."""
    exe = _which(KINDS[kind].command)
    if not exe:
        return False
    try:
        if kind == "claude":
            return _run([exe, "mcp", "get", NAME], 30).returncode == 0
        if kind == "codex":
            return _run([exe, "mcp", "get", NAME], 30).returncode == 0
        if kind == "antigravity":  # a table: NAME TYPE STATUS COMMAND/URL
            return any(line.split()[:1] == [NAME] for line in _run([exe, "mcp", "list"], 30).stdout.splitlines())
        if kind == "opencode":
            cfg = json.loads(_opencode_config().read_text(encoding="utf-8"))
            entry = cfg.get('mcp', {}).get(NAME) if isinstance(cfg,dict) and isinstance(cfg.get('mcp',{}),dict) else None
            return isinstance(entry,dict) and entry.get('enabled',True) and isinstance(entry.get('command'),list)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return False


def connect(kind: str) -> str:
    """Register decomp.wtf with the agent. Returns what happened, for the user."""
    kind = kind_id(kind)
    if kind not in LABEL:
        raise ValueError(f"unknown agent {kind!r}")
    if not _which(KINDS[kind].command):
        raise ValueError(f"{KINDS[kind].name} isn't installed")
    if kind == "opencode":
        path = _opencode_config()
        try:
            cfg = (json.loads(path.read_text(encoding="utf-8")) if path.exists()
                   else {"$schema": "https://opencode.ai/config.json"})
        except ValueError:
            raise ValueError(f"{path} isn't plain JSON (comments?); add this yourself: {shown(kind)}") from None
        if not isinstance(cfg,dict) or not isinstance(cfg.get('mcp',{}),dict):
            raise ValueError(f'{path} must contain a JSON object with an mcp object; existing configuration was kept')
        cfg.setdefault("mcp", {})[NAME] = {"type": "local", "command": bridge_command(), "enabled": True,
                                          "environment": environment(LABEL[kind])}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(cfg, indent=2) + '\n')
            os.replace(temporary,path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return f"added decomp.wtf to {path}"
    cmd = commands(kind)
    if kind != "antigravity" and status(kind):  # replace an older registration (agy's `mcp add` updates in place)
        _run([cmd[0], "mcp", "remove", *(["-s", "user"] if kind == "claude" else []), NAME], 30)
    res = _run(cmd, 60)
    if res.returncode != 0:
        raise ValueError(f"{KINDS[kind].name} said: {(res.stderr or res.stdout).strip()[-300:]}")
    return (res.stdout or res.stderr).strip()[-300:] or "connected"
