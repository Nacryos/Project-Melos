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
HEAD, BODY = 1, 2


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
    match, rows = heads.lookup(headword)
    return sorted(rows, key=lambda row: dictionary_rank(row.get("source"))) if match else []


def short_gloss_for(headword, heads):
    """(short gloss, dictionary label, text used for terms) or (None, None, '')."""
    rows = _entries(headword, heads)
    gloss = source = None
    for row in rows:
        printed = row.get("gloss") or ""
        head = short_head(printed) if printed.strip() else None
        if head:
            gloss, source = head["text"], DICTIONARY_LABELS.get(row.get("source"), row.get("source"))
            break
    heads_printed = [h["text"] for h in (short_head(str(r.get("gloss") or "")) for r in rows[:8]) if h]
    full = " ; ".join(filter(None, [*(str(r.get("gloss") or "") for r in rows[:6]),
                                    *(_english_part(r.get("entry_text")) for r in rows[:3])]))
    return gloss, source, {"heads": heads_printed, "full": full}


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
    return [(term, field, weight) for term, (field, weight) in out.items()]


__all__ = ["short_gloss_for", "gloss_terms", "english_terms", "stem", "HEAD", "BODY"]
