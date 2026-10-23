"""Preserve an explicitly decrypted DS input without applying secure-area encryption."""

import shutil
import struct
import json
import re
from pathlib import Path

import yaml

SECURE_MARKER = bytes.fromhex("ffdeffe7ffdeffe7")


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def header(path):
    with Path(path).open("rb") as stream:
        data = stream.read(0x200)
    if len(data) != 0x200 or crc16(data[:0x15E]) != struct.unpack_from("<H", data, 0x15E)[0]:
        raise ValueError("invalid or truncated DS header")
    if data[0x12] or data[0x1C] & 3:
        raise ValueError("TWL containers require the separate DSi workflow")
    return data


def stage_decrypted(source, target):
    """Defeat dsd's content heuristic on a private staging copy, then restore all supplied bytes."""
    data = header(source)
    offset, entry, address, size = struct.unpack_from("<4I", data, 0x20)
    if offset < 0x200 or size < 0x4000 or offset + size > Path(source).stat().st_size:
        raise ValueError("decrypted ARM9 extent is outside the ROM or lacks a full secure area")
    with Path(source).open("rb") as stream:
        stream.seek(offset)
        prefix = stream.read(0x800)
    shutil.copyfile(source, target)
    with Path(target).open("r+b") as stream:
        stream.seek(offset)
        stream.write(SECURE_MARKER)
    return prefix


def restore_prefix(extracted, prefix):
    config = yaml.safe_load((extracted / "config.yaml").read_text(encoding="utf-8"))
    arm9 = (extracted / config["arm9_bin"]).resolve()
    if extracted.resolve() not in arm9.parents or arm9.stat().st_size < len(prefix):
        raise ValueError("invalid extracted ARM9 path or size")
    with arm9.open("r+b") as stream:
        stream.write(prefix)


def empty_constructors(extracted, *, analysis=False):
    """Reserve the last word for a table explicitly marked absent.

    A nonzero tail is retained privately and emitted by the linker, rather than
    being exposed as recoverable source. No original bytes are discarded and
    the serialized absent-table fields are restored during ROM configuration.
    """
    config = yaml.safe_load((extracted / "config.yaml").read_text(encoding="utf-8"))
    retained = {}
    if config.get("arm9_overlays"):
        path = extracted / config["arm9_overlays"]
        document = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        fields = lambda node: {key.value: value for key, value in node.value}
        for node in fields(document)["overlays"].value:
            overlay = fields(node)
            start, end = int(overlay["ctor_start"].value), int(overlay["ctor_end"].value)
            if start != end:
                continue
            size, address = int(overlay["code_size"].value), int(overlay["base_address"].value)
            data = (path.parent / overlay["file_name"].value).read_bytes()
            if size < 4 or size % 4 or len(data) != size:
                raise ValueError(f"ARM9 overlay {overlay['id'].value} has an unaligned or truncated absent-constructor layout")
            retained[overlay["id"].value] = {"start": address + size - 4, "end": address + size,
                                             "serialized_start": start, "serialized_end": end}
            if data[-4:] != bytes(4):
                retained[overlay["id"].value]["tail_word"] = int.from_bytes(data[-4:], "little")
                (path.parent / overlay["file_name"].value).write_bytes(data[:-4] + bytes(4))
            overlay["ctor_start"].value = str(address + size - 4)
            overlay["ctor_end"].value = str(address + size)
            # dsd init insists on 32-byte BSS alignment. A private analysis view
            # may include padding; finish_layout removes it before targets or
            # source units are generated and records the actual BSS alignment.
            padding = -(address + size) % 32 if analysis else 0
            if padding:
                retained[overlay["id"].value]["analysis_padding"] = padding
                retained[overlay["id"].value]["initialized_size"] = size
                binary = path.parent / overlay["file_name"].value
                binary.write_bytes(binary.read_bytes() + bytes(padding))
                overlay["code_size"].value = str(size + padding)
        if retained:
            path.write_text(yaml.serialize(document, Dumper=yaml.SafeDumper), encoding="utf-8")
    (extracted / "retained_layout.json").write_text(json.dumps({"absent_arm9_constructors": retained}), encoding="utf-8")


def module_hash(data):
    """dsd's FxHasher64 slice checksum, including its 64-bit length prefix."""
    value, mask = 0, (1 << 64) - 1
    def add(word):
        nonlocal value
        value = (((((value << 5) | (value >> 59)) & mask) ^ word) * 0x517CC1B727220A95) & mask
    add(len(data))
    at = 0
    for size in (8, 4, 2, 1):
        while at + size <= len(data):
            add(int.from_bytes(data[at:at + size], "little"))
            at += size
    return f"{value:016x}"


def finish_layout(config_path):
    """Remove analyzer-only padding and make module hashes describe emitted bytes."""
    fields = lambda node: {key.value: value for key, value in node.value}
    config_document = yaml.compose(config_path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    config = fields(config_document)
    extracted_config = config_path.parent / config["rom_config"].value
    extracted = extracted_config.parent
    layout_path = extracted / "retained_layout.json"
    retained = json.loads(layout_path.read_text(encoding="utf-8"))["absent_arm9_constructors"]
    paths = yaml.safe_load(extracted_config.read_text(encoding="utf-8"))
    if not retained or not paths.get("arm9_overlays"):
        return
    table = extracted / paths["arm9_overlays"]
    document = yaml.compose(table.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    modules = {fields(m)["id"].value: fields(m) for m in config["overlays"].value}
    for node in fields(document)["overlays"].value:
        overlay = fields(node)
        original = retained.get(overlay["id"].value)
        if original is None:
            continue
        module = modules[overlay["id"].value]
        binary = table.parent / overlay["file_name"].value
        code = binary.read_bytes()
        if original.get("analysis_padding"):
            size, base = original["initialized_size"], int(overlay["base_address"].value)
            code = code[:size]
            binary.write_bytes(code)
            overlay["code_size"].value = str(size)
            bss_start = base + size
            bss_end = bss_start + int(overlay["bss_size"].value)
            alignment = min(32, bss_start & -bss_start)
            delinks = config_path.parent / module["delinks"].value
            text = delinks.read_text(encoding="utf-8")
            text, count = re.subn(r"(\.bss\s+)start:0x[0-9a-f]+ end:0x[0-9a-f]+ kind:bss align:\d+",
                lambda match: match[1] + f"start:0x{bss_start:08x} end:0x{bss_end:08x} kind:bss align:{alignment}", text)
            if count != 1:
                raise ValueError("unexpected analyzer BSS section for retained overlay")
            delinks.write_text(text, encoding="utf-8")
            symbols = config_path.parent / module["symbols"].value
            lines = []
            for line in symbols.read_text(encoding="utf-8").splitlines(keepends=True):
                address = re.search(r"\baddr:(0x[0-9a-f]+)", line)
                if address and bss_start <= int(address[1], 16) < bss_end:
                    line = re.sub(r"kind:data(?:\([^)]*\))?", "kind:bss", line)
                lines.append(line)
            symbols.write_text("".join(lines), encoding="utf-8")
        if "tail_word" in original:
            code = code[:-4] + original["tail_word"].to_bytes(4, "little")
        module["hash"].value = module_hash(code)
    table.write_text(yaml.serialize(document, Dumper=yaml.SafeDumper), encoding="utf-8")
    config_path.write_text(yaml.serialize(config_document, Dumper=yaml.SafeDumper), encoding="utf-8")

def retain_secure_crc(rom, reference):
    """Serialize retained secure CRC metadata and compute the new header CRC normally.

    No comparison exceptions: the caller still checks every rebuilt byte against
    its reference. The two fields are unavailable in dsd's header YAML format.
    """
    original, built = header(reference), header(rom)
    if built[12:16] != original[12:16]:
        raise ValueError("rebuilt game ID differs from decrypted reference")
    data = bytearray(built)
    data[0x6C:0x6E] = original[0x6C:0x6E]
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    with Path(rom).open("r+b") as stream:
        stream.write(data)
