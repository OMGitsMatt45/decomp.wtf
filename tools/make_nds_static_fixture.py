"""Regenerate the original CC0 ARM execution fixture with GNU Arm tools.

Tests use committed hexadecimal bytes and do not require a console toolchain.
This script records the linked symbols so code ranges exclude literal pools.
"""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import argparse

from elftools.elf.elffile import ELFFile
from decompnet import toolchains

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',choices=('nds-static','nds-hardware','nds-video','nds-rtc'),default='nds-static')
    fixture = parser.parse_args().fixture
    tools = toolchains.require('arm-gnu')/'bin'
    suffix = '.exe' if os.name=='nt' else ''
    result = {}
    with tempfile.TemporaryDirectory(prefix='nds-static-fixture-') as temporary:
        work = Path(temporary)
        for cpu, address in (('arm9',0x02000000),('arm7',0x03800000)):
            source = ROOT/'tests/fixtures'/fixture/(cpu+'.s')
            obj, elf, binary = [work/(cpu+extension) for extension in ('.o','.elf','.bin')]
            subprocess.run([str(tools/('arm-none-eabi-as'+suffix)),str(source),'-o',str(obj)],check=True)
            subprocess.run([str(tools/('arm-none-eabi-ld'+suffix)),'-Ttext',hex(address),'-o',str(elf),str(obj)],check=True)
            subprocess.run([str(tools/('arm-none-eabi-objcopy'+suffix)),'-O','binary',str(elf),str(binary)],check=True)
            with elf.open('rb') as stream:
                symbols = {s.name:s['st_value'] for s in ELFFile(stream).get_section_by_name('.symtab').iter_symbols()
                           if s.name in ('_start','main_end','thumb_start','thumb_end','loader','overlay1_source','overlay2_source',
                                         'save_read','save_read_end','save_write','save_write_end','irq_start','irq_end',
                                         'shared_start','shared_end','shared_exit','shared_exit_end','regular_start','regular_end','child_start','child_end',
                                         'large_start','large_end')}
            result[cpu] = dict(hex=binary.read_bytes().hex(),symbols=symbols)
    (ROOT/'tests/fixtures'/fixture/'program.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
