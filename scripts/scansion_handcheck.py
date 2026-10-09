"""Non-hexameter check: Sappho 1 and 31, Alcaeus 346, iambic trimeter, Pindar O.1, prose.

Texts come from data/corpus.sqlite by passage id (backend/scansion/data/handcheck.json lists the ids,
the excluded corrupt lines and the few documented edits). For verse, the gold of a unit is the
length its metrical position requires: the line is aligned to its scheme (metre.fit_line, which
also finds resolutions and synizesis), positions the scheme fixes (– or ⏑, and both shorts of a
resolved long) are scored, anceps and line-final positions are not. Every disagreement is printed
so it can be checked by hand.

Pindar O.1 is scored by responsion: a position's gold is the length that a grammar rule settles
with certainty (p = 0 or 1) in at least one of the eight responding lines (4 strophes,
4 antistrophes), provided no responding line settles it the other way; then
(a) the metre-free scanner is scored on strophe 1 and antistrophe 1 against that gold, and
(b) metre.responsion(strophe 1, antistrophe 1) is scored on the units the scanner left ambiguous.

Prose: only the distribution of the longness probabilities is reported.

    python scripts/scansion_handcheck.py [--lexicon] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scansion import metre  # noqa: E402
from backend.scansion.lexicon import QuantityLexicon  # noqa: E402
from backend.scansion.quantity import Scanner  # noqa: E402

CONFIG = ROOT / "backend/scansion/data/handcheck.json"
DATA = Path(os.environ.get("MELOS_DATA_DIR", ROOT / "data"))


def corpus():
    return sqlite3.connect(f"file:{(DATA / 'corpus.sqlite').as_posix()}?mode=ro", uri=True)


def passage_text(db, pid: str, replace) -> str:
    row = db.execute("SELECT text FROM passages WHERE id=?", (pid,)).fetchone()
    if not row:
        sys.exit(f"passage {pid} not found")
    text = row[0]
    for old, new, _why in replace:
        if old not in text:
            sys.exit(f"{pid}: expected text {old!r} not found")
        text = text.replace(old, new)
    return text


def verse(sc, p, db):
    text = passage_text(db, p["passage"], p.get("replace", []))
    lines = [l for l in text.split("\n") if l.strip() and l.strip() != "===="]
    first, last = p.get("lines", [1, len(lines)])
    temps = metre.TEMPLATES[p["metre"]]
    out = {"id": p["id"], "edition": p["edition"], "metre": p["metre"], "lines": [], "scored": 0, "decided": 0,
           "correct": 0, "ambiguous": 0, "anceps_or_final_skipped": 0, "metre_fits": 0, "lines_aligned": 0,
           "auto_detect_top": Counter(), "disagreements": []}
    for no in range(first, last + 1):
        line = lines[no - 1]
        if no in p.get("exclude_lines", []):
            out["lines"].append({"line": no, "text": line, "excluded": p.get("exclude_reason", {}).get(str(no), "")})
            continue
        template = temps[(no - 1) % len(temps)]
        units = sc.scan(line)
        fit = metre.fit_line(units, p["metre"], template)
        auto = metre.auto([units], top=3)
        out["auto_detect_top"][auto[0]["metre"] if auto else "none"] += 1
        row = {"line": no, "text": line, "units": len(units), "fit": fit.ok, "pattern": fit.pattern,
               "scanner": "".join({"L": "–", "S": "⏑", "A": "?"}[u.label] for u in units)}
        if fit.log_likelihood == float("-inf"):
            row["aligned"] = False
            row["message"] = fit.message
            out["lines"].append(row)
            continue
        out["lines_aligned"] += 1
        out["metre_fits"] += int(fit.ok)
        if not fit.ok:
            # the line does not fit its scheme without overruling the scanner, so the alignment of
            # units to positions is unreliable: report it, do not score it
            row["not_scored"] = fit.message + "; " + "; ".join(f"{v['text']} needs {v['needs']}" for v in fit.violations)
            out["lines_not_scored"] = out.get("lines_not_scored", 0) + 1
            out["lines"].append(row)
            continue
        by_index = {u.index: u for u in units}
        for a in fit.assignment:
            if a.get("synizesis") or a["symbol"] in "xXF":
                out["anceps_or_final_skipped"] += len(a["syllables"])
                continue
            u = by_index[a["syllables"][0]]
            gold = "S" if a["symbol"] in "DRX" and _is_resolved(fit, a) else ("L" if a["symbol"] in "-DR" else "S")
            out["scored"] += 1
            if u.label == "A":
                out["ambiguous"] += 1
            else:
                out["decided"] += 1
                if u.label == gold:
                    out["correct"] += 1
                else:
                    out["disagreements"].append({"line": no, "unit": u.text, "gold": gold, "scanner": u.label,
                                                 "p_long": round(u.p_long, 3), "rule": u.rule,
                                                 "vowel_rule": u.vowel["rule"]})
        out["lines"].append(row)
    out["auto_detect_top"] = dict(out["auto_detect_top"])
    return out


def _is_resolved(fit, a) -> bool:
    """True when this assignment is one of two shorts filling one position."""
    same = [b for b in fit.assignment if b["position"] == a["position"]]
    return len(same) == 2


def pindar(sc, p, db):
    def line(cit):
        row = db.execute("SELECT text FROM passages WHERE id LIKE ? AND citation=?",
                         (p["work_prefix"] + "%", f"1.{cit}")).fetchone()
        return row[0]
    groups = [[sc.scan(line(s + k)) for s in p["strophes"] + p["antistrophes"]] for k in range(p["length"])]
    res = {"id": p["id"], "edition": p["edition"], "positions": 0, "gold_positions": 0, "conflicting_positions": 0,
           "layer1": Counter(), "responsion": Counter(), "lines_with_unequal_units": 0, "disagreements": []}
    s1 = [g[0] for g in groups]
    a1 = [g[4] for g in groups]
    resp = metre.responsion(s1, a1)
    for k, versions in enumerate(groups):
        n = Counter(len(v) for v in versions).most_common(1)[0][0]
        same = [v for v in versions if len(v) == n]
        if len(same) < len(versions):
            res["lines_with_unequal_units"] += 1
        for i in range(n):
            res["positions"] += 1
            certain = {("L" if v[i].p_long == 1.0 else "S") for v in same if v[i].p_long in (0.0, 1.0)}
            if len(certain) != 1:
                if len(certain) == 2:
                    res["conflicting_positions"] += 1
                continue
            gold = certain.pop()
            res["gold_positions"] += 1
            for side, post in ((0, resp[k]["strophe_posterior"]), (4, resp[k]["antistrophe_posterior"])):
                v = versions[side]
                if len(v) != n:
                    continue
                u = v[i]
                if u.label == "A":
                    res["layer1"]["ambiguous"] += 1
                    pr = post[i] if i < len(post) else None
                    if pr is None:
                        continue
                    lab = "L" if pr >= 0.9 else "S" if pr <= 0.1 else "A"
                    res["responsion"]["ambiguous_after" if lab == "A" else ("resolved_right" if lab == gold else "resolved_wrong")] += 1
                else:
                    res["layer1"]["right" if u.label == gold else "wrong"] += 1
                    if u.label != gold:
                        res["disagreements"].append({"line": k + 1, "side": "strophe" if side == 0 else "antistrophe",
                                                     "unit": u.text, "gold": gold, "scanner": u.label, "rule": u.rule})
    res["layer1"] = dict(res["layer1"])
    res["responsion"] = dict(res["responsion"])
    res["strophe_1_vs_antistrophe_1"] = [{"line": r["line"], "strophe": r["strophe_pattern"],
                                          "antistrophe": r["antistrophe_pattern"], "mismatches": len(r["mismatches"])}
                                         for r in resp if r.get("line") is not None]
    return res


def prose(sc, p, db):
    text = passage_text(db, p["passage"], [])
    units = sc.scan(text)
    bands = Counter()
    rules = Counter()
    for u in units:
        bands["certain long (1.0)" if u.p_long == 1 else "certain short (0.0)" if u.p_long == 0 else
              "likely long (≥0.9)" if u.p_long >= .9 else "likely short (≤0.1)" if u.p_long <= .1 else "ambiguous"] += 1
        if u.label == "A":
            rules[u.rule if u.rule not in ("NATURE", "CONS-VOW") else u.vowel["rule"]] += 1
    return {"id": p["id"], "edition": p["edition"], "units": len(units), "bands": dict(bands),
            "ambiguous_by_rule": dict(rules.most_common())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lexicon", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    sc = Scanner(lexicon=QuantityLexicon() if args.lexicon else None)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    db = corpus()
    report = {"lexicon": args.lexicon, "passages": []}
    for p in cfg["passages"]:
        kind = p.get("kind", "verse")
        sc.dialect = p.get("dialect", "none")
        report["passages"].append(verse(sc, p, db) if kind == "verse" else pindar(sc, p, db) if kind == "responsion"
                                  else prose(sc, p, db))
    tot = defaultdict(int)
    for r in report["passages"]:
        for k in ("scored", "decided", "correct", "ambiguous"):
            tot[k] += r.get(k, 0)
    report["verse_total"] = dict(tot, decided_accuracy=round(tot["correct"] / max(tot["decided"], 1), 4),
                                 ambiguous_share=round(tot["ambiguous"] / max(tot["scored"], 1), 4))
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
