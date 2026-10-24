"""Qualify an exported PS2 project on the user's local graphics hardware."""
import argparse
import json
from pathlib import Path
import platform

from tools.ps2_hardware import selected_device,vulkan_devices
from tools.qualify_ps2_port import qualify


def assess(destination,*,sdk=None,allow_software=False):
    out=Path(destination).resolve()
    if out.exists():raise ValueError('choose a new assessment directory; existing work is preserved')
    out.mkdir(parents=True)
    report=dict(schema='decomp.wtf.ps2-hardware-assessment/v1',host=platform.platform(),
        hardware_qualified=False,original_fixture_passed=False,retail=False,manual_gameplay=False)
    try:
        report['vulkan_devices']=vulkan_devices()
        if not allow_software and not any(d['device_type'] in (1,2) for d in report['vulkan_devices']):
            raise ValueError('no integrated/discrete Vulkan GPU was found; software rendering cannot qualify physical hardware')
        result=qualify(out/'Original standalone fixture',sdk=sdk,execute=True)
        report['original_fixture_passed']=True
        report['selected_device']=selected_device(report['vulkan_devices'],result['runs']['vulkan']['run'])
        report['hardware_qualified']=report['selected_device']['physical']
        report['backend_revision']=result['backend_revision']
        if not report['hardware_qualified'] and not allow_software:raise ValueError(report['selected_device']['reason'])
        return report
    except Exception as error:
        report['error']=str(error)
        raise
    finally:(out/'hardware-assessment.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--sdk-root',type=Path)
    parser.add_argument('--allow-software',action='store_true',help='developer comparison only; never marks a CPU/virtual device as physical hardware')
    args=parser.parse_args()
    print(json.dumps(assess(args.destination,sdk=args.sdk_root,allow_software=args.allow_software),indent=2))
