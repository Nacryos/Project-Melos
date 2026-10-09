"""Release Q calibration classes and the lyric gold builder (general rules; other words)."""
import importlib.util
from pathlib import Path

from backend.lemma_calibration import apply_model, evidence_class, same_lexeme

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location("blg", ROOT / "scripts" / "build_lyric_lemma_gold.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_context_disagreement_and_recorded_form_split_the_no_signal_class():
    assert evidence_class(1) == "no_context_signal"
    assert evidence_class(1, 1) == "context_disagrees"
    assert evidence_class(1 | 2) == "recorded_form_no_context"
    assert evidence_class(1 | 2, 1) == "context_disagrees"
    # stronger evidence classes are unaffected by the flag
    assert evidence_class(1 | 16, 1) == "context_agrees"
    assert evidence_class(1 | 32, 1) == "context_chose"
    assert evidence_class(1 | 64, 1) == "damaged_word"


def test_old_map_without_new_classes_falls_back_to_pooled():
    model = {"all": [[0, 255, 0.9, 10]], "no_context_signal": [[0, 255, 0.5, 10]]}
    assert apply_model(model, 200, 1) == 0.5
    assert apply_model(model, 200, 1, 1) == 0.9          # context_disagrees not fitted -> pooled
    assert apply_model(model, 200, 1 | 2) == 0.9         # recorded_form_no_context not fitted -> pooled


def test_same_lexeme_needs_recorded_form_and_matching_part_of_speech():
    recorded = {"κάλλιστα": ["καλός"], "ἧς": ["ὅς", "ἑός"]}.get

    def form_lemmas(s):
        return recorded(s) or []
    assert same_lexeme("κάλλιστα", "καλός", "adverb", "adjective", form_lemmas)      # adverb of the adjective
    assert same_lexeme("καλός", "κάλλιστα", "adjective", "adverb", form_lemmas)      # either direction
    assert not same_lexeme("ἧς", "ὅς", "particle", "pronoun", form_lemmas)           # another word, same spelling
    assert not same_lexeme("χρυσός", "καλός", "noun", "noun", form_lemmas)           # not recorded as related
    assert not same_lexeme("κάλλιστα", "καλός", None, "adjective", form_lemmas)      # unknown POS: no claim


def test_lyric_gold_citations_and_line_numbers():
    b = _builder()
    m = list(b.CITE.finditer("cf. Sapph. 2.7, Alc. 34a, Thgn. 1197, Alc.Com.5"))
    found = [(x[1], x[2], x[3]) for x in m]
    assert ("Sapph", "2", "7") in found and ("Alc", "34a", None) in found and ("Thgn", "1197", None) in found
    assert not any(x[1] == "Alc" and x[2] == "5" for x in m)
    rec = {"lines": [{"label": ""}, {"label": ""}, {"label": "5"}, {"label": ""}]}
    assert b.line_numbers(rec) == [3, 4, 5, 6]
    assert b.line_numbers({"lines": [{"label": ""}, {"label": ""}]}) == [1, 2]
