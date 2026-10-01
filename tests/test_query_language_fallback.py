"""Synthetic API regression fixtures; no rows enter the literary corpus."""
import pytest
from backend import server
from test_api import client


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-wedding-note", "author": "Alpha", "work": "Notes", "citation": "wedding",
     "language": "eng", "kind": "commentary", "text": "Hector and Andromache celebrate a wedding"},
    {"id": "synthetic-accidental-greek", "author": "Alpha", "work": "Song", "citation": "accidental",
     "text": "τηε ανδ"},
]], indirect=True)
def test_description_keeps_original_words_and_rejects_accidental_greek_fallback(client, monkeypatch):
    result = client.get("/api/search", params={"q": "the wedding of Hector and Andromache",
                                               "author": "Alpha", "mode": "words"}).json()
    assert [row["id"] for row in result["results"]] == ["synthetic-wedding-note"]
    assert "fallback_terms" not in result
    assert not any("Greek spelling candidates" in warning for warning in result["warnings"])
    class Sem:
        def search(self, *args, **kwargs):
            return [{"id": "synthetic-accidental-greek", "score": .99},
                    {"id": "synthetic-wedding-note", "score": .98}]
    monkeypatch.setattr(server, "semantic_service", lambda: Sem())
    hybrid = client.get("/api/search", params={"q": "the wedding of Hector and Andromache",
                                               "author": "Alpha", "mode": "hybrid"}).json()
    assert hybrid["results"][0]["id"] == "synthetic-wedding-note"
    assert hybrid["results"][0]["retrieval_ranks"] == {"lexical": 1, "semantic": 2}
    assert "fallback_terms" not in hybrid


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-greek", "author": "Alpha", "work": "Song", "citation": "roman-control",
     "text": "γυγέω τοῦ πολυχρύσου"},
    {"id": "synthetic-original", "author": "Alpha", "work": "Notes", "citation": "native-control",
     "language": "eng", "kind": "commentary", "text": "Gygeo: synthetic explanatory note"},
]], indirect=True)
def test_complete_source_phrase_precedes_incidental_shared_word_fallback(client, monkeypatch):
    result = client.get("/api/search", params={"q": "Gygeo tou polychrysou", "author": "Alpha",
                                               "mode": "words"}).json()
    # Complete, source-confirmed wording is stronger than the old OR fallback:
    # an English note containing only Gygeo is no longer an equal phrase hit.
    assert [row["id"] for row in result["results"]] == ["synthetic-greek"]
    assert result["transliteration_phrase"]["original_query"] == "Gygeo tou polychrysou"
    assert result["transliteration_phrase"]["matched_greek_phrases"] == ["γυγεω του πολυχρυσου"]
    assert "fallback_terms" not in result
    class Sem:
        def search(self, *args, **kwargs):
            return []
    monkeypatch.setattr(server, "semantic_service", lambda: Sem())
    hybrid = client.get("/api/search", params={"q": "Gygeo tou polychrysou", "author": "Alpha",
                                               "mode": "hybrid"}).json()
    assert all(hybrid["transliteration_phrase"][key] == value
               for key, value in result["transliteration_phrase"].items())


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-greek-direct", "author": "Alpha", "work": "Song", "citation": "direct-control",
     "text": "γυγέω τοῦ πολυχρύσου"},
]], indirect=True)
def test_existing_greek_phrase_and_single_form_do_not_use_description_fallback(client):
    for query in ("γυγέω τοῦ πολυχρύσου", "polychrysou"):
        result = client.get("/api/search", params={"q": query, "author": "Alpha", "mode": "words"}).json()
        assert [row["id"] for row in result["results"]] == ["synthetic-greek-direct"]
        assert "fallback_terms" not in result


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-phrase", "author": "Alpha", "work": "Song", "citation": "phrase",
     "text": "βάλλων χρυσοκόμης Ἔρως"},
    {"id": "synthetic-short-note", "author": "Alpha", "work": "Notes", "citation": "note",
     "language": "eng", "kind": "commentary", "text": "Eros"},
    {"id": "synthetic-two-anchors", "author": "Alpha", "work": "Song", "citation": "anchors",
     "text": "βαλλον εροσ"},
]], indirect=True)
def test_querywide_coverage_outweighs_incidental_native_single_word_and_pages_stably(client):
    params = {"q": "ballon chrysokomes Eros", "author": "Alpha", "mode": "words", "limit": 1}
    pages = [client.get("/api/search", params=params | {"offset": offset}).json() for offset in range(3)]
    assert [page["total"] for page in pages] == [3, 3, 3]
    assert [page["results"][0]["id"] for page in pages] == [
        "synthetic-phrase", "synthetic-two-anchors", "synthetic-short-note"]
    assert [page["results"][0]["query_term_coverage"] for page in pages] == [3, 2, 1]
    assert len(pages[0]["fallback_terms"]["groups"]) == 3


@pytest.mark.parametrize("client", [[
    {"id": "synthetic-curly-control", "author": "Alpha", "work": "Song", "citation": "curly-control",
     "text": "εὕδουσιν δ’ ὀρέων κορυφαί"},
]], indirect=True)
def test_curly_apostrophe_roman_phrase_uses_same_supported_fallback_as_ascii(client):
    for apostrophe in ("'", "’"):
        result = client.get("/api/search", params={"q": f"Eudousin d{apostrophe} oreon koryphai",
                                                   "author": "Alpha", "mode": "words"}).json()
        assert result["results"][0]["id"] == "synthetic-curly-control"
        assert result["transliteration_phrase"]["matched_greek_phrases"] == ["ευδουσιν δ' ορεων κορυφαι"]


def test_greek_spacing_sign_does_not_activate_morphology_for_latin_description(client, monkeypatch):
    def forbidden():
        raise AssertionError("Greek-block punctuation is not a Greek-language word")
    class Sem:
        def search(self, *args, **kwargs):
            return []
    monkeypatch.setattr(server, "morph_service", forbidden)
    monkeypatch.setattr(server, "semantic_service", lambda: Sem())
    result = client.get("/api/search", params={"q": "a long description about love ᾿", "mode": "hybrid"})
    assert result.status_code == 200
