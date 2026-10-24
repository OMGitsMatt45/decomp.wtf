"""Independent generated module symbols and byte-selected EE dispatch.

Only zero-error, zero-stub emitter output may enter this adapter. It preserves
the original registration source and wraps every dense-table entry, including
resume PCs. Identical code identities with ambiguous implementations fail.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from ..pc import PCError
from .codegen import DECLARATION
from .media import _ram


def isolate(folder: Path, guards: dict) -> dict:
    folder = Path(folder).resolve()
    identity = guards['original_elf_sha256']
    if not re.fullmatch('[0-9a-f]{64}', identity): raise PCError('PS2 module identity is invalid')
    namespace = 'decomp_ps2_module_' + identity
    if not (folder / (namespace + '.hpp')).is_file(): raise PCError('PS2 module requires generated entry guards')
    marker = folder / 'module.json'
    if marker.exists() or (folder / 'register_functions.original.txt').exists():
        raise PCError('PS2 module is already isolated; preserve existing output')
    registration = folder / 'register_functions.cpp'
    original_registration = registration.read_bytes()
    text = original_registration.decode('utf-8')
    base_match = re.search(r'g_ps2RecompiledFunctionTableBase = (0x[0-9a-fA-F]+)u;', text)
    count_match = re.search(r'g_ps2RecompiledFunctionTableSlotCount = (\d+)u;', text)
    matches = re.findall(r'g_ps2RecompiledFunctionTable\[(\d+)\] = (\w+); // (0x[0-9a-fA-F]+)', text)
    if not base_match or not count_match or not matches: raise PCError('pinned PS2 registration layout differs')
    base, count = int(base_match[1], 16), int(count_match[1])
    declarations = re.findall(DECLARATION + ';', (folder / 'ps2_recompiled_functions.h').read_text(encoding='utf-8'))
    if len(declarations) != guards['guarded_functions']:
        raise PCError('PS2 guarded function count differs from its module declarations')
    entries = []
    for slot, name, address in matches:
        address = int(address, 16)
        if int(slot) >= count or address != base + int(slot) * 4 or name not in declarations:
            raise PCError('PS2 registration entry differs from its dense-table mapping')
        if not any(s['address'] <= address and address + 4 <= s['address'] + s['size'] for s in guards['code_ranges']):
            raise PCError('PS2 registered entry is outside guarded executable bytes')
        entries.append(dict(address=address, function=namespace + '_' + name))
    if len({e['address'] for e in entries}) != len(entries) or {m[1] for m in matches} != set(declarations):
        raise PCError('PS2 module has duplicate or unregistered function entries')
    functions_header = namespace + '_functions.h'
    stubs_header = namespace + '_stubs.h'
    sources = {}
    names = {name: namespace + '_' + name for name in declarations}
    token = re.compile(r'\b[A-Za-z_]\w*\b')
    for path in folder.iterdir():
        if path.suffix not in ('.cpp', '.h') or path == registration or path.name == 'ps2_code_guard.hpp': continue
        source = path.read_text(encoding='utf-8')
        source = token.sub(lambda m: names.get(m[0],m[0]), source)
        source = source.replace('ps2_recompiled_functions.h', functions_header).replace('ps2_recompiled_stubs.h', stubs_header)
        source = source.replace('PS2_RECOMPILED_FUNCTIONS_H', namespace.upper() + '_FUNCTIONS_H')
        target = folder / (functions_header if path.name == 'ps2_recompiled_functions.h'
                           else stubs_header if path.name == 'ps2_recompiled_stubs.h' else path.name)
        if target != path and target.exists(): raise PCError('PS2 isolated header exists; preserve existing output')
        sources[path] = (target, source)
    # All layout checks precede changes. Preserve the emitter's original table
    # as evidence but prevent it from registering unguarded global entries.
    registration.rename(folder / 'register_functions.original.txt')
    for old, (new, source) in sources.items():
        new.write_text(source, encoding='utf-8')
        if old != new: old.unlink()
    module = dict(path=str(folder), identity=identity, namespace=namespace,
        functions_header=functions_header, entries=entries, guards=guards,
        original_registration_sha256=hashlib.sha256(original_registration).hexdigest())
    marker.write_text(json.dumps({**module, 'path': '.'}, indent=2) + '\n', encoding='utf-8')
    return module


def registry(modules: list[dict], output: Path, *, project_root: Path | None = None) -> dict:
    output = Path(output).resolve()
    project_root=Path(project_root).resolve() if project_root is not None else output.parent
    if not output.is_relative_to(project_root):raise PCError('PS2 registry must stay inside its source project')
    if output.exists(): raise PCError('PS2 module registry output exists; preserve existing work')
    if not modules or len(modules) > 1024: raise PCError('PS2 module registry count is invalid')
    if len({m['identity'] for m in modules}) != len(modules): raise PCError('PS2 module identities must be unique')
    entries = {}
    lines = ['#include "ps2_runtime.h"', '#include <stdexcept>']
    for module in modules:
        expected_namespace = 'decomp_ps2_module_' + module['identity']
        if (not re.fullmatch('[0-9a-f]{64}', module['identity']) or
                module['namespace'] != expected_namespace or module['functions_header'] != expected_namespace + '_functions.h'):
            raise PCError('PS2 module namespace differs from its identity')
        folder = Path(module['path']).resolve()
        if not folder.is_relative_to(project_root): raise PCError('PS2 module source must stay inside the source project')
        prefix = Path(os.path.relpath(folder, output.parent)).as_posix()
        if any(c in prefix for c in '\\"\r\n'): raise PCError('PS2 module source path cannot be represented in an include')
        lines += [f'#include "{prefix}/{module["functions_header"]}"',
                  f'#include "{prefix}/{module["namespace"]}.hpp"']
        for entry in module['entries']:
            address = entry['address']
            if address & 3: raise PCError('PS2 module entry is unaligned')
            if _ram(address, 4)[0] != 'ee-ram': raise PCError('PS2 module registry currently requires EE RAM entries')
            if not re.fullmatch(re.escape(expected_namespace) + r'_\w+', entry['function']):
                raise PCError('PS2 module entry has an invalid function symbol')
            entries.setdefault(address, []).append((module, entry['function']))
    if not entries: raise PCError('PS2 module registry has no entries')
    base, end = min(entries), max(entries) + 4
    if end - base > 0x02000000: raise PCError('PS2 dense module registry exceeds its 32 MiB address-span bound')
    count = (end - base) // 4
    targets,dispatches={},{}
    for address, candidates in sorted(entries.items()):
        if len(candidates) == 1 and candidates[0][0].get('guards',{}).get('guard_scope') == 'function':
            # The function already guards its exact original bytes. Resume
            # entries can share that same pointer, avoiding thousands of
            # identical forwarding wrappers in a retail registry.
            targets[address]=candidates[0][1]
            continue
        key=tuple((m['identity'],f) for m,f in candidates)
        if key in dispatches:
            targets[address]=dispatches[key]
            continue
        target=f'dispatch_{address:x}'
        targets[address]=dispatches[key]=target
        lines += [f'static void {target}(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime) {{',
                  '    PS2Runtime::RecompiledFunction selected = nullptr;']
        for index, (module, function) in enumerate(candidates):
            lines += [f'    bool matches_{index} = false;', '    try {',
                      f'        {module["namespace"]}::check(rdram);', f'        matches_{index} = true;',
                      '    } catch (const decomp_ps2::CodeMismatch &) {}', f'    if (matches_{index}) {{',
                      '        if (selected) throw std::runtime_error("ambiguous PS2 resident code identity");',
                      f'        selected = {function};', '    }']
        # Never catch a mismatch from the selected function: restarting a second
        # implementation after guest side effects would corrupt guest state.
        lines += ['    if (!selected) throw decomp_ps2::CodeMismatch("no known module for resident EE entry");',
                  '    selected(rdram, ctx, runtime);', '}']
    lines += [f'extern const uint32_t g_ps2RecompiledFunctionTableBase = {base}u;',
              f'extern const uint32_t g_ps2RecompiledFunctionTableEnd = {end}u;',
              f'extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = {count}u;',
              f'PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[{count}u] = {{}};',
              'namespace { struct Entry { uint32_t slot; PS2Runtime::RecompiledFunction function; };',
              'const Entry known_entries[] = {']
    lines += [f'    {{{(address-base)//4}u, {targets[address]}}},' for address in sorted(entries)]
    lines += ['}; struct RegistryInitializer { RegistryInitializer() {',
        '    for (const auto &entry : known_entries) g_ps2RecompiledFunctionTable[entry.slot] = entry.function;',
        '} }; static const RegistryInitializer initialize; }']
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return dict(modules=len(modules), entries=len(entries), shared_entries=sum(len(v) > 1 for v in entries.values()),
        module_identities=[m['identity'] for m in modules],
        source_sha256=hashlib.sha256(output.read_bytes()).hexdigest(), selection='original-executable-bytes',
        unknown_code='reject', ambiguous_code='reject', interpreter_fallback=False,
        self_modification_within_function_qualified=False, runtime_registration_bypass_qualified=False)
