"""Send one bounded command to an optional native PS2 test controller."""
# SPDX-License-Identifier: MIT
import argparse
from pathlib import Path
import os
import tempfile
import time

BUTTONS={'SELECT','L3','R3','START','UP','RIGHT','DOWN','LEFT','L2','R2','L1','R1',
         'TRIANGLE','CIRCLE','CROSS','SQUARE'}

def send(command_file,buttons,ticks):
    path=Path(command_file).resolve();buttons=buttons.upper()
    if not 1<=ticks<=3600 or (buttons!='NONE' and any(n not in BUTTONS for n in buttons.split('+'))):
        raise ValueError('Use valid buttons and a hold of 1..3600 guest ticks')
    sequence=int(path.read_text().split()[0])+1 if path.exists() else 1
    line=f'{sequence} {buttons} {ticks}\n'
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',
                dir=path.parent,prefix=path.name+'.',suffix='.next',delete=False) as output:
            temporary=Path(output.name);output.write(line)
        deadline=time.monotonic()+1.0
        while True:
            try:
                os.replace(temporary,path)
                return line
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(0.01)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command_file');parser.add_argument('buttons');parser.add_argument('ticks',type=int,nargs='?',default=12)
    args=parser.parse_args();print(send(args.command_file,args.buttons,args.ticks).strip())

if __name__=='__main__':main()
