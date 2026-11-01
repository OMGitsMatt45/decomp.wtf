"""Project-owned features run independently of the optional cheat menu."""
import subprocess

from .test_nds_native import generate,execute,sdk  # noqa: F401
from .fixtures.nds_native import dual_cpu


def test_project_hooks_run_before_boot_and_after_every_frame(tmp_path,tmp_path_factory,sdk):
    _,root,exe=generate(tmp_path_factory.mktemp('hooks')/'p',dual_cpu)
    baseline=execute(exe,root,'--save',tmp_path/'baseline.sav')
    (root/'native/project_features.hpp').write_text('''#pragma once
namespace ds_project {
struct Features {
 unsigned frames=0,inputs=0;bool started=false;
 void start(dsr::Session&,const dsr::MachineConfig&){started=true;}
 bool input(dsr::Session&,dsr::InputState&){++inputs;return true;}
 void frame(dsr::Session& session,const dsr::InputState&) {
  if(!started)throw std::runtime_error("feature start was skipped");
  ++frames;session.machine().write32(dsr::CpuId::Arm9,0x02010000,frames+100);
 }
 void report(std::ostream& out)const{out<<",\\\"original_feature\\\":{"<<"\\\"frames\\\":"<<frames<<",\\\"inputs\\\":"<<inputs<<"}";}
};
}
''')
    done=subprocess.run(['cmake','--build',str(root/'build'),'--config','Release','--parallel','2'],capture_output=True,text=True,timeout=240)
    assert done.returncode==0,done.stdout+done.stderr
    report=execute(exe,root,'--save',tmp_path/'featured.sav')
    assert report['original_feature']==dict(frames=8,inputs=8)
    assert report['cheats']['enabled']==0
    assert report['observed'][0]==108
    assert baseline['observed'][0]!=108
    assert report['frames']==baseline['frames']==8
    path=root/'native/project_features.hpp'
    path.write_text(path.read_text().replace('++inputs;return true','++inputs;return inputs<=3'))
    assert '++inputs;return inputs<=3' in path.read_text()
    # This fixture checks hook behavior, not incremental dependency tracking.
    # MSBuild on CI can reuse the previous object after a rapid header edit,
    # even with an explicitly newer mtime. Build the edited fixture afresh.
    done=subprocess.run(['cmake','--build',str(root/'build'),'--config','Release','--clean-first','--parallel','2'],capture_output=True,text=True,timeout=240)
    assert done.returncode==0,done.stdout+done.stderr
    stopped=execute(exe,root,'--save',tmp_path/'stopped.sav')
    assert stopped['frames']==3 and stopped['original_feature']==dict(frames=3,inputs=4), (stopped,done.stdout,done.stderr)
