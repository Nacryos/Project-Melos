"""Read-only occurrence/selection audit, not a semantic accuracy benchmark.

All Greek and English data are copied from the source artifact or saved live API
responses. No reranking, machine fetch, inferred glosses, or reconstructed words.
Use a new output directory for each deployment; cached receipts are immutable.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.passage_analysis import MAX_CHARACTERS, MAX_WORDS, tokenize_span, utf16_offset
from backend.interlinear import canonical_features


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Receipts:
    def __init__(self, base, directory, timeout=90, offline=False):
        self.base, self.directory, self.timeout, self.offline = base.rstrip('/'), directory, timeout, offline
        directory.mkdir(parents=True, exist_ok=True)

    def call(self, route, params=None, payload=None):
        request = {'base': self.base, 'route': route, 'params': params, 'payload': payload}
        key = sha(json.dumps(request, sort_keys=True, ensure_ascii=False))
        path = self.directory / (key + '.json')
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            if self.offline:
                raise RuntimeError('Missing offline receipt: ' + str(path))
            if path.with_suffix('.pending.json').exists():
                raise RuntimeError('Interrupted request has a pending receipt; no automatic retry: ' + str(path))
            url = self.base + route + ('?' + urllib.parse.urlencode(params) if params else '')
            data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'Melos-occurrence-audit/1'})
            # A durable preflight record makes even an interrupted request visible.
            save(path.with_suffix('.pending.json'), {'request': request, 'started_at_unix': time.time()})
            began = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    raw, status, headers = response.read(), response.status, dict(response.headers)
            except urllib.error.HTTPError as error:
                raw, status, headers = error.read(), error.code, dict(error.headers)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                result = {'request': request, 'http_status': None, 'error': str(error), 'recorded_at_unix': time.time()}
                save(path, result)
                raise RuntimeError('Request failed; receipt saved, no retry: ' + str(path)) from error
            raw_path = path.with_suffix('.body')
            raw_path.write_bytes(raw)
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            result = {'request': request, 'http_status': status, 'headers': headers,
                      'raw_body_sha256': sha(raw), 'raw_body_file': raw_path.name,
                      'body': body, 'seconds': round(time.monotonic() - began, 3), 'recorded_at_unix': time.time()}
            save(path, result)
        if result['http_status'] != 200:
            raise RuntimeError(f"HTTP {result['http_status']}; receipt saved, no retry: {path}")
        return result['body'], path.name


def blocks(record):
    text = record['text']
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    segments = record.get('metadata', {}).get('verse_segments') or []
    ranges = []
    for segment in segments:
        start, end = offsets[segment['start_line_index']], offsets[segment['end_line_index_exclusive']]
        if ranges and ranges[-1]['end'] == start:
            ranges[-1]['end'] = end
        else:
            ranges.append({'start': start, 'end': end})
    if not ranges:
        raise ValueError('No source-defined verse segments: ' + record['id'])
    return ranges


def chunks(text, max_words=MAX_WORDS):
    """Line boundaries avoid splitting printed editorial words between requests."""
    result, start, end, count = [], 0, 0, 0
    for line in text.splitlines(keepends=True):
        words = sum(t['kind'] == 'word' for t in tokenize_span(text, end, end + len(line)))
        if words > max_words or len(line) > MAX_CHARACTERS:
            raise ValueError('A line exceeds the request bound; explicit boundary review required')
        if count and (count + words > max_words or end + len(line) - start > MAX_CHARACTERS):
            result.append((start, end))
            start, count = end, 0
        count += words
        end += len(line)
    if count:
        result.append((start, end))
    if any(b-a > MAX_CHARACTERS for a,b in result):
        raise ValueError('Leading editorial-only material exceeds the request bound; explicit boundary review required')
    return result


def barrier(text, tokens, start, end):
    selected = text[start:end]
    reasons = []
    if any(c in '[]<>⟨⟩⟦⟧†‡…\u0323' for c in selected):
        reasons.append('editorial_marks_or_uncertain_letters')
    if re.search(r'(?:\.\s*){2,}', selected):
        reasons.append('lacuna_dots')
    if any(t.get('editorial_fragment') or t.get('partial_word') for t in tokens):
        reasons.append('interrupted_printed_word')
    if (start and text[start-1] in '[]<>⟨⟩⟦⟧') or (end < len(text) and text[end] in '[]<>⟨⟩⟦⟧'):
        reasons.append('bracket_boundary')
    return reasons


def feature_coverage(features):
    """Conservative completeness policy; missing POS/verb subtype stays unknown.

    This only measures supplied feature fields. It never verifies their values.
    Categories follow the existing interlinear canonical feature adapter.
    """
    pos, vf = features.get('POS'), features.get('VerbForm')
    all_fields = {'Case', 'Gender', 'Number', 'Person', 'Tense', 'Mood', 'Voice', 'VerbForm'}
    conditional = set()
    if pos == 'PRON':
        # Gender is not universally marked on personal pronouns. The adapter
        # does not preserve enough subtype detail to require Gender or Person.
        required, conditional, category = {'Case', 'Number'}, {'Gender', 'Person'}, 'pronoun'
    elif pos in {'NOUN', 'PROPN', 'ADJ', 'DET'}:
        required, category = {'Case', 'Gender', 'Number'}, 'nominal'
    elif pos in {'VERB', 'AUX'}:
        if vf == 'Part':
            required, category = {'VerbForm', 'Case', 'Gender', 'Number', 'Tense', 'Voice'}, 'participle'
        elif vf == 'Inf':
            required, category = {'VerbForm', 'Tense', 'Voice'}, 'infinitive'
        elif vf == 'Fin' or features.get('Mood'):
            required, category = {'Person', 'Number', 'Tense', 'Mood', 'Voice'}, 'finite_verb'
        else:
            return {'status': 'unknown_verb_subtype', 'present': sorted(features), 'missing': ['VerbForm_or_Mood'], 'not_applicable': []}
    elif pos in {'ADV', 'ADP', 'CCONJ', 'SCONJ', 'PART', 'INTJ'}:
        required, category = set(), 'uninflected'
    else:
        return {'status': 'unknown_pos', 'present': sorted(features), 'missing': ['POS'], 'not_applicable': []}
    return {'status': 'complete_fields' if required <= features.keys() else 'incomplete_fields',
            'category': category, 'present': sorted(features), 'required': sorted(required),
            'missing': sorted(required - features.keys()), 'not_applicable': sorted(all_fields - required - conditional),
            'conditional_applicability_unresolved': sorted(conditional - features.keys()),
            'semantic_accuracy': 'not_verified'}


def candidate_summary(candidate, token, family):
    forms = [candidate.get(k) for k in ('matched_form', 'matched_object_form', 'form', 'attested_form')]
    forms += candidate.get('matched_form_variants') or []
    matched = any(unicodedata.normalize('NFC', str(f)) == unicodedata.normalize('NFC', token['text']) for f in forms if f)
    claims = candidate.get('claim_ids') or []
    exact_claims = [cid for cid in claims if token.get('claim_applications', {}).get(cid, {}).get('scope') == 'exact_token_span']
    rejected = (candidate.get('quarantined') or candidate.get('source_consistent') is False
                or candidate.get('source_inconsistent') or candidate.get('assertion_type') == 'model_inference'
                or any(re.search(r'quarantin|inconsisten|rejected|needs_review|machine_proposed', str(candidate.get(k, '')), re.I)
                       for k in ('status', 'quality', 'link_status', 'lemma_link_status')))
    features = canonical_features(candidate)
    return {'id': candidate.get('id'), 'family': family, 'lemma': candidate.get('lemma'),
            'match_kind': candidate.get('match_kind'), 'edit_distance': candidate.get('edit_distance'),
            'source_forms': [f for f in forms if f], 'exact_surface_match': matched,
            'exact_surface_eligible': bool(matched and not rejected and candidate.get('edit_distance', 0) in (0, None)),
            'exact_occurrence_claim_ids': exact_claims, 'features': features,
            'feature_coverage': feature_coverage(features),
            'claim_ids': claims, 'assertion_type': candidate.get('assertion_type'),
            'source_scope': candidate.get('source_scope'), 'explanation': candidate.get('explanation'),
            'source_gloss': candidate.get('gloss'), 'dictionary_senses_status': candidate.get('dictionary_senses_status'),
            'semantic_accuracy': 'not_verified'}


def occurrence(record, token, display, syntax, response_file, chunk):
    candidates = [candidate_summary(c, token, family) for family in ('source_candidates', 'contextual_candidates') for c in token.get(family, [])]
    machine = [candidate_summary(c, token, 'cached_machine') for c in token.get('machine', {}).get('machine_candidates', [])]
    identities = [json.dumps([c['lemma'], c['features'], c['source_scope']], sort_keys=True) for c in candidates + machine]
    candidate_ids = [c['id'] for c in candidates + machine if c.get('id')]
    gloss = display.get('gloss') or {}
    alternatives = display.get('candidate_meanings') or []
    literal_senses = {sense['id'] for candidate in alternatives
                      for sense in (candidate.get('gloss') or {}).get('alternatives', [])
                      if sense.get('id') and sense.get('text') and sense.get('source_url')
                      and sense.get('language') in ('en', 'eng', 'English')}
    linked_paths = [candidate for candidate in alternatives if candidate.get('linked_path')]
    line_start = record['text'].rfind('\n', 0, token['start']) + 1
    line_end = record['text'].find('\n', token['end'])
    if line_end == -1:
        line_end = len(record['text'])
    row = {'occurrence_id': f"{record['id']}@{token['start']}:{token['end']}", 'passage_id': record['id'],
           'text': token['text'], 'start': token['start'], 'end': token['end'],
           'start_utf16': token['start_utf16'], 'end_utf16': token['end_utf16'],
           'verse': any(b['start'] <= token['start'] and token['end'] <= b['end'] for b in blocks(record)),
           'source_exact': record['text'][token['start']:token['end']] == token['text'],
           'source_text_sha256': sha(record['text']), 'selected_span_sha256': sha(record['text'][chunk[0]:chunk[1]]),
           'response_file': response_file, 'api_token_id': token['id'],
           'editorial_fragment': bool(token.get('editorial_fragment')), 'partial_word': bool(token.get('partial_word')),
           'damaged_piece': bool(token.get('damaged_piece')),
           'editorial_barriers': barrier(record['text'], [token], token['start'], token['end']),
           'source_line': record['text'][line_start:line_end],
           'source_line_editorial_barriers': barrier(record['text'], [], line_start, line_end),
           'philological_integrity': 'not_independently_verified',
           'candidates': candidates, 'cached_machine_candidates': machine,
           'machine_status': token.get('machine', {}).get('status'),
           'claim_applications': token.get('claim_applications') or {},
           'structured_claims': token.get('structured_evidence', {}).get('claims') or [],
           'contextual_supporting_claims': token.get('contextual_supporting_claims') or [],
           'display': display, 'syntax_prediction': syntax,
           'display_feature_coverage': feature_coverage(display.get('features') or {}),
           'display_gloss_available': bool(gloss.get('text')),
           'gloss_unavailability_reason': None if gloss.get('text') else gloss.get('selection_basis', 'not_reported'),
           'alternative_glosses_available': sum(bool(a.get('gloss', {}).get('text')) for a in alternatives),
           'literal_sense_alternatives': len(literal_senses),
           'linked_candidate_paths': len(linked_paths),
           'lexicon_entry_count': len(token.get('lexicon_entries') or []),
           'candidate_duplicate_count': len(candidate_ids) - len(set(candidate_ids)),
           'repeated_canonical_feature_signatures': len(identities) - len(set(identities)),
           'variant_explanations': [c for c in candidates if c.get('explanation') or c.get('source_scope')],
           'semantic_accuracy': 'not_verified', 'warnings': token.get('warnings') or []}
    return row


def catalog(record, words, context):
    text = record['text']
    for block_index, block in enumerate(blocks(record)):
        in_block = [w for w in words if block['start'] <= w['start'] and w['end'] <= block['end']]
        for i, first in enumerate(in_block):
            for j in range(i, len(in_block)):
                last = in_block[j]
                a, b = first['start'], last['end']
                yield {'passage_id': record['id'], 'verse_block': block_index, 'start': a, 'end': b,
                       'start_utf16': utf16_offset(text, a), 'end_utf16': utf16_offset(text, b),
                       'selected_text_sha256': sha(text[a:b]), 'word_segments': j-i+1,
                       'editorial_barriers': barrier(text, in_block[i:j+1], a, b),
                       'api_bounded': j-i+1 <= MAX_WORDS and b-a <= MAX_CHARACTERS,
                       'api_requested_for_this_exact_span': False,
                       'context_translation_count': len(context.get('published_translations') or []),
                       'selection_translation_coverage': 'not_individually_tested',
                       'semantic_accuracy': 'not_verified'}


def priority_cases(rows):
    cases = []
    for row in rows:
        reasons = []
        if not row['source_exact']:
            reasons.append(('P0', 'source_slice_mismatch'))
        if row['editorial_fragment'] or row['partial_word']:
            if row['display_gloss_available'] or row['display'].get('lemma'):
                reasons.append(('P0', 'editorial_fragment_asserted_reading'))
            continue_if_no_error = not reasons
            if continue_if_no_error:
                continue
        else:
            if not row['display_gloss_available']:
                reasons.append(('P1', 'no_selected_english_gloss'))
            if row['display_feature_coverage']['status'] != 'complete_fields':
                reasons.append(('P1', 'incomplete_display_parse'))
            if row['display'].get('syntax_conflict'):
                reasons.append(('P1', 'source_parser_conflict'))
            if not any(c['exact_surface_eligible'] for c in row['candidates']):
                reasons.append(('P2', 'no_exact_surface_source_candidate'))
        if row['candidate_duplicate_count']:
            reasons.append(('P3', 'repeated_candidate_identities'))
        for priority, reason in reasons:
            cases.append({'priority': priority, 'reason': reason, 'occurrence_id': row['occurrence_id'],
                          'text': row['text'], 'selection_basis': row['display'].get('selection_basis'),
                          'feature_coverage': row['display_feature_coverage'], 'response_file': row['response_file']})
    return sorted(cases, key=lambda r: (r['priority'], r['occurrence_id'], r['reason']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, default=ROOT/'runtime/campbell-assignment/campbell_assignment.jsonl')
    parser.add_argument('--base', default='https://greeklyric.com')
    parser.add_argument('--output', type=Path, default=ROOT/'runtime/alcaeus-occurrences/baseline')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--max-words', type=int, default=80)
    args = parser.parse_args()
    if not 1 <= args.max_words <= MAX_WORDS:
        parser.error('--max-words must be 1..80')
    records = [json.loads(line) for line in args.records.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if len(records) != 5 or any(not r['id'].startswith('campbell-glp:alcaeus:') for r in records):
        raise ValueError('Expected exactly the five Campbell Alcaeus records')
    args.output.mkdir(parents=True, exist_ok=True)
    api = Receipts(args.base, args.output/'responses', offline=args.offline)
    save(args.output/'manifest.json', {'source_file': str(args.records), 'source_sha256': sha(args.records.read_bytes()),
         'script_sha256': sha(Path(__file__).read_bytes()),
         'local_module_sha256': {name: sha((ROOT/name).read_bytes()) for name in ('backend/passage_analysis.py', 'backend/interlinear.py')},
         'base': args.base, 'started_at_unix': time.time(),
         'rerank': False, 'fetch_machine': False, 'semantic_accuracy': 'not_verified',
         'scope': 'Every source word segment occurrence; every contiguous verse-block word-boundary span cataloged'})
    summaries, rows, all_spans = [], [], []
    status, status_receipt = api.call('/api/passage-analysis/status')
    for record in records:
        text = record['text']
        passage, passage_receipt = api.call('/api/passage', {'id': record['id']})
        if passage.get('text') != text:
            raise ValueError('Live source mismatch: ' + record['id'])
        words = [t for t in tokenize_span(text, 0, len(text)) if t['kind'] == 'word']
        chunk_summaries, record_rows, context = [], [], {}
        for a, b in chunks(text, args.max_words):
            payload = {'version': 1, 'passage_id': record['id'], 'start': a, 'end': b,
                       'offset_unit': 'codepoint', 'selected_text': text[a:b], 'rerank': False, 'fetch_machine': False}
            body, receipt = api.call('/api/analyze-passage', payload=payload)
            if (body.get('passage', {}).get('text_sha256') != sha(text)
                    or body.get('selection', {}).get('text') != text[a:b]
                    or (body.get('selection', {}).get('start'), body.get('selection', {}).get('end')) != (a,b)
                    or ''.join(t['text'] for t in body.get('tokens', [])) != text[a:b]
                    or body.get('limits', {}).get('machine_fetches') != 0
                    or body.get('ranking', {}).get('status') != 'not_requested'
                    or body.get('sense_ranking', {}).get('status') != 'not_requested'):
                raise ValueError('Source or no-fetch contract failed: ' + receipt)
            for token in body['tokens']:
                if (text[token['start']:token['end']] != token['text']
                        or token['start_utf16'] != utf16_offset(text, token['start'])
                        or token['end_utf16'] != utf16_offset(text, token['end'])):
                    raise ValueError('Token offsets failed: ' + receipt)
            displays = {t['id']: t for reading in body.get('interlinear', {}).get('readings', []) for t in reading.get('tokens', [])}
            syntax = {(t.get('absolute_start'), t.get('absolute_end')): t for t in body.get('syntax', {}).get('tokens', [])}
            for token in body['tokens']:
                if token['kind'] == 'word':
                    record_rows.append(occurrence(record, token, displays.get(token['id'], {}), syntax.get((token['start'], token['end'])), receipt, (a,b)))
            context = body.get('context') or {}
            chunk_summaries.append({'start': a, 'end': b, 'selected_text_sha256': sha(text[a:b]), 'response_file': receipt,
                                    'meaning': body.get('meaning'), 'context': context, 'limits': body.get('limits'),
                                    'syntax_status': body.get('syntax', {}).get('state', body.get('syntax', {}).get('status'))})
            print(f"{record['id']} {a}:{b}: {len(record_rows)}/{len(words)} occurrences", flush=True)
        expected = [(w['start'], w['end'], w['text']) for w in words]
        observed = [(w['start'], w['end'], w['text']) for w in record_rows]
        if observed != expected:
            raise ValueError('Occurrence omission/duplication/tokenizer mismatch: ' + record['id'])
        rows.extend(record_rows)
        spans = list(catalog(record, words, context))
        requested = {(c['start'], c['end']): c for c in chunk_summaries}
        for span in spans:
            if (span['start'], span['end']) in requested:
                span['api_requested_for_this_exact_span'] = True
                span['selection_translation_coverage'] = requested[(span['start'], span['end'])]['meaning']['status']
        all_spans.extend(spans)
        summaries.append({'passage_id': record['id'], 'source_sha256': sha(text), 'passage_receipt': passage_receipt,
                          'word_occurrences': len(words), 'verse_blocks': blocks(record), 'span_catalog_count': len(spans),
                          'chunks': chunk_summaries})
        save(args.output/'occurrences.json', rows)
        save(args.output/'records.json', summaries)
    with (args.output/'span-catalog.jsonl').open('w', encoding='utf-8') as stream:
        for span in all_spans:
            stream.write(json.dumps(span, ensure_ascii=False) + '\n')
    cases = priority_cases(rows)
    save(args.output/'priority-cases.json', cases)
    intact = [r for r in rows if not r['editorial_fragment'] and not r['partial_word'] and not r.get('damaged_piece')]
    analyzed_chunks = [c for record_summary in summaries for c in record_summary['chunks']]
    summary = {'records': len(records), 'word_occurrences': len(rows), 'verse_word_occurrences': sum(r['verse'] for r in rows),
               'counting_unit': 'source tokenizer word segment, including separately preserved pieces of interrupted printed words',
               'intact_word_occurrences': len(intact), 'api_unflagged_word_segments': len(intact),
               'editorial_fragment_occurrences': sum(r['editorial_fragment'] for r in rows),
               'damaged_piece_occurrences': sum(bool(r.get('damaged_piece')) for r in rows),
               'source_exact_occurrences': sum(r['source_exact'] for r in rows),
               'intact_with_exact_surface_source_candidates': sum(any(c['exact_surface_eligible'] for c in r['candidates']) for r in intact),
               'intact_with_occurrence_aligned_claims': sum(any(c['exact_occurrence_claim_ids'] for c in r['candidates']) for r in intact),
               'any_occurrence_aligned_claim_applications': sum(any(a.get('scope') == 'exact_token_span' for a in r['claim_applications'].values()) for r in intact),
               'intact_with_display_gloss': sum(r['display_gloss_available'] for r in intact),
               'intact_with_any_candidate_gloss': sum(r['display_gloss_available'] or r['alternative_glosses_available'] > 0 for r in intact),
               'unflagged_with_literal_sense_inventory': sum(r['literal_sense_alternatives'] > 0 for r in intact),
               'unflagged_with_linked_dictionary_paths': sum(r['linked_candidate_paths'] > 0 for r in intact),
               'display_feature_statuses': dict(Counter(r['display_feature_coverage']['status'] for r in intact)),
               'display_conditional_feature_applicability_unresolved': sum(bool(r['display_feature_coverage'].get('conditional_applicability_unresolved')) for r in intact),
               'selection_bases': dict(Counter(r['display'].get('selection_basis', 'missing') for r in intact)),
               'gloss_unavailability_reasons': dict(Counter(r['gloss_unavailability_reason'] for r in intact if not r['display_gloss_available'])),
               'syntax_conflicts': sum(bool(r['display'].get('syntax_conflict')) for r in intact),
               'repeated_candidate_identities': sum(r['candidate_duplicate_count'] for r in rows),
               'repeated_canonical_feature_signatures': sum(r['repeated_canonical_feature_signatures'] for r in rows),
               'span_catalog_count': len(all_spans), 'bounded_spans': sum(s['api_bounded'] for s in all_spans),
               'editorial_barrier_spans': sum(bool(s['editorial_barriers']) for s in all_spans),
               'individually_requested_catalog_spans': sum(s['api_requested_for_this_exact_span'] for s in all_spans),
               'analysis_requests': len(analyzed_chunks),
               'analysis_chunks_with_context_translations': sum(bool(c['context'].get('published_translations')) for c in analyzed_chunks),
               'analysis_chunks_with_published_commentary': sum(bool(c['context'].get('published_commentary') or c['context'].get('commentary')) for c in analyzed_chunks),
               'analysis_chunks_with_other_edition_comparisons': sum((c['context'].get('translation_comparisons') or {}).get('status') == 'available' for c in analyzed_chunks),
               'analysis_chunks_with_selection_interpretations': sum(bool(c['meaning'].get('interpretations')) for c in analyzed_chunks),
               'service_status_receipt': status_receipt, 'service_declared_meaning_capabilities': status.get('meaning'),
               'priority_counts': dict(Counter(c['reason'] for c in cases)),
               'semantic_accuracy': 'not_verified', 'gold_occurrence_accuracy_score': None,
               'limitations': ['Exact-surface candidates and complete feature fields are not verified occurrence analyses.',
                              'A catalog entry records selectable boundaries, not tested or accurate meaning.',
                              'Published context translations do not establish a selected-span translation.',
                              'Intact means API-unflagged, not independently confirmed philological completeness; spaced lacunae can leave partial printed fragments unflagged.',
                              'Editorial fragments are preserved without inventing restored words.',
                              'Feature completeness is conservative; pronoun subtype-specific gender applicability is unresolved.']}
    save(args.output/'summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
