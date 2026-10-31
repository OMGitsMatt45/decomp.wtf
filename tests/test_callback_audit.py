"""A callback missing from an otherwise valid registry must fail before compilation."""
import hashlib
import json

import pytest

from tools.audit_gba_callbacks import SCHEMA, audit, main


def project(tmp_path):
    rom = bytes(512)
    identity = hashlib.sha256(rom).hexdigest()
    source = tmp_path/'source with spaces'
    (source/'game').mkdir(parents=True)
    (source/'pc-project.json').write_text(json.dumps({'inputs': [{'sha256': identity}]}))
    (source/'game/dispatch_entries_000.inc').write_text(
        '    {0x08000004u, 1, function, 0u, 0u, 0u},\n')
    inventory = dict(schema=SCHEMA, input_sha256=identity, entries=[
        dict(address=0x08000004, mode='thumb', name='ExistingCallback'),
        dict(address=0x08000008, mode='arm', name='MissingCallback')])
    return rom, source, inventory


def test_missing_callback_fails_cli_and_lists_the_name(tmp_path):
    rom, source, inventory = project(tmp_path)
    original = tmp_path/'owner.gba'; original.write_bytes(rom)
    profile = tmp_path/'callbacks.json'; profile.write_text(json.dumps(inventory))
    report = tmp_path/'report.json'
    assert main(['--rom', str(original), '--source', str(source), '--inventory', str(profile), '--report', str(report)]) == 1
    result = json.loads(report.read_text())
    assert result['missing_required'][0]['names'] == ['MissingCallback']
    assert result['missing_required'][0]['address'] == 0x08000008
    # A real second dispatch entry, in decimal syntax, resolves the omission.
    (source/'game/dispatch_entries_001.inc').write_text('    {134217736u, 0, function, 0u, 0u, 0u},\n')
    assert audit(rom, source, inventory)['passed']


def test_wrong_instruction_mode_and_optional_candidates(tmp_path):
    rom, source, inventory = project(tmp_path)
    inventory['entries'][0]['mode'] = 'arm'
    inventory['entries'][1]['required'] = False
    result = audit(rom, source, inventory)
    assert not result['passed'] and result['missing_required'][0]['names'] == ['ExistingCallback']
    assert result['optional_review_candidates'][0]['names'] == ['MissingCallback']


def test_rom_identity_and_alignment_are_checked(tmp_path):
    rom, source, inventory = project(tmp_path)
    with pytest.raises(ValueError, match='supplied ROM'):
        audit(rom+b'X', source, inventory)
    inventory['entries'][0]['address'] += 1
    with pytest.raises(ValueError, match='address'):
        audit(rom, source, inventory)
