"""Original native file views cover CD sector gaps, EOF and 64-bit extents."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.qualify_ps2_runtime import executable


@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    if not shutil.which('cmake'): pytest.skip('disc file views require CMake and a native compiler')
    root=tmp_path_factory.mktemp('PS2 disc views with spaces')
    shutil.copyfile(Path(__file__).parents[1]/'src/decompnet/ps2_native/disc_files.hpp',root/'disc_files.hpp')
    (root/'main.cpp').write_text(r'''#include "disc_files.hpp"
#include <array>
#include <vector>
int main(int argc,char **argv) {
 if(argc!=5)return 1;
 using namespace decomp_ps2::disc;
 const unsigned sector=static_cast<unsigned>(std::stoul(argv[2])),skip=static_cast<unsigned>(std::stoul(argv[3]));
 const uint64_t lba=std::stoull(argv[4]);
 Entry entries[]={{"DIR/ORIGINAL.BIN",lba,3000}};
 mount(argv[1],entries,sector,skip);
 FILE *file=open("absent-original.bin","rb",R"(cdrom0:\dir\original.bin;1)");
 if(!file)return 2;
 std::array<uint8_t,4000> data; data.fill(0xa5);
 if(read(data.data(),1,data.size(),file)!=3000 || tell(file)!=3000)return 3;
 for(unsigned n=0;n<3000;n++)if(data[n]!=n%251)return 4;
 if(data[3000]!=0xa5 || read(data.data(),1,1,file)!=0)return 5;
 if(seek(file,-7,SEEK_END) || read(data.data(),1,100,file)!=7 || data[0]!=2993%251 || tell(file)!=3000)return 6;
 if(seek(file,100,SEEK_END)||read(data.data(),1,100,file)!=0 || tell(file)!=3100)return 7;
 if(seek(file,INT64_MIN,SEEK_CUR)!=-1 || tell(file)!=3100)return 8;
 bool rejected=false;
 try {mount(argv[1],entries,sector,skip);}catch(const std::runtime_error&){rejected=true;}
 if(!rejected)return 9;
 if(close(file))return 10;
 if(open("absent-original.bin","wb",R"(cdrom0:\dir\original.bin;1)") || errno!=EROFS)return 11;
 if(open("absent-original.bin","rb",R"(cdrom0:\..\dir\original.bin;1)"))return 12;
 if(open("absent-original.bin","rb",R"(cdrom0:\dir\unknown.bin;1)"))return 13;
 mount(argv[1],entries,sector,skip);
 file=open("native-save.bin","wb+","mc0:/SAVE");
 if(!file)return 14;
 const char value[]="original save";
 if(std::fwrite(value,1,sizeof(value),file)!=sizeof(value) || seek(file,0,SEEK_SET))return 15;
 if(read(data.data(),1,sizeof(value),file)!=sizeof(value)||std::memcmp(data.data(),value,sizeof(value)))return 16;
 if(close(file))return 17;
 Entry bad[]={{"OUTSIDE.BIN",lba+100,3000}};rejected=false;
 try{mount(argv[1],bad,sector,skip);}catch(const std::runtime_error&){rejected=true;}
 return rejected?0:18;
}
''',encoding='utf-8')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(DiscViews LANGUAGES CXX)\n'
        'add_executable(disc_views main.cpp)\ntarget_compile_features(disc_views PRIVATE cxx_std_20)\n')
    build=root/'build'
    for step,cmd in (('configure',['cmake','-S',root,'-B',build]),('build',['cmake','--build',build,'--config','Release'])):
        result=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=120)
        (root/(step+'.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stdout+result.stderr
    return executable(build,'disc_views')


@pytest.mark.parametrize('sector,skip,high',[(2048,0,False),(2352,16,False),(2352,24,False),(2336,8,False),(2048,0,True)])
def test_native_iso_and_raw_disc_views_do_not_read_neighbouring_files(probe,tmp_path,sector,skip,high):
    image=tmp_path/'original disc.bin'
    lba=(1<<32)//2048+3 if high else 3
    original=bytes(n%251 for n in range(3000))
    with image.open('w+b') as out:
        if high and os.name=='nt':
            import msvcrt
            returned=ctypes.c_uint32()
            assert ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(out.fileno())),
                ctypes.c_uint32(0x900C4),None,0,None,0,ctypes.byref(returned),None)
        out.truncate((lba+3)*sector)
        for n in range(2):
            out.seek((lba+n)*sector+skip);out.write(original[n*2048:(n+1)*2048])
        out.seek((lba+1)*sector+skip+952);out.write(b'NEIGHBOUR-MUST-STAY-PRIVATE')
    result=subprocess.run([probe,image,str(sector),str(skip),str(lba)],cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,(result.returncode,result.stderr)
    with image.open('rb') as stream:
        stream.seek((lba+1)*sector+skip+952)
        assert stream.read(len(b'NEIGHBOUR-MUST-STAY-PRIVATE'))==b'NEIGHBOUR-MUST-STAY-PRIVATE'
