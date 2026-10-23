"""Hash-bound declarations of reviewed unused, loaded PS1 module bytes."""

import hashlib
import json
from pathlib import Path

from .psx_layout import number


def validate(meta, image, declaration, root=None):
    if not isinstance(declaration, dict) or set(declaration) != {"format", "sha256", "modules"} or \
            declaration["format"] != 1 or declaration["sha256"] != hashlib.sha256(image).hexdigest():
        raise ValueError("PS1 mod space must use format 1 and the original analysis SHA-256")
    items = declaration["modules"]
    if not isinstance(items, list) or not 1 <= len(items) <= 129:
        raise ValueError("declare 1 to 129 reviewed PS1 module reserves")
    result = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"module", "start", "size"}:
            raise ValueError("a PS1 reserve needs module, start and size")
        name = item["module"]
        segment = next((s for s in meta["segments"] if s["kind"] == "code" and s["name"] == name), None)
        if not segment or name in result:
            raise ValueError("choose distinct existing PS1 code modules")
        start, size = number(item["start"], "reserve start"), number(item["size"], "reserve size")
        at = segment["start"] + start - segment["vram"]
        if start % 16 or size % 16 or not 16 <= size <= 2 << 20 or \
                not segment["start"] <= at < at + size <= (segment["end"] or len(image)):
            raise ValueError("PS1 reserve must be 16-byte aligned inside its loaded module")
        mapping = next((m for m in meta.get("disc", {}).get("layout", {}).get("maps", []) if m["segment"] == name), None)
        base = mapping["analysis_offset"] if mapping else 0
        if image[base:base + 8] == b"PS-X EXE":
            loaded = int.from_bytes(image[base + 0x1C:base + 0x20], "little")
            if not base + 0x800 <= at < at + size <= base + 0x800 + loaded:
                raise ValueError("PS1 reserve must be loaded by its original EXE header")
            bss = int.from_bytes(image[base + 0x28:base + 0x2C], "little")
            bss_size = int.from_bytes(image[base + 0x2C:base + 0x30], "little")
            if bss_size and bss < start + size and start < bss + bss_size:
                raise ValueError("PS1 reserve overlaps storage cleared by the original BSS initializer")
        if mapping and not mapping["analysis_offset"] + mapping.get("code_at", 0) <= at < at + size <= mapping["analysis_offset"] + mapping["size"]:
            raise ValueError("PS1 reserve is outside its mapped program file")
        if image[at:at + size].strip(b"\0"):
            raise ValueError("reviewed PS1 mod space must contain only original zero bytes")
        if mapping and any(at < mapping["analysis_offset"] + r["offset"] + 4 and mapping["analysis_offset"] + r["offset"] < at + size
                           for r in mapping.get("relocations", [])):
            raise ValueError("PS1 reserve overlaps an original loader relocation site")
        for fn in meta["functions"]:
            if fn["seg"] == name and start <= fn["vram"] < start + size:
                raise ValueError("a PS1 reserve overlaps an original function entry")
            if root is not None and fn["seg"] == name and fn["vram"] < start:
                from .split import parse_function, _complete_delay_slot
                path = root / fn["asm"]
                if not path.is_file():
                    raise ValueError("run the original PS1 build before configuring mod space")
                parsed = parse_function(path, name, False)
                if parsed:
                    _complete_delay_slot(parsed, image, False)
                    if parsed.vram + parsed.size > start:
                        raise ValueError("a PS1 reserve overlaps an original function body")
        result[name] = {"module": name, "start": start, "size": size, "offset": at}
    return result


def read(root, meta, image):
    path = root / "psx-mod-space.json"
    return validate(meta, image, json.loads(path.read_text(encoding="utf-8")), root) if path.exists() else {}


def configure(root, module, start, size):
    """Record a user's reviewed loader fact; zero padding alone is not proof of nonuse."""
    root = Path(root).resolve()
    meta = json.loads((root / "build.json").read_text(encoding="utf-8"))
    if meta.get("platform") != "psx":
        raise ValueError("choose an exported PS1 disc project; configure combined discs in their own directories")
    if disc := meta.get("disc"):
        from .psx_disc import analysis
        image = analysis(root / disc["image"], disc["layout"])
    else:
        image = (root / meta["image"]).read_bytes()
    if hashlib.sha1(image).hexdigest() != meta["sha1"]:
        raise ValueError("the original PS1 analysis image differs")
    path = root / "psx-mod-space.json"
    declaration = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": []}
    if path.exists():
        validate(meta, image, declaration, root)
    declaration["modules"] = [m for m in declaration["modules"] if m["module"] != module] + [
        {"module": module, "start": start, "size": size}]
    validate(meta, image, declaration, root)
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return declaration
