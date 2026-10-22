"""Retain an absent-constructor overlay's original unowned tail word at link time."""

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsd")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--lcf", required=True, type=Path)
    args = parser.parse_args()
    subprocess.run([args.dsd, "lcf", "-c", str(args.config)], check=True)
    config = yaml.load(args.config.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    layout = (args.config.parent / config["rom_config"]).parent / "retained_layout.json"
    if not layout.is_file():
        return
    retained = json.loads(layout.read_text(encoding="utf-8")).get("absent_arm9_constructors", {})
    text = args.lcf.read_text(encoding="utf-8")
    for identity, original in retained.items():
        if "tail_word" not in original:
            continue
        prefix = f"OV{int(identity):03}_CTOR_"
        pattern = re.compile(r"(" + prefix + r"START = \.;\s*)WRITEW\(0\);(\s*\. = ALIGN\(\d+\);\s*" +
                             prefix + r"END = \.;)")
        text, count = pattern.subn(lambda match: match[1] + f"WRITEW(0x{original['tail_word']:08X});" + match[2], text)
        if count != 1:
            raise ValueError(f"overlay {identity} no longer has an empty retained constructor section")
    args.lcf.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
