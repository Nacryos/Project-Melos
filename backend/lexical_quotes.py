"""Bounded comparison with quotations in existing, hash-verified LSJ TEI.

An entry quoting a passage does NOT identify every quoted word as a form of
its headword. These results are dictionary context, never morphological rows.
No source files, accepted datasets, or model classifications are changed.
"""
from functools import lru_cache
import hashlib
import re
import unicodedata

from lxml import etree

from .lexicon_render import (GREEK_LANGS, SPACE, _render_node, _source_path,
                             read_entry)


ENTRY_LIMIT = 12
HIT_LIMIT = 20
_APOSTROPHES = "'’ʼ᾽"
_SIGNS = _APOSTROPHES + '᾿'
_GAP = re.compile(r'[\[\]⟨⟩<>…\d]|\.{2,}|\.\s+\.')
SCOPE = 'dictionary_quotation_not_morphological_parse'


def _tokens(text):
    """Original character offsets; apostrophes stay attached to their words."""
    result, start = [], None
    for index, char in enumerate(text):
        if char.isalpha() or (start is not None and unicodedata.category(char).startswith('M')):
            if start is None:
                start = index
        elif char in _SIGNS and start is not None:
            continue
        elif start is not None:
            result.append((text[start:index], start, index))
            start = None
    if start is not None:
        result.append((text[start:], start, len(text)))
    return result


def _key(text):
    # Unicode UAX #15 canonical equivalence, not lossy accent/dialect folding.
    # Printed apostrophe variants identify the same mark; spacing psili does
    # not. No missing vowel, accent, or letter is supplied.
    return unicodedata.normalize('NFC', text).translate(str.maketrans({c: "'" for c in _APOSTROPHES}))


def _sense(node):
    return next((ancestor for ancestor in node.iterancestors() if ancestor.tag == 'sense'), None)


@lru_cache(maxsize=8)
def _verified_digest(path, mtime_ns, size):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


@lru_cache(maxsize=256)
def _quotes(path, entry_id, mtime_ns, size):
    entry, entities = read_entry(path, entry_id)
    output = []
    for cit in entry.iter('cit'):
        quote_nodes = cit.findall('quote')
        bibliographies = cit.findall('bibl')
        # Do not merge multiple quotations or pair a quotation with a citation
        # elsewhere in the entry. Unclear ownership is omitted, not guessed.
        if len(quote_nodes) != 1 or len(bibliographies) != 1:
            continue
        quote, bibl = quote_nodes[0], bibliographies[0]
        language = quote.get('lang') or quote.get('{http://www.w3.org/XML/1998/namespace}lang')
        if (language or '').lower() not in GREEK_LANGS:
            continue
        sense = _sense(cit)
        gloss = None
        if sense is not None:
            for node in sense.iter():
                if node is cit:
                    break
                if node.tag == 'tr' and node.getparent() is sense:
                    gloss = SPACE.sub(' ', _render_node(node, entities)).strip() or None
        rendered = SPACE.sub(' ', _render_node(quote, entities)).strip()
        if _GAP.search(rendered):
            continue
        tokens = _tokens(rendered)
        if len(tokens) < 2:
            continue
        source_quote = ''.join(quote.itertext()).strip()
        for marker, value in entities.items():
            source_quote = source_quote.replace(marker, value)
        tree_path = entry.getroottree().getpath(cit)
        output.append({
            'sense_id': sense.get('id') if sense is not None else None,
            'source_gloss': gloss,
            'source_gloss_status': 'preceding_translation_in_same_sense' if gloss else 'not_supplied_in_local_scope',
            'quote': rendered, 'raw_quote': source_quote,
            'raw_quote_encoding': 'Source Greek Beta Code with character references decoded; unresolved entity names retained literally.',
            'citation': SPACE.sub(' ', _render_node(bibl, entities)).strip(),
            'citation_urn': bibl.get('n'),
            'source_locator': '.' + tree_path[len('/entryFree'):],
            '_keys': tuple(_key(token) for token, _, _ in tokens),
        })
    return tuple(output)


def lookup_quotes(form, passage, entries, entry_limit=ENTRY_LIMIT):
    """Compare complete quotations from a declared candidate-entry shortlist."""
    unique = {}
    for record in entries:
        if record.get('source') == 'PerseusDL LSJ TEI':
            unique.setdefault((record.get('source_url'), record.get('entry_id')), record)
    entry_limit = max(0, min(int(entry_limit), ENTRY_LIMIT))
    result = {'hits': [], 'eligible_entries': len(unique), 'searched_entries': 0,
              'entry_limit': entry_limit, 'entries_truncated': len(unique) > entry_limit,
              'hit_limit': HIT_LIMIT, 'hits_truncated': False,
              'coverage': 'Candidate-shortlisted LSJ entries only; not an exhaustive dictionary quotation search.',
              'warnings': []}
    if not passage or passage.get('language') != 'grc' or passage.get('kind') != 'text':
        return result
    if passage.get('quality') not in {'source_text', 'machine_corrected_ocr'}:
        result['warnings'].append('Dictionary quote comparison omitted: the passage is not a searchable reading-text quality class.')
        return result
    if passage.get('quality') == 'machine_corrected_ocr':
        result['warnings'].append('The compared passage is labelled machine-corrected OCR, not independently verified transcription.')
    text = str(passage.get('text') or '')
    target = _key(form)
    words = _tokens(text)
    keys = [_key(word) for word, _, _ in words]
    if target not in keys:
        return result
    for record in list(unique.values())[:entry_limit]:
        try:
            path = _source_path(record['raw_path'])
            stat = path.stat()
            if not record.get('raw_sha256') or _verified_digest(path, stat.st_mtime_ns, stat.st_size) != record['raw_sha256']:
                raise ValueError('Source hash mismatch')
            quotations = _quotes(path, record['entry_id'], stat.st_mtime_ns, stat.st_size)
            if (path.stat().st_mtime_ns, path.stat().st_size) != (stat.st_mtime_ns, stat.st_size):
                raise ValueError('Source changed during read')
            result['searched_entries'] += 1
        except (KeyError, OSError, ValueError, etree.XMLSyntaxError):
            result['warnings'].append('An LSJ entry could not be read with verified source provenance; it was omitted.')
            continue
        for quotation in quotations:
            quote_keys = quotation['_keys']
            if target not in quote_keys:
                continue
            spans = []
            for index in range(len(keys) - len(quote_keys) + 1):
                if tuple(keys[index:index + len(quote_keys)]) != quote_keys:
                    continue
                start, end = words[index][1], words[index + len(quote_keys) - 1][2]
                if not _GAP.search(text[start:end]):
                    spans.append({'start': start, 'end': end, 'text': text[start:end]})
            if not spans:
                continue
            if len(result['hits']) >= HIT_LIMIT:
                result['hits_truncated'] = True
                continue
            hit = {key: value for key, value in quotation.items() if not key.startswith('_')}
            hit.update({key: record.get(key) for key in ('lemma', 'entry_id', 'source', 'source_url', 'entry_url', 'raw_sha256')})
            hit.update({'scope': SCOPE, 'passage_id': passage.get('id'), 'passage_quality': passage.get('quality'), 'passage_spans': spans,
                        'match_method': 'Complete contiguous quote tokens; NFC and apostrophe-glyph equivalence only; accents retained.',
                        'interpretation_warning': 'A quotation in this dictionary entry is not a claim that every quoted word is an inflection of its headword; no morphological parse is supplied.'})
            result['hits'].append(hit)
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    return result
