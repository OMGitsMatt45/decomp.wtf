"""Stage the owner's exact cartridge. Run with Python; no decomp.wtf install needed."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root/'assets.json').read_text(encoding='utf-8'))
    source = Path(sys.argv[1])
    if source.stat().st_size != expected['size']:
        raise ValueError('cartridge size differs from this source project')
    assets = root/'assets'; assets.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.extract-', dir=assets) as work:
        staged = Path(work)/'game.gba'
        shutil.copyfile(source, staged)
        with staged.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected['sha256']:
            raise ValueError('cartridge SHA-256 differs from this source project')
        staged.replace(assets/'game.gba')
    print('Verified cartridge staged in assets/game.gba')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, IndexError) as error:
        sys.exit(str(error))
