"""Larger C++ bodies, helpers and loaded data retain original function identity."""

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from elftools.elf.elffile import ELFFile
import pytest

from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from .test_psx_set import fixtures
from decompnet.rom import psx_space

@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
@pytest.mark.parametrize("toolchain", ["gcc-2.7.2-psx", "gcc-2.8.1-psx"])
def test_larger_cpp_helpers_initialized_data_bss_and_function_pointer_keep_original_entry(tmp_path, capsys, toolchain):
    original = fixtures(tmp_path, toolchain, 4)[0]
    from .test_overlays import _iso
    from decompnet.rom.psx import _Disc
    program = bytearray(_Disc(original).find("GAME.EXE"))
    program += bytes(0x10000)
    program[0x1C:0x20] = (len(program) - 0x800).to_bytes(4, "little")
    original = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\GAME.EXE;1\n", "GAME.EXE": bytes(program)})
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects with spaces")
    slug = net.import_rom(original, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    net._update_cfg(slug, lambda c: c["compiler"].update(sandbox="none"))
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported["identical"], exported
    root = Path(exported["path"])
    meta = json.loads((root / "build.json").read_text())
    fn = next(f for f in meta["functions"] if f["vram"] == 0x80010504)
    fn["compiler"] = {"flags": ["-O0", "-G0"]}
    (root / "build.json").write_text(json.dumps(meta))
    source = root / f'src/{fn["seg"]}/{fn["name"]}.cpp'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f'''extern "C" {{
int {fn["name"]}(int);
int initialized = 11;
int uninitialized[4];
int (*identity)(int) = {fn["name"]};
static int helper(int x) {{ uninitialized[1] = x; return initialized + x; }}
int (*get_identity(void))(int) {{ return {fn["name"]}; }}
int {fn["name"]}(int x) {{ return helper(x) + 1; }}
}}\n''')
    assert main(["psx", "reserve", str(root), "--module", "main", "--start", "0x80020600", "--size", "0x200"]) == 0
    declaration = json.loads(capsys.readouterr().out)
    assert declaration["modules"][0]["start"] == 0x80020600

    def run(*args):
        return subprocess.run([sys.executable, "build.py", *args], cwd=root, capture_output=True, text=True, timeout=120)

    process = run("mod")
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads((root / "build/psx-mod-result.json").read_text())
    assert report["mode"] == "reviewed-space" and report["changed_functions"] == [fn["name"]]
    space = report["spaces"][0]
    assert 8 < space["used"] <= space["capacity"] == 512
    image = (root / "build/psx-mod/program.exe").read_bytes()
    stub = int.from_bytes(image[fn["rom"]:fn["rom"] + 4], "little")
    assert stub >> 26 == 2 and image[fn["rom"] + 4:fn["rom"] + 8] == bytes(4)
    body = ((fn["vram"] + 4) & 0xF0000000) | ((stub & 0x3FFFFFF) << 2)
    assert 0x80020600 <= body < 0x80020800 and body == space["bodies"][0]["body"]
    with (root / "build/psx-mod/objects/main-arena.elf").open("rb") as stream:
        elf = ELFFile(stream)
        symbols = {s.name: s for s in elf.get_section_by_name(".symtab").iter_symbols()}
        assert symbols[fn["name"]]["st_shndx"] == "SHN_ABS" and symbols[fn["name"]]["st_value"] == fn["vram"]
        arena = elf.get_section_by_name(".arena")
        for name, value in (("initialized", (11).to_bytes(4, "little")), ("uninitialized", bytes(16)),
                            ("identity", fn["vram"].to_bytes(4, "little"))):
            at = symbols[name]["st_value"] - arena["sh_addr"]
            assert arena.data()[at:at + len(value)] == value
        helpers = [s for n, s in symbols.items() if n.startswith("helper") and isinstance(s["st_shndx"], int)]
        assert helpers and all(0x80020600 <= s["st_value"] < 0x80020800 for s in helpers)
        state_address = symbols["uninitialized"]["st_value"]
        get_identity = symbols["get_identity"]["st_value"]
    # Execute the actual linked MIPS code, including the entry jump, call,
    # stack frame, initialized global and newly allocated zero storage.
    import unicorn
    from unicorn import mips_const as mips
    cpu = unicorn.Uc(unicorn.UC_ARCH_MIPS, unicorn.UC_MODE_MIPS32 | unicorn.UC_MODE_LITTLE_ENDIAN)
    cpu.mem_map(0, 2 << 20)
    cpu.mem_write(0x10000, image[0x800:])
    for value in (5, -7):
        cpu.reg_write(mips.UC_MIPS_REG_A0, value & 0xFFFFFFFF)
        cpu.reg_write(mips.UC_MIPS_REG_SP, 0x801FF000)
        cpu.reg_write(mips.UC_MIPS_REG_RA, 0x801FFF00)
        cpu.emu_start(fn["vram"], 0x801FFF00, count=1000)
        assert cpu.reg_read(mips.UC_MIPS_REG_PC) == 0x801FFF00
        assert cpu.reg_read(mips.UC_MIPS_REG_V0) == (value + 12) & 0xFFFFFFFF
        assert int.from_bytes(cpu.mem_read((state_address & 0x1FFFFFFF) + 4, 4), "little") == value & 0xFFFFFFFF
    cpu.reg_write(mips.UC_MIPS_REG_SP, 0x801FF000)
    cpu.reg_write(mips.UC_MIPS_REG_RA, 0x801FFF00)
    cpu.emu_start(get_identity, 0x801FFF00, count=1000)
    assert cpu.reg_read(mips.UC_MIPS_REG_PC) == 0x801FFF00 and cpu.reg_read(mips.UC_MIPS_REG_V0) == fn["vram"]
    assert run().returncode != 0
    for name in ("asm", "assets", "build"):
        shutil.rmtree(root / name, ignore_errors=True)
    (root / meta["image"]).unlink()
    assert run("mod").returncode == 0
    assert (root / "build/psx-mod/program.exe").read_bytes() == image
    original_declaration = (root / "psx-mod-space.json").read_bytes()
    assert main(["psx", "reserve", str(root), "--module", "main", "--start", "0x80010500", "--size", "0x20"]) == 1
    assert (root / "psx-mod-space.json").read_bytes() == original_declaration
    assert main(["psx", "reserve", str(root), "--module", "main", "--start", "0x80020600", "--size", "16"]) == 0
    process = run("mod")
    assert process.returncode != 0 and "exceeds its reviewed mod space" in process.stdout + process.stderr
    assert not (root / "build/psx-mod-result.json").exists() and not (root / "build/psx-mod").exists()


@pytest.mark.parametrize("error", ["hash", "nonzero", "footer", "function", "alignment", "cleared_bss", "loader_fixup"])
def test_mod_space_is_bound_to_original_loaded_zero_bytes(error):
    image = bytearray(0x1200)
    image[:8] = b"PS-X EXE"
    image[0x1C:0x20] = (0x800).to_bytes(4, "little")
    meta = {"segments": [{"name": "main", "kind": "code", "start": 0x800, "end": len(image), "vram": 0x80010000}], "functions": []}
    item = {"module": "main", "start": 0x80010600, "size": 0x100}
    if error == "nonzero":
        image[0xE10] = 1
    elif error == "footer":
        item["start"] = 0x80010900
    elif error == "function":
        meta["functions"].append({"seg": "main", "vram": 0x80010640})
    elif error == "alignment":
        item["start"] += 4
    elif error == "cleared_bss":
        image[0x28:0x30] = (0x80010600).to_bytes(4, "little") + (0x100).to_bytes(4, "little")
    elif error == "loader_fixup":
        meta["disc"] = {"layout": {"maps": [{"segment": "main", "analysis_offset": 0, "size": len(image), "code_at": 0x800,
                                              "relocations": [{"offset": 0xE04}]}]}}
    declaration = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": [item]}
    if error == "hash":
        declaration["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        psx_space.validate(meta, image, declaration)


@pytest.mark.skipif(os.environ.get("DECOMP_TEST_PSX_CPP") != "1", reason="needs pinned PS1 tools")
def test_shared_cpp_growth_builds_both_discs_and_second_disc_exhaustion_clears_aggregate(tmp_path):
    from .test_psx_set import imported
    net, slugs, _ = imported(tmp_path, recover=True)
    net.set_psx_disc_set(slugs[0], slugs, "Grown two-disc project")
    result = net.export_rom(slugs[0], log=lambda *_: None)
    assert result["identical"], result
    root = Path(result["path"])
    child = root / "discs/disc-1"
    fn = next(f for f in json.loads((child / "build.json").read_text())["functions"] if f["vram"] == 0x80010500)
    source = next((root / "shared/src").glob("*.cpp"))
    source.write_text(f'extern "C" {{ volatile int new_counter = 3; '
                      f'int {fn["name"]}(int x) {{ return x + new_counter; }} }}\n')
    for number in (1, 2):
        assert main(["psx", "reserve", str(root / f"discs/disc-{number}"), "--module", "main", "--start", "0x80010600", "--size", "0x200"]) == 0
    assert main(["psx", "build", str(root), "--mod"]) == 0
    report = json.loads((root / "build/mod/disc-set-result.json").read_text())
    assert report["mode"] == "reviewed-space" and len(report["discs"]) == 2
    assert all(len(d["spaces"]) == len(d["changed_functions"]) == 1 for d in report["discs"])
    assert main(["psx", "reserve", str(root / "discs/disc-2"), "--module", "main", "--start", "0x80010600", "--size", "16"]) == 0
    assert main(["psx", "build", str(root), "--mod"]) == 1
    assert not (root / "build/mod").exists()
