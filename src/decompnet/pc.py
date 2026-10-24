"""Native PC-project adapter contract, separate from console byte matching.

Adapters generate real source projects and runtimes; matching exports are never
relabeled as PC output. Retail compatibility is qualified separately.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Callable

from . import platforms

SCHEMA = 'decomp.wtf.pc-project/v2'
LEGACY_SCHEMA = 'decomp.wtf.pc-project/v1'
PRESENTATION_SCHEMA = 'decomp.wtf.presentation/v1'
MODELS = ('native-source', 'static-recompiled', 'hybrid')


class PCError(ValueError):
    pass


@dataclass(frozen=True)
class Backend:
    id: str
    platform: str
    revision: str
    generate: Callable[[dict, Path], None]
    experimental: bool = False


# Each platform PR adds an adapter here only after an original fixture builds
# and executes through it. Retail/title qualification is reported separately.
BACKENDS: dict[str, Backend] | None = None


def _backends():
    # Resolve lazily: the DS adapter uses this contract and optional tools are
    # installed only when generating, never while checking app capabilities.
    if BACKENDS is not None:
        return list(BACKENDS.values())
    from .nds_native import backend
    return [backend()]


def status(platform: str = '') -> dict:
    platforms.require(platform, PCError)
    key = platforms.canonical(platform)
    available = [dict(id=b.id, platform=b.platform, revision=b.revision, experimental=b.experimental)
                 for b in _backends() if not key or b.platform == key]
    return dict(platform=key or None, first_platform='nds', available=bool(available), backends=available,
        experimental=bool(available) and all(b['experimental'] for b in available),
        console_reconstruction_is_pc_output=False,
        reason='' if available else 'No PC-project backend is installed for this platform. '
            'DS is the first implementation target; matching console exports remain separate.')


def _file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name:
        raise PCError('manifest paths must be relative POSIX file paths')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ('..', '.') for p in path.parts) or ':' in name:
        raise PCError('manifest paths must stay inside the PC project')
    file = root / name
    if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(root.resolve()):
        raise PCError('missing or external project file: '+name)
    return file


def presentation(renderer='auto', *, screens=1, screen_mode='single', gpu='opengl') -> dict:
    """Common display policy for generated game projects, across all consoles."""
    if gpu not in ('opengl', 'vulkan', 'direct3d'):
        raise PCError('presentation requires a supported GPU renderer')
    if renderer not in ('auto', gpu, 'software'):
        raise PCError('renderer must be auto, the GPU backend or software')
    if type(screens) is not int or screens not in (1, 2):
        raise PCError('presentation supports one or two console screens')
    if screen_mode not in (('single',) if screens == 1 else ('dual', 'unified')):
        raise PCError('screen mode must agree with the console screen count')
    return dict(schema=PRESENTATION_SCHEMA, renderer=renderer, renderers=[gpu, 'software'],
        gpu_rendering='geometry', resolution='drawable', initial_window='active-monitor',
        fullscreen='native-monitor', resizable=True, high_dpi=True,
        software_fallback='reported', screens=screens, screen_mode=screen_mode)


def _presentation(data: dict) -> bool:
    """Validate declared capabilities; execution reports provide runtime evidence."""
    if data['schema'] == LEGACY_SCHEMA:
        return False
    kind = data.get('output_kind', 'game')
    if kind == 'cpu-probe':
        qualification = data.get('qualification')
        if not isinstance(qualification, dict) or qualification.get('graphics') is not False or qualification.get('retail') is not False:
            raise PCError('a CPU probe must explicitly disclaim graphics and retail qualification')
        return False
    if kind != 'game':
        raise PCError('unsupported PC-project output kind')
    display = data.get('presentation')
    if not isinstance(display, dict) or display.get('schema') != PRESENTATION_SCHEMA:
        raise PCError('game output requires the shared GPU presentation contract')
    renderers = display.get('renderers')
    if not isinstance(renderers, list) or not all(isinstance(item, str) for item in renderers):
        raise PCError('presentation renderers must be a list of renderer names')
    if len(renderers) != len(set(renderers)) or 'software' not in renderers:
        raise PCError('presentation must declare GPU and software renderers')
    gpus = set(renderers) - {'software'}
    if not gpus or not gpus <= {'opengl', 'vulkan', 'direct3d'}:
        raise PCError('presentation must declare a supported GPU renderer')
    renderer = display.get('renderer')
    if not isinstance(renderer, str) or renderer not in ['auto', *renderers]:
        raise PCError('selected renderer is not supported by the project')
    required = dict(gpu_rendering='geometry', resolution='drawable',
        initial_window='active-monitor', fullscreen='native-monitor',
        resizable=True, high_dpi=True, software_fallback='reported')
    if any(type(display.get(key)) is not type(value) or display[key] != value
           for key, value in required.items()):
        raise PCError('presentation requires adaptive GPU rendering and reported software fallback')
    screens = 2 if data['platform'] in ('nds', '3ds') else 1
    if type(display.get('screens')) is not int or display['screens'] != screens:
        raise PCError('presentation screen count must agree with the console')
    modes = ('dual', 'unified') if screens == 2 else ('single',)
    if display.get('screen_mode') not in modes:
        raise PCError('presentation screen mode must agree with the console')
    return True


def verify(root: Path) -> dict:
    """Integrity/structure only. This does not claim host-build or gameplay success."""
    root = Path(root)
    data = json.loads(_file(root, 'pc-project.json').read_text())
    if not isinstance(data, dict):
        raise PCError('PC-project manifest must be an object')
    if data.get('schema') not in (SCHEMA, LEGACY_SCHEMA):
        raise PCError('unsupported PC-project manifest schema')
    platform = data.get('platform')
    platforms.require(platform, PCError)
    if platform not in platforms.NAMES:
        raise PCError('PC-project platform must identify a remaining console')
    backend = data.get('backend', {})
    if not isinstance(backend, dict) or not backend.get('id') or not backend.get('revision'):
        raise PCError('PC project must pin its backend identity and revision')
    if data.get('execution_model') not in MODELS:
        raise PCError('declare native-source, static-recompiled or hybrid execution')
    runtime = data.get('runtime', {})
    if not isinstance(runtime, dict) or not runtime.get('id') or not runtime.get('revision'):
        raise PCError('PC project must pin its console runtime')
    inputs = data.get('inputs')
    if not isinstance(inputs, list) or not inputs:
        raise PCError('PC project must identify its ordered original inputs')
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get('sha256'), str) or len(item['sha256']) != 64:
            raise PCError('each original input requires a SHA-256 identity')
        try:
            bytes.fromhex(item['sha256'])
        except ValueError as error:
            raise PCError('invalid input SHA-256') from error
    build = data.get('build', {})
    if not isinstance(build, dict) or build.get('system') != 'cmake' or not isinstance(build.get('target'), str) or not build['target']:
        raise PCError('PC project must declare a CMake executable target')
    files = data.get('files')
    if not isinstance(files, dict) or 'CMakeLists.txt' not in files or not any(
            name.endswith(('.c', '.cpp', '.cc', '.cxx')) for name in files):
        raise PCError('PC project must include CMake and host C/C++ source files')
    for name, expected in files.items():
        file = _file(root, name)
        with file.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise PCError('PC-project file hash differs: '+name)
    fallback = data.get('fallback')
    if not isinstance(fallback, dict) or not isinstance(fallback.get('interpreter'), bool) or not isinstance(
            fallback.get('runtime_compilation'), bool):
        raise PCError('PC project must disclose interpreter and runtime-compilation fallback')
    if data['execution_model'] != 'hybrid' and any(fallback.values()):
        raise PCError('fallback requires the hybrid execution model')
    return dict(manifest=data, integrity_verified=True, presentation_declared=_presentation(data),
                host_build_verified=False, gameplay_verified=False)


def export(project: dict, destination: Path, backend_id: str | None = None) -> dict:
    """Stage adapter output atomically. Never substitute a matching ROM export."""
    platform = platforms.canonical(project.get('platform', ''))
    candidates = [b for b in _backends() if b.platform == platform and
                  (backend_id is None or b.id == backend_id)]
    platforms.require(platform, PCError)
    if len(candidates) != 1:
        raise PCError(status(platform)['reason'] or 'select one registered PC backend')
    return export_backend(project, destination, candidates[0])


def export_backend(project: dict, destination: Path, backend: Backend) -> dict:
    """Publish a selected adapter, including explicitly invoked experimental ones.

    Experimental adapters are not automatically advertised as general platform
    support. They use the same integrity and publication checks as registered ones.
    """
    platform = platforms.canonical(project.get('platform', ''))
    platforms.require(platform, PCError)
    if backend.platform != platform:
        raise PCError('backend does not support the input platform')
    destination = Path(destination)
    if destination.exists():
        raise PCError('choose a new PC-project destination; existing work is preserved')
    root = project.get('root')
    if root and (destination.resolve() == Path(root).resolve() or
                 Path(root).resolve().is_relative_to(destination.resolve())):
        raise PCError('PC-project output must not contain the input project')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pc-export-', dir=destination.parent) as temp:
        stage = Path(temp) / 'project'
        stage.mkdir()
        backend.generate(project, stage)
        verified = verify(stage)
        manifest = verified['manifest']
        if manifest['schema'] != SCHEMA:
            raise PCError('new PC output must use the current project schema')
        if manifest['platform'] != platform or manifest['backend'] != dict(id=backend.id, revision=backend.revision):
            raise PCError('generated project does not match the selected backend/platform')
        # Renaming on the same filesystem publishes only a complete checked tree.
        if destination.exists():
            raise PCError('PC-project destination appeared during generation')
        stage.rename(destination)
    return dict(path=str(destination), format='pc', **verified)
