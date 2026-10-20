"""Package payload-free Windows host templates and their complete host source."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from decompnet.ee_native import ARCHIVE_SHA256, PROGRAMS, payload_section, sha256


def package(build: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    manifest = dict(format=1, archive_sha256=ARCHIVE_SHA256, tools={})
    with tempfile.TemporaryDirectory() as temporary:
        templates = Path(temporary)
        for name in PROGRAMS:
            image = (build / (name + '.exe')).read_bytes()
            payload = (build / name).read_bytes()
            offset, size = payload_section(image)
            if size != len(payload) or image[offset:offset + size] != payload:
                raise ValueError(f'Incorrect embedded payload: {name}')
            template = image[:offset] + bytes(size) + image[offset + size:]
            target = templates / (name + '.exe')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(template)
            manifest['tools'][name] = dict(payload_sha256=sha256(payload), template_sha256=sha256(template),
                                           executable_sha256=sha256(image))
        (templates / 'host-templates.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        shutil.copyfile(build / 'host-build.json', templates / 'host-build.json')
        with tarfile.open(output / 'ee-windows-templates-v1.tar.gz', 'w:gz') as archive:
            for path in sorted(templates.rglob('*')):
                if path.is_file(): archive.add(path, arcname=path.relative_to(templates))
    with tarfile.open(output / 'ee-windows-host-source-v1.tar.gz', 'w:gz') as archive:
        for path in sorted(Path(__file__).parent.iterdir()):
            if path.suffix in ('.py', '.c', '.md', '.json'): archive.add(path, arcname='recipe/' + path.name)
        for path in sorted((build / 'host-source').iterdir()):
            if path.suffix in ('.c', '.h') or path.name.startswith('COPYING'): archive.add(path, arcname='host-source/' + path.name)
        archive.add(ROOT / 'src/decompnet/ee_native.py', arcname='installer/ee_native.py')
    for path in sorted(output.glob('*.tar.gz')):
        print(sha256(path.read_bytes()), path.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package(args.build, args.output)
