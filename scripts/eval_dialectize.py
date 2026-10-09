"""Release U: measure the reverse dialect generator (backend/dialectize.py) on the lyric gold set.

From certain gold tokens of Sappho and Alcaeus whose printed form is a citation form of the gold headword (nominative
singular of a noun or adjective of the headword's gender, 1st singular present indicative active of a verb, or the
present active infinitive of an -ω verb, where the Attic infinitive is the headword's stem + -ειν), the Attic
form is given to the generator (dialect lesbian) and we check whether the printed Lesbian spelling is among the
accepted candidates. Recall is reported over tokens whose printed spelling differs from the Attic one; the other
accepted candidates are listed for a hand audit.

    python scripts/eval_dialectize.py --gold data/evaluation/lyric-gold-r.json --out dialectize-eval.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.dialectize import get_dialectizer, key  # noqa: E402

EXAMPLES = [("τηλόθεν", "lesbian", "πήλοθεν"), ("σελήνη", "lesbian", "σελάννα"), ("ἥλιος", "lesbian", "ἀέλιος"),
            ("ἥλιος", "doric", "ἅλιος"), ("φέρουσα", "lesbian", "φέροισα"), ("ἄγειν", "lesbian", "ἄγην"),
            ("μόνος", "lesbian", "μόνα"), ("χώρα", "ionic", "χώρη"), ("μόνος", "ionic", "μοῦνος"),
            ("θυμός", "lesbian", "θῦμος"), ("εἰμί", "lesbian", "ἔμμι"), ("Μοῦσα", "lesbian", "Μοῖσα"),
            ("ἐκεῖνος", "lesbian", "κῆνος"), ("ὅτε", "doric", "ὅκα")]


def nfc(s):
    return unicodedata.normalize("NFC", s)


def attic_form(tok):
    lemma, parse, printed = tok["lemma"], tok.get("parse") or "", tok["printed"]
    if any(ch in printed for ch in "[]’᾽'ʼ") or not lemma or " " in lemma:
        return None
    p = parse.split()
    if any(ch in unicodedata.normalize("NFD", printed) for ch in ()) or sum(
            unicodedata.normalize("NFD", printed).count(m) for m in "́͂̀") > 1:
        return None  # an enclitic's accent on the host (ἐνάντιός) is not a dialect spelling
    if ("noun" in p or "adj" in p) and "nom" in p and "sg" in p and not ({"comp", "superl", "neut"} & set(p)):
        if "adj" in p and "fem" in p and not key(lemma).endswith("ος"):
            return None
        if "adj" in p and "masc" not in p and "fem" not in p:
            return None
        return lemma  # an adjective's feminine is asked for by the masculine headword (rule "feminine")
    if "verb" in p and "1st" in p and "sg" in p and "pres" in p and "ind" in p and "act" in p:
        return lemma
    if "verb" in p and "inf" in p and "pres" in p and "act" in p and lemma.endswith("ω"):
        return lemma[:-1] + "ειν"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/evaluation/lyric-gold-r.json")
    ap.add_argument("--out", default="")
    ap.add_argument("--machine-state", default="", help="writable machine-morphology cache (MELOS_MACHINE_STATE)")
    args = ap.parse_args()
    if args.machine_state:
        import os
        os.environ["MELOS_MACHINE_STATE"] = args.machine_state
    dz = get_dialectizer()
    report = {"examples": [], "gold": []}
    t0 = time.perf_counter()
    dz.index.index
    t1 = time.perf_counter()
    dz.index.dialect_of_pid()
    t2 = time.perf_counter()
    sizes = [len(dz.index.dialect_forms(code)) for code in (1, 2)]
    t3 = time.perf_counter()
    report["cold"] = {"index_load_s": round(t1 - t0, 2), "dialect_table_s": round(t2 - t1, 2),
                      "spelling_tables_s": round(t3 - t2, 2), "lesbian_doric_spellings": sizes}
    fresh = ["καρδία", "ψυχή", "νύξ", "κόρη", "φωνή", "ἐρχομένη", "λέγουσα", "ἔχειν", "ζυγόν", "ὑμεῖς"]
    t4 = time.perf_counter()
    report["batch10_uncached"] = {"lesbian_ms": dz.dialectize(fresh, "lesbian")["ms"],
                                  "all_ms": dz.dialectize([f + "" for f in fresh[::-1]], "all")["ms"]}
    print("10 fresh forms", report["batch10_uncached"], flush=True)
    print("cold", report["cold"], flush=True)
    for form, dialect, want in EXAMPLES:
        r = dz.dialectize([form], dialect)
        forms = [c["form"] for c in r["results"][0]["candidates"]]
        report["examples"].append({"input": form, "dialect": dialect, "expected": want, "found": nfc(want) in forms,
                                   "accepted": [(c["form"], c["verdict"], [x["id"] for x in c["rules"]])
                                                for c in r["results"][0]["candidates"]], "ms": r["ms"]})
        print(form, dialect, want, nfc(want) in forms, r["ms"], "ms", forms[:6], flush=True)
    batch = ["σελήνη", "τηλόθεν", "ἥλιος", "θυμός", "μόνος", "εὕδω", "ἡμέρα", "φέρουσα", "ἄγειν", "κῆρυξ"]
    timings = []
    for _ in range(3):
        timings.append(dz.dialectize(batch, "lesbian")["ms"])
    report["batch10_lesbian_ms"] = timings
    report["batch10_all_ms"] = dz.dialectize(batch, "all")["ms"]
    print("10 forms lesbian ms", timings, "all dialects ms", report["batch10_all_ms"], flush=True)
    gold = json.load(open(args.gold, encoding="utf-8"))["tokens"]
    seen = set()
    for tok in gold:
        if tok.get("uncertain") or not any(a in tok["passage_id"] for a in ("sappho", "alcaeus")):
            continue
        attic = attic_form(tok)
        if not attic:
            continue
        pair = (nfc(attic), nfc(tok["printed"]))
        if pair in seen:
            continue
        seen.add(pair)
        differs = pair[0] != pair[1] and key(pair[0]) != key(pair[1].lower()) or pair[0] != pair[1]
        if pair[0].lower() == pair[1].lower():
            differs = False
        r = dz.dialectize([pair[0]], "lesbian")
        cands = r["results"][0]["candidates"]
        forms = [c["form"] for c in cands]
        report["gold"].append({"attic": pair[0], "printed": pair[1], "parse": tok["parse"], "differs": differs,
                               "recovered": pair[1] in forms or pair[1].lower() in [f.lower() for f in forms],
                               "accepted": [(c["form"], c["verdict"]) for c in cands], "ms": r["ms"]})
    diff = [g for g in report["gold"] if g["differs"]]
    same = [g for g in report["gold"] if not g["differs"]]
    times = sorted(g["ms"] for g in report["gold"])
    report["summary"] = {
        "examples_found": sum(e["found"] for e in report["examples"]), "examples": len(report["examples"]),
        "gold_pairs": len(report["gold"]), "gold_differs": len(diff),
        "recovered_differs": sum(g["recovered"] for g in diff),
        "same_spelling_pairs": len(same),
        "same_spelling_with_candidates": sum(bool(g["accepted"]) for g in same),
        "accepted_total": sum(len(g["accepted"]) for g in report["gold"]),
        "ms_median": times[len(times) // 2] if times else None, "ms_p90": times[int(len(times) * 0.9)] if times else None,
        "wall_s": round(time.perf_counter() - t0, 1)}
    print(json.dumps(report["summary"], ensure_ascii=False))
    for g in diff:
        print("DIFF", "OK " if g["recovered"] else "MISS", g["attic"], "->", g["printed"], g["parse"], "|",
              ", ".join(f"{f}:{v[:8]}" for f, v in g["accepted"][:6]))
    for g in same:
        if g["accepted"]:
            print("SAME", g["attic"], "|", ", ".join(f"{f}:{v[:8]}" for f, v in g["accepted"][:6]))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
