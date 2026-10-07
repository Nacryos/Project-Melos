"""Synthetic fixtures test protocol mechanics, never supply experiment data."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import jev_perseus_blind12 as harness


def pool():
    return [{'id': f'p-{i}', 'passage_id': 'p', 'target_nfc': str(i),
             'greek_letters': 5, 'corpus_exact_nfc_count': i // 4,
             'word_index_zero_based': i + 50} for i in range(32)]


def test_sampling_repeatable_and_low_quartile():
    rows = pool()
    eligible, selected, reserves, threshold = harness.choose(rows)
    assert threshold == 1
    assert len(eligible) == 8 and len(selected) == 4
    assert harness.choose(rows)[1] == selected
    assert {r['id'] for r in selected}.isdisjoint(r['id'] for r in reserves)
    assert all(r['corpus_exact_nfc_count'] <= threshold for r in selected)


def test_sampling_includes_all_cutoff_ties_and_excludes_opening():
    rows = pool()
    rows.append({**rows[0], 'id': 'duplicate', 'word_index_zero_based': 90})
    rows.append({**rows[0], 'id': 'opening', 'word_index_zero_based': 1})
    eligible, _, _, _ = harness.choose(rows)
    assert 'duplicate' in {r['id'] for r in eligible}
    assert 'opening' not in {r['id'] for r in eligible}


def test_no_silent_sampling_relaxation():
    with pytest.raises(ValueError, match='Fewer than four'):
        harness.choose(pool()[:3])


def test_blinding_removes_source_scores_and_source_ids():
    rows = [{'id': 'p1', 'lemma': 'fixture one', 'morphology': 'fixture', 'gloss': None,
             'perseus_percent': 100, 'user_votes': 9, 'source_row_index': 0},
            {'id': 'p2', 'lemma': 'fixture two', 'morphology': 'fixture', 'gloss': None,
             'perseus_percent': 0, 'user_votes': 0, 'source_row_index': 1}]
    clean, mapping = harness.clean_options('test', rows)
    assert len(mapping) == 2 and set(mapping.values()) == {'p1', 'p2'}
    assert all(set(x) == {'id', 'lemma', 'morphology', 'gloss'} for x in clean)
    assert all(x['id'].startswith('o_') for x in clean)
    assert harness.clean_options('test', rows) == (clean, mapping)


def test_tie_bounds_do_not_invent_unique_winner():
    assert harness.bounds({'a', 'b'}, {'b'}) == {
        'all_top_ties_accepted': False, 'any_top_tie_accepted': True,
        'top_ids': ['a', 'b']}
    assert not harness.bounds(set(), {'b'})['all_top_ties_accepted']


def test_exact_frequency_keeps_case_and_diacritics(tmp_path):
    database = tmp_path / 'corpus.sqlite'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE tokens(form TEXT, normalized TEXT, count INTEGER)')
        conn.execute('CREATE TABLE metadata(key TEXT, value TEXT)')
        for word, count in [('άλφα', 3), ('α\u0301λφα', 2), ('ΑΛΦΑ', 7)]:
            conn.execute('INSERT INTO tokens VALUES (?,?,?)', (word, harness.normalize(word), count))
    before = database.read_bytes()
    exact, folded, _ = harness.frequency_counts(database, [{'target': 'άλφα', 'target_nfc': 'άλφα'}])
    assert exact == {'άλφα': 5}
    assert folded == {'αλφα': 12}
    assert database.read_bytes() == before


def test_immutable_artifact_rejects_changes(tmp_path):
    path = tmp_path / 'frozen.json'
    harness.save(path, {'a': 1}, immutable=True)
    harness.save(path, {'a': 1}, immutable=True)
    with pytest.raises(ValueError):
        harness.save(path, {'a': 2}, immutable=True)


def test_failed_download_receipted_without_retry(tmp_path, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise harness.requests.Timeout('fixture timeout')
    monkeypatch.setattr(harness.requests, 'get', fail)
    with pytest.raises(harness.requests.Timeout):
        harness.fetch(tmp_path, 'test', 'https://www.perseus.tufts.edu/hopper/text?doc=fixture')
    receipts = list((tmp_path / 'raw').glob('*.meta.json'))
    assert len(calls) == 1 and len(receipts) == 1
    assert harness.read(receipts[0])['error_type'] == 'Timeout'


def test_cached_dom_capture_is_not_claimed_wire_bytes(tmp_path):
    source = tmp_path / 'capture.html'
    source.write_bytes(b'<html>synthetic fixture</html>')
    _, receipt = harness.fetch(tmp_path, 'test', 'https://www.perseus.tufts.edu/hopper/text?doc=fixture',
        cache_file=source, captured_at='2026-10-05T00:00:00Z', capture_type='browser_dom')
    assert receipt['preserved_response_body'] is False
    assert receipt['sha256'] == harness.sha(source.read_bytes())


def test_source_url_restriction():
    with pytest.raises(ValueError):
        harness.validate_source_url('https://example.com/hopper/morph?l=x', 'morph')
    with pytest.raises(ValueError):
        harness.validate_source_url('https://www.perseus.tufts.edu/hopper/text?doc=x', 'morph')


def test_occurrence_provenance_reads_source_onclick():
    soup = BeautifulSoup('''<script>addDocument('fixture-doc')</script>
        <div class="text_container"><div class="text">
        <a href="morph?l=fixture" onclick="m(this,42,0)">fixture</a>
        </div></div>''', 'html.parser')
    row, = harness.source_occurrences(soup, 'https://example.test', 'p')
    assert row['source_doc'] == 'fixture-doc' and row['word_occurrence_i'] == 42
    assert row['source_link_query'] == {'l': ['fixture']}


def test_run_rejects_unapproved_plan_before_reading_credentials(tmp_path):
    harness.save(tmp_path / 'frozen_plan.json', {'requests': []})
    with pytest.raises(ValueError, match='approval hash'):
        harness.run(argparse.Namespace(out=tmp_path, approved_plan_sha256='wrong', env_file=tmp_path / 'absent'))


def test_prepare_twelve_cases_yields_48_calls_and_blind_packets(tmp_path, monkeypatch):
    selected = [{'id': f'test-{i}', 'passage_id': 'test', 'target': 'synthetic',
                 'word_index_zero_based': i} for i in range(12)]
    monkeypatch.setattr(harness, 'frozen', lambda out: ({'selected': selected}, 'fixture-sha'))
    passage = {'greek': {'text': 'synthetic Greek context', 'citation_uri': 'fixture:1',
                          'title': 'synthetic title'},
               'translation': {'text': 'synthetic English context', 'context_scope': '1',
                               'edition_alignment_status': 'synthetic pairing'},
               'occurrences': [{'target': 'synthetic'} for _ in range(12)]}
    harness.save(tmp_path / 'passages/test.json', passage)
    for target in selected:
        harness.save(tmp_path / 'morphology' / (target['id'] + '.json'), {
            'status': 'success', 'candidates': [
                {'id': 'p1', 'lemma': 'synthetic one', 'morphology': 'fixture', 'gloss': None,
                 'perseus_percent': 100, 'user_votes': 9},
                {'id': 'p2', 'lemma': 'synthetic two', 'morphology': 'fixture', 'gloss': None,
                 'perseus_percent': 0, 'user_votes': 0}]})
    harness.prepare(argparse.Namespace(out=tmp_path))
    plan = harness.read(tmp_path / 'frozen_plan.json')
    assert len(plan['requests']) == 48
    packet_raw = (tmp_path / 'blind_judge_packet.json').read_text(encoding='utf-8')
    assert 'perseus_percent' not in packet_raw and 'user_votes' not in packet_raw
    forward, reverse = plan['requests'][:2]
    assert forward['request']['state']['candidates'] == list(reversed(reverse['request']['state']['candidates']))
    assert forward['candidate_mapping'] == reverse['candidate_mapping']
    assert 'translation' not in forward['request']['state']
    assert 'translation' in plan['requests'][2]['request']['state']


def test_cached_json_fragment_is_mechanically_decoded_and_pinned(tmp_path):
    path = tmp_path / 'capture.json'
    url = 'https://www.perseus.tufts.edu/hopper/morph?l=fixture'
    timestamp = '2026-10-05T00:00:00Z'
    harness.save(path, {'url': url, 'captured_at': timestamp, 'html': '<div>άλφα</div>'})
    soup, receipt = harness.fetch(tmp_path, 'test', url, cache_file=path,
                                  captured_at=timestamp, capture_type='browser_dom_fragment')
    assert soup.get_text() == 'άλφα'
    assert receipt['cached_json_sha256'] == harness.sha(path.read_bytes())
    assert receipt['capture_type'] == 'browser_dom_fragment'
    assert receipt['preserved_response_body'] is False
    with pytest.raises(ValueError, match='URL/timestamp'):
        harness.fetch(tmp_path, 'bad', url + 'wrong', cache_file=path,
                      captured_at=timestamp, capture_type='browser_dom_fragment')


def test_morphology_artifact_pinning_detects_edits(tmp_path):
    path = tmp_path / 'morphology/test.json'
    harness.save(path, {'status': 'synthetic'})
    plan = {'model': harness.MODEL, 'endpoint': harness.ENDPOINT,
            'coverage': [{'id': 'test', 'morphology_sha256': harness.sha(path.read_bytes())}]}
    harness.verify_plan_sources(tmp_path, plan)
    harness.save(path, {'status': 'changed'})
    with pytest.raises(ValueError, match='Morphology artifact'):
        harness.verify_plan_sources(tmp_path, plan)
