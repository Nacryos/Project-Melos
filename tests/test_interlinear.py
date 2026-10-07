"""Synthetic UI-projection fixtures only; never added to the Greek corpus."""
from copy import deepcopy

import pytest

from backend.interlinear import canonical_features, compact_parse, interlinear_reading
from backend.passage_analysis import tokenize_span


def fixture(text='α β γ', *, gender='Fem', relation='amod'):
    tokens = tokenize_span(text, 0, len(text))
    syntax = []
    words = [row for row in tokens if row['kind'] == 'word']
    for i, row in enumerate(words):
        features = {'Case': 'Nom', 'Number': 'Sing', 'Gender': gender, 'POS': 'ADJ' if i == 0 else 'NOUN'}
        row['source_candidates'] = [{'id': f'c{i}', 'lemma': row['text'], 'matched_form': row['text'],
                                     'features': features, 'gloss': 'test sense; second sense', 'source': 'synthetic LSJ'}]
        syntax.append({'id': i, 'text': row['text'], 'absolute_start': row['start'], 'absolute_end': row['end'],
                       'features': deepcopy(features), 'head': 1 if i == 0 else None, 'deprel': relation if i == 0 else 'root',
                       'sentence_id': 0})
    return {'selection': {'text': text, 'start': 0, 'end': len(text)}, 'tokens': tokens,
            'syntax': {'state': 'ready', 'tokens': syntax}, 'ranking': {'items': []}}


def reading(result):
    return interlinear_reading(result)['readings'][0]


def words(result):
    return [row for row in reading(result)['tokens'] if row['kind'] == 'word']


def test_lossless_unicode_and_source_unchanged():
    result = fixture('😀 α\u0313  β\n[γ]')
    before = deepcopy(result)
    view = reading(result)
    assert ''.join(row['text'] for row in view['tokens']) == result['selection']['text']
    assert result == before
    assert words(result)[0]['start_utf16'] == 3


def test_only_related_modifier_has_agreement_color():
    view = reading(fixture())
    assert len(view['groups']) == 1
    assert view['groups'][0]['token_ids'] == ['t0', 't2']
    assert view['groups'][0]['label'] == 'nom. fem. sg.'
    assert view['tokens'][4]['agreement_group_id'] is None


@pytest.mark.parametrize('field,value', [('Case', 'Acc'), ('Number', 'Plur'), ('Gender', 'Masc')])
def test_disagreement_has_no_color(field, value):
    result = fixture()
    result['tokens'][0]['source_candidates'][0]['features'][field] = value
    result['syntax']['tokens'][0]['features'][field] = value
    assert not reading(result)['groups']


def test_unknown_case_has_no_color():
    result = fixture()
    del result['tokens'][0]['source_candidates'][0]['features']['Case']
    del result['syntax']['tokens'][0]['features']['Case']
    assert not reading(result)['groups']


@pytest.mark.parametrize('text', ['α … β', 'α. β', 'α [β]', 'α[β]'])
def test_editorial_and_sentence_boundaries_no_color(text):
    assert not reading(fixture(text))['groups']


def test_different_sentence_no_color():
    result = fixture()
    result['syntax']['tokens'][1]['sentence_id'] = 1
    assert not reading(result)['groups']


def test_nmod_allowed_for_adjective_not_noun():
    result = fixture(relation='nmod')
    assert reading(result)['groups']
    result['tokens'][0]['source_candidates'][0]['features']['POS'] = 'NOUN'
    result['syntax']['tokens'][0]['features']['POS'] = 'NOUN'
    assert not reading(result)['groups']


def test_homograph_candidates_do_not_get_arbitrary_gloss():
    result = fixture()
    original = result['tokens'][0]['source_candidates'][0]
    original['lemma_raw'] = 'α1'
    result['tokens'][0]['source_candidates'].append({**original, 'lemma_raw': 'α2'})
    first = words(result)[0]
    assert first['status'] == 'ambiguous'
    assert first['gloss']['text'] is None
    assert first['alternative_count'] == 2


def test_no_gloss_or_english_source_no_invented_translation():
    result = fixture()
    result['tokens'][0]['source_candidates'][0]['gloss'] = None
    assert words(result)[0]['gloss']['text'] is None
    result['tokens'][0]['source_candidates'][0]['gloss'] = 'δοκιμή'
    assert words(result)[0]['gloss']['text'] is None
    result['tokens'][0]['source_candidates'][0].update(gloss='test', gloss_language='el')
    assert words(result)[0]['gloss']['text'] is None


def test_complete_dictionary_sense_no_arbitrary_word_clipping():
    result = fixture()
    candidate = result['tokens'][0]['source_candidates'][0]
    candidate['gloss'] = 'of every kind; manifold'
    assert words(result)[0]['gloss']['text'] == 'of every kind'
    candidate['gloss'] = 'a very long definition that cannot responsibly be clipped'
    gloss = words(result)[0]['gloss']
    assert gloss['text'] == candidate['gloss']
    assert gloss['status'] == 'available'
    assert gloss['full_text'] == candidate['gloss']


def test_machine_candidate_can_use_only_exact_lemma_dictionary_entry():
    result = fixture()
    token = result['tokens'][0]
    machine = {**token['source_candidates'][0], 'lemma': 'κήλημα', 'gloss': None}
    machine.pop('matched_form')
    token['source_candidates'] = []
    token['machine'] = {'machine_candidates': [machine]}
    token['lexicon_entries'] = [{'id': 's:1', 'lemma': 'Κήλημα', 'gloss': 'charm, spell', 'source': 'LSJ'},
                               {'id': 's:2', 'lemma': 'κτῆμα', 'gloss': 'wrong', 'source': 'LSJ'}]
    assert words(result)[0]['gloss']['text'] == 'charm, spell'
    token['lexicon_entries'].append({'id': 's:3', 'lemma': 'κήλημα', 'gloss': 'another homograph', 'source': 'LSJ'})
    assert words(result)[0]['gloss']['text'] is None


def test_fuzzy_candidate_does_not_supply_source_gloss():
    result = fixture()
    result['tokens'][0]['source_candidates'][0]['edit_distance'] = 1
    assert words(result)[0]['gloss']['text'] is None


def test_repeated_words_keep_span_bound_syntax():
    result = fixture('α α')
    result['syntax']['tokens'][1]['features'] = {'Case': 'Acc', 'Number': 'Sing'}
    result['tokens'][2]['source_candidates'][0]['features'] = {'Case': 'Acc', 'Number': 'Sing'}
    assert [word['parse_short'] for word in words(result)] == ['nom. fem. sg.', 'acc. sg.']


def test_machine_source_and_ud_abbreviations():
    assert compact_parse(canonical_features({'features': {'case': 'dative', 'gend': 'neuter', 'num': 'plural', 'pofs': 'noun'}})) == 'dat. neut. pl.'
    assert compact_parse(canonical_features({'analysis': 'a-s---fn-'})) == 'nom. fem. sg.'
    assert compact_parse({'Person': '3', 'Number': 'Sing', 'Tense': 'Pres', 'Mood': 'Ind', 'Voice': 'Act'}) == '3rd sg. pres. ind. act.'


def test_no_syntax_still_keeps_unique_source_parse():
    result = fixture()
    result['syntax'] = {'state': 'unavailable'}
    assert words(result)[0]['selection_basis'] == 'unique_candidate'
    assert not reading(result)['groups']


def test_no_false_joint_alternative_readings_or_probabilities():
    result = interlinear_reading(fixture())
    assert len(result['readings']) == 1
    assert 'probability' not in result['readings'][0]


def test_wrong_syntax_lemma_is_flagged_but_does_not_erase_the_exact_source_parse():
    # The statistical lemmatizer mislemmatizes dialect spellings (νᾶσος → νῆσος).
    # A differing predicted lemma is recorded as a conflict, never a veto of the
    # exact-form source analysis and its dictionary gloss.
    result = fixture()
    result['syntax']['tokens'][0]['lemma'] = 'δ'
    row = words(result)[0]
    assert row['gloss']['text'] == 'test sense'
    assert row['syntax_conflict']
    assert row['candidate_id'] is not None


def test_explicit_homograph_identifiers_remain_distinct():
    result = fixture()
    first = result['tokens'][0]['source_candidates'][0]
    first['homograph_id'] = '1'
    result['tokens'][0]['source_candidates'].append({**first, 'homograph_id': '2'})
    assert words(result)[0]['status'] == 'ambiguous'


def shared_sense_fixture():
    result = fixture('α')
    result['syntax'] = {'state': 'unavailable'}
    token = result['tokens'][0]
    first = token['source_candidates'][0]
    first['gloss_entry_id'] = 'entry'
    token['source_candidates'].append({**deepcopy(first), 'id': 'other', 'features': {'Case': 'Acc'}})
    token['lexicon_entries'] = [{'id': 'entry', 'lemma': 'α', 'source': 'LSJ', 'dictionary_senses': [{
        'id': 'sense', 'entry_id': 'entry', 'text': 'synthetic meaning', 'language': 'eng',
        'evidence_type': 'dictionary_sense', 'source': 'LSJ', 'source_url': 'https://example.test/entry',
        'raw_sha256': 'a' * 64, 'source_locator': {'node_path': '/entry/sense'}}]}]
    return result


def test_shared_single_sourced_meaning_does_not_resolve_ambiguous_morphology():
    result = shared_sense_fixture()
    before = deepcopy(result)
    row = words(result)[0]
    assert row['gloss']['text'] == 'synthetic meaning'
    assert row['gloss']['selection_basis'] == 'shared_source_dictionary_sense_not_contextual'
    assert row['gloss']['supporting_candidate_ids'] == ['c0', 'other']
    assert row['candidate_id'] is None and row['features'] == {}
    assert result == before


def test_shared_dictionary_sense_survives_wrong_syntax_without_accepting_parse():
    result = shared_sense_fixture()
    result['syntax'] = {'state': 'ready', 'tokens': [{'id': 0, 'text': 'α', 'lemma': 'wrong',
        'absolute_start': 0, 'absolute_end': 1, 'features': {'POS': 'ADV'}}]}
    row = words(result)[0]
    assert row['gloss']['text'] == 'synthetic meaning'
    assert row['syntax_conflict'] and row['candidate_id'] is None and row['features'] == {}


@pytest.mark.parametrize('change', ['other_sense', 'unknown', 'homograph', 'no_morphology', 'nonenglish', 'unscoped'])
def test_shared_meaning_fails_closed_without_all_exact_source_agreement(change):
    result = shared_sense_fixture()
    token = result['tokens'][0]
    sense = token['lexicon_entries'][0]['dictionary_senses'][0]
    if change == 'other_sense': token['lexicon_entries'][0]['dictionary_senses'].append({**sense, 'id': 'sense-two', 'text': 'another meaning'})
    if change == 'unknown': token['source_candidates'][1]['gloss_entry_id'] = 'missing'
    if change == 'homograph':
        token['source_candidates'][0]['homograph_id'] = '1'
        token['source_candidates'][1]['homograph_id'] = '2'
    if change == 'no_morphology': token['source_candidates'][1]['features'] = {}
    if change == 'nonenglish': sense['language'] = 'ell'
    if change == 'unscoped': sense.pop('source_locator')
    assert words(result)[0]['gloss'].get('selection_basis') != 'shared_source_dictionary_sense_not_contextual'


def test_real_contextual_exact_form_not_suppressed_by_legacy_spelling_status():
    import json
    from pathlib import Path
    from backend.interlinear import _exact
    path = Path('runtime/alcaeus-occurrences/baseline/responses/d3d75937f3ba2c6df2d1431795138b8079d774455ff5d0f21a3d326c659ebaf7.json')
    if not path.exists(): pytest.skip('Read-only source receipt not installed')
    result = json.loads(path.read_text(encoding='utf8'))['body']
    token = next(row for row in result['tokens'] if row['text'] == 'δᾶμον')
    assert token['analysis_match_status'] == 'spelling_suggestions_only'
    assert all(not _exact(row, token) for row in token['source_candidates'])
    exact = token['contextual_candidates'][0]
    assert _exact(exact, token)
    wrong = deepcopy(exact); wrong['matched_form'] = 'other'; wrong.pop('matched_object_form', None)
    token['contextual_candidates'] = [wrong]
    assert not _exact(wrong, token)
    token['contextual_candidates'] = [exact]
    token['structured_evidence']['claims'] = []
    token['contextual_supporting_claims'] = []
    assert not _exact(exact, token)


def lexical_release_c_fixture(name):
    import json
    from pathlib import Path
    from backend.lexical_variants import project_variants
    path = Path('runtime/lexical-release-c/operational') / (name + '.response.json')
    if not path.exists(): pytest.skip('Read-only canary C receipt not installed')
    result = json.loads(path.read_text(encoding='utf8'))
    # Replay D's source projection from C's unchanged accepted raw claims;
    # no Greek, source claim, or syntax prediction is altered.
    for token in result['tokens']:
        if token.get('lexical_variants'):
            token['lexical_variants'] = project_variants(token['text'], token.get('lexical_variant_supporting_claims') or [])
    return result


@pytest.mark.parametrize('name', ['130b-432affe78674', '130b-b003725862e9'])
def test_verified_lexical_variant_conflict_suppresses_model_only_parse(name):
    result = lexical_release_c_fixture(name)
    before = deepcopy(result)
    row = words(result)[0]
    assert row['parse_short'] == '' and row['features'] == {}
    assert row['candidate_id'] is None and row['source_candidate'] is None
    assert row['syntax_conflict'] is True
    assert row['selection_basis'] == 'lexical_source_syntax_conflict'
    assert row['lexical_prediction_check']['variants'][0]['claim_ids']
    assert not reading(result)['groups']
    assert result == before


def test_damon_consistent_exact_source_features_survive_contradictory_model():
    result = lexical_release_c_fixture('129-1e649d40c42b')
    row = words(result)[0]
    assert row['parse_short'] == 'acc. sg.'
    assert row['features'] == {'Case': 'Acc', 'Number': 'Sing'}
    # The model mislemmatizes the dialect form (δῆμος for δᾶμος); that lemma
    # disagreement is flagged, and the exact source analysis is selected.
    assert row['selection_basis'] == 'unique_compatible_candidate'
    assert row['syntax_conflict'] and row['candidate_id'] is not None
    assert row['morphology_ranking'] and row['morphology_ranking'][0]['parse_short'] == 'acc. sg.'


def test_source_consensus_fallback_never_inherits_machine_only_features():
    from backend.interlinear import _morphology_consensus
    source = {'id': 'source', 'lemma': 'x', 'features': {'Case': 'Acc'}}
    machine = {'id': 'machine', 'lemma': 'x', 'candidate_kind': 'machine_analysis',
               'features': {'Case': 'Acc', 'Number': 'Sing', 'Gender': 'Masc'}}
    syntax = {'lemma': 'wrong', 'features': {'POS': 'ADV'}}
    assert _morphology_consensus([source, machine], syntax) == ({}, [])
    source['features'] = deepcopy(machine['features'])
    assert _morphology_consensus([source, machine], syntax) == (source['features'], ['source'])
    machine['features']['Case'] = 'Dat'
    assert _morphology_consensus([source, machine], syntax) == ({}, [])


@pytest.mark.parametrize('damage', ['missing_proof', 'unbound_variant', 'disagreeing_pos_proof', 'partial'])
def test_lexical_veto_requires_exact_bound_complete_source_projection(damage):
    result = lexical_release_c_fixture('130b-b003725862e9')
    token = next(row for row in result['tokens'] if row['kind'] == 'word')
    if damage == 'missing_proof': token['lexical_variant_supporting_claims'] = []
    if damage == 'unbound_variant': token['lexical_variants'][0]['lemma'] = 'forged'
    if damage == 'partial': token['editorial_fragment'] = True
    if damage == 'disagreeing_pos_proof':
        claim = next(row for row in token['lexical_variant_supporting_claims'] if row['predicate'] == 'morphology')
        claim['object']['pos'] = 'noun'
    row = words(result)[0]
    assert 'lexical_prediction_check' not in row


def test_lexical_pos_never_becomes_full_morphology_and_matching_model_stays_prediction():
    result = lexical_release_c_fixture('130b-b003725862e9')
    token = next(row for row in result['tokens'] if row['kind'] == 'word')
    syntax = next(row for row in result['syntax']['tokens'] if row.get('selected'))
    syntax.update(lemma=token['lexical_variants'][0]['lemma'], upos='ADV', features={})
    row = words(result)[0]
    assert 'lexical_prediction_check' not in row
    assert row['selection_basis'] == 'syntax_prediction'
    assert row['candidate_id'] is None


def test_provenance_and_incomplete_qualifier_are_not_glosses():
    result = fixture()
    first = result['tokens'][0]['source_candidates'][0]
    first.pop('source'); first.pop('id'); first['gloss_language'] = 'en'
    assert words(result)[0]['gloss']['text'] is None
    first['source'] = 'synthetic LSJ'
    first['gloss'] = '(figuratively); brightness'
    assert words(result)[0]['gloss']['text'] is None
    first['gloss'] = 'not X, but Y'
    assert words(result)[0]['gloss']['text'] == 'not X, but Y'


def test_decisive_jev_must_match_syntax_and_exact_occurrence():
    result = fixture()
    first = result['tokens'][0]['source_candidates'][0]
    alternative = {**first, 'id': 'other', 'lemma': 'δ'}
    result['tokens'][0]['source_candidates'].append(alternative)
    result['ranking']['items'] = [{'token_id': 't0', 'decision': {'status': 'proposed', 'candidate_id': 'c0',
        'model_probabilities_uncalibrated': {'c0': .9, 'other': .05, 'abstain': .05},
        'packet': {'candidates': [first, alternative]}}}]
    assert words(result)[0]['selection_basis'] == 'jev_syntax_compatible'
    result['ranking']['items'][0]['decision']['model_probabilities_uncalibrated']['abstain'] = .85
    assert words(result)[0]['status'] == 'ambiguous'
