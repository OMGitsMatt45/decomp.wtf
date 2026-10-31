"""Data cheats change original guest RAM through the generated standalone host."""
import hashlib
import json
import struct

import pytest

from .test_nds_native import generate, execute, sdk  # noqa: F401
from .fixtures.nds_static import simple


@pytest.fixture(scope='module')
def cheat_project(tmp_path_factory,sdk):
    def original():
        # Write 7 once, then wait. All cheat targets are separate data RAM.
        code=struct.pack('<5I',0xe59f1008,0xe3a00007,0xe5810000,0xeafffffe,0x02010000)
        raw,profile=simple(code,struct.pack('<I',0xeafffffe),code_size9=16)
        profile.pop('save_region',None)
        profile['observe_words']=[0x02010000,0x02010004,0x02010008]
        return raw,profile
    return generate(tmp_path_factory.mktemp('nds-cheats')/'original',original)


def catalog(tmp_path,rom,text):
    path=tmp_path/'cheats.txt'
    path.write_text('rom '+hashlib.sha256(rom.read_bytes()).hexdigest()+'\n'+text)
    return path


def test_data_writes_copy_guards_and_disabled_equivalence(tmp_path,cheat_project):
    rom,root,exe=cheat_project
    path=catalog(tmp_path,rom,'''cheat "Value"
when16 0x02010000 7 7
write16 0x02010004 0x1234
write8 0x02010006 0x56
end
cheat "Copy"
copy16 0x02010004 0x02010008
end
cheat "Blocked"
when16 0x02010000 8 8
write32 0x02010000 99
end
''')
    baseline=execute(exe,root,'--save',tmp_path/'baseline.sav')
    off=execute(exe,root,'--save',tmp_path/'off.sav','--cheats',path)
    assert baseline['observed']==off['observed']==[7,0,0]
    for field in ('top_hash','bottom_hash','audio_frames','ticks','cpu_pc'):
        assert baseline[field]==off[field]
    on=execute(exe,root,'--save',tmp_path/'on.sav','--cheats',path,
        '--enable-cheat','Value','--enable-cheat','Copy','--enable-cheat','Blocked')
    assert on['observed']==[7,0x561234,0x1234]
    assert on['cheats']==dict(available=3,enabled=3,applications=24,menu_openings=0,menu_frames=0)
    # Catalog state is per launch; restarting does not silently keep toggles on.
    assert execute(exe,root,'--save',tmp_path/'off.sav','--cheats',path)['cheats']['enabled']==0


@pytest.mark.parametrize('operation,message',[
    ('write8 0x02010004 256','exceeds write width'),
    ('write16 0x02010005 1','aligned main RAM'),
    ('write32 0x02400000 1','aligned main RAM'),
    ('write32 0x02000000 1','requires a native source patch'),
    ('write64 0x02010004 1','unsupported cheat operation'),
    ('when16 0x02010000 8 7','invalid cheat guard'),
    ('write32 0x02010004 -1','invalid cheat number'),
])
def test_invalid_operations_fail_before_execution(tmp_path,cheat_project,operation,message):
    rom,root,exe=cheat_project
    path=catalog(tmp_path,rom,'cheat "Invalid"\n'+operation+'\nend\n')
    assert message in execute(exe,root,'--cheats',path,'--save',tmp_path/'bad.sav',ok=False)
    assert not (tmp_path/'bad.sav').exists()


def test_catalog_identity_and_unknown_names_fail(tmp_path,cheat_project):
    rom,root,exe=cheat_project
    path=catalog(tmp_path,rom,'cheat "Value"\nwrite32 0x02010004 42\nend\n')
    assert 'unknown cheat name' in execute(exe,root,'--cheats',path,'--enable-cheat','Unknown',ok=False)
    path.write_text(path.read_text().replace(hashlib.sha256(rom.read_bytes()).hexdigest(),'0'*64))
    assert 'ROM SHA-256 mismatch' in execute(exe,root,'--cheats',path,ok=False)
