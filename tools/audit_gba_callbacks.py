"""Check a ROM-bound callback inventory against a generated GBA dispatch registry.

Run after export and before compiling. Only source-known required entries fail
the check; optional review candidates remain visible in the JSON report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA = 'decomp.wtf.callback-inventory/v1'
ROW = re.compile(r'^\s*\{(?:0x([0-9a-fA-F]+)|(\d+))u,\s*([01]),', re.M)


def audit(rom, source, inventory):
    if inventory.get('schema') != SCHEMA:
        raise ValueError('unsupported callback inventory schema')
    identity = hashlib.sha256(rom).hexdigest()
    if inventory.get('input_sha256') != identity:
        raise ValueError('callback inventory does not match the supplied ROM')
    manifest = json.loads((source/'pc-project.json').read_text(encoding='utf-8'))
    if not manifest.get('inputs') or manifest['inputs'][0].get('sha256') != identity:
        raise ValueError('generated source does not match the supplied ROM')
    rows = inventory.get('entries')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100000:
        raise ValueError('inventory needs 1..100000 callback entries')
    expected = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid callback entry')
        address, mode = row.get('address'), row.get('mode')
        required = row.get('required', True)
        if (type(address) is not int or mode not in ('arm', 'thumb') or
                type(required) is not bool or address % (4 if mode == 'arm' else 2) or
                not 0x08000000 <= address < 0x08000000+len(rom)):
            raise ValueError('callback address, mode or required flag is invalid')
        names = row.get('names', [row.get('name', f'0x{address:08x}')])
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError('callback names must be strings')
        item = expected.setdefault((address, mode), dict(address=address, hex_address=f'0x{address:08x}',
            mode=mode, required=False, names=[]))
        item['required'] |= required
        item['names'] = sorted(set(item['names']) | set(names))
    files = sorted((source/'game').glob('dispatch_entries_*.inc'))
    if not files:
        files = [source/'game/dispatch.c']
    covered = set()
    for file in files:
        for match in ROW.finditer(file.read_text(encoding='utf-8')):
            address = int(match[1], 16) if match[1] else int(match[2])
            key = address, 'thumb' if match[3] == '1' else 'arm'
            if key in expected:
                covered.add(key)
    missing = [row for key, row in sorted(expected.items()) if key not in covered]
    required = [row for row in missing if row['required']]
    optional = [row for row in missing if not row['required']]
    return dict(schema='decomp.wtf.callback-audit/v1', input_sha256=identity,
        backend=manifest.get('backend'), source=str(source.resolve()),
        inventory_sources=inventory.get('sources', {}), scope=inventory.get('scope', ''),
        callbacks_checked=len(expected), required_callbacks=sum(v['required'] for v in expected.values()),
        covered_callbacks=len(covered), missing_required=required, optional_review_candidates=optional,
        passed=not required)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.rom.read_bytes(), args.source,
            json.loads(args.inventory.read_text(encoding='utf-8')))
        args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, KeyError) as error:
        print(f'Callback audit: {error}', file=sys.stderr)
        return 2
    print(f"Callbacks: {result['covered_callbacks']}/{result['callbacks_checked']} covered; "
          f"{len(result['missing_required'])} required missing; "
          f"{len(result['optional_review_candidates'])} optional review candidates")
    for row in result['missing_required']:
        print(f"  {row['hex_address']} {row['mode']}: {', '.join(row['names'])}")
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
