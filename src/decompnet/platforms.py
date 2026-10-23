"""Application platform scope, shared by imports, projects and output adapters."""
from __future__ import annotations

import struct

REMOVED = {"n64": "Nintendo 64", "gc": "GameCube", "wii": "Wii", "gcwii": "GameCube/Wii"}
ALIASES = {"gamecube": "gc", "gcn": "gc", "nintendo64": "n64", "nintendo 64": "n64",
           "gc-wii": "gcwii", "gamecube/wii": "gcwii", "ps": "psx", "ds": "nds"}
NAMES = {"nds": "Nintendo DS", "psx": "PlayStation", "ps2": "PlayStation 2",
         "gba": "Game Boy Advance", "gb": "Game Boy", "gbc": "Game Boy Color"}
REMOVED_TOOLS = frozenset({"gcc-2.7.2-kmc", "ido-5.3", "ido-7.1", "mwcc"})


def canonical(platform: str) -> str:
    value = str(platform or '').strip().lower()
    return ALIASES.get(value, value)


def enabled(platform: str) -> bool:
    return canonical(platform) not in REMOVED


def require(platform: str, error=ValueError) -> None:
    key = canonical(platform)
    if key in REMOVED:
        raise error(f"{REMOVED[key]} functionality has been removed from this branch. "
                    "Use the preserved main branch in PR #27 for the previous workflow. "
                    "Existing project files have not been deleted.")


def project_platform(root, declared='') -> str:
    """Check a public project's own declared target before registering it."""
    import json
    import yaml
    manifest = root / '.decomp.wtf.json'
    if manifest.is_file() and manifest.stat().st_size < 1 << 20:
        target = json.loads(manifest.read_text()).get('platform', '')
        require(target)
    for path in list(root.glob('*.yaml'))[:16] + list(root.glob('*.yml'))[:16]:
        if path.stat().st_size < 1 << 20:
            cfg = yaml.safe_load(path.read_text())
            if isinstance(cfg, dict):
                target = (cfg.get('options') or {}).get('platform', cfg.get('platform', ''))
                require(target)
    require(declared)
    return canonical(declared)


def removed_input(head: bytes, size: int) -> str | None:
    """Identify retired formats before decoding, uploading or starting a tool."""
    if head[:4] in (b'\x80\x37\x12\x40', b'\x37\x80\x40\x12', b'\x40\x12\x37\x80'):
        return 'n64'
    if len(head) >= 0x20:
        if struct.unpack_from('>I', head, 0x1c)[0] == 0xc2339f3d:
            return 'gc'
        if struct.unpack_from('>I', head, 0x18)[0] == 0x5d1c9ea3:
            return 'wii'
    if head[:4] in (b'RVZ\x01', b'WIA\x01', b'WBFS', b'CISO', b'\x01\xc0\x0b\xb1'):
        return 'gcwii'
    if len(head) >= 0x100:
        entry = struct.unpack_from('>I', head, 0xe0)[0]
        if 0x80000000 <= entry < 0x81800000:
            sections = [struct.unpack_from('>I', head, at + i*4)[0]
                        for at in (0, 72, 144) for i in range(18)]
            offsets, addresses, sizes = sections[:18], sections[18:36], sections[36:]
            live = [(o, a, n) for o, a, n in zip(offsets, addresses, sizes) if n]
            if live and all(o >= 0x100 and o+n <= size and
                            0x80000000 <= a < a+n <= 0x81800000 for o, a, n in live):
                return 'gc'
    return None
