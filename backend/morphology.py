"""Source-bound Greek word lookup and query normalization.

This module never generates inflections or parses. It ranks only lexicon and
treebank rows actually present in the source-derived JSONL files.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
import json
from pathlib import Path
from .publication import publication_restricted, record_allowed
import re
import unicodedata
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_TOKEN = re.compile(
    r"[A-Za-z\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+"
    r"(?:['\u2019\u02bc\u1fbd][A-Za-z\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+)*"
    r"['\u2019\u02bc\u1fbd]?"
)
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "\u1fbd": "'", "\u2018": "'", "`": "'"})
_HOMOGRAPH_NUMBER = re.compile(r"\d+$")

# Reviewed *exclusions*, not replacement linguistic data. Keep the immutable
# source row on disk and disclose it separately. Match the full pinned token
# identity plus its annotation: no form-wide, dialect or majority-vote rule.
# QA13 source review (2026-09-30): the XML prints this form with a pronoun
# annotation. Independent lexical evidence below identifies a verbal form;
# the erroneous source annotation must not supply an I/me dictionary preview.
_REVIEWED_SOURCE_EXCLUSIONS = ({
    'id': 'perseus-1.6-tlg0059.tlg001-2857971-17',
    'match': {
        'source_url': 'https://raw.githubusercontent.com/PerseusDL/treebank_data/bf4334f0af5e13d16b04c1cccd6237e683ac6f5f/v1.6/greek/data/tlg0059.tlg001.perseus-grc1.tb.xml',
        'raw_sha256': 'ef9e66087eded142748a291ff395d4faf9beba3c9b99226196aa0fafbad417be',
        'document_id': 'urn:cts:greekLit:tlg0059.tlg001.perseus-grc1',
        'sentence_id': '2857971', 'token_id': '17',
        'form': 'φαίνεται', 'lemma': 'ἐγώ', 'lemma_raw': 'ἐγώ1', 'analysis': 'p-s---md-',
    },
    'reason': 'Reviewed source annotation mismatch: this pinned token associates the printed verbal form with a pronoun lemma and dative pronoun tag. The source is preserved, but this annotation is excluded from automated interpretation; no replacement parse is supplied.',
    'review_evidence_url': 'https://en.wiktionary.org/w/index.php?title=φαίνεται&oldid=87216593#Ancient_Greek',
},)


def _source_exclusion(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return next((rule for rule in _REVIEWED_SOURCE_EXCLUSIONS
                 if all(row.get(field) == value for field, value in rule['match'].items())), None)

# AGDT's nine-slot morphological code, documented by PerseusDL at
# https://github.com/PerseusDL/treebank_data/blob/master/AGDT2/guidelines/Greek_guidelines.md
# (older v1.x `t`/`e` part-of-speech codes are documented in the AGDT 1.7
# README mirrored at https://github.com/cltk/greek_treebank_perseus).
_POSTAG_FIELDS: tuple[dict[str, str], ...] = (
    {"n": "noun", "v": "verb", "t": "participle", "a": "adjective", "d": "adverb",
     "l": "article", "g": "particle", "c": "conjunction", "r": "preposition",
     "p": "pronoun", "m": "numeral", "i": "interjection", "e": "exclamation",
     "u": "punctuation", "x": "unavailable"},
    {"1": "first person", "2": "second person", "3": "third person"},
    {"s": "singular", "p": "plural", "d": "dual"},
    {"p": "present", "i": "imperfect", "r": "perfect", "l": "pluperfect",
     "t": "future perfect", "f": "future", "a": "aorist"},
    {"i": "indicative", "s": "subjunctive", "o": "optative",
     "n": "infinitive", "m": "imperative", "p": "participle"},
    {"a": "active", "p": "passive", "m": "middle", "e": "medio-passive"},
    {"m": "masculine", "f": "feminine", "n": "neuter"},
    {"n": "nominative", "g": "genitive", "d": "dative", "a": "accusative",
     "v": "vocative", "l": "locative"},
    {"c": "comparative", "s": "superlative"},
)


def describe_postag(code: str | None) -> str | None:
    """Expand a documented Perseus nine-slot code, never infer a sense."""
    if not code or len(code) != 9:
        return None
    parts: list[str] = []
    for position, char in enumerate(code.lower()):
        if char == "-":
            continue
        value = _POSTAG_FIELDS[position].get(char)
        if value is None:
            return None
        if position == 4 and value == "participle" and code[0].lower() == "t":
            continue
        parts.append(value)
    return " · ".join(parts) or None

# TLG Beta Code Manual, https://stephanus.tlg.uci.edu/encoding.php
_BETA = dict(zip("abgdez hqiklmncoprstufxyw".replace(" ", ""),
                 "αβγδεζηθικλμνξοπρστυφχψω"))
# ALA-LC Ancient Greek romanization as tabulated alongside ISO 843 by
# T. T. Pedersen, https://transliteration.eki.ee/pdf/Greek.pdf . The input
# converter accepts common unmarked alternatives (f, y, o) for retrieval;
# it is deliberately not a reversible scholarly transliterator.
_ROMAN_DIGRAPHS = {"th": "θ", "ph": "φ", "ch": "χ", "kh": "χ", "ps": "ψ",
                   "rh": "ρ"}
_ROMAN = dict(zip("abgdezhiklmnxoprstyufwqcv",
                  "αβγδεζηικλμνξοπρστυυφωκκβ"))


def normalize(text: str) -> str:
    """Fold Unicode Greek accents, breathings and sigma for search keys.

    Spaces, apostrophes and literal spacing psili (U+1FBF) survive. Psili is
    NOT equated with an apostrophe. Other punctuation separates words. The
    original text must always be stored separately from this lossy key.
    """
    decomposed = unicodedata.normalize("NFD", str(text).translate(_APOSTROPHES).lower())
    chars: list[str] = []
    for char in decomposed:
        if unicodedata.category(char).startswith("M"):
            continue
        if char in "ςϲϹ":
            char = "σ"
        if char.isalpha() or char in "'᾿":
            chars.append(char)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def tokenize(text: str) -> list[str]:
    """Return original-script word tokens without claiming editorial certainty."""
    return _TOKEN.findall(text)


def _from_beta(text: str) -> str:
    # TLG Quick Reference, pp. 3–4: apostrophe is meaningful punctuation,
    # unlike the supported accents/breathings/underdot removed in folded keys.
    # https://stephanus.tlg.uci.edu/encoding/quickbeta.pdf
    # Unsupported punctuation/digits must separate words, never concatenate
    # their surrounding letters. This is a query decoder, not full TEI import.
    out = []
    for char in text.translate(_APOSTROPHES).lower():
        if char in _BETA:
            out.append(_BETA[char])
        elif char in "'᾿":
            out.append(char)
        elif char not in "*/\\=()|+?":
            out.append(' ')
    return ''.join(out)


def _from_roman(text: str) -> str:
    value = unicodedata.normalize("NFD", text.translate(_APOSTROPHES).lower())
    # ALA-LC explicitly distinguishes ē/ō from e/o. Preserve those supplied
    # long-vowel identities before discarding other Latin accent marks.
    value = value.replace('e\u0304', 'η').replace('o\u0304', 'ω')
    value = "".join(c for c in value if not unicodedata.category(c).startswith("M"))
    out: list[str] = []
    i = 0
    while i < len(value):
        pair = value[i:i + 2]
        if pair in _ROMAN_DIGRAPHS:
            out.append(_ROMAN_DIGRAPHS[pair])
            i += 2
        elif value[i] in 'ηω':
            out.append(value[i])
            i += 1
        elif value[i] in _ROMAN:
            out.append(_ROMAN[value[i]])
            i += 1
        elif value[i].isspace():
            out.append(" ")
            i += 1
        elif value[i] in "'᾿":
            out.append(value[i])
            i += 1
        else:
            out.append(" ")
            i += 1
    return "".join(out)


def query_variants(q: str) -> list[str]:
    """Greek folded key(s) for Unicode, Beta Code, or Latin-letter input.

    Both ASCII conventions are retained where ambiguous. A candidate's
    source record, not this transliteration, determines whether it is a word.
    """
    if not q.strip():
        return []
    if any(c.isalpha() and ("\u0370" <= c <= "\u03ff" or "\u1f00" <= c <= "\u1fff") for c in q):
        return [normalize(q)]
    beta = normalize(_from_beta(q))
    roman = normalize(_from_roman(q))
    preferred = (beta, roman) if any(c in q for c in "*/\\=()|+") else (roman, beta)
    result = []
    for value in preferred:
        if value and value not in result:
            result.append(value)
    return result


def _distance(a: str, b: str, cutoff: int) -> int:
    """Levenshtein distance with length and row-minimum cutoffs."""
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        if min(current) > cutoff:
            return cutoff + 1
        previous = current
    return previous[-1]


def _trigrams(key: str) -> set[str]:
    padded = "^" + key + "$"
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL {path}:{line_number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"Expected object at {path}:{line_number}")
                yield row


class Morphology:
    """Lazy lexicon lookup; keys and trigram postings build once per process."""

    def __init__(self, entries_path: str | Path = ROOT / "data/lexica/entries.jsonl",
                 forms_path: str | Path = ROOT / "data/lexica/forms.jsonl") -> None:
        self.entries_path = Path(entries_path)
        self.forms_path = Path(forms_path)
        self._loaded = False
        self.entry_count = 0
        self.form_count = 0
        self._entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._forms: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lemma_forms: dict[str, set[str]] = defaultdict(set)
        self._form_lemmas: dict[str, set[str]] = defaultdict(set)
        self._quarantined_forms: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # References to the same compact rows held by _forms, not copied corpus
        # tokens. Unlike retrieval keys, these identities preserve accents,
        # case, source-local homograph numbers, and source attribution.
        self._inventory_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        self._inventory_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        self._grams: dict[str, set[str]] = defaultdict(set)
        self._short: dict[tuple[int, str], set[str]] = defaultdict(set)

    def _load(self) -> None:
        if self._loaded:
            return
        for row in _read_jsonl(self.entries_path):
            if publication_restricted() and not record_allowed(row):
                continue
            lemma = row.get("lemma")
            if not isinstance(lemma, str) or not lemma.strip():
                continue
            self._entries[normalize(lemma)].append(row)
            self.entry_count += 1
        seen_forms: set[tuple[str, ...]] = set()
        # Temporary collection before reading-level deduplication: later tokens
        # of an already indexed form must not disappear. Buckets are shared by
        # precise inventory identity + spelling + existing source-ref fields.
        # Only capped, deduplicated summaries remain resident after loading.
        location_buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
        # Document/sentence/token identifiers repeat heavily. Share immutable
        # strings within this load instead of retaining one copy per raw row.
        location_atoms: dict[str, str] = {'': ''}
        for row in _read_jsonl(self.forms_path):
            if publication_restricted() and not record_allowed(row):
                continue
            form = row.get("form")
            lemma = row.get("lemma")
            if not isinstance(form, str) or not form.strip() or not isinstance(lemma, str) or not lemma.strip():
                continue
            form_key = normalize(form)
            exclusion = _source_exclusion(row)
            if exclusion:
                # Deliberately before every candidate/inventory/expansion
                # index. Do not attach a dictionary gloss to a rejected edge.
                public = {field: row.get(field) for field in (
                    'form', 'lemma', 'lemma_raw', 'analysis', 'analysis_format',
                    'source', 'source_url', 'raw_sha256', 'citation', 'document_id',
                    'sentence_id', 'token_id', 'license', 'quality')}
                public.update({'status': 'quarantined_source_annotation',
                               'exclusion_id': exclusion['id'], 'reason': exclusion['reason'],
                               'review_evidence_url': exclusion['review_evidence_url']})
                if public not in self._quarantined_forms[form_key]:
                    self._quarantined_forms[form_key].append(public)
                continue
            lemma_key = normalize(lemma)
            self._lemma_forms[lemma_key].add(form)
            self._form_lemmas[form_key].add(lemma_key)
            self.form_count += 1
            lemma_nfc = unicodedata.normalize('NFC', lemma)
            raw_nfc = unicodedata.normalize('NFC', str(row.get('lemma_raw') or lemma))
            inventory_key = (lemma_nfc, raw_nfc, str(row.get('source') or ''))
            source_ref_key = json.dumps({field: row.get(field) for field in
                                        ('source', 'source_url', 'analysis', 'analysis_format', 'license', 'quality')},
                                       sort_keys=True, ensure_ascii=False)
            location_key = (*inventory_key, form, source_ref_key)
            new_inventory_reading = location_key not in location_buckets
            location_summary = location_buckets.setdefault(location_key, {'_rows': []})
            raw_location = (str(row[field]) if row.get(field) not in (None, '') else ''
                            for field in ('citation', 'document_id', 'sentence_id', 'token_id'))
            location = tuple(location_atoms.setdefault(value, value) for value in raw_location)
            if any(location):
                location_summary['_rows'].append(location)
            identity = (form_key, form, lemma, str(row.get("lemma_raw") or lemma),
                        str(row.get("analysis")), str(row.get("source_url")), str(row.get("source")))
            new_candidate_reading = identity not in seen_forms
            if not new_candidate_reading and not new_inventory_reading:
                continue
            seen_forms.add(identity)
            # Raw JSONL keeps every token and its precise source location.
            # Lookup needs one copy of each attested reading, never its count.
            compact_row = {field: row.get(field) for field in
                                           ("form", "lemma", "lemma_raw", "analysis", "analysis_format",
                                            "source", "source_url", "license", "quality")}
            compact_row['_location_summary'] = location_summary
            if new_candidate_reading:
                self._forms[form_key].append(compact_row)
            if new_inventory_reading:
                # Inventory references retain metadata variants even when
                # candidate deduplication intentionally ignores those fields.
                self._inventory_rows[inventory_key].append(compact_row)
                self._inventory_keys[lemma_nfc].add(inventory_key)
        for summary in location_buckets.values():
            # A count of distinct supplied locator records, not a frequency or
            # assertion of unique token occurrences. Conflicting citation aliases
            # at identical coordinates remain distinct; absent fields stay null.
            locations = sorted(set(summary.pop('_rows')),
                               key=lambda value: (not bool(value[0]), *value))
            shown = locations[:20]
            # Keep compact tuples internally. JSON dictionaries are built only
            # for the bounded inventories requested by a user, not every token.
            summary.update({'_locations': tuple(shown), 'location_total': len(locations)})
        for key in self._forms.keys() | self._entries.keys():
            if len(key) < 5:
                self._short[(len(key), key[:1])].add(key)
            else:
                for gram in _trigrams(key):
                    self._grams[gram].add(key)
        self._loaded = True

    def counts(self) -> dict[str, int]:
        self._load()
        return {"entries": self.entry_count, "forms": self.form_count}

    def forms_for_lemma(self, lemma: str) -> list[str]:
        """Attested spellings for a headword, with no generated paradigms."""
        self._load()
        result: set[str] = set()
        for key in query_variants(lemma):
            result.update(self._lemma_forms.get(key, ()))
        return sorted(result, key=lambda form: (normalize(form), form))

    def expansion_lemmas_for_form(self, form: str) -> list[str]:
        """Conservative, exact-key lemma links for automatic query expansion.

        Multiple source lemmas can mean legitimate homography *or* a source
        error. Neither token frequency nor this module adjudicates that. Keep
        all readings in ``analyze`` but do not automatically expand an
        ambiguous form into whole paradigms. An explicitly queried dictionary
        headword remains usable. Nearby spelling suggestions never authorize
        expansion of the original query.
        """
        self._load()
        keys = query_variants(form)
        headwords = {str(row['lemma']) for key in keys
                     for row in self._entries.get(key, ())}
        if headwords:
            return sorted(headwords)
        lemmas = {lemma for key in keys for lemma in self._form_lemmas.get(key, ())}
        if len(lemmas) != 1:
            return []
        return sorted({str(row['lemma']) for key in keys
                       for row in self._forms.get(key, ())})

    def expansion_forms_for_lemma(self, lemma: str) -> list[str]:
        """Source spellings excluding unresolved, conflicting lemma edges.

        ``forms_for_lemma`` remains the non-quarantined source inventory. This
        separate method is for automatic search expansion, not an assertion
        that excluded readings are false or that retained readings are true.
        """
        self._load()
        keys = set(query_variants(lemma))
        return [form for form in self.forms_for_lemma(lemma)
                if len(self._form_lemmas.get(normalize(form), ())) == 1
                and self._form_lemmas[normalize(form)] <= keys]

    def _candidate_inventory_keys(self, candidate: Mapping[str, Any]) -> set[tuple[str, str, str]]:
        keys = self._inventory_keys.get(candidate['lemma'], set())
        if candidate['match_kind'] == 'lexicon_headword':
            # A dictionary headword does not identify a treebank homograph.
            # Keep every numbered source identity separate in the response.
            return set(keys)
        # Raw variants and source lists are independently flattened for the
        # old candidate UI. Their Cartesian product is NOT provenance. Retain
        # only the identity tuples of rows that actually built this candidate.
        return set(candidate.get('_inventory_identity_keys', ())) & keys

    def _observed_form_groups(self, candidates: list[dict[str, Any]],
                              query_lemma_ambiguous: bool) -> list[dict[str, Any]]:
        """Expose source inventories, never a generated or contextual paradigm.

        Inventory membership uses exact NFC lemma/raw/source identities. The
        source-local numeric suffix is not silently linked to another source's
        homograph numbering. Unnumbered rows stay unnumbered. These inventories
        cover the whole imported index, not just the selected author/passage.
        """
        matches: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for index, candidate in enumerate(candidates):
            if candidate['match_kind'] == 'lexicon_headword':
                match = {field: candidate[field] for field in
                         ('match_kind', 'edit_distance', 'matched_form', 'matched_form_variants')}
                match['candidate_index'] = index
                for key in self._candidate_inventory_keys(candidate):
                    matches[key].append(match)
                continue
            # A displayed candidate may merge spellings from different source
            # identities and edit distances. Preserve their actual pairings in
            # the inventory explanation instead of copying flattened variants.
            identity_matches: dict[tuple[tuple[str, str, str], int], set[str]] = defaultdict(set)
            for item in candidate['_inventory_match_rows']:
                identity_matches[(item['identity_key'], item['edit_distance'])].add(item['matched_form'])
            for (key, distance), spellings in sorted(identity_matches.items()):
                variants = sorted(spellings, key=lambda value: (normalize(value), value))
                matches[key].append({'candidate_index': index, 'match_kind': 'indexed_form',
                                     'edit_distance': distance, 'matched_form': variants[0],
                                     'matched_form_variants': variants})
        groups = []
        for key, candidate_matches in sorted(matches.items()):
            lemma, raw, source = key
            form_refs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
            for row in self._inventory_rows[key]:
                ref = {field: row.get(field) for field in
                       ('source', 'source_url', 'analysis', 'analysis_format', 'license', 'quality')}
                # Canonical sorting makes both truncation and source ordering
                # stable regardless of ingestion/file order.
                ref_key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
                location_summary = row['_location_summary']
                shown_locations = location_summary['_locations']
                ref.update({
                    'locations': [dict(zip(('citation', 'document_id', 'sentence_id', 'token_id'),
                                           (value or None for value in location)))
                                  for location in shown_locations],
                    'location_total': location_summary['location_total'],
                    'locations_shown': len(shown_locations),
                    'locations_truncated': location_summary['location_total'] > len(shown_locations),
                })
                form_refs[str(row['form'])][ref_key] = ref
            spellings = sorted(form_refs, key=lambda value: (normalize(value), value))
            forms = []
            for spelling in spellings[:50]:
                refs = form_refs[spelling]
                shown_refs = [refs[ref_key] for ref_key in sorted(refs)[:10]]
                forms.append({'form': spelling, 'source_refs': shown_refs,
                              'source_ref_total': len(refs), 'source_refs_shown': len(shown_refs),
                              'source_refs_truncated': len(refs) > len(shown_refs)})
            unnumbered_ambiguity = raw == lemma and any(
                other[1] != lemma and other[2] == source
                for other in self._inventory_keys[lemma])
            groups.append({'lemma': lemma, 'lemma_raw': raw, 'source': source or None,
                           'query_relation': ('exact_or_folded_match' if any(
                               item['edit_distance'] == 0 for item in candidate_matches)
                               else 'spelling_suggestion'),
                           'query_lemma_ambiguous': query_lemma_ambiguous,
                           'identity_status': ('unnumbered_homograph_ambiguous' if unnumbered_ambiguity
                                               else 'source_lemma'),
                           'matches': candidate_matches, 'forms': forms,
                           'total_forms': len(spellings), 'shown_forms': len(forms),
                           'truncated': len(spellings) > len(forms),
                           'complete_paradigm': False, 'scope': 'whole_imported_index'})
        return groups

    def _near_keys(self, key: str, cutoff: int) -> list[tuple[int, str]]:
        pool: set[str] = set()
        if len(key) < 5:
            for length in range(max(1, len(key) - cutoff), len(key) + cutoff + 1):
                pool.update(self._short.get((length, key[:1]), ()))
        else:
            grams = sorted(_trigrams(key), key=lambda gram: len(self._grams.get(gram, ())))
            for gram in grams[:5]:
                pool.update(self._grams.get(gram, ()))
            # Short keys may be within two edits of a five/six-letter query.
            if len(key) <= 6:
                for length in range(max(1, len(key) - cutoff), 5):
                    pool.update(self._short.get((length, key[:1]), ()))
        return sorted((d, candidate) for candidate in pool
                      if (d := _distance(key, candidate, cutoff)) <= cutoff)[:80]

    def analyze(self, form: str, passage: str | Mapping[str, Any] | None = None,
                occurrence_lookup: Callable[[str, int], list[dict[str, Any]]] | None = None,
                limit: int = 12) -> dict[str, Any]:
        self._load()
        variants = query_variants(form)
        normalized = variants[0] if variants else ""
        limit = max(1, min(int(limit), 50))
        context = dict(passage) if isinstance(passage, Mapping) else ({"text": passage} if passage else None)
        occurrences: list[dict[str, Any]] = []
        if occurrence_lookup and normalized:
            occurrences = occurrence_lookup(normalized, 30)
        annotated: dict[tuple[str, str], tuple[bool, bool]] = defaultdict(lambda: (False, False))
        passage_id = context.get("id") if context else None
        author_id = context.get("author_id") if context else None
        for row in occurrences:
            if not isinstance(row, dict) or not row.get("lemma") or not row.get("analysis"):
                continue
            identity = (normalize(str(row["lemma"])), str(row["analysis"]))
            in_passage, same_author = annotated[identity]
            in_passage |= bool(passage_id and row.get("passage_id") == passage_id)
            # A display-name match is not provenance. Same-author support
            # requires source-backed identifiers in both records.
            same_author |= bool(author_id and row.get("author_id") == author_id
                                and row.get("source_url"))
            annotated[identity] = (in_passage, same_author)

        matches: dict[str, tuple[int, int]] = {}
        for variant_index, key in enumerate(variants):
            matches.setdefault(key, (0, variant_index))
        if not any(key in self._forms or key in self._entries for key in matches):
            for variant_index, key in enumerate(variants):
                cutoff = 1 if len(key) < 6 else 2
                for distance, near in self._near_keys(key, cutoff):
                    old = matches.get(near)
                    if old is None or (distance, variant_index) < old:
                        matches[near] = (distance, variant_index)

        numbered: dict[tuple[str, str], set[str]] = defaultdict(set)
        for key in matches:
            for row in self._forms.get(key, ()):
                lemma_nfc = unicodedata.normalize("NFC", str(row["lemma"]))
                raw_nfc = unicodedata.normalize("NFC", str(row.get("lemma_raw") or lemma_nfc))
                if raw_nfc.startswith(lemma_nfc) and (marker := _HOMOGRAPH_NUMBER.search(raw_nfc[len(lemma_nfc):])):
                    numbered[(lemma_nfc, str(row.get("analysis")))].add(marker.group())
        ranked: list[tuple[tuple[Any, ...], tuple[str, str, str, str], dict[str, Any]]] = []
        for key, (distance, variant_index) in matches.items():
            for kind, rows in (("form", self._forms.get(key, ())), ("lemma", self._entries.get(key, ()))):
                for row in rows:
                    lemma = unicodedata.normalize("NFC", str(row.get("lemma", "")))
                    analysis = row.get("analysis") if kind == "form" else None
                    source_url = row.get("source_url")
                    raw_lemma = unicodedata.normalize("NFC", str(row.get("lemma_raw") or lemma))
                    suffix = (raw_lemma[len(lemma):] if raw_lemma.startswith(lemma) else "")
                    marker = suffix if suffix.isdigit() else ""
                    if not marker and len(numbered.get((lemma, str(analysis)), ())) == 1:
                        marker = next(iter(numbered[(lemma, str(analysis))]))
                    group = (kind, lemma, marker,
                             str(analysis) if kind == "form" else str(row.get("entry_id", "")))
                    if kind == "lemma":
                        possible_entries = [row]
                        gloss_row = row
                    else:
                        entries = self._entries.get(normalize(lemma), ())
                        exact_entries = [item for item in entries if
                                         unicodedata.normalize("NFC", str(item.get("lemma", ""))) ==
                                         unicodedata.normalize("NFC", lemma)]
                        possible_entries = exact_entries or entries
                        source_counts = Counter(str(item.get("source")) for item in possible_entries)
                        # LSJ and Autenrieth may each have one entry for a
                        # lemma; use the first only as a display default.
                        # Same-source homographs have no chosen gloss.
                        gloss_row = (possible_entries[0] if possible_entries and
                                     max(source_counts.values()) == 1 else None)
                    exact_surface = int(str(row.get("form", lemma)) == form)
                    matched_form = str(row.get("form", lemma))
                    passage_support, author_support = annotated[(normalize(lemma), str(analysis))]
                    reasons = []
                    if distance:
                        source_label = "indexed source form" if kind == "form" else "lexicon headword"
                        reasons.append(f"possible spelling match ({distance} edit{'s' if distance != 1 else ''})"
                                       f" to {source_label} {matched_form}")
                    elif variant_index:
                        reasons.append("alternate transliteration")
                    elif exact_surface:
                        reasons.append("exact indexed source form" if kind == "form" else "exact lexicon headword")
                    else:
                        reasons.append("diacritic/sigma-folded attested form" if kind == "form" else "diacritic/sigma-folded headword")
                    if passage_support:
                        reasons.append("annotated parse in this passage")
                    elif author_support:
                        reasons.append("annotated parse in this author's corpus")
                    candidate: dict[str, Any] = {"lemma": lemma, "analysis": analysis,
                                                 "_inventory_identity_keys": [(lemma, raw_lemma, str(row.get('source') or ''))] if kind == 'form' else [],
                                                 "_inventory_match_rows": [{'identity_key': (lemma, raw_lemma, str(row.get('source') or '')), 'matched_form': matched_form, 'edit_distance': distance}] if kind == 'form' else [],
                                                 "matched_form": matched_form,
                                                 "matched_form_variants": [matched_form],
                                                 "match_kind": "indexed_form" if kind == "form" else "lexicon_headword",
                                                 "edit_distance": distance,
                                                 "gloss": gloss_row.get("gloss") if gloss_row else row.get("gloss"),
                                                 "entry_text": gloss_row.get("entry_text") if gloss_row else None,
                                                 "source_url": source_url,
                                                 "source": row.get("source"),
                                                 "license": row.get("license"),
                                                 "gloss_license": gloss_row.get("license") if gloss_row else None,
                                                 "analysis_format": row.get("analysis_format"),
                                                 "analysis_text": (describe_postag(str(analysis)) if
                                                    kind == "form" and "Perseus treebank" in
                                                    str(row.get("analysis_format", "")) else None),
                                                 "quality": row.get("quality"),
                                                 "supporting_sources": [],
                                                 "lemma_raw_variants": [str(row.get("lemma_raw") or row.get("lemma"))],
                                                 "lexicon_entry_ids": [str(item.get("id") or
                                                     f"{item.get('source_url')}#{item.get('entry_id')}")
                                                     for item in possible_entries],
                                                 "reason": "; ".join(reasons)}
                    if gloss_row:
                        candidate["gloss_entry_id"] = str(gloss_row.get("id") or
                            f"{gloss_row.get('source_url')}#{gloss_row.get('entry_id')}")
                    if kind == "form":
                        candidate["attested_form"] = row.get("form")
                        if row.get("lemma_raw") and row.get("lemma_raw") != lemma:
                            candidate["lemma_raw"] = row.get("lemma_raw")
                    elif row.get("entry_id"):
                        candidate["entry_id"] = row.get("entry_id")
                    if gloss_row and gloss_row.get("source_url") != source_url:
                        candidate["gloss_source_url"] = gloss_row.get("source_url")
                        candidate["gloss_source"] = gloss_row.get("source")
                    sort_key = (distance, -int(passage_support), -int(author_support), -exact_surface,
                                variant_index, 0 if kind == "form" else 1,
                                lemma, str(analysis), str(source_url), str(row.get("entry_id", "")))
                    ranked.append((sort_key, group, candidate))
        ranked.sort(key=lambda item: item[0])
        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for _, group, candidate in ranked:
            source = {field: candidate.get(field) for field in
                      ("source", "source_url", "license", "analysis_format", "quality")}
            if group not in grouped:
                grouped[group] = candidate
            existing = grouped[group]
            for identity_key in candidate['_inventory_identity_keys']:
                if identity_key not in existing['_inventory_identity_keys']:
                    existing['_inventory_identity_keys'].append(identity_key)
            for match_row in candidate['_inventory_match_rows']:
                if match_row not in existing['_inventory_match_rows']:
                    existing['_inventory_match_rows'].append(match_row)
            if source["source_url"] and source not in existing["supporting_sources"]:
                existing["supporting_sources"].append(source)
            for raw_variant in candidate["lemma_raw_variants"]:
                if raw_variant not in existing["lemma_raw_variants"]:
                    existing["lemma_raw_variants"].append(raw_variant)
            for matched_variant in candidate["matched_form_variants"]:
                if matched_variant not in existing["matched_form_variants"]:
                    existing["matched_form_variants"].append(matched_variant)
            if not existing.get("lemma_raw") and candidate.get("lemma_raw"):
                existing["lemma_raw"] = candidate["lemma_raw"]
        all_candidates = list(grouped.values())
        # Check the complete candidate set before display truncation. Numeric
        # homograph identifiers are source-local; unnumbered NFC identities may
        # share a legacy list across sources, but never across accents/case.
        query_identities: set[tuple[str, str, str]] = set()
        for candidate in all_candidates:
            if candidate['edit_distance'] != 0:
                continue
            keys = self._candidate_inventory_keys(candidate)
            for lemma, raw, source in keys:
                query_identities.add((lemma, raw, source if raw != lemma else ''))
            if not keys:
                query_identities.add((candidate['lemma'], candidate['lemma'], ''))
        candidates = all_candidates[:limit]
        # Determine eligibility against the complete index, not the truncated
        # UI candidates. A low display limit must not erase conflicting evidence.
        expansion_lemmas = set(self.expansion_lemmas_for_form(form))
        for candidate in candidates:
            conflicting = sorted(self._form_lemmas.get(normalize(candidate['matched_form']), ()))
            candidate['lemma_link_status'] = (
                'ambiguous_source_lemmas' if len(conflicting) > 1 else
                'single_indexed_lemma' if conflicting else 'headword_only')
            candidate['conflicting_lemma_keys'] = conflicting if len(conflicting) > 1 else []
            candidate['automatic_expansion_eligible'] = (
                candidate['edit_distance'] == 0 and candidate['lemma'] in expansion_lemmas)
        lexicon_entries: dict[str, dict[str, Any]] = {}
        quotation_entries: list[dict[str, Any]] = []
        try:
            from .lexicon_render import render_source_record
        except ImportError:
            render_source_record = None
        for candidate in candidates:
            for entry in self._entries.get(normalize(candidate["lemma"]), ()):
                entry_id = str(entry.get("id") or
                               f"{entry.get('source_url')}#{entry.get('entry_id')}")
                if entry_id not in candidate["lexicon_entry_ids"]:
                    continue
                quotation_entries.append(entry)
                display_entry = {field: entry.get(field) for field in
                                             ("id", "entry_id", "lemma", "gloss", "entry_text",
                                              "source", "source_url", "entry_url")}
                if render_source_record:
                    display_entry.update(render_source_record(entry))
                else:
                    display_entry.update({"rendered_entry_text": None,
                                          "rendering_method": None,
                                          "rendering_warning": "The Beta Code renderer is unavailable."})
                lexicon_entries[entry_id] = display_entry
        for candidate in candidates:
            entry = lexicon_entries.get(candidate.get("gloss_entry_id"))
            candidate["rendered_entry_text"] = entry.get("rendered_entry_text") if entry else None
            candidate["rendering_method"] = entry.get("rendering_method") if entry else None
            if entry and entry.get('definition_excerpt'):
                candidate['definition_excerpt'] = entry['definition_excerpt']
                candidate['definition_excerpt_provenance'] = entry['definition_excerpt_provenance']
        observed_form_groups = self._observed_form_groups(candidates, len(query_identities) > 1)
        for candidate in all_candidates:
            candidate.pop('_inventory_identity_keys', None)
            candidate.pop('_inventory_match_rows', None)
        # Compatibility field, deliberately conservative: a nearby spelling's
        # inventory is never an inventory of the query. Ambiguous exact queries
        # also have no flat list. Consumers should prefer the scoped groups.
        attested_forms: set[str] = set()
        if len(query_identities) == 1 and any(
                candidate['automatic_expansion_eligible'] for candidate in candidates):
            for group in observed_form_groups:
                if group['query_relation'] == 'exact_or_folded_match' and group['identity_status'] == 'source_lemma':
                    key = (group['lemma'], group['lemma_raw'], group['source'] or '')
                    attested_forms.update(str(row['form']) for row in self._inventory_rows[key])
        legacy_total = len(attested_forms)
        attested_forms = set(sorted(attested_forms, key=lambda item: (normalize(item), item))[:100])
        warnings = []
        quarantined = [dict(row) for key in dict.fromkeys(variants)
                       for row in self._quarantined_forms.get(key, ())]
        if quarantined:
            warnings.append('A reviewed source annotation mismatch was quarantined: it cannot supply a parsing candidate, dictionary gloss, form inventory, or automatic expansion. The original source record is retained separately; no corrected parse was invented.')
        fuzzy_only = bool(candidates) and all(candidate["edit_distance"] > 0 for candidate in candidates)
        if any(candidate['lemma_link_status'] == 'ambiguous_source_lemmas'
               for candidate in candidates):
            subject = ('Some nearby spellings have conflicting lemma attributions; this does not establish conflicting parses of the queried form. '
                       if fuzzy_only else 'The indexed form has conflicting lemma attributions. ')
            warnings.append(subject + 'These may reflect legitimate homography or a source error; all readings are retained, but unresolved links do not drive automatic lemma expansion. Search a headword explicitly to choose a lemma.')
        if fuzzy_only:
            warnings.append("No exact indexed morphological analysis was found for this form. The following analyses belong to nearby spellings, not necessarily the queried form.")
        if not self.form_count:
            warnings.append("No attested form index is available; only sourced headwords can be returned.")
        if not candidates:
            warnings.append("No sourced parsing or headword match was found.")
        if context and candidates and not any(in_passage for in_passage, _ in annotated.values()):
            warnings.append("Context shown; these analyses are alternatives, not a resolved sense.")
        if candidates:
            warnings.append("Listed forms come only from indexed source texts, not a complete dialect paradigm.")
        if any(entry.get("rendering_warning") for entry in lexicon_entries.values()):
            warnings.append("Some dictionary display text could not be rendered from local TEI; raw entry text remains available.")
        analysis_match_status = (
            "spelling_suggestions_only" if fuzzy_only else
            "source_analysis_available" if any(candidate["analysis"] for candidate in candidates) else
            "headword_only" if candidates else "no_match"
        )
        from .lexical_quotes import lookup_quotes
        lexical_evidence = lookup_quotes(form, context, quotation_entries)
        return {"form": form, "normalized": normalized,
                "match_status": "spelling_suggestions_only" if fuzzy_only else
                    ("indexed_match" if candidates else "no_match"),
                "analysis_match_status": analysis_match_status,
                "candidates": candidates,
                "quarantined_source_analyses": quarantined,
                "expansion_lemmas": sorted(expansion_lemmas),
                "lexicon_entries": list(lexicon_entries.values()),
                "lexical_evidence": lexical_evidence,
                "observed_form_groups": observed_form_groups,
                "attested_forms": sorted(attested_forms, key=lambda item: (normalize(item), item)),
                "attested_forms_policy": "exact_unambiguous_eligible_lemma_only; prefer source-scoped observed_form_groups",
                "attested_forms_total": legacy_total,
                "attested_forms_truncated": legacy_total > len(attested_forms),
                "occurrences": occurrences, "context": context,
                "method": "attested-form lookup with folded/transliterated keys and bounded edit distance",
                "warnings": warnings}


__all__ = ["Morphology", "normalize", "tokenize", "query_variants", "describe_postag"]
