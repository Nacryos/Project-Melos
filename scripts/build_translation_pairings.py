"""Extract bounded passage-pair proofs from already downloaded Perseus TEI/CTS.

Read-only corpus, no downloads or corpus writes. The cached-fetch source is the
pinned archive acquired by ingest_perseus.py; each accepted record is reparsed
and checked against that archive AND its retained raw file. No similarity,
model output, manual pair list, or inferred line-number concordance is used.
Run as ``python -B -m scripts.build_translation_pairings --output <staging>``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from scripts.ingest_perseus import CTS, TEI, citation, direct_text, passages, text_of

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_hash(text: str) -> str:
    return sha(text.encode('utf-8'))


def file_hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def unlineated_reading_text(body: ET.Element) -> bool:
    """Reject substantive body text omitted by the collector's line-only branch.

    Explicit headings, speakers/stage directions and scholarly notes are not
    verse readings. Everything else outside a line must be whitespace only.
    Both element.text and child.tail are checked at their actual DOM scope.
    """
    excluded = {'l', 'note', 'bibl', 'head', 'label', 'speaker', 'stage'}
    def visit(node: ET.Element) -> bool:
        if node.tag.removeprefix(TEI) in excluded:
            return False
        if (node.text or '').strip():
            return True
        return any(visit(child) or (child.tail or '').strip() for child in node)
    return bool(visit(body))


def source_slice(record: dict, sequence: list[tuple[str, str]]) -> dict | None:
    """Locate the exact retained line sequence, including its source successor."""
    wanted = [(line['label'], line['text']) for line in record.get('lines', [])]
    if not wanted:
        return None
    positions = [i for i in range(len(sequence) - len(wanted) + 1)
                 if sequence[i:i + len(wanted)] == wanted]
    if len(positions) != 1:
        return None
    start = positions[0]
    end = start + len(wanted)
    return {'start_index': start, 'end_index_exclusive': end,
            'next_anchor': sequence[end][0] if end < len(sequence) else None,
            'at_source_end': end == len(sequence)}


def boundary_proof(parent: dict, translation: dict, ps: dict, ts: dict) -> dict | None:
    """Prove whole bodies or bounded identical anchors, never word alignment."""
    if ps.get('unlineated_reading_text', True) or ts.get('unlineated_reading_text', True):
        return None
    pspan = source_slice(parent, ps['sequence'])
    tspan = source_slice(translation, ts['sequence'])
    if not pspan or not tspan:
        return None
    common = {'parent_span': pspan, 'translation_span': tspan}
    if (ps['reading_record_count'] == ts['reading_record_count'] == 1
            and pspan['start_index'] == tspan['start_index'] == 0
            and pspan['at_source_end'] and tspan['at_source_end']):
        return {'method': 'complete_source_bodies', **common}
    plabels = [line['label'] for line in parent['lines']]
    tlabels = [line['label'] for line in translation['lines']]
    if (plabels == tlabels and len(set(plabels)) == len(plabels)
            and pspan['next_anchor'] == tspan['next_anchor']
            and pspan['at_source_end'] == tspan['at_source_end']):
        return {'method': 'identical_ordered_source_anchors_and_successor',
                'anchors': plabels, **common}
    return None


class CachedSources:
    def __init__(self, root: Path, archive: Path, commit: str):
        if not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise ValueError('Invalid pinned commit')
        self.root, self.archive, self.commit = root, zipfile.ZipFile(archive), commit
        self.prefix = f'canonical-greekLit-{commit}/'
        self.cache: dict[str, dict] = {}
        self.cts_cache: dict[str, tuple[bytes, ET.Element]] = {}

    def load(self, record: dict) -> dict:
        urn = record.get('metadata', {}).get('cts_urn', '')
        if not re.fullmatch(r'tlg\d+\.tlg\d+\.perseus-(?:grc|eng)\d+', urn):
            raise ValueError(f"Unsupported CTS version: {record['id']}")
        author, work, _ = urn.split('.')
        rel = f'data/{author}/{work}/{urn}.xml'
        raw_path = f'data/raw/perseus/{author}/{work}/{urn}.xml'
        expected_url = BASE + self.commit + '/' + rel
        if (record.get('metadata', {}).get('commit') != self.commit
                or record.get('source_url') != expected_url
                or record.get('raw_path') != raw_path):
            raise ValueError(f"Source identity mismatch: {record['id']}")
        if urn not in self.cache:
            payload = self.archive.read(self.prefix + rel)
            if (self.root / raw_path).read_bytes() != payload:
                raise ValueError(f'Archive / retained raw disagreement: {raw_path}')
            root = ET.fromstring(payload)
            body = root.find(f'.//{TEI}text/{TEI}body')
            if body is None:
                raise ValueError(f'No TEI body: {raw_path}')
            parents = {child: node for node in body.iter() for child in node}
            sequence = [(citation(node, parents), direct_text(node))
                        for node in body.iter(TEI + 'l') if direct_text(node)]
            parsed = passages(root, record['language'])
            credits = [text_of(node) for node in root.findall(f'.//{TEI}titleStmt/{TEI}editor')
                       if node.get('role') == 'translator' and text_of(node)]
            self.cache[urn] = {'sha256': sha(payload), 'sequence': sequence,
                               'unlineated_reading_text': unlineated_reading_text(body),
                               'parsed': parsed, 'translators': list(dict.fromkeys(credits)),
                               'reading_record_count': sum(x[3] in {'text', 'translation'} for x in parsed)}
        source = self.cache[urn]
        if record.get('raw_sha256') != source['sha256']:
            raise ValueError(f"Raw hash mismatch: {record['id']}")
        exact = [p for p in source['parsed'] if p[0] == record['citation']
                 and p[1] == record['text'] and p[2] == record.get('lines')
                 and p[3] == record['kind']]
        if len(exact) != 1:
            raise ValueError(f"Stored record does not uniquely reparse: {record['id']}")
        return source

    def cts_proof(self, parent: dict, translation: dict) -> dict | None:
        pu, tu = (r['metadata']['cts_urn'] for r in (parent, translation))
        work = '.'.join(pu.split('.')[:2])
        if work != '.'.join(tu.split('.')[:2]):
            return None
        rel = 'data/' + work.replace('.', '/') + '/__cts__.xml'
        if work not in self.cts_cache:
            payload = self.archive.read(self.prefix + rel)
            self.cts_cache[work] = (payload, ET.fromstring(payload))
        payload, root = self.cts_cache[work]
        versions = [(node.get('urn'), node.tag.removeprefix(CTS)) for node in root]
        prefix = 'urn:cts:greekLit:'
        if (root.get('urn') != prefix + work
                or versions.count((prefix + pu, 'edition')) != 1
                or versions.count((prefix + tu, 'translation')) != 1):
            return None
        return {'work_urn': prefix + work, 'source_url': BASE + self.commit + '/' + rel,
                'sha256': sha(payload), 'edition_urn': prefix + pu,
                'translation_urn': prefix + tu}


def record_proof(record: dict) -> dict:
    return {'text_sha256': text_hash(record['text']), 'raw_sha256': record['raw_sha256'],
            'source_url': record['source_url'], 'cts_urn': record['metadata']['cts_urn'],
            'commit': record['metadata']['commit'],
            'citation': record['citation'], 'edition': record['edition'],
            'language': record['language'], 'kind': record['kind'], 'quality': record['quality']}


def build(records: list[dict], sources: CachedSources) -> tuple[list[dict], list[dict]]:
    by_id = {record['id']: record for record in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate corpus IDs')
    reading_counts = Counter(r.get('raw_path') for r in records if r.get('kind') in {'text', 'translation'})
    pairs, excluded = [], []
    for translation in sorted(records, key=lambda r: r['id']):
        if translation.get('source') != 'perseus' or translation.get('kind') != 'translation':
            continue
        parent = by_id.get(translation.get('parent_id'))
        reason = ''
        if not parent:
            reason = 'no_explicit_present_parent'
        elif (parent.get('source') != 'perseus' or parent.get('kind') != 'text'
              or parent.get('language') != 'grc' or translation.get('language') != 'eng'):
            reason = 'unsupported_source_or_role'
        elif parent.get('quality') != 'source_text' or translation.get('quality') != 'source_text':
            reason = 'quality_not_clean'
        elif not parent.get('lines') or not translation.get('lines'):
            reason = 'no_source_line_arrays'
        if reason:
            excluded.append({'translation_id': translation['id'], 'reason': reason})
            continue
        same_labels = [l['label'] for l in parent['lines']] == [l['label'] for l in translation['lines']]
        whole_candidate = reading_counts[parent['raw_path']] == reading_counts[translation['raw_path']] == 1
        if not same_labels and not whole_candidate:
            excluded.append({'translation_id': translation['id'], 'reason': 'no_exact_source_boundary_candidate'})
            continue
        ps, ts = sources.load(parent), sources.load(translation)
        cts = sources.cts_proof(parent, translation)
        proof = boundary_proof(parent, translation, ps, ts) if cts else None
        if not proof:
            excluded.append({'translation_id': translation['id'],
                             'reason': 'no_exact_source_boundary_proof' if cts else 'no_cts_version_pair'})
            continue
        pairs.append({'parent_id': parent['id'], 'translation_id': translation['id'],
                      'work_urn': cts['work_urn'], 'parent': record_proof(parent),
                      'translation': {**record_proof(translation), 'translators': ts['translators']},
                      'boundary_proof': proof, 'cts_proof': cts})
    return pairs, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/corpus.sqlite')
    parser.add_argument('--output', type=Path, required=True, help='Fresh staging directory only')
    args = parser.parse_args()
    stage = args.output.resolve()
    if not stage.is_relative_to((ROOT / 'data/staging').resolve()) or stage.exists():
        raise ValueError('Output must be a NEW directory under data/staging')
    commit = json.loads((ROOT / 'data/raw/perseus/commit.json').read_text(encoding='utf-8'))['sha']
    archive = ROOT / f'data/raw/perseus/canonical-greekLit-{commit}.zip'
    database = args.database.resolve()
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('Input database must have no WAL or rollback journal')
    inputs = {'database': database, 'archive': archive, 'generator': Path(__file__).resolve(),
              'source_parser': ROOT / 'scripts/ingest_perseus.py'}
    before = {name: file_hash(path) for name, path in inputs.items()}
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        records = [json.loads(row[0]) for row in db.execute("SELECT data FROM passages WHERE source='perseus'")]
    sources = CachedSources(ROOT, archive, commit)
    try:
        pairs, excluded = build(records, sources)
    finally:
        sources.archive.close()
    after = {name: file_hash(path) for name, path in inputs.items()}
    if before != after or any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('Source archive, database or extraction code changed during proof generation')
    manifest = {'schema_version': 1, 'generator': 'scripts/build_translation_pairings.py',
                'source_commit': commit, 'source_archive_sha256': before['archive'],
                'input_sha256': before,
                'pair_count': len(pairs), 'scope': 'Source-bounded passage previews; not word or sentence alignment.',
                'pairs': pairs}
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    report = {'manifest_sha256': sha(payload), 'pair_count': len(pairs),
              'input_sha256_before': before, 'input_sha256_after': after,
              'input_perseus_records': len(records), 'source_files_checked': len(sources.cache),
              'methods': dict(Counter(p['boundary_proof']['method'] for p in pairs)),
              'excluded_counts': dict(Counter(e['reason'] for e in excluded)), 'excluded': excluded}
    stage.mkdir(parents=True)
    (stage / 'translation_pairings.json').write_bytes(payload)
    (stage / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'excluded'}))


if __name__ == '__main__':
    main()
