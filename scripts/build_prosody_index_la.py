#!/usr/bin/env python3
"""Build data/scansion/prosody_la.sqlite: one row per word token of the Hypotactic hand scansion (David Chamberlain,
CC BY 4.0), for the prosody attestation check L12 (backend/latin_prosody.py; docs/latin/prosody-attestation.md).

Inputs (data/open/latin/hypotactic/): lines.jsonl.gz (Catullus, Horace Odes 1) and, when present, lines-virgil.jsonl.gz
(Aeneid, Georgics, Eclogues, Horace's other lyrics; scripts/ingest_open_hypotactic_virgil.py).

  tokens  key (the scanner's folding: backend/scansion/latin.py key, letters only), form (as printed, with macrons),
          author, work, locus, line_id, metre, widx, nsyl, pat (one letter per syllable: L long, S short, E elided),
          syl (JSON: the syllables' letters), vpos (JSON: where each syllable's vowel starts in the key),
          final_ctx (END line end | E elided | V before a vowel or h | C one consonant | ML mute + liquid | CC cluster),
          final_open (the word ends in a vowel), next_initial, elided, mcl (JSON: syllables whose vowel stands before
          mute + liquid inside the word), mcl_boundary (open final before a word beginning mute + liquid), synizesis,
          prodelision (elided before est / es, or est / es after such a word), line_end, flags ("i:flag" per marked syllable)
  lines   line_id, author, work, locus, metre, text
  lemmas  key, lemma (backend/latin_lemma.py readings, the three most frequent), for the stem verdict
  meta    counts, sources, sha256

Usage: python scripts/build_prosody_index_la.py [--out PATH] [--no-lemmas]
       python scripts/build_prosody_index_la.py --measure     leave-one-line-out over Catullus's hendecasyllables (JSON)
       python scripts/build_prosody_index_la.py --variants 50 forms attested with both weights on a syllable (markdown)
"""
import argparse, datetime, gzip, hashlib, json, os, sqlite3, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import latin_prosody as lp  # noqa: E402

SRC = os.path.join(ROOT, "data", "open", "latin", "hypotactic")
SOURCES = ["lines.jsonl.gz", "lines-virgil.jsonl.gz"]
SYNIZESIS = ("synizesis", "synezesis")           # the second spelling is the source's own (odes1 37.5)
SCHEMA = """
CREATE TABLE tokens (id INTEGER PRIMARY KEY, key TEXT, form TEXT, author TEXT, work TEXT, locus TEXT, line_id TEXT, metre TEXT,
  widx INTEGER, nsyl INTEGER, pat TEXT, syl TEXT, vpos TEXT, final_ctx TEXT, final_open INTEGER, next_initial TEXT,
  elided INTEGER, mcl TEXT, mcl_boundary INTEGER, synizesis INTEGER, prodelision INTEGER, line_end INTEGER, flags TEXT);
CREATE TABLE lines (line_id TEXT PRIMARY KEY, author TEXT, work TEXT, locus TEXT, metre TEXT, text TEXT);
CREATE TABLE lemmas (key TEXT, lemma TEXT, PRIMARY KEY (key, lemma)) WITHOUT ROWID;
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def locus(r: dict) -> str:
    ref = ".".join(str(x).strip(":") for x in (r["book"], r["poem_number"], r["line_no"]) if str(x))
    work = "" if r["work"] in ("", "Poems") else r["work"] + " "
    return f"{r['author']} {work}{ref}"


def token_rows(r: dict):
    """The index rows of one gold line (a dict as written by the ingesters)."""
    words = [w for w in r["words"] if lp.fold(w["form"])]
    loc = locus(r)
    for i, w in enumerate(words):
        key = lp.fold(w["form"])
        syl = [s["t"] for s in w["syl"]]
        pat = "".join(s["q"] if s["q"] in "LSE" else "?" for s in w["syl"])
        nxt = words[i + 1]["form"] if i + 1 < len(words) else ""
        elided = pat.endswith("E")
        ctx = "E" if elided else lp.initial_class(nxt) if nxt else "END"
        open_ = lp.final_open(w["form"])
        vpos, off = [], 0
        for t in syl:
            vpos.append(off + lp.first_vowel(t))
            off += len(lp.bare(t))
        flags = " ".join(f"{j}:{f}" for j, s in enumerate(w["syl"]) for f in s["f"])
        prod = (elided and lp.fold(nxt) in ("est", "es")) or (key in ("est", "es") and i > 0 and words[i - 1]["pat"].endswith("e"))
        yield (key, w["form"], r["author"], r["work"], loc, r["id"], r["metre"], i, len(syl), pat, json.dumps(syl, ensure_ascii=False),
               json.dumps(vpos), ctx, int(open_), lp.initial_class(nxt) if nxt else "", int(elided), json.dumps(lp.mcl_after(syl)),
               int(open_ and not elided and bool(nxt) and lp.initial_class(nxt) == "ML"),
               int(any(f in SYNIZESIS for s in w["syl"] for f in s["f"])), int(prod), int(i == len(words) - 1), flags)


def build(sources: list[str], out: str, lemmas: bool = True) -> dict:
    tmp = out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    counts = {"lines": 0, "tokens": 0, "per_author": {}}
    used = {}
    for path in sources:
        if not os.path.exists(path):
            continue
        used[os.path.basename(path)] = sha(path)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for raw in f:
                r = json.loads(raw)
                rows = list(token_rows(r))
                if not rows:
                    continue
                db.execute("INSERT OR REPLACE INTO lines VALUES (?,?,?,?,?,?)", (r["id"], r["author"], r["work"], locus(r), r["metre"], r["text"]))
                db.executemany("INSERT INTO tokens (key, form, author, work, locus, line_id, metre, widx, nsyl, pat, syl, vpos, final_ctx, "
                               "final_open, next_initial, elided, mcl, mcl_boundary, synizesis, prodelision, line_end, flags) "
                               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                counts["lines"] += 1
                counts["tokens"] += len(rows)
                a = counts["per_author"].setdefault(r["author"], {"lines": 0, "tokens": 0})
                a["lines"] += 1
                a["tokens"] += len(rows)
    db.execute("CREATE INDEX tokens_key ON tokens(key)")
    db.execute("CREATE INDEX tokens_line ON tokens(line_id)")
    keys = [r[0] for r in db.execute("SELECT DISTINCT key FROM tokens")]
    counts["forms"] = len(keys)
    if lemmas:
        from backend import latin_lemma
        n = 0
        for k in keys:
            try:
                ls = [x["lemma"] for x in latin_lemma.readings(k)][:3]
            except Exception:
                ls = []
            for lem in dict.fromkeys(ls):
                db.execute("INSERT OR IGNORE INTO lemmas VALUES (?,?)", (k, lem))
                n += 1
        counts["lemma_rows"] = n
    db.execute("CREATE INDEX IF NOT EXISTS lemmas_lemma ON lemmas(lemma)")
    for k, v in (("built", time.strftime("%Y-%m-%d")), ("counts", json.dumps(counts)), ("sources", json.dumps(used)),
                 ("attribution", "David Chamberlain, hypotactic.com, CC BY 4.0")):
        db.execute("INSERT INTO meta VALUES (?,?)", (k, v))
    db.commit()
    db.close()
    os.replace(tmp, out)
    return counts


def measure() -> dict:
    """Leave-one-line-out: L12 on every Catullan hendecasyllable with that line's own tokens kept out of the evidence."""
    from backend.scansion import api, metre
    db = sqlite3.connect(lp.index_path())
    lines = db.execute("SELECT line_id, locus, text FROM lines WHERE author='Catullus' AND metre='hendecasyllables' ORDER BY rowid").fetchall()
    sc = api._scanner(None, True, "none", "la")
    tally, conflicts, misfit, lines_bad, by_cause = {}, [], [], 0, {}
    chosen, lp.MIN_CONFLICT = lp.MIN_CONFLICT, 1                    # run at N = 1; N = 2, 3 follow from each conflict's token count
    by_n = {n: {"conflict_tokens": 0, "lines": set(), "blockable": 0} for n in (1, 2, 3)}
    fixed, lex_all, lex_hits = 0, 0, []
    for line_id, loc, text in lines:
        plain = lp.unicodedata.normalize("NFC", "".join(ch for ch in lp.unicodedata.normalize("NFD", text) if ch not in "̄̆"))
        name = "phalaecian"
        if not metre.fit_line(sc.scan(plain), name).ok and metre.fit_line(sc.scan(plain), "phalaecian_decasyllable").ok:
            name = "phalaecian_decasyllable"
        res = lp.check(plain, metre_name=name, _exclude=frozenset([line_id]))
        if res["evidence"] and res["evidence"][0].get("metre"):
            misfit.append(loc)
        for e in res["evidence"]:
            worst = max((sum(s["other"].values()) for s in e.get("syllables", []) if s["status"] == "conflict"), default=0)
            for n in by_n:
                if worst >= n:
                    by_n[n]["conflict_tokens"] += 1
                    by_n[n]["lines"].add(loc)
            for s in e.get("syllables", []):
                if s["status"] == "ok":                            # a flipped quantity here would block at N iff the form has N tokens
                    fixed += 1
                    for n in by_n:
                        by_n[n]["blockable"] += sum(s["same"].values()) >= n
            if e["verdict"] == "conflict" and worst < chosen:
                e["verdict"] = "variant"
            if e.get("lexicon_disagrees"):
                lex_all += 1
                lex_hits.append({"locus": loc, "word": e["word"], "weights": e["weights"], "verdict": e["verdict"], "lexicon": e["lexicon_disagrees"]})
            tally[e["verdict"]] = tally.get(e["verdict"], 0) + 1
            if e["verdict"] == "conflict":
                for s in e["syllables"]:
                    if s["status"] == "conflict":
                        conflicts.append({"locus": loc, "text": text, "word": e["word"], "weights": e["weights"], "syllable": s["syllable"],
                                          "here": s["weight"], "other": s["other"], "cause": s["cause"], "misfit": bool(e.get("metre")),
                                          "eg": [x["locus"] + " " + x["form"] for x in s.get("other_loci", [])]})
            if e["verdict"] == "variant":
                for s in e["syllables"]:
                    if s["status"] != "ok":
                        by_cause[s["cause"]] = by_cause.get(s["cause"], 0) + 1
    total = sum(tally.values())
    lp.MIN_CONFLICT = chosen
    lines_bad = len(by_n[chosen]["lines"]) if chosen in by_n else lines_bad
    return {"run": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"), "min_conflict": chosen,
            "by_n": {n: {"false_conflict_tokens": v["conflict_tokens"], "rate": round(v["conflict_tokens"] / total, 5), "lines": sorted(v["lines"]),
                         "ok_syllables_blockable": v["blockable"], "blockable_share": round(v["blockable"] / max(fixed, 1), 4)} for n, v in by_n.items()},
            "ok_syllables": fixed,
            "lexicon": {"tokens_disagreeing_all": lex_all, "rate_all": round(lex_all / total, 5),
                        "verdict_tokens": tally.get("lexicon-conflict", 0), "rate_verdict": round(tally.get("lexicon-conflict", 0) / total, 5),
                        "hits": lex_hits},
            "lines": len(lines), "lines_with_conflict": lines_bad, "tokens": total, "verdicts": tally,
            "share": {k: round(v / total, 4) for k, v in tally.items()}, "variant_causes": by_cause, "lines_not_fitting": misfit,
            "conflicts": conflicts}


def variants(top: int) -> str:
    """Markdown table: forms with both weights on one syllable in like context, by token count."""
    db = sqlite3.connect(lp.index_path())
    db.row_factory = sqlite3.Row
    rows = {}
    for t in db.execute("SELECT key, author, nsyl, pat, final_ctx, final_open, mcl, flags, form, locus FROM tokens"):
        rows.setdefault((t["key"], t["nsyl"]), []).append(dict(t) | {"mcl": json.loads(t["mcl"])})
    found = []
    for (key, n), toks in rows.items():
        for i in range(n):
            groups = {}
            for t in toks:
                if t["pat"][i] not in "LS":
                    continue
                g = lp.context_group(bool(t["final_open"]), t["final_ctx"]) if i == n - 1 else ""
                if g in ("END", "E"):
                    continue
                groups.setdefault(g, []).append(t)
            for g, ts in groups.items():
                long_, short = [t for t in ts if t["pat"][i] == "L"], [t for t in ts if t["pat"][i] == "S"]
                if long_ and short:
                    cause = lp._cause(key, i, n, i in ts[0]["mcl"], ts)
                    per = lambda xs: ", ".join(f"{a} {c}" for a, c in sorted(lp._count(xs).items()))
                    found.append((min(len(long_), len(short)), len(ts), key, i + 1, g, per(long_), per(short), cause,
                                  long_[0]["locus"] + " " + long_[0]["form"], short[0]["locus"] + " " + short[0]["form"]))
    found.sort(key=lambda f: (-f[0], -f[1]))
    out = [f"{len(found)} (form, syllable, context) cases have both weights; the {top} with the most tokens on the rarer side:", "",
           "| form | syll. | context | long | short | cause | e.g. long | e.g. short |", "|---|---|---|---|---|---|---|---|"]
    names = {"": "any (not final)", "V": "final, before a vowel", "C": "final, before a consonant", "CC": "final, before a cluster"}
    for _, _, key, i, g, lo, sh, cause, el, es in found[:top]:
        out.append(f"| {key} | {i} | {names[g]} | {lo} | {sh} | {cause} | {el} | {es} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(lp.index_path()))
    ap.add_argument("--no-lemmas", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--variants", type=int, default=0)
    args = ap.parse_args()
    if args.measure:
        print(json.dumps(measure(), ensure_ascii=False, indent=1))
    elif args.variants:
        print(variants(args.variants))
    else:
        print(json.dumps(build([os.path.join(SRC, s) for s in SOURCES], args.out, not args.no_lemmas), indent=1))


if __name__ == "__main__":
    main()
