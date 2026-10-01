"""Synthetic presentation fixtures only; these are not corpus/source claims."""
from copy import deepcopy
from itertools import permutations
from types import SimpleNamespace

import pytest

from backend.occurrence_preview import group_preview


def row(identifier, **changes):
    return dict(id=identifier, author='Sappho', work='Synthetic work',
                citation='189', language='grc', kind='text', quality='source_text',
                text='Synthetic exact text', edition=identifier,
                source_url=f'https://example.test/{identifier}', **changes)


def changed(identifier, **changes):
    result = row(identifier)
    result.update(changes)
    return result


def mirror(identifier='mirror', **changes):
    result = changed(identifier, author='sappho', work='Synthetic mirror label',
                     metadata={'ogc_extra': {'provenance': {'url': 'https://example.test/direct'}}})
    result.update(changes)
    return result


def memberships(groups):
    return {frozenset(member['id'] for member in group['members']) for group in groups}


def test_exact_source_copies_and_one_hop_mirror_preserve_all_records_order_invariant():
    rows = [row('direct'), row('other'), mirror()]
    before = deepcopy(rows)
    for order in permutations(rows):
        groups = group_preview(order)
        assert memberships(groups) == {frozenset(['direct', 'other', 'mirror'])}
        assert groups[0]['member_count'] == 3
        proof = next(p for p in groups[0]['grouping_proofs'] if p['record_id'] == 'mirror')
        assert proof['source_record_ids'] == ['direct']
        assert proof['method'] == 'explicit_one_hop_upstream_work'
    assert rows == before


@pytest.mark.parametrize('changes', [
    {'citation': '188'}, {'citation': ''}, {'text': 'Synthetic exact text!'},
    {'text': 'Synthetic exact'}, {'text': 'synthetic exact text'},
    {'text': 'Synthetic [exact] text'}, {'text': 'Synthetic exáct text'},
    {'quality': 'machine_ocr'}, {'kind': 'commentary'}, {'language': 'eng'},
    {'author': 'Alcaeus'}, {'author': 'Sappho / Alcaeus'}, {'work': 'Other work'},
    {'work': ''}, {'quality': ''}, {'id': ''},
])
def test_different_loci_variants_extents_or_scope_never_collapse(changes):
    assert len(group_preview([row('first'), changed('second', **changes)])) == 2


def test_only_nfc_whitespace_and_work_case_are_ignored():
    rows = [changed('first', text='exáct\n text'),
            changed('second', text='exa\u0301ct  text', work='SYNTHETIC WORK')]
    assert len(group_preview(rows)) == 1


def test_unknown_author_not_grouped_even_with_identical_labels():
    assert len(group_preview([changed('a', author='Unverified author'),
                              changed('b', author='Unverified author')])) == 2


@pytest.mark.parametrize('changes', [
    {'metadata': {'source_section': 'Column ii'}},
    {'metadata': {'cited_edition_token': 'Synthetic edition numbering'}},
    {'metadata': {'numbering_scheme': 'Synthetic numbering'}},
    {'lines': [{'label': '5', 'text': 'Synthetic exact text'}]},
    {'lines': [{'section': 'Column ii', 'text': 'Synthetic exact text'}]},
])
def test_declared_extent_or_numbering_scope_is_not_merged_with_unspecified(changes):
    assert len(group_preview([row('first'), changed('second', **changes)])) == 2


def test_different_columns_and_line_extents_remain_distinct():
    rows = [changed('a', metadata={'source_section': 'Column i'}),
            changed('b', metadata={'source_section': 'Column ii'})]
    assert len(group_preview(rows)) == 2
    rows = [changed('a', lines=[{'label': '5', 'text': 'Synthetic exact text'}]),
            changed('b', lines=[{'label': '6', 'text': 'Synthetic exact text'}])]
    assert len(group_preview(rows)) == 2


def test_blank_line_labels_and_no_line_metadata_do_not_imply_different_extents():
    assert len(group_preview([row('first'), changed('second', lines=[{
        'label': '', 'text': 'Synthetic exact text'}])])) == 1


def test_conflicting_direct_targets_do_not_bridge_work_groups_in_any_order():
    rows = [row('direct'), changed('other', work='Other work', source_url='https://example.test/direct'),
            mirror(work='Synthetic work')]
    for order in permutations(rows):
        assert memberships(group_preview(order)) == {frozenset([r['id']]) for r in rows}


def test_original_mirror_work_cannot_bridge_to_unrelated_same_label_record():
    rows = [row('direct'), mirror(), changed('unrelated', work='Synthetic mirror label')]
    assert memberships(group_preview(rows)) == {frozenset(['direct', 'mirror']), frozenset(['unrelated'])}


def test_no_recursive_provenance_or_url_guessing():
    intermediary = mirror('middle', source_url='https://example.test/middle')
    last = mirror('last', work='Third label', metadata={'ogc_extra': {
        'provenance': {'url': 'https://example.test/middle'}}})
    groups = group_preview([row('direct'), intermediary, last])
    assert memberships(groups) == {frozenset(['direct', 'middle']), frozenset(['last'])}
    assert len(group_preview([row('direct'), mirror(metadata={})])) == 2


def test_api_retains_raw_occurrences_and_adds_preview_only(monkeypatch):
    from backend import server
    rows = [row('direct'), row('other'), mirror()]
    original = deepcopy(rows)
    monkeypatch.setattr(server, 'occurrences', lambda *args, **kwargs: rows)
    monkeypatch.setattr(server, 'morph_service', lambda: SimpleNamespace(analyze=lambda *a, **k: {
        'candidates': [], 'warnings': []}))
    monkeypatch.setattr(server, 'evidence_lookup', lambda *a, **k: {'ready': True, 'claims': []})
    monkeypatch.setattr(server, 'evidence_service', lambda: SimpleNamespace(candidate_analyses=lambda *a, **k: {
        'candidates': [], 'supporting_claims': [], 'method': 'synthetic'}))
    result = server.word('synthetic')
    assert result['occurrences'] == original
    assert len(result['occurrence_preview_groups']) == 1
    assert result['occurrence_preview_groups'][0]['members'] == original
