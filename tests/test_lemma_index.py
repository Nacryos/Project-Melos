"""Release O corpus headword index: tokens, read API, edition grouping, catalogue, gloss bridge."""
import json
import sqlite3

import numpy as np
import pytest

from backend.lemma_tokens import word_tokens, clean_form, fold
from backend.lemma_index import LemmaIndex, SCHEMA, _find_span, _log_likelihood
from backend.lemma_glosses_index import english_terms, gloss_terms
from backend.retrieval import group_editions
from backend.author_catalogue import author_record, display_work, period_of

FORMS = {  # printed form -> (headword, gloss)
    "σελάνναν": "σελήνη", "σελήνη": "σελήνη", "σελήνης": "σελήνη", "ἄστερες": "ἀστήρ", "ἀστέρες": "ἀστήρ",
    "κάλαν": "καλός", "καλή": "καλός", "Ἔρος": "ἔρως", "ἔρως": "ἔρως", "γλυκύπικρον": "γλυκύπικρος",
    "ῥοδοδάκτυλος": "ῥοδοδάκτυλος", "Ἠώς": "ἠώς", "μέν": "μέν", "μὲν": "μέν", "ἀμφὶ": "ἀμφί", "λάμπει": "λάμπω",
}
GLOSS = {"σελήνη": "the moon", "ἀστήρ": "star", "καλός": "beautiful", "ἔρως": "love, desire",
         "γλυκύπικρος": "bittersweet", "ῥοδοδάκτυλος": "rosy-fingered", "ἠώς": "the dawn", "μέν": "on the one hand",
         "ἀμφί": "around", "λάμπω": "to shine", "μήνη": "the moon"}
PASSAGES = [
    ("p:sappho:34", "Sappho", "ἄστερες μὲν ἀμφὶ κάλαν σελάνναν"),
    ("p:sappho:130", "Sappho", "Ἔρος γλυκύπικρον"),
    ("p:homer:1", "Homer", "ῥοδοδάκτυλος Ἠώς σελήνη λάμπει"),
    ("p:homer:2", "Homer", "ἀστέρες ἀμφὶ σελήνης καλή"),
    ("p:pindar:1", "Pindar", "ἔρως καλή σελήνη"),
]


def build(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    lemmas = {}
    forms = {}
    postings = {}
    tokens_by_lemma = {}
    for pid, (identifier, author, text) in enumerate(PASSAGES, start=1):
        toks = word_tokens(text)
        lem, fid = [], []
        for _, _, _, form, _ in toks:
            head = FORMS[form]
            lid = lemmas.setdefault(head, len(lemmas) + 1)
            f = forms.setdefault(form, len(forms) + 1)
            lem.append(lid)
            fid.append(f)
            postings[(lid, pid)] = postings.get((lid, pid), 0) + 1
            tokens_by_lemma[lid] = tokens_by_lemma.get(lid, 0) + 1
        con.execute("INSERT INTO passage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, identifier, "text", "source_text", "grc", author, author, "Fragments", identifier.split(":")[-1],
                     "test", len(toks), len(set(lem))))
        con.execute("INSERT INTO tok VALUES (?,?,?,?,?,?,?)", (
            pid, np.asarray(lem, np.uint32).tobytes(), np.asarray(fid, np.uint32).tobytes(),
            np.full(len(toks), 230, np.uint8).tobytes(), np.full(len(toks), 1, np.uint8).tobytes(),
            np.asarray([t[0] for t in toks], np.uint32).tobytes(),
            np.asarray([t[1] - t[0] for t in toks], np.uint16).tobytes()))
    lemmas.setdefault("μήνη", len(lemmas) + 1)
    for head, lid in lemmas.items():
        con.execute("INSERT INTO lemma VALUES (?,?,?,?,?,?,?,?,?)",
                    (lid, head, fold(head), "noun", "headword", tokens_by_lemma.get(lid, 0),
                     len({p for (l, p) in postings if l == lid}), GLOSS[head], "Middle Liddell"))
        for term, field, weight in gloss_terms(GLOSS[head], {"heads": [GLOSS[head]], "full": GLOSS[head]}):
            con.execute("INSERT INTO lemma_gloss_term VALUES (?,?,?,?)", (term, lid, field, weight))
    for form, f in forms.items():
        con.execute("INSERT INTO form VALUES (?,?,?,?,?,?)", (f, form, fold(form), 1, "parsed", None))
        con.execute("INSERT INTO form_lemma VALUES (?,?,?,?,?,?)", (f, lemmas[FORMS[form]], 0, 1.0, 1, '["acc fem sg"]'))
    for (lid, pid), n in sorted(postings.items()):
        con.execute("INSERT INTO posting VALUES (?,?,?)", (lid, pid, n))
    con.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps({"version": "test", "tokens": {}}),))
    con.commit()
    con.close()
    return lemmas


@pytest.fixture()
def index(tmp_path):
    path = tmp_path / "lemma_index.sqlite"
    lemmas = build(path)
    ix = LemmaIndex(path)
    ix.lemma_ids = lemmas
    return ix


def text_of(identifier):
    return {i: t for i, _, t in PASSAGES}[identifier]


def test_tokens_keep_offsets_and_strip_editorial_signs():
    toks = word_tokens("Κύπρι καὶ] ἀβλάβη[ν δ[ό]τε τυίδ’")
    assert [t[3] for t in toks] == ["Κύπρι", "καὶ", "ἀβλάβην", "δότε", "τυίδ’"]
    assert [t[4] for t in toks] == [False, True, True, True, False]
    assert clean_form("δ᾽") == "δ’"
    text = "ἄστερες μὲν"
    assert text[toks[0][0]:toks[0][1]] if False else word_tokens(text)[1][:2] == (8, 11)


def test_resolve_headword_form_and_english(index):
    assert index.resolve("σελήνη")[0]["lemma"] == "σελήνη"
    assert index.resolve("σελάνναν")[0]["lemma"] == "σελήνη"
    assert index.resolve("σεληνη")[0]["lemma"] == "σελήνη"  # accents ignored
    english = index.english_lemmas("moon")
    assert {r["lemma"] for r in english} == {"σελήνη"}  # μήνη has no corpus tokens
    assert index.english_lemmas("rose-fingered")[0]["lemma"] == "ῥοδοδάκτυλος"


def test_search_frequency_distribution(index):
    moon = index.lemma_ids["σελήνη"]
    result = index.search([moon])
    assert result["total_passages"] == 4 and result["total_tokens"] == 4
    assert {f["form"] for f in result["forms_found"]} == {"σελάνναν", "σελήνη", "σελήνης"}
    freq = index.frequency(moon)
    assert freq["tokens"] == 4 and freq["rank"] == 1
    authors = {row["author"]: row for row in freq["by_author"]}
    assert authors["Homer"]["count"] == 2 and authors["Sappho"]["count"] == 1
    assert authors["Sappho"]["per_10k"] == round(1e4 / 7, 2)  # Sappho: 5 + 2 tokens
    periods = {row["period"] for row in freq["by_period"]}
    assert periods <= {"Archaic (to 480 BCE)", "Classical (480–323 BCE)", "undated"}


def test_concordance_kwic(index):
    moon = index.lemma_ids["σελήνη"]
    lines = index.concordance([moon], text_lookup=text_of, width=12)["lines"]
    assert len(lines) == 4
    sappho = next(l for l in lines if l["id"] == "p:sappho:34")
    assert sappho["keyword"] == "σελάνναν" and sappho["left"].endswith("κάλαν") and sappho["right"] == ""


def test_collocations_and_log_likelihood(index):
    moon = index.lemma_ids["σελήνη"]
    result = index.collocations(moon, window=3, min_count=2, function_words=True)
    names = {c["lemma"] for c in result["collocates"]}
    assert "καλός" in names and "ἀμφί" in names
    assert _log_likelihood(10, 100, 20, 10000) > 0


def test_proximity_ordered_and_unordered(index):
    rosy, dawn = index.lemma_ids["ῥοδοδάκτυλος"], index.lemma_ids["ἠώς"]
    assert index.proximity([[rosy], [dawn]], window=0)["total"] == 1
    assert index.proximity([[dawn], [rosy]], window=0)["total"] == 0
    assert index.proximity([[dawn], [rosy]], window=0, ordered=False)["total"] == 1
    assert _find_span([[0, 9], [3]], 3, True) == (0, 3)


def test_passage_signal_prefers_covering_short_passages(index):
    groups = [{index.lemma_ids["ἔρως"]: 1.0}, {index.lemma_ids["καλός"]: 1.0}]
    hits = index.passage_signal(groups)
    assert hits[0]["id"] == "p:pindar:1" and hits[0]["groups_matched"] == 2


def test_diachrony_honest_fields(index):
    out = index.diachrony("moon")
    row = out["lemmas"][0]
    assert row["lemma"] == "σελήνη" and row["tokens"] == 4
    assert [p["period"] for p in row["by_period"]][0].startswith("Archaic")
    assert any("not composition dates" in n or "composition" in n for n in out["notes"])


def test_group_editions_folds_same_text_same_author():
    results = [
        {"id": "a", "author": "Sappho", "language": "grc", "text": "ἄστερες μὲν ἀμφὶ κάλαν σελάνναν ἀπυκρύπτοισι φάεννον"},
        {"id": "b", "author": "Sappho", "language": "grc", "text": "ἄστερες μεν αμφι καλαν σελανναν αψ απυκρυπτοισι"},
        {"id": "c", "author": "Alcaeus", "language": "grc", "text": "ἄστερες μὲν ἀμφὶ κάλαν σελάνναν ἀπυκρύπτοισι"},
    ]
    kept, folded = group_editions(results)
    assert [r["id"] for r in kept] == ["a", "c"] and folded == 1
    assert kept[0]["editions"][0]["id"] == "b" and kept[0]["edition_count"] == 2


def test_catalogue_genre_dates_and_work_titles():
    sappho = author_record("sappho")
    assert sappho["author"] == "Sappho" and sappho["genre"] == "melic lyric"
    assert sappho["date"]["approximate"] in (True, False)
    nonnus = author_record("nonnus")
    assert nonnus["author"] == "Nonnus" and (nonnus["date"] is None or nonnus["period"])
    assert author_record("apollonius-rhodius-epic")["author"] == "Apollonius Rhodius"
    assert display_work("theogonia") == "Theogony" and display_work("tlg0199-tlg001") == "Epinicians"
    assert period_of(-600).startswith("Archaic") and period_of(None) is None


def test_english_terms_compounds():
    assert english_terms("rose-fingered") == ["ros", "finger", "ros-finger", "rosefinger"]
    assert english_terms("the moon") == ["moon"]
