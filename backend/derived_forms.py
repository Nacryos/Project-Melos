"""Derived forms read to their base headword (release R).

LSJ and Autenrieth print adverbs, comparatives and superlatives either inside the entry of the positive
(ταχέως under ταχύς) or as short entries of their own that say so: "ταχέως, Adv. of ταχύς", "μάλιστα, Sup.
of μάλα", "ἀμείνων, irreg. Comp. of ἀγαθός", "ἄγχιστος (sup. of ἄγχι)". Such an entry is dictionary
evidence that the two headwords are one lexeme; the reader then shows the base headword (with the derived
headword and the relation as a note), the headword index counts the token under the base, and calibration
compares lemmas through the same link. Nothing is generated from spelling alone: a link exists only where
a dictionary entry of the derived headword prints it, and the base must itself be a dictionary headword.
"""
from __future__ import annotations

import re
import unicodedata

# The relation printed near the start of the derived headword's entry (Perseus Beta Code text).
_RELATION = re.compile(
    r"\b((?:irreg\.\s+|double\s+|used\s+as\s+)?(?:Adv\.|adv\.|Comp\.|comp\.|Sup\.|sup\.|Superl\.)"
    r"(?:\s*(?:and|&)\s*(?:Sup|sup)\.)?)\s+(?:of|fr\.|from)\s+([A-Za-z()\\/=|+*'&;]+)")
_HEAD_SPAN = 140


def _nfc(text):
    return unicodedata.normalize("NFC", str(text or ""))


def _relation_name(printed):
    p = printed.lower()
    if "adv" in p:
        return "adverb"
    if "sup" in p and "comp" in p:
        return "comparative_superlative"
    return "superlative" if "sup" in p else "comparative"


def _to_greek(beta):
    try:
        from betacode import beta_to_uni
        word = beta_to_uni(beta.strip("();,."))
    except Exception:  # noqa: BLE001 - not Beta Code
        return ""
    word = _nfc(word).strip()
    return word if any("Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿" for ch in word) else ""


def _letters(text):
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c).startswith("L")).lower()


def _other_words_before(before, own):
    """True when a Greek word other than the headword (inflection endings aside) stands before the
    relation: Beta Code words carrying accent or breathing marks, or Unicode Greek words of 3+ letters."""
    for word in re.findall(r"[*A-Za-z()/\\=|+'^_]+", before):
        if re.search(r"[()/\\=|+]", word):
            greek = _letters(_to_greek(word))
            if greek and greek != own:
                return True
    for word in re.findall(r"[Ͱ-Ͽἀ-῿̀-ͯ]+", before):
        letters = _letters(word)
        if len(letters) >= 3 and letters != own:
            return True
    return False


def derived_link(headword, entries, exists):
    """{base, relation, printed, entry_id, source} when a dictionary entry of `headword` says it is the
    adverb, comparative or superlative of another headword; else None.

    `entries` are the dictionary entries of `headword` (dicts with lemma, entry_text, source, id);
    `exists(base)` says whether the base is itself a dictionary headword."""
    own = _letters(headword)
    for entry in entries or []:
        if _letters(re.sub(r"\d+$", "", _nfc(entry.get("lemma")))) != own:
            continue
        text = str(entry.get("entry_text") or "")[:_HEAD_SPAN]
        match = _RELATION.search(text)
        if not match:
            continue
        if _other_words_before(text[:match.start()], own):
            # "ἤδη, ἤδης, v. εἴδω. ἥδιστος, ἡδίων, Sup. and Comp. of ἡδύς": the relation belongs to
            # other words listed in the entry, not to the headword
            continue
        base = _to_greek(match.group(2))
        if len(_letters(base)) < 2 or _letters(base) == own:
            continue
        relation = _relation_name(match.group(1))
        if relation == "adverb" and (not own.endswith("ως") or re.search(r"(ω|ομαι|μι)$", _letters(base))):
            # only adverbs in -ως are read to their adjective (μεγαλωστί, ἀγορῆθεν keep their own headword);
            # an adverb of a verb (ἀγνοούντως, Adv. of ἀγνοέω) is not an adjective's adverb
            continue
        if not exists(base):
            continue
        return {"base": base, "relation": relation, "printed": f"{match.group(1)} of {base}",
                "source_text": text[max(0, match.start() - 20):match.end()].strip(),
                "entry_id": entry.get("id"), "source": entry.get("source")}
    return None


__all__ = ["derived_link"]
