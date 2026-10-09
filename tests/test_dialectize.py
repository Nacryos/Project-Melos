"""Release U: reverse dialect generator (backend/dialectize.py) with fake corpus and parser evidence."""
import unicodedata

import pytest

from backend.dialectize import Dialectizer, ParserEvidence, generate, key


def nfc(s):
    return unicodedata.normalize("NFC", s)


@pytest.mark.parametrize("form,dialect,expected,rules", [
    ("τηλόθεν", "lesbian", "πήλοθεν", {"labiovelar_p", "recessive_accent"}),
    ("σελήνη", "lesbian", "σελάννα", {"eta_to_alpha", "geminate"}),
    ("ἥλιος", "lesbian", "ἀέλιος", {"psilosis", "uncontracted_eta"}),
    ("ἥλιος", "doric", "ἅλιος", {"eta_to_alpha"}),
    ("φέρουσα", "lesbian", "φέροισα", {"oi_before_sigma"}),
    ("ἄγειν", "lesbian", "ἄγην", {"infinitive_ein"}),
    ("μόνος", "lesbian", "μόνα", {"feminine", "eta_to_alpha"}),
    ("χώρα", "ionic", "χώρη", {"alpha_to_eta"}),
    ("μόνος", "ionic", "μοῦνος", {"ionic_lengthening"}),
    ("θυμός", "lesbian", "θῦμος", {"recessive_accent"}),
    ("εἰμί", "lesbian", "ἔμμι", {"geminate", "recessive_accent"}),
    ("ἐκεῖνος", "lesbian", "κῆνος", {"lesbian_lexical"}),
    ("ὅτε", "doric", "ὅκα", {"temporal_ka"}),
    ("πᾶσα", "lesbian", "παῖσα", {"ai_before_sigma"}),
])
def test_generates_known_dialect_spellings(form, dialect, expected, rules):
    hits = [g for g in generate(form, dialect) if g[0] == nfc(expected)]
    assert hits, f"{form} -> {expected} not generated"
    assert set(hits[0][1]) == rules


def test_rules_stay_in_their_dialect():
    assert not [g for g in generate("σελήνη", "ionic") if g[0] == nfc("σελάννα")]
    assert not [g for g in generate("χώρα", "lesbian") if g[0] == nfc("χώρη")]


class FakeIndex:
    def __init__(self, printed, headwords):
        self.printed = printed          # spelling -> (tokens, [lemma], dialect_tokens)
        self.headword_of = headwords    # input form -> [lemma]

    def headwords(self, form):
        return [(None, h) for h in self.headword_of.get(form, [])]

    def forms(self, spellings):
        return {s: {"form_ids": [1], "tokens": self.printed[s][0], "lemmas": [(None, l) for l in self.printed[s][1]]}
                for s in spellings if s in self.printed}

    def related_keys(self, lemma_ids):
        return set()

    def attestation(self, spelling, form_ids, lemma_ids, dialect, author="", scan=250):
        n = self.printed[spelling][2]
        return {"dialect_tokens": n, "dialect_authors": [{"author": "Sappho", "tokens": n}] if n else [],
                "author_tokens": None, "example": {"passage_id": "x", "citation": "fr. 154"} if n else None,
                "passages_scanned": 1}


def test_accepts_only_attested_or_parsed_under_the_same_headword():
    index = FakeIndex({nfc("σελάννα"): (12, ["σελήνη"], 4), nfc("σελάνα"): (3, ["σελήνη"], 0),
                       nfc("σελάννη"): (1, ["ἄλλος"], 0)},
                      {nfc("σελήνη"): ["σελήνη"]})
    parser = ParserEvidence(analyze=lambda s: [{"lemma": "σελήνη", "parse": "noun", "dialect_tag": "Aeolic"}]
                            if s == nfc("σελᾶνα") else [{"lemma": "σέλας", "parse": "noun", "dialect_tag": None}])
    out = Dialectizer(index, parser, max_parses=200).dialectize([nfc("σελήνη")], "lesbian", debug=True)
    cands = {c["form"]: c for c in out["results"][0]["candidates"]}
    assert cands[nfc("σελάννα")]["verdict"] == "attested_in_dialect"
    assert cands[nfc("σελάννα")]["evidence"]["attested_authors"][0]["author"] == "Sappho"
    assert cands[nfc("σελάνα")]["verdict"] == "attested_elsewhere"
    assert nfc("σελάννη") not in cands   # printed, but under another headword
    rejected = {r["form"] for r in out["results"][0]["rejected"]}
    assert nfc("σελάννη") in rejected
    # generated spellings the parser reads with another lemma are refused
    assert all(c["evidence"]["kind"] != "parses" or c["evidence"]["parses"][0]["lemma"] == "σελήνη"
               for c in cands.values())


def test_parse_only_candidate_is_labelled():
    index = FakeIndex({}, {nfc("ἄγειν"): ["ἄγω"]})
    parser = ParserEvidence(analyze=lambda s: [{"lemma": "ἄγω", "parse": "verb pres inf act", "dialect_tag": "Aeolic"}]
                            if s == nfc("ἄγην") else [])
    out = Dialectizer(index, parser).dialectize([nfc("ἄγειν")], "lesbian")
    cand = [c for c in out["results"][0]["candidates"] if c["form"] == nfc("ἄγην")][0]
    assert cand["verdict"] == "parses_only" and cand["evidence"]["parses"][0]["dialect_tag"] == "Aeolic"
    assert cand["rules"][0]["id"] == "infinitive_ein"


def test_dialect_form_under_attic_headword_is_kept_other_words_are_not():
    # The index files πήλοθεν under τηλόθεν: accepted. κάλλος "beauty" is spelled by the gemination rule
    # from καλός but is its own headword: refused. ἄγαν read first as ἄγω but also as the adverb: flagged.
    index = FakeIndex({nfc("πήλοθεν"): (3, ["τηλόθεν"], 3), nfc("κάλλος"): (372, ["κάλλος"], 5),
                       nfc("ἄγαν"): (398, ["ἄγω", "ἄγη", "ἄγαν"], 0)},
                      {nfc("τηλόθεν"): ["τηλόθεν"], nfc("καλός"): ["καλός"], nfc("ἄγειν"): ["ἄγω"]})
    dz = Dialectizer(index, ParserEvidence(analyze=lambda s: []))
    out = dz.dialectize([nfc("τηλόθεν"), nfc("καλός"), nfc("ἄγειν")], "lesbian")
    assert [c["form"] for c in out["results"][0]["candidates"]] == [nfc("πήλοθεν")]
    assert out["results"][1]["candidates"] == []
    agan = [c for c in out["results"][2]["candidates"] if c["form"] == nfc("ἄγαν")][0]
    assert agan["also_read_as"] == ["ἄγη", "ἄγαν"]


def test_route_validation():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.dialectize as dz
    from backend.dialectize_routes import router
    app = FastAPI()
    app.include_router(router)
    dz._SERVICE = Dialectizer(FakeIndex({nfc("σελάννα"): (12, ["σελήνη"], 4)}, {nfc("σελήνη"): ["σελήνη"]}),
                              ParserEvidence(analyze=lambda s: []))
    try:
        client = TestClient(app)
        assert client.post("/api/dialectize", json={"forms": []}).status_code == 422
        assert client.post("/api/dialectize", json={"form": "σελήνη", "dialect": "attic"}).status_code == 422
        assert client.post("/api/dialectize", json={"form": "two words"}).status_code == 422
        r = client.post("/api/dialectize", json={"form": "σελήνη", "dialect": "lesbian"})
        assert r.status_code == 200
        assert r.json()["results"][0]["candidates"][0]["form"] == nfc("σελάννα")
        # author picks the dialect when none is given
        r = client.post("/api/dialectize", json={"form": "σελήνη", "author": "Sappho"})
        assert r.json()["dialect"] == "lesbian"
    finally:
        dz._SERVICE = None


def test_key_folds_marks():
    assert key("Σελάννᾳ") == "σελαννα"


def test_spelling_of_another_word_needs_the_parser():
    # Lesbian παῖς = πᾶς is printed, but indexed under παῖς "child": accepted only because the parser reads
    # it as πᾶς, and flagged with the other reading.
    index = FakeIndex({nfc("παῖς"): (900, ["παῖς"], 30)}, {nfc("πᾶς"): ["πᾶς"]})
    parser = ParserEvidence(analyze=lambda s: [{"lemma": "πᾶς", "parse": "adj nom sg masc", "dialect_tag": "Aeolic"},
                                               {"lemma": "παῖς", "parse": "noun nom sg", "dialect_tag": None}]
                            if s == nfc("παῖς") else [])
    out = Dialectizer(index, parser).dialectize([nfc("πᾶς")], "lesbian")
    cand = [c for c in out["results"][0]["candidates"] if c["form"] == nfc("παῖς")][0]
    assert cand["also_read_as"] == ["παῖς"] and cand["evidence"]["parses"][0]["lemma"] == "πᾶς"
    assert cand["rules"][0]["id"] == "ai_before_sigma"
