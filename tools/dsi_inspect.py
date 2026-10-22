"""Inspect a DSi container or privately extract its stored, possibly encrypted ranges."""

import argparse
import json
from pathlib import Path

from decompnet.rom import dsi


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--output-dir", type=Path, help="new private directory outside the checkout")
    args = parser.parse_args()
    if args.output_dir:
        output = args.output_dir.expanduser().resolve()
        checkout = Path(__file__).resolve().parents[1]
        if output == checkout or checkout in output.parents:
            parser.error("--output-dir must be outside the checkout; it contains private ROM data")
    try:
        info = dsi.extract_stored(args.rom, output) if args.output_dir else dsi.inspect(args.rom)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
