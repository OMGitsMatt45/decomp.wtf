"""Regenerate the original GBA hardware fixture using GNU ARM binutils."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binutils', type=Path, required=True)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]/'tests/fixtures/gba-native'
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        def run(name, *options):
            return subprocess.check_output([str(args.binutils/('arm-none-eabi-'+name)), *map(str,options)], text=True)
        run('as', '-mcpu=arm7tdmi', '-o', work/'program.o', folder/'program.s')
        run('ld', '-Ttext=0x08000000', '-o', work/'program.elf', work/'program.o')
        run('objcopy', '-O', 'binary', work/'program.elf', work/'program.bin')
        names = ('_start','main','thumb_code','irq','ram_source','ram_end')
        symbols = {row[2]: int(row[0],16) for line in run('nm', work/'program.elf').splitlines()
                   if len(row := line.split()) == 3 and row[2] in names}
        (folder/'program.json').write_text(json.dumps(dict(hex=(work/'program.bin').read_bytes().hex(),
            symbols=symbols), indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
