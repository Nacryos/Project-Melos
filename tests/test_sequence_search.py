"""Synthetic mechanics fixtures only; no rows are literary/source data."""
import hashlib
import json
import sqlite3
import unicodedata
import pytest
from backend import sequence_search as seq
from backend import expansion
from backend.textutils import normalize, tokenize, search_text


def groups(*values):
    return [{'query_index': i, 'query_term': next(iter(value)) if isinstance(value, set) else value,
             'alternatives': {normalize(key): [{'kind': 'literal_query', 'form': key}]
                              for key in (value if isinstance(value, set) else [value])}}
            for i, value in enumerate(values)]


def test_order_proximity_all_terms_and_gap_boundaries():
    query = groups('alpha', 'beta')
    assert seq.verify('alpha beta', query)
    assert not seq.verify('beta alpha', query)
    assert seq.verify('beta alpha', query, 'proximity')
    assert not seq.verify('alpha extra beta', query)
    assert seq.verify('alpha extra beta', query, slop=1)['extra_words'] == 1
    assert not seq.verify('alpha extra extra beta', query, slop=1)
    assert seq.verify('beta one two alpha', query, 'all_terms')['extra_words'] is None
    assert not seq.verify('alpha alone', query, 'all_terms')
    assert seq.verify('alpha, beta.', query)


def test_query_token_occurrences_preserve_beta_code_and_split_greek_punctuation():
    assert seq.query_terms('a)/peira di/ktua') == ['a)/peira', 'di/ktua']
    assert seq.query_terms('κηλήμασι,παντοδαποῖς') == ['κηλήμασι', 'παντοδαποῖς']
    assert seq.query_terms("Eudousin d' oreon") == ['Eudousin', "d'", 'oreon']
    assert seq.query_terms('ἄπει-\nρα δίκτυα') == ['ἄπειρα', 'δίκτυα']


def test_repeated_and_overlapping_terms_need_distinct_positions():
    assert not seq.verify('alpha', groups('alpha', 'alpha'), 'all_terms')
    assert seq.verify('alpha alpha', groups('alpha', 'alpha'))
    query = groups({'alpha', 'beta'}, {'alpha'})
    assert not seq.verify('alpha', query, 'proximity')
    match = seq.verify('alpha beta', query, 'proximity')
    assert [term['token_index'] for term in match['terms']] == [1, 0]
    assert not seq.verify('alpha beta', query)


@pytest.mark.parametrize('text', ['alpha [ ] beta', 'alpha ... beta', 'alpha † beta',
                                  '[before alpha beta after]', 'before [alpha beta after',
                                  'before alpha beta] after', '<before alpha beta after>',
                                  'alpha\u0323 beta', 'alpha [restored words] beta'])
def test_editorial_damage_cannot_authorize_ordered_phrase(text):
    assert seq.verify(text, groups('alpha', 'beta'), slop=50) is None


def test_all_terms_can_cross_gap_but_not_use_restored_interior():
    assert seq.verify('alpha [ ] beta', groups('alpha', 'beta'), 'all_terms')
    assert not seq.verify('[before alpha beta after]', groups('alpha', 'beta'), 'all_terms')


def test_unmatched_brackets_do_not_quarantine_separate_later_source_lines():
    assert seq.verify('broken [text\nalpha beta', groups('alpha', 'beta'))
    assert seq.verify('alpha beta\nbroken] text', groups('alpha', 'beta'))
    # An explicitly closed multi-line region remains a marked region.
    assert not seq.verify('[before\nalpha beta\nafter]', groups('alpha', 'beta'))


def test_safe_division_nfd_original_offsets_and_raw_hash():
    raw = unicodedata.normalize('NFD', 'ἀλ-\nφα βήτα')
    proof = seq.verify(raw, groups('ἀλφα', 'βήτα'))
    assert proof
    assert len(proof['terms'][0]['source_spans']) == 2
    for term in proof['terms']:
        for span in term['source_spans']:
            assert raw[span['start']:span['end']] == span['text']
    assert proof['text_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert seq.verify('ἀλ-\nφα-\nβη γα', groups('ἀλφαβη', 'γα'))


@pytest.mark.parametrize('raw', ['[ἀλ-\nφα-\nβη γα', 'ἀλ-\nφα-\nβη] γα',
                                 'ἀλ̣-\nφα-\nβη γα', 'ἀλ᾽-\nφα γα'])
def test_rejected_chain_no_join_or_suffix_salvage(raw):
    assert not seq.verify(raw, groups('ἀλφαβη', 'γα'))
    assert not seq.verify(raw, groups('φαβη', 'γα'))


@pytest.mark.parametrize('sign', ["'", '’', '᾽', 'ʼ', '᾿'])
def test_final_elision_retained_but_bare_word_does_not_match(sign):
    raw = 'ἀλ-\nφα' + sign + ' γα'
    assert seq.verify(raw, groups('ἀλφα' + sign, 'γα'))
    assert not seq.verify(raw, groups('ἀλφα', 'γα'))


@pytest.mark.parametrize('sign', ['-', '\u2010', '\u00ad'])
def test_orphan_or_nonjoining_divisions_do_not_authorize_intact_forms(sign):
    for raw in [f'αλφα{sign} βητα', f'{sign}αλφα βητα', f'αλφα {sign}βητα', f'αλφα βητα{sign}',
                f'[] {sign}\nαλφα βητα', f'αλφα {sign} βητα']:
        assert not seq.verify(raw, groups('αλφα', 'βητα')), raw
    assert not seq.verify(f'αλφα{sign}\n', groups('αλφα', 'αλφα'), 'all_terms')
    assert seq.source_tokens(f'αλφα{sign}\n')[0]['eligible'] is False
    assert seq.verify(f'αλ{sign}\nφα βητα', groups('αλφα', 'βητα'))


def test_more_than_twelve_query_occurrences_are_verified():
    words = [f'word{chr(97+i)}' for i in range(15)]
    assert seq.verify(' '.join(words), groups(*words))
    assert not seq.verify(' '.join(words[:-1]), groups(*words))


def corpus(rows):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("CREATE TABLE passages(id,text,normalized,author,language); CREATE TABLE tokens(passage_id,form,normalized,count); CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED,normalized,tokenize='unicode61 remove_diacritics 0');")
    for identifier, text, indexed in rows:
        con.execute('INSERT INTO passages VALUES (?,?,?,?,?)', (identifier, text, normalize(search_text(text)), 'Synthetic', 'grc'))
        con.execute('INSERT INTO passage_fts VALUES (?,?)', (identifier, normalize(search_text(text))))
        if indexed:
            for token in tokenize(search_text(text)):
                con.execute('INSERT INTO tokens VALUES (?,?,?,?)', (identifier, token, normalize(token), 1))
    return con


def test_candidate_full_scan_unindexed_and_repeated_group_check():
    rows = [(str(i), 'beta alpha', True) for i in range(405)]
    rows.extend([('late', 'alpha beta', True), ('reference', 'alpha beta', False), ('overlap', 'alpha', True)])
    con = corpus(rows)
    matches, checked = seq.find_matches(con, groups('alpha', 'beta'), '', [], 'ordered', 0)
    assert set(matches) == {'late', 'reference'}
    assert checked == 407
    assert not seq.find_matches(con, groups('alpha', 'alpha'), '', [], 'all_terms', 0)[0]
    assert not seq.find_matches(con, groups('alpha', 'beta'), ' AND p.author=?', ['Other'], 'ordered', 0)[0]


def test_candidate_and_verification_limits_reject_not_truncate(monkeypatch):
    con = corpus([('a', 'alpha beta', True), ('b', 'alpha beta', True)])
    monkeypatch.setattr(seq, 'MAX_CANDIDATES', 1)
    with pytest.raises(expansion.SequenceLimit):
        seq.find_matches(con, groups('alpha', 'beta'), '', [], 'ordered', 0)
    monkeypatch.setattr(seq, 'MAX_MATCH_OPERATIONS', 0)
    with pytest.raises(expansion.SequenceLimit):
        seq.verify('alpha beta', groups('alpha', 'beta'))


def test_non_greek_tokenless_divisions_are_not_lost_by_index_preselection():
    raw = 'αλ-\nφα βη-\nτα'
    con = corpus([('mixed', raw, False)])
    con.execute("UPDATE passages SET language='mul',normalized=?", (normalize(raw),))
    con.execute('UPDATE passage_fts SET normalized=?', (normalize(raw),))
    result, count = seq.find_matches(con, groups('αλφα', 'βητα'), '', [], 'ordered', 0)
    assert count == 1 and 'mixed' in result
    assert all(len(term['source_spans']) == 2 for term in result['mixed']['terms'])


def test_prefilter_never_drops_verified_adjacent_witness_controls():
    cases = [('α β', groups('α', 'β')), ('α,β', groups('α', 'β')),
             ('α 123 β', groups('α', 'β')), ('ἀλ-\nφα βήτα', groups('ἀλφα', 'βήτα')),
             ("alpha' beta", groups("alpha'", 'beta')), ('α᾿ β', groups('α᾿', 'β')),
             (unicodedata.normalize('NFD', 'ἄλφα βήτα'), groups('ἄλφα', 'βήτα'))]
    for raw, query in cases:
        assert seq.verify(raw, query), raw
        assert seq.adjacent_prefilter(query).search(normalize(search_text(raw))), raw


def test_exceptional_id_cache_is_version_bound_and_final_filters_still_apply(monkeypatch):
    from collections import OrderedDict
    con = corpus([('one', 'αλ-\nφα βητα', False)])
    con.execute("UPDATE passages SET language='mul'")
    version = [1]
    monkeypatch.setattr(seq, '_DIVIDED_IDS', OrderedDict())
    monkeypatch.setattr(seq, '_corpus_identity', lambda connection: ('synthetic', version[0]))
    assert seq.non_greek_divided_ids(con) == ('one',)
    con.execute('INSERT INTO passages VALUES (?,?,?,?,?)', ('two', 'αλ-\nφα βητα', '', 'Other', 'mul'))
    version[0] = 2
    assert seq.non_greek_divided_ids(con) == ('one', 'two')
    matches, _ = seq.find_matches(con, groups('αλφα', 'βητα'), ' AND p.author=?', ['Synthetic'], 'ordered', 0)
    assert set(matches) == {'one'}


def test_exceptional_id_discovery_rejects_snapshot_drift(monkeypatch):
    con = corpus([('one', 'αλ-\nφα βητα', False)])
    identities = iter([('before',), ('after',)])
    monkeypatch.setattr(seq, '_corpus_identity', lambda connection: next(identities))
    with pytest.raises(expansion.SequenceLimit, match='corpus changed'):
        seq.non_greek_divided_ids(con)


def test_file_backed_exception_cache_invalidates_on_replace_wal_and_policy(tmp_path, monkeypatch):
    import os
    from collections import OrderedDict
    from backend import publication
    monkeypatch.setattr(seq, '_DIVIDED_IDS', OrderedDict())
    path = tmp_path/'source.sqlite'
    def create(target, identifier):
        con = sqlite3.connect(target)
        con.execute('CREATE TABLE passages(id,text,language)')
        con.execute('INSERT INTO passages VALUES (?,?,?)', (identifier, 'αλ-\nφα', 'mul'))
        con.commit(); con.close()
    def connect():
        con = sqlite3.connect(path); con.row_factory = sqlite3.Row
        return con
    create(path, 'before')
    with connect() as con:
        assert seq.non_greek_divided_ids(con) == ('before',)
    con.close()
    replacement = tmp_path/'replacement.sqlite'
    create(replacement, 'after')
    os.replace(replacement, path)
    with connect() as con:
        assert seq.non_greek_divided_ids(con) == ('after',)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('INSERT INTO passages VALUES (?,?,?)', ('wal-added', 'βη-\nτα', 'mul'))
        con.commit()
        assert set(seq.non_greek_divided_ids(con)) == {'after', 'wal-added'}
        previous = seq._corpus_identity(con)
        monkeypatch.setattr(publication, 'publication_restricted', lambda: not previous[-2])
        assert seq._corpus_identity(con) != previous
    con.close()


class EmptyMorphology:
    _forms = {}
    _entries = {}
    def _load(self): pass
    def expansion_lemmas_for_form(self, form): return []
    def expansion_forms_for_lemma(self, lemma): return []


class EmptyEvidence:
    def __init__(self, path): self.path = path
    def candidate_analyses(self, form, limit): return {'candidates': []}
    def lookup(self, form, limit): return {'claims': []}
    def _connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


def test_expansion_more_than_five_hundred_forms_and_explicit_ceiling(tmp_path, monkeypatch):
    path = tmp_path/'synthetic.sqlite'
    con = sqlite3.connect(path)
    con.executescript('CREATE TABLE claims(id,normalized_form,passage_id,predicate,status,assertion_type,evidence_json); CREATE TABLE form_edges(claim_id,form); CREATE INDEX claims_form_idx ON claims(normalized_form);')
    con.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,?)', ('synthetic', 'αλφα', None, 'morphology', 'source_claim', 'extracted_annotation', '[]'))
    con.executemany('INSERT INTO form_edges VALUES (?,?)', [('synthetic', 'form'+str(i)) for i in range(601)])
    con.commit(); con.close()
    result = expansion.build_groups(['αλφα', 'βητα'], EmptyMorphology(), EmptyEvidence(path))
    assert len(result[0]['alternatives']) == 602
    assert result[0]['alternatives']['form600'][0]['claim_id'] == 'synthetic'
    monkeypatch.setattr(expansion, 'MAX_GROUP_KEYS', 500)
    with pytest.raises(expansion.SequenceLimit):
        expansion.build_groups(['αλφα', 'βητα'], EmptyMorphology(), EmptyEvidence(path))


def test_saturated_candidate_projection_cannot_claim_complete_expansion(tmp_path):
    class Saturated(EmptyEvidence):
        def candidate_analyses(self, form, limit): return {'candidates': [{}]*100}
    with pytest.raises(expansion.SequenceLimit):
        expansion.build_groups(['αλφα', 'βητα'], EmptyMorphology(), Saturated(tmp_path/'unused'))
