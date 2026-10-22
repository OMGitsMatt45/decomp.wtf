"""Execute original and source-linked DS programs; the dedicated CI job requires every case."""

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from elftools.elf.elffile import ELFFile

from decompnet.app.engine import RomNetwork
from decompnet.forks import drafts, scratch_dsd

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "projects/demo-ds/build/demoquest.nds"
CORE = os.environ.get("DECOMP_DS_CORE")
pytestmark = pytest.mark.skipif(not CORE, reason="dedicated DS execution job supplies a pinned melonDS core")


def probe(tmp_path, *roms):
    output = tmp_path / "execution.json"
    output.unlink(missing_ok=True)
    result = subprocess.run([sys.executable, str(ROOT / "tools/ds_boot.py"), "--core", CORE, "--builtin-bios",
                             "--symbols", str(ROOT / "projects/demo-ds/build/demoq_ds.elf"), "--output", str(output),
                             *map(str, roms)], capture_output=True, text=True, timeout=120)
    return result, output


def test_original_and_source_linked_roms_execute_identically(tmp_path, monkeypatch):
    net = RomNetwork(tmp_path / "app.db", tmp_path / "projects")
    monkeypatch.setattr(net.forks, "link_soon", lambda *a, **kw: None)
    monkeypatch.setattr(scratch_dsd, "UNIT_BYTES", 16)
    slug = net.import_rom(ROM, toolchain="DS/2.0/sp1p5", confirmed=True, log=lambda *_: None)
    root = Path(net.project_row(slug)["root"])
    with (ROOT / "projects/demo-ds/build/demoq_ds.elf").open("rb") as stream:
        address = ELFFile(stream).get_section_by_name(".symtab").get_symbol_by_name("ds_thumb_step")[0]["st_value"] & ~1
    symbol = f"func_{address:08x}"
    unit = net.store.one("SELECT unit FROM functions WHERE name=?", symbol)["unit"]
    source = drafts.ds_mode_source(root, unit, symbol, f"int {symbol}(int value) {{ return value + 3; }}")
    agent, _ = net.local_agent("execution-owner")
    attempted = net.attempt(agent, symbol, source, slug)
    assert attempted["matched"], attempted["text"]
    assert net.forks.link(slug, log=lambda *_: None)["linked"]
    result, output = probe(tmp_path, ROM, root / "build/adqe/adqe.nds")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["identical_traces"] and len(report["roms"]) == 2
    for execution in report["roms"]:
        for name in ("g_frame_count", "arm7_counter"):
            assert len({sample[name] for sample in execution["samples"]}) > 1


@pytest.mark.parametrize("cpu", ["arm9", "arm7"])
def test_execution_rejects_a_stalled_processor(tmp_path, cpu):
    image = bytearray(ROM.read_bytes())
    if cpu == "arm9":
        arm9 = struct.unpack_from("<I", image, 0x20)[0]
        # Reproduce the former startup bug: stay in SVC mode across the BIOS call.
        offset = image.index(struct.pack("<I", 0xE321F0DF), arm9, arm9 + 0x1000)
        struct.pack_into("<I", image, offset, 0xE321F0D3)
        diagnostic = "g_frame_count did not advance"
    else:
        arm7 = struct.unpack_from("<I", image, 0x30)[0]
        assert struct.unpack_from("<I", image, arm7 + 12)[0] == 0xE5801000
        struct.pack_into("<I", image, arm7 + 12, 0xE1A00000)  # stop storing the ARM7 counter
        diagnostic = "arm7_counter did not advance"
    broken = tmp_path / "stalled.nds"
    broken.write_bytes(image)
    result, output = probe(tmp_path, ROM, broken)
    assert result.returncode != 0 and diagnostic in result.stdout + result.stderr
    assert not output.exists()


def test_scripted_trace_records_video_audio_and_private_screenshots(tmp_path):
    events = tmp_path / "inputs.json"
    events.write_text(json.dumps([{"start": 30, "end": 35, "buttons": ["a"]}]))
    output = tmp_path / "private traces"
    result = subprocess.run([sys.executable, "-m", "tools.ds_trace", "--core", CORE, "--builtin-bios",
                             "--frames", "120", "--inputs", str(events), "--output", str(output), str(ROM), str(ROM)],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["identical_video_audio"] and len(report["roms"]) == 2
    assert len(list((output / "rom-0").glob("frame-*.png"))) == 4
    assert all(t["width"] == 256 and t["height"] == 384 and t["audio_samples"] > 0
               for t in report["roms"][0]["traces"])
