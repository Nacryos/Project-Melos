"""Lewis & Short store, lookups and check L14 (backend/latin_dictionary.py, scripts/build_dictionary_la.py)."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_dictionary_la as build  # noqa: E402
from backend import latin_dictionary as ld  # noqa: E402

store = pytest.mark.skipif(not ld.available(), reason="data/lexica/lewis_short_la.sqlite not built")

BASIUM = """<entryFree key="basium" type="main" id="n1"><orth lang="la" extent="full">bāsĭum</orth>, <itype>ii</itype>,
<gen>n.</gen> <sense level="1" n="I" id="n1.0"><hi rend="ital">a kiss.</hi> </sense><sense level="1" n="I" id="n1.1"> In
gen. (rare and mostly <usg type="style">poet.</usg>; most freq. in Cat.): <cit><quote lang="la">da mi basia mille,</quote>
<bibl n="urn:cts:latinLit:phi0472.phi001.perseus-lat1:5:7"><author>Cat.</author> 5, 7</bibl></cit>;
<bibl n="urn:cts:latinLit:phi0472.phi001.perseus-lat1:5:13">5, 13</bibl>; <bibl><author>Mart.</author> 2, 21, 1</bibl>:
<bibl><author>id.</author> Spect. 3</bibl>.</sense></entryFree>"""


def test_parse_entry_senses_citations_labels():
    e = build.parse_entry(ET.fromstring(BASIUM))
    assert e["orths"] == ["bāsĭum"] and e["grammar"] == {"itype": "ii", "gen": "n."}
    assert [s["glosses"] for s in e["senses"]] == [["a kiss"], []]
    assert [(c["author"], c["work"], c["locus"], c["sense"]) for c in e["cites"]] == [
        ("Cat.", "", "5, 7", 1), ("Cat.", "", "5, 13", 1), ("Mart.", "", "2, 21, 1", 1), ("Mart.", "Spect.", "3", 1)]
    assert e["cites"][0]["quote"].startswith("da mi basia")
    assert e["labels"] == ["poet.", "rare"] and e["senses"][1]["labels"] == ["poet.", "rare"]


def test_labels():
    assert build.labels_in("(ante- and post-class.)") == ["ante-class.", "post-class."]
    assert build.labels_in("(post-Aug. and very rare)") == ["post-Aug.", "very rare"]
    assert build.labels_in("(late Lat.; class. servator)") == ["late Lat.", "class."]
    assert build.labels_in("(eccl. Lat.)") == ["eccl. Lat."] and build.labels_in("rarely so") == []
    assert not build.is_gloss("abl. sing.") and build.is_gloss("to love")


def test_author_table_from_the_list():
    table = build.build_authors("\n".join([
        "*'''Cat.''' or '''Catull.''' C. Valerius Catullus, ''poet.'' obiit B.C. 54",
        "*'''Ov.''' P. Ovidius Naso, ''poet,'' obiit A.D. 17",
        "*'''Vell.''' P. Velleius Paterculus, ''historian,'' fl. A.D. 30",
        "*'''Tert.''' Q. Septimius Florens Tertullianus, ''Chr. writer,'' ob. A.D. 220",
        "**'''Apol.,''' Apologeticus.",
        "*'''Inscr.''' Inscriptiones."]))
    assert table["Cat."][0]["year"] == -54 and table["Catull."][0]["before_ad14"] is True
    assert table["Ov."][0]["before_ad14"] is True          # died A.D. 17: wrote under Augustus
    assert table["Vell."][0]["before_ad14"] is False and table["Tert."][0]["before_ad14"] is False
    assert table["Inscr."][0]["year"] is None and "Apol." not in table
    assert table["Vulg."][0]["source"].startswith("editor")


def test_missing_store_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("MELOS_DICTIONARY_LA", str(tmp_path / "none.sqlite"))
    out = ld.check("da mi basia mille")
    assert out["id"] == "L14" and out["ok"] is True and out["blocking"] is False and out["detail"].startswith("unavailable:")
    assert ld.lookup("basium") == [] and ld.reverse("kiss") == []


def test_committed_author_table():
    import json
    data = json.loads((ROOT / "data/open/latin/lewis-short/authors.json").read_text(encoding="utf-8"))
    a = data["authors"]
    assert "wikisource" in data["source"].lower() and len(a) > 200
    for abbr, before in (("Cat.", True), ("Cic.", True), ("Verg.", True), ("Liv.", True), ("Plaut.", True), ("Plin.", False),
                         ("Sen.", False), ("Tac.", False), ("Vulg.", False), ("Aug.", False), ("Mart.", False)):
        assert all(r["before_ad14"] is before for r in a[abbr]), abbr


@store
def test_lookup_headword_and_form():
    (e,) = [x for x in ld.lookup("basia") if x["folded"] == "basium"]
    assert e["headword"] == "bāsĭum" and e["gender"] == "n." and "poet." in e["labels"]
    assert e["authors"]["Cat."] >= 3 and e["how"].startswith("form of basium")
    assert ("5, 7", "a kiss") in [(c["locus"], c["gloss"]) for c in e["catullus"]]
    assert ld.lookup("mellitus")[0]["how"] == "headword"
    assert ld.lookup("adfero") and ld.lookup("zzzz") == []        # L&S prints affero


@store
def test_reverse_prefers_primary_sense_and_catullus():
    kiss = ld.reverse("kiss", 8)
    assert kiss[0]["lemma"] == "basium" and kiss[0]["catullus"] >= 1 and kiss[0]["match"] == "primary sense"
    assert {"basio", "osculor"} <= {r["lemma"] for r in ld.reverse("kiss", 20)}
    assert ld.reverse("girl", 5)[0]["lemma"] == "puella" and ld.reverse("sparrow", 5)[0]["lemma"] == "passer"
    assert ld.reverse("") == [] and ld.reverse("xqzv") == []


@store
def test_l14_warns_on_late_words_only():
    out = ld.check("da mi basia mille deinde centum\npasser deliciae meae puellae")
    assert out["id"] == "L14" and out["name"] == "period and register" and out["ok"] is True and out["blocking"] is False
    row = {r["word"]: r for r in out["evidence"]}
    assert row["basia"]["status"] == "note" and "5, 7" in row["basia"]["cited"] and "poet." in row["basia"]["labels"]
    late = ld.check("salvator incarnatus trinitas resurrectio sanctificare beatificans")
    assert late["ok"] is False and late["blocking"] is False
    assert [r["status"] for r in late["evidence"]] == ["warn"] * 6
    assert "no author before A.D. 14" in late["detail"]
    odd = ld.check("Xyzzyx Marce")
    assert [r["status"] for r in odd["evidence"]] == ["no entry", "note"] and "no entry: Xyzzyx" in odd["detail"]
    assert ld.check("")["ok"] is True


def test_authors_on_each_side_of_ad14():
    """Pins the era and date parse of the committed table: the list as transcribed prints Priscian 'fl. B.C. 500'."""
    table = json.loads((ROOT / "data/open/latin/lewis-short/authors.json").read_text(encoding="utf-8"))["authors"]
    rows = lambda abbr: table[abbr] if isinstance(table[abbr], list) else [table[abbr]]  # noqa: E731
    for abbr in ("Plaut.", "Cic.", "Cat.", "Verg.", "Hor.", "Lucr.", "Liv.", "Ov."):
        assert all(r["before_ad14"] and r["year"] < 34 for r in rows(abbr)), abbr
    for abbr in ("Sen.", "Tac.", "App.", "Prisc.", "Aug.", "Pompon.", "Lampr.", "Vulg."):
        assert not any(r["before_ad14"] for r in rows(abbr)) and all(r["year"] > 14 for r in rows(abbr)), abbr
    assert rows("Prisc.")[0]["year"] == 500 and rows("Plaut.")[0]["year"] == -184
    # L&S's "August." is Augustine in practice (Conf., C. D., Serm.), whatever the list says: it must not vouch as early
    assert build.resolve_author("August.", table, {}) == "Aug." and build.resolve_author("Pomp.", table, {}) == "Pompon."


def test_english_stems_and_g2():
    assert ld.english_stems("To whom do I give the charming new little books") == ["giv", "charm", "new", "littl", "book"]
    assert ld.english_stem("kisses") == ld.english_stem("kissed") == ld.english_stem("kissing") == "kiss"
    assert build.g2(5, 5, 5, 2308) > build.g2(2, 17, 12, 2308) > build.g2(39, 300, 300, 2308)


@store
def test_reverse_names_its_sources():
    kiss = ld.reverse("kiss", 5)
    assert kiss[0]["sources"] == ["lewis-short", "catullus-interlinear"] and "5.7" in kiss[0]["interlinear"]["loci"]
    assert "kiss" in kiss[0]["interlinear"]["english"].lower() and kiss[0]["interlinear"]["latin"]
    napkin = ld.reverse("napkin", 5)[0]          # L&S glosses linteum "a linen cloth"; Catullus 12 supplies it
    assert napkin["lemma"] == "linteum" and napkin["sources"] == ["catullus-interlinear"] and napkin["interlinear"]["locus"] == "12.3"
    assert ld.reverse("tasteless", 3)[0]["lemma"] == "insulsus" and ld.reverse("charming", 3)[0]["lemma"] == "uenustus"
    assert [r["lemma"] for r in ld.reverse("sparrow", 5) if "catullus-interlinear" in r["sources"]] == ["passer"]
    assert ld.reverse("strigil", 3)[0]["sources"] == ["lewis-short"] and ld.reverse("strigil", 3)[0]["interlinear"] is None
