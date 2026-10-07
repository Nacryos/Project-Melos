"""Bounded, network-disabled profiling of existing source-word lookups.

Run only in an isolated diagnostic process, not by patching a serving worker.
The passage must match the caller's approved text hash. No model, morphology
fetch, corpus edit, or source assertion is made. Output is diagnostic metadata.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def forbid_network(*args, **kwargs):
    raise RuntimeError('Outbound network is disabled during this diagnostic')


def select_forms(record, count):
    from backend.passage_analysis import tokenize_span
    from backend.lacuna_boundaries import annotate_lacuna_boundaries, intact_word_eligible
    offsets = [0]
    for line in record['text'].splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    segments = record.get('metadata', {}).get('verse_segments')
    if not isinstance(segments, list) or not segments:
        raise ValueError('Explicit source verse boundaries are required.')
    selected = []
    for segment in segments:
        a, b = segment['start_line_index'], segment['end_line_index_exclusive']
        if not (type(a) is int and type(b) is int and 0 <= a < b < len(offsets)):
            raise ValueError('Invalid source verse boundaries.')
        # This diagnostic's caller permits only the five hash-bound Campbell
        # critical texts. Dot-adjacent letters are not certified whole words.
        tokens = annotate_lacuna_boundaries(record['text'],
            tokenize_span(record['text'], offsets[a], offsets[b]), source_critical=True)
        for token in tokens:
            if not intact_word_eligible(token):
                continue
            if token['text'] not in selected:
                selected.append(token['text'])
            if len(selected) == count:
                return selected
    return selected


def top_stats(profiler, limit=40):
    rows = []
    for (filename, line, name), (primitive, total, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
        path = Path(filename)
        rows.append({'file': path.name, 'line': line, 'function': name,
                     'primitive_calls': primitive, 'total_calls': total,
                     'own_seconds': own, 'cumulative_seconds': cumulative})
    return sorted(rows, key=lambda row: -row['cumulative_seconds'])[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--passage-id', required=True, choices=[
        'campbell-glp:alcaeus:' + fragment for fragment in ('34a', '129', '130b', '326', '350')])
    parser.add_argument('--text-sha256', required=True)
    parser.add_argument('--count', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.count <= 10:
        parser.error('The diagnostic permits 1–10 distinct exact source forms.')
    with patch.object(socket.socket, 'connect', forbid_network), patch.object(socket.socket, 'connect_ex', forbid_network):
        from backend import server
        with server.connect() as connection:
            row = connection.execute('SELECT data FROM passages WHERE id=?', (args.passage_id,)).fetchone()
        if not row:
            raise RuntimeError('Approved passage is absent; no substitute is permitted.')
        record = json.loads(row['data'])
        source_hash = hashlib.sha256(record['text'].encode()).hexdigest()
        if source_hash != args.text_sha256:
            raise RuntimeError('Source text hash differs from the approved caller value.')
        forms = select_forms(record, args.count)
        if not forms:
            raise RuntimeError('No intact source words to profile.')
        # Warm exactly this bounded set first; distinguish process/index startup
        # from the second-pass lookup profile. No results are persisted as data.
        start = time.perf_counter()
        for form in forms:
            server.word(form, args.passage_id)
        warmup = time.perf_counter() - start
        profiler = cProfile.Profile()
        timings = []
        for form in forms:
            start = time.perf_counter()
            result = profiler.runcall(server.word, form, args.passage_id)
            elapsed = time.perf_counter() - start
            encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
            timings.append({'form': form, 'seconds': elapsed, 'response_bytes': len(encoded),
                            'response_sha256': hashlib.sha256(encoded).hexdigest(),
                            'source_candidates': len(result.get('candidates', []))})
        print(json.dumps({'schema': 'melos-isolated-word-profile-v1', 'passage_id': args.passage_id,
                          'source_text_sha256': source_hash, 'warmup_seconds': warmup,
                          'forms': timings, 'profile': top_stats(profiler),
                          'backend_module_sha256': {
                              name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                              for name in ('backend.server', 'backend.morphology',
                                           'backend.lexicon_render', 'backend.lexicon_senses')
                              if (module := sys.modules.get(name)) is not None},
                          'limits': {'max_distinct_forms': 10, 'network': 'disabled',
                                     'paid_calls': 0, 'parser_fetches': 0},
                          'interpretation': 'Second-pass diagnostic process timings, not production HTTP latency.'},
                         ensure_ascii=False))


if __name__ == '__main__':
    main()
