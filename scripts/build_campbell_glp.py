"""Assemble the verified Campbell GLP transcription and its corpus records.

Inputs (committed evidence; method in docs/audits/campbell-glp-full.md):
  data/campbell_glp/evidence/merged_A.json, merged_B.json  two independent page-image transcriptions
  data/campbell_glp/evidence/adjudication/out_J*.json       image-based decisions on every A/B disagreement
                                                       and every cross-check/uncertainty flag
Outputs (committed):
  data/campbell_glp/transcription.json   final per-poem transcription with layout + provenance
  data/campbell_glp/campbell_glp.jsonl   corpus records (same schema as the five approved
                                         campbell-glp:alcaeus:* rows), excluding those five

The five owner-approved Alcaeus passages (34a, 129, 130b, 326, 350) are already live
and are never rebuilt here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'data/campbell_glp/evidence'
OUT_DIR = ROOT / 'data/campbell_glp'
PDF_SHA256 = '8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f'
PDF_NAME = 'Campbell Greek Lyric Poetry.pdf.pdf'
EDITION = 'David A. Campbell, Greek Lyric Poetry (1967; reprinted 1976), Macmillan'
SOURCE_URL = 'https://openlibrary.org/works/OL105540W'
APPROVED = {('ALCAEUS', '34a'), ('ALCAEUS', '129'), ('ALCAEUS', '130'), ('ALCAEUS', '326'), ('ALCAEUS', '350')}
AUTHORS = {'CARMINA POPULARIA': 'Carmina Popularia', 'SCOLIA': 'Scolia'}
METHOD = ('two independent image-grounded transcriptions of the scanned page; every disagreement and every '
          'cross-check or uncertainty flag adjudicated against magnified page crops; not certified '
          'exact-diplomatic at every glyph')


def nfc(text: str) -> str:
    return unicodedata.normalize('NFC', text)


def poem_id(poet: str, number: str) -> str:
    slug = number.lower().replace('fr.', 'fr').replace('(p.m.g.)', 'pmg').replace('–', '-')
    slug = re.sub(r'[^0-9a-z]+', '-', slug).strip('-')
    return f"campbell-glp:{poet.lower().replace(' ', '-')}:{slug}"


def author_of(poet: str) -> str:
    return AUTHORS.get(poet, poet.title())


def work_of(poet: str, number: str) -> str:
    if poet == 'THEOGNIS':
        return 'Elegies'
    if poet == 'BACCHYLIDES' and number.isdigit():
        return 'Odes'
    return 'Fragments'


def citation_of(poet: str, number: str) -> str:
    if poet == 'THEOGNIS':
        return 'Lines ' + number.replace('-', '–')
    if poet == 'BACCHYLIDES' and number.isdigit():
        return 'Ode ' + number
    if number.lower().startswith('fr.') or number.startswith('Fr.'):
        return 'Fragment ' + number.split('.', 1)[1].strip() if poet == 'BACCHYLIDES' else number
    return 'Fragment ' + number


def load_fragments(name: str) -> dict:
    data = json.loads((WORK / f'merged_{name}.json').read_text(encoding='utf-8'))
    return {f"{f['poet']}|{f['number']}": f for f in data['fragments']}


def load_decisions() -> tuple[dict, dict]:
    disputes = {d['dispute_id']: d for d in json.loads((WORK / 'disputes.json').read_text(encoding='utf-8'))['disputes']}
    decisions = {}
    for path in sorted((WORK / 'adjudication').glob('out_J[1-8].json')):
        for d in json.loads(path.read_text(encoding='utf-8'))['decisions']:
            if d['dispute_id'] in decisions:
                raise ValueError(f'duplicate decision {d["dispute_id"]}')
            decisions[d['dispute_id']] = {**d, 'packet': path.stem}
    missing = sorted(set(disputes) - set(decisions))
    if missing:
        raise ValueError(f'{len(missing)} disputes lack a decision, e.g. {missing[:10]}')
    return disputes, decisions


def apply_decisions(a: dict, b: dict, items: list) -> tuple[list, list, int]:
    lines = copy.deepcopy(a['lines'])
    notes, changed = [], 0
    for dispute, decision in sorted(items, key=lambda x: x[0]['a_range'][0], reverse=True):
        i1, i2 = dispute['a_range']
        j1, j2 = dispute['b_range']
        template = lines[i1:i2] or b['lines'][j1:j2] or [{'kind': 'verse', 'pdf_page': dispute['pdf_pages'][0]}]
        final = [nfc(t) for t in decision['final_lines']]
        labels = decision.get('labels') or [''] * len(final)
        speakers = decision.get('strophe_labels') or [''] * len(final)
        if len(labels) != len(final) or len(speakers) != len(final):
            raise ValueError(f'label count mismatch in dispute {dispute["dispute_id"]}')
        new = []
        for k, text in enumerate(final):
            base = template[min(k, len(template) - 1)]
            new.append({**base, 'text': text, 'label': labels[k], 'strophe_label': speakers[k]})
        if [x['text'] for x in lines[i1:i2]] != final:
            changed += 1
        lines[i1:i2] = new
        if decision.get('uncertain'):
            notes.append((i1, decision.get('uncertain_note') or decision.get('basis') or 'uncertain reading',
                          ' / '.join(final)))
    return lines, notes, changed


def load_proofreading() -> dict:
    """Image-adjudicated proofreading fixes (runtime/campbell-full/adjudication/{in,out}_R.json)."""
    in_path, out_path = WORK / 'adjudication/in_R.json', WORK / 'adjudication/out_R.json'
    if not in_path.exists():
        return {}
    items = {i['item_id']: i for i in json.loads(in_path.read_text(encoding='utf-8'))['items']}
    decisions = {d['item_id']: d for d in json.loads(out_path.read_text(encoding='utf-8'))['decisions']}
    if set(items) != set(decisions):
        raise ValueError('every proofreading item needs exactly one decision')
    fixes = {}
    for item_id, item in items.items():
        if item['type'] != 'text':
            raise ValueError(f'unhandled proofreading item type {item["type"]}')
        fixes[(item['poem_id'], item['line_index'])] = (item['current'], decisions[item_id])
    return fixes


def apply_proofreading(poem_id: str, lines: list, fixes: dict) -> tuple[list, list]:
    notes = []
    for (pid, index), (current, decision) in fixes.items():
        if pid != poem_id:
            continue
        if lines[index]['text'] != current:
            raise ValueError(f'proofreading fix for {pid} line {index} no longer matches the text')
        lines[index] = {**lines[index], 'text': nfc(decision['final_text'])}
        if decision.get('uncertain') or (not decision.get('accept') and decision.get('uncertain_note')):
            notes.append((index, decision.get('uncertain_note') or decision.get('basis'), lines[index]['text']))
    return lines, notes


def to_record(fragment: dict, lines: list, uncertain: list, transcription_sha: str) -> dict:
    poet, number = fragment['poet'], fragment['number']
    verse, prose, source_notes, structure = [], [], [], {'stanza_breaks': [], 'indented': [], 'strophe_labels': []}
    pending_gap = False
    for line in lines:
        kind = line.get('kind') or 'verse'
        if kind in ('prose', 'note'):
            (prose if kind == 'prose' else source_notes).append(line['text'])
            pending_gap = bool(verse)
            continue
        if pending_gap:
            verse.append({'label': '', 'text': ''})  # structural boundary, as in Alcaeus 350
            pending_gap = False
        index = len(verse)
        if line.get('stanza_break_before'):
            structure['stanza_breaks'].append(index)
        if line.get('indent'):
            structure['indented'].append(index)
        if line.get('strophe_label'):
            structure['strophe_labels'].append({'line_index': index, 'label': line['strophe_label']})
        verse.append({'label': line.get('label') or '', 'text': line['text']})
    text = '\n'.join(x['text'] for x in verse)
    pages = sorted({line['pdf_page'] for line in lines})
    metadata = {
        'edition_fragment': number,
        'source_pdf_sha256': PDF_SHA256,
        'source_pdf_filename': PDF_NAME,
        'source_source': 'User-supplied Campbell PDF',
        'pdf_pages': pages,
        'printed_pages': [p - 32 for p in pages],
        'transcription_method': METHOD,
        'transcription_uncertainty': uncertain,
        'audit_path': 'docs/audits/campbell-glp-full.md',
        'transcription_sha256': transcription_sha,
        'layout': structure,
    }
    if fragment.get('metre_lines'):
        metadata['metre_scheme'] = [m for m in fragment['metre_lines'] if isinstance(m, str)]
    if prose:
        metadata['quotation_prose_lines'] = [{'label': '', 'text': t} for t in prose]
    if source_notes:
        metadata['source_note'] = ' '.join(f'The edition prints the note “{t}” here.' for t in source_notes)
    return {
        'id': poem_id(poet, number), 'source': 'campbell_assignment', 'source_url': SOURCE_URL,
        'raw_path': 'data/campbell_glp/transcription.json', 'raw_sha256': transcription_sha,
        'author': author_of(poet), 'work': work_of(poet, number), 'edition': EDITION,
        'citation': citation_of(poet, number), 'language': 'grc', 'kind': 'text',
        'quality': 'machine_corrected_ocr', 'license': 'user_supplied_edition_excerpt',
        'text': text, 'lines': verse, 'metadata': metadata,
    }


def build(write: bool = True) -> dict:
    A, B = load_fragments('A'), load_fragments('B')
    disputes, decisions = load_decisions()
    by_key = {}
    for did, dispute in disputes.items():
        by_key.setdefault(dispute['key'], []).append((dispute, decisions[did]))
    poems, stats = [], {'fragments': 0, 'lines': 0, 'disputes': len(disputes), 'changed_from_A': 0}
    fixes = load_proofreading()
    stats['proofreading_items'] = len(fixes)
    for key, fragment in A.items():
        lines, notes, changed = apply_decisions(fragment, B[key], by_key.get(key, []))
        stats['changed_from_A'] += changed
        before = [line['text'] for line in lines]
        lines, proof_notes = apply_proofreading(poem_id(fragment['poet'], fragment['number']), lines, fixes)
        revised = {old: line['text'] for old, line in zip(before, lines) if old != line['text']}
        # An earlier adjudication note about a line the proofreading round revised is kept, but
        # re-attached to the revised text and marked as superseded, so the two views stay visible.
        notes = [(i, f'{note} (superseded by the proofreading round, which reads “{revised[text]}”)', revised[text])
                 if text in revised else (i, note, text) for i, note, text in notes]
        notes += proof_notes
        uncertain = []
        for _, note, text in sorted(notes, key=lambda n: n[0]):
            uncertain.append(f'Line “{text}”: {note}')
        poems.append({'id': poem_id(fragment['poet'], fragment['number']), 'poet': fragment['poet'],
                      'number': fragment['number'], 'approved_live': (fragment['poet'], fragment['number']) in APPROVED,
                      'metre_lines': fragment.get('metre_lines') or [], 'lines': lines, 'uncertain': uncertain})
        stats['fragments'] += 1
        stats['lines'] += len(lines)
    transcription = {'schema': 'campbell_glp_transcription', 'schema_version': 1, 'source_pdf_sha256': PDF_SHA256,
                     'edition': EDITION, 'method': METHOD, 'poems': poems}
    raw = (json.dumps(transcription, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    transcription_sha = hashlib.sha256(raw).hexdigest()
    records = [to_record({'poet': p['poet'], 'number': p['number'], 'metre_lines': p['metre_lines']},
                         p['lines'], p['uncertain'], transcription_sha)
               for p in poems if not p['approved_live']]
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate record ids')
    for r in records:
        if '�' in r['text'] or not unicodedata.is_normalized('NFC', r['text']) or not r['text'].strip():
            raise ValueError('bad text in ' + r['id'])
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / 'transcription.json').write_bytes(raw)
        (OUT_DIR / 'campbell_glp.jsonl').write_bytes(
            ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records).encode('utf-8'))
    stats.update(records=len(records), approved_live_skipped=sum(p['approved_live'] for p in poems),
                 transcription_sha256=transcription_sha)
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    print(json.dumps(build(write=not parser.parse_args().dry_run), indent=1))
