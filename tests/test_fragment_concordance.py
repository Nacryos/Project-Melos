"""Release Q: fragment numbers by numbering scheme (Voigt / Lobel-Page / Campbell).

General rules only; the numbers here are chosen to differ from the evaluation cases where possible."""
import json
import sqlite3

import pytest

from backend.citations import CitationIndex, parse_citation, scheme_name, query_schemes
from scripts.build_citation_index import edition_fragment_refs, text_equivalences


@pytest.mark.parametrize("query,author,scheme,locus", [
    ("Sappho Campbell 44", "Sappho", "Campbell", [(44, "")]),
    ("Alc. 129 L-P", "Alcaeus", "Lobel-Page", [(129, "")]),
    ("Alc. 42 L.P.", "Alcaeus", "Lobel-Page", [(42, "")]),
    ("Alc. Lobel & Page 332", "Alcaeus", "Lobel-Page", [(332, "")]),
    ("Sapph. fr. 94 V", "Sappho", "Voigt", [(94, "")]),
    ("Sappho fr. Voigt 96", "Sappho", "Voigt", [(96, "")]),
    ("Sapph. 2 C.", "Sappho", "Campbell", [(2, "")]),
    ("Voigt 44", None, "Voigt", [(44, "")]),
])
def test_scheme_before_or_after_the_number(query, author, scheme, locus):
    parsed = parse_citation(query)
    assert parsed["kind"] == "fragment" and parsed["author"] == author and parsed["scheme"] == scheme
    assert parsed["locus"] == locus


def test_leading_scheme_rule_does_not_touch_line_citations():
    assert parse_citation("Nonn. D. 1.1")["kind"] == "locus"
    assert parse_citation("Hes. Th. 116")["work"] == "Theogony"
    assert parse_citation("Pind. P. 8.95")["work"] == "Pythian Odes"
    assert parse_citation("V 31") is None          # single-letter sigla only after the number
    assert parse_citation("Campbell 1.2") is None  # a numbering name alone takes a fragment number
    assert scheme_name("lobel and page") == "Lobel-Page" and scheme_name("GLP") == "Campbell GLP"
    assert query_schemes("Campbell") == ("Campbell", "Campbell GLP") and query_schemes("Voigt") == ("Voigt",)


def test_printed_equivalences_in_note_text():
    got = text_equivalences("Meter: x. Text: 112B Voigt = 112C Campbell, LP Source: Hephaestion")
    assert ("Voigt", "112b", "Campbell", "112c") in [g[:4] for g in got]
    assert ("Voigt", "112b", "Lobel-Page", "112c") in [g[:4] for g in got]
    got = text_equivalences("120C Voigt = 220 Lobel and Page, and Campbell")
    assert {g[:4] for g in got} == {("Voigt", "120c", "Lobel-Page", "220"), ("Voigt", "120c", "Campbell", "220")}
    # Not exactly this shape: not read.
    assert text_equivalences("150A Voigt = 170 Campbell, and Lobel & Page 150B Adonean") == []
    assert text_equivalences("no numbers here") == []


CONCORDANCE = {"edition_numbering": [{
    "id": "ed", "scheme": "Campbell GLP", "edition": "Campbell GLP", "record_id_prefix": "campbell-glp:",
    "statement": "For Sappho and Alcaeus I have used the marginal numbers of Lobel and Page", "printed_page": "xxxii",
    "pdf_page": 30, "authors": {"Sappho": "Lobel-Page", "Alcaeus": "Lobel-Page"},
    "explicit_headings": [{"pattern": "^(\\d{1,4}[a-z]?)D\\.$", "scheme": "Diehl", "rule": "D. = Diehl"},
                          {"pattern": "^Fr\\. Adesp\\. (\\d{1,4}[a-z]?) \\(P\\.M\\.G\\.\\)$", "scheme": "PMG adespota",
                           "rule": "PMG adespota"}]}]}


def test_edition_numbering_statement_and_explicit_headings():
    rows = edition_fragment_refs("campbell-glp:alcaeus:129", "Alcaeus", {"edition_fragment": "129", "pdf_pages": [88]},
                                 CONCORDANCE)
    assert [(r[0], r[1], r[2]) for r in rows] == [("Campbell GLP", "129", "edition_heading"),
                                                  ("Lobel-Page", "129", "edition_numbering_statement")]
    assert "PDF p. 88" in rows[0][3] and "xxxii" in rows[1][3]
    # A poet the statement does not name keeps only the edition's own number.
    rows = edition_fragment_refs("campbell-glp:archilochus:5a", "Archilochus", {"edition_fragment": "5A"}, CONCORDANCE)
    assert [(r[0], r[1]) for r in rows] == [("Campbell GLP", "5a")]
    rows = edition_fragment_refs("campbell-glp:simonides:77d", "Simonides", {"edition_fragment": "77D."}, CONCORDANCE)
    assert [(r[0], r[1]) for r in rows] == [("Diehl", "77")]
    rows = edition_fragment_refs("campbell-glp:sappho:x", "Sappho", {"edition_fragment": "Fr. Adesp. 935 (P.M.G.)"},
                                 CONCORDANCE)
    assert [(r[0], r[1]) for r in rows] == [("PMG adespota", "935")]
    assert edition_fragment_refs("other:sappho:1", "Sappho", {"edition_fragment": "1"}, CONCORDANCE) == []


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "cite.sqlite"
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE work(work_key TEXT PRIMARY KEY, author TEXT, display_work TEXT, tlg_author TEXT, tlg_work TEXT,
                        tlg_source TEXT, tlg_evidence TEXT, depth INTEGER, loci INTEGER, first_passage TEXT,
                        labels TEXT, sources TEXT);
      CREATE TABLE equiv(author TEXT, scheme_a TEXT, num_a TEXT, scheme_b TEXT, num_b TEXT, passage_id TEXT, evidence TEXT);
      CREATE TABLE fragment_ref(author TEXT, scheme TEXT, number TEXT, passage_id TEXT, basis TEXT, evidence TEXT);
    """)
    manifest = {"version": "t", "concordance": {"conventions": [{
        "authors": ["Sappho"], "schemes": ["Voigt", "Lobel-Page"], "relation": "same number",
        "source": {"kind": "wikipedia", "title": "T", "revid": 1, "quote": "follows with minor variations"}}]}}
    con.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest),))
    con.executemany("INSERT INTO equiv VALUES (?,?,?,?,?,?,?)", [
        ("Sappho", "Voigt", "112b", "Lobel-Page", "112c", "note:1", "112B Voigt = 112C Campbell, LP"),
        ("Sappho", "Voigt", "112b", "Campbell", "112c", "note:1", "112B Voigt = 112C Campbell, LP"),
        ("Sappho", "Voigt", "60", "Diehl", "9", None, json.dumps({"kind": "wikipedia", "title": "S", "quote": "q"})),
    ])
    con.executemany("INSERT INTO fragment_ref VALUES (?,?,?,?,?,?)", [
        ("Sappho", "Lobel-Page", "112c", "glp:112c", "edition_numbering_statement", "stmt"),
        ("Sappho", "Campbell GLP", "112c", "glp:112c", "edition_heading", "head"),
        ("Sappho", "Lobel-Page", "60", "glp:60", "edition_numbering_statement", "stmt"),
        ("Sappho", "Lobel-Page", "112b", "other:112b", "record_citation", "απ. 112b Lobel-Page"),
        ("Alcman", "Campbell GLP", "60", "glp:alcman:60", "edition_heading", "head"),
    ])
    con.commit()
    con.close()
    return CitationIndex(path)


def test_explicit_equivalence_overrides_convention(index):
    nodes = {(n["scheme"], n["number"]): n["strength"] for n in index.concordance("Sappho", "Voigt", "112b")}
    assert nodes[("Lobel-Page", "112c")] == "printed"
    assert ("Lobel-Page", "112b") not in nodes  # the convention would say 112b; the printed equivalence says 112c


def test_convention_is_labelled_and_weaker(index):
    nodes = index.concordance("Sappho", "Voigt", "60")
    by = {(n["scheme"], n["number"]): n for n in nodes}
    assert by[("Voigt", "60")]["strength"] == "query"
    assert by[("Diehl", "9")]["strength"] == "source"
    assert by[("Lobel-Page", "60")]["strength"] == "convention"
    assert nodes[-1]["strength"] == "convention"  # weakest last


def test_campbell_query_covers_both_campbell_editions_and_authorless_lookup(index):
    nodes = {(n["scheme"], n["number"]) for n in index.concordance("Sappho", "Campbell", "112c")}
    assert {("Campbell", "112c"), ("Campbell GLP", "112c"), ("Voigt", "112b")} <= nodes
    assert index.fragment_authors("Campbell", "60") == ["Alcman"]
    assert [r["passage_id"] for r in index.fragment_refs("Sappho", "Lobel-Page", "60")] == ["glp:60"]
