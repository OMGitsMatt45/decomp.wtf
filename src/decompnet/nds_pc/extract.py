"""Standalone asset extraction for this generated PC repository (Python 3.9+)."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent.parent
    if len(sys.argv) != 2:
        raise ValueError('usage: python tools/extract_assets.py /path/to/original.nds')
    original = Path(sys.argv[1]).read_bytes()
    layout = json.loads((root/'game/image.json').read_text())
    if hashlib.sha256(original).hexdigest() != layout['input_sha256']:
        raise ValueError('original ROM SHA-256 differs from the reviewed input')
    decoded = []
    for module in layout['modules']:
        raw = original[module['offset']:module['offset']+module['stored_size']]
        data = decompress_blz(raw, module['size']) if module['compressed'] else raw
        if len(data) != module['size'] or hashlib.sha256(data).hexdigest() != module['sha256']:
            raise ValueError('decoded module differs: '+module['name'])
        decoded.append((module['asset'], data))
    # Validate every input before touching existing extracted files.
    (root/'assets').mkdir(exist_ok=True)
    for name, data in decoded:
        (root/'assets'/name).write_bytes(data)
    print('Extracted '+str(len(decoded))+' reviewed DS modules')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('asset extraction: '+str(error), file=sys.stderr)
        sys.exit(1)
