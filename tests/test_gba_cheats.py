"""Execute device cheats through the real standalone player and its memory bus."""
from pathlib import Path

from .test_gba_native import sdk, generate, execute, run
from .fixtures.gba_native import switch_table


def test_device_cheats_and_persistent_preferences(tmp_path, sdk):
    project=generate(tmp_path/'cheats',profile=False,fixture=switch_table())
    _, root, exe=project
    tests=exe.with_name('gba_cheat_tests'+exe.suffix)
    assert 'preferences passed' in run([tests,tmp_path/'preferences'])
    report=execute(project,'--strict-static','--cheat','cb:82000200 1234',
        '--observe','0x02000200')
    assert report['observed']==[0x1234]
    assert report['enabled_cheats']==1 and report['interpreted_cycles']==0 and report['misses']==[]
    assert not report['game_customized']
    save=tmp_path/'game.sav'
    prefs=Path(str(save)+'.cheats.toml')
    prefs.write_text('[[cheat]]\nname="Saved code"\nformat="cb"\ncode=["82000200 4567"]\nenabled=true\n')
    enabled=execute(project,'--strict-static','--save',save,'--observe','0x02000200')
    assert enabled['observed']==[0x4567] and enabled['enabled_cheats']==1
    prefs.write_text(prefs.read_text().replace('enabled=true','enabled=false'))
    disabled=execute(project,'--strict-static','--save',save,'--observe','0x02000200')
    assert disabled['observed']==[0] and disabled['enabled_cheats']==0
    assert 'requires a native source patch' in execute(project,'--cheat','raw:08000100:4770',ok=False)
    assert 'DEADFACE' in execute(project,'--cheat','gsv1raw:DEADFACE 00001234',ok=False)
    custom=root/'custom';custom.mkdir()
    (custom/'game.cpp').write_text('#include "customization.hpp"\n#include "anygba/system.hpp"\n'
        'namespace gba_customization {\n'
        'void configure(anygba::System& s) { s.write16(0x02000208, 0xf00d); }\n'
        'std::string description() { return "Custom\\n\\\"native\\\""; }\n}\n')
    run(['cmake','-S',root,'-B',root/'build'])
    run(['cmake','--build',root/'build','--config','Release','--parallel','2'])
    modified=execute(project,'--strict-static','--observe','0x02000208')
    assert modified['observed']==[0xf00d] and modified['game_customized']
    assert modified['customization']=='Custom\n"native"'
    assert modified['interpreted_cycles']==0 and modified['misses']==[]
