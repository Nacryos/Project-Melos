"""Rule registry: every branch of the scanner's decision tree, with a one-line citation.

Smyth = H. W. Smyth, A Greek Grammar for Colleges (1920), Perseus 1999.04.0007
        (http://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.04.0007:smythp=N).
Monro = D. B. Monro, A Grammar of the Homeric Dialect (2nd ed. 1891), Dickinson College
        Commentaries edition (https://dcc.dickinson.edu/grammar/monro/), CC BY-SA.
"""
from __future__ import annotations

RULES: dict[str, tuple[str, str]] = {
    # --- syllabification -----------------------------------------------------------------------
    "SYL-1": ("vowel + ι/υ written as a diphthong is one syllable", "Smyth §5, §140"),
    "SYL-2": ("diaeresis on ι/υ: two syllables, no diphthong", "Smyth §8"),
    "SYL-3": ("breathing or accent on the first vowel: two syllables (a diphthong carries them on its second vowel)", "Smyth §11, §152"),
    "SYL-4": ("ι written beside η, ω or circumflexed α (adscript) counts as iota subscript", "Smyth §5, §11"),
    "SYL-5": ("a new line (verse end) stops position: consonants do not carry across it", "Smyth §144a (position runs across words within the verse)"),
    "ELI-1": ("elided final vowel is not pronounced; the remaining consonant joins the next word", "Smyth §70; Monro §376"),
    "ELI-2": ("prodelision (aphaeresis): an initial ε lost after a long vowel", "Smyth §76"),
    "CRA-1": ("crasis (coronis inside a word) produces a long vowel", "Smyth §62, §147b"),
    # --- nature ----------------------------------------------------------------------------------
    "NAT-ETA": ("η and ω are long by nature", "Smyth §143"),
    "NAT-DIPH": ("a diphthong is long by nature", "Smyth §143"),
    "NAT-CIRC": ("a vowel with the circumflex is long", "Smyth §147a, §170"),
    "NAT-ISUB": ("ᾳ ῃ ῳ (iota subscript) are long", "Smyth §5, §143"),
    "NAT-EO": ("ε and ο are short by nature", "Smyth §142"),
    # --- dichrona α ι υ: accent ------------------------------------------------------------------
    "ACC-PROPAROX": ("acute on the antepenult: the ultima's α ι υ is short", "Smyth §163, §166, §170"),
    "ACC-PROPERISP": ("circumflex on the penult: the ultima's α ι υ is short", "Smyth §167c, §170"),
    "ACC-PAROX-LONG": ("acute on a long penult: the ultima's α ι υ is long (else the penult would have the circumflex)", "Smyth §166-167"),
    "ACC-PAROX-SHORT": ("acute on the penult before a short ultima: the penult's α ι υ is short (φίλος)", "Smyth §167b, §170"),
    "ACC-PAROX-SHORT-AIOI": ("as ACC-PAROX-SHORT with final -αι/-οι counted short (not in the optative)", "Smyth §169"),
    # --- dichrona: lexical data ------------------------------------------------------------------
    "LEX-L": ("lexical sources mark this α ι υ long", "Morpheus stems/endings; Wiktionary; LSJ (Perseus, Logeion)"),
    "LEX-S": ("lexical sources mark this α ι υ short", "Morpheus stems/endings; Wiktionary; LSJ (Perseus, Logeion)"),
    "LEX-CONFLICT": ("lexical sources disagree (homographs or variant quantities)", "Morpheus; Wiktionary; LSJ"),
    "LEX-ENDING": ("Morpheus ending without a length mark (its ending tables mark long α ι υ)", "Morpheus stemlib endtables"),
    "LEX-UNMARKED": ("the lexical sources know the word but give this α ι υ no length mark", "Morpheus stems; Wiktionary forms"),
    "DIA-ETA": ("Doric/Aeolic α where the Attic-Ionic form has η: ᾱ", "Smyth §30"),
    "DICH-UNK": ("α ι υ of unknown length (no accent rule or lexical mark applies)", "Smyth §147"),
    # --- position --------------------------------------------------------------------------------
    "POS-WORD": ("long by position: two consonants inside the word", "Smyth §144"),
    "POS-DOUBLE": ("long by position: double consonant ζ ξ ψ", "Smyth §144"),
    "POS-ACROSS": ("long by position: consonants on both sides of a word boundary", "Smyth §144a"),
    "POS-INIT": ("long by position: the next word begins with two consonants", "Smyth §144a"),
    "MCL-WORD": ("stop + liquid/nasal inside the word after a short vowel: weak position (either)", "Smyth §145; Monro §370"),
    "MCL-INIT": ("stop + liquid/nasal beginning the next word after a short vowel: weak position (either)", "Smyth §145; Monro §370"),
    # --- vowel before vowel ----------------------------------------------------------------------
    "COR-EXT": ("long vowel or diphthong at word end before a vowel: may be shortened (epic correption)", "Monro §380"),
    "COR-INT": ("long vowel or diphthong before a vowel inside a word: may be shortened (internal correption)", "Smyth §148; Monro §380"),
    "HIA-SHORT": ("short vowel at word end before a vowel (hiatus, not elided)", "Monro §379"),
    "SYN-CAND": ("ε/η + vowel: may merge into one long syllable (synizesis)", "Smyth §60; Monro §378"),
    # --- Homeric phenomena ----------------------------------------------------------------------
    "DIG-HIA": ("next word once began with ϝ: hiatus without correption or elision expected", "Monro §§390-392"),
    "DIG-LEN": ("short syllable before a word that once began with ϝ (or δϝ, ϝρ): may count long", "Monro §§390-395"),
    "EPL-INIT": ("short final vowel before initial ρ λ μ ν σ δ: may count long (epic)", "Monro §371"),
    "CONS-VOW": ("short syllable ending in a consonant before a vowel: short (occasionally lengthened in arsis)", "Monro §375"),
    # --- verse ----------------------------------------------------------------------------------
    "FIN-ANC": ("last syllable of a verse line: its length is indifferent to the metre (brevis in longo)", "Monro §366"),
}


def describe(rule_id: str) -> dict:
    text, cite = RULES[rule_id]
    return {"id": rule_id, "text": text, "cite": cite}
