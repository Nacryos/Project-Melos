"""Synthetic disambiguation fixtures: never added to the corpus."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from backend.interlinear import interlinear_reading, canonical_features, candidate_identity
from backend.sense_ranker import apply_sense_ranking, sense_packet
from test_sense_ranker import fixture, word, run, Provider


def ambiguous_fixture():
    passage, result = fixture()
    first = result['tokens'][0]['source_candidates'][0]
    result['tokens'][0]['source_candidates'].append({**deepcopy(first), 'id': 'alternate',
                                                    'features': {'case': 'accusative'}})
    result['interlinear'] = interlinear_reading(result)
    return passage, result


def test_same_lemma_sense_selected_without_resolving_morphology():
    passage, result = ambiguous_fixture()
    assert word(result)['candidate_id'] is None
    packet = sense_packet(passage, result, word(result))
    assert packet['selected_morphology'] is None
    assert packet['candidate_bindings'][packet['candidates'][0]['supporting_candidates_ref']] == ['candidate-0', 'alternate']
    decision = run(passage, result, Provider())
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    token = word(result)
    assert token['gloss']['text'] == 'second meaning'
    assert token['gloss']['supporting_candidate_ids'] == ['candidate-0', 'alternate']
    assert token['candidate_id'] is None and token['features'] == {}
    assert token['agreement_group_id'] is None


def test_unbound_homograph_does_not_gain_senses_by_shared_spelling():
    passage, result = ambiguous_fixture()
    for candidate in result['tokens'][0]['source_candidates']:
        candidate['homograph_id'] = candidate['id']
    result['interlinear'] = interlinear_reading(result)
    provider = Provider()
    assert run(passage, result, provider)['attempted_occurrences'] == 0
    assert not provider.calls


def test_changed_original_inventory_or_forged_support_blocks_apply():
    passage, result = ambiguous_fixture()
    decision = run(passage, result, Provider())
    decision['items'][0]['supporting_candidate_ids'] = ['invented']
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['gloss']['text'] is None


def test_stale_sense_decision_cannot_apply_after_morphology_payload_changes():
    passage, result = ambiguous_fixture()
    decision = run(passage, result, Provider())
    result['tokens'][0]['source_candidates'][0]['features'] = {'case': 'dative'}
    result['interlinear'] = interlinear_reading(result)
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['gloss']['selection_basis'] != 'jev_contextual_sense_proposal'


def test_conflicting_explicit_candidate_ids_fail_closed():
    passage, result = ambiguous_fixture()
    result['tokens'][0]['source_candidates'][1]['id'] = 'candidate-0'
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['candidate_id'] is None
    provider = Provider()
    assert run(passage, result, provider)['attempted_occurrences'] == 0
    assert not provider.calls
    decision = run(passage, result, Provider())
    result['tokens'][0]['lexicon_entries'][0]['dictionary_senses'][1]['text'] = 'changed'
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['gloss']['text'] is None


def test_unknown_extra_probability_is_not_a_complete_vector():
    passage, result = ambiguous_fixture()
    provider = Provider()
    provider.answer['model_probabilities']['foreign-choice'] = .1
    decision = run(passage, result, provider)
    assert decision['items'][0]['status'] == 'uncertain'


def test_decisive_existing_candidate_can_disagree_with_syntax():
    _, result = ambiguous_fixture()
    token = result['tokens'][0]
    result['syntax'] = {'state': 'ready', 'tokens': [{'id': 1, 'text': token['text'],
        'absolute_start': token['start'], 'absolute_end': token['end'], 'lemma': 'unrelated',
        'features': {'POS': 'ADV'}}]}
    result['ranking'] = {'items': [{'token_id': token['id'], 'decision': {
        'status': 'proposed', 'candidate_id': 'alternate',
        'packet': {'candidates': deepcopy(token['source_candidates'])},
        'model_probabilities_uncalibrated': {'candidate-0': .03, 'alternate': .94, 'abstain': .03}}}]}
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['candidate_id'] == 'alternate'
    assert word(result)['features'] == {'Case': 'Acc'}
    assert word(result)['syntax_conflict'] is True
    assert word(result)['agreement_group_id'] is None
    result['ranking']['items'][0]['decision']['model_probabilities_uncalibrated'].pop('abstain')
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['candidate_id'] is None


def test_forged_packet_candidate_cannot_replace_original_inventory():
    _, result = ambiguous_fixture()
    token = result['tokens'][0]
    forged = {**token['source_candidates'][0], 'id': 'forged', 'features': {'case': 'dative'}}
    result['ranking'] = {'items': [{'token_id': token['id'], 'decision': {
        'status': 'proposed', 'candidate_id': 'forged', 'packet': {'candidates': [forged]},
        'model_probabilities_uncalibrated': {'forged': .98, 'abstain': .02}}}]}
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['candidate_id'] is None


def test_legacy_identity_preserves_dictionary_and_claim_bindings():
    assert candidate_identity({'lemma': 'synthetic', 'lexicon_entry_ids': ['A']}) != candidate_identity({'lemma': 'synthetic', 'lexicon_entry_ids': ['B']})
    assert candidate_identity({'lemma': 'synthetic', 'claim_ids': ['A']}) != candidate_identity({'lemma': 'synthetic', 'claim_ids': ['B']})
    assert candidate_identity({'lemma': 'synthetic', 'source_tags': ['singular']}) != candidate_identity({'lemma': 'synthetic', 'source_tags': ['plural']})
    assert candidate_identity({'lemma': 'synthetic', 'matched_object_form': {'form': 'a'}}) != candidate_identity({'lemma': 'synthetic', 'matched_object_form': {'form': 'b'}})


def test_selected_parse_never_gets_another_candidates_meaning():
    passage, result = fixture()
    token = result['tokens'][0]
    other = deepcopy(token['lexicon_entries'][0])
    other.update(id='other-entry', lemma='other-lemma')
    other['dictionary_senses'] = [{**other['dictionary_senses'][0], 'id': 'other-sense',
                                'entry_id': 'other-entry', 'text': 'other meaning'}]
    token['lexicon_entries'].append(other)
    token['source_candidates'].append({'id': 'other', 'lemma': 'other-lemma',
        'matched_form': token['text'], 'features': {'case': 'nominative'}})
    result['syntax'] = {'state': 'ready', 'tokens': [{'id': 1, 'text': token['text'],
        'absolute_start': token['start'], 'absolute_end': token['end'], 'lemma': token['text'],
        'features': {'Case': 'Nom'}}]}
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['candidate_id'] == 'candidate-0'
    provider = Provider({'model': 'fake', 'choice': 'other-sense', 'model_probabilities':
                         {'sense-0': .02, 'sense-1': .02, 'other-sense': .94, 'abstain': .02}})
    decision = run(passage, result, provider)
    apply_sense_ranking(result['interlinear'], decision, source_result=result)
    assert word(result)['gloss']['text'] == 'first meaning'


@pytest.mark.parametrize('feature,value', [('Tense','Imp'), ('Person','3'), ('Number','Plur')])
def test_disagreeing_full_parse_does_not_become_consensus(feature, value):
    from backend.interlinear import _morphology_consensus
    first = {'id': 'a', 'lemma': 'synthetic', 'features': {'Tense': 'Aor', 'Person': '2', 'Number': 'Sing'}}
    second = deepcopy(first)
    second['id'] = 'b'; second['features'][feature] = value
    assert _morphology_consensus([first, second], None) == ({}, [])


def test_hyphenated_person_and_explicit_aorist_tags_survive():
    features = canonical_features({'source_tags': ['second-person', 'singular', 'aorist', 'indicative', 'active']})
    assert features == {'Person': '2', 'Number': 'Sing', 'Tense': 'Aor', 'Mood': 'Ind', 'Voice': 'Act'}


def test_real_saved_elthes_retains_explicit_aorist_without_resolving_homograph():
    path = Path('runtime/lyric-context-eval/elthes-baseline/0.response.json')
    if not path.exists(): pytest.skip('Read-only live receipt is not installed')
    result = json.loads(path.read_text(encoding='utf8'))
    token = interlinear_reading(result)['readings'][0]['tokens'][0]
    assert token['features']['Person'] == '2' and token['features']['Tense'] == 'Aor'
    # The fuller exact source row (explicit aorist) may be ranked first; the
    # ἦλθον headword row stays listed as an alternative, never dropped.
    assert token['selection_basis'] in ('source_morphology_consensus', 'morphology_ranked_by_syntax', 'morphology_ranked_parse_consensus')
    assert token['lemma'] in (None, 'ἔρχομαι')
    assert any(item['lemma'] == 'ἦλθον' for item in token['candidate_meanings'])
    assert token['morphology_ranking'][0]['parse_short'] == '2nd sg. aor. ind. act.'


@pytest.mark.parametrize('name,count', [('0', 21), ('1', 4), ('2', 7)])
def test_real_saved_sense_packets_keep_all_choices_within_original_bound(name, count):
    path = Path(f'runtime/lyric-context-eval/baseline/{name}.response.json')
    source = Path('runtime/campbell-assignment/campbell_assignment.jsonl')
    if not path.exists() or not source.exists(): pytest.skip('Read-only live receipts are not installed')
    passage = next(json.loads(line) for line in source.read_text(encoding='utf8').splitlines()
                   if json.loads(line)['id'].endswith(':326'))
    result = json.loads(path.read_text(encoding='utf8'))
    result['interlinear'] = interlinear_reading(result)
    packet = sense_packet(passage, result, word(result))
    assert len(packet['candidates']) == count
    assert len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) <= 32000
    assert packet['passage']['text'] == passage['text']


@pytest.mark.parametrize('folder,name', [('canary-326', '0'), ('canary-326', '1'),
                                        ('canary-326', '2'), ('canary-350', '0')])
def test_current_canary_packets_losslessly_roundtrip_semantic_evidence(folder, name):
    from backend.sense_ranker import _inventory
    path = Path(f'runtime/lyric-context-eval/{folder}/{name}.response.json')
    source = Path('runtime/campbell-assignment/campbell_assignment.jsonl')
    if not path.exists() or not source.exists(): pytest.skip('Read-only canary receipts are not installed')
    result = json.loads(path.read_text(encoding='utf8'))
    passage = next(json.loads(line) for line in source.read_text(encoding='utf8').splitlines()
                   if json.loads(line)['id'] == result['passage']['id'])
    result['interlinear'] = interlinear_reading(result)
    untouched = deepcopy(result)
    token = word(result)
    originals = {row['id']: deepcopy(row) for row in _inventory(token)}
    packet = sense_packet(passage, result, token)
    assert result == untouched
    assert len(packet['candidates']) == len(originals)
    assert len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) <= 32000
    assert packet['passage']['text'] == passage['text']
    for wire in packet['candidates']:
        # Campbell-only packets hoist fields that are exactly common to every
        # sense; reconstruct them before checking literal source equivalence.
        expanded = {**deepcopy(packet.get('candidate_common_fields', {})), **deepcopy(wire)}
        expanded.update(packet['source_contexts'][expanded.pop('source_context_ref')])
        expanded['supporting_candidate_ids'] = packet['candidate_bindings'][expanded.pop('supporting_candidates_ref')]
        for key in list(expanded):
            if key.endswith('_ref'):
                expanded[key[:-4]] = packet['shared_source_evidence'][expanded.pop(key)]
        expanded['id'] = packet.get('source_choice_ids', {}).get(expanded['id'], expanded['id'])
        linked_path = expanded.get('linked_path')
        if isinstance(linked_path, dict):
            for key in list(linked_path):
                if key.endswith('_ref'):
                    linked_path[key[:-4]] = packet['shared_source_evidence'][linked_path.pop(key)]
        expanded.pop('candidate_kind')
        original = originals[expanded['id']]
        for key in ('raw_path', 'scope_locator', 'source_locator', 'extraction_method'):
            original.pop(key, None)
        if isinstance(original.get('citations'), list):
            original['citations'] = [{key: value for key, value in citation.items() if key != 'source_locator'}
                                     if isinstance(citation, dict) else citation for citation in original['citations']]
        assert expanded == original


@pytest.mark.parametrize('name,count', [('0', 37), ('2', 13)])
def test_current_linked_326_packet_retains_all_senses_and_fits_full_provider_request(name, count, monkeypatch):
    """Read-only saved responses and current accepted dictionary; no HTTP call."""
    from backend import classifier, sense_ranker
    from backend.linked_dictionary import lookup_linked_dictionary

    path = Path(f'runtime/lyric-context-eval/canary-326/{name}.response.json')
    source = Path('runtime/campbell-assignment/campbell_assignment.jsonl')
    if not path.exists() or not source.exists(): pytest.skip('Read-only canary receipts are not installed')
    result = json.loads(path.read_text(encoding='utf8'))
    passage = next(json.loads(line) for line in source.read_text(encoding='utf8').splitlines()
                   if json.loads(line)['id'] == result['passage']['id'])
    for row in result['tokens']:
        if row.get('kind') == 'word':
            row['linked_dictionary'] = lookup_linked_dictionary(row['text'])
    result['interlinear'] = interlinear_reading(result)
    token = word(result)
    originals = sense_ranker._inventory(token)
    original_ids = [sense['id'] for sense in originals]
    by_original_id = {sense['id']: sense for sense in originals}
    packet = sense_packet(passage, result, token)
    assert len(packet['candidates']) == count
    assert list(packet['source_choice_ids'].values()) == original_ids
    assert len(set(original_ids)) == count
    for row in packet['candidates']:
        path = row.get('linked_path')
        if path:
            expanded = deepcopy(path)
            if 'source_noun_metadata_ref' in expanded:
                expanded['source_noun_metadata'] = deepcopy(packet['shared_source_evidence'][
                    expanded.pop('source_noun_metadata_ref')])
            expanded.update(packet['shared_source_evidence'][expanded.pop('context_ref')])
            source_id = packet['source_choice_ids'][row['id']]
            assert expanded == by_original_id[source_id]['linked_path']
    state_chars, combined_proxy, request_proxy = sense_ranker._request_size_proxy(packet)
    assert state_chars <= sense_ranker.MAX_SENSE_STATE_CHARS
    assert combined_proxy <= sense_ranker.MAX_SENSE_STATE_QUESTION_PROXY_CHARS
    assert request_proxy <= sense_ranker.MAX_SENSE_REQUEST_PROXY_CHARS

    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return json.dumps({'model': 'fixture', 'answers': {'contextual_parse': {
                'type': 'choice', 'choice': 'abstain'}}}).encode('utf8')
    def no_network(request, **_):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(classifier, 'urlopen', no_network)
    classifier.JevProvider(api_key='synthetic-test-key').decide(packet)
    body = captured[0]
    question = body['questions']['contextual_parse']
    assert body['state'] == json.loads(json.dumps(packet, ensure_ascii=False, separators=(',', ':')))
    assert set(question['criteria']) == {row['id'] for row in packet['candidates']} | {'abstain'}
    assert len(json.dumps(body, ensure_ascii=False, separators=(',', ':'))) <= request_proxy
    assert state_chars + len(json.dumps(question, ensure_ascii=False, separators=(',', ':'))) <= combined_proxy
    assert 'Choose only' in packet['constraints'][0]
    assert any('Use these notes as fallible whole-poem context' in value for value in packet['constraints'])
    assert not any('preserve alternatives and abstain' in value for value in packet['constraints'])
