"""Extract a small source-only evaluation dossier from accepted local records.

Selectors are record identities and lookup keys, not authored literary data or
gold answers. No candidates are removed and no model or provider is called.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.evidence import EvidenceIndex
from backend.lexicon_render import read_entry, _render_node
from backend.morphology import normalize, tokenize
from backend.textutils import search_text


# Observed accepted identifiers; Greek form values are extracted from passages.
SELECTORS = (
    ('ibycus-287-adjective', 'p2_cgl_anthology:355', '\u03b1\u03c0\u03b5\u03b9\u03c1\u03b1',
     ('p2_cgl_anthology:355:tr1', 'p2_cgl_anthology:355:tr2', 'p2_cgl_anthology:355:tr3'), None),
    ('ibycus-287-eye-control', 'p2_cgl_anthology:355', '\u03bf\u03bc\u03bc\u03b1\u03c3\u03b9',
     ('p2_cgl_anthology:355:tr1', 'p2_cgl_anthology:355:tr2', 'p2_cgl_anthology:355:tr3'), None),
    ('medea-672-adjective', 'perseus:tlg0006.tlg003.perseus-grc2:617\u2013672:1',
     '\u03b1\u03c0\u03b5\u03b9\u03c1\u03bf\u03c3', ('perseus:tlg0006.tlg003.perseus-eng2:667\u2013686:1',), '672'),
)
ENTRY_IDS = {'lsj:1:n11760', 'lsj:1:n11761', 'lsj:16:n73517'}
WIKTIONARY_RECORDS = ('wiktionary:kaikki:line:7806', 'wiktionary:kaikki:line:7807',
                      'wiktionary:kaikki:line:7808', 'wiktionary:kaikki:line:10214')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(output_root, root=ROOT):
    root, output_root = Path(root).resolve(), Path(output_root).resolve()
    staging = (root / 'data/staging').resolve()
    if not output_root.is_relative_to(staging) or output_root == staging or output_root.exists():
        raise ValueError('Output must be a fresh child directory below data/staging')
    corpus, evidence = root / 'data/corpus.sqlite', root / 'data/evidence.sqlite'
    entries_path = root / 'data/lexica/entries.jsonl'
    bindings = {}

    def bind(path):
        path = Path(path).resolve()
        key = str(path.relative_to(root)).replace('\\', '/')
        actual = {'sha256': sha(path), 'bytes': path.stat().st_size}
        if key in bindings:
            assert bindings[key] == actual, f'Input changed: {key}'
        bindings[key] = actual
        return actual['sha256']

    for path in (corpus, evidence, entries_path, Path(__file__), root / 'backend/textutils.py',
                 root / 'backend/morphology.py', root / 'backend/lexicon_render.py',
                 root / 'backend/evidence.py'):
        bind(path)
    con = sqlite3.connect(corpus.as_uri() + '?mode=ro', uri=True)
    source_records = {}

    def record(identifier):
        if identifier not in source_records:
            row = con.execute('SELECT data FROM passages WHERE id=?', (identifier,)).fetchone()
            assert row, f'Accepted record absent: {identifier}'
            item = json.loads(row[0])
            assert item['quality'] == 'source_text'
            assert bind(root / item['raw_path']) == item['raw_sha256']
            source_records[identifier] = {'record': item,
                'indexed_record_sha256': hashlib.sha256(row[0].encode('utf8')).hexdigest(),
                'text_sha256': hashlib.sha256(item['text'].encode('utf8')).hexdigest()}
        return source_records[identifier]

    def focus(item, label):
        source = root / item['raw_path']
        tree = etree.parse(str(source), etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))
        nodes = tree.xpath('//*[local-name()="l" and @n=$label]', label=label)
        assert len(nodes) == 1, 'Ambiguous source line locator'
        text = ' '.join(''.join(nodes[0].itertext()).split())
        accepted = [line for line in item['lines'] if str(line.get('label')) == label]
        assert len(accepted) == 1 and ' '.join(accepted[0]['text'].split()) == text
        return {'source_url': item['source_url'], 'raw_sha256': item['raw_sha256'],
                'locator': f'//l[@n="{label}"]', 'line': accepted[0],
                'scope': 'Source-labeled line evidence; not automatic whole-passage translation alignment.'}

    cases = []
    for identifier, passage_id, key, translation_ids, label in SELECTORS:
        passage = record(passage_id)['record']
        tokens = [token for token in tokenize(search_text(passage['text'])) if normalize(token) == key]
        assert len(tokens) == 1, f'No unique lookup occurrence: {identifier}'
        form = tokens[0]
        translations = []
        for translation_id in translation_ids:
            translation = record(translation_id)['record']
            translations.append({'record_id': translation_id,
                                 'source_focus': focus(translation, label) if label else None})
            if label is None:
                assert translation['parent_id'] == passage_id
                assert translation['metadata']['translation_of'] == passage_id
                assert translation['metadata']['source_translation_locator']
                assert translation['raw_sha256'] == passage['raw_sha256']
        cases.append({'id': identifier, 'form': form, 'passage_id': passage_id,
                      'lookup_only_line_join': form not in passage['text'],
                      'lookup_occurrences': len(tokens), 'translation_support': translations,
                      'source_focus': focus(passage, label) if label else None})
    con.close()
    lexical_entries = []
    for line in entries_path.read_bytes().splitlines():
        item = json.loads(line)
        if item['id'] not in ENTRY_IDS:
            continue
        assert bind(root / item['raw_path']) == item['raw_sha256']
        node, entities = read_entry(item['raw_path'], item['entry_id'])
        lexical_entries.append({'record': item, 'record_line_sha256': hashlib.sha256(line).hexdigest(),
                                'source_rendered_entry': _render_node(node, entities),
                                'locator': f'entryFree[@id="{item["entry_id"]}"]'})
    assert {item['record']['id'] for item in lexical_entries} == ENTRY_IDS
    ev = sqlite3.connect(evidence.as_uri() + '?mode=ro', uri=True)
    service = EvidenceIndex(evidence)
    sense_claims = []
    for source_id in WIKTIONARY_RECORDS:
        for row in ev.execute("SELECT id FROM claims WHERE id GLOB ? AND predicate='sense_gloss' ORDER BY id", (source_id + ':sense:*',)):
            claim = service.get_claim(row[0])
            for item in claim['evidence']:
                assert item['record_id'] == source_id
                assert bind(root / item['raw_path']) == item['raw_sha256']
            sense_claims.append(claim)
    ev.close()
    assert {item['evidence'][0]['record_id'] for item in sense_claims} == set(WIKTIONARY_RECORDS)
    wiki_path = root / 'data/lexica/wiktionary-entries.jsonl'
    wiki_records = {}
    for line in wiki_path.read_bytes().splitlines():
        item = json.loads(line)
        if item['id'] in WIKTIONARY_RECORDS:
            wiki_records[item['id']] = (item, hashlib.sha256(line).hexdigest())
    assert set(wiki_records) == set(WIKTIONARY_RECORDS)
    for claim in sense_claims:
        for item in claim['evidence']:
            parent, parent_sha = wiki_records[item['record_id']]
            assert parent_sha == item['parent_sha256']
            value = parent
            for component in item['locator'].strip('/').split('/'):
                value = value[int(component)] if isinstance(value, list) else value[component]
            assert value == json.loads(item['quote']), 'Accepted quotation no longer matches source pointer'
    wiki_proofs = []
    for raw_path in {item['raw_path'] for item, _ in wiki_records.values()}:
        wanted = {item['raw_line']: item for item, _ in wiki_records.values() if item['raw_path'] == raw_path}
        expected = {item['raw_sha256'] for item in wanted.values()}
        assert len(expected) == 1 and bind(root / raw_path) in expected
        with (root / raw_path).open('rb') as source:
            for number, line in enumerate(source, 1):
                if number not in wanted:
                    continue
                item = wanted.pop(number)
                # ingest_wiktionary pins the original binary line including newline.
                assert hashlib.sha256(line).hexdigest() == item['raw_line_sha256']
                assert json.loads(line) == item['entry']
                wiki_proofs.append({key: item[key] for key in
                                    ('id', 'raw_path', 'raw_sha256', 'raw_line', 'raw_line_sha256', 'quality')})
                if not wanted:
                    break
        assert not wanted, 'Original source snapshot line missing'
    for relative, item in list(bindings.items()):
        assert sha(root / relative) == item['sha256'], f'Input changed: {relative}'
    result = {'schema_version': 1, 'artifact_type': 'qa19_homograph_source_evidence',
              'purpose': 'Source evidence only. No model predictions, candidate filtering, or authored gold answers.',
              'paid_calls': 0, 'active_data_changed': False, 'input_files': bindings,
              'cases': cases, 'source_records': source_records, 'lexical_entries': lexical_entries,
              'accepted_sense_claims': sense_claims, 'wiktionary_original_line_proofs': wiki_proofs,
              'limitations': ['Same-page CGL translations are whole-fragment support, not token alignments.',
                             'Medea Greek and English chunks differ in extent; only the explicitly source-labeled focus line is compared.',
                             'Dictionary senses are entry-scoped, not passage-specific attestations.',
                             'Independent candidate-specific family and morphology rubrics must bind the final packet separately.']}
    output_root.mkdir(parents=True)
    target = output_root / 'source-fixtures.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return {'output': str(target), 'sha256': sha(target), 'cases': len(cases), 'sense_claims': len(sense_claims)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output_root)))


if __name__ == '__main__':
    main()
