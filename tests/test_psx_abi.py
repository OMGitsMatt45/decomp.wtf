"""Incoming register use must survive branches, delay slots and call chains."""

import os
import re
import struct
from types import SimpleNamespace

import pytest

from decompnet.rom.psx_abi import argument_packet, argument_summaries, incoming_arguments


BASE = 0x80010000


def words(*values):
    return struct.pack(f"<{len(values)}I", *values)


def jal(address):
    return 0x0C000000 | (address >> 2 & 0x3FFFFFF)


def row(address, code, unit="main"):
    return {"vram": address, "unit": unit, "target": code}


def test_later_branch_path_preserves_an_incoming_argument():
    # One path overwrites a1, the other returns its incoming value.
    code = words(0x10800003, 0, 0x24050007, 0, 0x03E00008, 0x00A01021)
    assert incoming_arguments(code, BASE) == 3
    # The branch consumes original a0 before its delay slot overwrites it.
    assert incoming_arguments(words(0x10800001, 0x24040000, 0x03E00008, 0x00E01021), BASE) == 9


def test_loop_paths_and_branch_delay_reads_reach_a_fixed_point():
    code = words(0x24040000, 0x14A00003, 0, 0x1000FFFD, 0x00C04021, 0x03E00008, 0x00E01021)
    assert incoming_arguments(code, BASE) == 14


def test_call_delay_slot_precedes_callee_arguments_and_return_clobbers():
    target = BASE + 0x100
    # a0 becomes a constant; a1 is still forwarded. a2 after the call is not
    # its incoming value under the ordinary o32 call-clobber convention.
    code = words(jal(target), 0x24040000, 0x03E00008, 0x00C01021)
    assert incoming_arguments(code, BASE, {target: 3}) == 2
    assert incoming_arguments(code, BASE) == 0  # unknown does not mean all four
    assert incoming_arguments(code, BASE, {target: None}) is None
    assert incoming_arguments(words(jal(target), 0x00A02021, 0x03E00008, 0), BASE, {target: 1}) == 2


def test_partial_loads_read_old_argument_word_before_overwriting():
    assert incoming_arguments(words(0x88860000, 0x03E00008, 0), BASE) == 5  # lwl a2,0(a0)


def test_optional_variadic_register_packet_does_not_inflate_caller_arity():
    callee = BASE + 0x100
    # Save a0..a3 to incoming SP0..12, using a SP-derived va_list pointer for
    # the last two words. Those stores cannot prove four mandatory C params.
    packet = words(0x27BDFFE8, 0x27A2001C, 0xAFA40018, 0x24040001,
                   0xAFA5001C, 0xAC460004, 0xAC470008, 0x03E00008, 0x27BD0018)
    assert argument_packet(packet)
    assert incoming_arguments(packet, callee) is None
    caller = words(jal(callee), 0x24040001, 0x03E00008, 0)
    assert argument_summaries([row(BASE, caller), row(callee, packet)]) == {(BASE, "main"): 0}


def test_ordinary_argument_uses_are_not_mistaken_for_an_o32_packet():
    fixed = words(0x27BDFFE8, 0xAFA40018, 0xAFA5001C, 0x03E00008, 0x27BD0018)
    assert not argument_packet(fixed) and incoming_arguments(fixed, BASE) == 3
    data_store = words(0xAC87000C, 0x03E00008, 0)
    assert not argument_packet(data_store) and incoming_arguments(data_store, BASE) == 9


def test_call_hints_do_not_fall_back_to_optional_packet_saves():
    from decompnet.rom.psx_calls import call_context
    from decompnet.rom.symbols import Symbol, SymbolTable
    target = BASE + 0x100
    callee = {"id": 1, **row(target, words(0x27BDFFE8, 0xAFA5001C, 0xAFA60020,
                                          0xAFA70024, 0x03E00008, 0x27BD0018))}
    net = SimpleNamespace(cfg=lambda proj: {"platform": "psx"}, store=SimpleNamespace(all=lambda *args: [callee]),
                          symbols=lambda pid: SymbolTable([Symbol("callback", target, kind="func")]))
    caller = row(BASE, words(jal(target), 0x24040001, 0x03E00008, 0))
    assert not call_context(net, {"id": 1}, caller, "int callback(int);", "")


def test_call_hint_cache_changes_when_original_function_bytes_change():
    from decompnet.rom.psx_calls import call_context
    from decompnet.rom.symbols import Symbol, SymbolTable
    target = BASE + 0x100
    callee = {"id": 1, **row(target, words(0x03E00008, 0x00801021))}
    net = SimpleNamespace(cfg=lambda proj: {"platform": "psx"}, store=SimpleNamespace(all=lambda *args: [callee]),
                          symbols=lambda pid: SymbolTable([Symbol("callback", target, kind="func")]))
    caller = row(BASE, words(jal(target), 0x24040001, 0x03E00008, 0))
    assert not call_context(net, {"id": 1}, caller, "int callback(int);", "")
    callee["target"] = words(0x10800002, 0, 0x00A01021, 0x03E00008, 0)
    assert call_context(net, {"id": 1}, caller, "int callback(int);", "") == "int callback(int, int);"


def test_unconditional_control_flow_ignores_unreachable_data():
    assert incoming_arguments(words(0x10000003, 0x00E04021, 0xFFFFFFFF, 0, 0x03E00008, 0), BASE) == 8
    assert incoming_arguments(words(0x03E00008, 0, 0xFFFFFFFF), BASE) == 0


@pytest.mark.parametrize("code", [
    words(0xFFFFFFFF, 0x03E00008, 0),  # outside MIPS I
    words(0x48C4D000, 0x03E00008, 0),  # GTE / unknown ABI
    words(0x03200008, 0),  # indirect tail
    words(0x0320F809, 0, 0x03E00008, 0),  # indirect call
    words(0x08008000, 0),  # external tail
    words(0x10000020, 0),  # branch outside registered function
    words(0x10800000, 0, 0x03E00008, 0),  # branch into a delay slot
    words(0x03E00008, 0x03E00008),  # transfer in delay slot
    words(0x03E00008),  # missing delay slot
    words(0x24040000),  # unreviewed fallthrough
    words(0x00850000, 0x03E00008, 0),  # reserved nonzero rs in SLL
])
def test_unsupported_or_ambiguous_control_flow_has_no_summary(code):
    assert incoming_arguments(code, BASE) is None


def test_known_callee_requirements_propagate_through_multiple_wrappers():
    middle, terminal = BASE + 0x100, BASE + 0x200
    caller = words(jal(middle), 0x24040001, 0x03E00008, 0)
    wrapper = words(jal(terminal), 0, 0x03E00008, 0)
    # a1 is read only after the first conditional transfer.
    leaf = words(0x10800002, 0, 0x00A01021, 0x03E00008, 0)
    result = argument_summaries([row(BASE, caller), row(middle, wrapper), row(terminal, leaf)])
    assert result == {(BASE, "main"): 2, (middle, "main"): 3, (terminal, "main"): 3}


def test_recursive_callees_add_only_established_incoming_reads():
    second = BASE + 0x100
    first_code = words(jal(second), 0, 0x03E00008, 0)
    second_code = words(0x00C04021, jal(BASE), 0, 0x03E00008, 0)
    assert argument_summaries([row(BASE, first_code), row(second, second_code)]) == {
        (BASE, "main"): 4, (second, "main"): 4}


def test_overlays_resolve_own_unit_and_reject_ambiguous_cross_unit_calls():
    callee, local_caller = BASE + 0x1000, BASE + 0x100
    call = words(jal(callee), 0, 0x03E00008, 0)
    functions = [row(BASE, call), row(local_caller, call, "field"),
                 row(callee, words(0x03E00008, 0x00801021), "field"),
                 row(callee, words(0x03E00008, 0x00A01021), "battle")]
    result = argument_summaries(functions)
    assert (BASE, "main") not in result
    assert result[(local_caller, "field")] == 1
    unique = argument_summaries([row(BASE, call, "field"), row(callee, words(0x03E00008, 0x00C01021))])
    assert unique[(BASE, "field")] == 4


def test_duplicate_entries_and_interior_calls_need_reviewed_entry_facts():
    callee = BASE + 0x1000
    leaf = row(callee, words(0x00801021, 0x03E00008, 0))
    assert not argument_summaries([row(BASE, words(jal(callee), 0, 0x03E00008, 0)), leaf, leaf])
    result = argument_summaries([row(BASE, words(jal(callee + 4), 0, 0x03E00008, 0)), leaf])
    assert (BASE, "main") not in result and result[(callee, "main")] == 1


def test_analysis_limits_return_no_inferred_facts():
    code = words(0x03E00008, 0x00801021)
    assert incoming_arguments(code, BASE, max_words=1) is None
    assert incoming_arguments(code, BASE, max_steps=0) is None
    assert not argument_summaries([row(BASE, code)], max_total_words=1)
    assert not argument_summaries([row(BASE, code)], max_functions=0)
    assert not argument_summaries([row(BASE, code)], max_steps=0)
    assert incoming_arguments(code, BASE + 1) is None
    assert incoming_arguments(code + b"x", BASE) is None


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("language", ["c", "c++"])
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_console_recovers_transitive_forwarded_words_with_original_compiler(tmp_path, language, toolchain):
    from decompnet import compiler, elfobj, project, seeds
    from decompnet.app.engine import RomNetwork
    from decompnet.rom.psx_calls import call_context, entry_arguments
    from .test_overlays import _iso, _resident_exe

    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": language, "flags": ["-O2", "-G0"], "sandbox": "none"}})
    sources = {
        "caller": "extern int middle(int, int); int caller(int unused, int value) { return middle(1, value) + 1; }",
        "middle": "extern int terminal(int, int); int middle(int test, int value) { return terminal(test, value) + 3; }",
        "terminal": "int terminal(int test, int value) { if (test) return value + 7; return 0; }",
    }
    addresses = {"caller": 0x80010500, "middle": 0x80010600, "terminal": 0x80010700}
    functions = {}
    for name, source in sources.items():
        compiled = compiler.compile_source(cfg, "", source)
        assert compiled.ok, compiled.log
        original = elfobj.extract_function(compiled.obj, name)
        code = bytearray(original.code)
        for relocation in original.relocs:
            assert relocation.type == 4 and relocation.symbol in addresses
            value = struct.unpack_from("<I", code, relocation.offset)[0]
            struct.pack_into("<I", code, relocation.offset,
                             value & 0xFC000000 | addresses[relocation.symbol] >> 2 & 0x3FFFFFF)
        functions[name] = bytes(code)
    assert entry_arguments(functions["middle"]) == 0
    summaries = argument_summaries([row(addresses[name], code) for name, code in functions.items()])
    assert summaries[(addresses["middle"], "main")] == 3
    assert summaries[(addresses["caller"], "main")] == 2
    exe = bytearray(_resident_exe())
    exe[0x800:] = bytes(0x800)
    exe[0x800:0x820] = words(0x27BDFFE8, 0xAFBF0014, jal(addresses["caller"]), 0,
                            0x8FBF0014, 0, 0x03E00008, 0x27BD0018)
    for name, code in functions.items():
        offset = 0x800 + addresses[name] - BASE
        exe[offset:offset + len(code)] = code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, flags=["-O2", "-G0"], confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none", language=language))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], addresses["caller"])
    header = net._context(proj["id"], fn["unit"])["header"]
    asm = net._asm_text(fn, proj)
    draft = seeds.generate_from_asm(asm, fn["name"], toolchain, header, valid=True, language=language)
    assert draft
    broken = net._compile(proj, header, seeds.M2C_MACROS + "\n" + draft, fn)
    assert broken.ok, broken.log
    middle_name = net.store.one("SELECT name FROM functions WHERE project_id=? AND vram=?",
                                proj["id"], addresses["middle"])["name"]
    prototype = re.search(r"\b" + re.escape(middle_name) + r"\(([^()]*)\)\s*;", draft)
    # An omitted a1 may happen to survive a call unchanged, so even exact bytes
    # do not establish the C prototype. The original draft names only a0.
    assert prototype and prototype[1].strip() and "," not in prototype[1]
    hints = call_context(net, proj, fn, draft, header)
    assert hints and "int, int" in hints
    source = seeds.M2C_MACROS + "\n" + net._machine_draft(fn, proj, header, valid=True)
    checked = net._compile(proj, header, source, fn)
    assert checked.ok and net._evaluate(fn, proj, checked.obj)[1] is True
    agent, _ = net.local_agent("interprocedural-argument-test")
    assert net._autopilot_one(agent, proj, fn["id"], prepare_seed=False) == "match"
    assert net._function(fn["name"], slug)["status"] == "matched"
