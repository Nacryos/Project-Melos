"""Diff stored Campbell GLP passages against the verified transcription.

The reference is data/campbell_glp/transcription.json (two independent image
transcriptions + image adjudication + proofreading). For every poem the expected
passage text is rebuilt from it with the same projection the record builder uses,
then compared with what is stored, either in a corpus snapshot or behind an API.

  python scripts/verify_campbell_glp.py --corpus /path/corpus.sqlite
  python scripts/verify_campbell_glp.py --origin http://127.0.0.1:8795 [--analyze sample|all|none]
  python scripts/verify_campbell_glp.py --origin https://greeklyric.com --expected-passages 288821

Exit status 1 on any difference, missing passage, failed analysis or count mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_campbell_glp import to_record  # noqa: E402

TRANSCRIPTION = ROOT / 'data/campbell_glp/transcription.json'
RECORDS = ROOT / 'data/campbell_glp/campbell_glp.jsonl'
SIDECAR = ROOT / 'backend/translation_comparisons_glp_data.json'
FIVE = ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl'


def expected() -> dict:
    raw = TRANSCRIPTION.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    out = {}
    for poem in json.loads(raw)['poems']:
        if poem['approved_live']:
            continue
        record = to_record({'poet': poem['poet'], 'number': poem['number'], 'metre_lines': poem['metre_lines']},
                           poem['lines'], poem['uncertain'], sha)
        out[record['id']] = record
    return out


def expected_five() -> dict:
    """The five previously approved Alcaeus passages, as corrected to the page images (2026-10-08)."""
    rows = [json.loads(line) for line in FIVE.read_text(encoding='utf-8').splitlines() if line.strip()]
    return {r['id']: r for r in rows}


def diff_line(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f'first difference at char {i}: stored {a[max(0, i-8):i+8]!r} expected {b[max(0, i-8):i+8]!r}'
    return f'length differs: stored {len(a)} expected {len(b)}'


def compare(stored: dict | None, want: dict) -> list:
    if stored is None:
        return ['missing']
    problems = []
    for key in ('text', 'author', 'work', 'edition', 'citation', 'source', 'quality', 'language', 'kind'):
        if stored.get(key) != want[key]:
            problems.append(f'{key}: ' + (diff_line(stored.get('text') or '', want['text']) if key == 'text'
                                          else f'stored {stored.get(key)!r} expected {want[key]!r}'))
    if [l.get('text') for l in stored.get('lines') or []] != [l['text'] for l in want['lines']]:
        problems.append('structured lines differ')
    return problems


def from_corpus(path: Path, ids) -> dict:
    con = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
    out = {}
    for identifier in ids:
        row = con.execute('SELECT data,text FROM passages WHERE id=?', (identifier,)).fetchone()
        if row:
            data = json.loads(row[0])
            if data.get('text') != row[1]:
                data['text'] = '<<text column differs from data JSON>>'
            out[identifier] = data
    return out


def get(origin: str, path: str, **params):
    url = origin.rstrip('/') + path + ('?' + urllib.parse.urlencode(params) if params else '')
    with urllib.request.urlopen(url, timeout=300) as response:
        return json.load(response)


def analyze(origin: str, pid: str, text: str, start: int, end: int):
    body = {'passage_id': pid, 'start': start, 'end': end, 'offset_unit': 'codepoint',
            'selected_text': text[start:end], 'rerank': False, 'fetch_machine': False}
    req = urllib.request.Request(origin.rstrip('/') + '/api/analyze-passage', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as response:
        return json.load(response)


def analysable_lines(text: str):
    from backend.passage_analysis import tokenize_span  # only needed with --origin --analyze
    start = 0
    for line in text.split('\n'):
        end = start + len(line)
        words = [t for t in tokenize_span(text, start, end) if t['kind'] == 'word'] if line.strip() else []
        if 1 <= len(words) <= 12:
            yield start, end, len(words)
        start = end + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--origin')
    parser.add_argument('--analyze', choices=('none', 'sample', 'all'), default='sample',
                        help='with --origin: analyse the first two lines of one poem per poet (sample) or of every poem (all)')
    parser.add_argument('--expected-passages', type=int)
    args = parser.parse_args()
    if bool(args.corpus) == bool(args.origin):
        parser.error('give exactly one of --corpus or --origin')
    new = expected()
    records = {r['id']: r for r in map(json.loads, RECORDS.read_text(encoding='utf-8').splitlines()) if r}
    five = expected_five()
    want = {**five, **new}  # all 237 poems in the book
    report = {'expected_poems': len(want), 'records_file_matches_transcription': records == new,
              'approved_five_corrected': sorted(five)}
    failures = 0 if report['records_file_matches_transcription'] and len(five) == 5 and len(want) == 237 else 1
    if args.corpus:
        stored = from_corpus(args.corpus, want)
        if args.expected_passages is not None:
            con = sqlite3.connect(f'file:{args.corpus.as_posix()}?mode=ro', uri=True)
            report['passages'] = con.execute('SELECT count(*) FROM passages').fetchone()[0]
    else:
        stored = {}
        for identifier in want:
            try:
                stored[identifier] = get(args.origin, '/api/passage', id=identifier)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        if args.expected_passages is not None:
            report['passages'] = get(args.origin, '/api/status')['passages']
    mismatches = {}
    for identifier, record in want.items():
        problems = compare(stored.get(identifier), record)
        if problems:
            mismatches[identifier] = problems
    failures += len(mismatches)
    report.update(found=sum(1 for i in want if i in stored), identical=len(want) - len(mismatches),
                  mismatches=mismatches)
    if args.expected_passages is not None and report['passages'] != args.expected_passages:
        failures += 1
        report['passage_count_error'] = f"{report['passages']} != {args.expected_passages}"
    if args.origin:
        sidecar = json.loads(SIDECAR.read_text(encoding='utf-8')) if SIDECAR.exists() else {'records': []}
        with_translation = {r['campbell_record_id'] for r in sidecar['records']} | set(five)
        bad_translation = [i for i in want if i in stored and
                           ((stored[i].get('translation_comparisons') or {}).get('status') == 'available') != (i in with_translation)]
        failures += len(bad_translation)
        report.update(translations_expected=len(with_translation & set(stored)), translation_mismatches=bad_translation)
        analysed, analysis_failures, seen_poets = 0, [], set()
        if args.analyze != 'none':
            for identifier, record in want.items():
                poet = record['author']
                if args.analyze == 'sample' and poet in seen_poets:
                    continue
                seen_poets.add(poet)
                for start, end, words in list(analysable_lines(record['text']))[:2]:
                    try:
                        result = analyze(args.origin, identifier, record['text'], start, end)
                        rows = [t for t in result['interlinear']['readings'][0]['tokens'] if t.get('kind') == 'word']
                        if not rows:
                            raise ValueError('no word rows')
                        analysed += 1
                    except (urllib.error.HTTPError, KeyError, IndexError, ValueError) as exc:
                        detail = exc.read()[:200].decode('utf-8', 'replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
                        analysis_failures.append({'id': identifier, 'span': record['text'][start:end], 'error': detail})
        failures += len(analysis_failures)
        report.update(lines_analysed=analysed, analysis_failures=analysis_failures)
    report['failures'] = failures
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
