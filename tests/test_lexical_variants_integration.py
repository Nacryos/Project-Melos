"""Source-backed integration checks; no new dictionary data is authored."""
from copy import deepcopy
from types import SimpleNamespace

from backend.evidence import EvidenceIndex
from backend.lexical_variants import lookup_variants
from backend.passage_analysis import PassageAnalysisService


def test_word_endpoint_keeps_lexical_semantics_out_of_morphological_candidates(monkeypatch):
    from backend import server
    index = EvidenceIndex()
    monkeypatch.setattr(server, 'morph_service', lambda: SimpleNamespace(analyze=lambda *a, **k: {'candidates': [], 'warnings': []}))
    monkeypatch.setattr(server, 'occurrences', lambda *a, **k: [])
    monkeypatch.setattr(server, 'evidence_service', lambda: index)
    monkeypatch.setattr(server, 'evidence_lookup', lambda *a, **k: {'ready': True, 'claims': []})
    result = server.word('τάλαις')
    assert result['lexical_variant_status'] == 'available'
    assert result['candidates'] == []
    assert result['contextual_candidates'] == []
    variant = result['lexical_variants'][0]
    assert variant['lemma'] == 'τάλας'
    assert variant['entry_senses'][0]['glosses'] == ['miserable']
    assert variant['features'] is None


def test_word_endpoint_unavailable_variant_index_preserves_source_results(monkeypatch):
    from backend import server
    monkeypatch.setattr(server, 'morph_service', lambda: SimpleNamespace(analyze=lambda *a, **k: {'candidates': [{'id': 'synthetic-plumbing-control'}], 'warnings': []}))
    monkeypatch.setattr(server, 'occurrences', lambda *a, **k: [])
    monkeypatch.setattr(server, 'evidence_service', lambda: SimpleNamespace(candidate_analyses=lambda *a, **k: {'candidates': [], 'supporting_claims': []}))
    monkeypatch.setattr(server, 'evidence_lookup', lambda *a, **k: {'ready': False, 'claims': []})
    result = server.word('τάλαις')
    assert result['lexical_variant_status'] == 'unavailable'
    assert result['candidates'] == [{'id': 'synthetic-plumbing-control'}]


def test_passage_variant_proof_stays_general_not_occurrence_parse():
    index = EvidenceIndex()
    lexical = lookup_variants('ὄππᾳ', index)
    source = {'candidates': [], 'contextual_candidates': [],
              'lexical_variants': lexical['lexical_variants'],
              'dictionary_crossreferences': lexical['dictionary_crossreferences'],
              'lexical_variant_supporting_claims': lexical['supporting_claims'],
              'lexical_variant_status': 'available'}
    original = deepcopy(source)
    passage = {'id': 'synthetic:plumbing-only', 'text': 'ὄππᾳ', 'kind': 'text', 'language': 'grc'}
    service = PassageAnalysisService(passage_lookup=lambda identifier: passage,
                                     word_lookup=lambda *args: source)
    result = service.analyze({'passage_id': passage['id'], 'selected_text': passage['text'],
                              'start': 0, 'end': len(passage['text']), 'offset_unit': 'codepoint'})
    token = next(token for token in result['tokens'] if token['kind'] == 'word')
    assert token['lexical_variants'][0]['lemma'] == 'ὅπῃ'
    assert token['source_candidates'] == token['contextual_candidates'] == []
    assert all(value['scope'] == 'general_source_record' for value in token['claim_applications'].values())
    assert source == original
