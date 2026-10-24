"""Original EE pointers/jump tables: prove the targets, preserve unknown paths."""
import struct
from decompnet.ps2_native.discovery import discover
from .test_ps2_native_discovery import stripped,addresses
from .fixtures.ps2_native import BASE,i,r


def image(words,functions=(64,80),table=None,read_only=False):
    raw=bytearray(stripped(words))
    if read_only:struct.pack_into('<I',raw,52+24,5)
    for at in functions:struct.pack_into('<2I',raw,0x100+at,r(8,rs=31),0)
    if table:
        at,values=table;struct.pack_into('<'+'I'*len(values),raw,0x100+at,*values)
    return bytes(raw)


def test_constant_target_is_latched_before_a_jalr_delay_slot_changes_it():
    result=discover(image([i(15,0,25,BASE>>16),i(13,25,25,64),r(9,rs=25,rd=31),i(13,25,25,80),r(8,rs=31),0]))
    assert result['resolved_indirect']==[dict(pc=BASE+8,targets=[BASE+64])]
    assert not result['unresolved'] and BASE+64 in addresses(result) and BASE+80 not in addresses(result)


def test_join_preserves_two_possible_targets_and_does_not_invent_an_unknown_one():
    words=[i(4,4,0,4),i(15,0,25,BASE>>16),i(13,25,25,64),i(4,0,0,3),0,i(13,25,25,80),0,r(9,rs=25,rd=31),0,r(8,rs=31),0]
    assert discover(image(words))['resolved_indirect']==[dict(pc=BASE+28,targets=[BASE+64,BASE+80])]
    words[5]=r(0x2d,rs=5,rt=0,rd=25)
    result=discover(image(words))
    assert result['resolved_indirect']==[]
    assert result['unresolved']==[dict(pc=BASE+28,kind='indirect-call',register=25)]


def test_bounded_indexed_table_resolves_both_targets_without_disassembling_the_table():
    words=[i(12,4,8,1),r(0,rt=8,rd=8,sa=2),i(15,0,9,BASE>>16),i(13,9,9,128),r(0x2d,rs=9,rt=8,rd=9),i(35,9,25,0),r(8,rs=25),0]
    result=discover(image(words,table=(128,[BASE+64,BASE+80]),read_only=True))
    assert result['resolved_indirect']==[dict(pc=BASE+24,targets=[BASE+64,BASE+80])]
    assert not result['unresolved'] and BASE+128 not in addresses(result)
    assert result['pointer_reads']==[dict(address=BASE+128,size=4,writable=False),dict(address=BASE+132,size=4,writable=False)]


def test_unsigned_bound_branch_refines_the_index_only_on_its_proven_edge():
    words=[i(11,4,1,2),i(4,1,0,18),0,r(0,rt=4,rd=8,sa=2),i(15,0,9,BASE>>16),i(13,9,9,128),r(0x2d,rs=9,rt=8,rd=9),i(35,9,25,0),r(8,rs=25),0]
    result=discover(image(words,table=(128,[BASE+64,BASE+80])))
    assert result['resolved_indirect']==[dict(pc=BASE+32,targets=[BASE+64,BASE+80])]


def test_native_call_continuation_cannot_reuse_a_caller_saved_target():
    words=[i(15,0,25,BASE>>16),i(13,25,25,80),3<<26|(BASE+64)>>2,0,r(9,rs=25,rd=31),0,r(8,rs=31),0]
    result=discover(image(words))
    assert result['resolved_indirect']==[]
    assert result['unresolved']==[dict(pc=BASE+16,kind='indirect-call',register=25)]


def test_annulled_delay_slot_does_not_change_an_indirect_target():
    words=[i(15,0,25,BASE>>16),i(13,25,25,64),i(21,4,4,2),i(13,25,25,80),r(9,rs=25,rd=31),0,r(8,rs=31),0]
    result=discover(image(words))
    assert result['resolved_indirect']==[dict(pc=BASE+16,targets=[BASE+64])]


def test_gp_relative_callback_uses_elf_reginfo_without_a_title_address():
    raw=bytearray(image([i(35,28,25,0),r(9,rs=25,rd=31),0,r(8,rs=31),0],table=(128,[BASE+64]),read_only=True))
    reginfo=len(raw);raw.extend(struct.pack('<6I',0,0,0,0,0,BASE+128))
    table=len(raw);raw.extend(bytes(40));raw.extend(struct.pack('<10I',0,0x70000006,0,0,reginfo,24,0,0,4,0))
    struct.pack_into('<I',raw,32,table);struct.pack_into('<3H',raw,46,40,2,0)
    result=discover(bytes(raw))
    assert result['resolved_indirect']==[dict(pc=BASE+4,targets=[BASE+64])]
