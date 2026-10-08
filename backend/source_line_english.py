"""Six audited full-line English correspondences; no partial phrase fallback.

exactmatch consumes an already corpus-bound, codepoint selection. This module
does not register routes, alter analysis, add model context, or join fragments.
The --build command projects only the approved source artifact into local data.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / 'runtime/alcaeus-translations/line-pairs'
DATA_PATH = Path(__file__).with_name('source_line_english_data.json')
DATA_SHA256 = 'e3501f6a9e4bbf7099875f49e9718c6c4589853ecfaf5fc0f384db56af2e7bf0'
MAX_BYTES = 150_000
PINS = {
    'accepted': 'a24787428143e3704d9854f4a08a66ff04ee977b549e7d2dfd2adaef50f1b601',
    'final_audit': '11a335669db20d64c9ed8de2b01435f1855f16a7e14863ef6d55166c92a1c1ef',
    'source_audit': '1c015c43909b74d8790069160367083b0181568f0e9c73ad81a6fc4a774e4f98',
    'campbell': 'ab2e1487885431669ebff57c566419bdceb1d6af69740e6ed05e8b7190d84457',
}
IDS = frozenset(('chs-line-pair:129:19', 'chs-line-pair:129:20', 'chs-line-pair:129:21',
                 'chs-line-pair:130b:3', 'chs-line-pair:130b:19', 'chs-line-pair:130b:20'))
IDENTITY_FIELDS = ('source', 'kind', 'language', 'quality', 'author', 'work', 'edition', 'source_url', 'raw_sha256')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, expected: str, limit: int = MAX_BYTES) -> bytes:
    if path.stat().st_size > limit:
        raise ValueError('Approved source exceeds size limit')
    raw = path.read_bytes()
    if _sha(raw) != expected:
        raise ValueError('Approved source hash mismatch: ' + path.name)
    return raw


def _public_slice(source: dict) -> dict:
    return {key: deepcopy(source[key]) for key in ('raw_sha256', 'byte_range', 'slice_sha256')}


def project(accepted_path: Path = STAGED / 'line-pairs.accepted.json',
            final_audit_path: Path = STAGED / 'line-pair-final-audit.json',
            source_audit_path: Path = STAGED / 'line-pair-audit.json',
            campbell_path: Path = ROOT / 'data/campbell_glp/alcaeus_five_corrected.jsonl') -> dict:
    accepted = json.loads(_read(accepted_path, PINS['accepted']))
    final_audit = json.loads(_read(final_audit_path, PINS['final_audit']))
    audit = json.loads(_read(source_audit_path, PINS['source_audit']))
    poems = {row['id']: row for row in map(json.loads, _read(campbell_path, PINS['campbell']).decode('utf8').splitlines())}
    if (final_audit.get('verdict') != 'PASS' or final_audit.get('accepted_sha256') != PINS['accepted']
            or final_audit.get('source_audit_sha256') != PINS['source_audit']
            or audit.get('verdict') != 'PASS' or accepted.get('audit_sha256') != PINS['source_audit']
            or accepted.get('candidate_sha256') != audit.get('candidate_sha256')
            or accepted.get('accepted_count') != 6 or accepted.get('excluded_count') != 0
            or len(accepted.get('accepted', [])) != 6
            or {row['id'] for row in accepted['accepted']} != IDS):
        raise ValueError('Finite source-line approval chain changed')
    records = []
    for row in accepted['accepted']:
        poem = poems[row['campbell_record_id']]
        verdict = audit['line_verdicts'][row['id']]
        text = poem['text']
        text_bytes = text.encode('utf8')
        metadata = poem['metadata']
        begin, end = row['campbell_line_text_utf8_range']
        row = dict(row)
        if (_sha(text_bytes) != row['campbell_text_sha256']
                and metadata.get('text_corrections')
                and metadata.get('previous_text_sha256') == row['campbell_text_sha256']):
            # Re-anchor to the page-image-corrected text (2026-10-08): the paired line itself
            # must be unchanged and occur exactly once; only its offsets and the text hash move.
            line = row['campbell_line_text'].encode('utf8')
            if (text_bytes.count(line) != 1
                    or any(c['previous'] == row['campbell_line_text'] for c in metadata['text_corrections'])):
                raise ValueError('Source line was itself corrected; re-approval required')
            begin = text_bytes.index(line)
            end = begin + len(line)
            row['campbell_text_sha256'] = _sha(text_bytes)
        if (verdict != row['independent_audit'] or verdict.get('verdict') != 'PASS'
                or verdict.get('source_notes_negate_compatibility') is not False
                or row.get('compatibility_verdict') != 'PASS'
                or row.get('word_aligned') is not False
                or row.get('whole_poem_exact_edition_alignment') is not False
                or row.get('standalone_sentence_claim') is not False
                or _sha(text_bytes) != row['campbell_text_sha256']
                or poem['raw_sha256'] != row['campbell_raw_sha256']
                or metadata['source_pdf_sha256'] != row['campbell_source_pdf_sha256']
                or text_bytes[begin:end].decode('utf8') != row['campbell_line_text']
                or row['source_greek']['text'] != row['campbell_line_text']):
            raise ValueError('Source-line identity or compatibility changed')
        start_cp, end_cp = len(text_bytes[:begin].decode('utf8')), len(text_bytes[:end].decode('utf8'))
        if text[start_cp:end_cp] != row['campbell_line_text']:
            raise ValueError('Source-line codepoint conversion failed')
        full_english = row['full_source_translation']
        english_lines = [line for line in full_english.splitlines() if line.strip()]
        ordinal = row['campbell_local_line_number']
        if english_lines[ordinal-1] != row['source_english']['text']:
            raise ValueError('English is no longer the approved complete source line')
        selected_notes = []
        for number in verdict.get('contextual_note_numbers', []):
            matches = [note for note in row['source_notes'] if note['number'] == number]
            if len(matches) != 1:
                raise ValueError('Required source note is missing')
            note = matches[0]
            selected_notes.append({key: deepcopy(note[key]) for key in ('number','text','source_url','raw_sha256')})
        records.append({
            'id': row['id'], 'campbell_record_id': poem['id'],
            'campbell_identity': {**{key: poem[key] for key in IDENTITY_FIELDS},
                'text_sha256':row['campbell_text_sha256'], 'source_pdf_sha256':metadata['source_pdf_sha256'],
                'assignment_fragment':metadata['assignment_fragment'], 'edition_fragment':metadata['edition_fragment']},
            'span': {'start':start_cp,'end':end_cp,'offset_unit':'codepoint','text':row['campbell_line_text']},
            'match': {
                'status':'matched', 'evidence_type':'published_source_line_comparison',
                'scope':'one_full_source_line_only', 'selection_match':'exact_full_line',
                'word_aligned':False, 'standalone_sentence_claim':False,
                'whole_poem_translation':False, 'exact_edition_alignment':False, 'model_eligible':False,
                'comparison_id':row['id'], 'language':'eng', 'text':row['source_english']['text'],
                'translator':row['translator'], 'edition':row['edition'], 'citation':row['citation'],
                'source_url':row['source_url'], 'source_greek':row['source_greek']['text'],
                'source_line_reference':{'fragment':metadata['assignment_fragment'],
                    'campbell_local_line_number':ordinal,'source_verse_ordinal':row['source_greek']['source_verse_ordinal']},
                'source_provenance':{'greek':_public_slice(row['source_greek']['source_slice']),
                    'english':_public_slice(row['source_english']['source_slice'])},
                'source_notes':selected_notes,
                'source_context':{'required_line_ordinals':deepcopy(verdict['required_context_ordinals']),
                    'english_lines':[{'ordinal':n,'text':english_lines[n-1]} for n in verdict['required_context_ordinals']],
                    'whole_source_translation':full_english},
                'audit_caveats':deepcopy(verdict['caveats']),
                'license':row['license'],'license_url':row['license_url'],'reuse_status':row['reuse_status'],
                'license_unrestricted':False,
            }})
    return {'schema_version':1,'schema':'audited_source_line_english','record_count':len(records),
            'source_hashes':PINS,'global_audit_caveats':deepcopy(audit['global_caveats']),'records':records}


def build_data(output: Path = DATA_PATH, **inputs) -> str:
    raw = (json.dumps(project(**inputs), ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf8')
    if output.exists() and output.read_bytes() != raw:
        raise FileExistsError('Existing source-line projection differs')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(raw)
    return _sha(raw)


def _bound(record: dict, passage: dict) -> bool:
    identity, metadata = record['campbell_identity'], passage.get('metadata')
    return (passage.get('id') == record['campbell_record_id'] and isinstance(metadata,dict)
        and all(passage.get(key) == identity[key] for key in IDENTITY_FIELDS)
        and all(metadata.get(key) == identity[key] for key in
                ('assignment_fragment','edition_fragment','source_pdf_sha256'))
        and isinstance(passage.get('text'),str)
        and _sha(passage['text'].encode('utf8')) == identity['text_sha256'])


def exactmatch(passage: dict, selection: dict, *, allow_outer_whitespace: bool = False,
               path: Path = DATA_PATH) -> dict | None:
    """Return an audited source-line comparison, or None without any fallback.

selection must contain text/start/end/offset_unit='codepoint', as emitted by
the passage analyzer. Caller-supplied text must equal the actual passage span.
Only explicit allow_outer_whitespace=True permits trimming actual selected
outer whitespace; interior whitespace, punctuation and diacritics stay exact.
"""
    if (not isinstance(passage,dict) or not isinstance(selection,dict)
            or type(allow_outer_whitespace) is not bool or selection.get('offset_unit') != 'codepoint'):
        return None
    text, selected = passage.get('text'), selection.get('text')
    start, end = selection.get('start'), selection.get('end')
    if (not isinstance(text,str) or not isinstance(selected,str) or not selected
            or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
            or text[start:end] != selected
            or ('passage_id' in selection and selection['passage_id'] != passage.get('id'))):
        return None
    original_start, original_end = start, end
    if allow_outer_whitespace:
        left = len(selected)-len(selected.lstrip())
        right = len(selected)-len(selected.rstrip())
        start, end = start+left, end-right
        selected = selected.strip()
        if not selected:
            return None
    try:
        payload = json.loads(_read(Path(path),DATA_SHA256))
        if (payload.get('schema_version') != 1 or payload.get('schema') != 'audited_source_line_english'
                or payload.get('record_count') != 6 or payload.get('source_hashes') != PINS
                or len(payload.get('records',[])) != 6 or {row['id'] for row in payload['records']} != IDS):
            return None
        matches = [row for row in payload['records'] if _bound(row,passage)
                   and row['span'] == {'start':start,'end':end,'offset_unit':'codepoint','text':selected}]
        if len(matches) != 1:
            return None
        result = deepcopy(matches[0]['match'])
        result['matched_span'] = {'start':start,'end':end,'offset_unit':'codepoint'}
        result['outer_whitespace_trimmed'] = (start,end) != (original_start,original_end)
        return result
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,json.JSONDecodeError):
        return None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true',required=True)
    parser.add_argument('--output',type=Path,default=DATA_PATH)
    print(build_data(parser.parse_args().output))
