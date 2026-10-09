"""Release U: do the GLAUx and Diorisis form counts help the reader's headword choice on the lyric gold set?

Offline re-ranking experiment on a lyric gold dump (scripts/eval_lyric_gold.py dump): every gold token's
ranked readings (`ranking_full`, the reader's own candidates and scores) get a prior from open annotated
corpora that Melos does not otherwise use:

  GLAUx lyric/poetry subset (data/open/glaux/lyric_tokens.jsonl.gz; automatic and manual annotation),
      WITHOUT the texts of Sappho and Alcaeus (the gold poems' own annotations would leak);
  Diorisis form/lemma/POS counts (data/open/diorisis/form_lemma_pos_counts.tsv.gz; automatic lemmatisation).

score' = score + w * share(form, lemma), share = count of the form with that lemma / count of the form (each
source separately, summed). The weight is chosen on the development half; the held-out half is reported with
that weight only. A token whose printed form neither source has is unchanged.

    python scripts/eval_open_priors.py --gold data/evaluation/lyric-gold-r.json --dump dump.json [--json out.json]
"""
from __future__ import annotations

import argparse
import gzip
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ELISION = "’'ʼ᾽"
EXCLUDE_GLAUX = {"Sappho", "Alcaeus"}


def key(form):
    form = unicodedata.normalize("NFC", str(form or "")).strip()
    if form[-1:] in ELISION:
        form = form[:-1] + "’"
    return form.lower()


def lemma_key(s):
    s = unicodedata.normalize("NFD", str(s or "")).casefold()
    return "".join(c for c in s if not unicodedata.combining(c)).rstrip("0123456789 ")


def load_counts(root):
    sources = {}
    texts = json.loads((root / "glaux/texts_selected.json").read_text(encoding="utf-8"))["selected"]
    excluded = {t["glaux_text_id"] for t in texts if t.get("author_standard") in EXCLUDE_GLAUX}
    glaux = defaultdict(Counter)
    with gzip.open(root / "glaux/lyric_tokens.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("text_id") in excluded or not row.get("form") or not row.get("lemma"):
                continue
            glaux[key(row["form"])][lemma_key(row["lemma"])] += 1
    sources["glaux"] = glaux
    dio = defaultdict(Counter)
    with gzip.open(root / "diorisis/form_lemma_pos_counts.tsv.gz", "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5 or not parts[0] or not parts[2]:
                continue
            dio[key(parts[0])][lemma_key(parts[2])] += int(parts[4] or 0)
    sources["diorisis"] = dio
    return sources, len(excluded)


def accepted(g):
    keys = {lemma_key(g["lemma"])}
    keys.update(lemma_key(x) for x in g.get("lemma_also") or [])
    return keys


def choose(row, sources, weight, use):
    ranking = [r for r in row.get("ranking_full") or [] if r.get("lemma")]
    if not ranking:
        return row.get("lemma") or "", False
    best = {}
    for r in ranking:
        lk = lemma_key(r["lemma"])
        s = float(r.get("score") or 0)
        if lk not in best or s > best[lk][0]:
            best[lk] = (s, r["lemma"])
    form = key(row.get("printed"))
    covered = False
    scored = []
    for lk, (s, lemma) in best.items():
        bonus = 0.0
        for name in use:
            counts = sources[name].get(form)
            if counts:
                covered = True
                bonus += counts.get(lk, 0) / sum(counts.values())
        scored.append((s + weight * bonus, -len(scored), lemma))
    shown = row.get("lemma") or ""
    if weight == 0 or not covered:
        return shown or max(scored)[2], covered
    top = max(scored)[2]
    # the prior only re-orders the reader's own candidates; a row with a settled lemma keeps it unless the
    # prior moves another candidate above it
    return top, covered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--open", default="data/open")
    ap.add_argument("--json")
    args = ap.parse_args()
    sources, excluded = load_counts(Path(args.open))
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))["tokens"]
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))["passages"]
    rows = {}
    for pid, p in dump.items():
        for w in p["words"]:
            rows[(pid, w["start"])] = w
    pairs = [(g, rows.get((g["passage_id"], g["start"]))) for g in gold if not g.get("uncertain")]
    pairs = [(g, r) for g, r in pairs if r is not None]

    def accuracy(split, weight, use):
        n = right = covered = changed = 0
        for g, r in pairs:
            if g["split"] != split:
                continue
            n += 1
            base, _ = choose(r, sources, 0.0, use)
            got, cov = choose(r, sources, weight, use)
            covered += cov
            changed += lemma_key(got) != lemma_key(base)
            right += lemma_key(got) in accepted(g)
        return {"tokens": n, "lemma_accuracy": round(right / n, 4) if n else None, "covered": covered, "changed": changed}

    report = {"excluded_glaux_texts": excluded, "weights": {}}
    for use in (("glaux",), ("diorisis",), ("glaux", "diorisis")):
        name = "+".join(use)
        sweep = {w: accuracy("dev", w, use) for w in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)}
        best_w = max(sweep, key=lambda w: (sweep[w]["lemma_accuracy"], -w))
        report["weights"][name] = {"dev_sweep": sweep, "chosen_weight": best_w,
                                   "held_baseline": accuracy("held", 0.0, use),
                                   "held_with_prior": accuracy("held", best_w, use)}
        print(name, "dev", {w: v["lemma_accuracy"] for w, v in sweep.items()}, "chosen", best_w,
              "held", report["weights"][name]["held_baseline"]["lemma_accuracy"], "->",
              report["weights"][name]["held_with_prior"]["lemma_accuracy"],
              "changed", report["weights"][name]["held_with_prior"]["changed"],
              "covered", report["weights"][name]["held_with_prior"]["covered"])
    # Fallback use: a word the reader leaves without a headword, read as the open sources' most frequent lemma.
    for split in ("dev", "held"):
        empty = fixed = offered = 0
        for g, r in pairs:
            if g["split"] != split or r.get("lemma") or any(i.get("lemma") for i in r.get("ranking_full") or []):
                continue
            empty += 1
            merged = Counter()
            for name in ("glaux", "diorisis"):
                for lk, c in (sources[name].get(key(r.get("printed"))) or {}).items():
                    merged[lk] += c
            if merged:
                offered += 1
                fixed += merged.most_common(1)[0][0] in accepted(g)
        report.setdefault("fallback", {})[split] = {"tokens_without_headword": empty, "open_reading_offered": offered,
                                                    "open_reading_right": fixed}
        print("fallback", split, report["fallback"][split])
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
