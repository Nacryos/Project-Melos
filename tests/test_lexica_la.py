"""The further Latin dictionaries: the reader (backend/latin_lexica.py), the ingest helpers
(scripts/ingest_lexica_la.py), the route and the wiring into reverse() and L14. Tests on the real stores skip when
the store is not built (data/lexica/ is local)."""
from __future__ import annotations

import gzip
import io
import sqlite3
import struct
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ingest_lexica_la as ingest  # noqa: E402
from backend import latin_dictionary as ld  # noqa: E402
from backend import latin_lexica as lx  # noqa: E402


def built(*names: str):
    have = {m["name"] for m in lx.available()}
    return pytest.mark.skipif(not set(names) <= have, reason=f"data/lexica/lex_{'/'.join(names)}.sqlite not built")


def make(path: Path, meta: dict, entries: list[tuple[str, str, str]], pages: list[tuple[str, int, str]] | None = None) -> None:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, headword TEXT, folded TEXT, text TEXT);"
                     "CREATE INDEX entries_folded ON entries(folded); CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
    db.executemany("INSERT INTO entries (headword, folded, text) VALUES (?,?,?)", entries)
    db.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    if pages is not None:
        db.execute("CREATE TABLE pages (volume TEXT, col INTEGER, text TEXT)")
        db.executemany("INSERT INTO pages VALUES (?,?,?)", pages)
    db.commit()
    db.close()


@pytest.fixture()
def toy(tmp_path, monkeypatch):
    make(tmp_path / "lex_toy.sqlite", {"name": "toy", "title": "Toy Latin-German", "language": "de", "direction": "la-de",
                                        "licence": "public domain"},
         [("bāsĭum", "basium", "bāsĭum, ī, n., ein zärtlicher Kuß, Catull."), ("vĕnustus", "uenustus", "venustus, a, um, anmutig, reizend")])
    make(tmp_path / "lex_toyen.sqlite", {"name": "toyen", "title": "Toy English-Latin", "language": "en", "direction": "en-la"},
         [("darling", "darling", "darling: 1. dēlĭciae, ārum: my d., deliciae meae, Cat. 2. mellītus: Cic."),
          ("kiss (subs.)", "kiss", "kiss (subs.): 1. oscŭlum: Cic. 2. bāsĭum: Cat.")])
    make(tmp_path / "lex_thes.sqlite", {"name": "thes", "title": "Pages only", "language": "la", "direction": "la-la"}, [],
         [("II", 1771, "basium, -i n. origo incerta. osculum amatorium"), ("II", 1772, "aliud")])
    (tmp_path / "lex_broken.sqlite").write_bytes(b"this is not a database")
    monkeypatch.setenv("MELOS_LEXICA_DIR", str(tmp_path))
    return tmp_path


def test_reader_on_stores_written_to_the_contract(toy):
    stores = {m["name"]: m for m in lx.available()}
    assert set(stores) == {"toy", "toyen", "thes"} and stores["thes"]["entries"] == 0 and stores["thes"]["pages"] == 2
    assert stores["toy"]["direction"] == "la-de" and stores["toy"]["licence"] == "public domain"
    hit = lx.lookup("basium")
    assert list(hit) == ["toy"] and hit["toy"][0]["headword"] == "bāsĭum" and "Kuß" in hit["toy"][0]["text"]
    assert lx.lookup("Venustus")["toy"][0]["folded"] == "uenustus"          # v -> u, case folded
    assert lx.lookup("basium", "toyen") == {} and lx.lookup("") == {} and lx.lookup("basium", "nosuch") == {}
    assert lx.gloss("basium", dicts=("toy",)) == {"toy": "bāsĭum, ī, n., ein zärtlicher Kuß, Catull."}


def test_english_picks_the_latin_by_its_quantities(toy):
    rows = lx.english("darling")
    assert rows[0]["dict"] == "toyen" and [w["word"] for w in rows[0]["latin"]] == ["dēlĭciae", "mellītus"]
    assert [w["folded"] for w in lx.english("kisses")[0]["latin"]] == ["osculum", "basium"]     # unpluralised
    assert lx.english("xyzzy") == [] and lx.english("") == []
    words = lx.latin_words("charming: 1. ămoenus: Cic. 2. vĕnustus (of persons): Cat.")
    assert [w["folded"] for w in words] == ["amoenus", "uenustus"] and "Cat." in words[1]["context"]


def test_search_and_pages_and_one_call(toy):
    assert lx.search("zärtlicher")["toy"][0]["headword"] == "bāsĭum" and "thes" not in lx.search("basium")
    pages = lx.pages("amatorium")
    assert list(pages) == ["thes"] and pages["thes"][0]["volume"] == "II" and pages["thes"][0]["col"] == 1771
    q = lx.query("basium", en="darling", search_text="osculum")
    assert {"dictionaries", "word", "lookup", "english", "search", "pages"} <= set(q) and "error" not in q
    assert [d["name"] for d in q["dictionaries"]] == ["thes", "toy", "toyen"]
    assert "pages" in lx.query("amatorium") and lx.query("amatorium")["lookup"] == {}       # no entry: the pages answer


def test_nothing_raises_without_the_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_LEXICA_DIR", str(tmp_path / "absent"))
    assert lx.available() == [] and lx.lookup("basium") == {} and lx.english("kiss") == []
    assert lx.search("kiss") == {} and lx.pages("kiss") == {} and lx.gloss("basium") == {}
    assert lx.query("basium", en="kiss", search_text="kiss")["dictionaries"] == []
    if ld.available():                                      # reverse() and L14 stand without the further dictionaries
        assert all("smith-hall" not in r["sources"] for r in ld.reverse("kiss", 5))
        assert "gloss" not in str(ld.check("strigilis mea")["evidence"])


def test_ingest_helpers(tmp_path):
    assert ingest.plain('<orth>osculum</orth> <sense marker="2.">b&amp;c</sense><br>d') == "osculum\n2. b&c\nd"
    assert ingest.gaffiot_text(r"\entree{bāsĭum}, \des{ĭī}, n., baiser : \aut{Catul.} 5, 7") == "bāsĭum, ĭī, n., baiser : Catul. 5, 7"
    assert ingest.fold_head("1 vĕnustus", "la-fr") == "uenustus" and ingest.fold_head("Darling (subs.)", "en-la") == "darling"
    assert ingest.licence_of("x", ["Title\nThis work is in the public domain.\n"]).startswith("This work is in the public domain")
    assert ingest.licence_of("x", ["nothing here"]) == "no licence statement in the keeper's repository"
    assert ingest.USER_AGENT == "Melos/1.0 (+https://greeklyric.com)" and ingest.PAUSE >= 1
    arts = [("kiss", "<k>kiss</k> oscŭlum"), ("sweet", "dulcis")]
    body, idx, off = b"", b"", 0
    for w, a in arts:
        raw = a.encode()
        idx += w.encode() + b"\0" + struct.pack(">II", off, len(raw))
        body, off = body + raw, off + len(raw)
    dz = io.BytesIO()
    with gzip.GzipFile(fileobj=dz, mode="wb") as g:
        g.write(body)
    archive = tmp_path / "toy.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("toy/toy.ifo", "StarDict's dict ifo file\nversion=2.4.2\nwordcount=2\nsametypesequence=h\n")
        z.writestr("toy/toy.idx", idx)
        z.writestr("toy/toy.dict.dz", dz.getvalue())
        z.writestr("toy/toy.syn", b"osculation\0" + struct.pack(">I", 0))
    ifo, words = ingest.read_stardict(archive)
    assert ifo["sametypesequence"] == "h" and words == [("kiss", "<k>kiss</k> oscŭlum", ["osculation"]), ("sweet", "dulcis", [])]


def test_stores_keep_the_contract():
    for m in lx.available():
        if m["name"] not in ingest.SOURCES:                 # the sibling builders answer for their own stores
            continue
        assert m["direction"] in {"la-de", "la-fr", "la-en", "la-la", "en-la", "de-la"}, m["name"]
        assert m.get("licence") and m.get("source_url") and m.get("title"), m["name"]
        assert m["entries"] or m["pages"], m["name"]
    for name in ingest.SOURCES:
        manifest = ROOT / "data" / "open" / "latin" / "lexica" / f"{name}.json"
        assert not manifest.exists() or manifest.stat().st_size < 20_000          # manifests stay small


@built("georges", "gaffiot")
def test_georges_and_gaffiot_on_catullus_words():
    hit = lx.lookup("venustus", ["georges", "gaffiot"])
    assert "anmutig" in hit["georges"][0]["text"] and "charme" in hit["gaffiot"][0]["text"]
    assert lx.lookup("basia", "gaffiot")["gaffiot"][0]["folded"] == "basium"       # the inflected form finds its lemma
    assert "Catul" in lx.lookup("basium", "gaffiot", full=True)["gaffiot"][0]["text"]
    assert set(lx.gloss("lepidus")) == {"georges", "gaffiot"} and len(lx.gloss("lepidus")["georges"]) <= 165
    assert "Kuß" in lx.search("zärtlicher Kuß", "georges")["georges"][0]["excerpt"] or lx.search("zärtlicher Kuß", "georges")


@built("smith_hall")
def test_smith_hall_answers_english_and_joins_reverse():
    assert {"deliciae", "mellitus"} <= {w["folded"] for w in lx.english("darling", dicts="smith_hall")[0]["latin"]}
    assert "amores" in [w["folded"] for e in lx.english("sweetheart", dicts="smith_hall") for w in e["latin"]]
    rows = ld.reverse("charming", 6)
    top = rows[0]
    assert top["lemma"] == "uenustus" and top["sources"] == ["lewis-short", "catullus-interlinear", "smith-hall"]
    assert top["smith_hall"]["under"].startswith("charming") and "nustus" in top["smith_hall"]["word"]
    assert any(r["sources"] == ["smith-hall"] for r in ld.reverse("darling", 12))      # suavis: L&S glosses it otherwise


@built("doederlein")
def test_doederlein_groups_answer_for_each_member():
    assert "ardent kiss" in lx.lookup("basium", "doederlein", full=True)["doederlein"][0]["text"]


@pytest.mark.skipif(not ld.available(), reason="data/lexica/lewis_short_la.sqlite not built")
def test_l14_gloss_is_evidence_and_leaves_the_verdict(monkeypatch):
    text = "strigilis mea deosculor"
    with_gloss = ld.check(text)
    monkeypatch.setattr(ld, "_second_opinion", lambda rows: None)
    bare = ld.check(text)
    assert with_gloss["ok"] == bare["ok"] and with_gloss["detail"] == bare["detail"]
    strip = lambda rows: [{k: v for k, v in r.items() if k != "gloss"} for r in rows]  # noqa: E731
    assert strip(with_gloss["evidence"]) == bare["evidence"]
    assert all(r["status"] in ("warn", "no entry") for r in with_gloss["evidence"] if "gloss" in r)


def test_route_needs_the_owner_or_the_agent_and_answers(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from backend import latin_routes
    for name in ("MELOS_OWNER_TOKEN", "MELOS_AGENT_TOKEN", "MELOS_DEV_AUTH", "MELOS_AUTH_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    app = fastapi.FastAPI()
    app.include_router(latin_routes.router)
    assert TestClient(app).get("/api/la/lexica", params={"q": "venustus"}).status_code in (401, 403, 404)
    app.dependency_overrides[latin_routes.require_owner_or_agent] = lambda: "owner"
    r = TestClient(app).get("/api/la/lexica", params={"q": "venustus", "en": "charming", "search": "venustus", "dict": "", "limit": 2})
    assert r.status_code == 200 and {"dictionaries", "word", "lookup", "english", "search"} <= set(r.json())
    assert set(TestClient(app).get("/api/la/lexica").json()) == {"dictionaries"}
    if {"georges"} <= {m["name"] for m in lx.available()}:
        assert "georges" in r.json()["lookup"] and len(r.json()["lookup"]["georges"]) <= 2
