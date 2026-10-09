"""Dialect grammar in parse ranking (release R).

The parser (Morpheus) labels many analyses with the dialects in which the spelling has that reading
("Doric Aeolic", "Attic epic Ionic"); the contextual model (odyCy) was trained on Attic-Ionic and epic
treebanks and reads a Lesbian spelling as the Attic word it resembles (αἰ as the article αἱ, ἄγην as the
noun ἄγη). In a passage whose author writes Lesbian Aeolic or a literary Doric (backend.passage_dialect),
these general rules gate and weigh the candidate parses of a word before the context model ranks them.
Every rule is stated for a class of forms; none names a word. Sources: Campbell, Greek Lyric Poetry (1967)
pp. 262-264, "features of the Lesbian dialect" §§ 1-10 (§ 1 no initial aspirates; § 2 recessive accent;
§ 3 vowels: ᾱ kept, η = ει in infinitives ἔχην, οισ = ουσ in λίποισα; § 6 contracted verbs in -μι, infinitive
φίλην; § 7 accusative plural -αις -οις, dative plural -αισι -οισι; § 8 prepositions ὂν = ἀνά, πεδά = μετά;
§ 10 αἰ = εἰ), Smyth §§ 70-72 (elision), 179-183 (proclitics, enclitic accent), 1840-1841 (μή in prohibitions).

Gates (a candidate set never becomes empty; removed readings are listed on the row as `dialect_rules`):

  iota_subscript     a printed final ᾳ ῃ ῳ is a dative singular when the word is a noun or adjective (any text).
  accented_proclitic a grave or circumflex on a proclitic spelling (οἳ, οἶ, ἒν) rules out the proclitic reading:
                     the article ὁ ἡ οἱ αἱ, ἐν, εἰς, ἐκ, εἰ (any text).
  dialect_label      a reading labelled only with Attic/Ionic/epic dialects yields to one labelled with the
                     passage's dialect when their parts of speech differ (ἄγην: the Attic-Ionic noun ἄγη
                     yields to the Aeolic infinitive of ἄγω; παῖσαν: παίω yields to πᾶς). Doric and Aeolic
                     labels count as compatible with each other; a normalised spelling's label is ignored.
  elision_vowel      elision removes a short vowel: a restoration ending in ι (dative plural, 3rd plural -σι)
                     or a diphthong yields to one with α ε ο (χαίροισ’ is χαίροισα).
  -ην infinitive     a form in -ην with an infinitive reading is that infinitive (§§ 3, 6: ἄγην, φίλην).
  μή + verb          after μή / μηδέ outside an εἰ/αἰ clause the imperative/subjunctive/optative reading stays.
  article_head       a form read both as the article and as a word of another class is the article only if an
                     agreeing nominal follows (skipping postpositive particles), or the article is pronominal
                     (before δέ/μέν/γάρ) and the next finite verb agrees in number (§ 10: αἰ = εἰ).
  -ας genitive       Lesbian only: the 1st/2nd declension accusative plural is -αις -οις (§ 7), so a first-
                     declension -ας that is also the genitive singular of the word is that genitive.
  dual               a dual reading yields to a singular or plural one unless the context model reads a dual.
  psilosis/barytone  readings reached only through the psilosis or recessive-accent variants (οἷ for printed
                     οἶ, ἀνθεῖ for ἄνθει; aeolic_variants.lesbian_fallback_variants) stay only when no reading
                     of the printed spelling survives (§§ 1-2).

Weights (added to the ranking score of interlinear._affinity, dialect passages only):

  dialect label   +0.4 for a reading labelled with the passage's dialect.
  -ην infinitive  +1.5 for an infinitive reading of a form in -ην.
  -οισα, -αισα    +1.5 for a participle reading (§ 3: λίποισα, ζεύξαισα).
  -μμι verbs      +0.5 for a verb reading of a form in -μμι, -ημι, -ωμι (§ 6: φίλημι, κάλημμι).
  elision         -0.75 for a restoration ending in ι or a diphthong (outside dialect passages too).
"""
from __future__ import annotations

import threading
import unicodedata

from .passage_dialect import dialect_labels

_LOCAL = threading.local()
ELISION = "’᾽'ʼ"
CLAUSE_END = {".", ";", ";", "·", "·", ":", "!", "?"}
# Postpositive particles and enclitics skipped when looking for the article's noun (folded spellings).
POSTPOSITIVE = {"δε", "δ", "γαρ", "μεν", "τε", "τ", "δη", "ποτα", "ποτε", "κε", "κεν", "κα", "αρα", "αρ", "ρα",
                "ουν", "ων", "τοι", "γε", "περ", "θην", "νυ", "μαν", "μην"}
SUBORDINATORS = {"ει", "αι", "εαν", "ην", "αν", "ινα", "οπως", "ως", "οτε", "οτα", "οππως", "οππα", "επει", "οττι",
                 "οτι", "πριν", "εως"}
NOMINAL = {"NOUN", "PROPN", "ADJ", "PRON", "DET", "NUM"}


def fold(text):
    nfd = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in nfd if unicodedata.category(c).startswith("L")).lower().replace("ς", "σ")


def _features(candidate):
    from .interlinear import canonical_features
    return canonical_features(candidate)


def label_fit(candidate, dialect):
    """'match', 'other' or None (unlabelled) for the parser's dialect label of a reading."""
    raw = candidate.get("features") if isinstance(candidate.get("features"), dict) else {}
    label = str(raw.get("dial") or raw.get("dialect") or "").lower()
    if not label or not dialect or candidate.get("normalised_query"):
        # a reading of a normalised spelling is labelled for that (standard) spelling, not the printed one
        return None
    if any(word in label for word in dialect_labels(dialect)):
        return "match"
    # Doric, Aeolic and Boeotian share what sets them apart from Attic-Ionic (ᾱ for η, σδ); a reading
    # labelled with one of the others is not evidence against the passage's dialect.
    if any(word in label for word in ("doric", "aeolic", "lesbian", "boeot", "laconia")):
        return None
    return "other"


# --------------------------------------------------------------------------- context words
def context_words(text, start, end, *, after=6, before=3):
    """The printed words after and before a word in the passage, stopping at a clause end.

    [{'form', 'folded', 'clause_end_before'}]; brackets and underdots are removed from the form.
    """
    from .passage_analysis import tokenize_span
    nxt, prev = [], []
    window = tokenize_span(text, end, min(len(text), end + 240))
    stop = False
    for token in window:
        if token["kind"] in ("punctuation",) and any(ch in CLAUSE_END for ch in token["text"]):
            stop = True
        if token["kind"] == "word" and token["start"] > end - 1:
            if stop or len(nxt) >= after:
                break
            nxt.append({"form": token.get("form") or token["text"], "folded": fold(token.get("form") or token["text"])})
    window = tokenize_span(text, max(0, start - 160), start)
    for token in reversed(window):
        if token["kind"] in ("punctuation",) and any(ch in CLAUSE_END for ch in token["text"]):
            break
        if token["kind"] == "word" and not token.get("partial_word"):
            prev.append({"form": token.get("form") or token["text"], "folded": fold(token.get("form") or token["text"])})
            if len(prev) >= before:
                break
    return {"next": nxt, "prev": prev}


def attach_context(token, text, dialect, analyse):
    """Store the passage dialect and the parser readings of the neighbouring words on a word token.

    `analyse(form)` returns a machine-morphology result (cached by the caller)."""
    token["passage_dialect"] = dialect
    words = context_words(text, token["start"], token["end"])
    for side in ("next", "prev"):
        for word in words[side]:
            try:
                result = analyse(word["form"]) or {}
            except Exception:  # noqa: BLE001 - a neighbour without readings simply gives no evidence
                result = {}
            word["readings"] = [_features(row) for row in result.get("machine_candidates") or []]
    token["context_words"] = words
    return token


# --------------------------------------------------------------------------- gates
def _is_article(candidate):
    from .lemma_glosses import headword_key
    return fold(headword_key(str(candidate.get("lemma") or ""))) == "ο" and _features(candidate).get("POS") in ("DET", "PRON", None)


def _agrees(article, reading):
    if reading.get("POS") not in NOMINAL and reading.get("VerbForm") != "Part" and reading.get("VerbForm") != "Inf":
        return False
    if reading.get("VerbForm") == "Inf":
        return article.get("Case") in ("Nom", "Acc", "Gen", "Dat") and article.get("Number") == "Sing" and article.get("Gender") == "Neut"
    return all(reading.get(key) in (None, article.get(key)) for key in ("Case", "Number", "Gender") if article.get(key))


def _article_has_head(article, words):
    """True when a following word can be the article's noun (or the article is a pronoun), and when
    the parser knows none of the words looked at (no evidence either way)."""
    seen = 0
    pronominal = False
    known = False
    for index, word in enumerate(words):
        if word["folded"] in POSTPOSITIVE:
            if index == 0 and word["folded"] in ("δε", "δ", "μεν", "γαρ"):
                pronominal = True
            continue
        known = known or bool(word.get("readings"))
        if any(_agrees(article, reading) for reading in word.get("readings") or []):
            return True
        seen += 1
        if seen >= 2:
            break
    if pronominal and article.get("Case") == "Nom":
        # ὁ δέ, αἱ δέ: the article as a pronoun is the subject of the next finite verb.
        for word in words:
            finite = [r for r in word.get("readings") or [] if r.get("Person") and r.get("Number")]
            if finite:
                return any(r.get("Number") == article.get("Number") for r in finite)
    return not known


def _final_iota_subscript(form):
    nfd = unicodedata.normalize("NFD", str(form or "").rstrip(ELISION))
    letters = [i for i, c in enumerate(nfd) if unicodedata.category(c).startswith("L")]
    return bool(letters) and nfd[letters[-1]].lower() in "αηω" and "ͅ" in nfd[letters[-1]:]


def gate(candidates, token, predicted):
    """(kept, removed) for one word's candidate parses; removed = [(rule, candidate)]."""
    dialect = token.get("passage_dialect")
    form = token.get("form") or token.get("text") or ""
    kept, removed = list(candidates), []

    def apply(rule, drop):
        nonlocal kept
        out = [c for c in kept if drop(c)]
        rest = [c for c in kept if not drop(c)]
        if out and rest:
            kept = rest
            removed.extend((rule, c) for c in out)

    feats = {id(c): _features(c) for c in candidates}
    if _final_iota_subscript(form):
        apply("iota_subscript", lambda c: feats[id(c)].get("Case") is not None
              and feats[id(c)].get("POS") != "VERB" and not (feats[id(c)].get("Case") == "Dat" and feats[id(c)].get("Number") in (None, "Sing")))
    marks = _accent_marks(form)
    if marks["grave"] or marks["circumflex"]:
        # Proclitics (the article ὁ ἡ οἱ αἱ, ἐν, εἰς, ἐκ, εἰ) carry no accent of their own; one that
        # enclisis gives them is an acute. A grave or circumflex on the printed word (οἳ, οἶ, ἒν) rules
        # the proclitic reading out (Smyth §§ 179-181).
        from .lemma_glosses import headword_key
        if fold(form) in PROCLITIC_FORMS:
            apply("accented_proclitic", lambda c: fold(headword_key(str(c.get("lemma") or ""))) in PROCLITICS
                  and (fold(headword_key(str(c.get("lemma") or ""))) != "ο" or feats[id(c)].get("Case") == "Nom"))
    if not dialect:
        return kept, removed
    fits = {id(c): label_fit(c, dialect) for c in candidates}
    if any(fits[id(c)] == "match" for c in kept):
        # The parser's labels name the dialects of the endings it applied and are not exhaustive, so they
        # only separate different words: a reading labelled only with other dialects yields when its part
        # of speech is not that of any reading labelled with the passage's dialect (ἄγην: the Attic-Ionic
        # noun ἄγη yields to the Aeolic infinitive of ἄγω; two verb readings stay for the context to rank).
        word_class = lambda c: {"PROPN": "NOUN", "AUX": "VERB"}.get(feats[id(c)].get("POS"), feats[id(c)].get("POS"))
        matched = {word_class(c) for c in kept if fits[id(c)] == "match"}
        apply("dialect_label", lambda c: fits[id(c)] == "other" and word_class(c) not in matched)
    elided = form[-1:] in ELISION
    if dialect == "lesbian" and not elided:
        # Release U (Campbell p. 262 § 3): Lesbian αισ, οισ before a vowel is the standard ᾱσ, ουσ (παῖσαν = πᾶσαν,
        # Μοῖσα = Μοῦσα). When a reading of the word is labelled Aeolic by the parser or comes from that
        # normalisation, readings the parser gives no dialect for (the Attic neuter participle παῖσαν of παίω)
        # yield to it.
        from .aeolic_variants import aeolic_diphthong_before_s
        if aeolic_diphthong_before_s(form):
            aeolic = lambda c: fits[id(c)] == "match" or c.get("normalisation_rule") == "aeolic_ais_ois_before_vowel"
            if any(aeolic(c) for c in kept):
                apply("aeolic_ais_ois_before_vowel", lambda c: not aeolic(c) and fits[id(c)] is None
                      and str(c.get("normalisation_rule") or "") not in FALLBACK_RULES)
    if elided:
        # Elision removes a short final vowel; a final ι (dative plural, 3rd plural -σι) or a diphthong
        # is rarely elided in lyric (Smyth § 70): such a restoration yields to a vowel one.
        apply("elision_vowel", lambda c: fold(str(c.get("normalised_query") or "")).endswith("ι")
              and fold(str(c.get("normalised_query") or "")) != fold(form))
        if _ends(form.rstrip(ELISION), "σ"):
            # The parser's own readings of an elided -σ’ name the lost ending only through their features:
            # a dative plural or a 3rd plural in -σι, a feminine plural participle in -σαι.
            # Release U: a 3rd plural in -σι is the clause's verb when no other word of the clause reads only
            # as a finite verb (φαῖσ’ "they say", ἄγοισ’ "they bring"); beside a finite verb the participle
            # stands (χαίροισ’ ἔρχεο), as release R ruled.
            keep_plural = elided_plural_is_verb(token)

            def i_or_diphthong(c):
                f = feats[id(c)]
                return ((f.get("Case") == "Dat" and f.get("Number") == "Plur")
                        or (f.get("Person") == "3" and f.get("Number") == "Plur" and f.get("Tense") in ("Pres", "Fut")
                            and f.get("VerbForm") != "Part" and not keep_plural)
                        or (f.get("VerbForm") == "Part" and f.get("Number") == "Plur" and f.get("Gender") == "Fem"
                            and f.get("Case") in ("Nom", "Voc")))
            apply("elision_vowel", i_or_diphthong)
    if not elided and _ends(form, "ην") and any(feats[id(c)].get("VerbForm") == "Inf" for c in kept):
        # Campbell § 7 (p. 263): thematic infinitives in -ην (ἄγην, ὔμνην = ἄγειν, ὑμνεῖν); an η-stem
        # accusative in -ην is not Lesbian or Doric (they keep ᾱ: -αν).
        apply("aeolic_infinitive_in_en", lambda c: feats[id(c)].get("VerbForm") != "Inf"
              and feats[id(c)].get("POS") not in ("ADV", "PART", "CCONJ", "SCONJ", "INTJ"))
    prev = (token.get("context_words") or {}).get("prev") or []
    if prohibitive(prev):
        # μή / μηδέ with a verb outside a conditional or final clause: a prohibition takes the
        # imperative or the subjunctive (Smyth §§ 1840-1841), not the indicative.
        apply("prohibitive_me", lambda c: feats[id(c)].get("Mood") == "Ind"
              and any(feats[id(o)].get("Mood") in ("Imp", "Sub", "Opt") for o in kept))
    words = (token.get("context_words") or {}).get("next")
    # Only against a reading of another word class (αἰ: the conjunction εἰ): the article as a demonstrative
    # or relative pronoun (τό "which") competes with ὅς readings and is left to the ranking.
    if words and any(_is_article(c) for c in kept) and any(
            not _is_article(c) and feats[id(c)].get("POS") not in ("PRON", "DET", None) for c in kept):
        apply("article_head", lambda c: _is_article(c) and not _article_has_head(feats[id(c)], words))
    if dialect == "lesbian" and _ends(form.rstrip(ELISION), "ας") and not _ends(form.rstrip(ELISION), "αις"):
        # Campbell p. 263 § 7: the Lesbian accusative plural of the 1st and 2nd declensions is -αις, -οις,
        # so a first-declension -ας that is also a genitive singular of the same word is that genitive
        # (ἄρας, φύγας, βόλλας). Third-declension -ας (no such genitive) is untouched.
        from .lemma_glosses import headword_key
        genitives = {fold(headword_key(str(c.get("lemma") or ""))) for c in kept
                     if feats[id(c)].get("Case") == "Gen" and feats[id(c)].get("Number") == "Sing"}
        apply("lesbian_accusative_plural_in_ais", lambda c: feats[id(c)].get("Case") == "Acc"
              and feats[id(c)].get("Number") == "Plur" and fold(headword_key(str(c.get("lemma") or ""))) in genitives)
    from .interlinear import canonical_features, _contradicts
    if canonical_features(predicted or {}).get("Number") != "Dual":
        apply("dual", lambda c: feats[id(c)].get("Number") == "Dual")
    # A reading of the psilosis variant (οἷ for printed οἶ) is a fallback: it stays only when no
    # reading of the exact printed spelling survives the gates uncontradicted by the context model
    # (the model ignores breathings, so its lemma cannot tell ἔσσο from ἕσσο).
    fallback = lambda c: str(c.get("normalisation_rule") or "") in FALLBACK_RULES
    predicted_pos = canonical_features(predicted or {}).get("POS")
    # Any surviving reading of the printed spelling (an interjection only if the model reads one)
    # keeps the psilosis / barytone readings out: the model ignores breathings and accents, so its
    # agreement with them is no evidence (ἔσσο is not ἕσσο, οἶος not οἷος, ἦς not ἧς).
    exact = [c for c in kept if not fallback(c) and feats[id(c)]
             and (feats[id(c)].get("POS") != "INTJ" or predicted_pos == "INTJ")]
    if exact:
        apply("psilosis_fallback_only", fallback)
    return kept, removed


# Lesbian spellings queried even when the parser reads the printed letters (backend.aeolic_variants.
# lesbian_fallback_variants): their readings stand only when no exact reading survives.
FALLBACK_RULES = {"psilosis", "psilotic_rho", "recessive_accent", "circumflex_for_acute"}
PROCLITICS = {"ο", "εν", "εισ", "εσ", "εκ", "εξ", "ει"}
# the printed spellings that are proclitic in some reading: ὁ ἡ οἱ αἱ (Lesbian/Doric ὀ ἀ οἰ αἰ), ἐν, εἰς/ἐς, ἐκ/ἐξ, εἰ
PROCLITIC_FORMS = {"ο", "η", "οι", "αι", "α", "εν", "εισ", "εσ", "εκ", "εξ", "ει"}


def _accent_marks(form):
    nfd = unicodedata.normalize("NFD", str(form or "").rstrip(ELISION))
    return {"grave": "̀" in nfd, "circumflex": "͂" in nfd}


def index_factors(form, candidates, heads, text, tokens, index, dialect, readings_of):
    """Release R, headword index: {headword: factor} for one token of a dialect passage. A headword all
    of whose readings the gates remove gets 0.15 (it stays an alternative); the others 1.0. `tokens` are
    backend.lemma_tokens.word_tokens of the passage text, `readings_of(spelling)` the canonical parser
    features of a spelling. Returns {} when no gate applies."""
    start, end = tokens[index][0], tokens[index][1]
    nxt, prev = [], []
    last = end
    for j in range(index + 1, min(len(tokens), index + 7)):
        s, e, _, spelling, _ = tokens[j]
        if any(ch in CLAUSE_END for ch in text[last:s]):
            break
        nxt.append({"form": spelling, "folded": fold(spelling), "readings": readings_of(spelling)})
        last = e
    last = start
    for j in range(index - 1, max(-1, index - 4), -1):
        s, e, _, spelling, _ = tokens[j]
        if any(ch in CLAUSE_END for ch in text[e:last]):
            break
        prev.append({"form": spelling, "folded": fold(spelling), "readings": readings_of(spelling)})
        last = s
    token = {"form": form, "text": form, "passage_dialect": dialect, "context_words": {"next": nxt, "prev": prev}}
    kept, removed = gate(candidates, token, None)
    if not removed:
        return {}
    alive = {c.get("lemma") for c in kept}
    # a fallback reading (psilosis twin) that survives is a new headword for this token
    return {h: (1.0 if h in alive else 0.15) for h in [*heads, *sorted(alive - set(heads))]}


# --------------------------------------------------------------------------- weights
def _ends(form, *endings):
    letters = fold(form)
    return any(letters.endswith(fold(e)) for e in endings)


def set_context(token):
    _LOCAL.token = token


def clear_context():
    _LOCAL.token = None


def adjust(candidate):
    """Score added to a candidate's ranking for the word being ranked (thread-local context)."""
    token = getattr(_LOCAL, "token", None)
    if not token:
        return 0.0
    form = token.get("form") or token.get("text") or ""
    feats = _features(candidate)
    score = 0.0
    elided = form[-1:] in ELISION
    restored = str(candidate.get("normalised_query") or "")
    if elided and restored and fold(restored)[-1:] and (fold(restored).endswith(("ι", "αι", "οι"))):
        score -= 0.75
    dialect = token.get("passage_dialect")
    if not dialect:
        return score
    fit = label_fit(candidate, dialect)
    score += 0.4 if fit == "match" else 0.0
    if not elided and _ends(form, "ην") and feats.get("VerbForm") == "Inf":
        score += 1.5
    if _ends(form.rstrip(ELISION), "οισα", "αισα", "οισαν", "αισαν", "οισαι", "αισαι") or (elided and _ends(form, "οισ", "αισ")):
        if elided and elided_plural_is_verb(token):
            # Release U: the clause has no other finite verb, so the elided -οισ’ is its 3rd plural verb.
            if feats.get("Person") == "3" and feats.get("Number") == "Plur" and feats.get("VerbForm") != "Part":
                score += 1.5
        elif feats.get("VerbForm") == "Part" and feats.get("Gender") in (None, "Fem"):
            score += 1.5
    if _ends(form, "μμι", "ημι", "ωμι", "ημμεν", "ημμεθα", "ημεν") and feats.get("POS") == "VERB":
        score += 0.5
    return score


FINITE_MOODS = ("Ind", "Imp", "Sub", "Opt")


def _only_finite(readings):
    """Every parser reading of a neighbouring word is a finite verb (ἔρχεο), not one reading among nouns."""
    return bool(readings) and all(r.get("Mood") in FINITE_MOODS and r.get("VerbForm") not in ("Part", "Inf")
                                  for r in readings)


def elided_plural_is_verb(token):
    """Release U: an elided -σ’ word whose clause (the words to the clause end on each side) has no other word
    read only as a finite verb. Without neighbour readings (no dialect context) nothing is decided."""
    words = token.get("context_words") or {}
    sides = [w for side in ("prev", "next") for w in words.get(side) or []]
    if not sides or not any("readings" in w for w in sides):
        return False
    return not any(_only_finite(w.get("readings") or []) for w in sides)


def prohibitive(prev):
    """μή / μηδέ among the two words before, with no subordinating conjunction before it in the clause."""
    before = [w["folded"] for w in prev or []]
    cut = next((i for i, w in enumerate(before[:2]) if w in ("μη", "μηδ", "μηδε")), None)
    return cut is not None and not any(w in SUBORDINATORS for w in before[cut + 1:])


__all__ = ["gate", "adjust", "index_factors", "attach_context", "context_words", "label_fit", "set_context", "clear_context", "fold"]
