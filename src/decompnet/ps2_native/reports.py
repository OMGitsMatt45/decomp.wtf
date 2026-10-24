"""Check all emitter diagnostics, including errors returned with exit code zero."""
import re

from ..pc import PCError


def generation_report(output: str, *, expected_functions: int | None = None) -> dict:
    counts = re.search(r'Functions processed: (\d+), recompiled: (\d+), stubs: (\d+), skipped: (\d+), decode failures: (\d+)', output)
    diagnostics = re.search(r'Warnings: (\d+), errors: (\d+)', output)
    if not counts or not diagnostics:
        raise PCError('PS2 emitter report is incomplete; native source is not qualified')
    result = dict(zip(('processed', 'recompiled', 'stubs', 'skipped', 'decode_failures'), map(int, counts.groups())))
    result.update(warnings=int(diagnostics[1]), errors=int(diagnostics[2]))
    if (not result['processed'] or result['processed'] != result['recompiled'] or
            any(result[k] for k in ('stubs', 'skipped', 'decode_failures', 'errors')) or
            (expected_functions is not None and result['processed'] != expected_functions)):
        raise PCError('PS2 translation is incomplete: ' + ', '.join(f'{k}={v}' for k, v in result.items()) +
                      '; inspect the retained diagnostics before building a game')
    return result
