"""Ending-based analyses for words no lexicon or parser recognises.

This is the last tier. It never looks a word up: it reads the inflectional
ending of the printed form and lists the case/number/gender (or person/number)
combinations that ending can carry in Greek, including the Lesbian Aeolic
endings an Attic table lacks (-οισι/-αισι, -εσσι, -αο, -ᾱν). Each candidate is
labelled ``pattern_analysis`` with the ending that produced it, carries no
lemma and no gloss, and ranks below every lexicon-backed parse. The caller
should pass the contextual prediction's part of speech so the right table is
used; without one both tables are consulted.

Proper names and hapax legomena in the fragments (Ὕρραον, Ὦγεσιλαΐδα,
λυκαιμίαις) are the intended cases.
"""
from __future__ import annotations

import unicodedata

# (ending, [(Case, Number, Gender or None), ...]) longest endings first.
NOMINAL = [
    ("εσσι", [("Dat", "Plur", None)]),
    ("αισι", [("Dat", "Plur", "Fem")]),
    ("οισι", [("Dat", "Plur", "Masc"), ("Dat", "Plur", "Neut")]),
    ("οιο", [("Gen", "Sing", "Masc"), ("Gen", "Sing", "Neut")]),
    ("αις", [("Dat", "Plur", "Fem")]),
    ("οις", [("Dat", "Plur", "Masc"), ("Dat", "Plur", "Neut")]),
    ("ους", [("Acc", "Plur", "Masc"), ("Gen", "Sing", None)]),
    ("ων", [("Gen", "Plur", None)]),
    ("ας", [("Acc", "Plur", "Fem"), ("Gen", "Sing", "Fem"), ("Nom", "Sing", "Masc"), ("Acc", "Plur", None)]),
    ("αν", [("Acc", "Sing", "Fem"), ("Acc", "Sing", "Masc")]),
    ("ον", [("Acc", "Sing", "Masc"), ("Nom", "Sing", "Neut"), ("Acc", "Sing", "Neut"), ("Voc", "Sing", "Neut")]),
    ("ος", [("Nom", "Sing", "Masc"), ("Nom", "Sing", "Fem"), ("Gen", "Sing", None)]),
    ("ου", [("Gen", "Sing", "Masc"), ("Gen", "Sing", "Neut")]),
    ("ης", [("Gen", "Sing", "Fem"), ("Nom", "Sing", "Masc")]),
    ("ην", [("Acc", "Sing", "Fem"), ("Acc", "Sing", "Masc")]),
    ("ες", [("Nom", "Plur", None), ("Voc", "Plur", None)]),
    ("ας", [("Acc", "Plur", None)]),
    ("αι", [("Nom", "Plur", "Fem"), ("Voc", "Plur", "Fem")]),
    ("οι", [("Nom", "Plur", "Masc"), ("Voc", "Plur", "Masc")]),
    ("ου", [("Gen", "Sing", None)]),
    ("αο", [("Gen", "Sing", "Masc")]),
    ("ῃ", [("Dat", "Sing", "Fem")]),
    ("ᾳ", [("Dat", "Sing", "Fem")]),
    ("ῳ", [("Dat", "Sing", "Masc"), ("Dat", "Sing", "Neut")]),
    ("α", [("Nom", "Sing", "Fem"), ("Acc", "Sing", None), ("Nom", "Plur", "Neut"), ("Acc", "Plur", "Neut"), ("Gen", "Sing", "Masc")]),
    ("η", [("Nom", "Sing", "Fem"), ("Voc", "Sing", "Fem")]),
    ("ι", [("Dat", "Sing", None)]),
    ("ε", [("Voc", "Sing", "Masc")]),
    ("υ", [("Nom", "Sing", "Neut"), ("Acc", "Sing", "Neut")]),
    ("ω", [("Nom", "Sing", "Fem"), ("Acc", "Sing", "Fem"), ("Gen", "Sing", None)]),
]
# (ending, [(Person, Number, Tense, Mood, Voice), ...])
VERBAL = [
    ("ομεν", [("1", "Plur", "Pres", "Ind", "Act")]),
    ("ετε", [("2", "Plur", "Pres", "Ind", "Act"), ("2", "Plur", "Pres", "Imp", "Act")]),
    ("ουσι", [("3", "Plur", "Pres", "Ind", "Act")]),
    ("οισι", [("3", "Plur", "Pres", "Ind", "Act")]),
    ("εις", [("2", "Sing", "Pres", "Ind", "Act")]),
    ("ει", [("3", "Sing", "Pres", "Ind", "Act")]),
    ("μι", [("1", "Sing", "Pres", "Ind", "Act")]),
    ("σι", [("3", "Sing", "Pres", "Ind", "Act")]),
    ("σα", [("1", "Sing", "Aor", "Ind", "Act")]),
    ("σας", [("2", "Sing", "Aor", "Ind", "Act")]),
    ("σε", [("3", "Sing", "Aor", "Ind", "Act")]),
    ("σαν", [("3", "Plur", "Aor", "Ind", "Act")]),
    ("ω", [("1", "Sing", "Pres", "Ind", "Act"), ("1", "Sing", "Pres", "Sub", "Act")]),
    ("ε", [("3", "Sing", "Imp", "Ind", "Act"), ("2", "Sing", "Pres", "Imp", "Act")]),
    ("ον", [("1", "Sing", "Imp", "Ind", "Act"), ("3", "Plur", "Imp", "Ind", "Act")]),
    ("ες", [("2", "Sing", "Imp", "Ind", "Act")]),
    ("ται", [("3", "Sing", "Pres", "Ind", "Mid")]),
    ("νται", [("3", "Plur", "Pres", "Ind", "Mid")]),
    ("μαι", [("1", "Sing", "Pres", "Ind", "Mid")]),
    ("σθαι", [(None, None, "Pres", None, "Mid")]),
    ("ην", [(None, None, "Pres", None, "Act")]),
    ("σθω", [("3", "Sing", "Pres", "Imp", "Mid")]),
    ("σθων", [("3", "Plur", "Pres", "Imp", "Mid")]),
    ("ντων", [("3", "Plur", "Pres", "Imp", "Act")]),
    ("τω", [("3", "Sing", "Pres", "Imp", "Act")]),
]
# Longest ending first, so -σαν is read before -σα and -σθω before -ω.
VERBAL.sort(key=lambda row: -len(row[0]))
# Participles: (ending, Voice, Tense or None, [(Case, Number, Gender or None), ...]).
# Middle-passive -μεν- forms and active -ουσ-/-οισ-/-οντ-/-σαντ- forms are
# participial whatever the context; they are read before the finite table.
PARTICIPLE = [
    ("μενοισι", "Mid", None, [("Dat", "Plur", "Masc"), ("Dat", "Plur", "Neut")]),
    ("μεναισι", "Mid", None, [("Dat", "Plur", "Fem")]),
    ("μενοις", "Mid", None, [("Dat", "Plur", "Masc"), ("Dat", "Plur", "Neut")]),
    ("μεναις", "Mid", None, [("Dat", "Plur", "Fem")]),
    ("μενους", "Mid", None, [("Acc", "Plur", "Masc")]),
    ("μενος", "Mid", None, [("Nom", "Sing", "Masc")]),
    ("μενον", "Mid", None, [("Acc", "Sing", "Masc"), ("Nom", "Sing", "Neut"), ("Acc", "Sing", "Neut")]),
    ("μενου", "Mid", None, [("Gen", "Sing", "Masc"), ("Gen", "Sing", "Neut")]),
    ("μενων", "Mid", None, [("Gen", "Plur", None)]),
    ("μενης", "Mid", None, [("Gen", "Sing", "Fem")]),
    ("μενας", "Mid", None, [("Acc", "Plur", "Fem"), ("Gen", "Sing", "Fem")]),
    ("μενην", "Mid", None, [("Acc", "Sing", "Fem")]),
    ("μεναν", "Mid", None, [("Acc", "Sing", "Fem")]),
    ("μενοι", "Mid", None, [("Nom", "Plur", "Masc")]),
    ("μεναι", "Mid", None, [("Nom", "Plur", "Fem")]),
    ("μενῳ", "Mid", None, [("Dat", "Sing", "Masc"), ("Dat", "Sing", "Neut")]),
    ("μενῃ", "Mid", None, [("Dat", "Sing", "Fem")]),
    ("μενᾳ", "Mid", None, [("Dat", "Sing", "Fem")]),
    ("μενη", "Mid", None, [("Nom", "Sing", "Fem")]),
    ("μενα", "Mid", None, [("Nom", "Sing", "Fem"), ("Nom", "Plur", "Neut"), ("Acc", "Plur", "Neut")]),
    ("σαντος", "Act", "Aor", [("Gen", "Sing", "Masc"), ("Gen", "Sing", "Neut")]),
    ("σαντες", "Act", "Aor", [("Nom", "Plur", "Masc")]),
    ("σαντα", "Act", "Aor", [("Acc", "Sing", "Masc"), ("Nom", "Plur", "Neut"), ("Acc", "Plur", "Neut")]),
    ("σασα", "Act", "Aor", [("Nom", "Sing", "Fem")]),
    ("σαισα", "Act", "Aor", [("Nom", "Sing", "Fem")]),
    ("ουσαν", "Act", "Pres", [("Acc", "Sing", "Fem")]),
    ("ουσαι", "Act", "Pres", [("Nom", "Plur", "Fem")]),
    ("ουσης", "Act", "Pres", [("Gen", "Sing", "Fem")]),
    ("ουσας", "Act", "Pres", [("Acc", "Plur", "Fem"), ("Gen", "Sing", "Fem")]),
    ("ουσῃ", "Act", "Pres", [("Dat", "Sing", "Fem")]),
    ("ουσᾳ", "Act", "Pres", [("Dat", "Sing", "Fem")]),
    ("ουσα", "Act", "Pres", [("Nom", "Sing", "Fem")]),
    ("οισαν", "Act", "Pres", [("Acc", "Sing", "Fem")]),
    ("οισα", "Act", "Pres", [("Nom", "Sing", "Fem")]),
    ("οντος", "Act", "Pres", [("Gen", "Sing", "Masc"), ("Gen", "Sing", "Neut")]),
    ("οντων", "Act", "Pres", [("Gen", "Plur", None)]),
    ("οντες", "Act", "Pres", [("Nom", "Plur", "Masc")]),
    ("οντας", "Act", "Pres", [("Acc", "Plur", "Masc")]),
    ("οντι", "Act", "Pres", [("Dat", "Sing", "Masc"), ("Dat", "Sing", "Neut")]),
    ("οντα", "Act", "Pres", [("Acc", "Sing", "Masc"), ("Nom", "Plur", "Neut"), ("Acc", "Plur", "Neut")]),
]
PARTICIPLE.sort(key=lambda row: -len(row[0]))
NOMINAL_POS = {"NOUN", "PROPN", "ADJ", "DET", "PRON", "NUM"}
VERBAL_POS = {"VERB", "AUX"}


def _bare(form):
    """Letters only, lower-cased, accents stripped, final elision mark dropped.
    The iota subscript is kept (-ῳ, -ῃ, -ᾳ are endings)."""
    text = unicodedata.normalize("NFD", form)
    text = "".join(c for c in text if unicodedata.category(c).startswith("L") or c == "ͅ").lower()
    return unicodedata.normalize("NFC", text)


def _participles(form, bare, predicted_pos):
    for ending, voice, tense, readings in PARTICIPLE:
        if bare.endswith(ending) and len(bare) > len(ending) + 1:
            out = []
            for case, number, gender in readings:
                features = {"case": case, "num": number, "voice": voice, "verbform": "Part"}
                if gender:
                    features["gend"] = gender
                if tense:
                    features["tense"] = tense
                out.append(_candidate(form, ending, features, "VERB"))
            return out
    return []


def pattern_candidates(form, predicted_pos=None, limit=6, predicted_verbform=None):
    """Labelled ending-based analyses of ``form``; empty when nothing fits.

    A participial ending (or a contextual prediction of a participle with one)
    is read as a participle before the finite-verb and nominal tables.
    """
    bare = _bare(form)
    if len(bare) < 3:
        return []
    use_nominal = predicted_pos in NOMINAL_POS or predicted_pos is None
    use_verbal = predicted_pos in VERBAL_POS or predicted_pos is None
    found, seen = [], set()
    if predicted_pos in VERBAL_POS or predicted_pos is None or predicted_verbform == "Part":
        participles = _participles(form, bare, predicted_pos)
        if participles:
            return participles[:limit]
    capitalised = form[:1] != form[:1].lower()
    if use_nominal and capitalised and bare.endswith("ιδα") and len(bare) > 5:
        # A capitalised patronymic in -ίδας: Lesbian/Doric genitive -ίδα
        # (Ὦγεσιλαΐδα "of Agesilaidas"); a vocative is the other possibility.
        for case in ("Gen", "Voc"):
            found.append(_candidate(form, "ιδα", {"case": case, "num": "Sing", "gend": "Masc"}, "NOUN"))
        return found
    if use_nominal:
        for ending, readings in NOMINAL:
            if bare.endswith(ending) and len(bare) > len(ending) + 1:
                for case, number, gender in readings:
                    features = {"case": case, "num": number}
                    if gender:
                        features["gend"] = gender
                    key = ("nominal", case, number, gender)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(_candidate(form, ending, features, predicted_pos if predicted_pos in NOMINAL_POS else "NOUN"))
                break
    if use_verbal:
        for ending, readings in VERBAL:
            if bare.endswith(ending) and len(bare) > len(ending) + 1:
                for person, number, tense, mood, voice in readings:
                    features = {k: v for k, v in (("pers", person), ("num", number), ("tense", tense), ("mood", mood), ("voice", voice)) if v}
                    if not mood and tense:
                        features["verbform"] = "Inf"
                    key = ("verbal", person, number, tense, mood, voice)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(_candidate(form, ending, features, "VERB"))
                break
    return found[:limit]


def _candidate(form, ending, features, pos):
    return {
        "candidate_kind": "pattern_analysis", "basis": "pattern_analysis",
        "lemma": None, "form": form, "pattern_ending": ending,
        "features": {**features, "pofs": pos},
        "tier": "ending_pattern_only",
        "note": ("Ending-based analysis only: the word is in no dictionary or parser lexicon used here, "
                 "so this reads its inflectional ending -" + ending + " and nothing else."),
    }
