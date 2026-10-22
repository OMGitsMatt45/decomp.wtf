"""Period C++ runtime contracts remain visible instead of binding host libraries."""

from io import BytesIO
import os
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
import pytest

from decompnet import compiler, project, toolchains

pytestmark = pytest.mark.skipif(os.environ.get('DECOMP_TEST_N64_CPP') != '1', reason='requires pinned N64 compilers')


@pytest.mark.parametrize('toolchain,frontend', [('gcc-2.7.2-kmc', ''), ('ido-5.3', 'edg'),
                                               ('ido-5.3', 'cfront'), ('ido-7.1', 'edg')])
def test_heap_array_virtual_and_static_runtime_contracts(tmp_path, toolchain, frontend):
    assert toolchains.installed(toolchain) is not None
    cfg = project.compiler_config(tmp_path, {'kind': 'rom', 'platform': 'n64', 'compiler': {
        'toolchain': toolchain, 'language': 'c++', 'sandbox': 'none',
        **({'cpp_frontend': frontend} if frontend else {})}})
    source = (Path(__file__).parent / 'fixtures/n64_cpp_runtime.cpp').read_text()
    result = compiler.compile_source(cfg, '', source)
    assert result.ok, result.log
    elf = ELFFile(BytesIO(result.obj))
    assert elf['e_machine'] == 'EM_MIPS' and not elf.little_endian and elf.elfclass == 32
    symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
    undefined = {s.name for s in symbols if s['st_shndx'] == 'SHN_UNDEF' and s.name}
    assert 'record_event' in undefined
    required = {'__builtin_new', '__builtin_delete'} if toolchain.startswith('gcc') else {
        '__nw__FUi', '__dl__FPv', '__vec_new', '__vec_delete'}
    assert required <= undefined
    assert not any(name.startswith(('__cxa_', 'GLIBC', '__gxx_')) for name in undefined)
    defined = {s.name for s in symbols if s['st_shndx'] != 'SHN_UNDEF'}
    assert {'runtime_heap', 'runtime_array', 'runtime_static'} <= defined
    assert any('GameObject' in name and ('read' in name or '__dt' in name or '_._' in name) for name in defined)
    fixups = []
    virtual_refs = []
    methods = {(s['st_shndx'], s['st_value']) for s in symbols if 'GameObject' in s.name and
               s['st_shndx'] != 'SHN_UNDEF' and s['st_info']['type'] == 'STT_FUNC'}
    for section in elf.iter_sections():
        if isinstance(section, RelocationSection):
            table = elf.get_section(section['sh_link'])
            owner = elf.get_section(section['sh_info'])
            for relocation in section.iter_relocations():
                symbol = table.get_symbol(relocation['r_info_sym'])
                fixups.append(symbol.name)
                if owner['sh_flags'] & 2 and not owner['sh_flags'] & 4 and relocation['r_info_type'] == 2:
                    at = relocation['r_offset']
                    addend = int.from_bytes(owner.data()[at:at + 4], 'big')
                    virtual_refs.append((symbol['st_shndx'], symbol['st_value'] + addend))
    assert required <= set(fixups)
    assert methods.intersection(virtual_refs), 'virtual tables must retain target method relocations'
    # Allocations, local-static guards and vector construction need the game's
    # period runtime. The object deliberately retains these unresolved imports.
    assert any(s['sh_size'] and s.name in ('.data', '.bss', '.rodata') for s in elf.iter_sections())
