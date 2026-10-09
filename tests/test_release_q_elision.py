"""Release Q: elided-word readings (backend/elision.py). General rules; other words than the
calibration's commonest errors."""
from backend.elision import (ElisionModel, base_distribution, is_elided, is_tie, key, next_initial, position,
                             restorations, token_features)


def keys(form, rough=None):
    return {r for r, needs in restorations(form) if rough is None or needs == rough}


def test_only_vowels_are_restored():
    out = keys("οὐδ’")
    assert "οὐδέ" in out and "οὐδε" in out
    assert all(r.startswith("οὐδ") and len(r) <= len("οὐδ") + 2 for r in out)
    assert not is_elided("οὐδέ") and is_elided("οὐδ᾽")


def test_aspirate_stands_for_stop_only_before_rough_breathing():
    assert "ἀντί" in keys("ἀνθ’", rough=True)
    assert "ἀντί" not in keys("ἀνθ’", rough=False)
    cands = {"ἀντί": 0.5, "ἄνθος": 0.5}
    freq = {"ἀντί": {"ἀντί": 100}, "ἄνθε": {"ἄνθος": 1}}
    plain = base_distribution("ἀνθ’", cands, freq.get, rough_next=False)
    rough = base_distribution("ἀνθ’", cands, freq.get, rough_next=True)
    assert rough["ἀντί"] > plain["ἀντί"]


def test_accented_stem_allows_retracted_oxytone():
    out = keys("δείν’")
    assert "δεῖνα" not in out          # never a new circumflex
    assert "δεινά" in out and "δείνα" in out


def test_unaccented_stem_restores_oxytone_or_atonic_only():
    out = keys("ὑπ’")
    assert "ὑπό" in out and "ὕπο" not in out


def test_next_initial_and_position():
    text = "λόγον, οὐδ’ αἱ δ’ ῥόδα · ἀνθ’ ὧν\nγάρ"
    assert next_initial(text, text.index("οὐδ’") + 4) == "rough"      # αἱ: breathing on the iota
    assert next_initial(text, text.index("δ’ ῥ") + 2) == "rho"
    assert next_initial(text, text.index("ἀνθ’") + 4) == "rough"
    assert next_initial(text, len(text)) == "none"
    assert position(text, 0) == "start"
    assert position(text, text.index("οὐδ’")) == "comma"
    assert position(text, text.index("ἀνθ’")) == "start"
    assert position(text, text.index("γάρ")) == "line"
    assert position(text, text.index("αἱ")) == "medial"


def test_key_ignores_case_grave_and_elision_sign():
    assert key("Οὐδ᾽") == key("οὐδ’")
    assert key("ἀντὶ") == key("ἀντί")


def test_tie_needs_a_different_reading():
    assert is_tie([("Πάρις", 0.5), ("πάρις", 0.45)]) is None
    assert is_tie([("μέν", 0.55), ("μήν", 0.4)]) == ("μήν", 0.4)
    assert is_tie([("μέν", 0.9), ("μήν", 0.1)]) is None


def test_model_prior_and_features_rank_readings():
    model = ElisionModel({
        "prior": {"οὐδ’": {"οὐδέ": 9, "οὐδός": 1}},
        "features": {"next_pos": {"οὐδέ": {"VERB": 5}, "οὐδός": {"NOUN": 5}}},
        "class_features": {"next_pos": {"conjunction": {"VERB": 5}, "noun": {"NOUN": 5}}},
        "values": {"next_pos": ["NOUN", "VERB"]},
        "params": {"alpha": 1.0, "beta": 3.0, "tau": 1.0}})
    base = {"οὐδέ": 0.5, "οὐδός": 0.5}
    classes = {"οὐδέ": "conjunction", "οὐδός": "noun"}
    ranked = model.rank("οὐδ’", base, classes, {"next_pos": "VERB"}, key)
    assert ranked[0][0] == "οὐδέ"
    unseen = model.rank("ἀνθ’", {"ἀντί": 0.3, "ἄνθος": 0.7}, {}, {}, key)
    assert unseen[0][0] == "ἄνθος"     # no train counts: the base distribution decides


def test_token_features_read_neighbours():
    from backend.lemma_tokens import word_tokens
    text = "καὶ οὐδ’ ἔβη"
    toks = word_tokens(text)
    preds = {toks[0][0]: [0, 3, "καί", "CCONJ"], toks[2][0]: [9, 12, "βαίνω", "VERB"]}
    f = token_features(text, toks, 1, preds)
    assert f["prev_pos"] == "CCONJ" and f["next_pos"] == "VERB" and f["own_pos"] == "UNK"
    assert f["next_initial"] == "smooth" and f["position"] == "medial"
