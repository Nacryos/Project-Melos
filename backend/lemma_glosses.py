"""Parser lemma -> dictionary headword -> first sourced English definition.

Runs after the interlinear projection, only for word rows that already carry a
parse lemma but no gloss (the parser's lemma had no dictionary entry joined to
its candidate, or the candidate pointed at an entry that could not be bound).
The lemma is looked up as a printed dictionary headword; the first extracted
definition of the first dictionary in DICTIONARY_ORDER that has exactly one
entry for it becomes the gloss. Dictionaries with several entries for the same
headword (homographs) are skipped, never guessed. The result is labelled a
dictionary first sense, not a contextual meaning. No text is generated.
"""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

from .interlinear import gloss_from_sense, sense_form_compatible, canonical_features
from .short_gloss import NON_NUMERAL_POS, dictionary_rank, letter_or_numeral_entry

VERSION = "parser-lemma-headword-gloss-v1"
MAX_LOOKUPS = 80
HOMOGRAPH_DIGITS = re.compile(r"\d+$")
_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _nfc(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def row_lemma(row):
    """The parse lemma shown for the row, or one lemma shared by the top parses."""
    if row.get("lemma"):
        return _nfc(row["lemma"]), "selected_parse_lemma"
    ranking = row.get("morphology_ranking") or []
    if ranking:
        top = ranking[0].get("score")
        if isinstance(top, (int, float)):
            lemmas = {_nfc(item.get("lemma")) for item in ranking
                      if item.get("lemma") and isinstance(item.get("score"), (int, float)) and top - item["score"] < 0.5}
            if len(lemmas) == 1:
                return lemmas.pop(), "top_ranked_parses_share_lemma"
    return None, None


def _valid_senses(entry):
    return [sense for sense in entry.get("dictionary_senses") or []
            if isinstance(sense, dict) and sense.get("id") and isinstance(sense.get("text"), str)
            and sense["text"].strip() and sense.get("evidence_type") == "dictionary_sense"
            and sense.get("source_url") and sense.get("source_locator")
            and _HEX.fullmatch(str(sense.get("raw_sha256") or ""))
            and (sense.get("lexicon_entry_id") or sense.get("entry_id")) in {entry.get("id"), entry.get("entry_id")}]


LSJ_KEYED = "LSJ (Logeion edition, H. Dik) TEI"


def _numbered_lsj_entry(entries, headword, number):
    """Morpheus numbers homographs with the Perseus LSJ entry keys (e.g.
    ἐρύω2 <-> key "e)ru/w2"), which the Logeion edition keeps. Return the one
    Logeion LSJ entry whose printed key carries the same headword and number."""
    from betacode import beta_to_uni
    found = []
    for entry in entries:
        key = str(entry.get("key") or "")
        match = re.fullmatch(r"(.*?)(\d+)", key)
        if entry.get("source") != LSJ_KEYED or not match or match.group(2) != number:
            continue
        if unicodedata.normalize("NFC", beta_to_uni(match.group(1))) == unicodedata.normalize("NFC", headword):
            found.append(entry)
    return found[0] if len(found) == 1 else None


def choose(entries, row, *, homograph_marked, homograph_number=None, headword=None):
    """First dictionary (in order) with exactly one entry and a usable sense."""
    by_source = {}
    for entry in sorted(entries, key=lambda item: dictionary_rank(item.get("source"))):
        by_source.setdefault(entry.get("source"), []).append(entry)
    pos = (row.get("features") or {}).get("POS")
    skipped = []
    if homograph_marked and homograph_number and headword:
        numbered = _numbered_lsj_entry(entries, headword, homograph_number)
        senses = _valid_senses(numbered) if numbered else []
        if senses:
            return numbered, senses, [{"source": LSJ_KEYED, "reason": "parser_homograph_number_matches_lsj_key",
                                       "entry_ids": [numbered.get("id")], "key": numbered.get("key")}]
    if homograph_marked and any(len(rows) > 1 for rows in by_source.values()):
        # The parser named one of several homographs; a dictionary that prints
        # them separately shows the choice is real. Do not pick one.
        return None, [], [{"source": source, "reason": "homograph_entries_unresolved",
                           "entry_ids": [r.get("id") for r in rows]} for source, rows in by_source.items() if len(rows) > 1]
    token = {"text": row.get("text"), "form": row.get("form") or row.get("text")}
    candidate = {"features": deepcopy(row.get("features") or {})}
    for source, rows in by_source.items():
        if pos in NON_NUMERAL_POS:
            rows = [entry for entry in rows if not letter_or_numeral_entry(entry)]
        if len(rows) != 1:
            skipped.append({"source": source, "reason": "homograph_entries_unresolved" if rows else "letter_or_numeral_entry",
                            "entry_ids": [r.get("id") for r in rows]})
            continue
        senses = _valid_senses(rows[0])
        eligible = [sense for sense in senses if sense_form_compatible(sense, token, candidate=candidate)]
        if not eligible:
            skipped.append({"source": source, "reason": "no_extracted_dictionary_sense", "entry_ids": [rows[0].get("id")]})
            continue
        return rows[0], eligible, skipped
    return None, [], skipped


GREEK_WORD = r"[\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f\u02bc\u2019]+"
# A stub entry that only points to another headword, read from the entry's own
# opening words: "γᾶ, Dor. for γῆ", "πεδά, Aeol. = μετά", "ἐς: see εἰς".
CROSS_REFERENCE = re.compile(r"(?:=|\bfor|\bv\.|\bsee)\s+(" + GREEK_WORD + r")")


def headword_key(lemma):
    """Lookup spelling for a parse lemma: homograph digits dropped, a grave
    accent written as the dictionary-form acute (καὶ -> καί)."""
    value = HOMOGRAPH_DIGITS.sub("", _nfc(lemma)).strip()
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", value).replace("\u0300", "\u0301"))


def _cross_reference(entries):
    """(entry, target, printed relation) for the first pure pointer entry."""
    for entry in sorted(entries, key=lambda item: dictionary_rank(item.get("source"))):
        if entry.get("dictionary_senses"):
            continue
        text = str(entry.get("rendered_entry_text") or entry.get("entry_text") or "")
        opening = text[:140]
        match = CROSS_REFERENCE.search(opening)
        if match:
            target = _nfc(match.group(1)).rstrip(",.;:\u02bc\u2019")
            if target and target != _nfc(entry.get("lemma")):
                return entry, target, opening[:match.end()].strip()
    return None


def resolve(lemma, row, lookup):
    """Entry + eligible senses for a parse lemma, with a labelled lookup trail.

    ``lookup`` is a (cached) Morphology.headword_entries. One explicit source
    cross-reference ("= X", "for X", "v. X", "see X") is followed when the
    lemma's own entries have no English definition.
    """
    marked = bool(HOMOGRAPH_DIGITS.search(lemma))
    headword = headword_key(lemma)
    found = lookup(headword) or {}
    entries = found.get("entries") or []
    number = HOMOGRAPH_DIGITS.search(lemma)
    entry, senses, skipped = choose(entries, row, homograph_marked=marked,
                                    homograph_number=number.group() if number else None, headword=headword)
    info = {"version": VERSION, "lemma": lemma, "headword_queried": headword,
            "headword_match": found.get("match"), "entry_ids": [e.get("id") for e in entries],
            "skipped": skipped, "contextually_selected": False}
    if entry is None and entries and not any(item["reason"] == "homograph_entries_unresolved" for item in skipped):
        pointer = _cross_reference(entries)
        if pointer:
            source_entry, target, relation = pointer
            target_found = lookup(target) or {}
            target_entries = [e for e in target_found.get("entries") or []
                              if target_found.get("match") == "exact_headword"]
            entry, senses, target_skipped = choose(target_entries, row, homograph_marked=False)
            info["cross_reference"] = {"from_entry_id": source_entry.get("id"), "printed_relation": relation,
                                       "target_headword": target, "target_entry_ids": [e.get("id") for e in target_entries],
                                       "target_skipped": target_skipped, "method": "explicit_source_cross_reference_one_hop"}
    if entry is None:
        info["status"] = "no_headword" if not entries else "unresolved"
    else:
        info.update(status="available", entry_id=entry.get("id"), dictionary=entry.get("source"))
    return entry, senses, info


def attach_lemma_glosses(interlinear, lookup, limit=MAX_LOOKUPS):
    """Fill missing glosses from the parse lemma's dictionary headword.

    ``lookup(lemma)`` returns Morphology.headword_entries(lemma). Returns a
    small summary for the response limits block.
    """
    cache, summary = {}, {"version": VERSION, "lookups": 0, "filled": 0, "unresolved": 0}

    def cached(headword):
        if headword not in cache:
            if len(cache) >= limit:
                return {"status": "request_limit", "entries": []}
            try:
                cache[headword] = lookup(headword) or {}
            except Exception:  # lookup failure never invents or blocks a reading
                cache[headword] = {"status": "unavailable", "entries": []}
            summary["lookups"] += 1
        return cache[headword]

    for reading in (interlinear or {}).get("readings") or []:
        for row in reading.get("tokens") or []:
            if row.get("kind") != "word" or row.get("damaged_piece") or row.get("selection_basis") == "partial_word":
                continue
            gloss = row.get("gloss") or {}
            if gloss.get("text"):
                continue
            lemma, basis = row_lemma(row)
            if not lemma:
                continue
            entry, senses, info = resolve(lemma, row, cached)
            info["lemma_basis"] = basis
            if entry is None:
                row["gloss"] = {**gloss, "lemma_dictionary": info}
                summary["unresolved"] += 1
                continue
            chosen = gloss_from_sense(senses[0], senses)
            chosen.update(selection_basis=("parser_lemma_cross_referenced_headword_first_sense_not_contextual"
                                           if info.get("cross_reference") else
                                           "parser_lemma_dictionary_headword_first_sense_not_contextual"),
                          lemma_dictionary=info)
            for key in ("conditional_on",):
                if key in gloss:
                    chosen[key] = gloss[key]
            row["gloss"] = chosen
            summary["filled"] += 1
    return summary


__all__ = ["attach_lemma_glosses", "row_lemma", "choose", "resolve", "headword_key", "VERSION"]
