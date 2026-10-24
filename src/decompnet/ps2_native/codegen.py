"""Guard pinned-emitter output against its own original executable sections.

Each module has a content-derived guard namespace. Guard every generated entry,
including functions reached by direct calls that bypass runtime lookup. This
deliberately rejects mutable executable sections; dirty-page tracking and
module selection remain separate runtime integration work.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from ..pc import PCError
from .media import _ram, elf_info

DECLARATION = r'void (\w+)\(uint8_t\* rdram, R5900Context\* ctx, PS2Runtime \*runtime\)'


def guard_generated(folder: Path, original: bytes, *, expected_functions: int) -> dict:
    folder = Path(folder)
    info = elf_info(original)
    sections = info['executable_sections']
    if not sections: raise PCError('PS2 module has no declared executable sections to guard')
    identity = hashlib.sha256(original).hexdigest()
    namespace = 'decomp_ps2_module_' + identity
    header = folder / (namespace + '.hpp')
    common = folder / 'ps2_code_guard.hpp'
    if header.exists() or common.exists(): raise PCError('PS2 generated code is already guarded; preserve existing output')
    definitions = {}
    sources = {}
    declarations = re.findall(DECLARATION + r';', (folder / 'ps2_recompiled_functions.h').read_text(encoding='utf-8'))
    if (not declarations or len(declarations) != expected_functions or
            len(declarations) != len(set(declarations))):
        raise PCError('pinned PS2 emitter declarations differ or contain duplicates')
    for path in sorted(folder.glob('*.cpp')):
        text = path.read_text(encoding='utf-8')
        matches = list(re.finditer(DECLARATION + r' \{', text))
        for match in matches:
            name = match[1]
            if name in definitions: raise PCError('pinned PS2 emitter has duplicate function definitions')
            definitions[name] = path
        if matches:
            text = re.sub(DECLARATION + r' \{',
                lambda m: m[0] + f'\n    {namespace}::check(rdram);', text)
            sources[path] = f'#include "{header.name}"\n' + text
    if set(definitions) != set(declarations):
        raise PCError('pinned PS2 emitter definitions differ from declarations')
    lines = ['#pragma once', '#include "ps2_code_guard.hpp"', f'namespace {namespace} {{']
    checks = []
    for index, section in enumerate(sections):
        region, physical = _ram(section['address'], section['size'])
        if region != 'ee-ram': raise PCError('PS2 native code guards currently require EE RAM sections')
        if not any(s['region'] == region and s['physical'] <= physical and
                   physical - s['physical'] + section['size'] <= s['file_size'] and
                   section['offset'] == s['offset'] + physical - s['physical']
                   for s in info['loads']):
            raise PCError('PS2 executable section differs from its file-backed load mapping')
        data = original[section['offset']:section['offset'] + section['size']]
        lines.append(f'inline constexpr uint8_t code_{index}[] = {{' + ','.join(map(str, data)) + '};')
        checks.append(f'    decomp_ps2::check_code(ram, {physical}u, code_{index}, "{identity}");')
    lines += ['inline void check(const uint8_t *ram) {', *checks, '}', '}']
    # Validate every input before modifying generated output. The pinned SDK is
    # never changed; these files belong to the new, reviewable source project.
    header.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    common.write_bytes(Path(__file__).with_name('code_guard.hpp').read_bytes())
    for path, text in sources.items(): path.write_text(text, encoding='utf-8')
    return dict(original_elf_sha256=identity, guarded_functions=len(definitions),
        executable_ranges=len(sections), guarded_bytes=sum(s['size'] for s in sections),
        guard='generated-function-entry', mutable_executable_sections_supported=False,
        self_modification_within_function_qualified=False)
