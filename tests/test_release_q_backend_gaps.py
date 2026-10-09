"""Release Q backend gaps: printed line numbers out of display text, variant links need matching
senses and a "= B" that names the headword itself. General rules, other words than the reports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from backend.lemma_index import display_context  # noqa: E402
import build_lemma_index as build  # noqa: E402


def test_line_numbers_become_metadata():
    text = "ἄειδε 12 θεὰ μῆνιν 13a ἄλγε’ ἔθηκε"
    i = text.index("μῆνιν")
    left, right, numbers = display_context(text, i, i + len("μῆνιν"), 40)
    assert left == "ἄειδε θεὰ" and right == "ἄλγε’ ἔθηκε"
    assert numbers == ["12", "13a"]


def test_numbers_inside_words_are_kept():
    text = "fr. 2a(i) καλὸν"
    i = text.index("καλὸν")
    left, _, numbers = display_context(text, i, len(text), 40)
    assert left == "fr. 2a(i)" and numbers == []


def test_variant_needs_matching_sense():
    assert not build.senses_agree("barren", "the moon")
    assert build.senses_agree("dawn", "the dawn, morning")
    assert build.senses_agree(None, "anything")       # no meaning of its own: the link supplies it


class _Heads:
    def __init__(self, entries):
        self.entries = entries

    def lookup(self, head):
        return ("exact", self.entries[head]) if head in self.entries else (None, [])

    def headword_key(self, text):
        return text


def test_equals_must_name_the_headword_itself():
    heads = _Heads({"μήνη": [{"gloss": "", "entry_text": "μήνη = σελήνη", "source": "D"}],
                    "Ἀθηναῖος": [{"gloss": "", "entry_text": "Ἀθηναῖος adj. Ἀθῆναι = Ἀθήνη of Athens", "source": "D"}]})
    ids = {"μήνη": 1, "σελήνη": 2, "Ἀθηναῖος": 3, "Ἀθήνη": 4}
    tokens = {i: 1 for i in ids.values()}
    glosses = {1: "the moon", 2: "the moon", 3: "Athenian", 4: "Athena"}
    rows = build.lemma_variants(ids, tokens, heads, glosses)
    assert [(r[0], r[1]) for r in rows] == [(1, 2)]
