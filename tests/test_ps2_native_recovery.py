"""Automatic source export requires closed flow and unambiguous function ownership."""
import pytest
from decompnet.pc import PCError
from decompnet.ps2_native.profile import module
from .fixtures.ps2_port import stripped_original
from .fixtures.ps2_native import BASE,i,r
from .test_ps2_native_indirect import image


def test_stripped_graphics_program_recovers_without_a_title_map_or_symbols():
    result=module(stripped_original())
    assert result['recovery']['method']=='bounded-closed-reachable-cfg'
    assert len(result['functions'])==1 and result['functions'][0]['address']==BASE
    assert result['functions'][0]['size']>100 and not result['native_services']


def test_unknown_callback_and_mutable_table_are_explicit_review_cases():
    with pytest.raises(PCError,match='reviewed'):
        module(image([r(9,rs=25,rd=31),0,r(8,rs=31),0]))
    words=[i(15,0,9,BASE>>16),i(13,9,9,128),i(35,9,25,0),r(9,rs=25,rd=31),0,r(8,rs=31),0]
    with pytest.raises(PCError,match='writable'):
        module(image(words,table=(128,[BASE+64])))


def test_a_resolved_jump_table_does_not_authorize_embedded_gaps_as_code():
    words=[i(12,4,8,1),r(0,rt=8,rd=8,sa=2),i(15,0,9,BASE>>16),i(13,9,9,128),r(0x2d,rs=9,rt=8,rd=9),i(35,9,25,0),r(8,rs=25),0]
    with pytest.raises(PCError,match='gaps'):
        module(image(words,table=(128,[BASE+64,BASE+80]),read_only=True))


def test_constant_callback_recovers_separate_exact_function_ranges():
    result=module(image([i(15,0,25,BASE>>16),i(13,25,25,64),r(9,rs=25,rd=31),0,r(8,rs=31),0]))
    assert [(f['address'],f['size']) for f in result['functions']]==[(BASE,24),(BASE+64,8)]
