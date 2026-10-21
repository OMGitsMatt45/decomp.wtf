"""Real assembly-only rebuilds need no period C compiler or commercial inputs."""

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom import overlays as disc_overlays
from .test_overlays import _iso, _overlay


def test_gba_literal_loads_across_exported_pieces_need_no_c_compiler(tmp_path, monkeypatch):
    """A literal pool in a neighbouring function must resolve during assembly."""
    from decompnet.rom import gba

    if toolchains.installed("binutils-arm") is None:
        pytest.skip("needs ARM binutils")
    tools = toolchains.require("binutils-arm") / "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    assembly = '''.syntax unified
.macro thumb_func_start name
.align 2, 0
.global \\name
.thumb
.thumb_func
.type \\name, %function
.endm
@ End embedded Luvdis macros
.text
.thumb
.space 0x120
thumb_func_start sub_08000120
sub_08000120:
ldr r0, _08000134
bx lr
.space 12
thumb_func_start sub_08000130
sub_08000130:
bx lr
.byte 0, 0
_08000134: .4byte 0x03000000
'''
    (tmp_path / "original.s").write_text(assembly)
    for command in ([str(tools / f"arm-none-eabi-as{suffix}"), "-mcpu=arm7tdmi", "-o", "original.o", "original.s"],
                    [str(tools / f"arm-none-eabi-ld{suffix}"), "-Ttext=0x08000000", "-o", "original.elf", "original.o"],
                    [str(tools / f"arm-none-eabi-objcopy{suffix}"), "-O", "binary", "original.elf", "baserom.gba"]):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    import hashlib
    manifest = {"image": "baserom.gba", "sha1": hashlib.sha1((tmp_path / "baserom.gba").read_bytes()).hexdigest(),
                "base": 0x08000000, "output": "build/game.gba", "compiler": {"language": "c++", "toolchain": "agbcc"},
                "symbols": {}, "functions": [{"name": f"sub_{addr:08X}", "addr": addr, "size": 4, "thumb": True}
                                              for addr in (0x08000120, 0x08000130)]}
    (tmp_path / "build.json").write_text(json.dumps(manifest))
    (tmp_path / "functions.cfg").write_text("")
    script = tmp_path / "build.py"
    shutil.copyfile(Path(gba.__file__).with_name("export_gba_build.py"), script)
    monkeypatch.setattr(gba, "_luvdis", lambda *_: (assembly, [0x08000120, 0x08000130]))
    builder = runpy.run_path(str(script))
    # Assembly-only exports must never ask for agbcc or a C/C++ configuration.
    monkeypatch.setitem(builder["build_objects"].__globals__, "build_config", lambda: pytest.fail("no C source exists"))
    assert builder["build"]()
    assert (tmp_path / "build/game.gba").read_bytes() == (tmp_path / "baserom.gba").read_bytes()


@pytest.fixture
def mips_tools():
    if toolchains.installed("binutils-mips") is None:
        pytest.skip("needs MIPS binutils")
    return toolchains.binary("binutils-mips").parent


def _elf(root: Path, tools: Path, count=40, base=0x00100000, resident=None):
    root.mkdir()
    (root / "code.bin").write_bytes(_overlay(base + 0x10, count))
    (root / "start.s").write_text('''
.set noreorder
.text
.globl _start
.type _start, @function
_start:
    lui $8, %hi(small_bss)
    addiu $8, $8, %lo(small_bss)
    lui $9, %hi(large_bss)
    addiu $9, $9, %lo(large_bss)
.incbin "code.bin"
.section .lit4,"a"
.word 0x12345678
.section .sdata,"aw"
.byte 0x12, 0x34, 0
.section .sbss,"aw",@nobits
.globl small_bss
small_bss: .space 12
.section .bss,"aw",@nobits
.globl large_bss
large_bss: .space 32
''')
    (root / "layout.ld").write_text('''ENTRY(_start)
SECTIONS {
 .text 0x00100000 : { *(.text) }
 .lit4 0x00101000 : { *(.lit4) }
 .sdata 0x00101010 : { *(.sdata) }
 .sbss 0x00101080 (NOLOAD) : { *(.sbss) }
 .bss 0x00101100 (NOLOAD) : { *(.bss) }
 /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) }
}
''')
    script = (root / "layout.ld").read_text()
    for offset in (0, 0x1000, 0x1010, 0x1080, 0x1100):
        script = script.replace(f"0x{0x00100000 + offset:08X}", f"0x{base + offset:08X}")
    if resident is not None:
        script += f"\nresident_bss = 0x{resident:X};\n"
        source = (root / "start.s").read_text().replace("%hi(large_bss)", "%hi(resident_bss)").replace("%lo(large_bss)", "%lo(resident_bss)")
        (root / "start.s").write_text(source)
    (root / "layout.ld").write_text(script)
    for command in ([str(tools / "mips-ps2-decompals-as"), "-EL", "-march=r5900", "-mabi=eabi", "-o", "start.o", "start.s"],
                    [str(tools / "mips-ps2-decompals-ld"), "-EL", "-T", "layout.ld", "-o", "game.elf", "start.o"]):
        subprocess.run(command, cwd=root, capture_output=True, check=True, timeout=30)
    return root / "game.elf"


@pytest.mark.parametrize("mode", ["standalone", "shared-main", "shared-other"])
def test_ps2_sections_zero_tail_and_exclusive_programs_rebuild(tmp_path, mips_tools, mode):
    main = _elf(tmp_path / "main", mips_tools)
    overlays = mode != "standalone"
    base = 0x00180000 if mode == "shared-other" else 0x00100000
    if overlays:
        resident = 0x00101080 if mode == "shared-other" else None
        battle = _elf(tmp_path / "battle", mips_tools, 35, base, resident)
        field = _elf(tmp_path / "field", mips_tools, 30, base, resident)
        disc = tmp_path / "game.iso"
        disc.write_bytes(_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SCUS_999.99;1\r\n", "SCUS_999.99": main.read_bytes(),
                               "BATTLE.ELF": battle.read_bytes(), "FIELD.ELF": field.read_bytes()}))
        source = disc
    else:
        source = main
    work = tmp_path / "app"
    work.mkdir()
    net = RomNetwork(work / "app.db", work)
    slug = net.import_rom(source, confirmed=True, log=lambda *_: None)
    if overlays:
        proj = net.project_row(slug)
        address = base + 0x10 + 29 * 32 + 8
        fn = net.store.one("SELECT * FROM functions WHERE project_id=? AND unit='ovl_field' AND vram<=? AND vram+size>?",
                           proj["id"], address, address)
        assert fn is not None
        code = disc_overlays._elf_segments(field.read_bytes())[0][1]
        expected = code[address - base:address - base + 4]
        assert net.reader(proj, fn)(address, 4) == expected
        assert net.reader(proj)(address, 4) != expected
    result = net.export_rom(slug, log=lambda *_: None)
    assert result["identical"] and result["matched"] == 0, result["log"]
    tree = Path(result["path"])
    assert (tree / "build/game-ps2.elf").read_bytes() == main.read_bytes()
    config = json.loads((tree / "build.json").read_text())
    original = (tree / config["image"]).read_bytes()
    assert (tree / config["output"]).read_bytes() == original
    if overlays:
        assert {s["name"] for s in config["segments"]} >= {"ovl_battle", "ovl_field"}
        assert len(list((tree / "build/modules").glob("*.bin"))) == 3
    for directory in ("asm", "assets", "build"):
        shutil.rmtree(tree / directory, ignore_errors=True)
    rebuilt = subprocess.run([sys.executable, "build.py"], cwd=tree, capture_output=True, text=True, timeout=60)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (tree / config["output"]).read_bytes() == original
    assert (tree / "build/game-ps2.elf").read_bytes() == main.read_bytes()
