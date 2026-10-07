"""Read-only source-linked inventory check against a running backend.

Queries only exact occurrences in the approved source artifact. No generated
Greek, English, model calls, source fetches or asserted contextual accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.linked_dictionary import lookup_linked_dictionary
from backend.sense_ranker import sense_packet
from scripts.audit_alcaeus_occurrences import Receipts, save
from scripts.evaluate_context_windows import reading, verify


def check_inventory(word_response, analysis, expected):
    assert word_response.get('linked_dictionary_status') == 'available'
    assert word_response.get('linked_dictionary') == expected, 'Word inventory differs from validated local sources'
    tokens = [row for row in analysis['tokens'] if row.get('kind') == 'word']
    assert len(tokens) == 1
    assert tokens[0].get('linked_dictionary') == expected, 'Phrase token lost or altered linked candidates'
    displayed = reading(analysis)
    required = {row['candidate_id'] for row in expected['candidates']}
    available = {row['candidate_id'] for row in displayed.get('candidate_meanings', [])}
    assert required <= available, 'Sourced alternatives were lost before meaning selection'
    return displayed


def packet_source_ids(packet):
    identifiers = [row['id'] for row in packet['candidates']]
    assert len(set(identifiers)) == len(identifiers), 'Duplicate packet choices'
    mapping = packet.get('source_choice_ids')
    if mapping is None:
        return set(identifiers)
    assert set(mapping) == set(identifiers), 'Incomplete short-ID mapping'
    assert len(set(mapping.values())) == len(mapping), 'Source choices were merged'
    return set(mapping.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--passage-id', required=True)
    parser.add_argument('--form', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in (ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf8').splitlines()]
    record = next(row for row in records if row['id'] == args.passage_id)
    assert record['text'].count(args.form) == 1 and not any(c.isspace() for c in args.form)
    start = record['text'].index(args.form)
    request = {'version': 1, 'passage_id': record['id'], 'start': start,
               'end': start + len(args.form), 'offset_unit': 'codepoint',
               'selected_text': args.form, 'rerank': False, 'fetch_machine': False}
    expected = lookup_linked_dictionary(args.form)
    assert expected['candidates'], 'No source-linked candidates in local approved source inventory'
    receipts = Receipts(args.origin, args.output / 'receipts', timeout=180)
    word, word_receipt = receipts.call('/api/word', params={'form': args.form, 'passage_id': record['id']})
    analysis, analysis_receipt = receipts.call('/api/analyze-passage', payload=request)
    verify(analysis, request, record, require_commentary=True)
    displayed = check_inventory(word, analysis, expected)
    packet = sense_packet(record, analysis, displayed)  # Offline preflight; never invokes Jev.
    required_senses = {sense['id'] for row in expected['candidates'] for sense in row['senses']}
    available_senses = packet_source_ids(packet)
    assert required_senses <= available_senses, 'Linked meanings were lost before the model packet'
    report = {'form': args.form, 'passage_id': record['id'], 'paid_calls': 0,
              'word_receipt': word_receipt, 'analysis_receipt': analysis_receipt,
              'source_candidate_paths': len(expected['candidates']),
              'linked_senses': len(required_senses), 'packet_senses': len(packet['candidates']),
              'packet_characters': len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))),
              'parse': displayed.get('parse_short'), 'selection_basis': displayed.get('selection_basis'),
              'scope': 'Source candidate coverage and packet transport; not contextual accuracy.'}
    save(args.output / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
