"""Keep native pool words while separating cross-module linker metadata.

dsd 0.12.1 assumes every DS Protect relocation belongs to the module that
contains its pool word. A protected overlay can also hold a shifted pointer
to resident ARM9 code. Native execution uses the original encoded word and
does not need that linker's relocation. Validate and retain its provenance,
then omit only its analysis metadata from dsd's module-local relocation pass.
"""
import hashlib
from pathlib import Path
import struct

import yaml


def prepare(extracted: Path) -> list[dict]:
    extracted = Path(extracted)
    residents = []
    for name in ('arm9', 'itcm', 'dtcm'):
        metadata = extracted/'arm9'/f'{name}.yaml'
        image = extracted/'arm9'/f'{name}.bin'
        if metadata.is_file() and image.is_file():
            record = yaml.safe_load(metadata.read_text(encoding='utf-8'))
            residents.append((name, int(record['base_address']), image.read_bytes()))
    path = extracted/'arm9_overlays/overlays.yaml'
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    reviewed = []
    for module in document.get('overlays', []):
        protected = module.get('dsprot', {}).get('unencrypted')
        if not protected:
            continue
        base = int(module['base_address'])
        size = int(module['code_size'])
        end = base + size + int(module.get('bss_size', 0))
        records = protected.get('relocations', [])
        external = [r for r in records if not base <= (r['to_address'] & ~1) < end]
        if not external:
            continue
        image_path = extracted/'arm9_overlays'/module['file_name']
        if image_path.resolve().parent != (extracted/'arm9_overlays').resolve():
            raise ValueError('DS Protect overlay image escapes extraction directory')
        image = image_path.read_bytes()
        if len(image) != size:
            raise ValueError('DS Protect overlay initialized size differs')
        for relocation in external:
            source, target, addend = (relocation[k] for k in ('from_address', 'to_address', 'addend'))
            if any(type(value) is not int or not 0 <= value <= 0xffffffff
                   for value in (source, target, addend)):
                raise ValueError('DS Protect relocation is not a bounded 32-bit value')
            if source & 3 or not base <= source <= base + len(image) - 4:
                raise ValueError('DS Protect relocation pool word is outside initialized overlay')
            if target + addend > 0xffffffff or struct.unpack_from('<I', image, source-base)[0] != target + addend:
                raise ValueError('DS Protect encoded pool word differs from relocation metadata')
            owners = [name for name, start, data in residents if start <= (target & ~1) < start+len(data)]
            if len(owners) != 1:
                raise ValueError('DS Protect external target needs one initialized resident ARM9 owner')
            reviewed.append(dict(module_id=int(module['id']), **relocation,
                                 target_module=owners[0], image_sha256=hashlib.sha256(image).hexdigest()))
        protected['relocations'] = [r for r in records if r not in external]
    # Validate every record before changing even the disposable metadata.
    if reviewed:
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
    return reviewed
