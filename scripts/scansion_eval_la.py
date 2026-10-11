#!/usr/bin/env python3
"""Score the Latin scanner against the Hypotactic Latin gold (docs/prd/latin-composer.md §4.4).

Per syllable (line-final unit excluded): decided = p_long <= 0.1 or >= 0.9; accuracy on decided; share ambiguous;
Brier; elision accuracy (gold E vs the unit's elision >= 0.5). Per line: the metre fit (ok without overruling a
unit; best pattern equal to the gold pattern), and the negative control (perturbed lines: false-accept rate).
Alignment: the scanner's units must match the gold syllable count; lines that do not align are reported, not scored.

Usage: python scripts/scansion_eval_la.py [--split dev|held_out|all] [--metre hendecasyllables] [--template phalaecian]
       [--fold-v] [--lexicon] [--out docs/latin/eval/NAME.json] [--errors N]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scansion import gold_la, metre  # noqa: E402
from backend.scansion.quantity_la import LatinScanner  # noqa: E402

TEMPLATE_FOR = {"hendecasyllables": "phalaecian", "hexameter": "hexameter", "sapadon": "sapphic", "scazon": "choliambic",
                "ia6g": "iambic_trimeter_pure", "elegy": "elegiac", "glycpher": None, "alcaic": "alcaic_horace",
                "sapphic2": "sapphic_horace"}
# Poems where the decasyllabic variant is allowed beside the hendecasyllable (PRD §4.5: a per-line alternative)
DECASYLLABLE_POEMS = {("catullus", "55"), ("catullus", "58b")}


def best_fit(units, template: str, g):
    """The line's fit; for 55 and 58b the better of the two Phalaecian templates (both are allowed there)."""
    f = metre.fit_line(units, template)
    if template == "phalaecian" and (g.work, g.poem) in DECASYLLABLE_POEMS:
        alt = metre.fit_line(units, "phalaecian_decasyllable")
        if (alt.ok and not f.ok) or (alt.ok == f.ok and alt.log_likelihood > f.log_likelihood):
            return alt
    return f


def fold_v(text: str) -> str:
    return text.replace("v", "u").replace("V", "U").replace("j", "i").replace("J", "I")


def score(lines, sc: LatinScanner, template: str | None, fold: bool, perturb_seed: int = 7):
    n_units = decided = right = 0
    brier = 0.0
    amb_rules = Counter()
    err_rules = Counter()
    errors = []
    eli_total = eli_right = 0
    hiatus_gold = Counter()
    fits = Counter()
    misaligned = []
    bands = Counter()
    band_long = Counter()
    decided_by = Counter()      # what decided the unit: position | finals_and_lists | lexicon | diphthong_mono | other
    rule_n = Counter()          # per (unit rule, vowel rule): units and gold-long units, for the measured shares
    rule_long = Counter()
    flag_n = Counter()          # per flag id: candidates and how often the flagged phenomenon happened in the gold
    flag_yes = Counter()
    rng = random.Random(perturb_seed)
    neg = Counter()
    for g in lines:
        text = fold_v(g.plain) if fold else g.plain
        units = sc.scan(text)
        if len(units) != len(g.lengths):
            misaligned.append((g.id, len(units), len(g.lengths), g.plain, "".join(g.lengths)))
            continue
        for u, q, f in zip(units[:-1], g.lengths[:-1], g.flags[:-1]):
            # Hypotactic writes prodelision as elision of the syllable before est / es: count it as the same
            prod = (u.prodelision or {}).get("p", 0) >= 0.5
            if q == "E" or u.elision >= 0.5 or u.elision > 0 or prod:
                for fl in u.flags:
                    if fl["id"].startswith(("ELI-", "PROD")) and fl["id"] != "ELI-1":
                        flag_n[fl["id"]] += 1
                        flag_yes[fl["id"]] += 1 if q == "E" else 0
                        break
                if q == "E" or u.elision > 0 or prod:
                    eli_total += 1
                    pred_e = u.elision >= 0.5 or prod
                    if pred_e == (q == "E"):
                        eli_right += 1
                    elif q != "E":
                        hiatus_gold["gold hiatus, predicted elision"] += 1
                        errors.append({"id": g.id, "text": g.plain, "unit": u.text, "p": round(u.elision, 2), "gold": "kept",
                                       "rule": "ELISION", "vowel_rule": "", "flags": f})
                    else:
                        hiatus_gold["gold elision, predicted kept"] += 1
                        errors.append({"id": g.id, "text": g.plain, "unit": u.text, "p": round(u.elision, 2), "gold": "E",
                                       "rule": "ELISION", "vowel_rule": "", "flags": f})
                if q == "E":
                    continue
            n_units += 1
            p = u.p_long
            y = 1.0 if q == "L" else 0.0
            rk = f"{u.rule} / {u.vowel['rule']}"
            rule_n[rk] += 1
            rule_long[rk] += y
            for fl in u.flags:
                if fl["id"].startswith(("SYN", "IAMB", "DIAER")):
                    flag_n[fl["id"]] += 1
                    flag_yes[fl["id"]] += 1 if ("synizesis" in f or ("IAMB" in fl["id"] and q == "S")) else 0
            brier += (p - y) ** 2
            band = min(int(p * 10), 9)
            bands[band] += 1
            band_long[band] += y
            if p <= 0.1 or p >= 0.9:
                decided += 1
                vr = u.vowel["rule"]
                decided_by["position" if u.rule.startswith(("POS", "INIT-DOUBLE")) else
                           "lexicon" if vr.startswith("LEX") else
                           "diphthong_or_monosyllable" if vr.startswith(("DIPH", "MONO", "TYPED")) else
                           "finals_and_lists" if vr.startswith(("FIN", "ENCL", "VAV")) else "other"] += 1
                ok = (p >= 0.9) == (q == "L")
                if ok:
                    right += 1
                else:
                    err_rules[(u.rule, u.vowel["rule"])] += 1
                    errors.append({"id": g.id, "text": g.plain, "unit": u.text, "p": round(p, 2), "gold": q,
                                   "rule": u.rule, "vowel_rule": u.vowel["rule"], "flags": f})
            else:
                amb_rules[(u.rule, u.vowel["rule"])] += 1
        if template:
            fit = best_fit(units, template, g)
            fits["lines"] += 1
            fits["parsed"] += fit.log_likelihood > float("-inf")
            fits["ok"] += fit.ok
            same = fit.pattern[:-1] == g.pattern[:-1]            # the line-final unit is anceps: not compared
            fits["pattern_match"] += same
            if fit.ok and not same:
                fits["ok_but_wrong_pattern"] += 1
            if not fit.ok:
                errors.append({"id": g.id, "text": g.plain, "unit": "", "p": None, "gold": g.pattern, "rule": "LINE-REJECTED",
                               "vowel_rule": fit.message, "flags": [v.get("text") + ":" + v.get("needs") for v in fit.violations][:4]})
            # negative control: swap two random words (changes position/elision), or replace one word by a word
            # from another gold line of a different syllable pattern; a scanner that accepts everything fails here
            words = text.split()
            if len(words) >= 3:
                i, j = rng.sample(range(len(words)), 2)
                swapped = list(words)
                swapped[i], swapped[j] = swapped[j], swapped[i]
                pf = best_fit(sc.scan(" ".join(swapped)), template, g)
                neg["swap_total"] += 1
                neg["swap_accepted"] += pf.ok
                other = rng.choice(lines)
                ow = [w for w in other.words if w["pat"] and w["pat"] != g.words[i % len(g.words)]["pat"]]
                if ow and len(words) == len(g.words):
                    k = rng.randrange(len(words))
                    repl = list(words)
                    repl[k] = fold_v(ow[rng.randrange(len(ow))]["form"]) if fold else ow[rng.randrange(len(ow))]["form"]
                    repl[k] = "".join(ch for ch in __import__("unicodedata").normalize("NFD", repl[k]) if ch not in "̄̆")
                    pf = best_fit(sc.scan(" ".join(repl)), template, g)
                    neg["replace_total"] += 1
                    neg["replace_accepted"] += pf.ok
    out = {
        "lines": len(lines), "misaligned": len(misaligned), "units_scored": n_units,
        "decided": decided, "decided_share": round(decided / max(n_units, 1), 4),
        "accuracy_on_decided": round(right / max(decided, 1), 4), "ambiguous_share": round(1 - decided / max(n_units, 1), 4),
        "brier": round(brier / max(n_units, 1), 4),
        "elision": {"candidates": eli_total, "right": eli_right, "accuracy": round(eli_right / max(eli_total, 1), 4),
                    "confusions": dict(hiatus_gold)},
        "fit": dict(fits), "negative_control": dict(neg),
        "decided_by": {k: {"units": v, "share_of_scored": round(v / max(n_units, 1), 4)} for k, v in decided_by.most_common()},
        "rule_shares": {k: {"n": v, "long": round(rule_long[k] / v, 3)} for k, v in rule_n.most_common() if v >= 5},
        "flag_shares": {k: {"n": v, "happened": round(flag_yes[k] / v, 3)} for k, v in flag_n.most_common()},
        "calibration": {f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": bands[b], "observed_long": round(band_long[b] / bands[b], 3)}
                        for b in sorted(bands)},
        "ambiguous_by_rule": [[f"{k[0]} / {k[1]}", v] for k, v in amb_rules.most_common(12)],
        "errors_by_rule": [[f"{k[0]} / {k[1]}", v] for k, v in err_rules.most_common(12)],
        "misaligned_lines": [{"id": a, "units": b, "gold": c, "text": d, "gold_q": e} for a, b, c, d, e in misaligned],
        "errors": errors,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "held_out", "all"])
    ap.add_argument("--work", default="catullus")
    ap.add_argument("--metre", default="hendecasyllables")
    ap.add_argument("--template", default=None)
    ap.add_argument("--fold-v", action="store_true")
    ap.add_argument("--lexicon", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--errors", type=int, default=40)
    args = ap.parse_args()
    lines = gold_la.load(work=args.work, metre=args.metre)
    if args.split != "all":
        lines = [g for g in lines if g.split == args.split]
    template = args.template or TEMPLATE_FOR.get(args.metre)
    spelling = "u" if args.fold_v else "uv"          # Hypotactic writes v and j throughout; folded = the owner's u/i typing
    sc = LatinScanner(spelling=spelling)
    if args.lexicon:
        from backend.scansion.lexicon_la import LatinQuantityLexicon
        sc = LatinScanner(lexicon=LatinQuantityLexicon(), spelling=spelling)
    t0 = time.perf_counter()
    res = score(lines, sc, template, args.fold_v)
    res["ms_per_line"] = round((time.perf_counter() - t0) * 1000 / max(len(lines), 1), 2)
    res["setting"] = {"split": args.split, "work": args.work, "metre": args.metre, "template": template,
                      "fold_v": args.fold_v, "lexicon": args.lexicon, "params": sc.grammar.params}
    summary = {k: v for k, v in res.items() if k not in ("errors", "misaligned_lines", "ambiguous_by_rule", "errors_by_rule", "calibration", "setting")}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("ambiguous by rule:", res["ambiguous_by_rule"][:8])
    print("errors by rule:", res["errors_by_rule"][:8])
    for m in res["misaligned_lines"][:8]:
        print("MISALIGNED", m["id"], m["units"], "vs", m["gold"], "|", m["text"], "|", m["gold_q"])
    for e in res["errors"][:args.errors]:
        print("ERR", e["id"], e["unit"], e["p"], "gold", e["gold"], e["rule"], e["vowel_rule"], e["flags"], "|", e["text"])
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
