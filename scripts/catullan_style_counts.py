#!/usr/bin/env python3
"""Every number in docs/latin/catullan-style-rubric.md, counted again.

    .venv/bin/python scripts/catullan_style_counts.py            # the report, section by section as in the rubric
    .venv/bin/python scripts/catullan_style_counts.py --json     # the same as JSON

Counts Catullus's hendecasyllabic poems with the code L5 and L6 run (backend/latin_style.py): lines and metre from
the Hypotactic gold, lemma / part of speech / features from the LASLA rows of data/lemma_index_la.sqlite, printed
text from data/corpus_la.sqlite, diminutives by Lewis & Short. WORDS below is a list of lemmas to look up, not a
judgement: the table prints whatever the index holds for each.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import latin_style as ls  # noqa: E402

AUTHOR, METRE = "Catullus", "phalaecian"
ENCLITIC_LEMMAS = ("que", "ne", "ue")
WORDS = ("bellus", "delicia", "uenustus", "basium", "basio", "lepidus", "elegans", "urbanus", "ineptus", "delicatus",
         "salsus", "sauium", "osculum", "facetus", "illepidus", "inuenustus", "insulsus", "inelegans")


def groups() -> dict:
    lines, poems = ls._corpus(AUTHOR)["lines"], ls._metre_poems(AUTHOR, METRE)
    return {"hendecasyllables": [l for l in lines if l["poem"] in poems],
            "other polymetrics": [l for l in lines if l["poem"] <= 60 and l["poem"] not in poems],
            "long poems 61-68": [l for l in lines if 61 <= l["poem"] <= 68],
            "epigrams 69-116": [l for l in lines if l["poem"] >= 69]}


def by_poem(lines: list[dict]) -> dict:
    out = defaultdict(list)
    for l in lines:
        out[l["pid"]].append(l)
    return out


def marker_rates(lines: list[dict]) -> dict:
    total = Counter()
    for poem in by_poem(lines).values():
        total.update(ls._marker_counts(poem)[0])
    return {m: ls._rate(total[m], total["printed lines"] if m == "run-on lines" else len(lines)) for m in ls.MARKERS} | {
        "lines": len(lines), "printed lines": total["printed lines"], "counts": {m: total[m] for m in ls.MARKERS}}


def shape(lines: list[dict]) -> dict:
    poems = by_poem(lines)
    key = lambda l: tuple(t[0] for t in l["toks"])
    voc = lambda l: any("Case=Voc" in t[3] for t in l["toks"])
    second = lambda l: any(ls._SECOND.search(t[3]) for t in l["toks"])
    no = lambda p: p[0]["poem"]
    lengths = sorted(len(p) for p in poems.values())
    repeats = {no(p): sum(n - 1 for n in Counter(key(l) for l in p).values() if n > 1) for p in poems.values()}
    return {"poems": len(poems), "lines": len(lines), "tokens": sum(len(l["toks"]) for l in lines),
            "length_min": lengths[0], "length_max": lengths[-1], "length_median": statistics.median(lengths),
            "vocative_line_1": sum(voc(p[0]) for p in poems.values()),
            "vocative_lines_1_2": sum(any(voc(l) for l in p[:2]) for p in poems.values()),
            "vocative_anywhere": sum(any(voc(l) for l in p) for p in poems.values()),
            "second_person_anywhere": sum(any(second(l) for l in p) for p in poems.values()),
            "first_line_is_last": sorted(no(p) for p in poems.values() if len(p) > 1 and key(p[0]) == key(p[-1])),
            "line_repeated": {k: v for k, v in sorted(repeats.items()) if v},
            "first_last_share_content_lemma": sorted(no(p) for p in poems.values() if len(p) > 1 and set(p[0]["content"]) & set(p[-1]["content"]))}


def last(line: dict) -> tuple:
    """The line's last word: an enclitic (-que, -ne, -ue is its own token in the index) is passed over."""
    words = [t for t in line["toks"] if t[1] not in ENCLITIC_LEMMAS] or line["toks"]
    return words[-1]


def line_ends(lines: list[dict]) -> dict:
    label = ls.GOLD_METRE[METRE]
    gold = [r for r in ls._gold() if r["author"] == AUTHOR and r["metre"] == label and r.get("words")]
    return {"gold_lines": len(gold),
            "final_word_syllables": dict(sorted(Counter(len(r["words"][-1]["syl"]) for r in gold).items())),
            "final_upos": Counter(last(l)[2] for l in lines if l["toks"]).most_common(),
            "final_lemmas": Counter(last(l)[1] for l in lines if l["toks"]).most_common(12),
            "opening_forms": Counter(l["toks"][0][0] for l in lines if l["toks"]).most_common(9)}


def diminutive_counts(g: dict) -> dict:
    rows = ls.diminutives(AUTHOR, METRE)
    pos = ls._positions(AUTHOR, METRE)
    starts, final = Counter(), 0
    for lemma, _base, _n, _how in rows:
        starts.update(pos["lemma"].get(lemma, Counter()))
        final += pos["lemma_final"][lemma]
    out = {"lemmas": rows, "tokens": sum(r[2] for r in rows), "by_suffix": [r[0] for r in rows if r[3] == "by suffix"],
           "start_syllables": dict(sorted(starts.items())), "placed": sum(starts.values()), "line_final": final,
           "profile": ls.marker_profile(AUTHOR, METRE)["markers"]["diminutives"], "by_group": {}}
    for name, lines in g.items():
        dim = sum(1 for l in lines for t in l["toks"] if t[2] in ("NOUN", "ADJ") and ls.diminutive_info(t[1]))
        puella = sum(1 for l in lines for t in l["toks"] if t[1] == "puella")
        out["by_group"][name] = {"lines": len(lines), "diminutives": dim, "per_100": ls._rate(dim, len(lines)),
                                 "puella": puella, "per_100_with_puella": ls._rate(dim + puella, len(lines))}
    return out


def vocabulary(g: dict) -> dict:
    mine, horace = ls._lemma_counts(AUTHOR, METRE), ls._lemma_counts("Horace", METRE)
    later = Counter(t[1] for name in ("long poems 61-68", "epigrams 69-116") for l in g[name] for t in l["toks"])
    content = Counter(t[1] for l in g["hendecasyllables"] for t in l["toks"] if t[2] in ls.CONTENT_UPOS)
    table = {w: {"polymetrics": mine.get(w, Counter())["polymetrics"], "hendecasyllables": mine.get(w, Counter())["metre"],
                 "long poems": mine.get(w, Counter())["long poems"], "epigrams": mine.get(w, Counter())["epigrams"],
                 "catullus": mine.get(w, Counter())["total"], "horace": horace.get(w, Counter())["total"]} for w in WORDS}
    return {"table": table,
            "hendeca_3plus_never_in_horace": [(w, n) for w, n in content.most_common() if n >= 3 and not horace.get(w, Counter())["total"] and ls._lemma_upos(w) != "PROPN"],
            "hendeca_4plus_none_in_61_116": [(w, n) for w, n in content.most_common() if n >= 4 and not later[w]]}


def counts() -> dict:
    g = groups()
    h = g["hendecasyllables"]
    intj = Counter(t[0] for l in h for t in l["toks"] if t[2] == "INTJ")
    return {"1 shape": shape(h), "2-3-8 markers (hendecasyllables, per poem spread)": ls.marker_profile(AUTHOR, METRE)["markers"],
            "2 interjections": intj.most_common(), "2 by group per 100 lines": {k: marker_rates(v) for k, v in g.items()},
            "4 diminutives": diminutive_counts(g), "5 vocabulary": vocabulary(g), "6-7 line openings and ends": line_ends(h),
            "9 collocation baseline": {k: v for k, v in ls.collocation_baseline(AUTHOR, METRE).items() if not isinstance(v, (list, dict))}}


def show(value, indent: int = 2) -> None:
    pad = " " * indent
    if isinstance(value, dict) and any(isinstance(v, (dict, list)) for v in value.values()):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and len(json.dumps(v, ensure_ascii=False, default=str)) > 110:
                print(f"{pad}{k}:")
                show(v, indent + 2)
            else:
                print(f"{pad}{k}: {json.dumps(v, ensure_ascii=False, default=str)}")
    elif isinstance(value, list) and value and isinstance(value[0], (list, tuple)):
        line = ", ".join(" ".join(str(x) for x in row if x != "") for row in value)
        print(pad + line)
    else:
        print(pad + json.dumps(value, ensure_ascii=False, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not ls.available() or not ls.gold_path().exists():
        print("catullan_style_counts: the Latin corpus, the lemma index or the Hypotactic gold is not built", file=sys.stderr)
        return 2
    result = counts()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        return 0
    for title, value in result.items():
        print(f"\n== {title}")
        show(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
