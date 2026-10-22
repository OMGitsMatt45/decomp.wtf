"""A real source-size change relocates calls and data pointers in a bounded cartridge."""

import hashlib
import json
from pathlib import Path
import shutil
import re
import struct
import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.rom.n64_crc import calculate, identify
from .test_n64code import _code


def fixture():
    image = bytearray(0x200000)
    image[:16] = struct.pack(">4I", 0x80371240, 0xF, 0x80000400, 0x1449)
    image[0x20:0x34] = b"SHIFTABLE N64 TEST".ljust(20, b" ")
    code = _code(0x80000400, 40)
    image[0x1000:0x1000 + len(code)] = code
    # A pinned pointer table and integer follow 768 bytes of explicitly unused
    # zero reserve. The pointer to function 2 must change when function 1 grows.
    struct.pack_into(">4I", image, 0x1800, 0x80000420, 7, 3, 4)
    struct.pack_into(">2I", image, 0x10, *calculate(image, 6102))
    layout = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": [
        {"name": "main", "rom_start": 0x1000, "rom_end": 0x1810, "vram": 0x80000400,
         "text_end": len(code),
         "sections": [{"offset": 0, "type": "code"}, {"offset": 0x800, "type": "data"}]}]}
    return bytes(image), layout


@pytest.mark.parametrize("toolchain,frontend", [("gcc-2.7.2-kmc", ""), ("ido-5.3", "edg"),
                                                ("ido-5.3", "cfront"), ("ido-7.1", "edg")])
def test_shiftable_source_growth_relocates_calls_and_function_pointers(tmp_path, toolchain, frontend):
    if toolchains.installed(toolchain) is None or toolchains.installed("binutils-mips") is None:
        pytest.skip("requires the pinned native N64 compilers")
    original, layout = fixture()
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    slug = net.import_rom(original, reviewed_layout=layout, toolchain=toolchain, confirmed=True, log=lambda *_: None)
    project = net.project_row(slug)
    config = net.cfg(project)
    config["compiler"].update(sandbox="none", language="c++", **({"cpp_frontend": frontend} if frontend else {}))
    with net.store.tx() as db:
        db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(config), project["id"]))
    result = net.export_rom(slug, format="shiftable", log=lambda *_: None)
    assert result["identical"], result["log"]
    assert result["shiftable"]["ready"], result["shiftable"]["detail"]
    tree = Path(result["path"])
    metadata = json.loads((tree / "build.json").read_text())
    functions = sorted(metadata["functions"], key=lambda f: f["vram"])
    first, second = functions[:2]
    values = metadata["module_symbols"]["main"]
    datum = next(name for name, address in values.items() if address == 0x80000C00)
    source_dir = tree / "src/main"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / (first["name"] + ".cpp")).write_text(
        f'extern "C" int {second["name"]}(int);\nextern "C" int {first["name"]}(int value) {{\n'
        '  volatile int a[8];\n' + "".join(f"  a[{i}] = value + {i};\n" for i in range(8)) +
        f'  return {second["name"]}(value)' + "".join(f" + a[{i}]" for i in range(8)) + ';\n}\n', encoding="utf-8", newline='\r\n')
    (source_dir / (second["name"] + ".cpp")).write_text(
        f'extern "C" int {datum}[];\nextern "C" int {second["name"]}(int value) {{ return {datum}[1] + value; }}\n', encoding="utf-8", newline='\r\n')
    def run(*args):
        return subprocess.run([sys.executable, "build.py", *args], cwd=tree, capture_output=True, text=True)
    modified = run("mod")
    assert modified.returncode == 0, modified.stdout + modified.stderr
    changed = (tree / "build/mod.z64").read_bytes()
    report = json.loads((tree / "build/shiftable-result.json").read_text())
    assert changed != original and len(changed) == len(original)
    assert report["functions"][first["name"]] == first["vram"]
    assert report["functions"][second["name"]] > second["vram"]
    assert 0 < report["used_growth"] <= report["available_growth"] == 768
    assert {2, 4, 5, 6} <= {r["type"] for r in report["relocations"]}
    assert int.from_bytes(changed[0x1800:0x1804], "big") == report["functions"][second["name"]]
    assert changed[0x1804:0x1810] == original[0x1804:0x1810]
    assert identify(changed) == report["cic"] == 6102
    assert struct.unpack_from(">2I", changed, 0x10) == calculate(changed, 6102)
    with (tree / "build/mod.elf").open("rb") as stream:
        elf = ELFFile(stream)
        symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
    assert symbols[datum] == 0x80000C00
    assert symbols[second["name"]] == report["functions"][second["name"]]
    start = first["rom"]
    stop = start + report["functions"][second["name"]] - first["vram"]
    calls = [((first["vram"] + at - start + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
             for at in range(start, stop, 4) if (word := int.from_bytes(changed[at:at + 4], 'big')) >> 26 == 3]
    assert symbols[second["name"]] in calls, 'the actual linked JAL must call the moved function'
    # Normal matching remains a separate, strict check after source changes.
    matching = run()
    assert matching.returncode != 0
    # A clean export has to regenerate its original disassembly and all build
    # products, then compile the edited source into the same modified cartridge.
    for generated in ("asm", "assets", "build"):
        shutil.rmtree(tree / generated)
    clean = run("mod")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert (tree / "build/mod.z64").read_bytes() == changed
    # Exceeding the size budget fails and removes a previous successful mod.
    source = source_dir / (first["name"] + ".cpp")
    source.write_text(source.read_text().replace('volatile int a[8];', 'volatile int a[512];')
        .replace(f'return {second["name"]}(value)', f'return {second["name"]}(value)' +
                 ''.join(f' + a[{i}]' for i in range(512))), encoding="utf-8")
    failed = run("mod")
    assert failed.returncode != 0 and "reserve" in failed.stderr
    assert not (tree / "build/mod.z64").exists()


@pytest.mark.parametrize('hazard', ['jump', 'data pointer', 'code address'])
def test_inventory_rejects_fixed_references_without_relocations(tmp_path, hazard):
    original, layout = fixture()
    if hazard == 'code address':
        original = bytearray(original)
        struct.pack_into('>2I', original, 0x1008, 0x3C088000, 0x35080420)
        original = bytes(original)
        layout['sha256'] = hashlib.sha256(original).hexdigest()
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    tree = Path(net.export_rom(slug, format='shiftable', log=lambda *_: None)['path'])
    metadata = json.loads((tree / 'build.json').read_text())
    first = min(metadata['functions'], key=lambda f: f['vram'])
    # Keep the original bytes but remove the assembler's symbolic fixups. The
    # exact baseline therefore still passes, while moving these values is unsafe.
    if hazard == 'data pointer':
        path = next((tree / 'asm/data').glob('*.data.s'))
        text = path.read_text()
        second = sorted(metadata['functions'], key=lambda f: f['vram'])[1]
        assert second['name'] in text
        text = text.replace(second['name'], '0x80000420')
    else:
        path = tree / first['asm']
        text = path.read_text()
        offsets = ('1008',) if hazard == 'jump' else ('1008', '100C')
        for at in offsets:
            text, count = re.subn(r'(/\* ' + at + r' [0-9A-F]+ ([0-9A-F]{8}) \*/)\s+[^\n]+',
                                 lambda m: m[1] + ' .word 0x' + m[2], text)
            assert count == 1
    path.write_text(text)
    run = subprocess.run([sys.executable, 'build.py', 'inventory', '--cic', '6102'], cwd=tree,
                         capture_output=True, text=True)
    assert run.returncode != 0 and 'unrelocated ' + hazard in run.stderr, run.stdout + run.stderr
    assert not (tree / 'build/mod.z64').exists()
    assert json.loads((tree / 'build/relocations.json').read_text())['hazards']
