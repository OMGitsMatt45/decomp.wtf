"""Code/data boundaries and service authorization use the original input identity."""
import copy
import hashlib
import json
import struct

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native import profile
from tests.fixtures.ps2_native import BASE,program


def test_original_symbol_map_is_complete_and_stripped_bytes_need_review():
    original,_,entries=program()
    mapping=profile.module(original)
    assert {f['address'] for f in mapping['functions']}==set(entries.values())
    stripped=bytearray(original)
    table=struct.unpack_from('<I',stripped,32)[0]
    struct.pack_into('<I',stripped,table+4*40+4,1) # .symtab becomes data
    recovered=profile.module(stripped)
    assert recovered['recovery']['method']=='bounded-closed-reachable-cfg'
    assert recovered['functions']==[dict(name=f'function_{BASE:08x}',address=BASE,size=12)]


def test_profile_rejects_changed_input_or_code_crossing_data(tmp_path):
    original=program()[0];mapping=profile.module(original)
    bad=copy.deepcopy(mapping);bad['sha256']='0'*64
    with pytest.raises(PCError,match='SHA-256'):profile.module(original,bad)
    bad=copy.deepcopy(mapping);bad['code_ranges']=[dict(address=BASE,size=4)]
    with pytest.raises(PCError,match='code/data boundary'):profile.module(original,bad)
    bad=copy.deepcopy(mapping);bad['native_services']=[dict(address=BASE+4,name='fioRead')]
    with pytest.raises(PCError,match='mapped SDK'):profile.module(original,bad)
    recipe=tmp_path/'profile.json'
    recipe.write_text(json.dumps(dict(schema=profile.SCHEMA,input_sha256='0'*64,modules=[dict(path='original.elf')])))
    with pytest.raises(PCError,match='original input SHA-256'):profile.load(recipe,hashlib.sha256(original).hexdigest())


def test_asset_staging_is_atomic_and_preserves_existing_saves(tmp_path):
    from decompnet.ps2_native.extract_assets import stage
    original,_,_=program()
    owner=tmp_path/'owner.elf';owner.write_bytes(original)
    root=tmp_path/'source';(root/'game').mkdir(parents=True);(root/'saves').mkdir()
    save=root/'saves/important';save.write_bytes(b'keep')
    recipe=dict(schema='decomp.wtf.ps2-assets/v1',kind='ee-elf',input=dict(size=len(original),sha256=hashlib.sha256(original).hexdigest()),extract=[])
    (root/'game/assets.json').write_text(json.dumps(recipe))
    wrong=tmp_path/'wrong.elf';wrong.write_bytes(original+b'changed')
    with pytest.raises(ValueError,match='differs'):stage(wrong,root)
    assert not (root/'assets').exists() and save.read_bytes()==b'keep'
    stage(owner,root)
    assert (root/'assets/cd/boot.elf').read_bytes()==original
    with pytest.raises(ValueError,match='already exist'):stage(owner,root)
    assert save.read_bytes()==b'keep'


def test_extracted_dvd_staging_verifies_payload_and_preserves_saves(tmp_path):
    from decompnet.ps2_native.extract_assets import stage

    owner = tmp_path/'owner'
    (owner/'BIN').mkdir(parents=True)
    (owner/'BOOT.ELF').write_bytes(b'boot')
    (owner/'BIN/DATA.BIN').write_bytes(b'good')
    (owner/'NOEXT').write_bytes(b'bare')
    (owner/'extraneous-save').write_bytes(b'private')
    root = tmp_path/'source'
    (root/'game').mkdir(parents=True)
    (root/'saves').mkdir()
    save = root/'saves/important'
    save.write_bytes(b'keep')
    files = [dict(path=name, size=4, sha256=hashlib.sha256((owner/name).read_bytes()).hexdigest())
             for name in ('BOOT.ELF', 'BIN/DATA.BIN')]
    files.append(dict(path='NOEXT.', size=4, sha256=hashlib.sha256(b'bare').hexdigest()))
    recipe = dict(schema='decomp.wtf.ps2-assets/v1', kind='disc', sector_size=2048,
                  sector_data_offset=0, disc_medium='dvd',
                  input=dict(size=128*2048, sha256='0'*64), extract=[],
                  directory=dict(sectors=128, files=files))
    recipe_path = root/'game/assets.json'
    recipe_path.write_text(json.dumps(recipe), encoding='utf-8')

    with pytest.raises(ValueError, match='choose either'):
        stage(owner, root, reference=True, directory=True)

    (owner/'BIN/DATA.BIN').write_bytes(b'bad!')
    with pytest.raises(ValueError, match='hash differs'):
        stage(owner, root, directory=True)
    assert not (root/'assets').exists() and save.read_bytes() == b'keep'

    (owner/'BIN/DATA.BIN').write_bytes(b'good')
    files.append(dict(files[0], path='../BOOT.ELF'))
    recipe_path.write_text(json.dumps(recipe), encoding='utf-8')
    with pytest.raises(ValueError, match='escapes'):
        stage(owner, root, directory=True)
    assert not (root/'assets').exists()
    files.pop()
    recipe_path.write_text(json.dumps(recipe), encoding='utf-8')

    assets = stage(owner, root, directory=True)
    assert (assets/'disc.directory').read_bytes() == b'128\n'
    assert (assets/'cd/BOOT.ELF').read_bytes() == b'boot'
    assert (assets/'cd/BIN/DATA.BIN').read_bytes() == b'good'
    assert (assets/'cd/NOEXT.').read_bytes() == b'bare'
    assert sorted(p.name for p in assets.iterdir()) == ['cd', 'disc.directory', 'identity.json']
    assert not (assets/'cd/extraneous-save').exists()
    assert save.read_bytes() == b'keep'


def test_directory_recipe_requires_disjoint_sector_extents():
    from decompnet.ps2_native import _disjoint_extents

    first = dict(lba=20, size=2049)
    assert _disjoint_extents([dict(lba=22, size=1), first, dict(lba=20, size=0)])
    assert not _disjoint_extents([first, dict(lba=21, size=1)])


def test_typed_analysis_preserves_load_images_and_explicit_late_entries():
    from decompnet.ps2_native.media import elf_info
    from decompnet.ps2_native.modules import typed_elf
    raw=bytearray(program()[0]);table=struct.unpack_from('<I',raw,32)[0]
    struct.pack_into('<I',raw,table+40+8,3) # container describes bytes as data
    info=elf_info(raw);assert not info['executable_sections']
    ranges=[dict(address=BASE,size=12),dict(address=BASE+0x1200,size=12)]
    typed=typed_elf(raw,ranges);converted=elf_info(typed)
    assert [(s['address'],s['size']) for s in converted['executable_sections']]==[(s['address'],s['size']) for s in ranges]
    assert [(s['address'],s['memory_size'],s['sha256']) for s in converted['loads']]==[
        (s['address'],s['memory_size'],s['sha256']) for s in info['loads']]
    assert converted['entry']==info['entry']
    reviewed=dict(sha256=info['sha256'],functions=[dict(name='entry',address=BASE,size=12)],code_ranges=ranges,native_services=[])
    assert profile.module(raw,reviewed)['functions']==reviewed['functions']


def test_optional_profile_requires_the_exact_full_original_hash():
    assert profile.known('0'*64) is None
    data=profile.known('a38f71b7a02f1ae0fe65cc78137ee9c943b75b44473ae1cd5ed89ef0e61400e9')
    assert len(data['modules'])==7
    assert len(data['modules'][0]['native_services'])==237
    assert sum(len(m['functions']) for m in data['modules'])==12421
    assert any(f['address']==0x002d0df0 for f in data['modules'][0]['functions'])
