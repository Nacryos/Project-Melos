"""Release U: group the editions of one fragment or passage, so author-level counts count it once.

Identity rule: the one search uses to fold editions (``backend.retrieval.group_editions``, release O): two
passages are the same text when they have the same canonical author and language and at least half of the
shorter text's content words (four letters or more, accent-free; at least three of them) occur in the other.
Search applies it to the first 300 results of a query; this script applies it to every pair of searchable
edited Greek passages of the same author held by DIFFERENT collections (sources), and joins the pairs into
groups (union-find). Two passages that are both mapped to TLG works are left to the release Q rule
(``LemmaIndex.count_mask`` already counts one collection of a TLG work), so no pair of mapped passages is linked.

Per group the primary collection is the one holding most of its words. A passage of another collection is not
counted (``counted`` = 0) when it matches a passage of the primary collection directly, so a long chain of
links never removes text the primary collection lacks. In a fragment-sized group (at most 8 passages) a
passage whose words are at least 80 % contained in a longer passage of the same collection is a
``same_source_copy`` and not counted either (Campbell prints Sappho 168B again as adesp. 976).
``LemmaIndex.count_mask`` applies the ``counted`` flag after its release Q rules.

    python scripts/build_edition_groups.py --out /u-data/edition_groups.sqlite [--report report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.lemma_index import get_index  # noqa: E402
from backend.retrieval import _content_words  # noqa: E402
from backend.author_aliases import fold  # noqa: E402

THRESHOLD = 0.5
MIN_WORDS = 3
SAME_SOURCE = 0.8
SMALL_GROUP = 8  # the same-collection copy rule applies to fragment-sized groups only


class Union:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        p = self.parent.setdefault(x, x)
        while p != self.parent[p]:
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        self.parent[x] = p
        return p

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def links_for_author(pids, words, source, mapped):
    """Cross-collection pairs meeting the identity rule (prefix filtering on the rarest words)."""
    df = Counter(w for p in pids for w in words[p])
    order = {p: sorted(words[p], key=lambda w: (df[w], w)) for p in pids}
    postings = defaultdict(list)
    for p in pids:
        for w in words[p]:
            postings[w].append(p)
    pairs = []
    for s in pids:
        ws = words[s]
        n = len(ws)
        if n < MIN_WORDS:
            continue
        need = math.ceil(THRESHOLD * n)
        prefix = order[s][: n - need + 1]
        cands = set()
        for w in prefix:
            cands.update(postings[w])
        for o in cands:
            if o == s or source[o] == source[s] or (mapped[o] and mapped[s]):
                continue
            no = len(words[o])
            # s is the shorter text (ties: the lower pid is "shorter", so each pair is tested once)
            if no < n or (no == n and o < s):
                continue
            if len(ws & words[o]) >= need:
                pairs.append((s, o))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/corpus.sqlite")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    args = ap.parse_args()
    t0 = time.time()
    ix = get_index()
    info = ix.work_info()
    mapped_arr = (info["tlg_group"] >= 0) if info is not None else None
    con = sqlite3.connect(f"file:{Path(args.corpus).as_posix()}?mode=ro", uri=True)
    by_author = defaultdict(list)
    words, source, mapped = {}, {}, {}
    for pid, pid_text in enumerate(ix.pid_id):
        if pid_text is None or not ix.edited[pid]:
            continue
        info_a = ix.authors.get(ix.author_of[pid]) or {}
        author = fold(info_a.get("author") or ix.author_of[pid] or "")
        if not author:
            continue
        by_author[author].append(pid)
        source[pid] = ix.meta[pid][5]
        mapped[pid] = bool(mapped_arr[pid]) if mapped_arr is not None else False
    texts = {}
    want = {ix.pid_id[p]: p for ps in by_author.values() for p in ps}
    for pid_text, text, language in con.execute("SELECT id, text, language FROM passages"):
        p = want.get(pid_text)
        if p is not None and (language or "grc").startswith(("grc", "el", "greek", "Greek")):
            texts[p] = text
    for author, ps in by_author.items():
        by_author[author] = [p for p in ps if p in texts]
        for p in by_author[author]:
            words[p] = _content_words(texts[p])
    print(time.strftime("%H:%M:%S"), "passages", sum(map(len, by_author.values())), "authors", len(by_author),
          round(time.time() - t0, 1), "s", flush=True)
    uf = Union()
    n_pairs = 0
    neighbours = defaultdict(set)
    for author, ps in sorted(by_author.items(), key=lambda kv: -len(kv[1])):
        if len({source[p] for p in ps}) < 2:
            continue
        pairs = links_for_author(ps, words, source, mapped)
        n_pairs += len(pairs)
        for a, b in pairs:
            uf.join(a, b)
            neighbours[a].add(b)
            neighbours[b].add(a)
    groups = defaultdict(list)
    for p in uf.parent:
        groups[uf.find(p)].append(p)
    groups = {g: sorted(m) for g, m in groups.items() if len(m) > 1}
    rows = []
    copies = dropped = 0
    for g, members in groups.items():
        # The primary collection holds the most words of the group. A passage of another collection is
        # not counted when it matches a passage of the primary collection directly (edge, not group:
        # a long chain never removes text the primary collection does not hold).
        size = Counter()
        for p in members:
            size[source[p]] += int(ix.ntok[p])
        primary = max(size, key=lambda s: (size[s], s))
        linked = {p for p in members if source[p] != primary
                  and any(source[q] == primary for q in neighbours[p])}
        kept_by_source = defaultdict(list)
        # longest first, so the shorter same-collection reprint is the copy
        for p in sorted(members, key=lambda p: (-len(words[p]), p)):
            copy = 0
            if len(members) <= SMALL_GROUP:
                for q in kept_by_source[source[p]]:
                    small = min(len(words[p]), len(words[q]))
                    if small >= MIN_WORDS and len(words[p] & words[q]) / small >= SAME_SOURCE:
                        copy = 1
                        break
            if not copy:
                kept_by_source[source[p]].append(p)
            counted = int(not copy and p not in linked)
            copies += copy
            dropped += int(not counted)
            rows.append((ix.pid_id[p], g, copy, counted, primary))
    out = Path(args.out)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript("CREATE TABLE edition_group(passage_id TEXT PRIMARY KEY, grp INTEGER NOT NULL, "
                     "same_source_copy INTEGER NOT NULL, counted INTEGER NOT NULL, primary_source TEXT); "
                     "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
    db.executemany("INSERT INTO edition_group VALUES (?,?,?,?,?)", rows)
    sizes = Counter(len(m) for m in groups.values())
    nsources = Counter(len({source[p] for p in m}) for m in groups.values())
    manifest = {"version": "u1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "rule": "same canonical author, >= 50% of the shorter text's 4+-letter words (>= 3) in the other, "
                        "different collections, not both TLG-mapped (backend.retrieval.group_editions rule)",
                "pairs": n_pairs, "groups": len(groups), "passages": len(rows), "same_source_copies": copies,
                "not_counted": dropped,
                "largest_groups": sorted(sizes.items())[-5:], "sources_per_group": dict(sorted(nsources.items()))}
    db.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest),))
    db.commit()
    print(json.dumps(manifest, ensure_ascii=False))
    if args.report:
        big = sorted(groups.values(), key=len, reverse=True)[:15]
        report = {"manifest": manifest,
                  "largest": [[(ix.pid_id[p], source[p], ix.meta[p][4], len(words[p])) for p in m[:40]] for m in big]}
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(time.strftime("%H:%M:%S"), "done", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
