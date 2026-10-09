"""Build a bi-encoder training set from the English-to-Greek links in the corpus.

Every English (or Modern Greek) translation or descriptive commentary that
names a Greek parent passage through ``parent_id`` is one judged pair:
anchor = the translation text, positive = the Greek passage text. Collector
outputs not yet indexed (Edmonds *Elegy and Iambus*, Paton's Greek Anthology)
contribute pairs the same way, resolving parents inside their own file or in
the index. Each pair gets up to N hard negatives: Greek passages that share
the positive's rarest words (BM25 over the index) but are not the positive or
a copy of it. Nothing is generated; every text is a corpus record with its ID.

Splits: pairs are assigned to train or dev by a hash of the Greek parent ID
(so sibling translations of one passage never straddle the split), and a hash
of (author, work) holds out whole works into dev for a generalisation check.

  python scripts/build_training_pairs.py --db /home/alvin/services/melos/data/corpus.sqlite \
      --extra data/processed/p2_perseus_elegy.jsonl data/processed/p2_attalus_anthology.jsonl \
      --out data/training/melos-bi-encoder-pairs-2026-10-09

Output: train.jsonl, dev.jsonl (fields anchor, positive, negatives[], ids and
provenance), stats.json, README.md (fine-tune recipe). The output directory is
git-ignored; it contains corpus text.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.author_aliases import canonical as canonical_author  # noqa: E402
from backend.textutils import normalize, text_key, tokenize  # noqa: E402

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
NON_DESCRIPTIVE = re.compile(r"Meter:|\bMetre\b|\bsee\b|\bcf\.|\bpp?\.\s*\d|\bvol\.|\b(?:18|19|20)\d\d\b|\bLoeb\b|\bed\.|\bfrr?\.\s*\d|"
                             r"\b(?:pres|aor|perf|impf|fut|gen|dat|acc|nom|sg|pl|partic|infin|subj|opt|indic)\b\.?", re.I)
SEARCHABLE = ("source_text", "machine_corrected_ocr")


def descriptive(text: str) -> bool:
    letters = sum(1 for c in text if c.isalpha())
    greek = len(GREEK.findall(text))
    return letters >= 80 and greek <= letters * 0.05 and not NON_DESCRIPTIVE.search(text)


def clean(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in str(text or "").split("\n")).strip()


def bucket(value: str, modulus: int = 100) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest(), 16) % modulus


class Builder:
    def __init__(self, db: Path, negatives: int, min_anchor: int, max_anchor: int, max_positive: int):
        self.con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.negatives = negatives
        self.min_anchor, self.max_anchor, self.max_positive = min_anchor, max_anchor, max_positive
        self.vocab_cache: dict[str, int] = {}

    def vocab(self, key: str) -> int:
        if key not in self.vocab_cache:
            row = self.con.execute("SELECT count FROM vocabulary WHERE normalized=?", (key,)).fetchone()
            self.vocab_cache[key] = int(row[0]) if row else 0
        return self.vocab_cache[key]

    def rare_terms(self, greek_text: str, keep: int = 8, ceiling: int = 1500) -> list[str]:
        scored = []
        for token in set(tokenize(greek_text)):
            key = normalize(token)
            if len(key) < 4 or not GREEK.search(key):
                continue
            count = self.vocab(key)
            if 1 < count <= ceiling:
                scored.append((count, key))
        scored.sort()
        return [key for _, key in scored[:keep]]

    def hard_negatives(self, positive_text: str, positive_key: tuple[str, str], exclude_ids: set[str]) -> list[dict]:
        terms = self.rare_terms(positive_text)
        if not terms:
            return []
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = self.con.execute(
            "SELECT p.id, p.text, p.author_canonical, p.text_key, p.author, p.work, p.citation FROM passage_fts "
            "JOIN passages p ON p.id=passage_fts.id WHERE passage_fts MATCH ? AND p.language='grc' AND p.kind='text' "
            "AND p.quality IN ('source_text','machine_corrected_ocr') ORDER BY bm25(passage_fts) LIMIT ?",
            (expression, self.negatives * 6)).fetchall()
        out = []
        seen_keys = {positive_key}
        positive_tokens = set(normalize(t) for t in tokenize(positive_text))
        for row in rows:
            key = (row["author_canonical"], row["text_key"])
            if row["id"] in exclude_ids or key in seen_keys:
                continue
            text = clean(row["text"])
            if not text or " ".join(text.split()) == " ".join(positive_text.split()):
                continue
            # Another edition of the same words (different accents, line breaks
            # or supplements) is a copy, not a negative: skip near-duplicates.
            candidate_tokens = set(normalize(t) for t in tokenize(text))
            overlap = len(candidate_tokens & positive_tokens) / max(1, min(len(candidate_tokens), len(positive_tokens)))
            if overlap >= 0.5:
                continue
            seen_keys.add(key)
            out.append({"id": row["id"], "text": text[:self.max_positive], "author": row["author"], "work": row["work"], "citation": row["citation"]})
            if len(out) >= self.negatives:
                break
        return out

    def indexed_pairs(self, include_commentary: str) -> list[dict]:
        rows = self.con.execute(
            """SELECT t.id qid, t.text qtext, t.language qlang, t.kind qkind, t.author qauthor, t.source qsource,
                      p.id pid, p.text ptext, p.author pauthor, p.author_canonical pcanon, p.text_key pkey, p.work pwork,
                      p.citation pcit, p.source psource
               FROM passages t JOIN passages p ON p.id=json_extract(t.data,'$.parent_id')
               WHERE t.kind IN ('translation','commentary') AND t.language IN ('eng','ell')
                 AND p.kind='text' AND p.language='grc' AND p.quality IN ('source_text','machine_corrected_ocr')""").fetchall()
        pairs = []
        for row in rows:
            anchor = clean(row["qtext"])
            if not (self.min_anchor <= len(anchor) <= self.max_anchor):
                continue
            if row["qkind"] == "commentary":
                if include_commentary == "none":
                    continue
                if include_commentary == "descriptive" and not descriptive(anchor):
                    continue
            pairs.append({
                "anchor": anchor, "anchor_id": row["qid"], "anchor_language": row["qlang"], "anchor_kind": row["qkind"],
                "anchor_author": row["qauthor"], "anchor_source": row["qsource"],
                "positive": clean(row["ptext"])[:self.max_positive], "positive_id": row["pid"],
                "author": row["pcanon"] or canonical_author(row["pauthor"]), "author_label": row["pauthor"],
                "work": row["pwork"], "citation": row["pcit"], "source": row["psource"],
                "_key": (row["pcanon"] or canonical_author(row["pauthor"]), row["pkey"]),
            })
        return pairs

    def extra_pairs(self, path: Path) -> list[dict]:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_id = {r["id"]: r for r in records}
        pairs = []
        for record in records:
            if record.get("kind") not in ("translation", "commentary") or record.get("language") not in ("eng", "ell"):
                continue
            parent_id = record.get("parent_id")
            if not parent_id:
                continue
            parent = by_id.get(parent_id)
            if parent is None:
                row = self.con.execute("SELECT id, text, author, author_canonical, text_key, work, citation, source, kind, language, quality FROM passages WHERE id=?", (parent_id,)).fetchone()
                if row is None or row["kind"] != "text" or row["language"] != "grc" or row["quality"] not in SEARCHABLE:
                    continue
                parent = dict(row)
            if parent.get("kind") != "text" or parent.get("language") != "grc" or parent.get("quality", "source_text") not in SEARCHABLE:
                continue
            anchor = clean(record["text"])
            if not (self.min_anchor <= len(anchor) <= self.max_anchor):
                continue
            if record.get("kind") == "commentary" and not descriptive(anchor):
                continue
            positive = clean(parent["text"])
            if len(positive) < 15:
                continue
            canon = parent.get("author_canonical") or canonical_author(parent.get("author", ""))
            key = (canon, parent.get("text_key") or text_key("grc", "text", parent["text"]))
            pairs.append({
                "anchor": anchor, "anchor_id": record["id"], "anchor_language": record["language"], "anchor_kind": record["kind"],
                "anchor_author": record.get("author"), "anchor_source": record.get("source"),
                "positive": positive[:self.max_positive], "positive_id": parent_id,
                "author": canon, "author_label": parent.get("author"), "work": parent.get("work"),
                "citation": parent.get("citation"), "source": parent.get("source"), "_key": key,
            })
        return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--extra", type=Path, nargs="*", default=[], help="collector JSONL files with parent links (not yet indexed)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--negatives", type=int, default=3)
    parser.add_argument("--commentary", choices=["descriptive", "all", "none"], default="none", help="commentary anchors: none (default; the corpus commentary is glosses and metre), descriptive, or all")
    parser.add_argument("--min-anchor", type=int, default=25)
    parser.add_argument("--max-anchor", type=int, default=1500)
    parser.add_argument("--max-positive", type=int, default=2000)
    parser.add_argument("--dev-percent", type=int, default=10)
    parser.add_argument("--heldout-work-percent", type=int, default=5)
    args = parser.parse_args()
    started = time.time()
    builder = Builder(args.db, args.negatives, args.min_anchor, args.max_anchor, args.max_positive)
    pairs = builder.indexed_pairs(args.commentary)
    sources = {"index": {"db": str(args.db), "mtime": datetime.fromtimestamp(args.db.stat().st_mtime, timezone.utc).isoformat(),
                         "size": args.db.stat().st_size, "pairs": len(pairs)}, "extra": []}
    for path in args.extra:
        extra = builder.extra_pairs(path)
        sources["extra"].append({"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pairs": len(extra)})
        pairs.extend(extra)
    # One anchor text per (anchor_id); drop exact duplicate anchor/positive text pairs.
    seen = set()
    unique = []
    for pair in pairs:
        signature = (pair["anchor"], pair["positive"])
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(pair)
    pairs = unique
    # Hard negatives and splits.
    siblings: dict[str, set[str]] = {}
    for pair in pairs:
        siblings.setdefault(pair["positive_id"], set()).add(pair["anchor_id"])
    # Held-out works: walk works in hash order, skipping any work holding more
    # than 2 % of all pairs (Homer would swallow the dev set), until the
    # held-out share is reached.
    work_sizes = Counter(f"{pair['author']}|{pair['work']}" for pair in pairs)
    heldout_works: set[str] = set()
    budget = len(pairs) * args.heldout_work_percent / 100
    held = 0
    for work_key in sorted(work_sizes, key=bucket):
        if held >= budget:
            break
        if work_sizes[work_key] > len(pairs) * 0.02:
            continue
        heldout_works.add(work_key)
        held += work_sizes[work_key]
    train, dev = [], []
    for number, pair in enumerate(pairs, 1):
        exclude = {pair["positive_id"], pair["anchor_id"], *siblings.get(pair["positive_id"], ())}
        pair["negatives"] = builder.hard_negatives(pair["positive"], pair["_key"], exclude)
        if f"{pair['author']}|{pair['work']}" in heldout_works:
            pair["split_reason"] = "heldout_work"
            dev.append(pair)
        elif bucket(pair["positive_id"]) < args.dev_percent:
            pair["split_reason"] = "dev_sample"
            dev.append(pair)
        else:
            pair["split_reason"] = "train"
            train.append(pair)
        if number % 500 == 0:
            print(f"{number}/{len(pairs)} pairs ({time.time() - started:.0f}s)", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("dev.jsonl", dev)):
        with (args.out / name).open("w", encoding="utf-8") as stream:
            for pair in rows:
                record = {k: v for k, v in pair.items() if not k.startswith("_")}
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    stats = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "sources": sources,
        "pairs": len(pairs), "train": len(train), "dev": len(dev),
        "dev_heldout_works": sum(1 for p in dev if p["split_reason"] == "heldout_work"),
        "heldout_work_count": len(heldout_works),
        "with_negatives": sum(1 for p in pairs if p["negatives"]),
        "negatives_total": sum(len(p["negatives"]) for p in pairs),
        "by_anchor_language": dict(Counter(p["anchor_language"] for p in pairs)),
        "by_anchor_kind": dict(Counter(p["anchor_kind"] for p in pairs)),
        "by_positive_source": dict(Counter(p["source"] for p in pairs)),
        "by_author_top": dict(Counter(p["author"] for p in pairs).most_common(25)),
        "anchor_chars_mean": round(sum(len(p["anchor"]) for p in pairs) / max(1, len(pairs))),
        "positive_chars_mean": round(sum(len(p["positive"]) for p in pairs) / max(1, len(pairs))),
        "parameters": vars(args) | {"db": str(args.db), "extra": [str(p) for p in args.extra], "out": str(args.out)},
        "elapsed_seconds": round(time.time() - started),
    }
    (args.out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "README.md").write_text(README.format(**{k: stats[k] for k in ("pairs", "train", "dev", "negatives_total")}, out=args.out.name), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("pairs", "train", "dev", "dev_heldout_works", "with_negatives", "negatives_total", "by_anchor_language", "by_anchor_kind")}, ensure_ascii=False))


README = """# Melos bi-encoder training set: {out}

{pairs} anchor/positive pairs ({train} train, {dev} dev) with {negatives_total} hard negatives.
Anchor = an English or Modern Greek translation/description of a Greek passage;
positive = the Greek passage it names through `parent_id`; negatives = Greek
passages sharing the positive's rarest words but not its text. All texts are
corpus records (IDs included); nothing is generated. The directory is
git-ignored because it contains corpus text.

Fields per line: `anchor`, `positive`, `negatives` (list of {{id, text, author,
work, citation}}), `anchor_id`, `positive_id`, `anchor_language` (eng/ell),
`anchor_kind` (translation/commentary), `author` (merged name), `author_label`,
`work`, `citation`, `source`, `split_reason` (train / dev_sample /
heldout_work).

## Fine-tune recipe (GPU, not run on the box)

`scripts/finetune_bi_encoder.py` trains `BAAI/bge-m3` with
MultipleNegativesRankingLoss (in-batch negatives plus the listed hard
negatives), batch size 32, lr 2e-5, 2 epochs, max length 512, bf16, and
evaluates Recall@k on the dev set treating dev positives plus their negatives
as the retrieval corpus. Afterwards the corpus must be re-encoded with the
fine-tuned model (`scripts/build_embeddings.py` currently pins BAAI/bge-m3;
point it at the new model directory and bump the manifest model name) and the
retrieval lab (`scripts/lab_eval.py`) re-run on a fixed snapshot before the
new index is deployed.
"""


if __name__ == "__main__":
    main()
