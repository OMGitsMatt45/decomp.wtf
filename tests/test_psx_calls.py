"""Call signatures must retain untouched incoming argument registers."""

import os
import struct
from types import SimpleNamespace

import pytest

from decompnet import compiler, elfobj, project, seeds
from decompnet.app.engine import RomNetwork
from decompnet.rom.psx_calls import call_context, call_sites, entry_arguments
from decompnet.rom.symbols import Symbol, SymbolTable
from .test_overlays import _iso, _resident_exe


def words(*values):
    return struct.pack(f"<{len(values)}I", *values)


def test_entry_argument_reads_include_delay_slots_but_not_overwritten_inputs():
    assert entry_arguments(words(0x03E00008, 0x00E01021)) == 8  # return a3
    assert entry_arguments(words(0x24040001, 0x03E00008, 0x00801021)) == 0
    assert entry_arguments(words(0x48C4D000, 0x03E00008, 0)) is None  # GTE control


def test_direct_calls_count_delay_slot_arguments_and_reset_at_control_flow():
    # A local a0 write before the branch does not establish this call's args.
    code = words(0x24040007, 0x10800001, 0, 0x0C004180, 0x24050000, 0x03E00008, 0)
    assert call_sites(code, 0x80010000) == {0x80010600: [2]}
    assert not call_sites(words(0x0C004180), 0x80010000)  # missing delay slot


def model(callees=None):
    caller = {"target": words(0x0C004180, 0x24050000, 0x03E00008, 0), "vram": 0x80010500, "unit": "main"}
    callees = callees if callees is not None else [{"target": words(0xAC850000, 0x03E00008, 0), "unit": "main"}]
    net = SimpleNamespace(cfg=lambda proj: {"platform": "psx"},
                          symbols=lambda pid: SymbolTable([Symbol("callback", 0x80010600, kind="func")]),
                          store=SimpleNamespace(all=lambda *args: callees))
    return net, {"id": 1}, caller


def test_inferred_call_prototype_places_explicit_a1_after_forwarded_a0():
    net, proj, caller = model()
    assert call_context(net, proj, caller, "M2C_UNK callback(u8);", "") == "int callback(int, unsigned char);"


@pytest.mark.parametrize("draft,context", [
    ("int callback(int);", "int callback(void *p, int value);"),
    ("int callback(double);", ""),
    ("long long callback(int);", ""),
])
def test_reviewed_or_wide_signatures_are_not_rewritten(draft, context):
    net, proj, caller = model()
    assert not call_context(net, proj, caller, draft, context)


def test_unknown_or_ambiguous_callee_does_not_establish_forwarded_arguments():
    for callees in ([], [{"target": words(0x48C4D000, 0x03E00008, 0), "unit": "main"}],
                    [{"target": words(0xAC850000, 0x03E00008, 0), "unit": unit} for unit in ("overlay1", "overlay2")]):
        net, proj, caller = model(callees)
        assert not call_context(net, proj, caller, "int callback(int);", "")


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 compilers and m2c")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_original_call_abi_recovers_when_callee_input_is_forwarded(tmp_path, toolchain):
    cfg = project.compiler_config(tmp_path, {"kind": "rom", "platform": "psx", "compiler": {
        "toolchain": toolchain, "language": "c++", "sandbox": "none"}})
    caller = compiler.compile_source(cfg, "", "extern void callee(int *, int); void caller(int *p) { if (p[7] & 64) callee(p, 0); }")
    callee = compiler.compile_source(cfg, "", "void callee(int *p, int value) { p[0] = value; }")
    assert caller.ok and callee.ok, caller.log + callee.log
    target = elfobj.extract_function(caller.obj, "caller")
    body = bytearray(target.code)
    assert target.relocs and all(r.type == 4 and r.symbol == "callee" for r in target.relocs)
    for relocation in target.relocs:
        value = struct.unpack_from("<I", body, relocation.offset)[0]
        struct.pack_into("<I", body, relocation.offset, value & 0xFC000000 | 0x80010600 >> 2 & 0x3FFFFFF)
    callee_code = elfobj.extract_function(callee.obj, "callee")
    assert not callee_code.relocs
    exe = bytearray(_resident_exe())
    struct.pack_into("<I", exe, 0x808, 0x0C000000 | (0x80010500 >> 2 & 0x3FFFFFF))
    exe[0xD00:0xD00 + len(body)] = body
    exe[0xE00:0xE00 + len(callee_code.code)] = callee_code.code
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": exe})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(image, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    proj = net.project_row(slug)
    fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], 0x80010500)
    header = net._context(proj["id"], fn["unit"])["header"]
    asm = net._asm_text(fn, proj)
    draft = seeds.generate_from_asm(asm, fn["name"], toolchain, header, valid=True, language="c++")
    assert draft
    broken = net._compile(proj, header, seeds.M2C_MACROS + "\n" + draft, fn)
    assert broken.ok and net._evaluate(fn, proj, broken.obj)[1] is False
    hints = call_context(net, proj, fn, draft, header)
    assert hints and "int, int" in hints
    repaired = seeds.generate_from_asm(asm, fn["name"], toolchain, header + "\n" + hints, valid=True, language="c++")
    assert repaired
    source = seeds.M2C_MACROS + "\n" + hints + "\n" + repaired
    checked = net._compile(proj, header, source, fn)
    assert checked.ok and net._evaluate(fn, proj, checked.obj)[1] is True
    agent, _ = net.local_agent("call-signature-test")
    assert net._autopilot_one(agent, proj, fn["id"], prepare_seed=False) == "match"
    assert net._function(fn["name"], slug)["status"] == "matched"
