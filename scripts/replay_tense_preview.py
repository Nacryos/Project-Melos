"""Capture a minimal real local source response for preview regression tests.

No network/model calls, Greek rewriting or definition authoring. The existing
audited API source pipeline reads archived lexica and morphology evidence.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.server import word


def main():
    response = word('ἦλθες', '')
    fields = ('id', 'entry_id', 'lemma', 'source', 'source_url', 'entry_url',
              'rendered_entry_text', 'rendering_method', 'dictionary_senses',
              'dictionary_senses_status', 'dictionary_senses_method')
    candidate_fields = ('id', 'lemma', 'lemma_raw', 'homograph_id', 'lemma_identity', 'features', 'source_tags',
                        'analysis', 'analysis_format', 'analysis_text', 'matched_form', 'matched_form_variants',
                        'match_kind', 'edit_distance', 'gloss_entry_id', 'lexicon_entry_ids', 'source', 'source_url',
                        'source_consistent', 'assertion_type', 'candidate_kind', 'basis', 'status', 'quality',
                        'link_status', 'lemma_link_status')
    fixture = {'form': response['form'], 'candidates': [{key: candidate[key] for key in candidate_fields if key in candidate}
                                                      for candidate in response['candidates']]}
    fixture['lexicon_entries'] = [{key: entry[key] for key in fields if key in entry}
                                  for entry in response['lexicon_entries']]
    output = ROOT / 'tests/fixtures/word-elthes-tense-preview.json'
    raw = json.dumps(fixture, ensure_ascii=False, indent=2).encode('utf-8')
    output.write_bytes(raw)
    print(json.dumps({'path': str(output), 'bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest(), 'model_calls': 0}))


if __name__ == '__main__':
    main()
