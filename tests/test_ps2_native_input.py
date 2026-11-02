"""The host test pad retains holds in guest time and preserves real input."""
from pathlib import Path
import shutil
import subprocess

import pytest
from tools.qualify_ps2_runtime import executable


def test_native_command_pad_holds_edges_bounds_and_file_input(tmp_path):
    if not shutil.which('cmake'):
        pytest.skip('requires CMake and a C++20 compiler')
    header=Path(__file__).parents[1]/'src/decompnet/ps2_native/command_pad.hpp'
    shutil.copyfile(header,tmp_path/'command_pad.hpp')
    (tmp_path/'main.cpp').write_text('''#include "command_pad.hpp"
int main(int argc,char**argv){
    decomp_ps2::CommandPad pad;uint32_t held=0x2000,pressed=0x2000;
    pad.accept("1 UP+CROSS 30",100);pad.merge(100,held,pressed);
    if(held!=0x6010||pressed!=0x6010)return 1;
    held=pressed=0;pad.merge(129,held,pressed);
    if(held!=0x4010||pressed)return 2;
    held=pressed=0;pad.merge(130,held,pressed);if(held||pressed)return 3;
    pad.accept("1 UP+CROSS 30",200);pad.merge(200,held,pressed);if(held||pressed)return 4;
    for(const auto*bad:{"2 UP 0","2 UP 3601","2 UNKNOWN 2","2 UP+ 2","2 UP 2 extra"}){
        bool rejected=false;try{pad.accept(bad,200);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected)return 5;
    }
    pad.accept("2 LEFT 20",200);pad.accept("3 NONE 1",201);
    held=pressed=0;pad.merge(201,held,pressed);if(held||pressed)return 6;
    decomp_ps2::CommandPad file;file.sample(argv[1],500,held,pressed);
    if(held!=0x40||pressed!=0x40)return 7;
    held=pressed=0;file.merge(509,held,pressed);if(held!=0x40||pressed)return 8;
    held=pressed=0;file.merge(510,held,pressed);return held||pressed?9:0;
}
''')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(PadProbe LANGUAGES CXX)\nadd_executable(pad_probe main.cpp)\ntarget_compile_features(pad_probe PRIVATE cxx_std_20)\n')
    build=tmp_path/'build'
    for args in (['cmake','-S',str(tmp_path),'-B',str(build)],
                 ['cmake','--build',str(build),'--config','Release']):
        result=subprocess.run(args,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
    command=tmp_path/'pad.txt';command.write_text('1 DOWN 10\n')
    subprocess.run([str(executable(build,'pad_probe')),str(command)],check=True,timeout=10)
