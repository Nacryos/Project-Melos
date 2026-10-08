"""Read-only check of a source-restricted meaning through actual HTTP APIs.

Uses the archived, audited word response as the expectation. Does not fetch
uncached morphology, invoke a classifier, or author lexical data.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_alcaeus_occurrences import Receipts, save, sha


def verify_dictionary(actual, expected):
    expected_entry = next(e for e in expected['lexicon_entries']
                          if any(s.get('morphology_restrictions') for s in e.get('dictionary_senses', [])))
    entry = next(e for e in actual['lexicon_entries'] if e['id'] == expected_entry['id'])
    # Compare full source-derived inventories, not merely the desired English.
    assert entry['dictionary_senses'] == expected_entry['dictionary_senses']
    restricted = [s for s in entry['dictionary_senses'] if s.get('morphology_restrictions')]
    assert len(restricted) == 2
    assert all(s['extraction_method'] == 'tei-definition-spans-v4' for s in restricted)
    return entry, {s['id'] for s in restricted}


def verify_interlinear(result, form, entry, restricted):
    assert result['selection']['text'] == form
    assert result['limits']['machine_fetches'] == 0
    assert result['ranking']['status'] == 'not_requested'
    assert result['sense_ranking']['status'] == 'not_requested'
    words = [t for t in result['interlinear']['readings'][0]['tokens'] if t['kind'] == 'word']
    assert len(words) == 1
    token = words[0]
    assert token['text'] == form
    expected_ids = {s['id'] for s in entry['dictionary_senses']}
    matched = []
    for candidate in token.get('candidate_meanings', []):
        gloss = candidate.get('gloss') or {}
        alternatives = gloss.get('alternatives') or []
        ids = {s['id'] for s in alternatives}
        if expected_ids <= ids and candidate.get('features', {}).get('Tense') == 'Aor':
            assert gloss.get('sense_id') in expected_ids - restricted
            assert restricted <= ids  # The full source entry is not deleted.
            matched.append(candidate['candidate_id'])
    assert matched, 'No actual aorist candidate with complete source inventory verified'
    return {'candidate_ids': matched, 'parse_short': token.get('parse_short'),
            'gloss': token.get('gloss'), 'complete_source_senses': len(expected_ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, required=True,
                        help='Exact staged dictionary-preview.js to test against the actual response')
    args = parser.parse_args()
    fixture = ROOT / 'tests/fixtures/word-elthes-tense-preview.json'
    expected = json.loads(fixture.read_text(encoding='utf-8'))
    source = ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl'
    record = next(json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()
                  if json.loads(line)['id'] == 'campbell-glp:alcaeus:350')
    form = expected['form']
    start = record['text'].index(form)
    receipts = Receipts(args.origin, args.output / 'receipts', timeout=180)
    word, word_receipt = receipts.call('/api/word', params={'form': form, 'passage_id': record['id']})
    entry, restricted = verify_dictionary(word, expected)
    result, analysis_receipt = receipts.call('/api/analyze-passage', payload={
        'version': 1, 'passage_id': record['id'], 'start': start, 'end': start + len(form),
        'offset_unit': 'codepoint', 'selected_text': form, 'rerank': False, 'fetch_machine': False})
    interlinear = verify_interlinear(result, form, entry, restricted)
    body_path = args.output / 'receipts' / Path(word_receipt).with_suffix('.body')
    # Replay the exact production frontend artifact, not the mutable working tree.
    program = """const fs=require('fs'),vm=require('vm');
const context=vm.createContext({window:{},URL});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const p=context.window.MelosDictionaryPreview.buildPreview(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
process.stdout.write(JSON.stringify({compact:p.compact.entries,all:p.entries}));"""
    frontend = json.loads(subprocess.check_output(['node', '-e', program, str(args.frontend), str(body_path)], text=True, encoding='utf-8'))
    compact = next(e for e in frontend['compact'] if e['id'] == entry['id'])
    assert all(m['sense_id'] not in restricted for m in compact['meanings'])
    expanded = next(e for e in frontend['all'] if e['id'] == entry['id'])
    assert {m['sense_id'] for m in expanded['meanings']} == {s['id'] for s in entry['dictionary_senses']}
    report = {'verdict': 'PASS', 'origin': args.origin, 'scope': 'Exact source tense restriction and display, not contextual accuracy certification',
              'source_sha256': sha(source.read_bytes()), 'fixture_sha256': sha(fixture.read_bytes()),
              'frontend_sha256': sha(args.frontend.read_bytes()), 'receipts': [word_receipt, analysis_receipt],
              'form': form, 'interlinear': interlinear, 'compact_meanings': compact['meanings'],
              'restricted_sense_ids': sorted(restricted)}
    save(args.output / 'report.json', report)
    print(json.dumps({'verdict': report['verdict'], 'form': form,
                      'compact_meanings': [m['text'] for m in compact['meanings']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
