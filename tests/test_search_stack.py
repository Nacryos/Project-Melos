"""Release S: stacked retrieval pieces (synthetic fixtures; no corpus, no models)."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend import commentary_context, search_rerank, search_stack  # noqa: E402


def corpus():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE passages(id TEXT PRIMARY KEY, language TEXT, kind TEXT, quality TEXT, normalized TEXT);
        CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized, citation, author, work,
                                                    tokenize='unicode61 remove_diacritics 0');
        CREATE TABLE vocabulary(normalized TEXT PRIMARY KEY, form TEXT, count INTEGER);
    """)
    rows = [("a", "αστερεσ μεν αμφι καλαν σελανναν"), ("b", "σεληνη φαεινη"), ("c", "οινοσ και υδωρ"),
            ("d", "σελαννα και αστερεσ")]
    for pid, text in rows:
        con.execute("INSERT INTO passages VALUES (?,?,?,?,?)", (pid, "grc", "text", "source_text", text))
        con.execute("INSERT INTO passage_fts VALUES (?,?,?,?,?)", (pid, text, "", "", ""))
    for word in {w for _, t in rows for w in t.split()}:
        con.execute("INSERT INTO vocabulary VALUES (?,?,?)", (word, word, 1))
    return con


def test_spelling_variants_follow_dialect_rules():
    vocab = {"σελαννα": 3, "σεληνη": 10, "σελανα": 1, "οινοσ": 5}
    found = search_stack.spelling_variants("σεληνα", vocab)
    assert found.get("σελανα") == 0.8  # η -> α
    assert "οινοσ" not in found


def test_keyword_hits_keep_exact_words_first_and_cap_variants(monkeypatch):
    con = corpus()
    monkeypatch.setattr(search_stack, "vocabulary", lambda c: {k: n for k, n in c.execute("SELECT normalized, count FROM vocabulary")})
    hits, variants = search_stack.keyword_hits(con, "σελάννα", limit=10)
    ids = [h["id"] for h in hits]
    assert ids[0] == "d"  # the printed word itself
    assert "σελανναν" in variants  # movable nu
    assert "c" not in ids


def test_display_rule_quotes_at_most_thirty_words():
    row = {"id": "x:1", "title": "T", "author": "A", "year": "1990", "locator": "p. 3", "page": "PDF page 3", "url": None,
           "licence": "in copyright (owner-provided PDF)", "text": " ".join(f"w{i}" for i in range(80))}
    shown = commentary_context.display_note(row)
    assert shown["display"] == "quotation"
    assert len(shown["text"].replace(" …", "").split()) == commentary_context.QUOTE_WORDS
    row["licence"] = "Public domain (published 1900)"
    assert commentary_context.display_note(row)["text"].split()[-1] == "w79"


def test_rerank_without_configuration_keeps_order(monkeypatch):
    monkeypatch.setattr(search_stack, "config", lambda: {})
    ranked = [{"id": "a"}, {"id": "b"}]
    assert search_rerank.rerank("moon", ranked, greek=False) == (ranked, None)


def test_all_of_patterns_need_every_part():
    import search_eval
    regex = search_eval.compile_query({"all_of": ["σελ", "αστ"]})
    assert regex.search("σεληνη και αστερεσ")
    assert not regex.search("σεληνη μονη")


def test_lab_rank_is_weighted_reciprocal_rank():
    import search_lab_s
    rows = [{"id": "a", "ranks": {"x": 1}}, {"id": "b", "ranks": {"y": 1}}, {"id": "c", "ranks": {"x": 2, "y": 2}}]
    assert [r["id"] for r in search_lab_s.rank(rows, {"x": 1.0, "y": 1.0})] == ["c", "a", "b"]
    assert [r["id"] for r in search_lab_s.rank(rows, {"x": 0.0, "y": 1.0}, alone=True)] == ["b", "c"]
