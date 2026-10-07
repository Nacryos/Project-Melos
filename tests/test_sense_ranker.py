"""Synthetic fixtures for source-bound UI selection, not corpus data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend.interlinear import interlinear_reading
from backend.sense_ranker import PassageSenseRanker, apply_sense_ranking, sense_packet
from backend.jev_gateway import GatewayLimit, CachedJevProvider


def fixture(count=1):
    text = ' '.join(['α'] * count)
    passage = {'id': 'fixture', 'text': text, 'author': 'Synthetic', 'language': 'grc'}
    senses = [{'id': f'sense-{i}', 'entry_id': 'entry', 'text': meaning, 'source': 'LSJ',
               'source_url': 'https://example.org/fixture', 'language': 'en', 'evidence_type': 'dictionary_sense',
               'source_locator': {'node_path': f'/entry/sense[{i}]'}, 'raw_sha256': 'a' * 64,
               'scope_text': meaning, 'qualifiers': []} for i, meaning in enumerate(['first meaning', 'second meaning'])]
    tokens = [{'id': f't{i}', 'text': 'α', 'kind': 'word', 'start': 2*i, 'end': 2*i+1,
               'source_candidates': [{'id': f'candidate-{i}', 'lemma': 'α', 'matched_form': 'α', 'features': {'case': 'nominative'}}],
               'lexicon_entries': [{'id': 'entry', 'lemma': 'α', 'source': 'LSJ', 'gloss': 'wrong etymology',
                                    'dictionary_senses': deepcopy(senses)}]} for i in range(count)]
    result = {'passage': {'id': 'fixture', 'text_sha256': hashlib.sha256(text.encode()).hexdigest()},
              'selection': {'text': text, 'start': 0, 'end': len(text)}, 'tokens': tokens,
              'syntax': {'state': 'unavailable'}, 'ranking': {'items': []}}
    result['interlinear'] = interlinear_reading(result)
    return passage, result


class Provider:
    model = 'fake-jev'
    def __init__(self, answer=None):
        self.answer = answer or {'choice': 'sense-1', 'model': self.model,
                                 'model_probabilities': {'sense-0': .05, 'sense-1': .9, 'abstain': .05}}
        self.calls = []
    def decide(self, packet):
        self.calls.append(deepcopy(packet))
        return deepcopy(self.answer)


def word(result):
    return result['interlinear']['readings'][0]['tokens'][0]


def run(passage, result, provider):
    return PassageSenseRanker(lambda _: passage, lambda _: provider)(result, visitor_id='a' * 64)


def test_default_preview_is_literal_not_legacy_flat_gloss_or_contextual():
    _, result = fixture()
    gloss = word(result)['gloss']
    assert gloss['text'] == 'first meaning'
    assert gloss['selection_basis'] == 'first_dictionary_sense_not_contextual_sense'
    assert len(gloss['alternatives']) == 2


def test_decisive_selection_uses_existing_sense_and_keeps_alternatives():
    passage, result = fixture()
    provider = Provider()
    ranking = run(passage, result, provider)
    assert ranking['items'][0]['status'] == 'proposed'
    assert provider.calls[0]['task_schema'] == 'melos-contextual-dictionary-sense-v2'
    apply_sense_ranking(result['interlinear'], ranking, source_result=result)
    assert word(result)['gloss']['text'] == 'second meaning'
    assert word(result)['gloss']['selection_basis'] == 'jev_contextual_sense_proposal'
    assert len(word(result)['gloss']['alternatives']) == 2


@pytest.mark.parametrize('change', ['text', 'id', 'entry_id', 'raw_sha256', 'source_locator'])
def test_tampered_sense_payload_rejected_before_call(change):
    passage, result = fixture()
    word(result)['gloss']['alternatives'][0][change] = 'tampered'
    provider = Provider()
    assert run(passage, result, provider)['attempted_occurrences'] == 0
    assert not provider.calls


@pytest.mark.parametrize('change', ['candidate_id', 'lemma', 'features', 'source_candidate', 'start', 'end'])
def test_tampered_morphology_or_occurrence_rejected(change):
    passage, result = fixture()
    word(result)[change] = 'tampered'
    provider = Provider()
    assert run(passage, result, provider)['attempted_occurrences'] == 0
    assert not provider.calls


def test_changed_passage_hash_blocks_calls():
    passage, result = fixture()
    passage['text'] += ' β'
    provider = Provider()
    assert run(passage, result, provider)['attempted_occurrences'] == 0


@pytest.mark.parametrize('answer', [
    {'choice': 'abstain', 'model': 'fake', 'model_probabilities': {'sense-0': .1, 'sense-1': .1, 'abstain': .8}},
    {'choice': 'sense-1', 'model': 'fake', 'model_probabilities': {'sense-0': .4, 'sense-1': .55, 'abstain': .05}},
    {'choice': 'sense-1', 'model': 'fake', 'model_probabilities': {'sense-1': .99}},
    {'choice': 'sense-1', 'model': 'fake', 'model_probabilities': {'sense-0': float('nan'), 'sense-1': .9, 'abstain': .1}},
    {'choice': 'invented-sense', 'model': 'fake', 'model_probabilities': {}},
])
def test_abstention_weak_incomplete_or_invalid_scores_preserve_source_preview(answer):
    passage, result = fixture()
    ranking = run(passage, result, Provider(answer))
    apply_sense_ranking(result['interlinear'], ranking, source_result=result)
    assert word(result)['gloss']['text'] == 'first meaning'
    assert ranking['items'][0]['selected_sense_id'] is None


def test_multiple_dictionaries_are_not_mistaken_for_homographs():
    _, result = fixture()
    entry = deepcopy(result['tokens'][0]['lexicon_entries'][0])
    entry.update(id='other-entry', source='Autenrieth')
    for i, sense in enumerate(entry['dictionary_senses']):
        sense.update(id=f'autenrieth-{i}', entry_id='other-entry', source='Autenrieth')
    result['tokens'][0]['lexicon_entries'].append(entry)
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 4
    entry['source'] = 'LSJ'
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['text'] is None


def test_wrong_explicit_dictionary_entry_does_not_fallback_to_another_lemma():
    _, result = fixture()
    result['tokens'][0]['source_candidates'][0]['gloss_entry_id'] = 'entry'
    result['tokens'][0]['lexicon_entries'][0]['lemma'] = 'β'
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['text'] is None


def test_explicit_primary_dictionary_can_keep_other_unambiguous_exact_lemma_senses():
    _, result = fixture()
    token = result['tokens'][0]
    token['source_candidates'][0]['gloss_entry_id'] = 'entry'
    other = deepcopy(token['lexicon_entries'][0])
    other.update(id='other-entry', source='Autenrieth')
    other['dictionary_senses'] = [{**other['dictionary_senses'][0], 'id': 'other-sense',
                                  'entry_id': 'other-entry', 'source': 'Autenrieth', 'text': 'I, me.'}]
    token['lexicon_entries'].append(other)
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['entry_id'] == 'entry'
    assert [s['text'] for s in word(result)['gloss']['alternatives']] == ['first meaning', 'second meaning', 'I, me.']
    token['lexicon_entries'][0]['lemma_beta'] = 'a)1'
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 2
    token['lexicon_entries'][0].pop('lemma_beta')
    other['lemma_beta'] = 'a)2'
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 2
    other.pop('lemma_beta')
    token['source_candidates'][0]['homograph_id'] = '1'
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 2
    token['source_candidates'][0].pop('homograph_id')
    token['lexicon_entries'].append({**other, 'id': 'ambiguous-other'})
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 2
    token['lexicon_entries'].pop()
    other['lemma'] = 'ά'
    result['interlinear'] = interlinear_reading(result)
    assert len(word(result)['gloss']['alternatives']) == 2


def test_restricted_variant_is_not_default_for_a_different_form():
    _, result = fixture()
    result['tokens'][0]['lexicon_entries'][0]['dictionary_senses'][0]['form_scope'] = {'relation': 'variant', 'text': 'β'}
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['text'] == 'second meaning'
    assert len(word(result)['gloss']['alternatives']) == 2


def test_model_cannot_override_known_incompatible_variant_scope():
    passage, result = fixture()
    result['tokens'][0]['lexicon_entries'][0]['dictionary_senses'][1]['form_scope'] = {'relation': 'variant', 'text': 'β'}
    result['interlinear'] = interlinear_reading(result)
    ranking = run(passage, result, Provider())
    assert ranking['items'][0]['status'] == 'uncertain'
    apply_sense_ranking(result['interlinear'], ranking, source_result=result)
    assert word(result)['gloss']['text'] == 'first meaning'
    # The view application itself also fails closed on a malformed proposal.
    apply_sense_ranking(result['interlinear'], {'items': [{'token_id': 't0', 'status': 'proposed', 'selected_sense_id': 'sense-1'}]})
    assert word(result)['gloss']['text'] == 'first meaning'


def test_real_archived_lsj_entry_id_and_sense_projection_integrate():
    from backend.lexicon_senses import dictionary_senses
    root = Path(__file__).resolve().parents[1]
    raw_path = 'data/raw/lexica/lsj/CTS_XML_TEI/perseus/pdllex/grc/lsj/grc.lsj.perseus-eng11.xml'
    if not (root / raw_path).exists():
        pytest.skip('Archived LSJ source not installed')
    with (root / raw_path).open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    record = {'id': 'lsj:11:n57100', 'entry_id': 'n57100', 'raw_path': raw_path, 'raw_sha256': digest,
              'source': 'PerseusDL LSJ TEI',
              'source_url': 'https://github.com/PerseusDL/lexica/blob/master/CTS_XML_TEI/perseus/pdllex/grc/lsj/grc.lsj.perseus-eng11.xml'}
    extracted = dictionary_senses(record)
    assert extracted['dictionary_senses']
    assert extracted['dictionary_senses'][0]['entry_id'] == 'n57100'
    assert extracted['dictionary_senses'][0]['lexicon_entry_id'] == 'lsj:11:n57100'
    passage, result = fixture()
    passage['text'] = 'κηλήμασι'
    result['passage']['text_sha256'] = hashlib.sha256(passage['text'].encode()).hexdigest()
    result['selection'].update(text=passage['text'], end=len(passage['text']))
    result['tokens'][0].update(text=passage['text'], end=len(passage['text']))
    result['tokens'][0]['source_candidates'][0].update(lemma='κήλημα', matched_form=passage['text'])
    result['tokens'][0]['lexicon_entries'] = [{**record, 'lemma': 'κήλημα', **extracted}]
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['text'] == 'charm, spell'
    assert word(result)['gloss']['entry_id'] == record['id']
    packet = sense_packet(passage, result, word(result))
    assert packet['source_contexts'][packet['candidates'][0]['source_context_ref']]['raw_sha256'] == digest


def test_structured_empty_or_nonenglish_blocks_bad_raw_gloss():
    _, result = fixture()
    result['tokens'][0]['lexicon_entries'][0]['dictionary_senses'] = []
    result['interlinear'] = interlinear_reading(result)
    assert word(result)['gloss']['text'] is None


def test_single_sense_needs_no_provider_and_no_false_context_confidence():
    passage, result = fixture()
    result['tokens'][0]['lexicon_entries'][0]['dictionary_senses'].pop()
    result['interlinear'] = interlinear_reading(result)
    provider = Provider()
    ranking = run(passage, result, provider)
    assert ranking['items'][0]['status'] == 'single_dictionary_sense'
    assert not provider.calls


def test_bounded_calls_and_limits_are_preserved():
    passage, result = fixture(4)
    provider = Provider()
    ranking = run(passage, result, provider)
    assert len(provider.calls) == 3
    assert ranking['items'][3]['status'] == 'request_limit'
    class Limited(Provider):
        def decide(self, packet):
            self.calls.append(packet)
            raise GatewayLimit('synthetic', 20)
    limited = Limited()
    ranking = run(passage, result, limited)
    assert len(limited.calls) == 1
    assert ranking['items'][0]['retry_after'] == 20
    assert all(item['status'] == 'rate_limited' for item in ranking['items'])


def test_existing_gateway_caches_sense_packet_and_bounds_cost(tmp_path):
    passage, result = fixture()
    provider = Provider()
    gateway = CachedJevProvider(provider, 'a' * 64, state_path=tmp_path / 'cache.sqlite')
    first = run(passage, result, gateway)
    second = run(passage, result, gateway)
    assert not first['items'][0]['cache_hit'] and second['items'][0]['cache_hit']
    assert len(provider.calls) == 1


def test_translation_is_context_only_and_nonenglish_never_sent():
    passage, result = fixture()
    passage['translation_previews'] = [
        {'record_id': 'good', 'parent_id': 'fixture', 'language': 'eng', 'text': 'Synthetic English context'},
        {'record_id': 'bad', 'parent_id': 'fixture', 'language': 'ell', 'text': 'Modern Greek context'},
        {'record_id': 'unrelated', 'parent_id': 'other', 'language': 'eng', 'text': 'Unrelated context'}]
    packet = sense_packet(passage, result, word(result))
    assert [row['record_id'] for row in packet['published_translation_context']] == ['good']
    assert packet['published_translation_context'][0]['selection_aligned'] is False


def test_provider_uses_semantic_not_morphological_question(monkeypatch):
    from backend import classifier
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self):
            return json.dumps({'model': 'fake', 'answers': {'contextual_parse': {'type': 'choice', 'choice': 'abstain'}}}).encode()
    def open_request(request, **_):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(classifier, 'urlopen', open_request)
    passage, result = fixture()
    classifier.JevProvider(api_key='synthetic-test-key').decide(sense_packet(passage, result, word(result)))
    instructions = captured[0]['questions']['contextual_parse']['instructions']
    assert 'dictionary sense' in instructions
    assert 'do not generate or rewrite' in instructions


def test_short_wire_choices_map_complete_model_vector_back_to_source_ids():
    passage, result = fixture()
    entry = result['tokens'][0]['lexicon_entries'][0]
    template = entry['dictionary_senses'][0]
    entry['dictionary_senses'] = [{**deepcopy(template), 'id': f'sense-{i}',
                                   'text': f'literal source meaning {i}',
                                   'scope_text': f'literal source meaning {i}'} for i in range(12)]
    result['interlinear'] = interlinear_reading(result)
    packet = sense_packet(passage, result, word(result))
    assert list(packet['source_choice_ids'].values()) == [f'sense-{i}' for i in range(12)]
    assert [row['id'] for row in packet['candidates']] == [f's{i}' for i in range(1, 13)]
    probabilities = {f's{i}': (.8 if i == 11 else .01) for i in range(1, 13)}
    probabilities['abstain'] = .09
    provider = Provider({'choice': 's11', 'model': 'fake', 'model_probabilities': probabilities})
    ranking = run(passage, result, provider)
    item = ranking['items'][0]
    assert item['status'] == 'proposed'
    assert item['selected_sense_id'] == 'sense-10'
    assert set(item['model_probabilities_uncalibrated']) == {f'sense-{i}' for i in range(12)} | {'abstain'}
    apply_sense_ranking(result['interlinear'], ranking, source_result=result)
    assert word(result)['gloss']['text'] == 'literal source meaning 10'


def test_short_wire_choice_cannot_propose_with_missing_competitor_score():
    passage, result = fixture()
    entry = result['tokens'][0]['lexicon_entries'][0]
    template = entry['dictionary_senses'][0]
    entry['dictionary_senses'] = [{**deepcopy(template), 'id': f'sense-{i}',
                                   'text': f'source meaning {i}'} for i in range(12)]
    result['interlinear'] = interlinear_reading(result)
    provider = Provider({'choice': 's11', 'model': 'fake',
                         'model_probabilities': {'s11': .99, 'abstain': .01}})
    ranking = run(passage, result, provider)
    assert ranking['items'][0]['status'] == 'uncertain'
    assert ranking['items'][0]['selected_sense_id'] is None
    apply_sense_ranking(result['interlinear'], ranking, source_result=result)
    assert word(result)['gloss']['text'] != 'source meaning 10'
