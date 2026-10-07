"""Synthetic plumbing regressions; these fixtures are never corpus data."""
from copy import deepcopy

from backend.interlinear import join_machine_dictionary, interlinear_reading
from backend.passage_analysis import PassageAnalysisService, MAX_DICTIONARY_LEMMA_LOOKUPS


def token():
    return {'id': 't0', 'text': 'α', 'kind': 'word', 'start': 0, 'end': 1,
            'start_utf16': 0, 'end_utf16': 1, 'source_candidates': [],
            'machine': {'machine_candidates': [
                {'id': 'machine:1', 'lemma': 'β', 'basis': 'machine_analysis',
                 'features': {'case': 'accusative', 'gend': 'feminine', 'num': 'singular', 'pofs': 'adjective'}}]}}


def entry(lemma='β', identifier='synthetic:1'):
    return {'id': identifier, 'lemma': lemma, 'source': 'synthetic LSJ',
            'dictionary_senses': [{'id': identifier + ':sense', 'lexicon_entry_id': identifier,
                'text': 'synthetic meaning', 'language': 'en', 'source': 'synthetic LSJ',
                'evidence_type': 'dictionary_sense'}]}


def projected(row, syntax=None):
    result = {'selection': {'text': 'α'}, 'tokens': [row],
              'syntax': {'state': 'ready', 'tokens': [syntax]} if syntax else {}}
    return interlinear_reading(result)['readings'][0]['tokens'][0]


def test_exact_dictionary_bridge_does_not_copy_occurrence_claims():
    row = token()
    found = {'lexicon_entries': [entry(), entry('γ', 'synthetic:wrong')],
             'candidates': [{'lemma': 'invented-fixture', 'analysis': 'wrong'}],
             'structured_evidence': {'claims': [{'id': 'not-this-occurrence'}]}}
    before = deepcopy(found)
    join_machine_dictionary(row, lambda lemma: found)
    assert found == before
    assert [item['id'] for item in row['lexicon_entries']] == ['synthetic:1']
    assert row['source_candidates'] == []
    candidate = row['machine']['machine_candidates'][0]
    assert candidate['basis'] == 'machine_analysis'
    assert candidate['dictionary_join']['occurrence_attested'] is False
    assert projected(row)['gloss']['text'] == 'synthetic meaning'


def test_conflicting_syntax_does_not_erase_parser_alternative_or_assert_it():
    row = token()
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry()]})
    syntax = {'id': 1, 'text': 'α', 'absolute_start': 0, 'absolute_end': 1,
              'lemma': 'γ', 'upos': 'VERB', 'features': {'Number': 'Plur'}}
    view = projected(row, syntax)
    # The parser's single full analysis is shown; the disagreeing statistical
    # prediction is recorded as a conflict rather than erasing the parse.
    assert view['syntax_conflict'] is True
    assert view['selection_basis'] == 'single_candidate_despite_syntax_conflict'
    assert view['features']['POS'] == 'ADJ'
    assert view['gloss']['text'] == 'synthetic meaning'
    assert view['lemma'] == row['machine']['machine_candidates'][0]['lemma']
    assert view['candidate_meanings'][0]['gloss']['text'] == 'synthetic meaning'
    assert view['candidate_meanings'][0]['status'] == 'unresolved_alternative'
    assert view['candidate_meanings'][0]['features']['POS'] == 'ADJ'


def test_multiple_parses_retain_separate_meanings_without_arbitrary_choice():
    row = token()
    row['machine']['machine_candidates'].append(
        {**row['machine']['machine_candidates'][0], 'id': 'machine:2', 'lemma': 'γ'})
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry(lemma, 'synthetic:' + lemma)]})
    view = projected(row)
    assert view['gloss']['text'] is None
    assert view['status'] == 'ambiguous'
    assert len(view['candidate_meanings']) == 2
    assert all(item['gloss']['text'] for item in view['candidate_meanings'])


def test_missing_shared_features_is_not_a_syntax_conflict():
    row = token()
    row['machine']['machine_candidates'][0]['features'] = {}
    syntax = {'id': 1, 'text': 'α', 'absolute_start': 0, 'absolute_end': 1,
              'lemma': 'β', 'upos': 'ADJ', 'features': {'Number': 'Sing'}}
    view = projected(row, syntax)
    assert view['syntax_conflict'] is False
    assert view['features']['Number'] == 'Sing'
    assert view['selection_basis'] == 'syntax_prediction'
    assert view['gloss']['text'] is None


def test_homographs_stay_unresolved_even_with_exact_spelling():
    row = token()
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry(), entry(identifier='synthetic:2')]})
    assert projected(row)['gloss']['text'] is None
    assert projected(row)['candidate_meanings'][0]['gloss']['text'] is None


def traced_entry(identifier, homograph=None):
    source = entry(identifier=identifier)
    if homograph:
        source['homograph_id'] = homograph
    sense = source['dictionary_senses'][0]
    sense.update(entry_id=identifier, source_url='https://example.invalid/synthetic-source',
                 source_locator={'node_path': '/synthetic/gloss'}, raw_sha256='a' * 64)
    return source


def test_unresolved_homographs_preserve_per_entry_literal_senses_without_winner():
    row = token()
    entries = [traced_entry('synthetic:one', '1'), traced_entry('synthetic:two', '2')]
    before = deepcopy(entries)
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': entries})
    view = projected(row)
    gloss = view['candidate_meanings'][0]['gloss']
    assert gloss['text'] is None and gloss['full_text'] is None
    assert gloss['status'] == 'alternatives'
    assert gloss['selection_basis'] == 'unresolved_dictionary_entries_not_contextual'
    assert [(item['id'], item['homograph_id']) for item in gloss['entry_alternatives']] == [
        ('synthetic:one', '1'), ('synthetic:two', '2')]
    assert gloss['alternatives'] == [source['dictionary_senses'][0] for source in entries]
    assert 'sense_id' not in gloss and 'entry_id' not in gloss
    assert entries == before


def test_unmarked_same_dictionary_entries_also_preserve_inventory_without_winner():
    row = token()
    entries = [traced_entry('synthetic:one'), traced_entry('synthetic:two')]
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': entries})
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert gloss['text'] is None
    assert len(gloss['entry_alternatives']) == 2


def test_unresolved_inventory_rejects_foreign_wrong_entry_and_untraced_senses():
    row = token()
    valid = traced_entry('synthetic:valid', '1')
    invalid = traced_entry('synthetic:invalid', '2')
    original = invalid['dictionary_senses'][0]
    invalid['dictionary_senses'] = [
        {**original, 'id': 'foreign', 'language': 'el'},
        {**original, 'id': 'wrong-pointer', 'lexicon_entry_id': 'other-entry'},
        {**original, 'id': 'missing-sha', 'raw_sha256': ''},
        {**original, 'id': 'missing-url', 'source_url': ''},
        {**original, 'id': 'missing-locator', 'source_locator': None},
    ]
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [valid, invalid]})
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert gloss['alternatives'] == valid['dictionary_senses']
    assert gloss['text'] is None
    assert len(gloss['entry_alternatives']) == 2
    assert gloss['entry_alternatives'][1]['sense_inventory_status'] == 'no_traced_english_senses'


def test_supplied_broken_entry_pointer_does_not_expand_to_homograph_inventory():
    row = token()
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [traced_entry('synthetic:one', '1')]})
    row['machine']['machine_candidates'][0]['gloss_entry_id'] = 'missing-pointer'
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert gloss['text'] is None
    assert not gloss.get('alternatives')


def test_unresolved_inventory_binds_both_qualified_and_raw_entry_ids():
    row = token()
    source = traced_entry('synthetic:qualified', '1')
    source['entry_id'] = 'raw-id'
    source['dictionary_senses'][0]['entry_id'] = 'raw-id'
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [source]})
    assert projected(row)['candidate_meanings'][0]['gloss']['alternatives'] == source['dictionary_senses']
    row['lexicon_entries'][0]['dictionary_senses'][0]['entry_id'] = 'wrong-raw-id'
    assert not projected(row)['candidate_meanings'][0]['gloss'].get('alternatives')


def test_conflicting_duplicate_entry_identity_fails_closed():
    row = token()
    first = traced_entry('synthetic:duplicate', '1')
    other = deepcopy(first)
    other['homograph_id'] = '2'
    row['lexicon_entries'] = [first, other]
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert gloss['selection_basis'] == 'conflicting_dictionary_inventory'
    assert gloss['text'] is None and not gloss.get('alternatives')


def test_conflicting_duplicate_sense_identity_fails_closed():
    row = token()
    first = traced_entry('synthetic:first', '1')
    second = traced_entry('synthetic:second', '2')
    second['dictionary_senses'][0]['id'] = first['dictionary_senses'][0]['id']
    row['lexicon_entries'] = [first, second]
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert gloss['selection_basis'] == 'conflicting_dictionary_inventory'
    assert not gloss.get('alternatives')


def test_identical_duplicate_payloads_deduplicate_without_losing_senses():
    row = token()
    source = traced_entry('synthetic:first', '1')
    source['dictionary_senses'].append(deepcopy(source['dictionary_senses'][0]))
    row['lexicon_entries'] = [source, deepcopy(source)]
    gloss = projected(row)['candidate_meanings'][0]['gloss']
    assert len(gloss['entry_alternatives']) == 1
    assert len(gloss['alternatives']) == 1
    assert gloss['text'] is None


def test_numbered_machine_identity_never_gets_lemma_only_join():
    row = token()
    row['machine']['machine_candidates'][0]['lemma_raw'] = 'β1'
    calls = []
    join_machine_dictionary(row, lambda lemma: calls.append(lemma))
    assert calls == []


def test_diacritics_never_fold_for_dictionary_identity():
    row = token()
    row['machine']['machine_candidates'][0]['lemma'] = 'ά'
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry('α')]})
    assert row['lexicon_entries'] == []
    assert projected(row)['gloss']['text'] is None


def test_modern_greek_definition_not_used_as_english():
    row = token()
    source = entry()
    source['dictionary_senses'][0]['language'] = 'el'
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [source]})
    assert projected(row)['gloss']['text'] is None


def test_bridge_keeps_existing_entries_and_deduplicates_by_source_id():
    row = token()
    row['lexicon_entries'] = [entry()]
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry()]})
    join_machine_dictionary(row, lambda lemma: {'lexicon_entries': [entry()]})
    assert len(row['lexicon_entries']) == 1


def test_editorial_fragment_has_no_candidate_meanings():
    row = token()
    row['editorial_fragment'] = True
    assert projected(row)['candidate_meanings'] == []


def test_request_lemma_bridge_is_cached_bounded_and_never_fetches_machine():
    calls = []
    candidates = [{**token()['machine']['machine_candidates'][0], 'lemma': chr(0x3b1 + i)}
                  for i in range(MAX_DICTIONARY_LEMMA_LOOKUPS + 2)]
    class Machine:
        def analyze(self, form, visitor_id, fetch=False):
            assert fetch is False
            return {'status': 'ready', 'machine_candidates': deepcopy(candidates)}
    def lookup(form, passage_id):
        if not passage_id:
            calls.append(form)
            return {'lexicon_entries': [entry(form, 'synthetic:' + form)]}
        return {}
    passage = {'id': 'synthetic:test', 'text': 'α α', 'language': 'grc', 'kind': 'text'}
    service = PassageAnalysisService(lambda identifier: passage, lookup, machine_service=Machine())
    result = service.analyze({'passage_id': passage['id'], 'start': 0, 'end': 3,
                              'offset_unit': 'codepoint', 'selected_text': passage['text']})
    assert len(calls) == MAX_DICTIONARY_LEMMA_LOOKUPS
    assert result['limits']['dictionary_lemma_lookups'] == MAX_DICTIONARY_LEMMA_LOOKUPS
    assert result['tokens'][0]['machine']['machine_candidates'][-1]['dictionary_join']['status'] == 'request_limit'
    assert result['tokens'][0]['machine'] == result['tokens'][2]['machine']
