"""Regenerate the original GBA hardware fixture using GNU ARM binutils."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binutils', type=Path, required=True)
    parser.add_argument('--fixture', choices=('all', 'program', 'bios-sound', 'callbacks', 'swi-timer', 'switch-table'), default='all')
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]/'tests/fixtures/gba-native'
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        def run(name, *options):
            return subprocess.check_output([str(args.binutils/('arm-none-eabi-'+name)), *map(str,options)], text=True)
        fixtures = ('program','bios-sound','callbacks','swi-timer','switch-table') if args.fixture == 'all' else (args.fixture,)
        for fixture in fixtures:
            run('as', '-mcpu=arm7tdmi', '-o', work/'program.o', folder/(fixture+'.s'))
            run('ld', '-Ttext=0x08000000', '-o', work/'program.elf', work/'program.o')
            run('objcopy', '-O', 'binary', work/'program.elf', work/'program.bin')
            names = dict(program=('_start','main','thumb_code','irq','ram_source','ram_end','short_source'),
                **{'bios-sound':('_start','main','irq','music_callback','thumb_on','wave'),
                   'swi-timer':('_start','main','thumb_timer'),
                   'switch-table':('_start','main','thumb_switch','case_zero','case_one','case_two','cases')},
                callbacks=('_start','main','thumb_stack','thumb_leaf','arm_stack','arm_leaf','callback_table','ram_source','ram_end'))[fixture]
            symbols = {row[2]: int(row[0],16) for line in run('nm', work/'program.elf').splitlines()
                       if len(row := line.split()) == 3 and row[2] in names}
            (folder/(fixture+'.json')).write_text(json.dumps(dict(hex=(work/'program.bin').read_bytes().hex(),
                symbols=symbols), indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
