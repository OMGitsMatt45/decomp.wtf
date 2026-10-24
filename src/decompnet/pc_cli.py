"""Inspect native PC backend availability and verify generated source projects."""
import json
from pathlib import Path
import sys

from . import pc


def add_parser(sub):
    parser = sub.add_parser('pc', help='native PC project capabilities and integrity checks')
    actions = parser.add_subparsers(dest='pc_action', required=True)
    status = actions.add_parser('status', help='show installed backends; DS is first')
    status.add_argument('--platform', default='')
    verify = actions.add_parser('verify', help='verify a PC project without claiming gameplay qualification')
    verify.add_argument('path', type=Path)
    generate = actions.add_parser('nds-generate', help='experimental DS static C++ repository from reviewed code ranges')
    generate.add_argument('rom', type=Path)
    generate.add_argument('profile', type=Path)
    generate.add_argument('output', type=Path)
    generate.add_argument('--experimental', action='store_true', required=True,
                          help='acknowledge incomplete ISA/hardware coverage; no retail port is qualified')
    native = actions.add_parser('nds-native', help='experimental DS C++ repository with a source-shipped hardware runtime')
    native.add_argument('rom', type=Path)
    native.add_argument('output', type=Path)
    native.add_argument('--profile', type=Path, help='reviewed original fixture; otherwise analyze the ROM automatically')
    native.add_argument('--input-format', choices=('auto','decrypted'), default='auto')
    native.add_argument('--arm7-bios', type=Path, help='optional private decoding input for encrypted originals')
    native.add_argument('--save-type', default='auto', help='cartridge chip for a new game, e.g. eeprom64k; auto infers from an existing raw save')
    native.add_argument('--renderer', choices=('auto','opengl','software'),default='auto',help='default native renderer; OpenGL draws 3D geometry at the window resolution')
    native.add_argument('--screen-mode', choices=('dual','unified'),default='dual',help='default presentation; unified extends one 3D camera across the window')
    native.add_argument('--experimental', action='store_true', required=True)


def run(args):
    try:
        if args.pc_action == 'nds-native':
            from .nds_native import export
            result = export(args.rom,args.output,profile=args.profile,input_format=args.input_format,
                            arm7_bios=args.arm7_bios,save_type=args.save_type,renderer=args.renderer,screen_mode=args.screen_mode)
        elif args.pc_action == 'nds-generate':
            from .nds_pc import export
            result = export(args.rom,args.profile,args.output)
        else:
            result = pc.status(args.platform) if args.pc_action == 'status' else pc.verify(args.path)
        print(json.dumps(result, indent=2))
        return 0
    except (pc.PCError, OSError, ValueError) as error:
        print('error: '+str(error), file=sys.stderr)
        return 1
