#!/usr/bin/env python3
"""Count Catullus's Phalaecian manner from every hendecasyllable in the Hypotactic hand scansion
(data/open/latin/hypotactic/lines.jsonl.gz, David Chamberlain, CC BY 4.0) and write
data/open/latin/phalaecian-profile/profile.json + manifest.json for backend/latin_metre_style.py (L13, L8).

Every number is a count from the gold; the features are read by backend.latin_metre_style.line_features, the same
reader the checks use on a draft. Denominators: `lines` = lines of 10 or 11 sounded syllables (base, elision,
line-end word); `hendecasyllables` = lines of 11 (word-ends and the main break: the decasyllable's positions differ).
A feature is rare when it stands in under RARE of its denominator; rare features keep up to 5 loci.

Usage: python scripts/build_phalaecian_profile.py [--out data/open/latin/phalaecian-profile]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import latin_metre_style as style  # noqa: E402
from backend.scansion import gold_la  # noqa: E402

RARE = 0.02          # the task's threshold: a feature in under 2 % of the lines it could stand in
MAX_LOCI = 5


def poem_key(p: str):
    m = re.match(r"(\d+)(.*)", p)
    return (int(m.group(1)), m.group(2)) if m else (0, p)


def share(n: int, of: int) -> float:
    return round(n / of, 4) if of else 0.0


def table(counter: Counter, of: int, order=None) -> dict:
    keys = order if order is not None else sorted(counter, key=lambda k: (-counter[k], str(k)))
    return {str(k): {"n": counter[k], "of": of, "share": share(counter[k], of)} for k in keys}


def build() -> dict:
    gold = gold_la.load(work="catullus", metre="hendecasyllables")
    rows = [(g, style.line_features(g.words)) for g in gold]
    regular = [(g, f) for g, f in rows if f["sounded"] in (10, 11)]
    hendeca = [(g, f) for g, f in regular if f["sounded"] == 11]
    n_lines, n_h = len(regular), len(hendeca)
    locus = lambda g: f"{g.poem}.{g.line_no}"  # noqa: E731

    feat_lines, labels = defaultdict(list), {}
    for g, f in regular:
        for k, label in f["keys"]:
            feat_lines[k].append(locus(g))
            labels[k] = label
    features = {}
    for k in sorted(feat_lines):
        of = n_h if k.startswith(("word_end:", "break:")) else n_lines
        n = len(feat_lines[k])
        rare = n / of < RARE
        features[k] = {"label": labels[k], "lines": n, "of": of, "share": share(n, of), "rare": rare,
                       "loci": feat_lines[k][:MAX_LOCI] if rare else []}

    base_all = Counter(f["base"] for _, f in regular)
    by_poem = defaultdict(Counter)
    for g, f in regular:
        by_poem[g.poem][f["base"]] += 1
    base_order = [b for b in ("spondee", "trochee", "iamb", "pyrrhic", "other") if base_all[b]]

    we, we_el = Counter(), Counter()
    for _, f in hendeca:
        we.update(f["word_ends"])
        we_el.update(f["word_ends"] + f["word_ends_elided"])
    brk = Counter(f["break"] for _, f in hendeca)
    brk_el = Counter(f["break_with_elision"] for _, f in hendeca)

    el_per_line = Counter(len(f["elisions"]) for _, f in regular)
    el_at, el_kind, mono = Counter(), Counter(), defaultdict(list)
    n_el = 0
    for g, f in regular:
        for e in f["elisions"]:
            n_el += 1
            el_at[e["at"]] += 1
            el_kind[e["kind"]] += 1
            if e["monosyllable"]:
                mono[style._letters(e["word"])].append(locus(g))
    prod = [(g, e) for g, f in regular for e in f["prodelisions"]]
    hiatus = [{"locus": locus(g), "text": g.text, **h} for g, f in regular for h in f["hiatus"]]
    synizesis = [{"locus": locus(g), "text": g.text, "syllable": t}
                 for g in gold for t, fl in zip(g.syllables, g.flags) if "synizesis" in fl]

    fin = Counter(f["final_word"]["syllables"] for _, f in regular)
    mono_end = [{"locus": locus(g), "word": f["final_word"]["form"], "text": g.text} for g, f in regular
                if f["final_word"]["syllables"] == 1]
    prod_end = [locus(g) for g, f in regular if f["final_word"]["prodelided_est"]]

    return {
        "version": 1,
        "metre": "phalaecian", "author": "Catullus",
        "source": "Hypotactic hand scansion (David Chamberlain, hypotactic.com), CC BY 4.0; metre label `hendecasyllables`",
        "rare_threshold": RARE,
        "denominators": {"gold_lines": len(gold), "lines": n_lines, "hendecasyllables": n_h,
                         "decasyllables": n_lines - n_h, "poems": len(by_poem)},
        "irregular_lines": [{"locus": locus(g), "text": g.text, "sounded": f["sounded"], "gold_q": "".join(g.lengths)}
                            for g, f in rows if f["sounded"] not in (10, 11)],
        "features": features,
        "base": {"overall": table(base_all, n_lines, base_order),
                 "by_poem": {p: {"lines": sum(c.values()), **{b: c[b] for b in base_order}}
                             for p, c in sorted(by_poem.items(), key=lambda t: poem_key(t[0]))}},
        "word_end_after": {str(k): {"n": we[k], "with_elided": we_el[k], "of": n_h, "share": share(we[k], n_h),
                                    "share_with_elided": share(we_el[k], n_h)} for k in range(1, 11)},
        "main_break": {"word_end_clear": table(brk, n_h, ["5th", "6th", "both", "neither"]),
                       "counting_word_ends_in_elision": table(brk_el, n_h, ["5th", "6th", "both", "neither"])},
        "elision": {"total": n_el, "lines_with": sum(v for k, v in el_per_line.items() if k), "of": n_lines,
                    "per_line": table(el_per_line, n_lines, sorted(el_per_line)),
                    "at_syllable": table(el_at, n_el, sorted(el_at)),
                    "kinds": table(el_kind, n_el, [k for k in style.ELIDED_KINDS if el_kind[k]]),
                    "monosyllables": {w: {"n": len(l), "loci": l[:MAX_LOCI]} for w, l in
                                      sorted(mono.items(), key=lambda t: (-len(t[1]), t[0]))},
                    "monosyllables_total": sum(len(l) for l in mono.values())},
        "prodelision": {"n": len(prod), "lines": len({locus(g) for g, _ in prod}), "of": n_lines,
                        "kinds": dict(Counter(e["kind"] for _, e in prod)),
                        "at_line_end": len(prod_end), "loci": [locus(g) for g, _ in prod][:MAX_LOCI]},
        "hiatus": hiatus,
        "synizesis": synizesis,
        "line_end": {"word_syllables": table(fin, n_lines, sorted(fin)), "monosyllabic_endings": mono_end,
                     "prodelided_est_endings": {"n": len(prod_end), "loci": prod_end[:MAX_LOCI]}},
        "decasyllable_lines": [{"locus": locus(g), "text": g.text} for g, f in regular if f["sounded"] == 10],
        "rare_features": {k: v for k, v in features.items() if v["rare"]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "open" / "latin" / "phalaecian-profile"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prof = build()
    (out / "profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
    src = gold_la.default_path()
    manifest = {"name": "phalaecian-profile", "built": date.today().isoformat(), "script": "scripts/build_phalaecian_profile.py",
                "files": {"profile.json": hashlib.sha256((out / "profile.json").read_bytes()).hexdigest()},
                "source": {"path": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
                           "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                           "attribution": "David Chamberlain, Hypotactic (hypotactic.com)", "license": "CC BY 4.0"},
                "license": "CC BY 4.0 (derived counts)", "denominators": prof["denominators"],
                "rare_threshold": prof["rare_threshold"]}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    d = prof["denominators"]
    print(json.dumps(d), "| base", {k: v["share"] for k, v in prof["base"]["overall"].items()},
          "| break", {k: v["share"] for k, v in prof["main_break"]["word_end_clear"].items()},
          "| elisions", prof["elision"]["total"], {k: v["n"] for k, v in prof["elision"]["kinds"].items()},
          "| prodelision", prof["prodelision"]["n"], "| hiatus", [(h["locus"], h["kind"]) for h in prof["hiatus"]],
          "| rare", len(prof["rare_features"]))


if __name__ == "__main__":
    main()
