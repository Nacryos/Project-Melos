"""Actual local HTTP route replay; archived receipt/source only, no network calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def route_probe(mode, endpoint='passage', release_server=False, full_word_source=False):
    from contextlib import nullcontext
    import shutil
    import tempfile
    from unittest.mock import patch
    sys.path.insert(0, str(ROOT))
    audit = json.loads((ROOT / 'docs/audits/machine-subentries-helper.json').read_text(encoding='utf8'))
    index = 'data/staging/lyric-subentries-20261006-v2/subentries.sqlite'
    os.environ.update(MELOS_PUBLIC_DEPLOYMENT='0', MELOS_PUBLIC_CLASSIFIER='0',
                      MELOS_MACHINE_SUBENTRIES_ENABLED='0' if mode == 'disabled' else '1',
                      MELOS_SUBENTRY_INDEX=str(ROOT / index),
                      MELOS_SUBENTRY_MANIFEST=str(ROOT / 'data/lexica/entries.jsonl'),
                      MELOS_SUBENTRY_INDEX_SHA256=audit['reviewed_files_sha256'][index])
    if mode == 'wrong_hash':
        os.environ['MELOS_SUBENTRY_INDEX_SHA256'] = '0' * 64
    if mode == 'missing_config':
        os.environ.pop('MELOS_SUBENTRY_MANIFEST')
    if release_server:
        # Execute the immutable-I-plus-wiring source, retaining the actual app
        # root just as the deployment's module overlay will. No file changes.
        import types
        import backend
        module = types.ModuleType('backend.server')
        module.__file__ = str(ROOT / 'backend/server.py')
        module.__package__ = 'backend'
        sys.modules['backend.server'] = module
        backend.server = module
        source = ROOT / 'runtime/machine-subentry-local-release/overlay/backend/server.py'
        exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
    from backend import server, machine_morphology, syntax_provider
    from fastapi.testclient import TestClient
    results = json.loads((ROOT / 'runtime/alcaeus-morpheus-maintenance/intact-results.json').read_text(encoding='utf8'))
    case = next(row for row in results['results'] if any(
        c.get('lemma') == '\u1f00\u03c3\u03c5\u03bd\u03b5\u03c4\u03ad\u03c9'
        for c in row['result'].get('machine_candidates', [])))
    form = case['form']
    passage = next(row for line in (ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl').read_text(encoding='utf8').splitlines()
                   if form in (row := json.loads(line)).get('text', ''))
    start = passage['text'].index(form)
    request = {'version': 1, 'passage_id': passage['id'], 'start': start, 'end': start + len(form),
               'offset_unit': 'codepoint', 'selected_text': form}
    with tempfile.TemporaryDirectory(prefix='melos-subentry-route-') as tmp:
        cache = Path(tmp) / 'machine.sqlite'
        shutil.copyfile(results['database'], cache)
        def no_network(*args, **kwargs):
            raise AssertionError('Network forbidden in source/receipt route replay')
        machine = machine_morphology.MachineMorphologyService(cache_path=cache, transport=no_network)
        assert machine.load_receipt(case['result']['receipt']['id'], form=form)['status'] == 'ok'
        with patch.object(server, 'passage', lambda identifier: passage), \
             (nullcontext() if full_word_source else patch.object(server, 'word', lambda form, *args: {'form': form, 'source_only_fixture': True})), \
             patch.object(machine_morphology, 'get_service', lambda: machine), \
             patch.object(syntax_provider, 'analyze', lambda *args: {'state': 'unavailable', 'tokens': []}):
            client = TestClient(server.app)
            response = (client.get('/api/word', params={'form': form, 'passage_id': passage['id']})
                        if endpoint == 'word' else client.post('/api/analyze-passage', json=request))
            assert response.status_code == 200, response.text
            result = response.json()
    if endpoint == 'passage':
        assert result['tokens'][0]['machine']['status'] == 'ok'
        assert result['limits']['machine_fetches'] == 0
    return result


@pytest.mark.parametrize('mode', ['enabled', 'disabled', 'wrong_hash', 'missing_config'])
@pytest.mark.parametrize('endpoint', ['passage', 'word'])
@pytest.mark.parametrize('release_server', [False, True])
def test_actual_server_route_with_archived_receipt_and_source(mode, endpoint, release_server):
    # Separate interpreter ensures route configuration is tested at actual app import,
    # without reloading shared server state used by unrelated tests.
    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe', mode, endpoint,
                                *(['--release-server'] if release_server else [])],
                               cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=60)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    if endpoint == 'word':
        assert result['source_only_fixture'] is True
        if mode == 'disabled':
            # Release N: /api/word adds labelled parser candidates (local Morpheus) and the
            # dictionary entries of their headwords; machine subentries stay off.
            # Release O: the ranked headline headword and its alternatives travel in the same response.
            extra = set(result) - {'form', 'source_only_fixture'}
            assert extra <= {'parser_candidates', 'parse_source', 'lexicon_entries', 'lookup_mode',
                             'headline_lemma', 'headline_basis', 'headline_evidence', 'headline_alternatives',
                             'headline_tie_broken', 'alternatives'}
            assert 'machine_dictionary' not in result
            assert all(row['candidate_kind'] == 'machine_analysis' for row in result.get('parser_candidates', []))
            return
        result = result['machine_dictionary']
        assert result['scope'] == 'standalone_form_query'
        if mode != 'enabled':
            assert result['status'] == 'unavailable' and result['tokens'] == []
            assert 'machine_subentry_evidence' not in result
            return
    token = result['tokens'][0]
    if mode == 'disabled':
        assert 'machine_subentries' not in token and 'machine_subentry_evidence' not in result
    elif mode == 'enabled':
        assert token['machine_subentries']['status'] == 'available'
        candidates = result['interlinear']['readings'][0]['tokens'][0]['candidate_meanings']
        assert len(candidates) == 1
        alternative = candidates[0]['machine_subentry_alternatives'][0]
        source = result['machine_subentry_evidence']['subentries'][alternative['subentry_ref']]['source_subentry']
        assert [sense['text'] for sense in source['dictionary_senses']] == ['to be without understanding']
        assert alternative['ranking_status'] == 'unsupported_source_type'
        assert candidates[0]['gloss']['text'] is None
        assert source['dictionary_senses'][0]['form_scope']['relation'] == 'variant'
    else:
        assert token['machine_subentries']['status'] == 'unavailable'
        assert token['machine_subentries']['candidate_refs'] == []
        assert not result['machine_subentry_evidence'].get('subentries')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', choices=['enabled', 'disabled', 'wrong_hash', 'missing_config'], required=True)
    parser.add_argument('endpoint', choices=['passage', 'word'])
    parser.add_argument('--release-server', action='store_true')
    parser.add_argument('--full-word-source', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    rendered = json.dumps(route_probe(args.probe, args.endpoint, args.release_server, args.full_word_source), ensure_ascii=True)
    if args.output:
        args.output.write_text(rendered + '\n', encoding='utf8')
        print(args.output)
    else:
        print(rendered)
