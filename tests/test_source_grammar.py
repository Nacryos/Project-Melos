"""Synthetic annotation mechanics; no fixture is added to literary datasets."""
from copy import deepcopy

from backend.source_grammar import grammar_disjunctions, projection_qualification
from backend.evidence import EvidenceIndex


QUOTE = 'SYNTHETIC (aor. act. inf. or 2nd sg. aor. mid. imper. from SOURCE) to talk'


def claim(identifier='one', raw='aor. act. inf.', features=None, quote=QUOTE):
    return {'id': identifier, 'predicate': 'morphology',
            'subject': {'type': 'form', 'form': 'SYNTHETIC', 'passage_id': 'synthetic-passage'},
            'object': {'raw_label': raw, 'features': features or {'tense': 'aorist', 'voice': 'active', 'mood': 'infinitive'}},
            'evidence': [{'record_id': 'synthetic-note', 'quote': quote,
                          'source_url': 'https://example.test/synthetic', 'raw_sha256': 'synthetic-hash'}],
            'status': 'source_claim', 'assertion_type': 'extracted_annotation',
            'source_family': 'Synthetic test source', 'strength': 'explicit_passage_link',
            'match_reason': 'Synthetic mechanics only'}


def second():
    return claim('two', '2nd sg. aor. mid. imper.',
                 {'person': 2, 'number': 'singular', 'tense': 'aorist', 'voice': 'middle', 'mood': 'imperative'})


def test_missing_source_branch_blocks_one_sided_features_and_preserves_exact_spans():
    source = claim(); before = deepcopy(source)
    result = projection_qualification(source, [source])
    assert result['source_projection_status'] == 'incomplete_explicit_alternatives'
    proof = result['source_grammar_alternatives'][0]
    assert proof['conflicting_feature_keys'] == ['mood', 'voice']
    for branch in proof['branches']:
        assert QUOTE[branch['start']:branch['end']] == branch['raw_label']
    assert source == before


def test_fully_represented_same_source_inventory_remains_available():
    inventory = [claim(), second()]
    for source in inventory:
        assert projection_qualification(source, inventory)['source_projection_status'] == 'explicit_alternatives_represented'


def test_shared_partial_does_not_inherit_case_gender_or_number():
    source = claim(raw='pres. act. partic.', features={'tense': 'present', 'voice': 'active', 'mood': 'participle'},
                   quote='SYNTHETIC (pres. act. partic. fem. acc. sg. or gen. pl. from SOURCE)')
    result = projection_qualification(source, [source])
    assert result['source_projection_status'] == 'partial_with_explicit_alternatives'
    assert result['source_grammar_alternatives'][0]['conflicting_feature_keys'] == []
    assert source['object']['features'] == {'tense': 'present', 'voice': 'active', 'mood': 'participle'}


def test_lexical_or_and_unrelated_grammar_or_do_not_flag_current_label():
    for quote in ['SYNTHETIC (aor. act. inf. from SOURCE) to come or go',
                  'SYNTHETIC (aor. act. inf. from SOURCE). OTHER WORD (gen. or dat.)']:
        source = claim(quote=quote)
        assert projection_qualification(source, [source]) == {}


def test_different_subject_or_source_cannot_complete_inventory():
    for changed in ['subject', 'evidence']:
        source, other = claim(), second()
        if changed == 'subject':
            other['subject']['form'] = 'OTHER SYNTHETIC FORM'
        else:
            other['evidence'][0]['raw_sha256'] = 'other-source'
        assert projection_qualification(source, [source, other])['source_projection_status'] == 'incomplete_explicit_alternatives'


def test_partial_second_branch_does_not_gain_unprinted_features():
    proof = grammar_disjunctions('SYNTHETIC (dat. pl. masc. or neut.)')[0]
    assert proof['branches'][1]['explicit_features'] == {'gender': 'neuter'}


def test_article_and_three_branches_preserved_without_guessing():
    proof = grammar_disjunctions('SYNTHETIC (acc. sg. fem. or a gen. pl. or dat. pl.)')[0]
    assert len(proof['branches']) == 3
    assert proof['source_text'] == 'acc. sg. fem. or a gen. pl. or dat. pl.'


def test_candidate_limit_cannot_hide_branch_and_lift_safety_guard(monkeypatch, tmp_path):
    index = EvidenceIndex(tmp_path / 'unused.sqlite')
    sources = [claim(), second()]
    monkeypatch.setattr(index, 'lookup', lambda *args, **kwargs: {'claims': sources, 'total': 2})
    monkeypatch.setattr(index, '_wiktionary_entry_context', lambda claims: {})
    full = index.candidate_analyses('SYNTHETIC', limit=2)
    assert {r['source_projection_status'] for r in full['candidates']} == {'explicit_alternatives_represented'}
    limited = index.candidate_analyses('SYNTHETIC', limit=1)
    assert limited['candidates'][0]['source_projection_status'] == 'incomplete_explicit_alternatives'
    assert limited['warnings']


def test_raw_label_is_not_a_prefix_of_a_different_source_token():
    source = claim(raw='inf', quote='SYNTHETIC (infinitive or imperative)')
    assert projection_qualification(source, [source]) == {}


def test_repeated_label_cannot_bind_unrelated_later_disjunction():
    quote = 'SYNTHETIC (aor. act. inf. from SOURCE). OTHER (aor. act. inf. or aor. mid. imper.)'
    source = claim(quote=quote)
    assert projection_qualification(source, [source]) == {}


def test_explicit_branch_offset_must_match_exact_label_and_quote():
    quote = 'SYNTHETIC (aor. act. inf. from SOURCE). OTHER (aor. act. inf. or aor. mid. imper.)'
    source = claim(quote=quote)
    first = quote.index('aor. act. inf.')
    source['object']['source_grammar_branch'] = {'quote_start': first, 'quote_end': first + len('aor. act. inf.')}
    assert projection_qualification(source, [source]) == {}
    start = quote.rindex('aor. act. inf.')
    source['object']['source_grammar_branch'] = {'quote_start': start, 'quote_end': start + len('aor. act. inf.')}
    assert projection_qualification(source, [source])['source_projection_status'] == 'incomplete_explicit_alternatives'
    source['object']['source_grammar_branch']['quote_start'] += 1
    assert projection_qualification(source, [source]) == {}
