"""Original, non-retail 3DS inputs exercise loading and actual native output."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from decompnet import pc
from decompnet.ctr_native import export_probe, media, provider
from decompnet.rom import detect
from decompnet.rom.errors import RomError
from tools.ctr_fixture import BASE, cartridge, fixture


@pytest.mark.parametrize('wrapped', [False, True], ids=['ncch','ncsd'])
def test_original_executable_layout_identity_and_native_routing(tmp_path, wrapped):
    raw=fixture()
    if wrapped:
        raw=cartridge(raw)
    path=tmp_path/'unnamed.bin';path.write_bytes(raw)
    result=media.load(path, include_code=True)
    assert result['entry']==BASE and result['input']['sha256']==hashlib.sha256(raw).hexdigest()
    assert result['segments'][0]['size']==16
    assert [s['access'] for s in result['segments']]==['rx','r','rw']
    assert result['code'][:4]==struct.pack('<I',0xe3a00007)
    assert result['native_game_backend_available'] is True
    assert pc.input_platform(path)=='3ds'
    with pytest.raises(RomError,match='3DS support is in development'):
        detect.identify(path)
    assert path.read_bytes()==raw


@pytest.mark.parametrize('change', ['encrypted','size','exefs','code-checksum','segment-overlap','pages','code-size','missing-code'])
def test_malformed_and_encrypted_inputs_fail_before_any_tool_or_output(tmp_path, change, monkeypatch):
    raw=bytearray(fixture())
    if change=='encrypted':raw[0x18f]=0
    elif change=='size':struct.pack_into('<I',raw,0x104,0x7fffffff)
    elif change=='exefs':struct.pack_into('<I',raw,0x1a0,0x7fffffff)
    elif change=='code-checksum':raw[0xc00]^=1
    elif change=='segment-overlap':struct.pack_into('<I',raw,0x220,BASE)
    elif change=='pages':struct.pack_into('<I',raw,0x214,0x100000)
    elif change=='code-size':struct.pack_into('<I',raw,0xa0c,0x7fffffff)
    elif change=='missing-code':raw[0xa00:0xa08]=b'other\0\0\0'
    path=tmp_path/'input.cxi';path.write_bytes(raw)
    monkeypatch.setattr(provider,'download',lambda *_a,**_k:pytest.fail('must validate before tool installation'))
    monkeypatch.setattr(provider,'build',lambda *_a,**_k:pytest.fail('must validate before tool execution'))
    with pytest.raises(pc.PCError):export_probe(path,tmp_path/'output')
    assert not (tmp_path/'output').exists()
    assert path.read_bytes()==raw


def test_partition_overlap_is_rejected(tmp_path):
    raw=bytearray(cartridge(fixture()))
    struct.pack_into('<II',raw,0x128,0x20,1)
    path=tmp_path/'bad.3ds';path.write_bytes(raw)
    with pytest.raises(pc.PCError,match='partitions overlap'):media.load(path)


def test_streamed_source_has_the_same_validated_identity_as_a_file(tmp_path):
    from io import BytesIO
    from types import SimpleNamespace
    raw=cartridge(fixture('thumb'))
    class Source:
        def stat(self):return SimpleNamespace(st_size=len(raw))
        def open(self,mode):
            assert mode=='rb'
            return BytesIO(raw)
    path=tmp_path/'original.3ds';path.write_bytes(raw)
    assert media.load_source(Source(),include_code=True)==media.load(path,include_code=True)


def test_blz_backwards_references_have_an_independent_expected_result():
    # Three literal bytes followed backwards by 18-byte and 9-byte copies.
    packed=b'\x00\x60\x00\xf0ABC\x18'+struct.pack('<II',0x08000010,14)
    assert media.decompress(packed,expected=30)==b'ABC'*10
    for bad in (packed[:-1], packed[:-4]+struct.pack('<I',0x7fffffff), b'0'*8):
        with pytest.raises(pc.PCError):media.decompress(bad,expected=30)
    broken=bytearray(packed);broken[2]=0xff
    with pytest.raises(pc.PCError,match='reads beyond'):media.decompress(broken,expected=30)


def test_independently_compressed_original_executable_has_exact_instruction_and_data_bytes():
    from io import BytesIO
    from types import SimpleNamespace
    original=fixture('arm')
    expected=original[0xc00:0xc00+int.from_bytes(original[0xa0c:0xa10],'little')]
    raw=fixture('blz-arm')
    source=SimpleNamespace(stat=lambda:SimpleNamespace(st_size=len(raw)),open=lambda mode:BytesIO(raw))
    loaded=media.load_source(source,include_code=True)
    assert loaded['compressed'] and loaded['code']==expected


def test_blz_accepts_final_data_page_padding_but_not_output_beyond_allocation(tmp_path):
    # Independently encode ABC repeated across all three allocated pages. The
    # final data segment uses four bytes; its remaining page is still in .code.
    tokens=[b'C',b'B',b'A']
    remaining=0x3000-3
    while remaining:
        count=min(18,remaining)
        assert count>=3
        tokens.append(struct.pack('<H',(count-3)<<12))
        remaining-=count
    groups=[]
    for at in range(0,len(tokens),8):
        group=tokens[at:at+8]
        flags=sum(1<<(7-i) for i,token in enumerate(group) if len(token)==2)
        groups.append(b''.join(reversed(group))+bytes([flags]))
    packed=b''.join(reversed(groups))
    packed+=struct.pack('<II',0x08000000|(len(packed)+8),0x3000-(len(packed)+8))
    assert media.decompress(packed,expected=0x3000)==b'ABC'*0x1000
    raw=bytearray(fixture());raw[0x20d]=1
    struct.pack_into('<I',raw,0xa0c,len(packed))
    raw[0xbe0:0xc00]=hashlib.sha256(packed).digest()
    raw[0xc00:0xc00+len(packed)]=packed
    path=tmp_path/'padded.cxi';path.write_bytes(raw)
    assert media.load(path,include_code=True)['code']==b'ABC'*0x1000
    # A footer that requests another page remains outside the validated layout.
    packed=packed[:-4]+struct.pack('<I',0x4000-len(packed))
    raw[0xbe0:0xc00]=hashlib.sha256(packed).digest()
    raw[0xc00:0xc00+len(packed)]=packed
    path.write_bytes(raw)
    with pytest.raises(pc.PCError,match='decompressed size is invalid'):media.load(path)


def test_3ds_game_backend_is_explicitly_experimental_and_status_does_not_install(monkeypatch):
    monkeypatch.setattr(provider,'download',lambda *_a,**_k:pytest.fail('status must not install'))
    status=pc.status('3ds')
    assert status['available'] and status['experimental']
    assert status['backends'][0]['id']=='3ds-native-3dsrecomp-zakuro'
    assert not status['console_reconstruction_is_pc_output']


def test_inspect_cli_and_preserved_destination(tmp_path,capsys):
    from decompnet.cli import main
    path=tmp_path/'original.cxi';path.write_bytes(fixture())
    assert main(['pc','ctr-inspect',str(path)])==0
    assert json.loads(capsys.readouterr().out)['platform']=='3ds'
    target=tmp_path/'keep';target.mkdir();(target/'source.c').write_text('owner edits')
    with pytest.raises(pc.PCError,match='existing work'):export_probe(path,target)
    assert (target/'source.c').read_text()=='owner edits'


@pytest.fixture(scope='module')
def native_tools():
    rust=os.environ.get('DECOMP_3DS_RUSTC') or shutil.which('rustc')
    cmake=shutil.which('cmake')
    if not rust or not cmake:
        if os.environ.get('DECOMP_TEST_3DS_NATIVE')=='1':
            pytest.fail('required 3DS native test needs Rust and CMake')
        pytest.skip('3DS native execution needs Rust 1.88+, CMake and a host C/C++ compiler')
    return cmake


def build_original(tmp_path, kind, cmake):
    path=tmp_path/(kind+'.cxi');path.write_bytes(fixture(kind))
    out=tmp_path/('source '+kind)
    result=export_probe(path,out)
    assert result['manifest']['output_kind']=='cpu-probe'
    assert not result['manifest']['fallback']['interpreter']
    assert not result['presentation_declared']
    for command in ([cmake,'-S',str(out),'-B',str(out/'build')],
                    [cmake,'--build',str(out/'build'),'--config','Release','--parallel','2']):
        step=subprocess.run(command,capture_output=True,text=True,timeout=180)
        assert step.returncode==0,step.stdout+step.stderr
    candidates=list((out/'build').rglob('ctr_probe.exe' if os.name=='nt' else 'ctr_probe'))
    binary=next(p for p in candidates if p.is_file())
    return out,binary


def test_input_bound_coverage_recovers_a_hidden_thumb_callback(tmp_path,native_tools):
    _original,binary=build_original(tmp_path,'hidden-callback',native_tools)
    failed=subprocess.run([str(binary),str(_original/'assets')],capture_output=True,text=True,timeout=15)
    assert failed.returncode!=0 and 'untranslated' in failed.stderr
    image=tmp_path/'hidden-callback.cxi'
    feedback=tmp_path/'compatibility coverage.json'
    feedback.write_text(json.dumps(dict(schema='decomp.wtf.3ds-runtime-run/v1',
        input_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),static_misses=[BASE+0x19],
        interpreter_allowed=True,interpreted_instructions=2,rejected_instructions=0)))
    out=tmp_path/'regenerated source'
    export_probe(image,out,feedback=[feedback])
    metadata=json.loads((out/'analysis.json').read_text())['coverage']
    assert metadata['entries']==[BASE+0x19] and metadata['reports'][0]['interpreted_instructions']==2
    for args in ([native_tools,'-S',out,'-B',out/'build'],
                 [native_tools,'--build',out/'build','--config','Release']):
        step=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=180)
        assert step.returncode==0,step.stdout+step.stderr
    executable=next(p for p in (out/'build').rglob('ctr_probe.exe' if os.name=='nt' else 'ctr_probe') if p.is_file())
    result=subprocess.run([str(executable),str(out/'assets')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['process_exited'] and report['r0']==42 and report['interpreted_instructions']==0


@pytest.mark.parametrize('bad',['identity','schema','range','alignment','boolean','count','inline','counters','json','size'])
def test_invalid_coverage_fails_before_tools_or_output(tmp_path,monkeypatch,bad):
    image=tmp_path/'original.cxi';image.write_bytes(fixture())
    data=dict(schema='decomp.wtf.3ds-runtime-run/v1',input_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
              static_misses=[BASE],interpreter_allowed=False,interpreted_instructions=0,rejected_instructions=0)
    if bad=='identity':data['input_sha256']='0'*64
    elif bad=='schema':data['schema']='other'
    elif bad=='range':data['static_misses']=[0]
    elif bad=='alignment':data['static_misses']=[BASE+2]
    elif bad=='boolean':data['static_misses']=[True]
    elif bad=='count':data['static_misses']=[BASE]*4097
    elif bad=='inline':data['rejected_instructions']=1
    elif bad=='counters':data['interpreted_instructions']=1
    feedback=tmp_path/'coverage.json'
    feedback.write_text('{' if bad=='json' else ' '*1048577 if bad=='size' else json.dumps(data))
    monkeypatch.setattr(provider,'build',lambda *_a,**_k:pytest.fail('feedback must validate before tools'))
    with pytest.raises(pc.PCError):export_probe(image,tmp_path/'output',feedback=[feedback])
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize(('kind','expected'), [('arm',12),('blz-arm',12),('thumb',42),('vfp',0x40000000),('bss',0),('data-callback',42),('relative-callbacks',42)])
def test_translated_original_3ds_program_builds_and_executes(tmp_path,native_tools,kind,expected):
    out,binary=build_original(tmp_path,kind,native_tools)
    result=subprocess.run([str(binary),str(out/'assets')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['process_exited'] and report['r0']==expected and report['native_instructions']>0
    assert report['interpreted_instructions']==0 and report['retail_qualified'] is False
    if kind in ('arm','blz-arm','thumb','vfp','relative-callbacks'):
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_INTR
        from unicorn.arm_const import UC_ARM_REG_C1_C0_2,UC_ARM_REG_FPEXC,UC_ARM_REG_R0
        reference=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        reference.mem_map(BASE,0x4000)
        reference.mem_write(BASE,media.load(tmp_path/(kind+'.cxi'),include_code=True)['code'])
        reference.reg_write(UC_ARM_REG_C1_C0_2,0x00f00000)
        reference.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        reference.hook_add(UC_HOOK_INTR,lambda cpu,*_:cpu.emu_stop())
        reference.emu_start(BASE,BASE+0x1000,count=100)
        assert reference.reg_read(UC_ARM_REG_R0)==report['r0']
    if kind=='blz-arm':
        from decompnet import toolchains
        sdk=Path(os.environ.get('DECOMP_3DS_SDK') or toolchains.root()/'3dsrecomp-sdk')
        rust=os.environ.get('DECOMP_3DS_RUSTC') or shutil.which('rustc')
        decoder=provider.build(sdk,tmp_path/'independent decoder',rust)
        packed=tmp_path/'original.blz'
        packed.write_bytes(bytes.fromhex(Path(__file__).parents[1].joinpath('tools/fixtures/ctr-arm-code.blz.hex').read_text()))
        decoded=tmp_path/'independent code.bin'
        step=subprocess.run([str(decoder),'--decode-blz',str(packed),str(decoded)],capture_output=True,text=True,timeout=60)
        assert step.returncode==0,step.stderr
        assert decoded.read_bytes()==media.load(tmp_path/'blz-arm.cxi',include_code=True)['code']
    if kind=='arm':
        # C source is the executed product: editing it changes the native result.
        source=out/'game/code000.c';text=source.read_text()
        assert text.count('0x00000007u')==1
        source.write_text(text.replace('0x00000007u','0x00000008u'))
        built=subprocess.run([native_tools,'--build',str(out/'build'),'--config','Release'],capture_output=True,text=True,timeout=90)
        assert built.returncode==0,built.stdout+built.stderr
        edited=subprocess.run([str(binary),str(out/'assets')],capture_output=True,text=True,timeout=15)
        assert edited.returncode==0 and json.loads(edited.stdout)['r0']==13
    # Owner assets are bound at runtime as well as by pc verify.
    code=out/'assets/text.bin';raw=code.read_bytes();code.write_bytes(bytes([raw[0]^1])+raw[1:])
    result=subprocess.run([str(binary),str(out/'assets')],capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'identity differs' in result.stderr


@pytest.mark.parametrize(('kind','message'), [('unsupported-service','unimplemented 3DS kernel service'),
    ('unknown-target','untranslated ARM11 target'),('unsupported-opcode','unsupported ARM11 instruction'),
    ('read-only-write','read-only 3DS memory'),('loop','budget')])
def test_guards_never_fall_back_to_an_interpreter(tmp_path,native_tools,kind,message):
    out,binary=build_original(tmp_path,kind,native_tools)
    result=subprocess.run([str(binary),str(out/'assets'),'100'],capture_output=True,text=True,timeout=15)
    if message=='budget':
        assert result.returncode==2 and json.loads(result.stdout)['process_exited'] is False
    else:
        assert result.returncode==1 and message in result.stderr
