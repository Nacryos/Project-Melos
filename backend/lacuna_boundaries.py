"""Conservative boundary metadata for explicitly identified critical texts.

Printed spaced dot runs in fragmentary editions can separate surviving letters
without establishing a lexical boundary. This is uncertainty metadata, not a
restoration or a declaration that either adjacent word is incomplete/invalid.
The caller must opt in from source metadata; arbitrary prose ellipses must not
silently become physical lacunae.

Source motivating the boundary distinction: Campbell, Greek Lyric Poetry,
Alcaeus 130, printed p. 57 / commentary p. 296 note 16 (user-supplied PDF).
No source Greek or lexical answer is encoded here.
"""
from bisect import bisect_left, bisect_right
from copy import deepcopy
import re
import unicodedata


# A run of spaced dots (". . .") marks several lost letters; a single dot
# standing between spaces (" . ") marks one lost letter. Both separate
# surviving letters from the lost ones without establishing a word boundary.
# Also a dot printed directly against a letter (".\u03af.\u03b1\u03b9\u03c2"): a sentence period is
# followed by space or line end, a lost-letter dot is followed by a letter.
_DOT_RUN = re.compile(r"\.(?:[\t \u00a0\u202f]*\.)+|(?<=[\t \u00a0\u202f\[\]])\.(?=[\t \u00a0\u202f\[\]])|\.(?=[^\W\d_])")
_BRACKETS = frozenset("[]⟦⟧⟨⟩<>")


def _adjacent_material(value):
    """Horizontal typesetting space/editorial brackets, never another word/line."""
    return all(char == "\t" or unicodedata.category(char) == "Zs"
               or char in _BRACKETS for char in value)


def annotate_lacuna_boundaries(text, tokens, *, source_critical):
    """Return copied tokens with offset-bound evidence of nearby printed loss.

Offsets address the *full unchanged source text*, even when tokens cover only a
selection. Existing partial-word and editorial-fragment statuses are untouched.
Consumers may still offer literal-string lookups conditionally; this flag must
not be promoted into an intact attestation or a resolved contextual meaning.
"""
    result = deepcopy(tokens)
    if source_critical is not True:
        return result
    gaps = [(match.start(), match.end()) for match in _DOT_RUN.finditer(text)]
    starts, ends = [gap[0] for gap in gaps], [gap[1] for gap in gaps]
    for token in result:
        if token.get("kind") != "word":
            continue
        start, end = token.get("start"), token.get("end")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or text[start:end] != token.get("text")):
            raise ValueError("Lacuna boundary token offsets must match unchanged source text.")
        evidence = []
        left = bisect_right(ends, start) - 1
        if left >= 0 and _adjacent_material(text[ends[left]:start]):
            evidence.append({"start": starts[left], "end": ends[left], "side": "before",
                             "offset_unit": "codepoint", "basis": "printed_dot_run"})
        right = bisect_left(starts, end)
        if right < len(gaps) and _adjacent_material(text[end:starts[right]]):
            evidence.append({"start": starts[right], "end": ends[right], "side": "after",
                             "offset_unit": "codepoint", "basis": "printed_dot_run"})
        if evidence:
            token["lacuna_boundary_uncertain"] = True
            token["lacuna_boundary_evidence"] = evidence
    return result


def intact_word_eligible(token):
    """Mechanical coverage eligibility only, never a lexical correctness claim."""
    return token.get("kind") == "word" and not any(token.get(key) for key in (
        "partial_word", "editorial_fragment", "uncertain_letters", "lacuna_boundary_uncertain"))
