"""Lyric gold set: dump what the reader shows for every word of chosen poems, and score it (release R).

    python3 scripts/eval_lyric_gold.py dump  --base http://127.0.0.1:8791 --out dump.json [--passages id ...]
    python3 scripts/eval_lyric_gold.py score --gold data/evaluation/lyric-gold-r.json --dump dump.json [--json out.json]

`dump` asks the backend exactly what the reader asks on a click: one /api/analyze-passage request per word
span (the span of the word's interlinear row in a line analysis), and the batch index headline
(/api/words/headlines). The displayed headword is the frontend's choice (js/word-panel.js headlineDetail):
the row's lemma, else the first ranked parse whose lemma is not the printed spelling itself; the displayed
parse is that row's (or that ranked parse's) features.

`score` compares the displayed headword and parse with the gold set: lemma accuracy (headword equal up to a
homograph number, case and NFC) and full-parse accuracy (lemma right and every feature the gold states equal),
for the development and held-out halves and for certain tokens only (uncertain gold tokens are reported apart).
Standard library only; no request leaves the given origin.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict

POEMS = ["campbell-glp:sappho:1", "campbell-glp:sappho:16", "campbell-glp:sappho:31", "campbell-glp:sappho:34",
         "campbell-glp:sappho:44", "campbell-glp:sappho:94", "campbell-glp:sappho:96",
         "campbell-glp:alcaeus:34a", "campbell-glp:alcaeus:129", "campbell-glp:alcaeus:130b",
         "campbell-glp:alcaeus:326", "campbell-glp:alcaeus:350", "campbell-glp:alcaeus:346",
         "campbell-glp:alcaeus:347"]
UA = {"User-Agent": "Melos/1.0 (+https://greeklyric.com)", "Content-Type": "application/json"}
# gold parse vocabulary -> UD feature values used by the interlinear rows
FEATS = {"POS": {"noun": "NOUN", "name": "PROPN", "adj": "ADJ", "verb": "VERB", "part": "VERB", "adv": "ADV",
                 "pron": "PRON", "art": "DET", "prep": "ADP", "conj": "CCONJ", "sconj": "SCONJ", "particle": "PART",
                 "num": "NUM", "interj": "INTJ"},
         "Case": {"nom": "Nom", "gen": "Gen", "dat": "Dat", "acc": "Acc", "voc": "Voc"},
         "Number": {"sg": "Sing", "pl": "Plur", "du": "Dual"},
         "Gender": {"masc": "Masc", "fem": "Fem", "neut": "Neut"},
         "Tense": {"pres": "Pres", "impf": "Imp", "fut": "Fut", "aor": "Aor", "perf": "Perf", "plup": "Pqp",
                   "futperf": "Fut"},
         "Mood": {"ind": "Ind", "subj": "Sub", "opt": "Opt", "imp": "Imp"},
         "VerbForm": {"inf": "Inf", "ptcp": "Part"},
         "Voice": {"act": "Act", "mid": "Mid", "pass": "Pass", "mp": "Med"},
         "Person": {"1": "1", "2": "2", "3": "3"},
         "Degree": {"comp": "Cmp", "sup": "Sup"}}
# Parts of speech that count as the same class: dictionaries, the parser and the treebanks label nominal
# words (μάκαρ noun or adjective, ὅσος pronoun or adjective, εἷς numeral or adjective) and particles,
# adverbs and conjunctions differently; case, number and gender are what the parse must get right.
POS_SAME = [{"NOUN", "PROPN", "ADJ", "PRON", "DET", "NUM"}, {"CCONJ", "SCONJ", "PART", "ADV"},
            {"VERB", "AUX"}, {"ADP", "ADV"}]
VOICE_SAME = [{"Mid", "Med", "Pass"}]


def post(base, path, body, timeout=600):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=UA)
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except Exception:  # noqa: BLE001 - retried, then raised
            if attempt == 2:
                raise
            time.sleep(2)


def get(base, path):
    return json.load(urllib.request.urlopen(urllib.request.Request(base + path, headers=UA), timeout=120))


def u16(s):
    return len(s.encode("utf-16-le")) // 2


def from_u16(text, n):
    """Code-point index of a UTF-16 offset."""
    acc = 0
    for i, ch in enumerate(text):
        if acc >= n:
            return i
        acc += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def word_rows(data):
    return [r for r in (data.get("interlinear") or {}).get("readings", [{}])[0].get("tokens", []) if r.get("kind") == "word"]


def unelided(s):
    return str(s or "").rstrip("’'ʼ᾽")


def displayed(row, mode="r"):
    """(lemma, features, parse) the reader shows for an interlinear row (js/word-panel.js headlineDetail).

    mode "q": release Q's frontend (row lemma, else the first ranked parse whose lemma is not the printed
    spelling); mode "r": release R's (row lemma, else the backend headline with its best-ranked parse; a
    lemma spelt like the printed word is skipped only for an elided word)."""
    ranking = row.get("ranking_full") or []
    feats_of = row.get("meaning_features") or {}
    text = row.get("printed") or ""
    elided = text[-1:] in "’'ʼ᾽"
    if row.get("lemma"):
        if mode == "r" and not row.get("parse_short"):
            own = next((i for i in ranking if i.get("lemma") and i.get("parse_short")
                        and lemma_key(i["lemma"]) == lemma_key(row["lemma"])), None)
            if own:
                return own["lemma"], feats_of.get(own.get("candidate_id")) or {}, own["parse_short"]
        return row["lemma"], row.get("features") or {}, row.get("parse_short") or ""
    if mode == "q":
        usable = lambda item: item.get("lemma") and item.get("parse_short") and unelided(item["lemma"]) != unelided(text)
        item = next((i for i in ranking if usable(i)), None)
        if item:
            return item["lemma"], feats_of.get(item.get("candidate_id")) or {}, row.get("parse_short") or item["parse_short"]
        return "", {}, row.get("parse_short") or ""
    usable = lambda item: item.get("lemma") and item.get("parse_short") and not (elided and unelided(item["lemma"]) == unelided(text))
    head = row.get("headline_lemma")
    item = next((i for i in ranking if usable(i) and lemma_key(i["lemma"]) == lemma_key(head)), None) if head else None
    item = item or next((i for i in ranking if usable(i)), None)
    if item:
        return item["lemma"], feats_of.get(item.get("candidate_id")) or {}, item["parse_short"] or row.get("parse_short") or ""
    if head and not (elided and unelided(head) == unelided(text)):
        return head, {}, ""
    return "", {}, row.get("parse_short") or ""


def dump(args):
    out = {"base": args.base, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "passages": {}}
    for pid in args.passages:
        p = get(args.base, "/api/passage?id=" + urllib.request.quote(pid))
        text = p["text"]
        try:
            batch = post(args.base, "/api/words/headlines", {"passage_id": pid})
        except Exception:  # noqa: BLE001
            batch = {"tokens": []}
        by_start = {t["start"]: t for t in batch.get("tokens", [])}
        words, pos = [], 0
        for line in text.split("\n"):
            s, e = pos, pos + len(line)
            pos = e + 1
            if not line.strip():
                continue
            try:
                data = post(args.base, "/api/analyze-passage", {"version": 1, "passage_id": pid, "start": u16(text[:s]),
                                                             "end": u16(text[:e]), "offset_unit": "utf16",
                                                             "selected_text": text[s:e], "fetch_machine": False, "rerank": False})
            except Exception as exc:  # noqa: BLE001 - a line with no word (a lacuna) is skipped
                print("line skipped", pid, repr(line[:40]), exc, file=sys.stderr)
                continue
            for row in word_rows(data):
                words.append((row["start_utf16"], row["end_utf16"], row.get("text")))
        rows = []
        only = None
        if args.gold and args.split:
            only = {g["start"] for g in json.load(open(args.gold, encoding="utf-8"))["tokens"]
                    if g["passage_id"] == pid and g["split"] == args.split}
        for i, (a, b, printed) in enumerate(words):
            cs, ce = from_u16(text, a), from_u16(text, b)
            if only is not None and cs not in only:
                continue
            data = post(args.base, "/api/analyze-passage", {"version": 1, "passage_id": pid, "start": a, "end": b,
                                                         "offset_unit": "utf16", "selected_text": text[cs:ce],
                                                         "fetch_machine": False, "rerank": False})
            got = [r for r in word_rows(data) if r.get("start_utf16") == a] or word_rows(data)[:1]
            row = got[0] if got else {}
            ix = by_start.get(cs) or {}
            rows.append({"i": i, "start": cs, "end": ce, "printed": printed, "form": row.get("form") or printed,
                         "lemma": row.get("lemma"), "features": row.get("features") or {}, "parse_short": row.get("parse_short"),
                         "ranking_full": [{"lemma": r.get("lemma"), "parse_short": r.get("parse_short"), "score": r.get("score"),
                                           "candidate_id": r.get("candidate_id")} for r in row.get("morphology_ranking") or []],
                         "meaning_features": {m.get("candidate_id"): m.get("features") for m in row.get("candidate_meanings") or []},
                         "dialect_rules": row.get("dialect_rules"),
                         "headline_lemma": row.get("headline_lemma"), "status": row.get("status"),
                         "selection_basis": row.get("selection_basis"),
                         "gloss": ((row.get("gloss") or {}).get("short_text") or (row.get("gloss") or {}).get("text")),
                         "damaged": bool(row.get("damaged_piece") or row.get("editorial_fragment") or row.get("partial_word")),
                         "index_lemma": ix.get("lemma"), "index_probability": ix.get("probability"),
                         "index_alternatives": [a.get("lemma") if isinstance(a, dict) else a for a in ix.get("alternatives", [])]})
        out["passages"][pid] = {"text": text, "words": rows}
        print(pid, len(rows), "words", file=sys.stderr)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0)


def lemma_key(s):
    s = unicodedata.normalize("NFC", str(s or "")).strip().lstrip("†*").rstrip("0123456789").strip()
    return unicodedata.normalize("NFC", s).casefold()


# One word under two lemmatisation conventions (the treebanks lemmatise ἡμεῖς under ἐγώ, ὑμεῖς under σύ).
CONVENTIONS = [{"ἐγώ", "ἡμεῖς"}, {"σύ", "ὑμεῖς"}, {"ῥύομαι", "ἐρύω"}]


def accepted(g):
    keys = {lemma_key(x) for x in [g["lemma"]] + g.get("lemma_also", [])}
    for group in CONVENTIONS:
        if keys & {lemma_key(x) for x in group}:
            keys |= {lemma_key(x) for x in group}
    return keys


def same(field, gold, got):
    if gold == got:
        return True
    pools = POS_SAME if field == "POS" else VOICE_SAME if field == "Voice" else []
    return any(gold in p and got in p for p in pools)


def gold_features(parse):
    """'verb 2sg aor imp mid' / 'noun voc sg fem' -> UD feature dict."""
    feats = {}
    for word in str(parse or "").split():
        if word in ("1sg", "2sg", "3sg", "1pl", "2pl", "3pl", "1du", "2du", "3du"):
            feats["Person"], feats["Number"] = word[0], FEATS["Number"][word[1:]]
            continue
        for field, table in FEATS.items():
            if word in table:
                feats[field] = table[word]
                break
        else:
            raise ValueError(f"unknown parse word {word!r} in {parse!r}")
    return feats


def score(args):
    gold = json.load(open(args.gold, encoding="utf-8"))
    dumped = json.load(open(args.dump, encoding="utf-8"))
    res = defaultdict(Counter)
    errors = []
    for g in gold["tokens"]:
        words = dumped["passages"].get(g["passage_id"], {}).get("words", [])
        w = next((x for x in words if x["start"] == g["start"]), None)
        split = g["split"]
        keys = [split, "all"] + ([split + "_certain", "all_certain"] if not g.get("uncertain") else ["uncertain"])
        poet = g["passage_id"].split(":")[1]
        keys += [poet + ("_certain" if not g.get("uncertain") else "_uncertain")]
        shown_lemma, shown_feats, shown_parse = displayed(w, args.frontend) if w else ("", {}, "")
        lemma_ok = bool(w) and lemma_key(shown_lemma) in accepted(g)
        ix_ok = bool(w) and lemma_key(w.get("index_lemma")) in accepted(g)
        want = gold_features(g["parse"])
        if want.get("POS") == "PRON" and "Person" in want:
            want.pop("Person")  # a personal pronoun's person is its lemma (ἐγώ, σύ), not a parser feature
        got = shown_feats
        bad = [f for f, v in want.items() if not same(f, v, got.get(f))]
        parse_ok = lemma_ok and not bad
        for k in keys:
            res[k]["n"] += 1
            res[k]["lemma"] += lemma_ok
            res[k]["parse"] += parse_ok
            res[k]["index_lemma"] += ix_ok
        if not g.get("uncertain") and (not lemma_ok or bad):
            errors.append({"passage_id": g["passage_id"], "start": g["start"], "printed": g["printed"], "split": split,
                           "gold": [g["lemma"], g["parse"]], "got": [shown_lemma, shown_parse], "index": (w or {}).get("index_lemma"),
                           "bad_features": bad, "lemma_ok": lemma_ok})
    table = {k: {"tokens": v["n"], "lemma_accuracy": round(v["lemma"] / v["n"], 4),
                 "full_parse_accuracy": round(v["parse"] / v["n"], 4),
                 "index_lemma_accuracy": round(v["index_lemma"] / v["n"], 4)} for k, v in sorted(res.items()) if v["n"]}
    report = {"gold": args.gold, "dump": args.dump, "base": dumped.get("base"), "at": dumped.get("at"),
              "results": table, "errors": errors}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    for k, v in table.items():
        print(f"{k:22s} n={v['tokens']:4d} lemma {v['lemma_accuracy']:.3f} parse {v['full_parse_accuracy']:.3f} index {v['index_lemma_accuracy']:.3f}")
    if args.errors:
        for e in errors:
            print(json.dumps(e, ensure_ascii=False))


def index_score(args):
    """Headline headword of the corpus index (the batch headwords) against the gold set, per half."""
    import sqlite3
    from array import array
    gold = json.load(open(args.gold, encoding="utf-8"))["tokens"]
    res = defaultdict(Counter)
    errors = []
    for path in args.index:
        ix = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        lemma_of = dict(ix.execute("SELECT id, lemma FROM lemma"))
        pid_of = dict(ix.execute("SELECT id, pid FROM passage WHERE id LIKE 'campbell-glp:%'"))
        cache = {}
        for g in gold:
            if g.get("uncertain") or not g.get("lemma"):
                continue
            pid = pid_of.get(g["passage_id"])
            if pid not in cache:
                row = ix.execute("SELECT lemmas, starts FROM tok WHERE pid=?", (pid,)).fetchone()
                cache[pid] = (array("I", row[0]).tolist(), array("I", row[1]).tolist()) if row else None
            t = cache.get(pid)
            if not t or g["start"] not in t[1]:
                continue
            lemma = lemma_of.get(t[0][t[1].index(g["start"])])
            ok = lemma_key(lemma) in accepted(g)
            for k in (g["split"], "all"):
                res[(path, k)]["n"] += 1
                res[(path, k)]["ok"] += ok
            if not ok and path == args.index[-1] and g["split"] == "dev":
                errors.append(f'{g["passage_id"]} {g["printed"]} gold {g["lemma"]} got {lemma}')
    for (path, k), v in sorted(res.items()):
        print(f"{path} {k:5s} n={v['n']} index lemma accuracy {v['ok'] / v['n']:.3f}")
    if args.errors:
        print("\n".join(errors))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--base", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--passages", nargs="+", default=POEMS)
    d.add_argument("--gold", help="with --split: dump only the gold tokens of that half")
    d.add_argument("--split", choices=("dev", "held"))
    s = sub.add_parser("score")
    s.add_argument("--gold", required=True)
    s.add_argument("--dump", required=True)
    s.add_argument("--json")
    s.add_argument("--errors", action="store_true")
    s.add_argument("--frontend", choices=("q", "r"), default="r", help="which release's frontend display rule")
    i = sub.add_parser("index")
    i.add_argument("--gold", required=True)
    i.add_argument("--index", nargs="+", required=True)
    i.add_argument("--errors", action="store_true")
    args = p.parse_args()
    {"dump": dump, "score": score, "index": index_score}[args.cmd](args)


if __name__ == "__main__":
    main()
