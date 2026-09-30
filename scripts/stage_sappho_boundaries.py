"""Stage cached-source boundary repairs; never overwrite accepted corpus/audits.

Output JSONL is a full replacement candidate. Unaffected pages retain their
original serialized rows. An independent audit is required before acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import ingest_sappho as collector


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reading_signature(record):
    return {key: record.get(key) for key in ('id', 'citation', 'text', 'quality', 'lines')}


def stage(output_dir):
    root = collector.ROOT
    source = root / 'data/processed/sappho.jsonl'
    raw_lines = source.read_text(encoding='utf-8').splitlines()
    rows = [json.loads(line) for line in raw_lines]
    accepted = json.loads((root / 'data/reports/audit-sappho.json').read_text(encoding='utf-8'))['files'][source.name]
    if accepted.get('verdict') != 'PASS' or accepted.get('sha256') != digest(source.read_bytes()):
        raise RuntimeError('Input is not the accepted Sappho snapshot')
    pages = {}
    for row in rows:
        if row['id'].startswith('digital-sappho:'):
            pages.setdefault(row['source_url'], []).append(row)
    replacements = {}
    report = {'input_sha256': digest(source.read_bytes()), 'acceptance': 'PENDING INDEPENDENT AUDIT',
              'pages': [], 'unchanged_pages': 0}
    for url, previous in pages.items():
        raw_paths = {(row['raw_path'], row['raw_sha256']) for row in previous}
        if len(raw_paths) != 1:
            raise RuntimeError('Multiple raw artifacts for page: ' + url)
        relative, expected = next(iter(raw_paths))
        path = root / relative
        data = path.read_bytes()
        if digest(data) != expected:
            raise RuntimeError('Raw artifact hash mismatch: ' + relative)
        parsed = collector.digital_records(url, path, data, previous)
        before = [reading_signature(r) for r in previous if r['kind'] == 'text']
        after = [reading_signature(r) for r in parsed if r['kind'] == 'text']
        before_parents = {r['id']: r.get('parent_id') for r in previous if r.get('metadata', {}).get('subtype') == 'vocabulary'}
        after_parents = {r['id']: r.get('parent_id') for r in parsed if r.get('metadata', {}).get('subtype') == 'vocabulary'}
        if before == after and before_parents == after_parents:
            report['unchanged_pages'] += 1
            continue
        replacements[url] = parsed
        old_by_id = {r['id']: r for r in previous}
        new_by_id = {r['id']: r for r in parsed}
        reused_wrongly = [identifier for identifier in old_by_id.keys() & new_by_id.keys()
                         if old_by_id[identifier]['kind'] == 'text'
                         and old_by_id[identifier]['citation'] != new_by_id[identifier]['citation']]
        if reused_wrongly:
            raise RuntimeError('Existing IDs repurposed: ' + repr(reused_wrongly))
        report['pages'].append({'source_url': url, 'raw_path': relative, 'raw_sha256': expected,
            'old_readings': before, 'new_readings': after,
            'added_ids': sorted(new_by_id.keys() - old_by_id.keys()),
            'removed_ids': sorted(old_by_id.keys() - new_by_id.keys()),
            'changed_ids': sorted(identifier for identifier in old_by_id.keys() & new_by_id.keys()
                                  if old_by_id[identifier] != new_by_id[identifier]),
            'new_footnote_links': [{'record_id': r['id'], 'links': r.get('metadata', {}).get('source_footnote_links')}
                                   for r in parsed if r.get('metadata', {}).get('source_footnote_links')]})
    emitted = set()
    output = []
    for row, raw_line in zip(rows, raw_lines):
        url = row['source_url']
        if url not in replacements:
            output.append(raw_line)
        elif url not in emitted:
            output.extend(json.dumps(r, ensure_ascii=False) for r in replacements[url])
            emitted.add(url)
    parsed_output = [json.loads(line) for line in output]
    ids = {row['id'] for row in parsed_output}
    if len(ids) != len(parsed_output):
        raise RuntimeError('Duplicate staged IDs')
    if any(r.get('parent_id') and r['parent_id'] not in ids for r in parsed_output):
        raise RuntimeError('Dangling staged parent link')
    payload = ('\n'.join(output) + '\n').encode('utf-8')
    report.update(output_sha256=digest(payload), old_records=len(rows), new_records=len(output),
                  changed_pages=len(replacements), source_files_changed=False)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / 'sappho.jsonl'
    report_path = output_dir / 'parser-diff.json'
    if destination.exists() or report_path.exists():
        raise FileExistsError('Require fresh staging files; existing staged artifacts are preserved')
    destination.write_bytes(payload)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('changed_pages', 'unchanged_pages', 'old_records', 'new_records', 'output_sha256')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    stage(parser.parse_args().output_dir)
