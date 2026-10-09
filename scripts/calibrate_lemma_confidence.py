"""Calibrate the headword index's confidence against treebank gold lemmas (release P).

Gold: the PerseusDL Greek Dependency Treebank tokens already in data/lexica/forms.jsonl (quality
annotated_treebank_token) for works that are also stored in the corpus as Perseus passages with
line citations: Homer (Iliad, Odyssey), Hesiod (Theogony, Shield), Sophocles, Aeschylus.

Leakage control. The index uses lemmas recorded for a spelling in source annotations, which include
these treebanks. The evaluation index is therefore assembled from the same staging data with the
gold works' treebank tokens removed from the form lists (`filter-lexica`, then the assemble stage
with that lexica directory), so no gold token's own annotation can support its prediction. The
contextual model (OdyCy) was trained on UD treebanks derived from these texts; its agreement is
therefore optimistic here, and the report shows it separately.

    python scripts/calibrate_lemma_confidence.py filter-lexica --forms /lexica/forms.jsonl --out DIR/forms.jsonl
    python scripts/calibrate_lemma_confidence.py evaluate --index EVAL.sqlite --forms /lexica/forms.jsonl \
        --out report.json --calibration calibration.json

Split: every gold token belongs to a block (work, book, 25-line group); blocks are assigned to the
fitting half or the held-out half by a fixed hash. The mapping is fitted on the fitting half
(isotonic regression of correctness on the raw confidence, separately per evidence class) and the
reliability table is reported on the held-out half only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lemma_tokens import fold  # noqa: E402
from backend.lemma_calibration import evidence_class, CLASSES  # noqa: E402

GOLD_TEXTGROUPS = ("tlg0012", "tlg0020", "tlg0011", "tlg0085")
CITE = re.compile(r"urn:cts:greekLit:(tlg\d{4})\.(tlg\d{3}):(\d+)(?:\.(\d+))?")
DOC = re.compile(r"urn:cts:greekLit:(tlg\d{4})\.(tlg\d{3})")
DIGITS = re.compile(r"\d+$")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def is_gold_row(row):
    if row.get("quality") != "annotated_treebank_token":
        return False
    m = DOC.search(str(row.get("document_id") or ""))
    return bool(m and m[1] in GOLD_TEXTGROUPS)


def filter_lexica(args):
    kept = dropped = 0
    with open(args.forms, encoding="utf-8") as src, open(args.out, "w", encoding="utf-8") as dst:
        for line in src:
            row = json.loads(line)
            if is_gold_row(row):
                dropped += 1
                continue
            dst.write(line)
            kept += 1
    log("forms kept", kept, "gold-work treebank tokens removed", dropped)


def gold_tokens(forms):
    """{(tlgA, tlgW): [(locus tuple, sentence, token, form, lemma)]} for cited gold tokens."""
    out = defaultdict(list)
    for line in open(forms, encoding="utf-8"):
        if "annotated_treebank_token" not in line:
            continue
        row = json.loads(line)
        if not is_gold_row(row):
            continue
        m = CITE.search(str(row.get("citation") or ""))
        if not m:
            continue
        locus = (int(m[3]),) + ((int(m[4]),) if m[4] else ())
        out[(m[1], m[2])].append((locus, int(row.get("sentence_id") or 0), int(row.get("token_id") or 0),
                                  row.get("form") or "", row.get("lemma") or ""))
    for key in out:
        out[key].sort(key=lambda t: (t[1], t[2]))
    return out


def gold_key(lemma):
    from backend.lemma_glosses import headword_key
    return fold(headword_key(DIGITS.sub("", unicodedata.normalize("NFC", lemma))))


def align(args):
    """Evaluation rows: (block, raw confidence, source bits, correct, pred lemma, gold lemma, form)."""
    from backend.lemma_index import LemmaIndex
    from backend.citations import parse_range
    ix = LemmaIndex(args.index)
    con = ix.con()
    lemma_of = {r[0]: r[1] for r in con.execute("SELECT id, lemma FROM lemma")}
    form_of = {r[0]: r[1] for r in con.execute("SELECT id, form FROM form")}
    gold = gold_tokens(args.forms)
    log("gold tokens with line citations", sum(len(v) for v in gold.values()), "in", len(gold), "works")
    passages = defaultdict(list)
    for pid, pid_text in enumerate(ix.pid_id):
        if not pid_text or not pid_text.startswith("perseus:") or not ix.edited[pid]:
            continue
        m = re.match(r"perseus:(tlg\d{4})\.(tlg\d{3})\.", pid_text)
        if not m or (m[1], m[2]) not in gold:
            continue
        rng = parse_range(ix.meta[pid][4])
        if rng:
            passages[(m[1], m[2])].append(([x[0] for x in rng[0]], [x[0] for x in rng[1]], pid))
    import bisect
    rows, stats = [], Counter()
    for work, toks in gold.items():
        depth = Counter(len(t[0]) for t in toks).most_common(1)[0][0]
        spans = sorted((tuple(start[-depth:]), tuple(end[-depth:]), pid) for start, end, pid in passages.get(work, [])
                       if len(start) >= depth)
        starts = [sp[0] for sp in spans]
        by_pid = defaultdict(list)
        for tok in toks:
            locus = tuple(tok[0])
            if len(locus) != depth:
                stats["gold_other_citation_depth"] += 1
                continue
            i = bisect.bisect_right(starts, locus) - 1
            hit = None
            for j in (i, i - 1, i - 2):
                if 0 <= j < len(spans) and spans[j][0] <= locus <= spans[j][1]:
                    hit = spans[j][2]
                    break
            if hit is None:
                stats["gold_without_passage"] += 1
                continue
            by_pid[hit].append(tok)
        for pid, gtoks in by_pid.items():
            t = ix.tokens(pid)
            if t is None:
                continue
            pred_forms = [fold(form_of.get(int(f), "")) for f in t[1]]
            gold_forms = [fold(g[3]) for g in gtoks]
            sm = difflib.SequenceMatcher(None, gold_forms, pred_forms, autojunk=False)
            for a, b, size in sm.get_matching_blocks():
                for k in range(size):
                    g, i = gtoks[a + k], b + k
                    stats["aligned"] += 1
                    lid = int(t[0][i])
                    block = f"{work[0]}.{work[1]}:{g[0][0] if len(g[0]) > 1 else 0}:{g[0][-1] // 25}"
                    if not lid:
                        stats["aligned_without_headword"] += 1
                        rows.append((block, 0, int(t[3][i]), None, None, g[4], g[3]))
                        continue
                    pred = lemma_of.get(lid, "")
                    correct = gold_key(g[4]) == fold(pred)
                    rows.append((block, int(t[2][i]), int(t[3][i]), bool(correct), pred, g[4], g[3]))
            stats["gold_in_matched_passages"] += len(gtoks)
    log("alignment", dict(stats))
    return rows, stats


def isotonic(x, y, w=None):
    """Pool-adjacent-violators: non-decreasing fit of y on sorted x. Returns (breakpoints, values)."""
    order = np.argsort(x, kind="stable")
    xs, ys = np.asarray(x)[order], np.asarray(y, dtype=float)[order]
    ws = np.ones_like(ys) if w is None else np.asarray(w, dtype=float)[order]
    # pool identical x first
    ux, idx = np.unique(xs, return_index=True)
    sums = np.add.reduceat(ys * ws, idx)
    wts = np.add.reduceat(ws, idx)
    blocks = [[ux[i], ux[i], sums[i], wts[i]] for i in range(len(ux))]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][2] / out[-2][3] > out[-1][2] / out[-1][3]:
            lo, hi = out[-2], out.pop()
            out[-1] = [lo[0], hi[1], lo[2] + hi[2], lo[3] + hi[3]]
    return [[int(b[0]), int(b[1]), round(b[2] / b[3], 4), int(b[3])] for b in out]


def fit(rows):
    model = {}
    by_class = defaultdict(list)
    for block, conf, src, correct, *_ in rows:
        if correct is None:
            continue
        by_class[evidence_class(src)].append((conf, correct))
    pooled = [r for v in by_class.values() for r in v]
    model["all"] = isotonic([c for c, _ in pooled], [int(k) for _, k in pooled])
    for cls, vals in by_class.items():
        if len(vals) >= 300:
            model[cls] = isotonic([c for c, _ in vals], [int(k) for _, k in vals])
    return model, {cls: len(v) for cls, v in by_class.items()}


def reliability(pairs, edges=(0, .5, .6, .7, .8, .9, .95, .98, 1.0001)):
    table = []
    ece = 0.0
    n_all = len(pairs)
    for lo, hi in zip(edges, edges[1:]):
        sel = [(p, c) for p, c in pairs if lo <= p < hi]
        if not sel:
            continue
        mean_p = sum(p for p, _ in sel) / len(sel)
        acc = sum(c for _, c in sel) / len(sel)
        ece += len(sel) / n_all * abs(mean_p - acc)
        table.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "tokens": len(sel), "mean_confidence": round(mean_p, 3),
                      "observed_accuracy": round(acc, 3), "gap": round(acc - mean_p, 3)})
    return table, round(ece, 4)


def evaluate(args):
    from backend.lemma_calibration import apply_model
    rows, stats = align(args)
    fit_rows = [r for r in rows if int(hashlib.sha1(r[0].encode()).hexdigest(), 16) % 2 == 0]
    test_rows = [r for r in rows if int(hashlib.sha1(r[0].encode()).hexdigest(), 16) % 2 == 1]
    model, fit_counts = fit(fit_rows)
    calibration = {"version": "melos-lemma-calibration-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "classes": CLASSES, "model": model, "fit_tokens_by_class": fit_counts,
                   "method": ("Isotonic regression (pool-adjacent-violators) of agreement with the treebank gold "
                              "lemma on the raw 0-255 confidence, per evidence class when the class has at least "
                              "300 fitting tokens, else pooled. Fitted on half of the gold blocks."),
                   "gold": "PerseusDL Greek Dependency Treebank v1.6 tokens of Homer, Hesiod, Sophocles and Aeschylus "
                           "aligned to the corpus's Perseus passages",
                   "index": args.index}
    test = [r for r in test_rows if r[3] is not None]
    raw_pairs = [(r[1] / 255, int(r[3])) for r in test]
    cal_pairs = [(apply_model(model, r[1], r[2]), int(r[3])) for r in test]
    raw_table, raw_ece = reliability(raw_pairs)
    cal_table, cal_ece = reliability(cal_pairs)
    by_class = {}
    for cls in CLASSES:
        sel = [r for r in test if evidence_class(r[2]) == cls]
        if sel:
            by_class[cls] = {"tokens": len(sel), "accuracy": round(sum(r[3] for r in sel) / len(sel), 3),
                             "mean_raw_confidence": round(sum(r[1] for r in sel) / len(sel) / 255, 3),
                             "mean_calibrated": round(sum(apply_model(model, r[1], r[2]) for r in sel) / len(sel), 3)}
    errors = Counter((r[5], r[4]) for r in test if r[3] is False)
    no_head = sum(1 for r in test_rows if r[3] is None)
    report = {"alignment": dict(stats), "tokens": {"fit": len([r for r in fit_rows if r[3] is not None]),
                                                    "held_out": len(test), "held_out_without_headword": no_head},
              "held_out_accuracy": round(sum(r[3] for r in test) / len(test), 4) if test else None,
              "raw_confidence": {"ece": raw_ece, "bins": raw_table},
              "calibrated": {"ece": cal_ece, "bins": cal_table}, "by_evidence_class": by_class,
              "frequent_disagreements": [{"gold": g, "predicted": p, "count": c} for (g, p), c in errors.most_common(40)],
              "notes": ["Correct = the predicted headword equals the treebank lemma after homograph digits, length "
                        "marks and accents are removed; treebank lemma conventions that differ from the dictionaries' "
                        "headwords count as disagreements.",
                        "The contextual model was trained on UD treebanks built from these texts: "
                        "context_agrees / context_chose accuracy is optimistic here."]}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.calibration:
        Path(args.calibration).write_text(json.dumps(calibration, ensure_ascii=False) + "\n", encoding="utf-8")
    log("held-out accuracy", report["held_out_accuracy"], "ECE raw", raw_ece, "calibrated", cal_ece)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("filter-lexica")
    a.add_argument("--forms", required=True)
    a.add_argument("--out", required=True)
    b = sub.add_parser("evaluate")
    b.add_argument("--index", required=True)
    b.add_argument("--forms", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--calibration", default="")
    args = p.parse_args()
    {"filter-lexica": filter_lexica, "evaluate": evaluate}[args.cmd](args)


if __name__ == "__main__":
    main()
