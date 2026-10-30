"""Large native registries remain Git-hostable with identical C initializers."""
import re

import pytest

from decompnet import pc
from decompnet.gba_native import _fragment_dispatch


def dispatch(tmp_path, rows):
    game = tmp_path/'game'
    game.mkdir()
    text = ('#include "game.h"\nextern void resumed(anygba_cpu*);\n'
        'static const anygba_function_entry functions[] = {\n'+''.join(rows)+
        '};\nconst anygba_game anygba_game_info = {"title", "hash", 1024u, functions, '+
        str(len(rows))+'u};\n')
    (game/'dispatch.c').write_text(text, encoding='utf-8')
    return game, text


def test_large_dispatch_fragments_preserve_all_entries_including_duplicate_guards(tmp_path):
    # Two guarded RAM candidates at the same address must retain their order.
    rows = [f'    {{{address}u, 1, resumed, 33554432u, 33554440u, {source}u}},\n'
        for address, source in [(33554432, 134217728), (33554432, 134217744),
            *[(134217728+i*2, 0) for i in range(200)]]]
    game, original = dispatch(tmp_path, rows)
    _fragment_dispatch(tmp_path, max_bytes=256)
    fragmented = (game/'dispatch.c').read_text(encoding='utf-8')
    names = re.findall(r'^#include "(dispatch_entries_\d+\.inc)"$', fragmented, re.M)
    assert len(names) > 1
    assert set(names) == {path.name for path in game.glob('*.inc')}
    assert all((game/name).stat().st_size <= 256 for name in names)
    expanded = re.sub(r'^#include "(dispatch_entries_\d+\.inc)"\n',
        lambda match: (game/match[1]).read_text(encoding='utf-8'), fragmented, flags=re.M)
    assert expanded == original


def test_small_dispatch_is_unchanged(tmp_path):
    game, original = dispatch(tmp_path, ['    {134217728u, 0, resumed, 0u, 0u, 0u},\n'])
    _fragment_dispatch(tmp_path)
    assert (game/'dispatch.c').read_text(encoding='utf-8') == original
    assert not list(game.glob('*.inc'))


@pytest.mark.parametrize('change', ['marker', 'terminator', 'long-entry'])
def test_invalid_large_dispatch_preserves_original_without_partial_fragments(tmp_path, change):
    game, original = dispatch(tmp_path, ['    {'+'0'*300+'},\n'])
    if change == 'marker':
        original = original.replace('functions[]', 'unknown[]')
    elif change == 'terminator':
        original = original.replace('};\n', '}\n')
    (game/'dispatch.c').write_text(original, encoding='utf-8')
    with pytest.raises(pc.PCError, match='dispatch'):
        _fragment_dispatch(tmp_path, max_bytes=128)
    assert (game/'dispatch.c').read_text(encoding='utf-8') == original
    assert not list(game.glob('*.inc'))
