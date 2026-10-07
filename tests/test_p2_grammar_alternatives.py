"""Synthetic annotation tests; these strings are never literary corpus data."""
from scripts.extract_p2_notes import first_grammar, grammar_objects


def extract(body):
    prefix = 'SYNTHETIC '
    return grammar_objects(first_grammar(body), prefix + body, body, len(prefix))


def test_direct_annotation_retains_two_exact_branches_without_inheritance():
    body = '( aor. act. inf. or 2nd sg. aor. mid. imper. from SOURCE )'
    rows = extract(body)
    assert len(rows) == 2
    assert rows[0]['features'] == {'tense': 'aorist', 'voice': 'active', 'mood': 'infinitive'}
    assert rows[1]['features']['mood'] == 'imperative'
    quote = 'SYNTHETIC ' + body
    for row in rows:
        span = row['source_grammar_branch']
        assert quote[span['quote_start']:span['quote_end']] == row['raw_label']


def test_explicit_equivalent_prefix_keeps_direct_annotation_scope():
    rows = extract('Aeol. for \u03b1\u03b2 (aor. act. inf. or 2nd sg. aor. mid. imper. from SOURCE)')
    assert len(rows) == 2
    assert {row['source_grammar_scope'] for row in rows} == {'direct_headword_parenthesis'}


def test_abbreviated_second_branch_does_not_inherit_verbal_or_gender_features():
    rows = extract('(pres. act. partic. fem. acc. sg. or gen. pl. from SOURCE)')
    assert len(rows) == 2
    assert rows[1]['features'] == {'case': 'genitive', 'number': 'plural'}


def test_discussion_of_substring_remains_qualified_not_new_whole_word_parse():
    rows = extract('It is unclear where word breaks are; OTHER could be an acc. sg. fem. or a gen. pl. of SOURCE')
    assert len(rows) == 1
    assert rows[0]['source_grammar_scope'] == 'unresolved_prose_scope'
    assert len(rows[0]['source_grammar_alternatives'][0]['branches']) == 2
    assert 'source_grammar_branch' not in rows[0]


def test_lexical_or_does_not_change_original_object():
    assert extract('(aor. act. inf. from SOURCE) to come or go') == [
        {'raw_label': 'aor. act. inf.', 'features': {'tense': 'aorist', 'voice': 'active', 'mood': 'infinitive'}}]


def test_unclosed_direct_annotation_is_not_split():
    rows = extract('(aor. act. inf. or aor. mid. imper. from SOURCE')
    assert len(rows) == 1
    assert rows[0]['source_grammar_scope'] == 'unresolved_annotation_boundary'
