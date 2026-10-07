from argparse import Namespace
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.experiment_commentary_prompt import ablated, ORIGINAL, REVISED, encoded, digest_bytes, run, ROOT


def test_only_one_constraint_changes_and_source_choices_untouched():
    source = {'constraints': ['first', ORIGINAL, 'last'], 'candidates': [{'id': 'real-source-placeholder'}]}
    before = deepcopy(source)
    changed = ablated(source)
    assert source == before
    changed['constraints'][1] = ORIGINAL
    assert changed == before
    with pytest.raises(ValueError): ablated({'constraints': [ORIGINAL, ORIGINAL]})


def frozen(tmp_path, cases=1):
    packet = {'constraints': [ORIGINAL], 'candidates': [{'id': 'fixture'}]}
    entries = []
    for i in range(cases):
        arms = []
        for arm, value in [('baseline', packet), ('commentary_only', ablated(packet))]:
            path = tmp_path / f'{i}-{arm}.packet.json'
            path.write_bytes(encoded(value))
            arms.append({'arm': arm, 'file': path.name, 'sha256': digest_bytes(path.read_bytes())})
        entries.append({'case': i, 'arms': arms})
    manifest = {'cases': entries, 'maximum_provider_calls': len(entries) * 2, 'model': 'fixture',
                'approved_output_directory': str(tmp_path.resolve()),
                'provider_code_sha256': digest_bytes((ROOT / 'backend/classifier.py').read_bytes()),
                'gateway_code_sha256': digest_bytes((ROOT / 'backend/jev_gateway.py').read_bytes()),
                'script_sha256': digest_bytes((ROOT / 'scripts/experiment_commentary_prompt.py').read_bytes())}
    (tmp_path / 'manifest.json').write_bytes(encoded(manifest))
    return Namespace(output=tmp_path, approved_manifest_sha256=digest_bytes(encoded(manifest)), model='fixture')


@pytest.mark.parametrize('change', ['approval', 'model', 'packet'])
def test_execution_refuses_unreviewed_changes(tmp_path, change, monkeypatch):
    args = frozen(tmp_path)
    if change == 'approval': args.approved_manifest_sha256 = '0' * 64
    elif change == 'model': args.model = 'changed'
    else: (tmp_path / '0-baseline.packet.json').write_text('{}')
    def forbidden(*args, **kwargs): raise AssertionError('Provider must not be constructed')
    monkeypatch.setattr('backend.classifier.JevProvider', forbidden)
    with pytest.raises(ValueError): run(args)


def test_six_cases_hard_bound_and_no_repeat_execution(tmp_path, monkeypatch):
    args = frozen(tmp_path, 6)
    calls = []
    class Fake:
        def __init__(self, *a, **kw): pass
        def decide(self, packet):
            calls.append(packet)
            return {'choice': 'abstain', 'model': 'fixture', 'model_probabilities': {'fixture': 0, 'abstain': 1}}
    monkeypatch.setattr('backend.classifier.JevProvider', Fake)
    monkeypatch.setattr('backend.jev_gateway.CachedJevProvider', Fake)
    run(args)
    assert len(calls) == 12
    with pytest.raises(ValueError): run(args)
    assert len(calls) == 12


def test_provider_failure_stops_without_retry_and_attempt_remains_counted(tmp_path, monkeypatch):
    args = frozen(tmp_path, 2)
    calls = []
    class Fake:
        def __init__(self, *a, **kw): pass
        def decide(self, packet):
            calls.append(packet)
            raise TimeoutError()
    monkeypatch.setattr('backend.classifier.JevProvider', Fake)
    monkeypatch.setattr('backend.jev_gateway.CachedJevProvider', Fake)
    with pytest.raises(SystemExit): run(args)
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / 'attempts.sqlite') as con:
        assert con.execute('SELECT status FROM attempts').fetchall() == [('failed_or_indeterminate',)]
    with pytest.raises(ValueError): run(args)
    assert len(calls) == 1


def test_copied_approved_manifest_cannot_reset_lifetime_budget(tmp_path):
    import shutil
    first = tmp_path / 'original'
    first.mkdir()
    args = frozen(first)
    second = tmp_path / 'copy'
    shutil.copytree(first, second)
    args.output = second
    with pytest.raises(ValueError, match='directory differs'): run(args)
