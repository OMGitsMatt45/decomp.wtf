"""Bound runtime coverage hints to the exact owner image, never qualification."""
import hashlib
import json
from pathlib import Path

from ..pc import PCError

MAX_REPORT = 1024*1024
MAX_ENTRIES = 4096


def load(paths, inspection):
    paths=list(paths)
    if len(paths)>32:raise PCError('3DS feedback accepts at most 32 reports')
    text=inspection['segments'][0]
    entries=set();reports=[]
    for path in paths:
        try:
            with Path(path).open('rb') as stream:raw=stream.read(MAX_REPORT+1)
            if len(raw)>MAX_REPORT:raise PCError('3DS feedback report exceeds 1 MiB')
            report=json.loads(raw)
        except (OSError,ValueError) as error:
            raise PCError('cannot read 3DS coverage feedback: '+str(error)) from error
        if not isinstance(report,dict) or report.get('schema')!='decomp.wtf.3ds-runtime-run/v1':
            raise PCError('3DS feedback must be a runtime execution report')
        if report.get('input_sha256')!=inspection['input']['sha256']:
            raise PCError('3DS feedback input SHA-256 differs from the owner image')
        if type(report.get('interpreter_allowed')) is not bool or type(report.get('interpreted_instructions')) is not int or report['interpreted_instructions']<0:
            raise PCError('3DS feedback must declare interpreter use')
        if not report['interpreter_allowed'] and report['interpreted_instructions']:
            raise PCError('3DS feedback has inconsistent interpreter counters')
        if type(report.get('rejected_instructions')) is not int or report['rejected_instructions']!=0:
            raise PCError('3DS feedback cannot repair an unsupported inline instruction')
        misses=report.get('static_misses')
        if not isinstance(misses,list) or not misses or len(misses)>MAX_ENTRIES:
            raise PCError('3DS feedback needs 1 through 4096 missing native targets')
        for target in misses:
            if (type(target) is not int or not 0<=target<=0xffffffff
                    or (not (target&1) and target%4!=0)
                    or text['address']>(target&~1)
                    or (target&~1)+(2 if target&1 else 4)>text['address']+text['size']):
                raise PCError('3DS feedback target is outside the main executable or misaligned; relocated module feedback is not supported')
            entries.add(target)
        if len(entries)>MAX_ENTRIES:raise PCError('combined 3DS feedback exceeds 4096 entries')
        reports.append(dict(sha256=hashlib.sha256(raw).hexdigest(),
            interpreter_allowed=report['interpreter_allowed'],
            interpreted_instructions=report['interpreted_instructions'],
            coverage_truncated=bool(report.get('coverage_truncated',False))))
    return entries,reports
