"""Labelled dialect normalisations used only as *query variants* for the parser.

The hosted Morpheus parser knows Attic-Ionic and epic spellings. Lesbian Aeolic
poetry prints forms it cannot match literally (psilotic ῤήα for ῥέα, apocopated
ὀντρέχοντες for ἀνατρέχοντες). Each rule below rewrites the printed form into
the spelling a standard lexicon would list, and every analysis obtained this way
is carried with the rule that produced it. The printed form is never changed in
the source, and a normalised analysis never outranks an analysis of the exact
printed form.

Rules are deliberately few, orthographic, and documented from standard grammars
of Lesbian Aeolic (Buck, *Greek Dialects* §§57, 95; Hamm, *Grammatik zu Sappho
und Alkaios*). They are not a reconstruction of Aeolic phonology.
"""
from __future__ import annotations

import unicodedata

ELISION = "’᾽'"
VOWELS = "αεηιουωᾳῃῳ"
SMOOTH = "̓"
ROUGH = "̔"

# Assimilated apocopated prefixes: κὰτ τόν, κάββαλλε, καγγεγήρασ', πεδὰ (= μετά).
APOCOPE = (
    ("ὀν", "ἀνα", "Aeolic apocope and assimilation of ἀνα- (ὀν- for ἀν-)"),
    ("καγ", "κατα", "Aeolic apocope of κατα- (καγ- before γ)"),
    ("κακ", "κατα", "Aeolic apocope of κατα- (κακ- before κ)"),
    ("καλ", "κατα", "Aeolic apocope of κατα- (καλ- before λ)"),
    ("καμ", "κατα", "Aeolic apocope of κατα- (καμ- before μ)"),
    ("καπ", "κατα", "Aeolic apocope of κατα- (καπ- before π)"),
    ("καρ", "κατα", "Aeolic apocope of κατα- (καρ- before ρ)"),
    ("κασ", "κατα", "Aeolic apocope of κατα- (κασ- before σ)"),
    ("κατ", "κατα", "Aeolic apocope of κατα- (κατ- before τ)"),
    ("καβ", "κατα", "Aeolic apocope of κατα- (καβ- before β)"),
    ("καδ", "κατα", "Aeolic apocope of κατα- (καδ- before δ)"),
    ("πεδ", "μετα", "Aeolic πεδά for μετά in composition"),
)
GEMINATES = (("νν", "ν"), ("μμ", "μ"), ("λλ", "λ"), ("σσ", "σ"), ("ρρ", "ρ"))
# Lesbian function words with an isolated standard equivalent (Hamm §§ 30, 40;
# Buck §§ 100–102). Only words whose equivalence is lexical, not derivable.
LEXICAL = {
    "ἤπειτα": ("ἔπειτα", "Lesbian ἤπειτα for ἔπειτα"),
    "ὄττι": ("ὅτι", "Lesbian ὄττι for ὅτι"),
    "ὄττινας": ("οὕστινας", "Lesbian ὄττινας for οὕστινας"),
    "κῆνος": ("ἐκεῖνος", "Lesbian κῆνος for ἐκεῖνος"),
    "κήνων": ("ἐκείνων", "Lesbian κήνων for ἐκείνων"),
    "ἄμμες": ("ἡμεῖς", "Lesbian ἄμμες for ἡμεῖς"),
    "ἄμμι": ("ἡμῖν", "Lesbian ἄμμι for ἡμῖν"),
    "ἄμμε": ("ἡμᾶς", "Lesbian ἄμμε for ἡμᾶς"),
    "ὔμμες": ("ὑμεῖς", "Lesbian ὔμμες for ὑμεῖς"),
    "ὔμμι": ("ὑμῖν", "Lesbian ὔμμι for ὑμῖν"),
    "πεδά": ("μετά", "Lesbian πεδά for μετά"),
    "πεδὰ": ("μετὰ", "Lesbian πεδά for μετά"),
    "ὄνυμα": ("ὄνομα", "Lesbian ὄνυμα for ὄνομα"),
    "αἴ": ("εἰ", "Lesbian αἴ for εἰ"),
    "ἔγων": ("ἐγών", "Lesbian ἔγων (recessive accent) for epic ἐγών"),
    "τὼ": ("τῶ", "Lesbian τὼ (grave in context) for the genitive article τῶ, Attic τοῦ"),
    "τῶ": ("τοῦ", "Lesbian/Doric genitive article τῶ for Attic τοῦ"),
}


def _nfd(text):
    return unicodedata.normalize("NFD", text)


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def _initial_breathing_swap(form):
    """ὐπ’ → ὑπ’, ὀ → ὁ, ῤ → ῥ: Lesbian psilosis written with a smooth breathing."""
    decomposed = _nfd(form)
    if len(decomposed) < 2 or decomposed[1] != SMOOTH:
        return None
    if decomposed[0].lower() not in VOWELS + "ρ":
        return None
    return _nfc(decomposed[0] + ROUGH + decomposed[2:])


ACUTE = "́"
GRAVE = "̀"
CIRCUMFLEX = "͂"
_IOTA_UPSILON = "ιυ"


def _vowel_groups(decomposed):
    """Index spans of vowel groups (diphthongs kept together) in NFD text."""
    groups, index = [], 0
    while index < len(decomposed):
        if decomposed[index].lower() in VOWELS:
            start = index
            index += 1
            while index < len(decomposed) and unicodedata.category(decomposed[index]).startswith("M"):
                index += 1
            # A following ι/υ without a diaeresis closes a diphthong.
            if (index < len(decomposed) and decomposed[index].lower() in _IOTA_UPSILON
                    and not (index + 1 < len(decomposed) and decomposed[index + 1] == "̈")):
                index += 1
                while index < len(decomposed) and unicodedata.category(decomposed[index]).startswith("M"):
                    index += 1
            groups.append((start, index))
        else:
            index += 1
    return groups


def _accent_shifted_right(form):
    """τήλοθεν → τηλόθεν, ἔκτος → ἐκτός: undo the Lesbian recessive accent.

    Only an acute (or a circumflex, rewritten as an acute) is moved, by one
    vowel group towards the end of the word, onto the last vowel of that group.
    """
    decomposed = _nfd(form)
    groups = _vowel_groups(decomposed)
    for position, (start, end) in enumerate(groups):
        span = decomposed[start:end]
        if ACUTE in span or CIRCUMFLEX in span:
            if position + 1 >= len(groups):
                return None
            stripped = span.replace(ACUTE, "").replace(CIRCUMFLEX, "")
            next_start, next_end = groups[position + 1]
            target = decomposed[next_start:next_end]
            if ACUTE in target or GRAVE in target or CIRCUMFLEX in target:
                return None
            # Place the acute after the last base vowel and its breathing/diaeresis.
            last_vowel = max(i for i, char in enumerate(target) if char.lower() in VOWELS)
            insert = last_vowel + 1
            while insert < len(target) and target[insert] in ("̓", "̔", "̈"):
                insert += 1
            shifted = target[:insert] + ACUTE + target[insert:]
            return _nfc(decomposed[:start] + stripped + decomposed[end:next_start] + shifted + decomposed[next_end:])
    return None


_ACUTE_ON = {"α": "ά", "ε": "έ", "ι": "ί", "ο": "ό"}
_ELIDABLE = "αεοι"


def elision_restorations(form):
    """ἀλλ’ -> ἀλλά, βρίθοντ’ -> βρίθοντα ...: the elided vowel put back.

    Elision removes a short final α, ε, ι or ο (Smyth § 70). Every vowel is
    offered; when the printed stem has no accent the restored vowel may carry
    the word's acute (οὐδ’ -> οὐδέ). The caller keeps only spellings a source
    actually records, so impossible restorations simply find nothing.
    """
    form = _nfc(form)
    if not form or form[-1] not in ELISION or len(form) < 2:
        return []
    stem = form[:-1]
    accented = any(mark in _nfd(stem) for mark in (ACUTE, GRAVE, CIRCUMFLEX))
    found = []
    for vowel in _ELIDABLE:
        found.append(stem + vowel)
        if not accented:
            found.append(stem + _ACUTE_ON[vowel])
    if accented and GRAVE in _nfd(stem):
        # τότ’ printed with a grave on the stem: the dictionary spelling has the acute.
        found = [_nfc(_nfd(item).replace(GRAVE, ACUTE)) for item in found]
    return [{"form": _nfc(item), "rule": "elision_restored",
             "note": "Elided final vowel restored (" + _nfc(item)[-1] + "); only spellings a source records are used",
             "tier": "dialect_normalised_query"} for item in found]


# Crasis (Smyth §§ 49-55): καί, the article or τοι fused with a following
# vowel-initial word. The vowel of the crasis syllable stands for the second
# word's initial vowel: ἀ/ᾀ <- α, ε; ου <- ο, ε; ω <- ο, α; ει/η <- ε, ει.
_CRASIS_VOWELS = (("ου", ("ο", "ε", "ου")), ("οι", ("ι",)), ("ω", ("ο", "α")), ("ει", ("ει", "ε")),
                  ("ᾳ", ("ει", "α", "ε")), ("α", ("α", "ε")), ("η", ("ε", "η", "α")))


def crasis_second_words(form):
    """κἀγώ -> ἐγώ, τοὔνομα -> ὄνομα, χὠ -> ὁ: the vowel-initial word of a crasis.

    Only a κ/τ/θ/χ followed by a vowel bearing a coronis (smooth breathing) is
    read as crasis; θ/χ show that the second word had a rough breathing.
    The parse then describes the second word, which is labelled as such.
    """
    decomposed = _nfd(_nfc(form))
    if len(decomposed) < 3 or decomposed[0].lower() not in "κτθχ":
        return []
    rest = decomposed[1:]
    letters = [i for i, c in enumerate(rest) if unicodedata.category(c).startswith("L")]
    # the coronis sits on the first vowel or on the second letter of a diphthong
    head = "".join(rest[i] for i in letters[:2]).lower()
    coronis_at = [i for i, c in enumerate(rest[:6]) if c in (SMOOTH, ROUGH, "᾽")]
    if not coronis_at or not letters or rest[letters[0]].lower() not in VOWELS:
        return []
    breathing = ROUGH if decomposed[0].lower() in "θχ" else SMOOTH
    plain = "".join(c for c in rest if c not in (SMOOTH, ROUGH))
    letters_plain = [i for i, c in enumerate(plain) if unicodedata.category(c).startswith("L")]
    found = []
    for crasis_vowel, originals in _CRASIS_VOWELS:
        if not head.startswith(crasis_vowel) and not (crasis_vowel == "ᾳ" and head[:1] == "α" and "ͅ" in rest[:4]):
            continue
        width = len(crasis_vowel) if crasis_vowel != "ᾳ" else 1
        if len(letters_plain) < width:
            break
        tail_start = letters_plain[width - 1] + 1
        while tail_start < len(plain) and unicodedata.category(plain[tail_start]).startswith("M"):
            tail_start += 1
        accents = "".join(c for c in plain[letters_plain[0]:tail_start] if c in (ACUTE, GRAVE, CIRCUMFLEX))
        capital = plain[letters_plain[0]].isupper()
        for original in originals:
            # The breathing sits on a single vowel, or on the second letter of a diphthong.
            vowels = original.upper() if capital and len(original) == 1 else (original[0].upper() + original[1:] if capital else original)
            word = vowels + breathing + accents.replace(GRAVE, ACUTE) + plain[tail_start:]
            found.append(_nfc(word.replace("ͅ", "")))
        break
    out, seen = [], set()
    for word in found:
        if word not in seen:
            seen.add(word)
            out.append({"form": word, "rule": "crasis_second_word",
                        "note": "Crasis: the parse is of the second, vowel-initial word fused into this spelling",
                        "tier": "dialect_normalised_query"})
    return out


def alpha_for_eta(form):
    """Doric/Aeolic ᾱ where Attic-Ionic has η (Buck § 8): νάσω -> νήσω.

    Each α that does not begin a diphthong (αι, αυ without diaeresis) is
    rewritten one at a time, keeping its accent and breathing; the caller keeps
    only spellings a source records.
    """
    decomposed = _nfd(_nfc(form))
    groups, index = [], 0
    while index < len(decomposed):
        end = index + 1
        while end < len(decomposed) and unicodedata.category(decomposed[end]).startswith("M"):
            end += 1
        groups.append((decomposed[index], decomposed[index + 1:end]))
        index = end
    found = []
    for k, (base, marks) in enumerate(groups):
        if base.lower() != "α":
            continue
        if k + 1 < len(groups) and groups[k + 1][0].lower() in "ιυ" and "̈" not in groups[k + 1][1]:
            continue
        replacement = "η" if base == "α" else "Η"
        rebuilt = groups[:k] + [(replacement, marks)] + groups[k + 1:]
        found.append(_nfc("".join(b + m for b, m in rebuilt)))
    return [{"form": item, "rule": "doric_aeolic_alpha_for_eta",
             "note": "Doric/Aeolic ᾱ where the standard spelling has η",
             "tier": "dialect_normalised_query"} for item in found[:4]]


def offline_variants(form, limit=10):
    """Labelled spellings to look up in the recorded-form index when nothing
    knows the printed form: the parser normalisations above, the elided vowel
    restored, the second word of a crasis, and Doric/Aeolic ᾱ for η."""
    found, seen = [], {_nfc(form)}
    for item in [*variants(form), *elision_restorations(form), *crasis_second_words(form), *alpha_for_eta(form)]:
        if item["form"] not in seen:
            seen.add(item["form"])
            found.append(item)
    return found[:limit]


def variants(form):
    """Ordered, labelled spelling variants to query; never more than four."""
    form = _nfc(form)
    found, seen = [], {form}

    def add(candidate, rule, note):
        candidate = _nfc(candidate)
        if candidate and candidate not in seen and len(found) < 6:
            seen.add(candidate)
            found.append({"form": candidate, "rule": rule, "note": note, "tier": "dialect_normalised_query"})

    shifted = _accent_shifted_right(form)
    if shifted:
        add(shifted, "recessive_accent", "Lesbian recessive accent: the edition accents the word one syllable earlier than the standard spelling")
    swapped = _initial_breathing_swap(form)
    if swapped:
        rule = "psilotic_rho" if _nfd(form)[0].lower() == "ρ" else "psilosis"
        add(swapped, rule, "Lesbian psilosis: the edition prints a smooth breathing where the standard spelling has a rough one")
    lowered = form.lower()
    for prefix, replacement, note in APOCOPE:
        if lowered.startswith(prefix) and len(form) > len(prefix) + 1:
            rest = form[len(prefix):]
            if _nfd(rest)[0] not in VOWELS:
                add(replacement + rest, "apocope_" + prefix, note)
                if swapped and _nfd(swapped)[0].lower() == form[0].lower():
                    add(replacement + swapped[len(prefix):], "apocope_" + prefix + "+psilosis", note)
            break
    for double, single in GEMINATES:
        index = form.find(double)
        if 0 < index:
            add(form[:index] + single + form[index + 2:], "aeolic_gemination_" + double,
                "Lesbian gemination (-" + double + "-) for the standard single consonant with a long vowel")
    if "ζ" in form[1:]:
        add(form.replace("ζ", "σσ", 1), "aeolic_zeta_for_sigma", "Lesbian -ζω for standard -σσω verbs")
    if "ὀνυμ" in lowered:
        index = lowered.index("ὀνυμ")
        replacement = "Ὀνομ" if form[index].isupper() else "ὀνομ"
        add(form[:index] + replacement + form[index + 4:], "aeolic_onyma", "Lesbian ὄνυμα for ὄνομα in names and compounds")
    if form[-1] in ELISION and len(form) > 2:
        # ἔγων’ beside a vowel: the word may be complete and only an enclitic
        # or final vowel elided; the parser accepts the bare word.
        bare = form[:-1]
        add(bare, "elision_mark_dropped", "The final elision mark is dropped; the remaining letters are read as a complete word")
        bare_shifted = _accent_shifted_right(bare)
        if bare_shifted:
            add(bare_shifted, "elision_mark_dropped+recessive_accent", "Elision mark dropped and the Lesbian recessive accent undone")
    lexical = LEXICAL.get(form)
    if lexical:
        add(lexical[0], "aeolic_lexical", lexical[1])
    if _nfd(form)[0].lower() == "ο" and SMOOTH in _nfd(form)[:3] and len(form) > 3 and _nfd(form)[2].lower() in "ηε":
        # ὀήϊα for οἰήϊα: Lesbian ὀ- where the standard spelling has οἰ-.
        add(_nfc("οἰ" + _nfd(form)[2:]) if form[0].islower() else _nfc("Οἰ" + _nfd(form)[2:]),
            "aeolic_o_for_oi", "Lesbian ὀ- for standard οἰ- before a vowel")
    if "η" in _nfd(form)[1:]:
        # Αἰολήαν for Αἰολείαν, κῆνος for κεῖνος: Lesbian η where Attic has ει.
        index = _nfd(form).index("η", 1)
        add(_nfc(_nfd(form)[:index] + "ει" + _nfd(form)[index + 1:]), "aeolic_eta_for_ei",
            "Lesbian η where the standard spelling has ει (secondary lengthening)")
    decomposed = _nfd(form)
    if CIRCUMFLEX in decomposed:
        # κεῖσεσθ’ for κείσεσθ(αι): the recessive accent turns an acute on a
        # long penult into a circumflex; the standard spelling keeps the acute.
        add(_nfc(decomposed.replace(CIRCUMFLEX, ACUTE, 1)), "circumflex_for_acute",
            "Lesbian recessive accent: a circumflex where the standard spelling has an acute on the same syllable")
    if lowered.startswith("εὐρ") and len(form) > 4:
        add("ἐρρ" + form[3:], "aeolic_eu_for_err", "Lesbian εὐρ- for standard ἐρρ- (εὐρύσαο for ἐρρύσαο)")
    return found
