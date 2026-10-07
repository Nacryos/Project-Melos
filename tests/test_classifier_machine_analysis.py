"""Synthetic engine-analysis protocol tests; no source assertions or HTTP calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backend import classifier, jev_gateway


FORM = '\u03b1'
PASSAGE = {'id': 'synthetic:passage', 'text': FORM, 'language': 'grc', 'kind': 'text'}
RECEIPT = {'id': 'synthetic:receipt', 'request_form': FORM,
    'url': 'https://example.test/engine', 'http_status': 201,
    'received_utc': '2026-01-01T00:00:00Z', 'raw_sha256': 'a' * 64,
    'parser_version': 'synthetic-v1', 'engine_revision': None}
CANDIDATE = {'id': 'synthetic:machine:1', 'basis': 'machine_analysis',
    'candidate_kind': 'machine_analysis', 'receipt_id': RECEIPT['id'],
    'lemma': FORM, 'dictionary_fields': {'hdwd': {'$': FORM}, 'gend': {'$': 'dictionary-only'}},
    'inflection': {'case': {'$': 'synthetic-case'}, 'dial': {'$': 'literal unsplit label'}},
    'features': {'case': 'synthetic-case', 'dial': 'literal unsplit label'},
    'entry_pointer': '/synthetic/entry', 'inflection_pointer': '/synthetic/entry/infl/0'}


class Provider:
    model = 'synthetic-model'
    timeout = 1

    def __init__(self, choice=CANDIDATE['id']):
        self.choice = choice
        self.calls = 0

    def decide(self, packet):
        self.calls += 1
        return {'choice': self.choice, 'model': self.model}


@pytest.fixture
def trusted_adapter(monkeypatch):
    """A fake trusted store for classifier-only tests, not receipt-validation QA."""
    rows = [deepcopy(CANDIDATE)]
    calls = []

    def verify(receipt_id, candidates, form):
        calls.append((receipt_id, deepcopy(candidates), form))
        if receipt_id != RECEIPT['id'] or candidates != rows or form != FORM:
            return None
        return {'status': 'ok', 'receipt': deepcopy(RECEIPT), 'machine_candidates': deepcopy(rows)}

    monkeypatch.setitem(sys.modules, 'backend.machine_morphology',
        SimpleNamespace(validate_receipt_projection=verify))
    return rows, calls


def compare(candidates=None, **kwargs):
    return classifier.classify_context(FORM, PASSAGE,
        deepcopy([CANDIDATE] if candidates is None else candidates),
        machine_validation={'receipt': deepcopy(RECEIPT)},
        source_guard_candidates=[], **kwargs)


def test_machine_choice_has_separate_provenance_and_no_source_claim(trusted_adapter):
    provider = Provider()
    result = compare(provider=provider)
    assert provider.calls == 1 and result['status'] == 'machine_proposed'
    assert result['candidate_basis'] == 'machine'
    assert result['evidence_ids'] == []
    assert result['machine_evidence']['receipt'] == RECEIPT
    option = result['packet']['candidates'][0]
    assert option['claim_ids'] == option['source_references'] == []
    assert option['dictionary_fields'] == CANDIDATE['dictionary_fields']
    assert option['inflection'] == CANDIDATE['inflection']
    assert option['features'] == CANDIDATE['features']
    assert 'gend' not in option['features']
    assert result['packet']['claims'] == []


def test_machine_flags_or_url_never_replace_receipt_validation():
    provider = Provider()
    fake = {**CANDIDATE, 'source_url': 'https://example.test/dictionary',
            'status': 'source_claim', 'claim_ids': ['invented']}
    result = classifier.classify_context(FORM, PASSAGE, [fake], provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0
    assert 'validated raw-analysis receipt' in result['reason']


@pytest.mark.parametrize('field,value', [('lemma', 'changed'),
    ('inflection_pointer', '/wrong'), ('receipt_id', 'wrong'),
    ('claim_ids', ['invented']), ('entry_senses', [{'gloss': 'invented'}])])
def test_changed_projection_is_rejected_before_provider(trusted_adapter, field, value):
    row = {**deepcopy(CANDIDATE), field: value}
    provider = Provider()
    result = compare([row], provider=provider)
    assert provider.calls == 0 and result['decision_stage'] == 'preflight'


def test_missing_alternative_and_mixed_source_inventory_are_rejected(trusted_adapter):
    rows, _ = trusted_adapter
    rows.append({**deepcopy(CANDIDATE), 'id': 'synthetic:machine:2',
                 'inflection_pointer': '/synthetic/entry/infl/1'})
    provider = Provider()
    assert compare(provider=provider)['decision_stage'] == 'preflight'
    mixed = [*rows, {'id': 'source', 'source_url': 'https://example.test/source'}]
    assert compare(mixed, provider=provider)['decision_stage'] == 'preflight'
    assert provider.calls == 0


def test_source_guard_inventory_is_required_and_incomplete_projection_blocks(trusted_adapter):
    provider = Provider()
    result = classifier.classify_context(FORM, PASSAGE, [CANDIDATE],
        machine_validation={'receipt': RECEIPT}, provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0
    guard = {'id': 'source', 'candidate_kind': 'grammatical_analysis',
        'source_projection_status': 'incomplete_explicit_alternatives',
        'source_grammar_alternatives': [{'quote': 'Synthetic A or B'}]}
    result = classifier.classify_context(FORM, PASSAGE, [CANDIDATE],
        machine_validation={'receipt': RECEIPT}, source_guard_candidates=[guard], provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0
    assert result['packet']['incomplete_source_projections'][0]['id'] == 'source'


def test_all_alternatives_preserved_and_bounds_not_silently_truncated(trusted_adapter):
    rows, _ = trusted_adapter
    rows[:] = [{**deepcopy(CANDIDATE), 'id': f'synthetic:{i}',
        'inflection_pointer': f'/synthetic/entry/infl/{i}'} for i in range(33)]
    provider = Provider()
    result = compare(rows, provider=provider)
    assert len(result['packet']['candidates']) == 33
    assert provider.calls == 0 and result['decision_stage'] == 'preflight'


def test_machine_packet_size_guard_retains_raw_payload_without_paid_fallback(trusted_adapter):
    rows, _ = trusted_adapter
    rows[0]['inflection']['synthetic_large_note'] = 'x' * 33000
    provider = Provider()
    result = compare(rows, provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0
    assert 'exceeds 32000' in result['reason']
    assert result['packet']['candidates'][0]['inflection'] == rows[0]['inflection']


def test_machine_options_do_not_bypass_incomplete_source_senses_or_rewrite_editorial_text(trusted_adapter):
    provider = Provider()
    guard = {'id': 'source', 'candidate_kind': 'grammatical_analysis',
             'entry_sense_claim_ids': ['missing:source-sense'], 'claim_ids': ['missing:grammar']}
    passage = {**PASSAGE, 'text': '\u2020' + FORM + '\u2020 [...]', 'quality': 'source_text'}
    result = classifier.classify_context(FORM, passage, [CANDIDATE],
        machine_validation={'receipt': RECEIPT}, source_guard_candidates=[guard], provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0
    assert result['packet']['incomplete_entry_sense_evidence'][0]['candidate_id'] == 'source'
    assert result['packet']['passage']['text'] == passage['text']


def test_machine_abstain_and_invalid_choice_remain_nonproposals(trusted_adapter):
    for choice in ('abstain', 'invented'):
        result = compare(provider=Provider(choice))
        assert result['status'] == 'abstained'
        assert result['candidate_id'] is None and result['evidence_ids'] == []


def test_machine_schema_participates_in_cache_without_invalidating_source_namespace(tmp_path, trusted_adapter):
    packet = compare(provider=Provider())['packet']
    provider = Provider()
    cached = jev_gateway.CachedJevProvider(provider,
        hashlib.sha256(b'synthetic-visitor').hexdigest(), state_path=tmp_path/'cache.sqlite')
    assert jev_gateway.CACHE_VERSION == 'jev-contextual-parse-v7-contextual-hypothesis'
    assert cached.decide(packet)['cache_hit'] is False
    assert cached.decide(packet)['cache_hit'] is True
    changed = deepcopy(packet)
    changed['machine_packet_schema'] = 'synthetic-next-schema'
    assert cached.decide(changed)['cache_hit'] is False
    assert provider.calls == 2


@pytest.fixture
def raw_service(tmp_path, monkeypatch):
    from backend import machine_morphology
    raw = json.dumps({'RDF': {'Annotation': {
        'hasTarget': {'Description': {'about': 'urn:word:' + FORM}},
        'hasBody': {'resource': 'urn:synthetic:analysis'},
        'Body': {'about': 'urn:synthetic:analysis', 'rest': {'entry': {'dict': {'hdwd': {'$': FORM},
            'gend': {'$': 'dictionary-only'}}, 'infl': [
                {'term': {'stem': {'$': FORM}}, 'pofs': {'$': 'synthetic-POS'},
                 'case': {'$': 'synthetic-A'}, 'dial': {'$': 'literal unsplit'}},
                {'term': {'stem': {'$': FORM}}, 'pofs': {'$': 'synthetic-POS'},
                 'case': {'$': 'synthetic-B'}}]}}}}}}, ensure_ascii=False).encode()
    service = machine_morphology.MachineMorphologyService(tmp_path/'raw.sqlite',
        transport=lambda url: (201, raw, {}))
    result = service.analyze(FORM, hashlib.sha256(b'synthetic-visitor').hexdigest())
    assert result['status'] == 'ok' and len(result['machine_candidates']) == 2
    monkeypatch.setattr(machine_morphology, 'get_service', lambda: service)
    return service, result


def test_actual_receipt_reparse_preserves_both_options_and_rejects_forgery(raw_service):
    service, validation = raw_service
    candidates = validation['machine_candidates']
    provider = Provider(candidates[1]['id'])
    result = classifier.classify_context(FORM, PASSAGE, candidates,
        machine_validation=validation, source_guard_candidates=[], provider=provider)
    assert result['status'] == 'machine_proposed' and provider.calls == 1
    assert len(result['packet']['candidates']) == 2
    assert result['machine_evidence']['inflection_pointer'] == candidates[1]['inflection_pointer']
    # Only receipt.id is a lookup handle. Submitted receipt metadata is never
    # trusted, even when the caller tries to mark it as source-bearing proof.
    altered_validation = deepcopy(validation)
    altered_validation['receipt']['raw_sha256'] = 'f' * 64
    altered_validation['receipt']['engine_revision'] = 'fabricated'
    result = classifier.classify_context(FORM, PASSAGE, candidates,
        machine_validation=altered_validation, source_guard_candidates=[], provider=provider)
    assert result['machine_evidence']['receipt']['raw_sha256'] == validation['receipt']['raw_sha256']
    assert result['machine_evidence']['receipt']['engine_revision'] is None
    for changed in ([candidates[0]], [{**candidates[0], 'features': {'case': 'invented'}}, candidates[1]]):
        before = provider.calls
        failed = classifier.classify_context(FORM, PASSAGE, changed,
            machine_validation=validation, source_guard_candidates=[], provider=provider)
        assert failed['decision_stage'] == 'preflight' and provider.calls == before
    before = provider.calls
    failed = classifier.classify_context('\u03b2', {**PASSAGE, 'text': '\u03b2'}, candidates,
        machine_validation=validation, source_guard_candidates=[], provider=provider)
    assert failed['decision_stage'] == 'preflight' and provider.calls == before


def test_corrupted_raw_receipt_is_rejected_before_classifier_cache(raw_service):
    service, validation = raw_service
    # Deliberately simulate disk corruption after disabling the protective
    # immutable trigger in this isolated synthetic database only.
    with service._connect() as connection:
        connection.execute('DROP TRIGGER receipt_no_update')
        connection.execute('UPDATE receipts SET raw=? WHERE id=?',
            (b'{}', validation['receipt']['id']))
    provider = Provider()
    result = classifier.classify_context(FORM, PASSAGE, validation['machine_candidates'],
        machine_validation=validation, source_guard_candidates=[], provider=provider)
    assert result['decision_stage'] == 'preflight' and provider.calls == 0


def test_machine_criteria_use_raw_machine_proof_without_dictionary_sense_claim(raw_service, monkeypatch):
    import io
    _, validation = raw_service
    packet = classifier.build_evidence_packet(FORM, PASSAGE, validation['machine_candidates'],
        machine_validation=validation, source_guard_candidates=[])
    captured = []

    def capture(request, timeout):
        captured.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'model': 'synthetic-model', 'answers': {
            'contextual_parse': {'type': 'choice', 'choice': 'abstain'}}}).encode())

    monkeypatch.setattr(classifier, 'urlopen', capture)
    classifier.JevProvider(api_key='synthetic-unused', model='synthetic-model').decide(packet)
    assert len(captured) == 1
    criteria = captured[0]['questions']['contextual_parse']['criteria']
    assert set(criteria) == {row['id'] for row in validation['machine_candidates']} | {'abstain'}
    for row in validation['machine_candidates']:
        assert criteria[row['id']]['inflection'] == row['inflection']
        assert criteria[row['id']]['dictionary_fields'] == row['dictionary_fields']
        assert 'machine analysis, not source-attested parsing' in criteria[row['id']]['evidence']
    assert packet['claims'] == []


def test_audited_elision_packet_preserves_trusted_transport_provenance(tmp_path, monkeypatch):
    from backend import machine_morphology
    fixtures = Path(__file__).parent / 'fixtures/machine_morphology/elision'
    sample = json.loads((fixtures / 'manifest.json').read_bytes())['samples'][0]
    raw = (fixtures / sample['raw_file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sample['receipt']['raw_sha256']
    service = machine_morphology.MachineMorphologyService(tmp_path / 'elision.sqlite',
        transport=lambda _: (201, raw, {}))
    validation = service.analyze(sample['text'], 'a' * 64)
    assert validation['status'] == 'ok'
    monkeypatch.setattr(machine_morphology, 'get_service', lambda: service)
    supplied = deepcopy(validation)
    fields = ('source_form', 'input_form', 'input_transformation', 'input_convention')
    for field in fields:
        supplied['receipt'][field] = 'SYNTHETIC forged client metadata'
    packet = classifier.build_evidence_packet(sample['text'],
        {'id': sample['passage_id'], 'text': sample['text'], 'language': 'grc'},
        validation['machine_candidates'], machine_validation=supplied, source_guard_candidates=[])
    for field in fields:
        assert packet['machine_receipt'][field] == validation['receipt'][field]
    assert packet['machine_receipt']['source_form'] == sample['text']
    assert packet['machine_receipt']['request_form'] == sample['receipt']['request_form']
    assert packet['machine_receipt']['source_form'] != packet['machine_receipt']['request_form']
    assert packet['claims'] == []
    assert len(packet['candidates']) == sample['candidate_count']
