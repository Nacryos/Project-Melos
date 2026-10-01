"""Build judged retrieval queries from links that already exist in the index.

Every record in the corpus that is an English translation or commentary of a
Greek text names its parent through ``parent_id``. That link is a judgment:
the English text describes that Greek passage. Sampling such records gives a
large, reproducible set of "English description -> Greek passage" queries
with no human labelling and no invented text. Three query families:

  translation_to_greek   query = a linked English translation (Perseus; epic-heavy)
  commentary_to_greek    query = a linked English commentary paragraph (Sappho-heavy)
  fixtures               the 38 hand-checked queries in data/evaluation

For each query the target is the parent passage plus every indexed copy of the
same words (same merged author, text key and quality), and ``exclude_ids`` lists
the query record itself and its sibling translations/commentary, so a method
cannot score by finding the English text it was given. Scores are retrieval
diagnostics over this corpus, not statements about Ancient Greek semantics.

  python scripts/lab_build_eval.py --db /app/data/corpus.sqlite --out /lab/eval-queries.jsonl --per-family 150
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path


import re

GREEK_CHARS = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
# Commentary that glosses words, prints metrical schemes or cites scholarship
# is not a description of the poem's content; these patterns drop it from the
# "descriptive" query set.
NON_DESCRIPTIVE = re.compile(r"Meter:|\bMetre\b|\bsee\b|\bcf\.|\bpp?\.\s*\d|\bvol\.|\b(?:18|19|20)\d\d\b|\bLoeb\b|\bed\.|\bfrr?\.\s*\d|"
                             r"\b(?:pres|aor|perf|impf|fut|gen|dat|acc|nom|sg|pl|partic|infin|subj|opt|indic)\b\.?", re.I)


def descriptive(text: str) -> bool:
    letters = sum(1 for c in text if c.isalpha())
    greek = len(GREEK_CHARS.findall(text))
    return letters >= 80 and greek <= letters * 0.05 and not NON_DESCRIPTIVE.search(text)


def sample_linked(con: sqlite3.Connection, kind: str, count: int, seed: int, min_len: int, max_len: int, keep_siblings: bool = False, only_descriptive: bool = False) -> list[dict]:
    rows = con.execute(
        """SELECT t.id, t.text, t.author, p.id, p.author, p.author_canonical, p.text_key, p.quality, p.work, p.citation, p.source
           FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id')
           WHERE t.kind=? AND t.language='eng' AND p.kind='text' AND p.language='grc'
             AND p.quality IN ('source_text','machine_corrected_ocr')
             AND length(t.text) BETWEEN ? AND ?""", (kind, min_len, max_len)).fetchall()
    if only_descriptive:
        rows = [row for row in rows if descriptive(row[1])]
    rng = random.Random(seed)
    # Stratify: at most a third of the sample from any single parent author so
    # Homer does not swamp the translation family.
    by_author: dict[str, list] = {}
    for row in rows:
        by_author.setdefault(row[5] or row[4], []).append(row)
    for group in by_author.values():
        rng.shuffle(group)
    cap = max(1, count // 3)
    chosen: list = []
    authors = sorted(by_author, key=lambda a: -len(by_author[a]))
    while len(chosen) < count and any(by_author.values()):
        progressed = False
        for author in authors:
            group = by_author[author]
            taken = sum(1 for row in chosen if (row[5] or row[4]) == author)
            if group and taken < cap and len(chosen) < count:
                chosen.append(group.pop())
                progressed = True
        if not progressed:
            break
    queries = []
    for (query_id, text, query_author, parent_id, parent_author, canonical, text_key, quality, work, citation, source) in chosen:
        copies = [r[0] for r in con.execute(
            "SELECT id FROM passages WHERE author_canonical=? AND text_key=? AND quality=?", (canonical, text_key, quality))]
        siblings = [r[0] for r in con.execute(
            "SELECT id FROM passages WHERE json_extract(data,'$.parent_id')=? AND kind IN ('translation','commentary')", (parent_id,))]
        queries.append({
            "id": f"{kind}:{query_id}", "family": f"{kind}_to_greek", "query": " ".join(text.split()),
            "query_record": query_id, "target_ids": sorted(set(copies) | {parent_id}),
            "exclude_ids": [query_id] if keep_siblings else sorted(set(siblings) | {query_id}),
            "author": canonical or parent_author, "work": work, "citation": citation, "source": source,
        })
    return queries


def fixtures(path: Path, con: sqlite3.Connection) -> list[dict]:
    out = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        target = con.execute("SELECT author_canonical, text_key, quality FROM passages WHERE id=?", (row["target_id"],)).fetchone()
        if not target:
            continue
        copies = [r[0] for r in con.execute(
            "SELECT id FROM passages WHERE author_canonical=? AND text_key=? AND quality=?", target)]
        out.append({"id": f"fixture:{row['id']}", "family": f"fixture_{row['category']}", "query": row["query"],
                    "query_record": None, "target_ids": sorted(set(copies) | {row["target_id"]}), "exclude_ids": [],
                    "author": target[0], "work": None, "citation": None, "source": "fixture"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("/app/scripts/../data/evaluation/retrieval-queries.jsonl"))
    parser.add_argument("--per-family", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--keep-siblings", action="store_true", help="exclude only the query record itself; other translations/commentary of the parent stay in the pool (realistic description search)")
    parser.add_argument("--descriptive", action="store_true", help="keep only commentary/translation that reads as a description (no glosses, metre, bibliography)")
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    queries = (sample_linked(con, "translation", args.per_family, args.seed, 60, 600, args.keep_siblings, args.descriptive)
               + sample_linked(con, "commentary", args.per_family, args.seed + 1, 80, 900, args.keep_siblings, args.descriptive)
               + fixtures(args.fixtures, con))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as stream:
        for row in queries:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    families: dict[str, int] = {}
    authors: dict[str, int] = {}
    for row in queries:
        families[row["family"]] = families.get(row["family"], 0) + 1
        authors[row["author"]] = authors.get(row["author"], 0) + 1
    print(json.dumps({"queries": len(queries), "families": families,
                      "authors": dict(sorted(authors.items(), key=lambda kv: -kv[1])[:12])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
