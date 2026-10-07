"""Isolated, source-receipted rare-form experiment; no corpus writes.

Acquire passages, freeze sampling, acquire browser-observed morphology, prepare
blind requests, then explicitly authorize the exact frozen plan for paid calls.
No request is retried automatically. Judgments are provisional, never gold.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sqlite3
import sys
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, build_opener

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize
from scripts.jev_perseus_pilot_extract import candidates, norm, text_record
from scripts.jev_perseus_pilot_run import ENDPOINT, MODEL, INSTRUCTIONS, NoRedirect

OUT = ROOT / 'data/experiments/jev-perseus-blind12-20261005'
SEED = 20261005
MAX_CALLS = 48
ARMS = ('greek_context', 'translation_context')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def read(path):
    return json.loads(path.read_bytes())


def save(path, value, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = encode(value)
    if immutable and path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Frozen artifact already exists: {path}')
        return sha(raw)
    with path.open('xb' if immutable else 'wb') as stream:
        stream.write(raw)
    return sha(raw)


def safe_id(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
        raise ValueError('IDs must be alphanumeric with underscores or hyphens')
    return value


def validate_source_url(url, kind):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != 'www.perseus.tufts.edu':
        raise ValueError('Only HTTPS www.perseus.tufts.edu source URLs are allowed')
    if parts.path != '/hopper/' + kind or parts.username or parts.password:
        raise ValueError('Unexpected source endpoint')
    return parse_qs(parts.query)


def fetch(out, name, url, *, cache_file=None, captured_at=None,
          capture_type=None, referer=None):
    """Append receipts for successes and failures; cached browser DOM is explicit."""
    safe_id(name)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    raw_path = out / 'raw' / f'{name}_{stamp}.html'
    meta_path = raw_path.with_suffix('.meta.json')
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {'requested_url': url, 'started_utc': now(), 'raw_path': str(raw_path),
            'status': 'pending', 'capture_type': 'direct_http'}
    save(meta_path, meta, immutable=True)
    try:
        if cache_file:
            if not captured_at or capture_type not in ('browser_dom', 'browser_dom_fragment', 'browser_response'):
                raise ValueError('Cached capture needs timestamp and explicit browser capture type')
            datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
            raw = cache_file.read_bytes()
            if cache_file.suffix.lower() == '.json':
                cached = json.loads(raw)
                if cached['url'] != url or cached['captured_at'] != captured_at:
                    raise ValueError('Cached JSON URL/timestamp differs from acquisition arguments')
                meta.update(cached_json_sha256=sha(raw), cached_json_path=str(cache_file.resolve()))
                raw = cached['html'].encode('utf-8')
            meta.update(status=200, capture_type=capture_type, captured_at=captured_at,
                        cache_path=str(cache_file.resolve()), effective_url=url,
                        preserved_response_body=capture_type == 'browser_response')
        else:
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0',
                                    **({'Referer': referer} if referer else {})}, timeout=20)
            raw = response.content
            meta.update(status=response.status_code, effective_url=response.url,
                        response_headers=dict(response.headers), preserved_response_body=True)
        raw_path.write_bytes(raw)
        meta.update(sha256=sha(raw), bytes=len(raw))
        save(meta_path, meta)
        if meta['status'] != 200:
            raise RuntimeError(f"Source returned HTTP {meta['status']}")
        return BeautifulSoup(raw.decode('utf-8') if cache_file else raw, 'html.parser'), meta
    except Exception as exc:
        meta.update(error_type=type(exc).__name__, error=str(exc), completed_utc=now())
        save(meta_path, meta)
        raise


def source_occurrences(soup, source_url, passage_id):
    text = soup.select_one('.text_container > .text')
    if text is None:
        raise ValueError('No Greek text container')
    documents = re.findall(r"addDocument\('([^']+)'\)", str(soup))
    rows = []
    for index, link in enumerate(text.select('a[href^="morph?"]')):
        match = re.search(r'm\(this,(-?\d+),(\d+)\)', link.get('onclick', ''))
        if not match:
            raise ValueError('Missing exact occurrence onclick')
        which, doc_index = map(int, match.groups())
        doc = documents[doc_index]
        target = norm(link)
        # Unicode canonical composition/counting follows UAX #15; no transliteration.
        nfc = unicodedata.normalize('NFC', target)
        greek_letters = sum(unicodedata.category(c).startswith('L') and
                            'GREEK' in unicodedata.name(c, '') for c in nfc)
        rows.append({'id': f'{passage_id}-{index:04d}', 'passage_id': passage_id,
                     'target': target, 'target_nfc': nfc, 'greek_letters': greek_letters,
                     'word_index_zero_based': index, 'word_occurrence_i': which,
                     'source_doc': doc, 'source_href': link['href'],
                     'source_onclick': link['onclick'],
                     'source_link_query': parse_qs(urlsplit(link['href']).query),
                     'source_url': source_url})
    if not rows:
        raise ValueError('No source word links')
    return rows


def acquire_passage(args):
    if (args.out / 'sampling_freeze.json').exists():
        raise ValueError('Cannot change passage pool after sampling freeze')
    safe_id(args.passage_id)
    validate_source_url(args.url, 'text')
    path = args.out / 'passages' / (args.passage_id + '.json')
    if path.exists():
        raise ValueError('Passage already acquired')
    soup, meta = fetch(args.out, args.passage_id + '_greek', args.url,
                       cache_file=args.cache_file, captured_at=args.captured_at,
                       capture_type=args.capture_type)
    greek = text_record(soup, meta)
    links = [{'url': urljoin(args.url, a['href']), 'source_label': norm(a.parent)}
             for a in soup.select('a[href]') if a.get_text(strip=True) == 'focus'
             and 'English' in norm(a.parent)]
    passage = {'id': args.passage_id, 'greek': greek, 'greek_receipt': meta,
               'occurrences': source_occurrences(soup, args.url, args.passage_id),
               'english_links': links, 'translation': None,
               'translation_status': 'not_acquired'}
    save(path, passage, immutable=True)
    print(json.dumps({'passage_id': args.passage_id, 'occurrences': len(passage['occurrences']),
                      'english_links': links}, ensure_ascii=False))


def acquire_translation(args):
    if (args.out / 'sampling_freeze.json').exists():
        raise ValueError('Translation acquisition must precede sampling freeze')
    path = args.out / 'passages' / (safe_id(args.passage_id) + '.json')
    passage = read(path)
    if passage['translation']:
        raise ValueError('Translation already acquired')
    if args.url not in {x['url'] for x in passage['english_links']}:
        raise ValueError('Translation URL was not discovered in Greek source')
    validate_source_url(args.url, 'text')
    soup, meta = fetch(args.out, args.passage_id + '_english', args.url,
                       cache_file=args.cache_file, captured_at=args.captured_at,
                       capture_type=args.capture_type, referer=passage['greek']['source_url'])
    translation = text_record(soup, meta)
    greek_range = passage['greek']['citation_uri'].rsplit(':', 1)[-1]
    english_range = translation['citation_uri'].rsplit(':', 1)[-1]
    # Ranges alone do not prove work identity; source parallel link supplies pairing.
    aligned = greek_range == english_range
    translation.update(context_scope=english_range,
                       edition_alignment_status='Source-linked parallel edition; identical CTS range'
                       if aligned else 'Source-linked edition with unequal CTS range; excluded')
    passage.update(translation=translation, translation_receipt=meta,
                   translation_status='paired' if aligned else 'range_mismatch')
    save(path, passage)
    print(json.dumps({'passage_id': args.passage_id, 'translation_status': passage['translation_status']}))


def frequency_counts(corpus, occurrences):
    """Indexed search-key lookup, then exact NFC comparison; database opened ro."""
    keys = sorted({normalize(x['target']) for x in occurrences})
    exact = {x['target_nfc']: 0 for x in occurrences}
    folded = {key: 0 for key in keys}
    with sqlite3.connect(corpus.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            rows = conn.execute('SELECT form, normalized, SUM(count) FROM tokens WHERE normalized IN (' +
                                ','.join('?' for _ in chunk) + ') GROUP BY form, normalized', chunk)
            for form, key, count in rows:
                folded[key] += count
                nfc = unicodedata.normalize('NFC', form)
                if nfc in exact:
                    exact[nfc] += count
        metadata = dict(conn.execute('SELECT key,value FROM metadata'))
    return exact, folded, metadata


def choose(occurrences, per_passage=4, seed=SEED):
    """Lowest quartile of unique NFC forms, inclusive threshold ties; sample occurrences."""
    eligible_base = [x for x in occurrences if x['greek_letters'] >= 5
                     and x['word_index_zero_based'] >= 50]
    forms = {x['target_nfc']: x['corpus_exact_nfc_count'] for x in eligible_base}
    if not forms:
        raise ValueError('No eligible forms')
    counts = sorted(forms.values())
    cutoff = counts[max(0, math.ceil(len(counts) * .25) - 1)]
    eligible = [x for x in eligible_base if x['corpus_exact_nfc_count'] <= cutoff]
    if len(eligible) < per_passage:
        raise ValueError('Fewer than four rare eligible occurrences; no automatic relaxation')
    ordered = list(eligible)
    random.Random(str(seed) + ':' + occurrences[0]['passage_id']).shuffle(ordered)
    return eligible, ordered[:per_passage], ordered[per_passage:], cutoff


def freeze(args):
    if (args.out / 'sampling_freeze.json').exists():
        raise ValueError('Sampling is already frozen')
    if (args.out / 'morphology').exists() or (args.out / 'frozen_plan.json').exists():
        raise ValueError('Candidate inspection artifacts precede freeze')
    paths = sorted((args.out / 'passages').glob('*.json'))
    if len(paths) != 3:
        raise ValueError('Exactly three acquired source passages required')
    passages = [read(p) for p in paths]
    if any(p['translation_status'] != 'paired' for p in passages):
        raise ValueError('All three passages require source-linked, range-matched English')
    occurrences = [o.copy() for p in passages for o in p['occurrences']]
    exact, folded, metadata = frequency_counts(args.corpus, occurrences)
    for occurrence in occurrences:
        occurrence.update(corpus_exact_nfc_count=exact[occurrence['target_nfc']],
                          corpus_folded_count=folded[normalize(occurrence['target'])])
    selected, groups = [], []
    for passage in passages:
        pool = [x for x in occurrences if x['passage_id'] == passage['id']]
        eligible, targets, reserves, cutoff = choose(pool)
        selected.extend(targets)
        groups.append({'passage_id': passage['id'], 'pool': pool, 'eligible': eligible,
                       'cutoff_exact_nfc_count': cutoff, 'selected': targets,
                       'reserve_order_not_automatic_replacements': reserves})
    result = {'frozen_at': now(), 'seed': SEED, 'target_count': len(selected),
              'sampling_unit': 'occurrence; duplicate forms can occur and are disclosed',
              'rarity_definition': 'Within each passage: exclude first 50 linked Greek word occurrences as opening proxy; Greek forms >=5 letters; lowest quartile of unique NFC forms ranked by exact NFC token count in Melos corpus; nearest-rank ceil(N*.25), all cutoff ties included; random occurrence sample without replacement',
              'zero_count_meaning': 'Unattested in this corpus; not established rarity in ancient Greek',
              'corpus': {'path': str(args.corpus.resolve()), 'mode': 'read-only',
                         'size': args.corpus.stat().st_size,
                         'mtime_ns': args.corpus.stat().st_mtime_ns, 'metadata': metadata,
                         'count_policy': 'Exact case-sensitive NFC form, folded search key used only as indexed prefilter; folded count reported separately',
                         'normalization_reference': 'https://www.unicode.org/reports/tr15/'},
              'passage_sha256': {p.name: sha(p.read_bytes()) for p in paths},
              'groups': groups, 'selected': selected,
              'failure_policy': 'Retain every selected occurrence in denominator; no automatic replacement or ambiguity filtering',
              'claims': 'Small predeclared sample; not statistically representative accuracy'}
    digest = save(args.out / 'sampling_freeze.json', result, immutable=True)
    print(json.dumps({'sampling_sha256': digest, 'selected': selected}, ensure_ascii=True))


def frozen(out):
    raw = (out / 'sampling_freeze.json').read_bytes()
    value = json.loads(raw)
    for name, digest in value['passage_sha256'].items():
        if sha((out / 'passages' / name).read_bytes()) != digest:
            raise ValueError('Passage changed after freeze')
    return value, sha(raw)


def journal_morph(out, record):
    """Individual attempt receipts are authoritative; aggregate is rebuildable."""
    directory = out / 'morphology_attempt_receipts'
    # Migrate prior single-case records without losing a failed attempt on cache recovery.
    for path in (out / 'morphology').glob('*.json'):
        old = read(path)
        key = old['id'] + '_' + sha(old['started_utc'].encode())[:16]
        dest = directory / (key + '.json')
        if not dest.exists():
            save(dest, old, immutable=True)
    key = record['id'] + '_' + sha(record['started_utc'].encode())[:16]
    save(directory / (key + '.json'), record)
    save(out / 'morphology_attempts.json', sorted(
        [read(p) for p in directory.glob('*.json')], key=lambda x: x['started_utc']))


def verify_plan_sources(out, plan):
    if plan['model'] != MODEL or plan['endpoint'] != ENDPOINT:
        raise ValueError('Pinned endpoint or model changed after preparation')
    for case in plan['coverage']:
        if case['morphology_sha256'] is not None:
            path = out / 'morphology' / (case['id'] + '.json')
            if sha(path.read_bytes()) != case['morphology_sha256']:
                raise ValueError('Morphology artifact changed after preparation')


def acquire_morph(args):
    freeze_value, freeze_sha = frozen(args.out)
    target = next(x for x in freeze_value['selected'] if x['id'] == args.case_id)
    query = validate_source_url(args.url, 'morph')
    for key, expected in [('d', target['source_doc']), ('i', str(target['word_occurrence_i'])),
                          ('l', target['source_link_query']['l'][0])]:
        if query.get(key) != [expected]:
            raise ValueError(f'Browser-observed URL mismatches frozen occurrence {key}')
    path = args.out / 'morphology' / (safe_id(args.case_id) + '.json')
    if path.exists() and read(path)['status'] == 'success':
        raise ValueError('Successful morphology already captured')
    record = {'id': args.case_id, 'observed_url': args.url, 'sampling_sha256': freeze_sha,
              'started_utc': now(), 'status': 'pending'}
    journal_morph(args.out, record)
    try:
        soup, meta = fetch(args.out, args.case_id + '_morph', args.url,
                           cache_file=args.cache_file, captured_at=args.captured_at,
                           capture_type=args.capture_type, referer=target['source_url'])
        # Browsers insert tbody in table DOM; unwrap only that structural wrapper
        # to match the original HTTP parser's direct-tr contract. No text changes.
        for wrapper in soup.select('.analysis > .lemma > table > tbody'):
            wrapper.unwrap()
        parsed = candidates(soup)
        record.update(status='success', candidates=parsed, receipt=meta,
                      candidate_count=len(parsed),
                      combined_evaluator_table=[[norm(c) for c in row.select('th,td')]
                                                for row in soup.select('#votes table tr')])
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save(path, record)
        journal_morph(args.out, record)
        raise
    save(path, record)
    journal_morph(args.out, record)
    print(json.dumps({'id': args.case_id, 'candidate_count': len(parsed)}))


def clean_options(case_id, parsed):
    order = list(range(len(parsed)))
    random.Random(f'{SEED}:options:{case_id}').shuffle(order)
    mapping, clean = {}, []
    for index in order:
        item = parsed[index]
        opaque = 'o_' + sha(f'{SEED}:{case_id}:{index}:blind'.encode())[:10]
        mapping[opaque] = item['id']
        clean.append({'id': opaque, **{k: item.get(k) for k in ('lemma', 'morphology', 'gloss')}})
    return clean, mapping


def prepare(args):
    sampling, sampling_sha = frozen(args.out)
    cases, plan, private = [], [], []
    for target in sampling['selected']:
        path = args.out / 'morphology' / (target['id'] + '.json')
        morph = read(path) if path.exists() else {'status': 'not_acquired'}
        private.append({'id': target['id'], 'status': morph['status'],
                        'morphology_sha256': sha(path.read_bytes()) if path.exists() else None})
        if morph['status'] != 'success':
            continue
        passage = read(args.out / 'passages' / (target['passage_id'] + '.json'))
        clean, mapping = clean_options(target['id'], morph['candidates'])
        # Exact local link sequence locates the target without duplicating a whole poem.
        index = target['word_index_zero_based']
        sequence = [x['target'] for x in passage['occurrences']]
        context = {'target': target['target'], 'greek_context': passage['greek']['text'],
                   'citation': passage['greek']['citation_uri'],
                   'source_title': passage['greek']['title'],
                   'target_word_index_zero_based': target['word_index_zero_based'],
                   'target_neighbors_before': sequence[max(0, index - 20):index],
                   'target_neighbors_after': sequence[index + 1:index + 21],
                   'translation': {k: passage['translation'][k] for k in
                                   ('text', 'context_scope', 'edition_alignment_status')}}
        cases.append({'id': target['id'], **context, 'candidates': clean})
        for arm in ARMS:
            for direction in ('forward', 'reverse'):
                order = clean if direction == 'forward' else list(reversed(clean))
                state = {k: v for k, v in context.items() if arm == 'translation_context' or k != 'translation'}
                state['candidates'] = order
                criteria = {x['id']: {k: v for k, v in x.items() if k != 'id'} for x in order}
                criteria['none_of_these'] = 'No supplied lemma/morphology fits this occurrence.'
                body = {'model': MODEL, 'state': state, 'questions': {'parse': {
                    'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': criteria}}}
                plan.append({'id': target['id'], 'arm': arm, 'direction': direction,
                             'candidate_mapping': mapping, 'request': body,
                             'request_sha256': sha(encode(body))})
    if not cases:
        raise ValueError('No captured morphology cases')
    if len(plan) > MAX_CALLS:
        raise ValueError('Paid call cap exceeded')
    judge_sha = save(args.out / 'blind_judge_packet.json', {
        'status': 'Provisional blind adjudication inputs; no source scores or model predictions',
        'instructions': 'Return cases with id, acceptable_candidate_ids (opaque IDs, or none_of_these only when no supplied analysis fits), rationale, confidence, correct_option_absent boolean. Accept all linguistically defensible rows. Published translation is passage-scoped, not token-aligned. Empty accepted set means unresolved and is not a wrong prediction. Do not inspect any other experiment artifact.',
        'cases': cases}, immutable=True)
    result = {'sampling_sha256': sampling_sha, 'judge_packet_sha256': judge_sha,
              'created_at': now(), 'model': MODEL, 'endpoint': ENDPOINT,
              'planned_calls': len(plan), 'max_calls': MAX_CALLS,
              'primary_arms': list(ARMS), 'order_controls': ['forward', 'reverse'],
              'coverage': private, 'requests': plan}
    digest = save(args.out / 'frozen_plan.json', result, immutable=True)
    print(json.dumps({'plan_sha256': digest, 'cases': len(cases), 'paid_calls': len(plan),
                      'max_request_characters': max(len(encode(x['request']).decode('utf-8')) for x in plan),
                      'max_request_bytes': max(len(encode(x['request'])) for x in plan)}))


def run(args):
    """Explicit exact-plan authorization; crash reservations consume a call slot."""
    from dotenv import dotenv_values
    plan_raw = (args.out / 'frozen_plan.json').read_bytes()
    plan = json.loads(plan_raw)
    if sha(plan_raw) != args.approved_plan_sha256:
        raise ValueError('Explicit approval hash does not match frozen request plan')
    verify_plan_sources(args.out, plan)
    _, sampling_sha = frozen(args.out)
    if sampling_sha != plan['sampling_sha256']:
        raise ValueError('Sampling freeze changed')
    if sha((args.out / 'blind_judge_packet.json').read_bytes()) != plan['judge_packet_sha256']:
        raise ValueError('Blind judge packet changed')
    values = dotenv_values(args.env_file)
    key = values.get('TYPESAFE_API_KEY') or values.get('JEV_API_KEY')
    if not key:
        raise ValueError('No Jev credential in explicitly supplied env file')
    if len(plan['requests']) > MAX_CALLS:
        raise ValueError('Call cap exceeded')
    receipts = args.out / 'jev_receipts'
    receipts.mkdir(exist_ok=True)
    opener = build_opener(NoRedirect())
    for item in plan['requests']:
        name = '__'.join(item[k] for k in ('id', 'arm', 'direction'))
        path = receipts / (name + '.json')
        if path.exists():
            previous = read(path)
            if previous['request_sha256'] != item['request_sha256']:
                raise ValueError('Existing reservation belongs to different request')
            continue
        if len([p for p in receipts.glob('*.json') if not p.name.endswith('.response.json')]) >= MAX_CALLS:
            raise ValueError('Durable attempt cap reached')
        body = encode(item['request'])
        if sha(body) != item['request_sha256']:
            raise ValueError('Request hash mismatch')
        record = {k: item[k] for k in ('id', 'arm', 'direction', 'request_sha256')}
        record.update(plan_sha256=sha(plan_raw), started_utc=now(), status='reserved')
        save(path, record, immutable=True)
        started = time.perf_counter()
        try:
            request = Request(ENDPOINT, data=body, method='POST', headers={
                'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
            with opener.open(request, timeout=25) as response:
                raw = response.read()
            (receipts / (name + '.response.json')).write_bytes(raw)
            result = json.loads(raw)
            answer = result['answers']['parse']
            probs = answer['probabilities']
            expected = set(item['request']['questions']['parse']['criteria'])
            if set(probs) != expected or not all(isinstance(v, (float, int)) and
                    math.isfinite(v) and 0 <= v <= 1 for v in probs.values()):
                raise ValueError('Invalid returned probability labels or values')
            if abs(sum(probs.values()) - 1) >= .005 or answer['choice'] not in expected:
                raise ValueError('Invalid probability normalization or choice')
            if probs[answer['choice']] < max(probs.values()) - 1e-6:
                raise ValueError('Choice differs from maximum probability')
            record.update(status='success', response=result, response_sha256=sha(raw))
        except HTTPError as exc:
            record.update(status='http_error', http_status=exc.code)
        except Exception as exc:
            record.update(status='error', error_type=type(exc).__name__)
        record['latency_seconds'] = time.perf_counter() - started
        save(path, record)
        print(json.dumps({k: record[k] for k in ('id', 'arm', 'direction', 'status')}), flush=True)


def bounds(top, accepted):
    return {'all_top_ties_accepted': bool(top) and set(top) <= set(accepted),
            'any_top_tie_accepted': bool(set(top) & set(accepted)), 'top_ids': sorted(top)}


def summarize(args):
    sampling, _ = frozen(args.out)
    plan = read(args.out / 'frozen_plan.json')
    verify_plan_sources(args.out, plan)
    judge = read(args.judgments)
    judgments = {x['id']: x for x in judge['cases']}
    packet = read(args.out / 'blind_judge_packet.json')
    allowed = {x['id']: {c['id'] for c in x['candidates']} | {'none_of_these'} for x in packet['cases']}
    for case_id, judgment in judgments.items():
        if case_id not in allowed or not set(judgment['acceptable_candidate_ids']) <= allowed[case_id]:
            raise ValueError('Judgment IDs do not match blind packet')
    baselines, predictions = [], []
    for case in packet['cases']:
        case_id = case['id']
        if case_id not in judgments:
            continue
        accepted = set(judgments[case_id]['acceptable_candidate_ids'])
        if not accepted:
            continue
        mapping = next(x['candidate_mapping'] for x in plan['requests'] if x['id'] == case_id)
        source_accepted = {mapping[x] for x in accepted if x in mapping}
        morph = read(args.out / 'morphology' / (case_id + '.json'))
        for field, label in [('perseus_percent', 'combined_evaluator'), ('user_votes', 'historical_user_votes')]:
            maximum = max(x[field] for x in morph['candidates'])
            top = {x['id'] for x in morph['candidates'] if x[field] == maximum}
            baselines.append({'id': case_id, 'baseline': label, 'maximum': maximum,
                              'evidence_status': 'no_votes_no_empirical_evidence'
                              if field == 'user_votes' and maximum == 0 else 'available',
                              'no_unique_winner': len(top) != 1,
                              **bounds(top, source_accepted)})
    for item in plan['requests']:
        path = args.out / 'jev_receipts' / ('__'.join(item[k] for k in ('id', 'arm', 'direction')) + '.json')
        receipt = read(path) if path.exists() else {'status': 'not_attempted'}
        row = {k: item[k] for k in ('id', 'arm', 'direction')}
        row['status'] = receipt['status']
        accepted = set(judgments.get(item['id'], {}).get('acceptable_candidate_ids', []))
        if receipt['status'] == 'success' and accepted:
            if receipt['request_sha256'] != item['request_sha256']:
                raise ValueError('Receipt request mismatch')
            answer = receipt['response']['answers']['parse']
            probs = answer['probabilities']
            top = {k for k, v in probs.items() if abs(v - max(probs.values())) <= 1e-6}
            row.update(bounds(top, accepted))
            row.update(choice=answer['choice'], choice_accepted=answer['choice'] in accepted,
                       choice_probability=probs[answer['choice']],
                       api_confidence=answer.get('confidence'),
                       top_two_probability_margin=sorted(probs.values(), reverse=True)[0] - sorted(probs.values(), reverse=True)[1],
                       probabilities=probs, model=receipt['response'].get('model'),
                       latency_seconds=receipt.get('latency_seconds'),
                       probability_mass_on_accepted=sum(probs[x] for x in accepted))
        predictions.append(row)
    aggregate = {}
    for label in ('combined_evaluator', 'historical_user_votes'):
        rows = [x for x in baselines if x['baseline'] == label and x['evidence_status'] == 'available']
        aggregate[label] = {'evaluable': len(rows), 'all_ties_accepted': sum(x['all_top_ties_accepted'] for x in rows),
                            'any_tie_accepted': sum(x['any_top_tie_accepted'] for x in rows),
                            'no_evidence_cases': sum(x['baseline'] == label and x['evidence_status'] != 'available' for x in baselines)}
    for arm in ARMS:
        for direction in ('forward', 'reverse'):
            rows = [x for x in predictions if x['arm'] == arm and x['direction'] == direction and 'all_top_ties_accepted' in x]
            aggregate[arm + '_' + direction] = {'evaluable': len(rows),
                'all_ties_accepted': sum(x['all_top_ties_accepted'] for x in rows),
                'any_tie_accepted': sum(x['any_top_tie_accepted'] for x in rows)}
    result = {'status': 'provisional_blind_judge_agreement_not_accuracy',
              'frozen_occurrences': len(sampling['selected']), 'morphology_coverage': plan['coverage'],
              'judge_coverage': len(judgments), 'judge_unresolved': [k for k,v in judgments.items() if not v['acceptable_candidate_ids']],
              'correct_option_absent': [k for k,v in judgments.items() if v.get('correct_option_absent') or v['acceptable_candidate_ids'] == ['none_of_these']],
              'aggregate': aggregate, 'baselines': baselines, 'jev': predictions,
              'judge_sha256': sha(args.judgments.read_bytes()),
              'limitations': ['Purposive pool: whole Pindar Pythian 4 and Bacchylides Ep. 5 poems, plus Odyssey 7.152-197 card; first 50 linked words excluded from each, then random rare eligible occurrences.',
                  'Corpus zero counts indicate non-attestation, not proven linguistic rarity.',
                  'Provisional judge accepted sets are not independent expert gold.',
                  'Source combined scores are not calibrated probabilities; votes are a separate baseline.',
                  'Forward and reverse order are controls, not extra independent occurrences.',
                  'Published translation is full matched passage scope, not token-aligned.',
                  'Missing and unambiguous targets remain in the frozen denominator; no automatic replacement.',
                  'No statistical population accuracy, confidence calibration, or unique source winner claim.']}
    save(args.out / 'summary.json', result, immutable=True)
    print(json.dumps({'aggregate': aggregate, 'frozen_occurrences': len(sampling['selected'])}))


def report(args):
    """Human-readable report derived exclusively from recorded experiment artifacts."""
    summary = read(args.out / 'summary.json')
    sampling, _ = frozen(args.out)
    browser = read(args.out / 'manual_browser_trials.json')
    attempts = read(args.out / 'morphology_attempts.json')
    direct_failures = [x for x in attempts if x['status'] == 'failed']
    successful = [x for x in summary['jev'] if x['status'] == 'success']
    lines = ['Perseus / Jev frozen rare-form trial', '',
             f"Frozen sample: {summary['frozen_occurrences']} occurrences, seed {sampling['seed']}, four per source.",
             'Sources: whole Pindar Pythian 4 and Bacchylides Ep. 5, plus Odyssey 7.152-197.',
             'Rarity: exact-NFC Melos corpus counts, lowest within-source quartile with inclusive ties; first 50 linked words excluded. Corpus absence is not established Greek rarity.',
             f"Manual browser clicks: {browser['manual_clicks']}; {browser['successes']} success and {browser['browser_HTTP_503']} HTTP 503 (parent browser observations).",
             'Direct HTTP failures: ' + ', '.join(f"{label}: {sum(label in x.get('error', '') for x in direct_failures)}" for label in ('HTTP 503', 'HTTP 429', 'timed out')) + '.',
             'The successful browser analysis fragment was mechanically captured and parsed; failed targets were retained, never replaced.',
             f"Evaluable morphology coverage: {sum(x['status'] == 'success' for x in summary['morphology_coverage'])}/{summary['frozen_occurrences']}.",
             f"Paid calls: {len(summary['jev'])}; successful: {len(successful)}. No retries or additional source trials.", '']
    for baseline in summary['baselines']:
        target = next(x['target'] for x in sampling['selected'] if x['id'] == baseline['id'])
        if baseline['evidence_status'] != 'available':
            lines.append(f"{target}: historical user votes: NO VOTES; no empirical voting baseline.")
        else:
            lines.append(f"{target}: Perseus combined displayed top score {baseline['maximum']}%; blind-judge agreement all/any tied maxima: {baseline['all_top_ties_accepted']}/{baseline['any_top_tie_accepted']}. This is not a calibrated probability.")
    for row in summary['jev']:
        if row['status'] != 'success':
            lines.append(f"{row['arm']} / {row['direction']}: {row['status']}")
            continue
        lines.append(f"{row['arm']} / {row['direction']}: accepted={row.get('choice_accepted')}; top probability={row.get('choice_probability')}; API confidence={row.get('api_confidence')}; margin={row.get('top_two_probability_margin', 0):.2f}; latency={row.get('latency_seconds', 0):.3f}s.")
    tokens = {'input_tokens': 0, 'output_tokens': 0}
    for path in (args.out / 'jev_receipts').glob('*.response.json'):
        usage = read(path).get('usage', {})
        for key in tokens:
            tokens[key] += usage.get(key, 0)
    lines += ['', f"Reported API usage: {tokens['input_tokens']} input tokens; {tokens['output_tokens']} output tokens.",
              'Comparison is agreement with one provisional blind model judge, not gold accuracy. Reversed-order calls are repeated controls, not independent cases. The available comparison does not establish a performance advantage.',
              'Correct-option-absent cases reported by judge: ' + str(len(summary['correct_option_absent'])) + '.',
              'No corpus or production annotations were changed.', '', 'Limitations:']
    lines += ['- ' + value for value in summary['limitations']]
    path = args.out / 'human_report.txt'
    raw = ('\n'.join(lines) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'report': str(path), 'sha256': sha(raw), 'usage': tokens}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    sub = parser.add_subparsers(dest='mode', required=True)
    for mode in ('acquire-passage', 'acquire-translation', 'acquire-morph'):
        p = sub.add_parser(mode)
        p.add_argument('--case-id' if mode == 'acquire-morph' else '--passage-id', required=True)
        p.add_argument('--url', required=True)
        p.add_argument('--cache-file', type=Path)
        p.add_argument('--captured-at')
        p.add_argument('--capture-type', choices=['browser_dom', 'browser_dom_fragment', 'browser_response'])
    p = sub.add_parser('freeze')
    p.add_argument('--corpus', type=Path, default=ROOT / 'data/corpus.sqlite')
    sub.add_parser('prepare')
    sub.add_parser('report')
    p = sub.add_parser('run')
    p.add_argument('--env-file', required=True, type=Path)
    p.add_argument('--approved-plan-sha256', required=True)
    p = sub.add_parser('summarize')
    p.add_argument('--judgments', required=True, type=Path)
    args = parser.parse_args()
    {'acquire-passage': acquire_passage, 'acquire-translation': acquire_translation,
     'acquire-morph': acquire_morph, 'freeze': freeze, 'prepare': prepare,
     'run': run, 'summarize': summarize, 'report': report}[args.mode](args)


if __name__ == '__main__':
    main()
