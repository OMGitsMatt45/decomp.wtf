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
    ctr_inspect = actions.add_parser('ctr-inspect', help='validate a decrypted 3DS NCCH/NCSD executable without exporting or running it')
    ctr_inspect.add_argument('input', type=Path)
    ctr_probe = actions.add_parser('ctr-probe', help='3DS native C/C++ CPU development project; no graphics or retail game runtime yet')
    ctr_probe.add_argument('input', type=Path)
    ctr_probe.add_argument('output', type=Path)
    ctr_probe.add_argument('--experimental', action='store_true', required=True)
    ctr_probe.add_argument('--feedback',action='append',type=Path,default=[],help='exact-input runtime coverage report; repeat to combine runs')
    ctr_runtime = actions.add_parser('ctr-runtime', help='3DS source-shipped kernel/service development project; desktop gameplay is not qualified')
    ctr_runtime.add_argument('input', type=Path)
    ctr_runtime.add_argument('output', type=Path)
    ctr_runtime.add_argument('--experimental', action='store_true', required=True)
    ctr_runtime.add_argument('--feedback',action='append',type=Path,default=[],help='exact-input runtime coverage report; discovery does not qualify native execution')
    ctr_runtime.add_argument('--screen-mode', choices=('dual','unified'), default='dual', help='default adaptive screen composition in the exported window')
    gba_inspect = actions.add_parser('gba-inspect', help='validate a GBA cartridge and identify its exact revision')
    gba_inspect.add_argument('input', type=Path)
    for name, help in (('gba-probe', 'headless GBA native C/C++ development probe'),
                       ('gba-native', 'GBA C/C++ desktop source with raw-state OpenGL rendering, audio and saves')):
        gba = actions.add_parser(name, help=help)
        gba.add_argument('input', type=Path)
        gba.add_argument('output', type=Path)
        gba.add_argument('--profile', type=Path, help='input-bound code entries and ROM-to-RAM code mappings')
        gba.add_argument('--save-type', choices=('auto','none','sram','flash64','flash128','eeprom','eeprom512','eeprom8k'), default='auto')
        gba.add_argument('--rtc', choices=('auto','on','off'), default='auto')
        gba.add_argument('--feedback', action='append', type=Path, default=[], help='input-bound runtime miss log; repeat to combine coverage runs')
        gba.add_argument('--experimental', action='store_true', required=True)
        if name == 'gba-native':
            gba.add_argument('--renderer', choices=('auto','opengl','software'), default='auto')
    ps2_inspect = actions.add_parser('ps2-inspect', help='inspect a PS2 ISO/BIN or EE ELF without running or exporting it')
    ps2_inspect.add_argument('input', type=Path)
    ps2_inspect.add_argument('--quick', action='store_true', help='skip whole-image SHA-256; does not verify full input identity')
    ps2_inspect.add_argument('--discover-code', action='store_true',
        help='trace bounded static control flow in the boot ELF and recognized overlays; reports unresolved targets')
    ps2 = actions.add_parser('ps2-native', help='experimental PS2 C++ source project with a source-shipped hardware runtime')
    ps2.add_argument('input',type=Path)
    ps2.add_argument('output',type=Path)
    ps2.add_argument('--profile',type=Path,help='reviewed input-bound map for ambiguous code, external callbacks and native SDK bindings')
    ps2.add_argument('--title',default='')
    ps2.add_argument('--renderer',choices=('auto','vulkan','software'),default='auto')
    ps2.add_argument('--experimental',action='store_true',required=True)
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
    psx = actions.add_parser('psx-native', help='PS1 C/C++ repository for one game and its ordered disc set')
    psx.add_argument('inputs',nargs='+',type=Path,help='disc images/CUE sheets in order, or an M3U playlist')
    psx.add_argument('output',type=Path)
    psx.add_argument('--title',default='')
    psx.add_argument('--renderer',choices=('auto','opengl','software'),default='auto')
    psx.add_argument('--experimental',action='store_true',required=True)


def run(args):
    try:
        if args.pc_action == 'ctr-inspect':
            from .ctr_native.media import load
            result = load(args.input)
        elif args.pc_action == 'ctr-probe':
            from .ctr_native import export_probe
            result = export_probe(args.input, args.output,feedback=args.feedback)
        elif args.pc_action == 'ctr-runtime':
            from .ctr_native import export_runtime
            result = export_runtime(args.input, args.output, screen_mode=args.screen_mode,feedback=args.feedback)
        elif args.pc_action == 'gba-inspect':
            from .gba_native import inspect
            result = inspect(args.input)
        elif args.pc_action in ('gba-probe', 'gba-native'):
            from .gba_native import export, export_game
            native = args.pc_action == 'gba-native'
            result = (export_game if native else export)(args.input, args.output, profile=args.profile,
                save_type=args.save_type, rtc=args.rtc, feedback=args.feedback,
                **({'renderer': args.renderer} if native else {}))
        elif args.pc_action == 'ps2-inspect':
            from .ps2_native.media import inspect
            result = inspect(args.input, hash_input=not args.quick, discover_code=args.discover_code)
        elif args.pc_action == 'ps2-native':
            from .ps2_native import export
            result = export(args.input,args.output,profile=args.profile,title=args.title,renderer=args.renderer)
        elif args.pc_action == 'psx-native':
            from .psx_native import export
            result = export(args.inputs,args.output,title=args.title,renderer=args.renderer)
        elif args.pc_action == 'nds-native':
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
