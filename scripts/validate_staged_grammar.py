"""Offline integration validation of independently audited staged grammar claims.

Only an isolated fresh staging root is written. The provider is an explicit
counting abstention stub: its calls prove control flow, never model accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.classifier import build_evidence_packet, classify_context
from backend.evidence import EvidenceIndex
from scripts.build_evidence import build


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OfflineAbstainer:
    """No network, cache, API key or paid provider is accessed."""
    def __init__(self):
        self.calls = 0

    def decide(self, packet):
        self.calls += 1
        return {'model': 'offline-control-flow-stub-not-a-model', 'choice': 'abstain'}


def inspect_source(index, changed_claims, passage):
    subject = changed_claims[0]['subject']
    assert all(row['subject'] == subject for row in changed_claims)
    form, passage_id = subject['form'], subject['passage_id']
    full = index.candidate_analyses(form, passage_id, limit=200)
    claims = index.lookup(form, passage_id=passage_id, limit=None)['claims']
    changed_ids = {row['id'] for row in changed_claims}
    by_id = {row['id']: row for row in full['candidates']}
    assert changed_ids <= by_id.keys(), 'Changed source projection disappeared from candidate inventory'
    for source in changed_claims:
        candidate = by_id[source['id']]
        assert candidate['features'] == source['object']['features'], 'Unprinted feature inheritance'
        assert candidate['analysis'] == source['object']['raw_label']
        assert candidate['source_grammar_alternatives'], 'Source alternatives lost'
        for proof in candidate['source_grammar_alternatives']:
            evidence = next(item for item in source['evidence'] if item['record_id'] == proof['record_id'])
            quote = evidence['quote']
            assert quote[proof['quote_start']:proof['quote_end']] == proof['source_text']
            for branch in proof['branches']:
                assert quote[branch['start']:branch['end']] == branch['raw_label']
    direct = all(row['object'].get('source_grammar_scope') == 'direct_headword_parenthesis'
                 for row in changed_claims)
    if direct:
        assert {by_id[i]['source_projection_status'] for i in changed_ids} == {'explicit_alternatives_represented'}
    else:
        assert len(changed_claims) == 1, 'Prose scope was promoted into alternative whole-token parses'
        assert 'source_grammar_branch' not in changed_claims[0]['object']
        assert by_id[next(iter(changed_ids))]['source_projection_status'] == 'incomplete_explicit_alternatives'
    checks = []
    for limit in range(1, len(full['candidates']) + 1):
        projected = index.candidate_analyses(form, passage_id, limit=limit)
        packet = build_evidence_packet(form, passage, projected['candidates'], claims)
        source_ids = {row['id'] for row in projected['candidates']} & changed_ids
        assert source_ids, 'A non-grammatical prefix hid every changed source candidate'
        complete = direct and source_ids == changed_ids
        flagged = bool(packet.get('incomplete_source_projections'))
        assert flagged != complete, 'Incomplete source inventory unexpectedly passed preflight qualification'
        provider = OfflineAbstainer()
        decision = classify_context(form, passage, projected['candidates'], claims, provider=provider)
        if complete:
            assert provider.calls == 1 and decision['decision_stage'] == 'model_abstained'
        else:
            assert provider.calls == 0 and decision['decision_stage'] == 'preflight'
            assert 'does not preserve all' in decision['reason']
        checks.append({'limit': limit, 'candidate_ids': [row['id'] for row in projected['candidates']],
                       'changed_source_ids_returned': sorted(source_ids),
                       'complete_source_inventory': complete, 'stub_calls': provider.calls,
                       'decision_stage': decision['decision_stage'], 'reason': decision['reason']})
    packet = build_evidence_packet(form, passage, full['candidates'], claims)
    packet_claims = {row['id']: row for row in packet['claims']}
    assert changed_ids <= packet_claims.keys()
    for source in changed_claims:
        projected = packet_claims[source['id']]
        assert projected['object'] == source['object']
        assert projected['subject'] == source['subject']
        assert projected['evidence'] == [
            {key: item[key] for key in ('record_id', 'source_url', 'quote', 'locator')
             if item.get(key) is not None} for item in source['evidence']]
    return {'source_record_id': changed_claims[0]['evidence'][0]['record_id'],
            'changed_claim_ids': sorted(changed_ids), 'subject': subject,
            'source_evidence': changed_claims[0]['evidence'], 'direct_headword_scope': direct,
            'prefix_checks': checks, 'packet': packet}


def validate(claims_path, extraction_report, acceptance_path, output_root, root=ROOT):
    root, output_root = Path(root).resolve(), Path(output_root).resolve()
    claims_path, extraction_report, acceptance_path = map(Path, (claims_path, extraction_report, acceptance_path))
    allowed = (root / 'data/staging').resolve()
    if not output_root.is_relative_to(allowed) or output_root == allowed or output_root.exists():
        raise ValueError('Output must be a fresh child of data/staging')
    report = json.loads(extraction_report.read_text(encoding='utf8'))
    acceptance = json.loads(acceptance_path.read_text(encoding='utf8'))
    assert acceptance['scope'] == 'isolated validation only; not active admission'
    assert acceptance['active_admission'] is False and acceptance['model_calls_authorized'] is False
    assert acceptance['source_report_sha256'] == digest(extraction_report)
    assert acceptance['source_grammar_sha256'] == digest(root / 'backend/source_grammar.py')
    expected = acceptance['files'][claims_path.name]
    assert expected['verdict'] == 'PASS' and expected['sha256'] == digest(claims_path)
    assert report['staged_only'] and report['output_sha256'] == expected['sha256']
    for relative, sha in report['input_bindings'].items():
        assert digest(root / relative) == sha, f'Source/extractor binding changed: {relative}'
    staged = [json.loads(line) for line in claims_path.read_bytes().splitlines()]
    assert len(staged) == expected['records'] == report['count']
    changed_ids = set(report['claim_changes']['added'])
    assert not report['claim_changes']['same_id_changed']
    changed = [row for row in staged if row['id'] in changed_ids]
    assert {row['id'] for row in changed} == changed_ids
    source_path = root / report['input']
    source_lines = {json.loads(line)['id']: (line, json.loads(line)) for line in source_path.read_bytes().splitlines()}
    groups = {}
    for row in changed:
        for evidence in row['evidence']:
            raw, record = source_lines[evidence['record_id']]
            assert hashlib.sha256(raw).hexdigest() == evidence['parent_sha256']
            assert evidence['quote'] in record['text']
            assert record['source_url'] == evidence['source_url']
            assert digest(root / evidence['raw_path']) == evidence['raw_sha256']
        groups.setdefault(row['evidence'][0]['record_id'], []).append(row)
    bound_paths = [claims_path, extraction_report, acceptance_path, source_path,
                   root / 'data/claims/p2_notes.jsonl', root / 'data/evidence.sqlite',
                   root / 'backend/source_grammar.py', root / 'backend/evidence.py',
                   root / 'backend/classifier.py', root / 'scripts/build_evidence.py', Path(__file__)]
    before = {str(path): digest(path) for path in bound_paths}
    isolated_claims = output_root / 'data/claims' / claims_path.name
    isolated_claims.parent.mkdir(parents=True)
    shutil.copyfile(claims_path, isolated_claims)
    isolated_manifest = output_root / 'validation-source-acceptance.json'
    shutil.copyfile(acceptance_path, isolated_manifest)
    db = output_root / 'evidence.sqlite'
    built = build(output_root, db, isolated_manifest)
    index = EvidenceIndex(db)
    cases = []
    for source_id, rows in sorted(groups.items()):
        passage = source_lines[rows[0]['subject']['passage_id']][1]
        for row in rows:
            subject = row['subject']
            assert passage['text'][subject['start']:subject['end']] == subject['form']
        cases.append(inspect_source(index, rows, passage))
    for path, sha in before.items():
        assert digest(path) == sha, f'Input/code/active state changed during validation: {path}'
    result = {'purpose': 'Isolated source-derived candidate inventory and preflight validation, not model evaluation or active admission.',
              'paid_calls': 0, 'source_bindings': before, 'isolated_build': built, 'cases': cases,
              'limitations': ['Only the corrected p2_notes source file is indexed here; this is not a full-corpus mixture test.',
                              'A counting abstention stub establishes reachability only; no ranking or accuracy claim follows.']}
    target = output_root / 'integration-report.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return {'report': str(target), 'sha256': digest(target), 'cases': len(cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claims', type=Path, required=True)
    parser.add_argument('--extraction-report', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.claims, args.extraction_report, args.acceptance, args.output_root)))


if __name__ == '__main__':
    main()
