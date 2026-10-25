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


def validate_native_services(folder: Path, bindings: list[dict]) -> None:
    """A permitted SDK wrapper is explicit, never counted as recovered game C++."""
    declared = re.findall(r'void (\w+)\(uint8_t\* rdram, R5900Context\* ctx, PS2Runtime\* runtime\);',
        (Path(folder)/'ps2_recompiled_stubs.h').read_text(encoding='utf-8'))
    by_address={}
    for name in declared:
        suffix=re.search(r'_0x([0-9a-fA-F]+)$',name)
        if suffix is None:raise PCError('PS2 native service wrapper has no input address')
        by_address[int(suffix[1],16)]=name
    if len(by_address)!=len(declared) or set(by_address)!={b['address'] for b in bindings}:
        raise PCError('PS2 emitted native services differ from the explicit profile')
    for binding in bindings:
        name=by_address[binding['address']]
        text=(Path(folder)/(name+'.cpp')).read_text(encoding='utf-8')
        calls=re.findall(r'ps2_(?:stubs|syscalls)::(\w+)\(rdram, ctx, runtime\)',text)
        if calls!=[binding['name']] or re.search(r'throw|TODO|return\s*;',text):
            raise PCError('PS2 native service is not a supported explicit runtime binding: '+name)


def guard_generated(folder: Path, original: bytes, *, expected_functions: int,
                    function_ranges: dict[int, int] | None = None,
                    code_ranges: list[dict] | None = None) -> dict:
    folder = Path(folder)
    info = elf_info(original)
    sections = info['executable_sections']
    if not sections and code_ranges is None: raise PCError('PS2 module has no declared executable sections to guard')
    if code_ranges is not None:
        available=[*sections,*[dict(address=s['address'],size=s['file_size'],offset=s['offset'])
            for s in info['loads'] if s['flags']&1 and s['file_size']]]
        selected = []
        for row in code_ranges:
            address, size = row['address'], row['size']
            section = next((s for s in available if s['address'] <= address and
                address + size <= s['address'] + s['size']), None)
            if section is None or size <= 0 or address & 3 or size & 3:
                raise PCError('PS2 typed code range is outside executable sections')
            selected.append({**section, 'address': address, 'size': size,
                'offset': section['offset'] + address - section['address']})
        sections = sorted(selected, key=lambda s:s['address'])
        if not sections or any(a['address'] + a['size'] > b['address'] for a,b in zip(sections,sections[1:])):
            raise PCError('PS2 typed code ranges are empty or overlap')
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
            def checked(match):
                if function_ranges is None:return match[0] + f'\n    {namespace}::check(rdram);'
                suffix = re.search(r'_0x([0-9a-fA-F]+)$', match[1])
                address = int(suffix[1],16) if suffix else None
                size = function_ranges.get(address,0)
                if not size or address & 3 or size & 3 or not any(s['address'] <= address and
                    address + size <= s['address'] + s['size'] for s in sections):
                    raise PCError('PS2 function guard has no exact typed code range: '+match[1])
                return match[0] + f'\n    {namespace}::check_range(rdram, {address}u, {size}u);'
            text = re.sub(DECLARATION + r' \{',
                checked, text)
            sources[path] = f'#include "{header.name}"\n' + text
    if set(definitions) != set(declarations):
        raise PCError('pinned PS2 emitter definitions differ from declarations')
    lines = ['#pragma once', '#include "ps2_code_guard.hpp"', f'namespace {namespace} {{']
    checks = []
    blobs = [f'#include "{header.name}"', f'namespace {namespace} {{']
    range_checks = []
    for index, section in enumerate(sections):
        region, physical = _ram(section['address'], section['size'])
        if region != 'ee-ram': raise PCError('PS2 native code guards currently require EE RAM sections')
        if not any(s['region'] == region and s['physical'] <= physical and
                   physical - s['physical'] + section['size'] <= s['file_size'] and
                   section['offset'] == s['offset'] + physical - s['physical']
                   for s in info['loads']):
            raise PCError('PS2 executable section differs from its file-backed load mapping')
        data = original[section['offset']:section['offset'] + section['size']]
        if function_ranges is None:
            lines.append(f'inline constexpr uint8_t code_{index}[] = {{' + ','.join(map(str, data)) + '};')
        else:
            lines.append(f'extern const uint8_t code_{index}[{len(data)}];')
            blobs.append(f'const uint8_t code_{index}[{len(data)}] = {{' + ','.join(map(str,data)) + '};')
            range_checks.append(f'    if (address >= {section["address"]}u && address - {section["address"]}u < {len(data)}u && size <= {len(data)}u - (address - {section["address"]}u)) {{\n'
                f'        decomp_ps2::check_code(ram, {physical}u + (address - {section["address"]}u), std::span(code_{index} + (address - {section["address"]}u), size), "{identity}"); return;\n    }}')
        checks.append(f'    decomp_ps2::check_code(ram, {physical}u, code_{index}, "{identity}");')
    lines += ['inline void check(const uint8_t *ram) {', *checks, '}']
    if function_ranges is not None:
        lines += ['inline void check_range(const uint8_t *ram, uint32_t address, uint32_t size) {',
            '    if (!size) throw std::invalid_argument("empty PS2 function guard");', *range_checks,
            '    throw std::invalid_argument("PS2 function guard outside typed code");', '}']
    lines += ['}']
    # Validate every input before modifying generated output. The pinned SDK is
    # never changed; these files belong to the new, reviewable source project.
    header.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    common.write_bytes(Path(__file__).with_name('code_guard.hpp').read_bytes())
    if function_ranges is not None:
        (folder / (namespace + '.cpp')).write_text('\n'.join([*blobs,'}'])+'\n',encoding='utf-8')
    for path, text in sources.items(): path.write_text(text, encoding='utf-8')
    return dict(original_elf_sha256=identity, guarded_functions=len(definitions),
        executable_ranges=len(sections), guarded_bytes=sum(s['size'] for s in sections),
        code_ranges=[dict(address=s['address'], size=s['size']) for s in sections],
        guard='generated-function-entry', mutable_executable_sections_supported=False,
        guard_scope='function' if function_ranges is not None else 'module',
        self_modification_within_function_qualified=False)
