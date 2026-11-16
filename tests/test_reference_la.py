"""The Latin reference stores (backend/latin_reference.py over data/reference_la.sqlite, scripts/build_reference_la.py):
Merrill's commentary and introduction, Allen and Greenough's grammar. The committed jsonl files are checked always;
the lookups need the built database and are skipped without it; the lemma hop needs the lemma index as well."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend import latin_lemma, latin_reference as ref

ROOT = Path(__file__).resolve().parents[1]
OPEN = ROOT / "data" / "open" / "latin"
needs_db = pytest.mark.skipif(not ref.available(), reason="data/reference_la.sqlite not built")
needs_lemmas = pytest.mark.skipif(not ref.available() or not latin_lemma.available(), reason="reference database or lemma index not built")


def rows(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_merrill_notes_file_has_every_field_and_the_counts_of_its_manifest():
    notes = rows(OPEN / "merrill-commentary" / "notes.jsonl")
    man = json.loads((OPEN / "merrill-commentary" / "manifest.json").read_text(encoding="utf-8"))
    assert len([r for r in notes if r["kind"] == "note"]) == man["counts"]["notes"] == 2530
    assert len({r["id"] for r in notes}) == len(notes)
    for r in notes:
        assert r["poem"] and r["text"] and r["source_url"].startswith("https://www.perseus.tufts.edu/")
        if r["kind"] == "note":
            assert r["line"] and r["line_start"] <= r["line_end"]
    assert "non-commercial purposes only" in man["licence"]["quote"] and "credit Perseus" in man["licence"]["quote"]
    assert man["counts"]["poems_without_line_notes"] == ["18-20"]
    basia = next(r for r in notes if r["poem"] == "5" and r["lemma"] == "basia")
    assert basia["line"] == "7" and "the word appears first here" in basia["text"] and "savia" in basia["latin"]
    assert (next(r for r in notes if r["line"] == "92-6")["line_start"], next(r for r in notes if r["line"] == "92-6")["line_end"]) == (92, 96)


def test_merrill_introduction_has_86_sections_with_metres_and_prosody():
    intro = rows(OPEN / "merrill-commentary" / "intro.jsonl")
    assert [r["section"] for r in intro] == [str(n) for n in range(1, 87)]
    assert {r["heading"] for r in intro if 76 <= int(r["section"]) <= 85} == {"Metres."}
    assert intro[-1]["heading"] == "Prosody." and "ELISION" in intro[-1]["text"] and "HIATUS" in intro[-1]["text"].upper()
    assert next(r for r in intro if r["section"] == "81")["text"].startswith("PHALAECEAN, often called Hendecasyllabic")


def test_allen_and_greenough_has_all_642_sections_and_the_prosody_ones_whole():
    secs = rows(OPEN / "allen-greenough" / "sections.jsonl")
    nums = [int(r["section"]) for r in secs if r["sub"] == ""]
    assert nums == list(range(1, 643)) and len({r["id"] for r in secs}) == len(secs) and all(r["text"] for r in secs)
    by = {r["id"]: r for r in secs}
    assert by["ag:603f"]["heading_path"] == ["PROSODY", "QUANTITY", "GENERAL RULES", "Quantity of Syllables"]
    assert "long by position" in by["ag:603f"]["text"] and "either long or short (common)" in by["ag:603f"]["text"]
    assert "This is called Elision" in by["ag:612e"]["text"] and "Hiatus" in by["ag:612g"]["text"]
    assert "Phalæcean" in "".join(r["text"] for r in secs if r["section"] == "625")
    syntax = [r for r in secs if r["heading_path"][:1] == ["PART SECOND — SYNTAX"] and r["sub"] == ""]
    assert (int(syntax[0]["section"]), int(syntax[-1]["section"]), len(syntax)) == (268, 601, 334)
    assert "Ablative Absolute" in by["ag:419"]["text"]


@needs_db
def test_commentary_by_poem_and_line():
    all5 = ref.commentary("5")
    assert all5[0]["kind"] == "headnote" and all5[0]["text"].startswith("To Lesbia")
    on7 = ref.commentary("5", 7)
    assert [r["lemma"] for r in on7] == ["basia", "deinde"] and all(r["line"] == "7" for r in on7)
    assert any(r["line"] == "1-3" for r in ref.commentary(1, 2))          # a range note covers the line inside it
    assert {r["poem"] for r in ref.commentary("68")} == {"68a", "68b"}
    assert ref.commentary("5", 99) == [] and ref.commentary("999") == [] and ref.commentary("") == []


@needs_db
def test_searches_fold_v_and_u_and_return_excerpts():
    hits = ref.commentary_search("uenuste")
    assert hits and any(r["lemma"] == "venuste" for r in hits) and all(r["excerpt"] for r in hits)
    assert any(r["section"] == "86" for r in ref.intro_search("hiatus"))
    g = ref.grammar_search("elision", limit=20)
    assert any(r["id"] == "ag:612e" for r in g) and isinstance(g[0]["heading_path"], list)
    assert ref.grammar_search("long by position")[0]["match"] == "phrase"
    assert ref.grammar_search("") == [] and ref.commentary_search('"((') == [] and ref.intro_search("zzzzqq") == []


@needs_db
def test_grammar_by_section_and_subsection():
    g = ref.grammar("603")
    assert g["section"] == "603" and [s["sub"] for s in g["subsections"]] == list("abcdef")
    assert g["text"].startswith("The following are General Rules of Quantity") and "f. Position." in g["full_text"]
    assert ref.grammar("603f")["id"] == ref.grammar("§ 603. f")["id"] == "ag:603f"
    assert ref.grammar("9999") is None and ref.grammar("603z") is None and ref.grammar("") is None and ref.grammar("abc") is None


@needs_db
def test_intro_by_number_and_by_heading():
    assert len(ref.intro()) == 86
    assert [r["section"] for r in ref.intro("86")] == ["86"] and ref.intro("86")[0]["heading"] == "Prosody."
    assert [r["section"] for r in ref.intro("Metres")] == [str(n) for n in range(76, 86)]
    assert ref.intro("no such heading") == []


@needs_db
def test_notes_for_words_puts_lemma_phrase_matches_first():
    out = ref.notes_for_words(["basia", "Venuste", ""], limit=3)
    assert [w["word"] for w in out] == ["basia", "Venuste", ""] and out[2]["notes"] == []
    assert out[0]["notes"][0]["matched_in"] == "lemma" and out[0]["notes"][0]["poem"] == "5"
    assert out[1]["notes"][0]["lemma"] == "venuste" and len(out[1]["notes"]) <= 3


@needs_lemmas
def test_an_inflected_form_finds_the_note_on_its_headword():
    bella = ref.notes_for_words(["bella"], limit=10)[0]
    assert "bellus" in bella["keys"]
    assert any(r["lemma"] == "bellus" and r["poem"] == "22" for r in bella["notes"])
    back = ref.notes_for_words(["basiatio"])[0]["notes"]                  # headword -> the note on the inflected lemma phrase
    assert any(r["lemma"] == "basiationes" for r in back)


def test_a_missing_database_gives_empty_results_and_a_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_REFERENCE_LA", str(tmp_path / "absent.sqlite"))
    assert ref.commentary("5") == [] and ref.commentary_search("basia") == [] and ref.intro() == [] and ref.intro_search("x") == []
    assert ref.grammar("603") is None and ref.grammar_search("elision") == []
    assert ref.notes_for_words(["basia"])[0]["notes"] == []
    st = ref.status()
    assert st["available"] is False and "build_reference_la.py" in st["reason"]


def test_a_corrupt_database_does_not_raise(tmp_path, monkeypatch):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database")
    monkeypatch.setenv("MELOS_REFERENCE_LA", str(bad))
    assert ref.commentary("5") == [] and ref.grammar("603") is None and ref.grammar_search("elision") == []
    assert ref.status()["available"] is False and "unreadable" in ref.status()["reason"]


def test_subject_map_comes_from_the_books_index_and_headings_and_says_what_is_confirmed():
    subj = rows(OPEN / "allen-greenough" / "subjects.jsonl")
    ids = {r["id"] for r in rows(OPEN / "allen-greenough" / "sections.jsonl")}
    assert {r["source"] for r in subj} == {"heading", "index-ocr"} and all(r["row"] in ids for r in subj)
    man = json.loads((OPEN / "allen-greenough" / "manifest.json").read_text(encoding="utf-8"))
    counts = man["index"]["counts"]
    assert counts["references"] == sum(r["source"] == "index-ocr" for r in subj) > 4000
    assert counts["references_confirmed"] == sum(r["confirmed"] for r in subj if r["source"] == "index-ocr") < counts["references"]
    assert "not in the Perseus TEI" in man["index"]["what"] and man["index"]["rights_fields"]["possible-copyright-status"] == "NOT_IN_COPYRIGHT"
    landed = {(r["subject"], r["row"]) for r in subj if r["confirmed"]}
    assert {("Elision", "ag:612e"), ("Hiatus", "ag:612g"), ("Common syllables", "ag:603f"), ("Synizesis", "ag:603c")} <= landed


def test_manifests_quote_the_licence_statements_and_say_the_books_are_public_domain():
    merrill = json.loads((OPEN / "merrill-commentary" / "manifest.json").read_text(encoding="utf-8"))["licence"]
    ag = json.loads((OPEN / "allen-greenough" / "manifest.json").read_text(encoding="utf-8"))["licence"]
    assert "You use it for non-commercial purposes only" in merrill["quote"]
    assert merrill["perseus_page_quote"] == "This work is licensed under a Creative Commons Attribution-ShareAlike 3.0 United States License."
    assert "Creative Commons Attribution-Noncommercial-Share Alike 3.0 United States License" in ag["alpheios_readme_quote"]
    assert "(1893) is in the public domain" in merrill["plain"] and "(1903) is in the public domain" in ag["plain"]


@needs_db
def test_grammar_search_asks_the_books_own_index_before_the_text():
    def top(q):
        return [r["id"] for r in ref.grammar_search(q)]
    first = ref.grammar_search("common syllables")
    assert [r["id"] for r in first[:2]] == ["ag:11c", "ag:603f"]
    assert first[0]["match"] == "index" and first[0]["subject"] == "Common syllables" and first[1]["index_ref"] == "603. f"
    assert top("elision")[0] == "ag:612e" and top("hiatus")[0] == "ag:612g" and top("synizesis") == ["ag:603c", "ag:642"]
    assert {"ag:11b", "ag:603", "ag:603f"} <= set(top("position")[:5])
    assert top("diminutives")[:2] == ["ag:243", "ag:263"]
    assert top("cum clauses")[0] == "ag:544" and "ag:549b" in top("cum clauses")
    assert {"ag:481", "ag:483", "ag:484", "ag:485"} <= set(top("sequence of tenses"))
    assert top("Phalaecean") == ["ag:625"]
    assert ref.grammar_search("long by position")[0]["match"] == "phrase"       # a weaker subject match does not push the phrase down
    assert all("step" not in r for r in first)


@needs_db
def test_grammar_search_does_not_invent_what_the_book_does_not_say():
    # Allen and Greenough never write "hendecasyllable": their name for the verse is Phalaecean (625. 11).
    assert ref.grammar_search("hendecasyllable") == []
    # They never call l and r liquids where they give the rule (603 f, "a mute followed by l or r"), and the index puts
    # it under "Common syllables" and "Position in Prosody": "mute and liquid" lands on the index entry Mutes (section 4).
    assert ref.grammar_search("mute and liquid")[0]["id"] == "ag:4"


@needs_db
def test_intro_search_reaches_metres_and_prosody():
    def secs(q):
        return [r["section"] for r in ref.intro_search(q)]
    hendeca = ref.intro_search("hendecasyllable")       # Merrill writes "hendecasyllabic" and "Phalaecean"
    assert hendeca[0]["section"] == "81" and hendeca[0]["match"] == "stem"
    assert secs("Phalaecean") == ["81"] and secs("elision") == ["82", "86"] and set(secs("hiatus")) == {"76", "82", "86"}
    assert secs("diminutives") == ["46"]                # he treats diminutives under the Poems, not in 76-86


@needs_db
def test_status_and_command_line():
    st = ref.status()
    assert st["available"] and st["counts"]["merrill_notes"] == 2648 and st["counts"]["ag_sections"] == 642
    assert "non-commercial" in st["licences"]["merrill-commentary"]["quote"]
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "la_ref.py"), "grammar", "603f"], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "A&G § 603f" in run.stdout and "long by position" in run.stdout
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "la_ref.py"), "commentary", "5", "7"], capture_output=True, text=True, timeout=60)
    assert "Merrill on 5.7  [basia]" in run.stdout


def test_ellis_rows_are_labelled_as_unaudited_ocr_and_stay_out_of_the_lookups():
    path = OPEN / "ellis-commentary" / "notes.jsonl"
    if not path.exists():
        pytest.skip("Ellis OCR not ingested")
    notes = rows(path)
    man = json.loads((OPEN / "ellis-commentary" / "manifest.json").read_text(encoding="utf-8"))
    assert len(notes) == man["counts"]["notes"] > 1500 and "UNAUDITED" in man["name"]
    assert all("unaudited" in r["quality"] and r["poem_check"] in ("text-match", "segment-match", "unverified") for r in notes)
    assert man["licence"]["possible-copyright-status"] == "NOT_IN_COPYRIGHT"
    assert any(r["poem"] == "5" and r["line_start"] == 10 and r["text"].startswith("milia multa") for r in notes)
    poems = [int(r["poem"]) for r in notes]
    assert poems == sorted(poems)                                         # poems never run backwards
    assert all(r["source_url"].startswith("https://www.perseus.tufts.edu/") for r in ref.commentary("5"))
