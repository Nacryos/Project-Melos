"""Contract checks for the live probe using the archived source fixture."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.interlinear import interlinear_reading
from scripts.check_source_tense_live import verify_dictionary, verify_interlinear


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/word-elthes-tense-preview.json').read_text(encoding='utf-8'))


def projected():
    word = fixture()
    token = {'id': 'synthetic-selection-token', 'kind': 'word', 'text': word['form'], 'start': 0, 'end': len(word['form']),
             'source_candidates': word['candidates'], 'lexicon_entries': word['lexicon_entries'],
             'machine': {'machine_candidates': []}}
    result = {'tokens': [token], 'syntax': {'tokens': []}, 'ranking': {'status': 'not_requested'},
              'selection': {'text': word['form'], 'start': 0, 'end': len(word['form'])},
              'limits': {'machine_fetches': 0}, 'sense_ranking': {'status': 'not_requested'}}
    result['interlinear'] = interlinear_reading(result)
    return word, result


def test_actual_source_projection_passes_without_network_or_model():
    word, result = projected()
    entry, restricted = verify_dictionary(word, fixture())
    assert verify_interlinear(result, word['form'], entry, restricted)['complete_source_senses'] == len(entry['dictionary_senses'])


def test_changed_source_meaning_is_not_accepted():
    word = fixture()
    altered = deepcopy(word)
    altered['lexicon_entries'][0]['dictionary_senses'][0]['text'] = 'synthetic corruption'
    with pytest.raises(AssertionError):
        verify_dictionary(altered, word)


def test_removed_alternatives_or_incompatible_headline_are_not_accepted():
    word, result = projected()
    entry, restricted = verify_dictionary(word, fixture())
    for remove in (True, False):
        changed = deepcopy(result)
        for candidate in changed['interlinear']['readings'][0]['tokens'][0]['candidate_meanings']:
            gloss = candidate.get('gloss') or {}
            if remove:
                gloss['alternatives'] = [s for s in gloss.get('alternatives', []) if s['id'] not in restricted]
            else:
                gloss['sense_id'] = next(iter(restricted))
        with pytest.raises(AssertionError):
            verify_interlinear(changed, word['form'], entry, restricted)


def test_probe_rejects_unrequested_paid_or_upstream_work():
    word, result = projected()
    entry, restricted = verify_dictionary(word, fixture())
    result['limits']['machine_fetches'] = 1
    with pytest.raises(AssertionError):
        verify_interlinear(result, word['form'], entry, restricted)
