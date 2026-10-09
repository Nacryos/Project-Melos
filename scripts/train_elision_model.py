"""Train the elided-word model of the headword index (release Q; backend/elision.py).

Train data = treebank tokens only, never the held-out half:
  * prior counts P(lemma | elided spelling): every PerseusDL treebank token of data/lexica/forms.jsonl
    whose spelling is elided, except tokens of the gold works (Homer, Hesiod, Sophocles, Aeschylus) in
    the other half of the calibration split and gold-work tokens without a line citation;
  * feature counts (own / previous / next part of speech from the contextual model, clause position,
    next word's initial): gold-work tokens of the training half aligned to the corpus passages, read
    from the corpus text and the staging file's contextual predictions.
The smoothing (alpha, beta) and feature weight (tau) are chosen on a second split inside the training
half. --split fit trains on the calibration's fitting half (production and the held-out evaluation);
--split held trains on the held-out half (only to cross-fit the calibration map, never deployed).

    python scripts/train_elision_model.py --index EVAL_INDEX.sqlite --forms /lexica/forms.jsonl \
        --corpus /corpus.sqlite --build /build/lemma-build.sqlite --split fit --out elision_model.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.elision import (ELIDED_ONLY_FEATURES, FEATURES, ElisionModel, base_distribution, is_elided, key,  # noqa: E402
                             token_features)
from backend.lemma_tokens import fold, word_tokens  # noqa: E402
import calibrate_lemma_confidence as cal  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def half(block):
    return int(hashlib.sha1(block.encode()).hexdigest(), 16) % 2


def sub_half(block):
    return int(hashlib.sha1((block + "|elision").encode()).hexdigest(), 16) % 2


def model_key(lemma):
    """Accent-preserving lemma key of the model (ἄρα and ἀρά stay apart; case and grave ignored)."""
    from backend.lemma_glosses import headword_key
    import unicodedata
    return key(headword_key(cal.DIGITS.sub("", unicodedata.normalize("NFC", lemma))))


def gold_block(row):
    m = cal.CITE.search(str(row.get("citation") or ""))
    if not m:
        return None
    locus = (int(m[3]),) + ((int(m[4]),) if m[4] else ())
    return f"{m[1]}.{m[2]}:{locus[0] if len(locus) > 1 else 0}:{locus[-1] // 25}"


def prior_rows(forms, split):
    """(elided spelling key, gold lemma key, gold block or None) for the training treebank tokens."""
    want = 0 if split == "fit" else 1
    for line in open(forms, encoding="utf-8"):
        if "annotated_treebank_token" not in line:
            continue
        row = json.loads(line)
        if row.get("quality") != "annotated_treebank_token":
            continue
        form = row.get("form") or ""
        if not is_elided(form) or not row.get("lemma"):
            continue
        block = None
        if cal.is_gold_row(row):
            block = gold_block(row)
            if block is None or half(block) != want:
                continue
        yield key(form), model_key(row["lemma"]), block


def index_tables(index_path):
    con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    lemma_key, cls_of = {}, {}
    best = {}
    for lid, lemma, k, pos, tokens in con.execute("SELECT id,lemma,key,pos,tokens FROM lemma"):
        lemma_key[lid] = (lemma, k)
        if k not in best or (tokens or 0) > best[k]:
            best[k] = tokens or 0
            cls_of[k] = pos or "unknown"
    freq = defaultdict(Counter)
    readings = {}
    forms = {}
    for fid, form, tokens in con.execute("SELECT id,form,tokens FROM form"):
        forms[fid] = (form, tokens or 0)
    for fid, lid, rank, prob in con.execute("SELECT form_id,lemma_id,rank,prob FROM form_lemma ORDER BY form_id,rank"):
        form, n = forms[fid]
        lemma = lemma_key[lid][0]
        if is_elided(form):
            readings.setdefault(form, {})[lemma] = prob
        else:
            freq[key(form)][lemma] += n * prob
    lemma_pos = {lemma: cls_of.get(k, "unknown") for lemma, k in lemma_key.values()}
    return readings, freq, cls_of, lemma_pos


def build_model(prior_counts, feat_rows, params, values):
    prior = defaultdict(Counter)
    for form_key, lemma_key in prior_counts:
        prior[form_key][lemma_key] += 1
    feat = {f: defaultdict(Counter) for f in FEATURES}
    cls_feat = {f: defaultdict(Counter) for f in FEATURES}
    for lemma_key, cls, feats, elided in feat_rows:
        for f in FEATURES:
            if f in ELIDED_ONLY_FEATURES and not elided:
                continue
            feat[f][lemma_key][feats[f]] += 1
            cls_feat[f][cls][feats[f]] += 1
    return {"prior": {k: dict(v) for k, v in prior.items()},
            "features": {f: {k: dict(v) for k, v in d.items()} for f, d in feat.items()},
            "class_features": {f: {k: dict(v) for k, v in d.items()} for f, d in cls_feat.items()},
            "values": values, "params": params}


def accuracy(model, cases, readings, freq, lemma_pos):
    m = ElisionModel(model)
    right = n = 0
    for form, gold, feats in cases:
        cands = readings.get(form)
        if not cands:
            continue
        rough = feats["next_initial"] == "rough"
        base = base_distribution(form, cands, lambda k: freq.get(k), rough)
        ranked = m.rank(form, base, {h: lemma_pos.get(h) for h in cands}, feats, key)
        n += 1
        right += fold(ranked[0][0]) == fold(gold)
    return right / max(1, n), n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", required=True)
    p.add_argument("--forms", required=True)
    p.add_argument("--corpus", required=True)
    p.add_argument("--build", required=True)
    p.add_argument("--split", choices=["fit", "held"], default="fit")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    want = 0 if args.split == "fit" else 1

    prior_all = list(prior_rows(args.forms, args.split))
    log("treebank elided tokens for the prior", len(prior_all),
        "of which gold-work", sum(1 for r in prior_all if r[2]))

    class A:
        pass
    a = A()
    a.index, a.forms = args.index, args.forms
    rows, _ = cal.align(a)
    train = [r for r in rows if half(r[0]) == want and r[6]]
    log("aligned gold tokens in the training half", len(train), "elided", sum(1 for r in train if is_elided(r[6])))

    from backend.lemma_index import LemmaIndex
    ix = LemmaIndex(args.index)
    readings, freq, cls_of, lemma_pos = index_tables(args.index)
    corpus = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    st = sqlite3.connect(f"file:{args.build}?mode=ro", uri=True)
    form_of = {r[0]: r[1] for r in ix.con().execute("SELECT id, form FROM form")}
    by_pid = defaultdict(list)
    for r in train:
        by_pid[r[7]].append(r)
    feat_rows, cases = [], []   # (lemma key, class, feats) / (form, gold key, feats, block)
    for pid, toks in by_pid.items():
        row = corpus.execute("SELECT rowid, text FROM passages WHERE id=?", (ix.pid_id[pid],)).fetchone()
        if not row:
            continue
        rowid, text = row
        tokens = word_tokens(text)
        c = st.execute("SELECT preds FROM context WHERE rowid_=?", (rowid,)).fetchone()
        pred_at = {pp[0]: pp for pp in json.loads(c[0])} if c else {}
        fids = ix.tokens(pid)[1]
        for r in toks:
            i = r[8]
            if i >= len(tokens):
                continue
            form = form_of.get(int(fids[i]), "")
            elided = is_elided(form)
            feats = token_features(text, tokens, i, pred_at)
            gk = model_key(r[5])
            feat_rows.append((gk, cls_of.get(fold(gk), "unknown"), feats, r[0], elided))
            if elided:
                cases.append((form, gk, feats, r[0]))
    values = {f: sorted({fr[2][f] for fr in feat_rows}) for f in FEATURES}
    log("feature rows", len(feat_rows))

    # parameter choice on a second split inside the training half
    sub_prior = [(f, l) for f, l, b in prior_all if b is None or sub_half(b) == 0]
    sub_feats = [(l, c, f, e) for l, c, f, b, e in feat_rows if sub_half(b) == 0]
    sub_cases = [(f, g, ft) for f, g, ft, b in cases if sub_half(b) == 1]
    grid = []
    for alpha in (1.0, 3.0, 10.0, 30.0):
        for beta in (3.0, 10.0, 30.0):
            for tau in (0.0, 0.5, 0.75, 1.0):
                model = build_model(sub_prior, sub_feats, {"alpha": alpha, "beta": beta, "tau": tau}, values)
                acc, n = accuracy(model, sub_cases, readings, freq, lemma_pos)
                grid.append({"alpha": alpha, "beta": beta, "tau": tau, "accuracy": round(acc, 4), "tokens": n})
    best = max(grid, key=lambda g: (g["accuracy"], g["tau"] > 0))
    log("parameter choice", best)
    params = {k: best[k] for k in ("alpha", "beta", "tau")}
    model = build_model([(f, l) for f, l, _ in prior_all], [(l, c, f, e) for l, c, f, _, e in feat_rows], params, values)
    model.update({
        "version": "melos-elision-model-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "split": args.split, "index": args.index,
        "train": {"prior_tokens": len(prior_all), "prior_gold_work_tokens": sum(1 for r in prior_all if r[2]),
                  "feature_tokens": len(feat_rows), "feature_tokens_elided": len(cases), "spellings": len(model["prior"])},
        "parameter_search": {"chosen": best, "grid": grid},
        "method": ("Naive Bayes over the readings of an elided spelling: prior = treebank train counts smoothed "
                   "toward the restored spellings' corpus frequency mixed with the parser ranking (alpha); "
                   "features = own part of speech (elided tokens) and previous/next part of speech and clause "
                   "position (every token of the headword), from the contextual model, learnt per headword and backed off to its part of speech (beta), weighted "
                   "by tau; theta/phi/chi read as tau/pi/kappa only before a rough breathing."),
    })
    Path(args.out).write_text(json.dumps(model, ensure_ascii=False) + "\n", encoding="utf-8")
    log("written", args.out)


if __name__ == "__main__":
    main()
