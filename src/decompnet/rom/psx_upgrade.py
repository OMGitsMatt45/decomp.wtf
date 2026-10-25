"""Refresh copied PS1 build helpers while retaining user source and backups."""

import hashlib
import json
from pathlib import Path
import tempfile

from .errors import RomError
from .psx_media import inside


def upgrade(directory):
    root = Path(directory).resolve()
    updates = []
    def copy(name, target):
        if target.is_symlink():
            raise RomError("copied PS1 build helpers must be regular project files")
        data = Path(__file__).with_name(name).read_bytes()
        if target.exists():
            old = target.read_bytes()
            if old == data:
                return
            backup = target.with_name(target.name + ".before-upgrade-" + hashlib.sha256(old).hexdigest()[:16])
            if backup.is_symlink():
                raise RomError("PS1 helper backups must be regular project files")
            if not backup.exists():
                backup.write_bytes(old)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(data)
                handle.close()
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        updates.append(str(target.relative_to(root)))
    projects = [root]
    if (root / "disc-set.json").exists():
        manifest = json.loads((root / "disc-set.json").read_text(encoding="utf-8"))
        if manifest.get("format") != 1 or not 2 <= len(manifest.get("discs", [])) <= 16:
            raise RomError("invalid combined PS1 project")
        projects = []
        for number, disc in enumerate(manifest["discs"], 1):
            if disc["project"] != f"discs/disc-{number}":
                raise RomError("combined PS1 projects must retain numbered disc paths")
            projects.append(inside(root, disc["project"]))
    # Preflight every child before changing any copied helper.
    for folder in projects:
        if json.loads((folder / "build.json").read_text(encoding="utf-8")).get("platform") != "psx":
            raise RomError("choose an exported PS1 source project")
    if projects != [root]:
        copy("psx_set_build.py", root / "build.py")
    for folder in projects:
        copy("psx_mod_build.py", folder / "psx_mod.py")
    return {"path": str(root), "updated": updates, "source_preserved": True,
            "backups": "Each replaced helper has a .before-upgrade-SHA256 backup."}
