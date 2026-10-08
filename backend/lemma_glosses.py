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

from .interlinear import gloss_from_sense, sense_class_compatible, sense_form_compatible, canonical_features
from .short_gloss import NON_NUMERAL_POS, corroborated_choice, dictionary_rank, letter_or_numeral_entry, metalanguage_only

VERSION = "parser-lemma-headword-gloss-v2"
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
    usable = []
    for source, rows in by_source.items():
        if pos in NON_NUMERAL_POS:
            rows = [entry for entry in rows if not letter_or_numeral_entry(entry)]
        if len(rows) != 1:
            skipped.append({"source": source, "reason": "homograph_entries_unresolved" if rows else "letter_or_numeral_entry",
                            "entry_ids": [r.get("id") for r in rows]})
            continue
        senses = _valid_senses(rows[0])
        eligible = [sense for sense in senses if sense_form_compatible(sense, token, candidate=candidate)
                    and not metalanguage_only(sense["text"])]
        # A preposition skips the dictionary's adverb-labelled senses and vice versa.
        eligible = [sense for sense in eligible if sense_class_compatible(sense, rows[0], pos)] or eligible
        if not eligible:
            skipped.append({"source": source, "reason": "no_extracted_dictionary_sense", "entry_ids": [rows[0].get("id")]})
            continue
        usable.append((rows[0], eligible))
    if not usable:
        return None, [], skipped
    # Prefer the sense and head phrase another dictionary confirms (Latin
    # equivalents and stray description words are in no other entry).
    texts = {entry.get("id"): str(entry.get("rendered_entry_text") or entry.get("entry_text") or "") for entry in entries}
    groups = [(entry.get("source"), eligible,
               [text for other, text in texts.items() if other != entry.get("id")
                and next((e.get("source") for e in entries if e.get("id") == other), None) != entry.get("source")])
              for entry, eligible in usable]
    choice = corroborated_choice(groups)
    if choice:
        sense, phrase = choice
        entry, eligible = next((entry, eligible) for entry, eligible in usable if sense in eligible)
        chosen = {**sense, "_corroborated_phrase": phrase}
        return entry, [chosen, *[item for item in eligible if item is not sense]], skipped
    return usable[0][0], usable[0][1], skipped


GREEK_WORD = r"[\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f\u02bc\u2019]+"
# A stub entry that only points to another headword, read from the entry's own
# opening words: "γᾶ, Dor. for γῆ", "πεδά, Aeol. = μετά", "ἐς: see εἰς".
CROSS_REFERENCE = re.compile(r"(?:=|\bfor|\bv\.|\bsee)\s+(" + GREEK_WORD + r")")


# Vowel-length marks the parser prints on lemmas (πῑ́νω) that dictionary
# headwords do not carry.
_LENGTH_MARKS = ("̄", "̆")
ELISION_MARKS = "’᾽'ʼ᾽"


def headword_key(lemma):
    """Lookup spelling for a parse lemma: homograph digits dropped, a grave
    accent written as the dictionary-form acute (καὶ -> καί), macrons and
    breves removed (πῑ́νω -> πίνω)."""
    value = HOMOGRAPH_DIGITS.sub("", _nfc(lemma)).strip()
    decomposed = unicodedata.normalize("NFD", value).replace("̀", "́")
    for mark in _LENGTH_MARKS:
        decomposed = decomposed.replace(mark, "")
    # A breathing or apostrophe printed before the initial letter (̓Αλέξανδρος,
    # ʼἀλέξανδρος) belongs on that letter: move a breathing onto it, drop an
    # apostrophe.
    lead = ""
    while decomposed and (not unicodedata.category(decomposed[0]).startswith("L") or decomposed[0] in "ʼ’'"):
        if decomposed[0] in ("̓", "̔"):
            lead = decomposed[0]
        decomposed = decomposed[1:]
    if lead and decomposed and "̓" not in decomposed[1:3] and "̔" not in decomposed[1:3]:
        decomposed = decomposed[0] + lead + decomposed[1:]
    return unicodedata.normalize("NFC", decomposed)


_FURTHER_TARGET = re.compile(r"\s*(?:,|\bor\b|\band\b)\s*(" + GREEK_WORD + r")")


def _cross_reference(entries):
    """(entry, [targets], printed relation) for the first pure pointer entry.

    The targets are the Greek words printed right after the relation, joined
    by commas or "or" ("Aeol. for ἀώς, ἠώς"), in their printed order.
    """
    for entry in sorted(entries, key=lambda item: dictionary_rank(item.get("source"))):
        if entry.get("dictionary_senses"):
            continue
        text = str(entry.get("rendered_entry_text") or entry.get("entry_text") or "")
        opening = text[:140]
        match = CROSS_REFERENCE.search(opening)
        if match:
            own = _nfc(entry.get("lemma"))
            targets, end = [], match.end()
            first = _nfc(match.group(1)).rstrip(",.;:\u02bc\u2019")
            if first and first != own:
                targets.append(first)
            while len(targets) < 4:
                further = _FURTHER_TARGET.match(opening, end)
                if not further:
                    break
                word = _nfc(further.group(1)).rstrip(",.;:\u02bc\u2019")
                if word and word != own and word not in targets:
                    targets.append(word)
                end = further.end()
            if targets:
                return entry, targets, opening[:end].strip()
    return None


def _fold(text):
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in decomposed if unicodedata.category(c).startswith("L")).lower().replace("ς", "σ")


# Dialect vowel and consonant correspondences between a dialect spelling and
# the Attic headword a dictionary lists (Buck, Greek Dialects §§ 8, 41, 81-86).
# Each is tried on a lemma that has no usable headword of its own; a variant
# counts only when it is itself a printed dictionary headword.
DIALECT_HEADWORD_RULES = (
    ("η", "α", "ionic_eta_for_attic_alpha", "Ionic η where Attic has ᾱ (τρηχύς: τραχύς)"),
    ("α", "η", "doric_aeolic_alpha_for_eta", "Doric/Aeolic ᾱ where Attic-Ionic has η (μάτηρ: μήτηρ)"),
    ("ει", "ε", "ionic_ei_lengthening", "Ionic/epic ει by compensatory lengthening where Attic has ε (ξεῖνος: ξένος)"),
    ("ου", "ο", "ionic_ou_lengthening", "Ionic/epic ου by compensatory lengthening where Attic has ο (μοῦνος: μόνος)"),
    ("σσ", "ττ", "attic_tt_for_ss", "Attic ττ where other dialects have σσ (θάλασσα: θάλαττα)"),
    ("ρσ", "ρρ", "attic_rr_for_rs", "Attic ρρ where other dialects have ρσ (θάρσος: θάρρος)"),
    ("ω", "ου", "doric_omega_for_ou", "Doric ω where Attic has ου (Μῶσα: Μοῦσα)"),
    ("οι", "ου", "aeolic_oi_for_ou", "Aeolic οι where Attic has ου (Μοῖσα: Μοῦσα)"),
    ("ευ", "ου", "ionic_eu_for_ou", "Ionic ευ (contracted εο) where Attic has ου (ποιεῦμεν: ποιοῦμεν)"),
)


def dialect_headword_variants(headword):
    """Labelled one-substitution variants of a headword, in rule order.

    Each rule rewrites one occurrence at a time (and all at once), on the
    accent-free letters; the caller matches the result against folded
    dictionary headwords, so the accent of the target headword is its own.
    """
    letters = _fold(headword)
    capital = headword[:1] != headword[:1].lower()
    found, seen = [], {letters}
    for old, new, rule, note in DIALECT_HEADWORD_RULES:
        positions = [i for i in range(len(letters)) if letters.startswith(old, i)]
        options = [letters[:i] + new + letters[i + len(old):] for i in positions]
        if len(positions) > 1:
            options.append(letters.replace(old, new))
        for option in options:
            if option not in seen:
                seen.add(option)
                found.append({"key": option.capitalize() if capital else option, "rule": rule, "note": note})
    return found


def elided_lemma_candidates(lemma):
    """A lemma printed with an elision mark (τ’) names an elided word; the
    headword is the stem plus the elided vowel (τε). Every vowel is offered;
    the caller keeps the result only when exactly one is a headword."""
    stem = _nfc(lemma).rstrip(ELISION_MARKS)
    if not stem or stem == _nfc(lemma):
        return []
    return [stem + vowel for vowel in ("ε", "α", "ο", "ι", "έ", "ά", "ό", "ί", "ή")]


def stem_shared(form, lemma):
    """The printed form and a lemma share a run of letters (a guard against a
    model lemma that belongs to another word). Three letters, or two when
    either word has at most four letters."""
    a, b = _fold(form).replace("ξ", "κσ").replace("ψ", "πσ"), _fold(lemma).replace("ξ", "κσ").replace("ψ", "πσ")
    if not a or not b:
        return False
    need = 2 if min(len(a), len(b)) <= 4 else 3
    need = min(need, len(a), len(b))
    if any(b[j:j + need] in a for j in range(len(b) - need + 1)):
        return True
    # Vowel gradation (λείπω / ἔλιπον, φεύγω / ἔφυγον): the lemma's first
    # consonants recur, in order, in the form.
    vowels = "αεηιουω"
    skeleton_a = "".join(c for c in a if c not in vowels)
    skeleton_b = "".join(c for c in b if c not in vowels)[:3]
    k = min(3, len(skeleton_b))
    return k >= 2 and skeleton_b[:k] in skeleton_a


def _initial_upper(text):
    letters = [c for c in unicodedata.normalize("NFD", str(text or "")).lstrip("†") if unicodedata.category(c).startswith("L")]
    return bool(letters) and letters[0].isupper()


def _resolve_direct(headword, row, lookup, *, marked=False, number=None, accept_folded=True):
    found = lookup(headword) or {}
    entries = found.get("entries") or []
    if not accept_folded and found.get("match") != "exact_headword":
        entries = []
    if found.get("match") == "folded_headword" and _initial_upper(headword):
        # A proper name (Ἀνακτορία) never takes the meaning of a common noun that
        # differs from it only in case or accent (ἀνακτορία "management").
        from .short_gloss import entry_names_a_being
        entries = [e for e in entries if _initial_upper(e.get("lemma")) or entry_names_a_being(e)]
    if found.get("match") == "folded_headword" and len({headword_key(e.get("lemma")).casefold() for e in entries}) > 1:
        # Several accent-distinct headwords share the letters (ὄρος / ὀρός):
        # the folded key does not say which one is meant.
        return None, [], [{"reason": "folded_headword_ambiguous", "entry_ids": [e.get("id") for e in entries]}], found, entries
    entry, senses, skipped = choose(entries, row, homograph_marked=marked, homograph_number=number, headword=headword)
    return entry, senses, skipped, found, entries


def resolve(lemma, row, lookup, form_lemmas=None):
    """Entry + eligible senses for a parse lemma, with a labelled lookup trail.

    ``lookup`` is a (cached) Morphology.headword_entries. Tried in order, each
    labelled in the result:

    1. the lemma's own headword (digits, grave accent, length marks normalised);
    2. one explicit source cross-reference ("= X", "for X", "v. X", "see X")
       when the lemma's own entries have no English definition;
    3. an elided lemma (τ’) restored to the one headword its stem can be;
    4. the lemma read as an attested form (Μοῦσαι, a plural printed as the
       lemma) whose recorded analyses all name one other lemma;
    5. Lesbian psilosis in the lemma itself (ὀ -> ὁ);
    6. dialect correspondences (τρηχύς -> τραχύς) that give a printed headword.
    """
    marked = bool(HOMOGRAPH_DIGITS.search(lemma))
    headword = headword_key(lemma)
    number = HOMOGRAPH_DIGITS.search(lemma)
    entry, senses, skipped, found, entries = _resolve_direct(
        headword, row, lookup, marked=marked, number=number.group() if number else None)
    info = {"version": VERSION, "lemma": lemma, "headword_queried": headword,
            "headword_match": found.get("match"), "entry_ids": [e.get("id") for e in entries],
            "skipped": skipped, "contextually_selected": False}
    homograph = any(item["reason"] == "homograph_entries_unresolved" for item in skipped)
    folded_ambiguous = any(item["reason"] == "folded_headword_ambiguous" for item in skipped)
    if entry is None and entries and not homograph and not folded_ambiguous:
        pointer = _cross_reference(entries)
        if pointer:
            source_entry, targets, relation = pointer
            # "Aeol. for ἀώς, ἠώς": the printed targets are tried in order,
            # each one hop, until one has an English definition.
            for target in targets:
                target_found = lookup(target) or {}
                target_entries = [e for e in target_found.get("entries") or []
                                  if target_found.get("match") == "exact_headword"]
                entry, senses, target_skipped = choose(target_entries, row, homograph_marked=False)
                info["cross_reference"] = {"from_entry_id": source_entry.get("id"), "printed_relation": relation,
                                           "target_headword": target, "printed_targets": targets,
                                           "target_entry_ids": [e.get("id") for e in target_entries],
                                           "target_skipped": target_skipped, "method": "explicit_source_cross_reference_one_hop"}
                if entry is not None:
                    break
    if entry is None and not homograph and not marked:
        entry, senses, normalisation = _normalised_headword(lemma, headword, row, lookup, form_lemmas)
        if normalisation:
            info["lemma_normalisation"] = normalisation
    if entry is None:
        info["status"] = "no_headword" if not entries else "unresolved"
    else:
        info.update(status="available", entry_id=entry.get("id"), dictionary=entry.get("source"),
                    headword=entry.get("lemma"))
    return entry, senses, info


def _normalised_headword(lemma, headword, row, lookup, form_lemmas):
    """Steps 3-5 of ``resolve``; returns (entry, senses, labelled trail)."""
    tried = []
    # 3. Elided lemma: exactly one restored vowel must give a usable headword.
    restored = []
    for option in elided_lemma_candidates(lemma):
        entry, senses, _, found, _ = _resolve_direct(option, row, lookup, accept_folded=False)
        if entry is not None:
            restored.append((option, entry, senses))
    if elided_lemma_candidates(lemma):
        tried.append({"rule": "elided_lemma_restored", "candidates": [item[0] for item in restored]})
        if len({_nfc(item[1].get("lemma")) for item in restored}) == 1:
            option, entry, senses = restored[0]
            return entry, senses, {"rule": "elided_lemma_restored", "from": lemma, "to": option,
                                   "note": "The parser's lemma is an elided spelling; the only headword its stem can restore is used",
                                   "tried": tried}
    # 4. The lemma as an attested form of exactly one other lemma.
    if form_lemmas is not None:
        try:
            others = [value for value in form_lemmas(headword) or [] if headword_key(value) != headword]
        except Exception:
            others = []
        # Case is not a lexical difference here (Μοῦσα / μοῦσα in different
        # annotation sets); the lemma's own capitalisation is kept.
        targets = {}
        for value in others:
            key = headword_key(value)
            if key.casefold() not in targets or (key[:1].isupper() == headword[:1].isupper()):
                targets[key.casefold()] = key
        targets = set(targets.values())
        tried.append({"rule": "lemma_as_attested_form", "candidates": sorted(targets)})
        if len(targets) == 1:
            target = targets.pop()
            entry, senses, _, _, _ = _resolve_direct(target, row, lookup, accept_folded=False)
            if entry is not None:
                return entry, senses, {"rule": "lemma_as_attested_form", "from": lemma, "to": target,
                                       "note": "The parser's lemma is itself a recorded inflected form; every recorded analysis of it names this headword",
                                       "tried": tried}
    # 5. Lesbian psilosis printed in the lemma itself (ὀ for the article ὁ):
    #    the rough-breathing spelling, as an exact headword.
    from .aeolic_variants import _initial_breathing_swap
    rough = _initial_breathing_swap(headword)
    if rough:
        entry, senses, _, _, _ = _resolve_direct(rough, row, lookup, accept_folded=False)
        tried.append({"rule": "aeolic_psilosis_lemma", "candidates": [rough] if entry is not None else []})
        if entry is not None:
            return entry, senses, {"rule": "aeolic_psilosis_lemma", "from": lemma, "to": rough,
                                   "note": "Lesbian psilosis: the lemma is printed with a smooth breathing where the headword has a rough one",
                                   "tried": tried}
    # 6. Dialect correspondences; the variant must be one unambiguous headword.
    hits = []
    # Short lemmas are left alone: a one-letter change to two or three letters
    # too easily lands on an unrelated word.
    for variant in (dialect_headword_variants(headword) if len(_fold(headword)) >= 4 else []):
        entry, senses, skipped, found, entries = _resolve_direct(variant["key"], row, lookup)
        if entry is not None:
            hits.append((variant, entry, senses))
            break
    tried.append({"rule": "dialect_headword", "candidates": [item[0]["key"] for item in hits]})
    if hits:
        variant, entry, senses = hits[0]
        return entry, senses, {"rule": variant["rule"], "from": lemma, "to": entry.get("lemma"),
                               "note": variant["note"], "tried": tried}
    return None, [], {"rule": None, "tried": tried}


def _syntax_rows(syntax):
    if not isinstance(syntax, dict) or syntax.get("state", syntax.get("status")) != "ready":
        return {}
    rows = {}
    for item in syntax.get("tokens") or []:
        if item.get("prediction_status") == "not_applicable" or not item.get("lemma"):
            continue
        rows[(item.get("absolute_start"), item.get("absolute_end"))] = item
    return rows


def _model_lemma(row, predictions):
    """The contextual model's lemma for this word, when the parse gave none."""
    item = predictions.get((row.get("start"), row.get("end"))) or predictions.get((row.get("start"), (row.get("end") or 0) - 1))
    if not item or item.get("text") not in (row.get("text"), (row.get("text") or "")[:-1], row.get("form")):
        return None
    lemma = _nfc(item.get("lemma"))
    if not lemma or not any(unicodedata.category(c).startswith("L") for c in lemma):
        return None
    return lemma


def _restore_elided(lemma, row, predictions, cached):
    options = {_fold(option) for option in elided_lemma_candidates(lemma)}
    predicted = _model_lemma(row, predictions)
    if predicted and _fold(headword_key(predicted)) in options:
        found = cached(headword_key(predicted))
        hits = [e for e in found.get("entries") or [] if found.get("match") == "exact_headword"]
        if hits:
            return hits[0], "elided_lemma_restored_by_model_lemma"
    entry, _, info = resolve(lemma, row, cached, None)
    if entry is not None and (info.get("lemma_normalisation") or {}).get("rule") == "elided_lemma_restored":
        return entry, "elided_lemma_restored"
    return None, None


ATTESTED_MIN_FORMS = 5


def attested_tie_lemma(row, attestations):
    """One lemma of a top-ranked tie that the source index attests when no other does.

    The tie group is the ranked parses within the homograph margin (as row_lemma).
    A lemma is chosen only if it has at least ATTESTED_MIN_FORMS recorded forms and
    every other tied lemma has none (κάτεσσαν: καθίζω, 32 recorded forms, against a
    parser-generated compound that no source records). Real ambiguities stay open.
    """
    ranking = row.get("morphology_ranking") or []
    if not ranking or not isinstance(ranking[0].get("score"), (int, float)):
        return None
    top = ranking[0]["score"]
    lemmas = {_nfc(item["lemma"]) for item in ranking if item.get("lemma")
              and isinstance(item.get("score"), (int, float)) and top - item["score"] < 0.5}
    if len(lemmas) < 2:
        return None
    counts = {}
    for lemma in lemmas:
        try:
            counts[lemma] = int(attestations(lemma) or 0)
        except Exception:
            return None
    attested = [lemma for lemma, count in counts.items() if count >= ATTESTED_MIN_FORMS]
    if len(attested) == 1 and all(count == 0 for lemma, count in counts.items() if lemma != attested[0]):
        return attested[0]
    return None


def attach_lemma_glosses(interlinear, lookup, limit=MAX_LOOKUPS, *, syntax=None, form_lemmas=None,
                         lemma_attestations=None):
    """Fill missing glosses from the parse lemma's dictionary headword.

    ``lookup(lemma)`` returns Morphology.headword_entries(lemma);
    ``form_lemmas(form)`` (optional) the lemmas recorded for an attested form.
    A row without any parse lemma may take the contextual model's lemma
    (``syntax`` is the analysis' syntax block) when that lemma is a printed
    dictionary headword sharing letters with the word; it is labelled
    ``syntax_model_lemma_dictionary_headword``. Returns a small summary for
    the response limits block.
    """
    cache, summary = {}, {"version": VERSION, "lookups": 0, "filled": 0, "unresolved": 0, "model_lemmas": 0}
    predictions = _syntax_rows(syntax)

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

    form_cache = {}

    def cached_forms(form):
        if form_lemmas is None:
            return []
        if form not in form_cache:
            try:
                form_cache[form] = list(form_lemmas(form) or [])
            except Exception:
                form_cache[form] = []
        return form_cache[form]

    for reading in (interlinear or {}).get("readings") or []:
        for row in reading.get("tokens") or []:
            if row.get("kind") != "word" or row.get("damaged_piece") or row.get("selection_basis") == "partial_word":
                continue
            gloss = row.get("gloss") or {}
            lemma, basis = row_lemma(row)
            model = None
            if not lemma and lemma_attestations is not None:
                lemma = attested_tie_lemma(row, lemma_attestations)
                if lemma:
                    basis = "top_ranked_tie_only_attested_lemma"
                    row["lemma"] = lemma
                    row["lemma_source"] = {"basis": basis, "note": (
                        "The top-ranked parses tie on several lemmas; only this one is attested in the "
                        "indexed source texts. The other parses stay listed.")}
            if not lemma:
                model = _model_lemma(row, predictions)
                # Parser lemmas, when there are any, bound the choice: a model
                # lemma that none of the ranked parses names is not used.
                ranked = {_fold(headword_key(item.get("lemma"))) for item in row.get("morphology_ranking") or []
                          if item.get("lemma")}
                form = row.get("form") or row.get("text") or ""
                if model and ranked and _fold(headword_key(model)) not in ranked:
                    model = None
                # Two surviving letters (ἔσ beside a gap) are too few to tie a
                # model lemma to the word.
                if model and len(_fold(form)) >= 3 and stem_shared(form, model):
                    lemma, basis = model, "syntax_model_lemma"
                else:
                    model = None
            if lemma and not model and _nfc(lemma)[-1:] in ELISION_MARKS:
                # The lemma is an elided spelling (τ’). A dictionary may even
                # print it as a headword; the full word is named only when the
                # contextual model's lemma is one of the restorations, or when
                # exactly one restoration is a headword.
                restored, label = _restore_elided(lemma, row, predictions, cached)
                if restored is not None:
                    row["lemma_source"] = {"basis": label, "printed_lemma": lemma,
                                           "headword": restored.get("lemma"), "entry_id": restored.get("id")}
                    row["lemma"] = lemma = restored.get("lemma")
                    basis = label
            if not lemma or (gloss.get("text") and not model):
                continue
            entry, senses, info = resolve(lemma, row, cached, cached_forms if form_lemmas is not None else None)
            info["lemma_basis"] = basis
            if model:
                if entry is None:
                    # An unverified model lemma is never shown on its own.
                    continue
                row["lemma"] = entry.get("lemma") or headword_key(model)
                row["lemma_source"] = {"basis": "syntax_model_lemma_dictionary_headword", "model_lemma": model,
                                       "headword": entry.get("lemma"), "entry_id": entry.get("id"),
                                       "note": "Lemma predicted by the contextual model and found as a printed dictionary headword; not a parser analysis."}
                summary["model_lemmas"] += 1
                if gloss.get("text"):
                    continue
            if entry is None:
                row["gloss"] = {**gloss, "lemma_dictionary": info}
                summary["unresolved"] += 1
                continue
            phrase = senses[0].get("_corroborated_phrase")
            senses = [{k: v for k, v in sense.items() if k != "_corroborated_phrase"} for sense in senses]
            chosen = gloss_from_sense(senses[0], senses, phrase=phrase)
            if model:
                selection = "syntax_model_lemma_dictionary_headword_first_sense_not_contextual"
            elif info.get("cross_reference"):
                selection = "parser_lemma_cross_referenced_headword_first_sense_not_contextual"
            elif info.get("lemma_normalisation", {}).get("rule"):
                selection = "parser_lemma_normalised_headword_first_sense_not_contextual"
            else:
                selection = "parser_lemma_dictionary_headword_first_sense_not_contextual"
            chosen.update(selection_basis=selection, lemma_dictionary=info)
            for key in ("conditional_on",):
                if key in gloss:
                    chosen[key] = gloss[key]
            from .short_gloss import normalise_gloss_case
            row["gloss"] = normalise_gloss_case(chosen, row.get("lemma"))
            summary["filled"] += 1
    return summary


__all__ = ["attach_lemma_glosses", "row_lemma", "choose", "resolve", "headword_key", "dialect_headword_variants",
           "elided_lemma_candidates", "stem_shared", "VERSION"]
