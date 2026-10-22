"""ARM7 calls and initialized data enter a strict ROM build from real C/C++ objects."""

import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from decompnet import toolchains
from decompnet.app.engine import RomNetwork
from decompnet.network import NetworkError
from decompnet.forks.project import ForkProject
from .test_ds_encrypted import encrypted

pytestmark = pytest.mark.skipif(
    any(toolchains.installed(t) is None for t in ("mwccarm", "dsd", "objdiff-cli", "arm-gnu")) or
    (sys.platform != "win32" and not toolchains.installed("wibo")), reason="needs native DS tools")


@pytest.fixture(params=["arm", "thumb"])
def arm7_calls(encrypted, tmp_path, request):
    original, bios = encrypted
    seed = tmp_path / "seed"
    shutil.copytree(original.parent / "seed", seed)
    base = 0x02380000
    code = bytearray(0xC0)
    # Original ARMv4T fixture: increment the shared counter by calling recovered()
    # and storing its result. No SDK code, firmware or Nintendo key table.
    if request.param == "arm":
        struct.pack_into("<7I", code, 0, 0xE59F4010, 0xE3A00000, 0xEB00000C, 0xE5840000,
                         0xEAFFFFFC, 0xE1A00000, 0x0238FFF0)
        struct.pack_into("<8I", code, 0x40, 0xE92D4008, 0xEB00000D, 0xE59F100C, 0xE5911000,
                         0xE0810000, 0xE8BD4008, 0xE12FFF1E, base + 0xA0)
        struct.pack_into("<2I", code, 0x80, 0xE2800001, 0xE12FFF1E)
    else:
        # An ARMv4T BX enters Thumb; Thumb BL resolves to the other Thumb function.
        struct.pack_into("<10I", code, 0, 0xE59F4018, 0xE3A00000, 0xE59F1014, 0xE1A0E00F,
                         0xE12FFF11, 0xE5840000, 0xEAFFFFFA, 0xE1A00000, 0x0238FFF0, base + 0x41)
        struct.pack_into("<10H", code, 0x40, 0xB508, 0xF000, 0xF81D, 0x4903, 0x6809,
                         0x1808, 0xBC08, 0xBC08, 0x4718, 0x46C0)
        struct.pack_into("<I", code, 0x54, base + 0xA0)
        struct.pack_into("<2H", code, 0x80, 0x3001, 0x4770)
    struct.pack_into("<I", code, 0xA0, 7)
    (seed / "arm7/arm7.bin").write_bytes(code)
    game = tmp_path / "arm7-calls.nds"
    subprocess.run([str(toolchains.binary("dsd")), "rom", "build", "--config", str(seed / "config.yaml"),
                    "--rom", str(game), "--arm7-bios", str(bios)], check=True, capture_output=True)
    return game, bios, request.param


@pytest.mark.parametrize("language", ["c", "c++"])
def test_arm7_calls_and_owned_data_are_linked_from_c_and_cpp(arm7_calls, tmp_path, monkeypatch, language):
    game, bios, mode = arm7_calls
    monkeypatch.setenv("DECOMP_ARM7_BIOS", str(bios))
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    net.forks.background_links = False
    slug = net.import_rom(game, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
    project = net.project_row(slug)
    root = Path(project["root"])
    path = root / "config/adqe/arm7/units.json"
    manifest = json.loads(path.read_text())
    unit = next(u for u in manifest["units"] if u["address"] == 0x02380040)
    assert unit["size"] == (32 if mode == "arm" else 24)
    assert unit["mode"] == mode
    fp = ForkProject(root)
    agent, _ = net.local_agent("arm7-source-owner")
    saved = path.read_bytes()
    with pytest.raises(NetworkError, match="overlaps"):
        net.forks.configure_arm7_unit(agent, slug, unit["source"], ".data:0x02380080:4")
    assert path.read_bytes() == saved
    configured = net.forks.configure_arm7_unit(agent, slug, unit["source"],
                                               ".data:0x023800A0:4:arm7_data_023800A0", language)
    assert configured.startswith("✅"), configured
    unit = next(u for u in json.loads(path.read_text())["units"] if u["address"] == 0x02380040)
    source = ("extern int arm7_main_02380080(int);\n"
              "int arm7_data_023800A0 = 7;\n"
              "int arm7_main_02380040(int x) { return arm7_main_02380080(x) + arm7_data_023800A0; }\n")
    if language == "c++":
        source = ('template<int N> struct Fixed { enum { value = N }; };\nextern "C" {\n'
                  + source.replace(" = 7;", " = Fixed<7>::value;") + "}\n")
    source = f"#pragma thumb {'on' if mode == 'thumb' else 'off'}\n" + source
    previous = (root / unit["source"]).read_text()
    edited = net.forks.edit_file(agent, slug, unit["source"], previous, source,
                                 "Recover the ARM7 function and its initialized global")
    assert edited.startswith(("✅", "⚠️")), edited
    result = net.attempt(agent, unit["symbol"], source, slug)
    assert result["matched"], result["text"]
    linked = net.forks.link(slug, log=lambda *_: None)
    assert unit["source"] in linked["linked"] or fp.link_states()[unit["source"]][0] == "Matching", linked
    assert (root / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
    # The actual source-built bytes, including global initialization, are a ROM input.
    compiled = root / "build/adqe/build/arm7-linked-0.bin"
    assert compiled.is_file() and struct.unpack_from("<I", compiled.read_bytes(), 0xA0)[0] == 7
    # Objdiff may ignore a changed linked branch destination. Both the displayed
    # match and the file-level scores must still reject those raw-byte changes.
    good = (root / unit["source"]).read_text()
    changed = json.loads(path.read_text())
    changed["symbols"]["arm7_main_02380080"]["address"] += 4
    original_manifest = path.read_text()
    path.write_text(json.dumps(changed))
    object_unit = next(u for u in fp.units() if u.source == unit["source"])
    assert fp.build_unit(object_unit)[0]
    assert fp.diff(object_unit, unit["symbol"]).match_percent < 100
    assert fp.diff(object_unit, None).unit_scores[unit["symbol"]] < 100
    report = fp.report()
    measured = next(u for u in report["units"] if u["name"] == object_unit.name)
    assert measured["measures"]["matched_functions"] == 0
    assert not fp.verify()[0]
    path.write_text(original_manifest)
    assert fp.verify()[0]
    # Mutating active source must fail verification; target bytes are not copied
    # back over a changed candidate to manufacture success.
    bad = good.replace(" = 7;", " = 8;").replace("Fixed<7>", "Fixed<8>")
    (root / unit["source"]).write_text(bad)
    assert not fp.verify()[0]
    (root / unit["source"]).write_text(good)
    assert fp.verify()[0]
    if language == "c++" and mode == "thumb":
        # A clean export has no app or generated build artifacts. Its own scripts
        # must extract the owner's inputs and consume the same source-built data.
        from decompnet.forks import scratch_dsd
        clean = tmp_path / "standalone ARM7 export"
        shutil.copytree(root, clean, ignore=shutil.ignore_patterns(".git", "extract", "build", "build.ninja", "objdiff.json", ".ninja_*", "*.d"))
        (clean / "extract").mkdir()
        shutil.copyfile(game, clean / "extract/baserom.nds")
        shutil.copyfile(bios, clean / "extract/arm7_bios.bin")
        for command in ([sys.executable, "tools/configure.py", "adqe", *scratch_dsd.tool_args()], ["ninja", "rom"]):
            ok, output = ForkProject(clean).run(command, log=lambda *_: None)
            assert ok, output[-4000:]
        assert (clean / "build/adqe/adqe.nds").read_bytes() == game.read_bytes()
