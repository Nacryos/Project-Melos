"""Extract six preselected source-layout line pairs from audited cached HTML.

No translation, linguistic normalization, inferred word alignment, or generic
whole-poem positional zip is performed. Byte slices retain exact source HTML.
An independent line-by-line audit is required before acceptance. Staging only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runtime/alcaeus-translations'
OUT = BASE / 'line-pairs'
HTML = BASE / 'chs-edmunds.html'
SOURCE = BASE / 'chs-translation-candidates.json'
NOTES = BASE / 'chs-source-notes.json'
CAMPBELL = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
PINS = {
    'html': '4e0354d528dc388d2b0afe93cf6cd395d0fefb30591c93af68ee813ad276e5af',
    'source': 'ec305104d5983c4db649438a3d078308ce418d37e14fa213b60680564b0ff1f0',
    'notes': '5ae6184824807d8d7b4c8be657048440fa3809a2c640bc66832563d06169449a',
    'campbell': 'afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b',
}
# Only source selectors and local line numbers, never source wording.
TARGETS = {'129': (0, 1, (19, 20, 21)), '130b': (2, 3, (3, 19, 20))}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path, name: str) -> bytes:
    raw = path.read_bytes()
    if sha(raw) != PINS[name]:
        raise ValueError('Audited input changed: ' + path.name)
    return raw


def save(name: str, payload) -> str:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf8')
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if path.exists() and path.read_bytes() != raw:
        raise FileExistsError('Existing staging artifact differs: ' + name)
    path.write_bytes(raw)
    return sha(raw)


def evidence(raw: bytes, start: int, end: int) -> dict:
    part = raw[start:end]
    return {'raw_path': HTML.relative_to(ROOT).as_posix(), 'raw_sha256': PINS['html'],
            'byte_range': [start, end], 'slice_sha256': sha(part), 'raw_utf8_slice': part.decode('utf8')}


def greek_lines(raw: bytes, block) -> list[dict]:
    rows = []
    for pre_index, pre in enumerate(re.finditer(rb'<pre>(.*?)</pre>', block.group(1), re.S)):
        pre_start = block.start(1) + pre.start(1)
        cursor = pre_start
        for part in pre.group(1).splitlines(keepends=True):
            start, end = cursor, cursor + len(part)
            cursor = end
            displayed = html.unescape(part.decode('utf8')).strip()
            if not displayed:
                continue
            if '<' in displayed or '>' in displayed:
                raise ValueError('Unexpected Greek HTML markup')
            label = re.match(r'^(\d+)\s+', displayed)
            text = displayed[label.end():] if label else displayed
            rows.append({'source_verse_ordinal': len(rows)+1, 'source_pre_index': pre_index,
                         'printed_label': label.group(1) if label else None, 'text': text,
                         'source_slice': evidence(raw, start, end)})
    return rows


def english_text(part: bytes) -> str:
    node = BeautifulSoup(part.decode('utf8'), 'html.parser')
    for marker in node.select('.noteref,a[name]'):
        marker.decompose()
    return re.sub(r'\s+', ' ', node.get_text()).strip()


def english_lines(raw: bytes, block) -> list[dict]:
    body = block.group(1)
    rows = []
    cursor = 0
    boundaries = list(re.finditer(rb'<br\s*/?>|<p(?:\s[^>]*)?>|</p>', body, re.I))
    for boundary in boundaries + [None]:
        end = boundary.start() if boundary else len(body)
        part = body[cursor:end]
        text = english_text(part)
        if text:
            rows.append({'source_english_line_ordinal': len(rows)+1, 'text': text,
                         'source_slice': evidence(raw, block.start(1)+cursor, block.start(1)+end)})
        cursor = boundary.end() if boundary else len(body)
    return rows


def note_evidence(raw: bytes, approved_notes: list[dict]) -> list[dict]:
    nodes = list(re.finditer(rb'<div class="ftNote">\s*<div class="Paragraph">.*?</div>\s*</div>', raw, re.S))
    output = []
    for note in approved_notes:
        target = ('name="n.' + str(note['number']) + '"').encode('ascii')
        matches = [node for node in nodes if target in node.group(0)]
        if len(matches) != 1:
            raise ValueError('Source note boundary is not unique')
        node = matches[0]
        parsed_note = BeautifulSoup(node.group(0).decode('utf8'), 'html.parser')
        for marker in parsed_note.select('.noteref'):
            marker.decompose()
        if parsed_note.get_text(' ', strip=True) != note['text']:
            raise ValueError('Source note differs from approved extraction')
        output.append({**deepcopy(note), 'source_slice': evidence(raw, node.start(), node.end())})
    return output


def extract() -> str:
    raw = read(HTML, 'html')
    sources = {row['assignment_fragment']: row for row in json.loads(read(SOURCE, 'source'))}
    notes = note_evidence(raw, json.loads(read(NOTES, 'notes')))
    poems = {row['metadata']['assignment_fragment']: row for row in
             map(json.loads, read(CAMPBELL, 'campbell').decode('utf8').splitlines())}
    blocks = list(re.finditer(rb'<div class="inlineCitation">(.*?)</div>', raw, re.S))
    if len(blocks) != 8:
        raise ValueError('Source parallel layout changed')
    candidates = []
    inventories = []
    for fragment, (gi, ei, targets) in TARGETS.items():
        greek, english = greek_lines(raw, blocks[gi]), english_lines(raw, blocks[ei])
        source, poem = sources[fragment], poems[fragment]
        approved_greek = [re.sub(r'^\d+\s+', '', line.strip()) for line in source['paired_greek'].splitlines() if line.strip()]
        approved_english = [line for line in source['text'].splitlines() if line.strip()]
        if [row['text'] for row in greek] != approved_greek or [row['text'] for row in english] != approved_english:
            raise ValueError('Byte parser disagrees with approved whole source')
        expected_counts = (28,28) if fragment == '129' else (24,22)
        if (len(greek), len(english)) != expected_counts:
            raise ValueError('Source verse inventory changed')
        inventories.append({'fragment':fragment, 'greek_line_count':len(greek), 'english_line_count':len(english),
                            'bounded_pairable_ordinals':[1,28] if fragment=='129' else [1,20],
                            'selected_ordinals':list(targets)})
        poem_lines = poem['text'].splitlines(keepends=True)
        poem_bytes = poem['text'].encode('utf8')
        offsets = [0]
        for line in poem_lines: offsets.append(offsets[-1]+len(line.encode('utf8')))
        for ordinal in targets:
            if fragment=='130b' and ordinal>20:
                raise ValueError('No global positional pairing for unequal source inventories')
            gr, en = greek[ordinal-1], english[ordinal-1]
            campbell_line = poem_lines[ordinal-1].rstrip('\r\n')
            if gr['text'] != campbell_line:
                raise ValueError('Greek is not an exact Campbell line: '+fragment+':'+str(ordinal))
            begin = offsets[ordinal-1]
            end = begin + len(campbell_line.encode('utf8'))
            if poem_bytes[begin:end].decode('utf8') != gr['text']:
                raise ValueError('Campbell line byte range mismatch')
            relevant_numbers = {27,28,29,30} if fragment=='129' else {48,49,50,51}
            candidates.append({
                'id':f'chs-line-pair:{fragment}:{ordinal}', 'status':'pending_independent_line_audit',
                'campbell_record_id':poem['id'], 'campbell_local_line_number':ordinal,
                'campbell_line_index_range':[ordinal-1,ordinal], 'campbell_text_sha256':sha(poem_bytes),
                'campbell_raw_sha256':poem['raw_sha256'], 'campbell_source_pdf_sha256':poem['metadata']['source_pdf_sha256'],
                'campbell_line_text_utf8_range':[begin,end], 'campbell_line_text':campbell_line,
                'campbell_greek_line_exact_match':True, 'source_greek':gr, 'source_english':en,
                'source_url':source['source_url'], 'translator':source['translator'],
                'edition':source['edition'], 'citation':source['citation'],
                'pairing_method':'same_bounded_verse_ordinal_in_published_parallel_layout',
                'alignment_scope':'one_full_source_line_only', 'word_aligned':False,
                'standalone_sentence_claim':False, 'whole_poem_exact_edition_alignment':False,
                'source_context':{'greek_lines':deepcopy(greek[max(0,ordinal-3):min(len(greek),ordinal+2)]),
                                  'english_lines':deepcopy(english[max(0,ordinal-3):min(len(english),ordinal+2)])},
                'source_notes':deepcopy([note for note in notes if note['number'] in relevant_numbers]),
                'full_source_translation':source['text'],
                'whole_source_translation_slice':evidence(raw,blocks[ei].start(),blocks[ei].end()),
                'license':source['license'], 'license_url':source['license_url'], 'reuse_status':source['reuse_status'],
                'compatibility_verdict':'pending', 'source_notes_negate_compatibility':None,
            })
    payload = {'schema_version':1, 'scope':'source_line_comparison_candidates_staging_only',
               'candidate_count':len(candidates), 'input_hashes':PINS, 'source_inventories':inventories,
               'candidates':candidates}
    return save('line-pair-candidates.json',payload)


def accept(audit_path: Path) -> str:
    raw = (OUT/'line-pair-candidates.json').read_bytes()
    audit_raw = audit_path.read_bytes()
    audit = json.loads(audit_raw)
    if audit.get('candidate_sha256') != sha(raw) or audit.get('verdict') != 'PASS':
        raise ValueError('No hash-bound independent line audit')
    payload = json.loads(raw)
    verdicts = audit.get('line_verdicts',{})
    if set(verdicts) != {row['id'] for row in payload['candidates']}:
        raise ValueError('Audit must account for every finite candidate')
    accepted, excluded = [], []
    for row in payload['candidates']:
        verdict = verdicts[row['id']]
        if verdict.get('verdict') == 'PASS' and verdict.get('source_notes_negate_compatibility') is False:
            accepted.append({**deepcopy(row), 'status':'independently_audited_source_line_pair',
                             'compatibility_verdict':'PASS', 'source_notes_negate_compatibility':False,
                             'independent_audit':deepcopy(verdict)})
        else:
            excluded.append({'id':row['id'], 'independent_audit':deepcopy(verdict)})
    return save('line-pairs.accepted.json',{'schema_version':1,'scope':'source_line_pairs_staging_only',
        'candidate_sha256':sha(raw),'audit_sha256':sha(audit_raw),'accepted_count':len(accepted),
        'excluded_count':len(excluded),'accepted':accepted,'excluded':excluded})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['extract','accept'])
    parser.add_argument('--audit',type=Path,default=OUT/'line-pair-audit.json')
    args=parser.parse_args()
    print(extract() if args.phase=='extract' else accept(args.audit))
