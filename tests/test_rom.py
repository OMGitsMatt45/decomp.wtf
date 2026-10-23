"""Shared ROM pipeline checks, migrated from the retired N64 demo to PS1."""
import struct
import pytest
from decompnet import toolchains
from decompnet.rom import psx as reader
from decompnet.rom.errors import RomError
from .psx_fixture import built
from .test_psx import psx
from . import test_psx as matching

pytestmark = pytest.mark.skipif(any(toolchains.installed(t) is None for t in
    ('gcc-2.7.2-psx','gcc-2.8.1-psx','binutils-mips')),reason='requires pinned PS1 compiler fixtures')


def test_header_and_byte_orders(built):
    data, info = reader.read_exe(built)
    assert data[:8] == b'PS-X EXE'
    assert struct.unpack_from('<I',data,0x18)[0] == info['load']
    with pytest.raises(RomError):reader.read_exe(b'bad')


def test_split_finds_every_function(psx):
    matching.test_import(psx)


def test_original_source_matches_the_rom_byte_for_byte(psx):
    matching.test_every_game_function_matches(psx)


def test_a_wrong_function_does_not_match(psx):
    matching.test_wrong_code_does_not_match(psx)


def test_unknown_names_are_explained(psx):
    net, slug, _, _ = psx
    agent,_ = net.local_agent('unknown-symbol-check')
    fn=net.store.one("SELECT f.name FROM functions f JOIN projects p ON p.id=f.project_id WHERE p.slug=? AND f.status='open' ORDER BY f.id LIMIT 1",slug)
    result=net.compile_and_diff(agent,fn['name'],f"void some_helper(void); void {fn['name']}(void) {{ some_helper(); }}",slug)
    assert 'some_helper' in result
