"""Synthetic entry-sense plumbing; never provider calls or corpus assertions."""

from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from backend import classifier, jev_gateway, server
from backend.candidate_senses import project_entry_senses
from backend.evidence import EvidenceIndex
from scripts.build_evidence import build
from test_candidate_senses import fixtures
from test_evidence import _stage
from test_jev_gateway import Provider, wrapper


PASSAGE = {'id': 'synthetic-passage', 'text': '\u03b2', 'language': 'grc', 'kind': 'text'}


def attached(number=1, gloss='SYNTHETIC definition'):
    candidate, morphology, sense = fixtures(number, gloss)
    candidate['entry_senses'] = project_entry_senses(candidate, morphology, [sense])
    candidate['entry_sense_claim_ids'] = [sense['id']]
    return candidate, morphology, sense


def resolve(packet, candidate):
    return candidate.get('entry_senses') or [packet['entry_sense_catalog'][sid]
                                            for sid in candidate.get('entry_sense_claim_ids', [])]


def test_evidence_index_associates_only_direct_entry_senses(tmp_path):
    rows = []
    for number in (1, 2):
        _, morphology, sense = fixtures(number, f'SYNTHETIC meaning {number}')
        entry = f'wiktionary:kaikki:line:{number}'
        headword = {**deepcopy(morphology), 'id': entry + ':lemma:entry', 'predicate': 'lemma',
                    'object': {'lemma': '\u03b1', 'pos': 'adj', 'head_templates': []}}
        rows.extend([morphology, sense, headword])
    _stage(tmp_path, rows)
    db = tmp_path / 'data/evidence.sqlite'
    build(tmp_path, db)
    projected = EvidenceIndex(db).candidate_analyses('\u03b2')
    assert len(projected['candidates']) == 2
    assert len(projected['supporting_claims']) == 2
    for c in projected['candidates']:
        entry = c['claim_ids'][0].removesuffix(':morphology:entry')
        assert c['entry_senses'][0]['entry_id'] == entry
        assert c['entry_sense_claim_ids'] == [entry + ':sense:0']
        assert len(c['claim_ids']) == 1  # grammatical identity remains unchanged


def test_catalog_shares_proof_not_homograph_identity_or_grammar_choices():
    candidates, claims = [], []
    for number in (1, 2):
        c, morphology, sense = attached(number, f'SYNTHETIC meaning {number}')
        claims.extend([morphology, sense])
        for ordinal in range(3):
            morphology['object']['forms'].append(deepcopy(morphology['object']['forms'][0]))
            copy = deepcopy(c)
            copy['id'] = morphology['id'] + f'#form:{ordinal}'
            candidates.append(copy)
    packet = classifier.build_evidence_packet('\u03b2', PASSAGE, candidates, claims)
    assert len(packet['candidates']) == 6
    assert len(packet['entry_sense_catalog']) == 2
    for c in packet['candidates']:
        senses = resolve(packet, c)
        assert len(senses) == 1
        assert senses[0]['entry_id'] == c['claim_ids'][0].removesuffix(':morphology:entry')
        assert senses[0]['raw_glosses'][0].startswith('(SYNTHETIC qualifier)')
    assert not packet.get('incomplete_entry_sense_evidence')
    requests = []
    def intercept(request, **kwargs):
        requests.append(json.loads(request.data))
        raise RuntimeError('OFFLINE capture; HTTP was not sent')
    with patch.object(classifier, 'urlopen', intercept):
        with pytest.raises(RuntimeError):
            classifier.JevProvider(api_key='synthetic-offline', model='synthetic-model').decide(packet)
    wire = requests[0]
    assert wire['state']['entry_sense_catalog'] == packet['entry_sense_catalog']
    for c in packet['candidates']:
        assert wire['questions']['contextual_parse']['criteria'][c['id']]['entry_sense_claim_ids'] == c['entry_sense_claim_ids']


@pytest.mark.parametrize('failure', ['missing', 'wrong-entry', 'wrong-parent', 'needs-review'])
def test_missing_or_wrong_sense_proof_prevents_any_provider_call(failure):
    c, morphology, sense = attached()
    claims = [morphology, sense]
    if failure == 'missing':
        claims.pop()
    elif failure == 'wrong-entry':
        sense['metadata']['source_record_id'] = 'wiktionary:kaikki:line:2'
    elif failure == 'wrong-parent':
        sense['evidence'][0]['parent_sha256'] = 'f' * 64
    else:
        sense['status'] = 'needs_review'
    provider = Provider()
    result = classifier.classify_context('\u03b2', PASSAGE, [c], claims, provider=provider)
    assert result['decision_stage'] == 'preflight'
    assert 'sense evidence is incomplete' in result['reason']
    assert provider.calls == 0


def test_untrusted_display_sense_is_rebuilt_from_accepted_proof():
    c, morphology, sense = attached()
    c['entry_senses'][0]['glosses'] = ['UNSOURCED injected gloss']
    packet = classifier.build_evidence_packet('\u03b2', PASSAGE, [c], [morphology, sense])
    assert resolve(packet, packet['candidates'][0])[0]['glosses'] == sense['object']['glosses']
    assert 'UNSOURCED' not in json.dumps(packet)


def test_api_carries_sense_support_without_promoting_it_to_grammar():
    c, morphology, sense = attached()
    data = {'context': PASSAGE, 'contextual_candidates': [c],
            'structured_evidence': {'claims': [morphology]},
            'contextual_supporting_claims': [sense], 'author_profile': {}}
    provider = Provider()
    with patch.object(server, 'word', return_value=data), \
            patch.object(jev_gateway, 'public_enabled', return_value=False), \
            patch.object(classifier, 'configured_provider', return_value=provider):
        result = server.classify_context_request(server.ContextRequest(form='\u03b2', passage_id=PASSAGE['id']), None)
    assert provider.calls == 1
    assert result['status'] == 'proposed'
    assert result['packet']['candidates'][0]['claim_ids'] == [morphology['id']]
    assert sense['id'] in result['evidence_ids']
    assert sense['id'] in {claim['id'] for claim in result['packet']['claims']}


def test_sense_payload_and_version_are_cache_bound(tmp_path, monkeypatch):
    c, morphology, sense = attached()
    provider = Provider()
    cache = wrapper(tmp_path, provider)
    old_c = {k: v for k, v in c.items() if not k.startswith('entry_sense')}
    old_packet = classifier.build_evidence_packet('\u03b2', PASSAGE, [old_c], [morphology])
    new_packet = classifier.build_evidence_packet('\u03b2', PASSAGE, [c], [morphology, sense])
    assert cache.decide(old_packet)['cache_hit'] is False
    assert cache.decide(new_packet)['cache_hit'] is False
    assert cache.decide(new_packet)['cache_hit'] is True
    monkeypatch.setattr(jev_gateway, 'CACHE_VERSION', 'synthetic-other-version')
    assert cache.decide(new_packet)['cache_hit'] is False
    assert provider.calls == 3


def test_oversized_evidence_is_not_truncated_to_allow_comparison():
    c, morphology, sense = attached(gloss='SYNTHETIC oversized ' * 5000)
    provider = Provider()
    result = classifier.classify_context('\u03b2', PASSAGE, [c], [morphology, sense], provider=provider)
    assert result['decision_stage'] == 'preflight'
    assert 'exceeds' in result['reason']
    assert provider.calls == 0
    assert resolve(result['packet'], result['packet']['candidates'][0])[0]['glosses'] == sense['object']['glosses']
