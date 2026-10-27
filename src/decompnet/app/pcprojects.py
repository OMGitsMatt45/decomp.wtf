"""Local catalog of generated PC projects, separate from console matching progress."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .. import pc, platforms


class PCProjects:
    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pc_projects (id TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL, "
                       "metadata TEXT NOT NULL, created REAL NOT NULL, checked REAL, verification TEXT)")

    def remember(self, root: Path, manifest: dict, *, verified=False) -> dict:
        root = Path(root).resolve()
        if manifest.get('schema') not in (pc.SCHEMA, pc.LEGACY_SCHEMA) or manifest.get('platform') not in platforms.NAMES:
            raise pc.PCError('choose a generated native PC project with a supported pc-project.json')
        if not isinstance(manifest.get('build'),dict) or not isinstance(manifest['build'].get('target'),str):
            raise pc.PCError('PC project must declare its build target')
        key = 'pc-' + hashlib.sha256(str(root).encode()).hexdigest()[:20]
        metadata = dict(id=key, slug=key, kind='pc', title=manifest.get('title') or root.name,
                        platform=manifest['platform'], platform_name=platforms.NAMES[manifest['platform']],
                        path=str(root), ready=True, output_kind=manifest.get('output_kind','game'), execution_model=manifest.get('execution_model'),
                        presentation=manifest.get('presentation', {}), build=manifest.get('build', {}))
        now = time.time()
        with self.store.tx() as db:
            db.execute("INSERT INTO pc_projects(id,root,metadata,created,checked,verification) VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata,checked=excluded.checked,"
                       "verification=excluded.verification", (key,str(root),json.dumps(metadata),now,
                       now if verified else None,json.dumps(dict(passed=True)) if verified else None))
        return self.get(key)

    def add(self, root: Path) -> dict:
        root = Path(root).resolve()
        source = root/'pc-project.json'
        if source.is_symlink() or source.stat().st_size > 16 * 1024 * 1024:
            raise pc.PCError('choose a local PC-project manifest smaller than 16 MiB')
        manifest = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(manifest,dict):
            raise pc.PCError('PC-project manifest must be an object')
        project = self.remember(root, manifest)
        return self.verify(project['id'])

    def list(self) -> list[dict]:
        return [self._row(row) for row in self.store.all('SELECT * FROM pc_projects ORDER BY created DESC')]

    @staticmethod
    def _row(row) -> dict:
        data = json.loads(row['metadata'])
        data.update(created=row['created'], checked=row['checked'],
                    verification=json.loads(row['verification']) if row['verification'] else None,
                    missing=not (Path(row['root'])/'pc-project.json').is_file())
        return data

    def get(self, key: str) -> dict:
        row = self.store.one('SELECT * FROM pc_projects WHERE id=?', key)
        if row is None:
            raise pc.PCError('no tracked PC project with that ID; add its folder first')
        return self._row(row)

    def contains(self, key: str) -> bool:
        return self.store.one('SELECT id FROM pc_projects WHERE id=?',key) is not None

    def readme(self, key: str) -> str:
        root = Path(self.get(key)['path'])
        for name in ('README.md','README.txt'):
            path = root/name
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
                with path.open(encoding='utf-8',errors='replace') as stream:
                    return stream.read(128 * 1024)
        return 'The project README is missing. Restore it from your original export.'

    def verify(self, key: str) -> dict:
        project = self.get(key)
        try:
            pc.verify(Path(project['path']))
            result = dict(passed=True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = dict(passed=False, error=str(error))
        with self.store.tx() as db:
            db.execute('UPDATE pc_projects SET checked=?,verification=? WHERE id=?',
                       (time.time(),json.dumps(result),key))
        return self.get(key)

    def forget(self, key: str) -> None:
        self.get(key)
        with self.store.tx() as db:
            db.execute('DELETE FROM pc_projects WHERE id=?',(key,))
