"""Frequent lemma n-grams (2-4) per author, genre and period (release P).

    python scripts/build_ngrams.py --index data/lemma_index.sqlite --out data/ngrams.sqlite

Read from the corpus headword index (docs/lemma-index.md): each token's top-ranked headword, in
searchable edited Greek text (the default scope of every lemma endpoint). An n-gram is n
consecutive headwords inside one stored passage; a token without a headword breaks the sequence.

Statistic: Dunning's log-likelihood G2 of the n-gram's last headword following its (n-1)-word
prefix, against that headword's frequency in the same group (for bigrams this is the usual
collocation G2 of two adjacent words). Rows need a minimum count (author 3, genre and period 5,
whole corpus 10) and a positive association (observed above expected). With --citations, a text held
in several collections (Perseus Iliad, OGC ilias) is counted once, and a passage repeated word for word
within one work (a refrain) is counted once. Up to 400 n-grams per
group and length are kept, ranked by G2; `function_only` marks n-grams made only of articles,
particles, conjunctions, prepositions and pronouns (the API hides them by default).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lemma_index import LemmaIndex, _log_likelihood  # noqa: E402

MIN_COUNT = {"author": 3, "genre": 5, "period": 5, "corpus": 10}
KEEP = 400
CLOSED = ("article", "particle", "conjunction", "preposition", "pronoun")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--include-reference", action="store_true")
    p.add_argument("--citations", default="", help="citation_index.sqlite: count one collection per TLG work")
    args = p.parse_args()
    started = time.time()
    ix = LemmaIndex(args.index)
    mask = ix.scope_mask(args.include_reference)
    con = ix.con()
    lemma_name, closed = {}, set()
    for lid, lemma, pos, norm in con.execute("SELECT id, lemma, pos, normalisation FROM lemma"):
        lemma_name[lid] = lemma
        if pos in CLOSED or norm is None:
            closed.add(lid)
    skip = set()
    if args.citations:
        # One copy of each text: where several collections hold the same TLG work (Perseus Iliad and
        # OGC ilias), only the collection with the most cited passages is counted.
        cit = sqlite3.connect(f"file:{args.citations}?mode=ro", uri=True)
        rows = cit.execute("SELECT w.tlg_author, w.tlg_work, l.source, l.passage_id FROM locus l JOIN work w "
                           "ON w.work_key=l.work_key WHERE w.tlg_work IS NOT NULL").fetchall()
        size = Counter((a, w, src) for a, w, src, _ in rows)
        primary = {}
        for (a, w, src), count in size.items():
            if (a, w) not in primary or count > size[(a, w, primary[(a, w)])]:
                primary[(a, w)] = src
        dropped = {(a, w, src) for (a, w, src) in size if primary[(a, w)] != src}
        skip = {pid for a, w, src, pid in rows if (a, w, src) in dropped}
        print(time.strftime("%H:%M:%S"), "duplicate collections skipped:", len(dropped), "works,", len(skip), "passages",
              flush=True)
    groups = defaultdict(list)  # (kind, name) -> pids
    for pid in np.flatnonzero(mask).tolist():
        if ix.pid_id[pid] in skip:
            continue
        info = ix.authors.get(ix.author_of[pid]) or {}
        groups[("author", info.get("author") or ix.author_of[pid])].append(pid)
        if info.get("genre"):
            groups[("genre", info["genre"])].append(pid)
        groups[("period", ix.pid_period[pid] or "undated")].append(pid)
        groups[("corpus", "all")].append(pid)
    print(time.strftime("%H:%M:%S"), len(groups), "groups", flush=True)
    seqs = {}
    for pid in np.flatnonzero(mask).tolist():
        toks = ix.tokens(pid)
        if toks is not None:
            seqs[pid] = toks[0].astype(np.int64).tolist()
    out = Path(args.out)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript("""PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE grp(kind TEXT, name TEXT, passages INTEGER, tokens INTEGER, PRIMARY KEY(kind, name));
      CREATE TABLE ngram(kind TEXT, name TEXT, n INTEGER, rank INTEGER, lemma_ids TEXT, lemmas TEXT, count INTEGER,
                         expected REAL, g2 REAL, per_10k REAL, function_only INTEGER, example TEXT);""")
    for (kind, name), pids in sorted(groups.items()):
        unigram = Counter()
        grams = {2: Counter(), 3: Counter(), 4: Counter()}
        example = {}
        tokens = 0
        repeated = set()
        for pid in pids:
            seq = seqs.get(pid)
            if not seq:
                continue
            # A line repeated within one work (a refrain) is counted once.
            key = (ix.meta[pid][5], ix.meta[pid][2], ix.meta[pid][3], tuple(seq))
            if key in repeated:
                continue
            repeated.add(key)
            tokens += len(seq)
            unigram.update(x for x in seq if x)
            for n in (2, 3, 4):
                for i in range(len(seq) - n + 1):
                    gram = tuple(seq[i:i + n])
                    if 0 in gram:
                        continue
                    grams[n][gram] += 1
                    if gram not in example:
                        example[gram] = ix.pid_id[pid]
        db.execute("INSERT INTO grp VALUES (?,?,?,?)", (kind, name, len(pids), tokens))
        if tokens < 50:
            continue
        minimum = MIN_COUNT[kind]
        for n in (2, 3, 4):
            prefixes = grams[n - 1] if n > 2 else unigram
            prefix_total = sum(prefixes.values()) or 1
            rows = []
            for gram, c in grams[n].items():
                if c < minimum:
                    continue
                r1 = prefixes.get(gram[:-1] if n > 2 else gram[0], 0)   # prefix occurrences
                c1 = unigram.get(gram[-1], 0)                            # last headword occurrences
                N = prefix_total if n > 2 else tokens
                expected = r1 * c1 / N if N else 0
                if expected <= 0 or c <= expected:
                    continue
                g2 = _log_likelihood(c, r1, c1, N)
                rows.append((g2, c, expected, gram))
            rows.sort(key=lambda r: (-r[0], -r[1]))
            for rank, (g2, c, expected, gram) in enumerate(rows[:KEEP], 1):
                db.execute("INSERT INTO ngram VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    kind, name, n, rank, " ".join(map(str, gram)), " ".join(lemma_name.get(x, "?") for x in gram), c,
                    round(expected, 3), round(g2, 2), round(c * 1e4 / tokens, 3),
                    int(all(x in closed for x in gram)), example.get(gram)))
        db.commit()
    db.executescript("CREATE INDEX ngram_group ON ngram(kind, name, n, rank);")
    manifest = {"version": "melos-lemma-ngrams-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "index": {k: ix.manifest.get(k) for k in ("version", "built_at")},
                "scope": "all indexed Greek records" if args.include_reference else "searchable edited Greek text",
                "min_count": MIN_COUNT, "keep_per_group_and_length": KEEP, "groups": len(groups),
                "duplicate_passages_skipped": len(skip),
                "deduplication": ("one collection per TLG work (citation index); unnumbered fragment editions are "
                                  "not deduplicated") if args.citations else None,
                "statistic": ("Dunning log-likelihood G2 of the last headword following the (n-1)-headword prefix "
                              "against its frequency in the group; positive associations only"),
                "seconds": round(time.time() - started)}
    db.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest),))
    db.commit()
    db.close()
    print(time.strftime("%H:%M:%S"), "wrote", out, os.path.getsize(out), manifest, flush=True)


if __name__ == "__main__":
    main()
