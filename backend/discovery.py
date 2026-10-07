"""Read-only dictionary browsing and bounded, source-spanned discovery.

Dictionary meanings are verified TEI spans. Literary prompts retrieve parents;
they never create annotations or independent embeddings for derived units.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import json
from pathlib import Path
import re
from threading import RLock
import unicodedata

from fastapi import APIRouter, HTTPException, Query

from .morphology import normalize, query_variants
from .publication import publication_restricted, public_deployment, record_allowed

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]
MAX_ENGLISH_CANDIDATES = 256
PARENT_LIMIT = 120
MAX_UNIT_RESULTS = 12000
MAX_CHARACTERS = 1_000_000
CHILD_EMBEDDING_LIMIT = 64
CHILD_PARENT_LIMIT = 16
CHILD_CHARACTER_LIMIT = 800
_LOCK = RLock()
_PARENT_CACHE = OrderedDict()
_CHILD_CACHE = OrderedDict()

THEMES = (
    ('sea_coast', 'Sea & coast', 'aesthetic_annotation', 'sea coast waves shore'),
    ('garden_grove', 'Garden & grove', 'aesthetic_annotation', 'garden grove flowers trees'),
    ('meadow_pasture', 'Meadow & pasture', 'aesthetic_annotation', 'meadow pasture grass flowers'),
    ('mountain_woodland', 'Mountain & woodland', 'aesthetic_annotation', 'mountain woodland forest'),
    ('river_spring', 'River & spring', 'aesthetic_annotation', 'river spring flowing water'),
    ('love', 'Love & desire', 'retrieval_prompt', 'love desire longing beloved'),
    ('unrequited_love', 'Unrequited love', 'retrieval_prompt', 'unrequited love longing rejection beloved'),
    ('politics', 'Politics & the city', 'retrieval_prompt', 'politics civic conflict exile tyranny city'),
    ('sympotic_song', 'Sympotic song', 'retrieval_prompt', 'wine drinking companions symposium song'),
    ('melic_song', 'Song & performance', 'retrieval_prompt', 'song music lyre chorus dance performance'),
    ('war', 'War & courage', 'retrieval_prompt', 'war battle courage warriors'),
    ('memory', 'Memory & time', 'retrieval_prompt', 'memory remembrance time youth old age'),
    ('religion', 'Gods & ritual', 'retrieval_prompt', 'gods prayer ritual worship hymn'),
)
THEME_MAP = {row[0]: row for row in THEMES}
UNIT_METHODS = {
    'passage': 'Stored source record; not an inferred complete poem.',
    'stanza': 'Explicit blank-line-separated source blocks; typographic, not verified metrical stanzas.',
    'line': 'Printed newline-delimited source lines; no reconstructed lineation.',
    'sentence': 'Punctuation-delimited source spans; heuristic, not a grammatical annotation.',
    'phrase': 'Punctuation-delimited clauses; heuristic, not a syntactic annotation.',
    'word': 'Literal written tokens; not dictionary lemmas or resolved parses.',
}


def _signature(path):
    path = Path(path)
    if not path.exists():
        return None
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def _entries_path():
    """Apply the same source acceptance gate as the existing word endpoint."""
    from . import server
    path = server.ROOT / 'data/lexica/entries.jsonl'
    audit_path = server.ROOT / 'data/reports/audit-lexica.json'
    try:
        accepted = json.loads(audit_path.read_text(encoding='utf-8'))['files']['entries.jsonl']
        stat = path.stat()
        digest = server.file_digest(str(path), stat.st_mtime_ns, stat.st_size)
        if accepted.get('verdict') != 'PASS' or digest != accepted.get('sha256'):
            raise ValueError('Unaccepted dictionary')
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(503, 'Dictionary source files are unavailable or await source validation.') from exc
    return path


@lru_cache(maxsize=2)
def _lexicon_index(path, stamp, size, restricted):
    """Compact read-only directory; source payloads are read only when needed."""
    rows = []
    with open(path, 'rb') as handle:
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line:
                break
            if not line.strip():
                continue
            entry = json.loads(line)
            if restricted and not record_allowed(entry):
                continue
            lemma = entry.get('lemma')
            if not isinstance(lemma, str) or not lemma.strip():
                continue
            rows.append((normalize(lemma), unicodedata.normalize('NFC', lemma),
                         entry['id'], offset, len(line),
                         str(entry.get('entry_text', '')).casefold()))
    rows.sort(key=lambda item: item[:3])
    if _signature(path) != (str(Path(path).resolve()), stamp, size):
        raise HTTPException(503, 'Dictionary changed during lookup; retry after source validation.')
    return tuple(rows)


def _read_entry(handle, item):
    handle.seek(item[3])
    return json.loads(handle.read(item[4]))


def _display_entry(entry, english_pattern=None):
    from .lexicon_senses import dictionary_senses
    projected = dictionary_senses(entry)
    senses = projected.get('dictionary_senses', [])
    # A subform's definition must not masquerade as its entry headword's sense.
    senses = [sense for sense in senses if sense.get('form_scope', {}).get('relation', 'headword') == 'headword']
    if english_pattern is not None:
        senses = [sense for sense in senses if english_pattern.search(sense.get('text', ''))]
        if not senses:
            return None
    meanings = [{key: sense.get(key) for key in
                 ('id', 'text', 'source', 'source_url', 'lexicon_entry_id', 'source_locator', 'sense_path')}
                for sense in senses[:3]]
    return {'id': entry['id'], 'headword': entry['lemma'], 'lemma': entry['lemma'],
            'source': entry.get('source'), 'source_url': entry.get('entry_url') or entry.get('source_url'),
            'license': entry.get('license'), 'meaning': meanings[0]['text'] if meanings else '',
            'meanings': meanings, 'meaning_count': len(senses), 'entry_count': 1,
            'homograph': re.search(r'\d+$', str(entry.get('lemma_beta', ''))).group()
            if re.search(r'\d+$', str(entry.get('lemma_beta', ''))) else None,
            'meaning_status': projected.get('dictionary_senses_status', 'unavailable')}


@router.get('/api/lexicon')
def lexicon(q: str = '', prefix: str = '', mode: str = 'auto',
            limit: int = Query(30, ge=1, le=60), offset: int = Query(0, ge=0, le=1000000)):
    q, prefix = q.strip(), prefix.strip()
    if len(q) > 100 or len(prefix) > 100 or mode not in {'auto', 'greek', 'english'}:
        raise HTTPException(422, 'Use at most 100 characters and mode auto, greek, or english.')
    path = _entries_path()
    stat = path.stat()
    with _LOCK:
        rows = _lexicon_index(str(path), stat.st_mtime_ns, stat.st_size, publication_restricted())
    prefix_keys = query_variants(prefix) if prefix else []
    filtered = [row for row in rows if not prefix_keys or any(row[0].startswith(key) for key in prefix_keys)]
    keys = query_variants(q) if q else []
    has_greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', q))
    exact = [row for row in filtered if row[0] in keys] if q else []
    effective_mode = mode
    if mode == 'auto':
        effective_mode = 'greek' if not q or has_greek or exact else 'english'
        if q and effective_mode == 'english' and not any(q.casefold() in row[5] for row in filtered):
            # Latin input can be a transliterated inflection. Only the actual
            # source form index may authorize its headword link.
            effective_mode = 'greek'
    warnings = []
    complete = True
    inspected = 0
    if q and effective_mode == 'greek':
        # Resolve actual indexed forms only for a search, never for alphabet browsing.
        lemma_keys = set(keys)
        if not exact and keys:
            try:
                from . import server
                service = server.morph_service()
                for key in keys:
                    lemma_keys.update(service._form_lemmas.get(key, ()))
            except (OSError, RuntimeError, ValueError):
                warnings.append('Indexed form lookup is unavailable; headword matches are shown.')
        filtered = [row for row in filtered if row[0] in lemma_keys or any(row[0].startswith(key) for key in keys)]
    english_pattern = None
    if q and effective_mode == 'english':
        # entry_text is only a candidate filter: every output must subsequently
        # match a hash-verified, structured English definition span.
        terms = re.findall(r'[A-Za-z]+', q)
        if not terms:
            filtered = []
        else:
            english_pattern = re.compile(r'(?<![A-Za-z])' + r'\s+'.join(map(re.escape, terms)) + r'(?![A-Za-z])', re.I)
            filtered = [row for row in filtered if english_pattern.search(row[5])]
        complete = len(filtered) <= MAX_ENGLISH_CANDIDATES
        candidates = filtered[:MAX_ENGLISH_CANDIDATES]
        inspected = len(candidates)
        with path.open('rb') as handle:
            results = [found for item in candidates if (found := _display_entry(_read_entry(handle, item), english_pattern))]
        total = len(results)
        results = results[offset:offset + limit]
        if not complete:
            warnings.append(f'English lookup checked the first {MAX_ENGLISH_CANDIDATES} alphabetical source-entry candidates; the result count covers only this window. Refine the term or Greek prefix for wider coverage.')
    else:
        total = len(filtered)
        with path.open('rb') as handle:
            results = [_display_entry(_read_entry(handle, item)) for item in filtered[offset:offset + limit]]
    if _signature(path) != (str(path.resolve()), stat.st_mtime_ns, stat.st_size):
        raise HTTPException(503, 'Dictionary changed during lookup; retry after source validation.')
    return {'results': results, 'total': total, 'limit': limit, 'offset': offset,
            'has_more': offset + len(results) < total, 'mode': effective_mode,
            'method': 'Alphabetical source headwords; English meanings are verified structured dictionary spans.',
            'warnings': warnings, 'search_contract': {'complete': complete,
                'english_candidate_limit': MAX_ENGLISH_CANDIDATES, 'candidates_checked': inspected,
                'ordering': 'diacritic-folded Greek headword, exact headword, source entry id',
                'sense_selection': 'source order, not contextual interpretation'}}


@router.get('/api/discovery-catalog')
def discovery_catalog():
    return {'themes': [{'id': identifier, 'label': label, 'kind': kind, 'query': query,
                        'description': ('Source-bound model aesthetic annotations with validated quotations.'
                                        if kind == 'aesthetic_annotation' else
                                        'A literary discovery query, not an annotated category.')}
                       for identifier, label, kind, query in THEMES],
            'units': [{'id': identifier, 'label': identifier.title(), 'method': method}
                      for identifier, method in UNIT_METHODS.items()],
            'authors_endpoint': '/api/authors',
            'method': 'Existing parent retrieval, literal source-span segmentation, bounded on-demand local child encoding, and annotation-span overlap.',
            'independent_unit_embeddings': False}


def _annotation_path():
    from .visual_themes import ANNOTATIONS
    return ANNOTATIONS if ANNOTATIONS.exists() else ROOT / 'discovery-data/validated.json'


def _cache_identity(server):
    return (_signature(server.DB), _signature(str(server.DB) + '-wal'),
            _signature(server.ROOT / 'data/embeddings/manifest.json'), _signature(_annotation_path()),
            _signature(server.ROOT / 'backend/author_aliases.json'),
            _signature(server.ROOT / 'data/metadata/chronology.json'),
            publication_restricted(), public_deployment())


def _nature_parents(server, theme, author):
    from .visual_themes import load_annotations, annotation_for
    from .author_aliases import component_keys
    path = _annotation_path()
    saved, _ = load_annotations(path)
    identifiers = sorted(identifier for identifier, row in saved.items()
                         if not row.get('parent_id') and any(label.get('theme') == theme for label in row.get('labels', [])))
    sought = set(server.author_filter_keys(author)) if author else set()
    records = []
    with server.connect() as con:
        def lookup(identifier):
            row = con.execute('SELECT data FROM passages WHERE id=?', (identifier,)).fetchone()
            return json.loads(row['data']) if row else None
        for identifier in identifiers:
            record = lookup(identifier)
            if not record or (sought and not sought.intersection(component_keys(record.get('author')))):
                continue
            annotation = annotation_for(record, lookup, path)
            if annotation and theme in annotation.get('themes', []):
                records.append({**record, 'visual_themes': annotation})
    records.sort(key=lambda row: (row.get('author', ''), row.get('work', ''), row.get('sequence', 0), row['id']))
    return records


def _parents(q, theme, author):
    from . import server
    identity = _cache_identity(server)
    key = identity, q, theme, author
    # Serialize cache misses so simultaneous pages cannot launch duplicate encodes.
    with _LOCK:
        if key in _PARENT_CACHE:
            _PARENT_CACHE.move_to_end(key)
            return _PARENT_CACHE[key]
        warnings = []
        parent_scope = {}
        is_nature = bool(theme and THEME_MAP[theme][2] == 'aesthetic_annotation')
        if is_nature:
            available = _nature_parents(server, theme, author)
            if q:
                # Explicit q narrows a nature category through parent retrieval.
                found = server.search(q=q, mode='themes', author=author, limit=PARENT_LIMIT,
                                      offset=0, include_reference=False)
                ranks = {row['id']: i for i, row in enumerate(found['results'])}
                available = [row for row in available if row['id'] in ranks]
                available.sort(key=lambda row: ranks[row['id']])
                warnings.extend(found.get('warnings', []))
                semantic_total = found.get('total', len(found['results']))
                parent_scope = {
                    'kind': 'annotation_intersection_with_semantic_parent_window',
                    'semantic_parents_retrieved': len(found['results']),
                    'semantic_parent_candidates_total': semantic_total,
                    'intersection_matches_in_window': len(available),
                    'intersection_bounded': semantic_total > len(found['results']),
                }
                if parent_scope['intersection_bounded']:
                    warnings.append('The nature category was intersected with a bounded semantic parent window; additional category matches may exist outside that window.')
            total = len(available)
            records = available[:PARENT_LIMIT]
            method = 'Validated aesthetic annotations' + (' intersected with semantic parent retrieval' if q else '')
        elif q:
            found = server.search(q=q, mode='themes', author=author, limit=PARENT_LIMIT,
                                  offset=0, include_reference=False)
            warnings.extend(found.get('warnings', []))
            records = found['results']
            total = found.get('total', len(records))
            method = found.get('method', 'Semantic parent retrieval')
            if not records and 'unavailable' in method.lower():
                found = server.search(q=q, mode='words', author=author, limit=PARENT_LIMIT,
                                      offset=0, include_reference=False, match='exact')
                records = found['results']
                total = found.get('total', len(records))
                method = 'Source lexical fallback; local semantic retrieval unavailable'
                warnings.append('Local semantic retrieval is unavailable; only literal source matches are shown.')
        else:
            records, total, method = [], 0, 'Choose a theme or enter a literary idea.'
        records = [row for row in records if row.get('kind') == 'text' and row.get('language') == 'grc']
        value = records, total, method, list(dict.fromkeys(warnings)), parent_scope
        if identity == _cache_identity(server):
            _PARENT_CACHE[key] = value
            while len(_PARENT_CACHE) > 16:
                _PARENT_CACHE.popitem(last=False)
        return value


def _overlap(span, evidence):
    return max(0, min(span['end'], evidence['end']) - max(span['start'], evidence['start']))


def _semantic_children(query, results):
    """Encode a disclosed bounded sample of literal child spans on demand.

No vector is saved into the corpus/index. The existing pinned local encoder
and its serialization lock are reused; long spans are never silently clipped.
"""
    from . import server
    import numpy as np
    candidate_count = len(results)
    results = [row for row in results if any(
        unicodedata.category(char) in {'Lu', 'Ll', 'Lt'}
        and 'GREEK' in unicodedata.name(char, '') for char in row['quote'])]
    nonlexical_omitted = candidate_count - len(results)
    omitted_metadata = {'non_greek_letter_units_omitted': nonlexical_omitted,
                        'eligibility': 'At least one printed Greek alphabetic letter; editorial marks alone are not lexical evidence.'}
    groups = OrderedDict()
    for result in results:
        if result['parent_rank'] > CHILD_PARENT_LIMIT or len(result['quote']) > CHILD_CHARACTER_LIMIT:
            continue
        groups.setdefault(result['passage_id'], []).append(result)
    # First keep direct literal/evidence support; remaining picks are spread
    # across each source record instead of selecting its opening words only.
    queues = []
    for group in groups.values():
        witnessed = sorted((row for row in group if row['score']), key=lambda row: (-row['score'], row['start']))
        ordered = sorted((row for row in group if not row['score']), key=lambda row: row['start'])
        if ordered:
            quota = max(1, CHILD_EMBEDDING_LIMIT // len(groups))
            positions = list(dict.fromkeys(int(value) for value in np.linspace(0, len(ordered) - 1, min(len(ordered), quota))))
            ordered = [ordered[index] for index in positions]
        queues.append(witnessed + ordered)
    sample = []
    while queues and len(sample) < CHILD_EMBEDDING_LIMIT:
        for queue in queues:
            if queue and len(sample) < CHILD_EMBEDDING_LIMIT:
                sample.append(queue.pop(0))
        queues = [queue for queue in queues if queue]
    if not sample:
        return results, {'available': False, **omitted_metadata,
                         'reason': 'No Greek-letter child spans within the local encoding bounds.'}
    identity = _cache_identity(server)
    key = identity, query, tuple(row['id'] for row in sample)
    with _LOCK:
        cached = _CHILD_CACHE.get(key)
        if cached is None:
            try:
                semantic = server.semantic_service()
                if not semantic.ready:
                    return results, {'available': False, **omitted_metadata, 'reason': 'Local semantic index unavailable.'}
                with semantic._state_lock:
                    manifest = semantic._manifest
                model = semantic._get_model(manifest)
                with semantic._encode_lock:
                    # Character bounds alone cannot prevent tokenizer truncation
                    # (especially in polytonic Greek). Check complete tokenized
                    # spans, including special tokens, before encoding anything.
                    texts = [query] + [row['quote'] for row in sample]
                    tokenized = model.tokenizer(texts, truncation=False, padding=False,
                                               add_special_tokens=True)['input_ids']
                    token_limit = int(model.max_seq_length)
                    if len(tokenized[0]) > token_limit:
                        return results, {'available': False, **omitted_metadata, 'reason': 'Query exceeds complete-span local tokenizer bound.'}
                    keep = [index for index, ids in enumerate(tokenized[1:]) if len(ids) <= token_limit]
                    if not keep:
                        return results, {'available': False, **omitted_metadata, 'reason': 'Child spans exceed complete-span local tokenizer bound.'}
                    vectors = np.asarray(model.encode([query] + [sample[index]['quote'] for index in keep],
                        batch_size=8, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)
                scores = [round(float(value), 6) for value in vectors[1:] @ vectors[0]]
                if len(scores) != len(keep) or not np.all(np.isfinite(scores)):
                    raise RuntimeError('Invalid local child similarities')
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                return results, {'available': False, **omitted_metadata,
                                 'reason': 'Local child encoding unavailable; literal span support and parent rank retained.'}
            _CHILD_CACHE[key] = keep, scores, token_limit
            while len(_CHILD_CACHE) > 64:
                _CHILD_CACHE.popitem(last=False)
        else:
            keep, scores, token_limit = cached
            _CHILD_CACHE.move_to_end(key)
    ranked = []
    for row, score in zip((sample[index] for index in keep), scores):
        ranked.append({**row, 'literal_support_score': row['score'], 'score': score,
                       'retrieval_score_kind': 'on_demand_child_cosine',
                       'match_reason': 'Local semantic similarity of this exact source span',
                       'unit_embedding_method': 'on-demand existing local parent encoder; no independent unit index'})
    ranked.sort(key=lambda row: (-row['score'], row['parent_rank'], row['start'], row['id']))
    return ranked, {'available': True, 'encoded_units': len(keep), **omitted_metadata,
                    'candidate_units': candidate_count, 'sampled': len(keep) < candidate_count,
                    'token_limit_including_special_tokens': token_limit,
                    'tokenizer_rejected_units': len(sample) - len(keep),
                    'unit_limit': CHILD_EMBEDDING_LIMIT, 'parent_limit': CHILD_PARENT_LIMIT,
                    'source_character_limit_per_unit': CHILD_CHARACTER_LIMIT,
                    'sampling': 'Round-robin over first 16 parents; literal support first, then evenly spaced source spans.',
                    'method': 'On-demand local BGE-M3 exact-span cosine; rank is not calibrated confidence.'}


@router.get('/api/theme-search')
def theme_search(q: str = '', theme: str = '', author: str = '', unit: str = 'passage',
                 limit: int = Query(20, ge=1, le=60), offset: int = Query(0, ge=0, le=1000000)):
    from .discovery_units import segment_record, MAX_SOURCE_LENGTH, MAX_UNITS_PER_RECORD
    q, theme, author = q.strip(), theme.strip(), author.strip()
    if len(q) > 200 or len(author) > 200 or unit not in UNIT_METHODS or (theme and theme not in THEME_MAP):
        raise HTTPException(422, 'Choose a supported theme/unit and at most 200 query or author characters.')
    effective_query = q or (THEME_MAP[theme][3] if theme and THEME_MAP[theme][2] == 'retrieval_prompt' else '')
    try:
        parent_result = _parents(effective_query, theme, author)
        parents, parent_total, method, cached_warnings = parent_result[:4]
        parent_scope = parent_result[4] if len(parent_result) > 4 else {}
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, 'Discovery sources are temporarily unavailable.') from exc
    warnings = list(cached_warnings)
    query_keys = set(normalize(effective_query).split())
    results = []
    characters = 0
    bounded = bool(parent_scope.get('intersection_bounded'))
    omitted = 0
    for rank, parent in enumerate(parents):
        text = parent.get('text', '')
        characters += len(text)
        if characters > MAX_CHARACTERS:
            bounded = True
            break
        if len(text) > MAX_SOURCE_LENGTH:
            omitted += 1
            continue
        spans = segment_record(parent, unit)
        if len(spans) == MAX_UNITS_PER_RECORD:
            bounded = True
        evidence = [span for label in parent.get('visual_themes', {}).get('labels', [])
                    if label.get('theme') == theme for span in label.get('evidence', [])
                    if span.get('id') == parent['id']]
        for span in spans:
            tokens = set(normalize(span['quote']).split())
            lexical = len(tokens.intersection(query_keys))
            overlap = sum(_overlap(span, proof) for proof in evidence)
            # The child score is explicitly lexical/evidence support. Parent
            # rank resolves ties; it is not a unit embedding or probability.
            support = lexical + (1 if overlap else 0)
            result = {key: parent.get(key) for key in ('author', 'work', 'work_id', 'citation',
                      'source', 'source_url', 'license', 'language', 'quality', 'author_chronology')}
            result.update(span)
            result.update({'score': support, 'parent_rank': rank + 1,
                           'parent_length': len(text), 'retrieval_score_kind': 'literal_span_support',
                           'match_reason': ('Overlaps validated aesthetic evidence' if overlap else
                                            'Literal query words in this source span' if lexical else
                                            'Parent passage relevance; no independent match established for this span'),
                           'annotation_scope': 'parent_passage' if parent.get('visual_themes') else None,
                           'lexical_matches': sorted(tokens.intersection(query_keys)),
                           'independent_unit_embedding': False})
            if parent.get('visual_themes'):
                result['visual_themes'] = parent['visual_themes']
            results.append(result)
            if len(results) >= MAX_UNIT_RESULTS:
                bounded = True
                break
        if len(results) >= MAX_UNIT_RESULTS:
            break
    results.sort(key=lambda row: (-row['score'], row['parent_rank'], row['start'], row['id']))
    child_reranking = {'available': False, 'reason': 'Parent passage retrieval or annotation-span ranking requested.'}
    if unit != 'passage' and effective_query and results:
        results, child_reranking = _semantic_children(effective_query, results)
        bounded = bounded or child_reranking.get('sampled', False) or bool(child_reranking.get('non_greek_letter_units_omitted'))
        if child_reranking.get('non_greek_letter_units_omitted'):
            warnings.append('Child spans without a printed Greek alphabetic letter were omitted; editorial gaps remain unchanged in their parent sources.')
        if child_reranking.get('available'):
            warnings = ['Parent retrieval: ' + warning for warning in warnings]
            method += '; bounded on-demand local BGE-M3 source-span cosine reranking'
            warnings.append('Local multilingual similarity on Ancient Greek is not a validated interpretation or a literary annotation.')
    total = len(results)
    if parent_total > len(parents) or bounded or omitted:
        warnings.append('Results cover a bounded parent candidate window; totals count only sampled, encoded child units.'
                        if child_reranking.get('available') else
                        'Results cover a bounded parent candidate window; totals count only derived units in that window.')
    if unit != 'passage':
        warnings.append(UNIT_METHODS[unit])
    if unit == 'stanza' and not results:
        warnings.append('No explicit blank-line-separated blocks were present in the retrieved parents.')
    contract = {'parent_limit': PARENT_LIMIT, 'parents_retrieved': len(parents),
                'parent_candidates_total': parent_total, 'unit_limit': MAX_UNIT_RESULTS,
                'parent_scope': parent_scope,
                'source_character_limit': MAX_CHARACTERS, 'long_parents_omitted': omitted,
                'total_scope': ('sampled, encoded child units from the bounded retrieved parent window'
                                if child_reranking.get('available') else
                                'units in bounded retrieved parent window'),
                'complete': parent_total <= len(parents) and not bounded and not omitted,
                'segmentation': UNIT_METHODS[unit], 'independent_unit_embeddings': False,
                'child_semantic_reranking': child_reranking,
                'child_ranking': ('on-demand local BGE-M3 source-span cosine, then parent rank'
                                  if child_reranking.get('available') else
                                  'literal query-token overlap or validated annotation-span overlap, then parent rank'),
                'offset_basis': 'Unicode codepoints in original passage.text'}
    return {'results': results[offset:offset + limit], 'total': total, 'limit': limit,
            'offset': offset, 'has_more': offset + limit < total, 'unit': unit,
            'theme': theme, 'query': effective_query, 'method': method,
            'warnings': list(dict.fromkeys(warnings)), 'search_contract': contract}
