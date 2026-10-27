"""Original PS1 fixture shared by local application and own-agent integration tests."""
from pathlib import Path
import subprocess
import sys

import pytest
from decompnet.app.engine import RomNetwork

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT/'projects/demo-psx'
ROM = DEMO/'build/DEMOQ_PS1.EXE'


@pytest.fixture(scope='module')
def built():
    if not ROM.exists():
        subprocess.run([sys.executable,str(DEMO/'build.py')],check=True)
    return ROM.read_bytes()


@pytest.fixture(autouse=True)
def fixture_compiler_runtime(monkeypatch):
    """Match the existing PS1 fixture harness, including local compatibility compilers."""
    original = RomNetwork._compile
    def compile_fixture(net, project, header, source, fn=None):
        cfg = net.cfg(project)
        cfg['compiler']['sandbox'] = 'none'
        import json
        # Standalone exports use the same fixture harness as in-app compiles.
        with net.store.tx() as db:
            db.execute('UPDATE projects SET config=? WHERE id=?',(json.dumps(cfg),project['id']))
        return original(net,{**dict(project),'config':json.dumps(cfg)},header,source,fn)
    monkeypatch.setattr(RomNetwork,'_compile',compile_fixture)
