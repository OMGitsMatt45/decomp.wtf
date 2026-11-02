"""Retain pending internal calls when a shared body crosses its code region.

The pinned emitter inlines same-region calls into one C++ dispatcher. An
outgoing tail therefore may still owe an internal return. Conversely, a
reentrant invocation must return to its host caller when the guest returns to
the invocation's incoming LR, even if that address belongs to this region.
"""
import re


def rewrite(code,begin,end,thumb):
    anchor='    bool dispatch_first_block = true;\n'
    if code.count(anchor)!=1:raise ValueError('Pinned shared-call entry anchor differs')
    code=code.replace(anchor,'    const std::uint32_t dispatch_entry_lr = c->r[14];\n'+anchor)
    first=re.search(r'^L_[0-9a-f]{8}: ;$',code,re.M)
    if first is None:raise ValueError('Shared body has no decoded instruction label')
    header,body=code[:first.start()],code[first.start():]
    outgoing='        ::dsr::dsr_call(c, dispatch_target);\n        return;'
    if header.count(outgoing)!=2:raise ValueError('Pinned shared-call dispatcher exits differ')
    resume=('        const std::uint32_t dispatch_link = c->r[14];\n'
        '        ::dsr::dsr_call(c, dispatch_target);\n'
        f'        if (dispatch_link != dispatch_entry_lr && (dispatch_link & 1u) == {int(thumb)}u && '
        f'(dispatch_link & ~1u) >= 0x{begin:08x}u && (dispatch_link & ~1u) < 0x{end:08x}u) {{\n'
        '            dispatch_target = dispatch_link;\n'
        '            goto L_region_dispatch;\n'
        '        }\n'
        '        return;')
    header=header.replace(outgoing,resume)
    # Restrict this guard to actual return paths, not ordinary internal calls.
    pattern=(r'(if \()(?=\(dispatch_target & 1u\) == [01]u && '
        r'\(dispatch_target & ~1u\) >= 0x[0-9a-f]+u && '
        r'\(dispatch_target & ~1u\) < 0x[0-9a-f]+u\) goto L_region_dispatch;\n\s*DSR_RET)')
    body=re.sub(pattern,r'\1dispatch_target != dispatch_entry_lr && ',body)
    return header+body


def install(emitter):
    cls=emitter.FunctionEmitter
    if getattr(cls,'_decomp_shared_calls_fixed',False):return
    original=cls.emit
    def emit(self):
        code=original(self)
        if self.dispatch_entries is None or not self.insns:return code
        return rewrite(code,self.begin,self.end,self.thumb)
    cls.emit=emit
    cls._decomp_shared_calls_fixed=True
