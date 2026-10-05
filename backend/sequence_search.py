"""Strict multiword witnesses over original source records, no positional DB writes."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from collections import OrderedDict
from threading import Lock
from .expansion import SequenceLimit
from . import textutils

MAX_CANDIDATES = 20000
MAX_SOURCE_CHARACTERS = 25000000
MAX_MATCH_OPERATIONS = 2000000
_BARRIER = re.compile(r'[\[\]<>\{\}⟨⟩〈〉‹›⟦⟧⸢⸣⸤⸥†‡…\u0323\u2010\u00ad-]|\.{2,}')
_POSSIBLE_DIVISION = re.compile(r'[-\u2010\u00ad][ \t]*\r?\n')
_DIVIDED_IDS = OrderedDict()
_DIVIDED_LOCK = Lock()


def _corpus_identity(con):
    from .publication import publication_restricted, public_deployment
    filename = next((row[2] for row in con.execute('PRAGMA database_list') if row[1] == 'main'), '')
    if not filename:
        return None  # Isolated in-memory fixtures never share this cache.
    path = Path(filename).resolve()
    def signature(target):
        if not target.exists():
            return None
        info = target.stat()
        return info.st_size, info.st_mtime_ns, info.st_ino
    return str(path), signature(path), signature(Path(str(path)+'-wal')), publication_restricted(), public_deployment()


def non_greek_divided_ids(con):
    """Version-bound derived IDs only; all current source filters run afterward."""
    with _DIVIDED_LOCK:
        identity = _corpus_identity(con)
        if identity is not None and identity in _DIVIDED_IDS:
            _DIVIDED_IDS.move_to_end(identity)
            return _DIVIDED_IDS[identity]
        rows = con.execute("SELECT id,text FROM passages WHERE language!='grc' AND instr(text,char(10))>0 "
                           "AND (instr(text,'-')>0 OR instr(text,char(8208))>0 OR instr(text,char(173))>0)")
        result = tuple(row['id'] for row in rows if _POSSIBLE_DIVISION.search(row['text']))
        if _corpus_identity(con) != identity:
            raise SequenceLimit('The corpus changed while preparing positional lookup; retry against the stable source snapshot.')
        if identity is not None:
            _DIVIDED_IDS[identity] = result
            while len(_DIVIDED_IDS) > 2:
                _DIVIDED_IDS.popitem(last=False)
        return result


def adjacent_prefilter(groups):
    """Necessary-only regex: punctuation/digits are allowed to overselect.

    The source lexer emits letter units, so any true adjacent pair has only
    nonletters (or discarded digits/underscores) between its complete keys.
    Apostrophe boundaries/editorial certainty are checked only by verify().
    """
    parts = ['(?:' + '|'.join(re.escape(key) for key in sorted(group['alternatives'], key=len, reverse=True)) + ')'
             for group in groups]
    return re.compile(r'(?<![^\W\d_])' + r'[\W\d_]+'.join(parts) + r'(?![^\W\d_])')


class _IdentityOffsets:
    def __getitem__(self, index):
        return index, index + 1


def query_terms(query):
    """Greek punctuation separates words; Beta Code accents do not split one word."""
    terms, current = [], []
    def flush():
        if not current:
            return
        value = ''.join(current)
        current.clear()
        if any(textutils._greek_letter(char) for char in value):
            terms.extend(textutils.tokenize(value))
        elif any(char.isalpha() for char in value):
            terms.append(value)
    for char in textutils.search_text(query):
        if char.isalpha() or unicodedata.category(char).startswith('M') or char in "*/\\=()|+" + textutils._WORD_SIGNS:
            current.append(char)
        else:
            flush()
    flush()
    return terms


def editorial_mask(text):
    """Conservative uncertainty regions, not an interpretation of restorations."""
    pairs = dict(zip('[<{⟨〈‹⟦⸢⸤', ']>}⟩〉›⟧⸣⸥'))
    closers = set(pairs.values())
    stack, intervals = [], []
    for index, char in enumerate(text):
        if char in pairs:
            stack.append((char, index))
        elif char in closers:
            if stack and pairs[stack[-1][0]] == char:
                _, start = stack.pop()
                intervals.append((start, index + 1))
            else:
                intervals.append((text.rfind('\n', 0, index) + 1, index + 1))
    for _, start in stack:
        line_end = text.find('\n', start)
        intervals.append((start, line_end if line_end >= 0 else len(text)))
    mask = bytearray(len(text))
    for start, end in intervals:
        mask[start:end] = b'\1' * (end - start)
    return mask


def canonical_map(text):
    """NFC lookup copy with every character bound to its original codepoint range."""
    if unicodedata.normalize('NFC', text) == text:
        return text, _IdentityOffsets()
    output, offsets = [], []
    start = 0
    while start < len(text):
        end = start + 1
        while end < len(text) and unicodedata.category(text[end]).startswith('M'):
            end += 1
        cluster = unicodedata.normalize('NFC', text[start:end])
        output.append(cluster)
        offsets.extend([(start, end)] * len(cluster))
        start = end
    result = ''.join(output)
    if result != unicodedata.normalize('NFC', text):
        raise SequenceLimit('This passage requires unsupported source-offset normalization. No unverified positional result was returned.')
    return result, offsets


def source_tokens(text):
    """Retain original spans and refuse phrase bridges across editorial damage.

    Ordinary punctuation separates words without adding a word. Editorial
    gaps/uncertainty are barriers. Safe line-end divisions reuse the existing
    search-layout policy; rejected maximal chains cannot donate suffixes.
    """
    value, mapping = canonical_map(text)
    uncertain = editorial_mask(value)
    spans, cursor = [], 0
    for form in textutils.tokenize(value):
        start = value.find(form, cursor)
        if start < 0:
            raise SequenceLimit('Source token offsets could not be verified.')
        spans.append((start, start + len(form)))
        cursor = start + len(form)
    result, index, segment, previous = [], 0, 0, 0
    while index < len(spans):
        end = index
        while end + 1 < len(spans) and textutils._LINE_DIVISION.fullmatch(value, spans[end][1], spans[end + 1][0]):
            end += 1
        first, last = spans[index][0], spans[end][1]
        before, after = first, last
        while before and not value[before - 1].isspace():
            before -= 1
        while after < len(value) and not value[after].isspace():
            after += 1
        safe = (not _BARRIER.search(value, before, first) and not _BARRIER.search(value, last, after)
                and not textutils._DOTTED_GAP.match(value, last)
                and not textutils._orphan_division_before(value, first)
                and not any(uncertain[first:last])
                and all('\u0323' not in unicodedata.normalize('NFD', value[a:b]) for a, b in spans[index:end + 1]))
        if end > index:
            safe = (safe and not textutils._EDITORIAL_EDGE.search(value, before, first)
                    and not textutils._EDITORIAL_EDGE.search(value, last, after)
                    and not textutils._orphan_division_before(value, first)
                    and all(textutils._greek_letter(value[spans[i][1] - 1]) for i in range(index, end))
                    and all(all(textutils._greek_letter(char) or unicodedata.category(char).startswith('M') or char in textutils._JOIN_SIGNS
                                for char in value[a:b]) for a, b in spans[index:end + 1]))
        if _BARRIER.search(value, previous, first) or not safe:
            segment += 1
        units = [spans[index:end + 1]] if safe else [[span] for span in spans[index:end + 1]]
        for unit in units:
            raw_spans = [{'start': mapping[a][0], 'end': mapping[b - 1][1],
                          'text': text[mapping[a][0]:mapping[b - 1][1]]} for a, b in unit]
            form = ''.join(value[a:b] for a, b in unit)
            result.append({'token_index': len(result), 'form': form, 'key': textutils.normalize(form),
                           'source_spans': raw_spans, 'segment': segment, 'eligible': safe})
        if not safe:
            segment += 1
        previous, index = last, end + 1
    return result


def verify(text, groups, relation='ordered', slop=0):
    tokens = source_tokens(text)
    key_groups = {}
    for i, group in enumerate(groups):
        for key in group['alternatives']:
            key_groups.setdefault(key, set()).add(i)
    possible = {token['token_index']: key_groups[token['key']] for token in tokens
                if token['eligible'] and token['key'] in key_groups}
    n, operations = len(groups), 0

    def spend():
        nonlocal operations
        operations += 1
        if operations > MAX_MATCH_OPERATIONS:
            raise SequenceLimit('The positional query is too broad to verify completely; narrow the author, edition, or wording.')

    def assign(positions):
        # Bipartite matching: overlapping alternatives and repeated query words
        # may not reuse one source token for two query occurrences.
        owner = {}
        def visit(group, seen):
            for position in positions:
                spend()
                if group not in possible[position] or position in seen:
                    continue
                seen.add(position)
                if position not in owner or visit(owner[position], seen):
                    owner[position] = group
                    return True
            return False
        for group in range(n):
            if not visit(group, set()):
                return None
        return {group: position for position, group in owner.items()}

    chosen = None
    positions = sorted(possible)
    if relation == 'all_terms':
        chosen = assign(positions)
    elif relation == 'ordered':
        for first in positions:
            if 0 not in possible[first]:
                continue
            selected, wanted = {0: first}, 1
            for position in range(first + 1, min(len(tokens), first + n + slop)):
                spend()
                if tokens[position]['segment'] != tokens[first]['segment']:
                    break
                if wanted in possible.get(position, ()):
                    selected[wanted] = position
                    wanted += 1
                    if wanted == n:
                        chosen = selected
                        break
            if chosen:
                break
    else:
        for start, first in enumerate(positions):
            window = []
            for position in positions[start:]:
                spend()
                if position - first >= n + slop or tokens[position]['segment'] != tokens[first]['segment']:
                    break
                window.append(position)
            if len(window) >= n:
                chosen = assign(window)
                if chosen:
                    break
    if chosen is None:
        return None
    terms = []
    for i, group in enumerate(groups):
        token = tokens[chosen[i]]
        terms.append({'query_index': i, 'query_term': group['query_term'],
                      'matched_form': token['form'], 'token_index': token['token_index'],
                      'source_spans': token['source_spans'], 'matching_keys': [token['key']],
                      'expansion_refs': group['alternatives'][token['key']],
                      'expansion_refs_complete': token['key'] not in group.get('abbreviated_provenance_keys', set())})
    return {'relation': relation, 'slop': slop,
            'extra_words': None if relation == 'all_terms' else max(chosen.values()) - min(chosen.values()) + 1 - n,
            'terms': terms, 'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'offset_basis': 'Unicode codepoints in original passage.text',
            'editorial_scope_policy': 'Explicit paired brackets mark their full span; unmatched brackets are bounded to their printed line, without resolving the source editorial scope.',
            'witness_policy': 'One complete witness per passage; not an enumeration of all occurrences.'}


def find_matches(con, groups, extra, params, relation, slop):
    # SQL is only a presence superset. Identical repeated query groups need
    # one presence test, not a multiplicative join over every corpus token;
    # their required multiplicity remains in the original-position verifier.
    unique_groups = list(dict.fromkeys(tuple(sorted(group['alternatives'])) for group in groups))
    alternatives = [[index, key] for index, keys in enumerate(unique_groups) for key in keys]
    encoded = json.dumps(alternatives)
    # Non-tokenized source records (commentary/reference quality) must not
    # disappear. A normalized substring anchor overselects them for the same
    # source-position verifier; it never establishes a match itself.
    anchor = min(groups, key=lambda group: len(group['alternatives']))
    expression = ' OR '.join('"' + key.replace('"', '""') + '"' for key in anchor['alternatives'])
    divided_ids = non_greek_divided_ids(con)
    sql = ("WITH alternatives AS (SELECT json_extract(value,'$[0]') gid,json_extract(value,'$[1]') key FROM json_each(?)), "
           "indexed AS (SELECT t.passage_id id FROM tokens t JOIN alternatives a ON a.key=t.normalized "
           "GROUP BY t.passage_id HAVING COUNT(DISTINCT a.gid)=?), "
           "unindexed AS (SELECT id FROM passage_fts WHERE passage_fts MATCH ? AND "
           "NOT EXISTS (SELECT 1 FROM tokens t WHERE t.passage_id=passage_fts.id)), "
           "non_greek_divided AS (SELECT value id FROM json_each(?)), "
           "candidate_ids AS (SELECT id FROM indexed UNION SELECT id FROM unindexed UNION SELECT id FROM non_greek_divided) "
           "SELECT p.id,p.text,p.normalized,p.language FROM candidate_ids c JOIN passages p ON p.id=c.id WHERE 1=1" + extra +
           " ORDER BY p.id LIMIT ?")
    rows = con.execute(sql, [encoded, len(unique_groups), expression, json.dumps(divided_ids), *params, MAX_CANDIDATES + 1]).fetchall()
    if len(rows) > MAX_CANDIDATES:
        raise SequenceLimit('More than 20,000 candidate passages require verification; narrow the author, edition, or wording. No partial result count was returned.')
    if sum(len(row['text']) for row in rows) > MAX_SOURCE_CHARACTERS:
        raise SequenceLimit('The candidate source text exceeds the positional verification budget; narrow the author, edition, or wording. No partial results were returned.')
    matches = {}
    prefilter = adjacent_prefilter(groups) if relation == 'ordered' and slop == 0 else None
    for row in rows:
        if prefilter:
            # Necessary-only prefilter over the accepted index's layout/folded
            # copy. It ignores editorial barriers (overselects), and supplies
            # no returned proof. Every survivor still needs original-text
            # verification. Non-Greek source indexes do not join Greek line
            # divisions, so derive their necessary-only copy locally instead.
            normalized = row['normalized']
            if row['language'] != 'grc' and _POSSIBLE_DIVISION.search(row['text']):
                normalized = textutils.normalize(textutils.search_text(row['text']))
            if not prefilter.search(normalized):
                continue
        proof = verify(row['text'], groups, relation, slop)
        if proof:
            matches[row['id']] = proof
    return matches, len(rows)
