"""Build the release S search evaluation set (120 queries) with its cited evidence and relevant counts.

  python scripts/build_search_eval_s.py --corpus data/corpus.sqlite --lemma-index data/lemma_index.sqlite

Inputs: data/evaluation/search-eval-o.json (release O's 42 queries, kept first and unchanged, so their
development / held-out split is the same) and data/evaluation/search-eval-s-draft.json (78 queries written
before any release S retriever was run). Every third query of the combined list is held out.

The judgement rule is release O's: a passage is relevant when it is Greek edited text whose normalised text
matches the query's pattern (imagery and motif queries: every pattern in ``all_of``). The evidence added
here is what the judgement rests on, read from the data rather than written by hand:

- ``headword_evidence``: each named headword's dictionary head meaning and the dictionary it comes from
  (the lemma index's ``gloss`` / ``gloss_source``: Middle Liddell, LSJ, Cunliffe, ...);
- ``corpus_loci``: up to four relevant passages (author, citation, record id, the matching words), lyric
  and elegiac authors first; for allusion queries, whether a relevant passage is by the poet the query
  alludes to (``locus_author_found``);
- the number of relevant passages in the corpus (ideal DCG and recall@50), written to the counts file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.textutils import normalize  # noqa: E402
from search_eval import compile_query  # noqa: E402

EVAL = ROOT / "data/evaluation"
# Headwords behind release O's queries (its file names the pattern only).
O_HEADWORDS = {
    "moon": ["σελήνη", "μήνη"], "stars": ["ἀστήρ", "ἄστρον"], "wine": ["οἶνος"], "honey": ["μέλι"],
    "rose": ["ῥόδον"], "sleep": ["ὕπνος"], "death": ["θάνατος"], "old age": ["γῆρας"], "nightingale": ["ἀηδών"],
    "swallow": ["χελιδών"], "horse": ["ἵππος"], "gold": ["χρυσός"], "lyre": ["λύρα", "φόρμιγξ", "βάρβιτος", "χέλυς"],
    "tears": ["δάκρυ"], "springtime": ["ἔαρ"], "snow": ["χιών", "νιφάς"], "eagle": ["αἰετός"],
    "wedding": ["γάμος", "ὑμέναιος"], "dawn": ["ἠώς"], "dream": ["ὄνειρος", "ὄναρ"], "sword": ["ξίφος", "φάσγανον"],
    "fate": ["μοῖρα", "πότμος"], "desire": ["πόθος", "ἵμερος", "ἔρως", "ἐπιθυμία"], "shield": ["ἀσπίς", "σάκος"],
    "ἔρως": ["ἔρως"], "σελήνη": ["σελήνη"], "θάνατος": ["θάνατος"], "Μοῦσα": ["Μοῦσα"], "ἀηδών": ["ἀηδών"],
    "οἶνος": ["οἶνος"], "χρυσός": ["χρυσός"], "rose-fingered": ["ῥοδοδάκτυλος"], "bittersweet": ["γλυκύπικρος"],
    "golden-throned": ["χρυσόθρονος"], "violet-crowned": ["ἰοστέφανος", "ἰόπλοκος"], "ox-eyed": ["βοῶπις"],
    "wine-dark sea": ["οἶνοψ"], "grey-eyed Athena": ["γλαυκῶπις"], "ῥοδοδάκτυλος Ἠώς": ["ῥοδοδάκτυλος", "ἠώς"],
    "πόδας ὠκὺς Ἀχιλλεύς": ["ποδάρκης"], "ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα": ["ποικιλόθρονος"],
    "γλυκύπικρον ἀμάχανον ὄρπετον": ["γλυκύπικρος"],
}
O_LOCI = {"ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα": ["Sappho 1 L-P"], "γλυκύπικρον ἀμάχανον ὄρπετον": ["Sappho 130 L-P"],
          "πόδας ὠκὺς Ἀχιλλεύς": ["Hom. Il. 1.58"], "ῥοδοδάκτυλος Ἠώς": ["Hom. Od. 2.1"]}
LYRIC_FIRST = ("sappho", "alcaeus", "anacreon", "alcman", "stesichorus", "ibycus", "pindar", "bacchylides",
               "simonides", "archilochus", "mimnermus", "theognis", "tyrtaeus", "solon", "semonides", "hipponax",
               "corinna", "xenophanes", "callinus", "anacreontea")


def headword_evidence(con, words):
    out = []
    for word in words:
        rows = con.execute("SELECT lemma, gloss, gloss_source, tokens FROM lemma WHERE lemma=? ORDER BY tokens DESC",
                           (word,)).fetchall()
        if not rows:
            rows = con.execute("SELECT lemma, gloss, gloss_source, tokens FROM lemma WHERE key=? ORDER BY tokens DESC",
                               (normalize(word),)).fetchall()
        if rows:
            lemma, gloss, source, tokens = rows[0]
            out.append({"headword": lemma, "head_meaning": gloss, "dictionary": source, "corpus_tokens": tokens})
        else:
            out.append({"headword": word, "head_meaning": None, "dictionary": None,
                        "note": "not a headword of the corpus index; the pattern carries the spelling"})
    return out


def first_match(regex, text):
    pats = getattr(regex, "patterns", None) or [regex]
    found = []
    for p in pats:
        m = p.search(text)
        if m:
            found.append(text[max(0, m.start() - 20): m.end() + 20].strip())
    return " … ".join(found)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--lemma-index", required=True)
    ap.add_argument("--out", default=str(EVAL / "search-eval-s.json"))
    ap.add_argument("--counts", default=str(EVAL / "search-eval-s-counts.json"))
    args = ap.parse_args()
    o = json.loads((EVAL / "search-eval-o.json").read_text(encoding="utf-8"))
    draft_path = EVAL / "search-eval-s-draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    queries = []
    for q in o["queries"]:
        queries.append({**q, "origin": "release O", "headwords": O_HEADWORDS.get(q["q"], []),
                        **({"loci": O_LOCI[q["q"]]} if q["q"] in O_LOCI else {}),
                        "reasoning": "Release O judgement: the pattern is the concept's Greek vocabulary."})
    queries += [{**q, "origin": "release S"} for q in draft["queries"]]
    lemma = sqlite3.connect(f"file:{args.lemma_index}?mode=ro", uri=True)
    corpus = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    texts = [(i, a or "", c or "", normalize(t or "")) for i, a, c, t in corpus.execute(
        "SELECT id, author, citation, text FROM passages WHERE language='grc' AND kind='text' "
        "AND quality IN ('source_text','machine_corrected_ocr')")]
    counts = {}
    for index, q in enumerate(queries):
        q["split"] = "held_out" if index % 3 == 2 else "development"
        regex = compile_query(q)
        hits = [(i, a, c, t) for i, a, c, t in texts if regex.search(t)]
        counts[q["q"]] = len(hits)
        hits.sort(key=lambda h: (not any(k in h[1].casefold() for k in LYRIC_FIRST), h[0]))
        q["relevant_in_corpus"] = len(hits)
        q["corpus_loci"] = [{"author": a, "citation": c, "id": i, "match": first_match(regex, t)[:160]}
                            for i, a, c, t in hits[:4]]
        if q.get("loci"):
            poets = {re.split(r"[ .]", locus)[0].casefold() for locus in q["loci"]}
            poets = {"homer" if p == "hom" else "pindar" if p == "pind" else p for p in poets}
            q["locus_author_found"] = any(any(p in a.casefold() for p in poets) for _, a, _, _ in hits)
        q["headword_evidence"] = headword_evidence(lemma, q.get("headwords", []))
    out = {"version": "search-eval-s-v1", "created": "2026-10-09",
           "purpose": ("Release S search evaluation: release O's 42 queries (first, unchanged) and 78 more: English "
                       "concepts, Greek headwords and phrases, epithets, imagery, motifs, cross-lingual and "
                       "transliterated queries, and allusions to well-known lines. Written before any release S "
                       "retriever was run; every third query is held out and was not used to choose weights."),
           "judgement_rule": o["judgement_rule"] + (" Imagery and motif queries list several patterns in all_of; "
                                                     "a passage is relevant only when every one matches."),
           "metric": o["metric"] + " recall@50: distinct relevant passages in the first 50 / min(50, relevant passages).",
           "draft_sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(),
           "queries": queries}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.counts).write_text(json.dumps(counts, ensure_ascii=False, indent=1), encoding="utf-8")
    zero = [q["q"] for q in queries if not q["relevant_in_corpus"]]
    missing_locus = [q["q"] for q in queries if q.get("loci") and not q.get("locus_author_found")]
    no_gloss = [(q["q"], e["headword"]) for q in queries for e in q["headword_evidence"] if not e.get("head_meaning")]
    print(json.dumps({"queries": len(queries), "held_out": sum(q["split"] == "held_out" for q in queries),
                      "no_relevant": zero, "locus_author_missing": missing_locus, "headwords_without_gloss": no_gloss},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
