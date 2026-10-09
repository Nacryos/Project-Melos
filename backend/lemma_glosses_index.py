"""Short glosses and English gloss terms for corpus headwords (release O).

``short_gloss_for`` picks one dictionary's printed gloss for a headword, in the site's
dictionary order (Middle Liddell, Autenrieth, LSJ, Cunliffe, Dodson). ``gloss_terms``
turns the head gloss (and the start of the entry) into English search terms with a weight,
so an English query can be read as Greek headwords whose dictionaries define them with
those words (moon -> σελήνη, rose-fingered -> ῥοδοδάκτυλος). Terms are crude stems; the
mapping is a retrieval aid, not a translation.
"""
from __future__ import annotations

import re
import unicodedata

from .short_gloss import DICTIONARY_LABELS, dictionary_rank, short_head

STOP = frozenset("""a an and are as at be but by for from has have he her his i in is it its of on or she that the their
them they this to was were which who will with you your not no so than then there these those into upon when where
while whom whose one any anything something thing things also used use esp especially etc cf eg ie freq usu
form forms word words name epith epithet prob perh person persons sort kind made make like being metaph pl sg lat
very much more most less same other another such own way part""".split())
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_SUFFIXES = ("ingly", "edly", "ings", "ing", "ied", "ies", "ed", "es", "s", "ly", "y", "e")
HEAD, BODY, MEANING = 1, 2, 3
# A dictionary gloss that only points to another headword ("= πότνια", "v. ἔρως").
CROSS_REFERENCE = re.compile(r"^\s*(?:=|v\.|see\b|cf\.)", re.I)
_ARTICLE = re.compile(r"^(?:to|a|an|the|one who|that which|of)\s+", re.I)


def stem(word: str) -> str:
    word = word.lower()
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def english_terms(text: str) -> list[str]:
    """Stems of English content words; a hyphenated compound also gives its joined key (ros-finger)."""
    out = []
    for match in _WORD.finditer(unicodedata.normalize("NFKC", text or "")):
        parts = [p for p in match.group().lower().split("-") if p]
        stems = [stem(p) for p in parts if p not in STOP and len(p) > 1]
        out.extend(stems)
        if len(parts) > 1 and len(stems) == len(parts):
            out.append("-".join(stems))
        if len(parts) > 1:
            # "bitter-sweet" and "bittersweet" are one English word written two ways.
            out.append(stem("".join(parts)))
    return list(dict.fromkeys(t for t in out if len(t) >= 2))


def _english_part(entry_text: str, limit: int = 220) -> str:
    """Leading English of an entry; Greek letters and Beta Code-like tokens dropped."""
    text = str(entry_text or "")[:limit]
    words = []
    for token in text.split():
        if any(c in token for c in ")(/\\=|*+") or any("Ͱ" <= c <= "῿" for c in token):
            continue
        words.append(token)
    return " ".join(words)


def _entries(headword, heads):
    """Entries in dictionary order; within one dictionary the main entry first (release P): an
    entry whose gloss is only a cross-reference, or a shorter homograph (LSJ's ὁδός (B)
    "threshold" beside ὁδός "way"), comes after the fuller entry."""
    match, rows = heads.lookup(headword)
    if not match:
        return []
    return sorted(rows, key=lambda row: (dictionary_rank(row.get("source")),
                                         bool(CROSS_REFERENCE.match(str(row.get("gloss") or ""))),
                                         -len(str(row.get("entry_text") or ""))))


def short_gloss_for(headword, heads):
    """(short gloss, dictionary label, text used for terms) or (None, None, '')."""
    rows = _entries(headword, heads)
    gloss = source = None
    for row in rows:
        printed = row.get("gloss") or ""
        if CROSS_REFERENCE.match(printed):
            continue
        head = short_head(printed) if printed.strip() else None
        if head:
            gloss, source = head["text"], DICTIONARY_LABELS.get(row.get("source"), row.get("source"))
            break
    heads_printed = [h["text"] for h in (short_head(str(r.get("gloss") or "")) for r in rows[:8]
                                         if not CROSS_REFERENCE.match(str(r.get("gloss") or ""))) if h]
    full = " ; ".join(filter(None, [*(str(r.get("gloss") or "") for r in rows[:6]),
                                    *(_english_part(r.get("entry_text")) for r in rows[:3])]))
    glosses = [str(r.get("gloss") or "") for r in rows[:8] if not CROSS_REFERENCE.match(str(r.get("gloss") or ""))]
    return gloss, source, {"heads": heads_printed, "full": full, "glosses": glosses}


def head_meanings(gloss_text, limit=8):
    """The head words of a printed gloss's senses (release P): the gloss is cut into sense phrases at
    ; , and "or"; a phrase of one or two words (after a leading article or "to") gives its content
    words ("the moon" -> moon, "a mate or companion" -> mate, companion), a longer phrase only its
    first content word ("Io, identified with the moon" -> io, identified). Whole words (a plural -s dropped), not stems; a
    hyphenated word stays one word ("sea-man")."""
    out = []
    for phrase in re.split(r"\s*(?:[;,:()\[\]]|\bor\b|—|–)\s*", unicodedata.normalize("NFKC", gloss_text or ""))[:limit]:
        phrase = _ARTICLE.sub("", phrase.strip().lower()).strip(" .")
        tokens = _WORD.findall(phrase)
        words = [w for w in tokens if w.lower() not in STOP and len(w) > 1]
        if not words:
            continue
        for word in (words if len(tokens) <= 2 else words[:1]):
            out.append(singular(word.lower()))
    return list(dict.fromkeys(out))


def singular(word):
    """A plural -s dropped (stars -> star), not the -s of a singular (eros, chaos, iris, lotus)."""
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "os", "as")):
        return word[:-1]
    return word


def gloss_terms(gloss, texts):
    """[(term, field, weight)]: a head-gloss term weighs 1/len(that head's terms) (best head);
    terms only in the entry body weigh 0.25."""
    texts = texts if isinstance(texts, dict) else {"heads": [gloss] if gloss else [], "full": texts or ""}
    out = {}
    for head in [gloss, *texts.get("heads", [])]:
        terms = english_terms(head or "")
        simple = max(1, len([t for t in terms if "-" not in t]))
        for term in terms:
            weight = round(1.0 / simple, 4)
            if term not in out or out[term][1] < weight:
                out[term] = (HEAD, weight)
    for term in english_terms(texts.get("full", "")):
        if term not in out:
            out[term] = (BODY, 0.25)
    rows = [(term, field, weight) for term, (field, weight) in out.items()]
    meanings = {}
    for text in [gloss or "", *texts.get("glosses", [])]:
        words = head_meanings(text)
        for word in words:
            weight = round(1.0 / max(1, len(words)), 4)
            meanings[word] = max(meanings.get(word, 0), weight)
    rows.extend(("=" + word, MEANING, weight) for word, weight in meanings.items())
    return rows


__all__ = ["short_gloss_for", "gloss_terms", "english_terms", "head_meanings", "singular", "stem", "HEAD",
           "BODY", "MEANING"]
