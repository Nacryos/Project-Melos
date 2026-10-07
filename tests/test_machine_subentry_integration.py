"""Local source/receipt replay only; no API calls, corpus writes or paid inference."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend.interlinear import interlinear_reading, catalog_machine_subentries, _subentry_digest, canonical_features, compact_parse
from backend.machine_morphology import project
from backend.machine_subentries import MachineSubentryResolver
from backend.passage_analysis import PassageAnalysisService, MAX_MACHINE_SUBENTRY_LOOKUPS, machine_dictionary_lookup
from backend.sense_ranker import _inventory

ROOT = Path(__file__).resolve().parents[1]


def actual_fixture():
    audit = json.loads((ROOT / 'docs/audits/machine-subentries-helper.json').read_text(encoding='utf8'))
    results = json.loads((ROOT / 'runtime/alcaeus-morpheus-maintenance/intact-results.json').read_text(encoding='utf8'))
    case = next(row for row in results['results'] if any(
        c.get('lemma') == 'ἀσυνετέω' for c in row['result'].get('machine_candidates', [])))
    original = deepcopy(case['result'])
    raw = Path(case['raw_path']).read_bytes()
    receipt = original['receipt']
    def loader(receipt_id, *, form):
        metadata = {key: value for key, value in receipt.items() if key != 'id'}
        if receipt_id != _subentry_digest(metadata) or form != original['form']:
            return {'status': 'invalid_receipt'}
        return project(raw, form, receipt)
    resolver = MachineSubentryResolver(
        ROOT / 'data/staging/lyric-subentries-20261006-v2/subentries.sqlite', ROOT / 'data/lexica/entries.jsonl',
        expected_index_sha256=audit['reviewed_files_sha256']['data/staging/lyric-subentries-20261006-v2/subentries.sqlite'])
    passage = next(row for line in (ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf8').splitlines()
                   if original['form'] in (row := json.loads(line)).get('text', ''))
    class CacheOnly:
        def analyze(self, form, visitor_id, fetch=False):
            assert fetch is False, 'Integration cannot fetch morphology'
            return deepcopy(original) if form == original['form'] else {'status': 'cache_miss', 'machine_candidates': []}
    callback = lambda token: resolver.resolve(token, receipt_loader=loader)
    return original, passage, CacheOnly(), callback


def run_actual(enabled=True):
    original, passage, machine, callback = actual_fixture()
    service = PassageAnalysisService(lambda identifier: passage, lambda form, passage_id: {},
                                     machine_service=machine, machine_subentry_lookup=callback if enabled else None)
    start = passage['text'].index(original['form'])
    request = {'passage_id': passage['id'], 'start': start, 'end': start + len(original['form']),
               'offset_unit': 'codepoint', 'selected_text': original['form']}
    return service.analyze(request)


@pytest.fixture(scope='module')
def actual():
    return run_actual()


def meaning(result):
    return interlinear_reading(result)['readings'][0]['tokens'][0]['candidate_meanings'][0]


def test_actual_source_and_cached_receipt_produce_display_refs_not_ranker_senses(actual):
    word = meaning(actual)
    refs = word['machine_subentry_alternatives']
    assert len(refs) == 1
    assert refs[0]['ranking_status'] == 'unsupported_source_type'
    source = actual['machine_subentry_evidence']['subentries'][refs[0]['subentry_ref']]['source_subentry']
    assert [s['text'] for s in source['dictionary_senses']] == ['to be without understanding']
    assert source['dictionary_senses'][0]['form_scope']['relation'] == 'variant'
    assert source['dictionary_senses'][0]['form_scope']['text'] != actual['selection']['text']
    assert word['gloss']['text'] is None and not word['gloss'].get('alternatives')
    assert _inventory({'candidate_meanings': [word]}) == []
    assert actual['tokens'][0]['source_candidates'] == []
    assert actual['limits']['machine_fetches'] == 0
    assert word['features']['Person'] == '1'
    assert word['parse_short'] == '1st sg. pres. ind. act.'


@pytest.mark.parametrize('ordinal,person', [('1st', '1'), ('2nd', '2'), ('3rd', '3')])
@pytest.mark.parametrize('key', ['pers', 'person', 'Person'])
def test_literal_person_ordinals_are_canonical_not_lost(ordinal, person, key):
    parsed = canonical_features({'features': {key: ordinal}})
    assert parsed['Person'] == person
    assert compact_parse(parsed) == ordinal


@pytest.mark.parametrize('candidate', [
    {'features': {'pers': ['1st', '2nd']}},
    {'features': {'pers': '1st,3rd'}},
    {'features': {'pers': '1st', 'Person': '2'}},
    {'features': {'pers': '1st'}, 'source_tags': ['third-person']},
    {'features': {'pers': ['1st', '2nd']}, 'source_tags': ['first-person']},
])
def test_conflicting_person_values_do_not_get_an_arbitrary_winner(candidate):
    assert 'Person' not in canonical_features(candidate)


@pytest.mark.parametrize('features,expected', [({'voice': 'mediopassive'}, {'Voice': 'Med'}),
    ({'mood': 'infinitive'}, {'VerbForm': 'Inf'}), ({'mood': 'participle'}, {'VerbForm': 'Part'}),
    ({'pofs': 'verb participle'}, {'POS': 'VERB', 'VerbForm': 'Part'})])
def test_explicit_machine_nonfinite_and_voice_labels(features, expected):
    before = deepcopy(features)
    assert canonical_features({'features': features}) == expected
    assert features == before


@pytest.mark.parametrize('features', [{'mood': ['infinitive', 'indicative']},
    {'mood': 'infinitive', 'VerbForm': 'Part'}, {'voice': ['mediopassive', 'active']}])
def test_machine_label_conflicts_remain_unresolved(features):
    assert canonical_features({'features': features}) == {}


def test_default_disabled_leaves_existing_response_contract_unchanged():
    result = run_actual(False)
    assert 'machine_subentry_evidence' not in result
    assert 'machine_subentries' not in result['tokens'][0]
    assert 'machine_subentry_alternatives' not in meaning(result)


def test_standalone_lookup_reuses_same_source_binding_without_occurrence_claim():
    original, passage, machine, callback = actual_fixture()
    before = deepcopy(original)
    result = machine_dictionary_lookup(original['form'],
        machine_lookup=lambda form: machine.analyze(form, None, fetch=False), subentry_lookup=callback)
    assert original == before
    assert result['scope'] == 'standalone_form_query' and 'passage' not in result
    assert result['tokens'][0]['source_candidates'] == []
    refs = meaning(result)['machine_subentry_alternatives']
    assert len(refs) == 1 and meaning(result)['gloss']['text'] is None
    binding = result['machine_subentry_evidence']['bindings'][refs[0]['binding_ref']]
    assert binding['contextually_selected'] is False and binding['occurrence_attested'] is False


@pytest.mark.parametrize('status,returned_form,expected', [('cache_miss', 'query', 'cache_miss'),
    ('no_analyses', 'query', 'no_analyses'), ('ok', 'other', 'unavailable')])
def test_standalone_missing_or_different_machine_form_never_calls_dictionary(status, returned_form, expected):
    def forbidden(token):
        raise AssertionError('Unavailable or mismatched parser result must not resolve a source entry')
    result = machine_dictionary_lookup('query', machine_lookup=lambda form: {'status': status, 'form': returned_form},
                                      subentry_lookup=forbidden)
    assert result['status'] == expected and result['tokens'] == []
    assert 'machine_subentry_evidence' not in result


@pytest.mark.parametrize('field,value', [('lemma', 'wrong'), ('id', 'machine:wrong'),
                                       ('receipt_id', '0' * 64), ('features', {})])
def test_changed_machine_candidate_cannot_reuse_valid_source_refs(actual, field, value):
    result = deepcopy(actual)
    result['tokens'][0]['machine']['machine_candidates'][0][field] = value
    views = interlinear_reading(result)['readings'][0]['tokens'][0]['candidate_meanings']
    assert all(not row.get('machine_subentry_alternatives') for row in views)


def test_changed_catalog_without_new_digest_fails_closed(actual):
    result = deepcopy(actual)
    source = next(iter(result['machine_subentry_evidence']['subentries'].values()))['source_subentry']
    source['dictionary_senses'][0]['text'] = 'tampered synthetic content'
    assert not meaning(result).get('machine_subentry_alternatives')


def rebuild_catalog_with_mutation(actual, mutate):
    result = deepcopy(actual)
    catalog = result['machine_subentry_evidence']
    ref = result['tokens'][0]['machine_subentries']
    envelope = catalog['inventories'][ref['inventory_ref']]
    body = {k: deepcopy(v) for k, v in envelope.items() if k not in
            {'dependency_ref', 'candidates', 'supporting_subentries', 'supporting_receipts'}}
    body['dependencies'] = catalog['dependencies'][envelope['dependency_ref']]
    for field, pool in (('candidates', 'bindings'), ('supporting_subentries', 'subentries'), ('supporting_receipts', 'receipts')):
        body[field] = [catalog[pool][identifier] for identifier in envelope[field]]
    mutate(body)
    body['inventory_sha256'] = _subentry_digest(body)
    result['machine_subentry_evidence'] = {'version': 1}
    result['tokens'][0]['machine_subentries'] = catalog_machine_subentries(result['machine_subentry_evidence'], body)
    return result


@pytest.mark.parametrize('field,value', [('entry_id', 'wrong'), ('lexicon_entry_id', 'wrong'),
    ('raw_sha256', '0' * 64), ('source_url', 'https://example.invalid/wrong'), ('language', 'el'),
    ('form_scope', {'relation': 'headword', 'text': 'wrong'}), ('source_locator', None)])
def test_sense_ownership_checked_even_if_catalog_digest_recomputed(actual, field, value):
    def mutate(body):
        body['supporting_subentries'][0]['source_subentry']['dictionary_senses'][0][field] = value
    result = rebuild_catalog_with_mutation(actual, mutate)
    assert not meaning(result).get('machine_subentry_alternatives')


def test_ineligible_preview_never_exposed_even_if_catalog_digest_recomputed(actual):
    result = rebuild_catalog_with_mutation(actual, lambda body: body['supporting_subentries'][0]['english_preview'].update(eligible=False))
    assert not meaning(result).get('machine_subentry_alternatives')


def test_same_source_identity_conflict_cannot_overwrite_pooled_proof(actual):
    catalog = deepcopy(actual['machine_subentry_evidence'])
    broken = rebuild_catalog_with_mutation(actual, lambda body: body['supporting_subentries'][0]['source_subentry'].update(orthography='wrong'))
    envelope = next(iter(broken['machine_subentry_evidence']['inventories'].values()))
    # Reuse the collection with a different pool payload: a second catalog
    # insertion must reject it transactionally, leaving previous proof intact.
    original, passage, machine, callback = actual_fixture()
    payload = callback({'kind': 'word', 'text': original['form'], 'machine': original})
    payload['supporting_subentries'][0]['source_subentry']['orthography'] = 'wrong'
    payload['inventory_sha256'] = _subentry_digest({k: v for k, v in payload.items() if k != 'inventory_sha256'})
    before = deepcopy(catalog)
    with pytest.raises(ValueError, match='Conflicting pooled'):
        catalog_machine_subentries(catalog, payload)
    assert catalog == before


def test_bounded_callback_unavailable_and_editorial_tokens_never_fetch():
    calls = []
    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            assert fetch is False
            return {'status': 'ok', 'form': form, 'machine_candidates': []}
    def callback(token):
        calls.append(token['text'])
        raise OSError('fixture unavailable')
    text = ' '.join('α' * n for n in range(1, 27)) + ' α α̣'
    passage = {'id': 'synthetic:limit', 'kind': 'text', 'language': 'grc', 'text': text}
    service = PassageAnalysisService(lambda identifier: passage, lambda *args: {}, machine_service=Machine(), machine_subentry_lookup=callback)
    result = service.analyze({'passage_id': passage['id'], 'start': 0, 'end': len(text), 'offset_unit': 'codepoint', 'selected_text': text})
    assert len(calls) == MAX_MACHINE_SUBENTRY_LOOKUPS
    assert any(t.get('machine_subentries', {}).get('status') == 'request_limit' for t in result['tokens'])
    # An underdotted word is analysed as the editor's reading; here the
    # bounded callback budget is already spent, so it reports the limit.
    assert result['tokens'][-1]['uncertain_letters'] is True
    assert result['tokens'][-1]['form'] == 'α'
    # Its reading 'α' repeats the first token, whose failed callback was cached.
    assert result['tokens'][-1]['machine_subentries']['status'] in ('unavailable', 'request_limit')


def test_repeated_form_reuses_one_callback_and_one_evidence_catalog():
    original, _, machine, callback = actual_fixture()
    # Synthetic repetition exercises transport; it adds no corpus text.
    text = original['form'] + ' ' + original['form']
    passage = {'id': 'synthetic:repetition', 'kind': 'text', 'language': 'grc', 'text': text}
    calls = []
    def counted(token):
        calls.append(token['text'])
        return callback(token)
    service = PassageAnalysisService(lambda identifier: passage, lambda *args: {},
                                     machine_service=machine, machine_subentry_lookup=counted)
    result = service.analyze({'passage_id': passage['id'], 'start': 0, 'end': len(text),
                              'offset_unit': 'codepoint', 'selected_text': text})
    assert calls == [original['form']]
    assert result['tokens'][0]['machine_subentries'] == result['tokens'][2]['machine_subentries']
    for pool in ('dependencies', 'subentries', 'receipts', 'bindings', 'inventories'):
        assert len(result['machine_subentry_evidence'][pool]) == 1
    assert result['tokens'][0]['start'] != result['tokens'][2]['start']


def test_no_exact_subentry_is_preserved_not_reported_as_failure(actual):
    def mutate(body):
        body.update(status='no_exact_subentry', candidates=[], supporting_subentries=[], supporting_receipts=[])
    result = rebuild_catalog_with_mutation(actual, mutate)
    assert result['tokens'][0]['machine_subentries']['status'] == 'no_exact_subentry'
    assert not meaning(result).get('machine_subentry_alternatives')


def test_catalog_envelope_failure_is_transactional():
    original, _, _, callback = actual_fixture()
    payload = callback({'kind': 'word', 'text': original['form'], 'machine': original})
    payload.pop('status')
    payload['inventory_sha256'] = _subentry_digest({k: v for k, v in payload.items() if k != 'inventory_sha256'})
    catalog = {'version': 1}
    before = deepcopy(catalog)
    with pytest.raises(ValueError, match='envelope'):
        catalog_machine_subentries(catalog, payload)
    assert catalog == before


def test_coordinated_unrelated_orthography_cannot_borrow_source_scope(actual):
    def mutate(body):
        source = body['supporting_subentries'][0]['source_subentry']
        source['orthography'] = 'unrelated'
        for sense in source['dictionary_senses']:
            sense['form_scope']['text'] = 'unrelated'
    assert not meaning(rebuild_catalog_with_mutation(actual, mutate)).get('machine_subentry_alternatives')


def test_binding_identity_recomputed_from_entire_binding(actual):
    def mutate(body):
        body['candidates'][0]['id'] = 'machine-subentry:' + '0' * 64
    assert not meaning(rebuild_catalog_with_mutation(actual, mutate)).get('machine_subentry_alternatives')


if __name__ == '__main__':
    # Reproducible read-only integration replay, saved separately from source
    # receipts for frontend QA. This writes no corpus or production records.
    target = ROOT / 'runtime/alcaeus-morpheus-maintenance/subentry-integration-response.json'
    target.write_text(json.dumps(run_actual(), ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(target)
