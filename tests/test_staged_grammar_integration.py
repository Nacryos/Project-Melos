"""Synthetic isolated plumbing tests; no fixture is literary corpus data."""
import hashlib
import json

import pytest

from backend.evidence import EvidenceIndex
from scripts.build_evidence import build
from scripts.extract_p2_notes import first_grammar, grammar_objects
from scripts.validate_staged_grammar import inspect_source, validate


def isolated(tmp_path, body):
    quote = 'SYNTHETIC ' + body
    objects = grammar_objects(first_grammar(body), quote, body, len('SYNTHETIC '))
    rows = [{'id': f'synthetic:{i}', 'subject': {'type': 'form', 'form': '\u03b1',
                'passage_id': 'synthetic:passage', 'start': 0, 'end': 1},
             'predicate': 'morphology', 'object': obj,
             'evidence': [{'record_id': 'synthetic:source', 'source_url': 'https://example.test/synthetic',
                           'raw_path': 'synthetic-only', 'raw_sha256': 'a' * 64, 'quote': quote}],
             'status': 'source_claim', 'assertion_type': 'extracted_annotation',
             'method': 'synthetic-test', 'source_family': 'Synthetic test fixture'}
            for i, obj in enumerate(objects)]
    directory = tmp_path / 'data/claims'
    directory.mkdir(parents=True)
    source = directory / 'synthetic.jsonl'
    source.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf8')
    manifest = tmp_path / 'synthetic-acceptance.json'
    manifest.write_text(json.dumps({'files': {'synthetic.jsonl': {'verdict': 'PASS',
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'records': len(rows)}}}), encoding='utf8')
    db = tmp_path / 'synthetic-evidence.sqlite'
    build(tmp_path, db, manifest)
    return EvidenceIndex(db), rows, {'id': 'synthetic:passage', 'text': '\u03b1', 'kind': 'text', 'language': 'grc'}


@pytest.mark.parametrize('body', [
    '(aor. act. inf. or 2nd sg. aor. mid. imper. from SOURCE)',
    '(pres. act. partic. fem. acc. sg. or gen. pl. from SOURCE)',
])
def test_real_index_packet_and_preflight_require_complete_direct_inventory(tmp_path, body):
    index, rows, passage = isolated(tmp_path, body)
    result = inspect_source(index, rows, passage)
    assert result['direct_headword_scope']
    assert [case['stub_calls'] for case in result['prefix_checks']] == [0, 1]
    assert [case['complete_source_inventory'] for case in result['prefix_checks']] == [False, True]


def test_prose_substring_discussion_is_not_promoted_to_new_alternative(tmp_path):
    index, rows, passage = isolated(tmp_path,
        'Another substring could be acc. sg. fem. or gen. pl. of SOURCE')
    result = inspect_source(index, rows, passage)
    assert not result['direct_headword_scope']
    assert len(result['packet']['candidates']) == 1
    assert result['prefix_checks'][0]['stub_calls'] == 0


def test_validator_rejects_existing_or_nonstaging_output_before_reading_inputs(tmp_path):
    with pytest.raises(ValueError, match='fresh child'):
        validate('missing', 'missing', 'missing', tmp_path, root=tmp_path)
