"""Release U: general rules for the fast headline lookup (POST /api/words/headlines), the composer's
form check (loop-design L1). Each rule is stated for a class of forms; none names a word.

  folded_lookup     a spelling the index does not hold is matched by its letters: first with the second
                    accent an enclitic throws onto the word removed (θῦμόν → θῦμον, Smyth § 183), then among
                    the spellings with the same letters, preferring one that differs only in breathing (Lesbian
                    psilosis: εὔδω → εὕδω) or accent; the match is labelled (`form_match`).
  aeolic_singular   in a Lesbian or Doric text a first-declension ending in ᾱ of a headword whose Attic
                    feminine has η (a noun in -η, an adjective in -ος, -η, -ον) is singular: -α nom./voc.,
                    -αν acc., -ας gen., -ᾳ dat. (Campbell p. 262 § 3: ᾱ kept; σελάννα, μόνα). The parser reads
                    the same letters as the Attic dual or neuter plural; those readings follow.
  dual              a dual reading follows the other readings; in a Lesbian or Doric text it is dropped when
                    another reading exists (release R rule: no dual in lyric).
  pronoun_vocative  a reading of a pronoun as a vocative (αὖτε as αὐτός) yields to any other headword of the
                    spelling: pronouns are not addressed.
  name_vocative     a capitalised word read as a vocative whose headword's dictionaries give only a place or
                    people adjective ("Attic") addresses a person of that name: the gloss names it (Ἄτθι:
                    "Atthis (a name; vocative)"); the dictionary gloss is kept as `dictionary_gloss`.
"""
from __future__ import annotations

import re
import unicodedata

ACUTE, GRAVE, CIRCUMFLEX = "́", "̀", "͂"
SMOOTH, ROUGH = "̓", "̔"
AEOLIC_DORIC = ("lesbian", "doric", "boeotian", "aeolic")


def _nfd(text):
    return unicodedata.normalize("NFD", text or "")


def _nfc(text):
    return unicodedata.normalize("NFC", text or "")


def _marks(text):
    """(position of each accent / breathing mark among the letters, mark)."""
    out, letters = [], -1
    for ch in _nfd(text):
        if unicodedata.combining(ch):
            if ch in (ACUTE, GRAVE, CIRCUMFLEX, SMOOTH, ROUGH):
                out.append((letters, ch))
        else:
            letters += 1
    return out


def enclitic_accent_dropped(form):
    """θῦμόν → θῦμον: a second accent on the last syllable, thrown there by a following enclitic."""
    nfd = _nfd(form)
    accents = [i for i, ch in enumerate(nfd) if ch in (ACUTE, GRAVE, CIRCUMFLEX)]
    if len(accents) < 2 or nfd[accents[-1]] != ACUTE:
        return None
    return _nfc(nfd[:accents[-1]] + nfd[accents[-1] + 1:])


def mark_distance(a, b):
    """How far two spellings with the same letters are apart: 1 per differing breathing, 2 per accent."""
    ma, mb = set(_marks(a)), set(_marks(b))
    diff = ma ^ mb
    return sum(1 if mark in (SMOOTH, ROUGH) else 2 for _, mark in diff)


def folded_lookup(con, form, fold):
    """(form_id, matched spelling, rule) for a spelling the index does not hold, or None."""
    dropped = enclitic_accent_dropped(form)
    if dropped:
        row = con.execute("SELECT id, form FROM form WHERE form=?", (dropped,)).fetchone()
        if row:
            return row[0], row[1], "enclitic_accent_dropped"
    key = fold(form)
    if not key:
        return None
    rows = con.execute("SELECT id, form, tokens FROM form WHERE key=?", (key,)).fetchall()
    if not rows:
        return None
    same_case = [r for r in rows if (r[1][:1].isupper()) == (form[:1].isupper())] or rows
    best = min(same_case, key=lambda r: (mark_distance(form, r[1]), -(r[2] or 0), r[1]))
    diff = set(_marks(form)) ^ set(_marks(best[1]))
    rule = "breathing_folded" if diff and all(mark in (SMOOTH, ROUGH) for _, mark in diff) else "accent_folded"
    return best[0], best[1], rule


# ------------------------------------------------------------------ parses
_ENDINGS = (("ᾳ", ["dat. fem. sg."]), ("αν", ["acc. fem. sg."]), ("ας", ["gen. fem. sg."]), ("α", ["nom. fem. sg.", "voc. fem. sg."]))


def _letters(text):
    return "".join(ch for ch in _nfd(text) if not unicodedata.combining(ch) or ch == "ͅ").lower()


def eta_feminine(lemma, pos):
    """The headword's Attic feminine singular is an η-stem: a noun in -η, an adjective in -ος (three endings)."""
    letters = _letters(lemma)
    if pos == "noun" and letters.endswith("η"):
        return True
    return pos == "adjective" and letters.endswith("ος")


def aeolic_singular(form, lemma, pos, parses, dialect):
    """Parses with the Lesbian/Doric ᾱ singulars first (and duals dropped), or the parses unchanged."""
    if (dialect or "") not in AEOLIC_DORIC or not eta_feminine(lemma, pos):
        return parses, None
    letters = _letters(form)
    if letters.endswith(("ια", "εα", "ρα", "ιαν", "εαν", "ραν", "ιας", "εας", "ρας")):
        return parses, None  # Attic keeps ᾱ after ε ι ρ: the parser already reads these
    for ending, labels in _ENDINGS:
        if letters.endswith(_letters(ending)):
            if pos == "noun":
                labels = [label.replace(" fem.", " fem.") for label in labels]
            added = [label for label in labels if label not in parses]
            rest = [p for p in parses if " du." not in p]
            return labels + [p for p in rest if p not in labels], ("aeolic_singular" if added or rest != parses else None)
    return parses, None


def duals_last(parses, dialect):
    singular = [p for p in parses if " du." not in p]
    if (dialect or "") in AEOLIC_DORIC and singular:
        return singular, "dual" if len(singular) != len(parses) else None
    return singular + [p for p in parses if " du." in p], None


def pronoun_vocative_only(parses, pos):
    return pos == "pronoun" and bool(parses) and all(p.startswith("voc.") for p in parses)


# ------------------------------------------------------------------ names
_PLACE_ADJECTIVE = re.compile(r"^(?:the\s+)?[A-Z][a-z]+(?:ic|ian|ean|an|ese|ish|ite)\b")
_LATIN = {"α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e", "θ": "th", "ι": "i", "κ": "c",
          "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
          "υ": "y", "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o"}
_DIGRAPHS = {"αι": "ae", "οι": "oe", "ει": "i", "ου": "u", "αυ": "au", "ευ": "eu", "γγ": "ng", "γκ": "nc", "γχ": "nch"}


def latin_name(lemma):
    """The conventional Latin spelling of a Greek name (Ἀτθίς → Atthis, Γογγύλα → Gongyla)."""
    nfd = _nfd(lemma)
    rough = len(nfd) > 1 and ROUGH in nfd[:3]
    letters = "".join(ch for ch in nfd if not unicodedata.combining(ch)).lower()
    out, i = [], 0
    while i < len(letters):
        pair = letters[i:i + 2]
        if pair in _DIGRAPHS:
            out.append(_DIGRAPHS[pair])
            i += 2
            continue
        out.append(_LATIN.get(letters[i], letters[i]))
        i += 1
    text = "".join(out)
    if text.endswith("os"):
        text = text[:-2] + "us"
    if rough:
        text = "h" + text
    return text[:1].upper() + text[1:]


def name_vocative(printed, lemma, parses, gloss):
    """A gloss naming the person addressed, or None (see name_vocative in the module notes)."""
    if not printed or not printed[:1].isupper() or not lemma or not gloss:
        return None
    if not parses or not str(parses[0]).startswith("voc."):
        return None
    head = str(gloss).strip()
    if not _PLACE_ADJECTIVE.match(head) or len(head.split()) > 2:
        return None
    return f"{latin_name(lemma)} (a name; vocative)"


__all__ = ["folded_lookup", "aeolic_singular", "duals_last", "pronoun_vocative_only", "name_vocative", "latin_name",
           "enclitic_accent_dropped", "mark_distance", "eta_feminine"]


def apply_name_vocatives(interlinear, gloss_of):
    """Release U: the name_vocative rule on an analysis' interlinear rows (reader and draft analysis).
    `gloss_of(lemma)` gives the headword's index gloss (the first dictionary's short gloss). Returns the count."""
    count = 0
    for reading in (interlinear or {}).get("readings") or []:
        for row in reading.get("tokens") or []:
            if row.get("kind") != "word" or not row.get("lemma"):
                continue
            parse = row.get("parse_short") or ""
            named = name_vocative(row.get("text") or "", row["lemma"], [parse], gloss_of(row["lemma"]))
            if not named:
                continue
            old = row.get("gloss") if isinstance(row.get("gloss"), dict) else {}
            row["gloss"] = {**old, "text": named, "full_text": named, "short_text": named, "status": "available",
                            "selection_basis": "name_vocative",
                            "dictionary_gloss": old.get("short_text") or old.get("text"),
                            "note": "A capitalised word addressed in the vocative whose dictionaries give only a "
                                    "place or people adjective is read as the name of the person addressed."}
            count += 1
    return count
