"""ARM7 C/C++ compiler checks against original ARMv4T instruction vectors."""

import subprocess
import struct
import sys

import pytest

from decompnet import toolchains
from decompnet.forks.scratch_dsd import versions
from decompnet.rom.ds_arm7 import draft, verify
from decompnet.rom.dsprot import SIGNATURES
from decompnet.rom.nds_modules import NdsImage
from tests.test_ds_modules import fixture

needs_compiler = pytest.mark.skipif(
    not versions() or (sys.platform != "win32" and not toolchains.installed("wibo")),
    reason="needs installed CodeWarrior for DS and wibo on non-Windows hosts")


@needs_compiler
@pytest.mark.parametrize("mode,address,size", [("arm", 0x02380000, 8), ("thumb", 0x02380010, 4)])
@pytest.mark.parametrize("language", ["c", "c++"])
def test_c_and_genuine_cpp_compile_to_arm7_bytes(mode, address, size, language):
    source = "int recovered(void) { return 7; }"
    if language == "c++":
        source = 'template<int N> struct Value { enum { value = N }; };\nextern "C" int recovered(void) { return Value<7>::value; }'
    result = verify(NdsImage(bytes(fixture())), "arm7", address, size, mode, source, "recovered", language=language)
    assert result["exact"], result
    assert result["cpu"] == "arm7tdmi" and not result["whole_rom_verified"]


@needs_compiler
@pytest.mark.parametrize("source,symbol,reason", [
    ("int probe(void) { return 8; }", "probe", "bytes"),
    ("int probe(void) { return 7; }", "missing", "no function"),
    ("extern int other(int); int probe(int x) { return other(x); }", "probe", "relocations"),
    ("#pragma thumb on\nint probe(void) { return 7; }", "probe", "compilation failed"),
    ("asm int probe(void) { bx lr }", "probe", "compilation failed"),
])
def test_no_false_matches(source, symbol, reason):
    result = verify(NdsImage(bytes(fixture())), "arm7", 0x02380000, 8, "arm", source, symbol)
    assert not result["exact"] and reason in result["reason"], result


@pytest.mark.parametrize("module,address,size,mode,reason", [
    ("arm9", 0x02000000, 8, "arm", "ARM7 module"),
    ("arm7", 0x0237FFFC, 8, "arm", "outside initialized"),
    ("arm7", 0x023800FC, 8, "arm", "outside initialized"),
    ("arm7", 0x02380001, 8, "thumb", "alignment"),
    ("arm7", 0x02380000, 6, "arm", "alignment"),
])
def test_bad_targets_fail_before_compiler(module, address, size, mode, reason, monkeypatch):
    monkeypatch.setattr(toolchains, "require", lambda *_: pytest.fail("compiler should not be needed"))
    with pytest.raises(ValueError, match=reason):
        verify(NdsImage(bytes(fixture())), module, address, size, mode, "", "probe")


def test_protected_module_fails_before_compiler(monkeypatch):
    data = fixture()
    data[0x5020:0x5038] = SIGNATURES["1.00"]
    monkeypatch.setattr(toolchains, "require", lambda *_: pytest.fail("compiler should not be needed"))
    with pytest.raises(ValueError, match="DS Protect"):
        verify(NdsImage(bytes(data)), "arm7", 0x02380000, 8, "arm", "", "probe")


def test_signed_arm7_overlay_fails_before_compiler(monkeypatch):
    data = fixture()
    struct.pack_into("<I", data, 0x35C, 0x2000000)
    monkeypatch.setattr(toolchains, "require", lambda *_: pytest.fail("compiler should not be needed"))
    with pytest.raises(ValueError, match="signed ARM7"):
        verify(NdsImage(bytes(data)), "arm7:ov41", 0x02300000, 8, "arm", "", "probe")


def test_cli_inspection_leaves_rom_unchanged(tmp_path):
    rom = tmp_path / "original.nds"
    data = bytes(fixture())
    rom.write_bytes(data)
    result = subprocess.run([sys.executable, "tools/ds_arm7.py", str(rom), "inspect"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"bios_required_for_inspection": false' in result.stdout
    assert rom.read_bytes() == data


@needs_compiler
@pytest.mark.skipif(not toolchains.installed("m2c"), reason="needs m2c")
@pytest.mark.parametrize("mode,address,size", [("arm", 0x02380000, 8), ("thumb", 0x02380010, 4)])
def test_draft_then_compile_recovers_original_leaf(mode, address, size):
    image = NdsImage(bytes(fixture()))
    source = draft(image, "arm7", address, size, mode, "recovered")
    assert "return 7" in source
    assert verify(image, "arm7", address, size, mode, source, "recovered")["exact"]


@pytest.mark.parametrize("words,reason", [
    ("000000eb1eff2fe1", "calls"),
    ("00009fe51eff2fe1", "PC-relative"),
    ("000000ea1eff2fe1", "outside function"),
    ("0700a0e300000000", "ending in bx lr"),
])
def test_drafts_reject_missing_link_context(words, reason, monkeypatch):
    from decompnet import seeds

    data = fixture()
    data[0x5000:0x5008] = bytes.fromhex(words)
    monkeypatch.setattr(seeds, "run_m2c", lambda *a, **k: pytest.fail("must reject before m2c"))
    with pytest.raises(ValueError, match=reason):
        draft(NdsImage(bytes(data)), "arm7", 0x02380000, 8, "arm", "recovered")
