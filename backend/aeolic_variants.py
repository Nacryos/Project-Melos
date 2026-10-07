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
