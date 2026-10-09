"""Release U checks over HTTP (standard library only): one check per item of the release, with the expected
outcome stated, and draft-analysis / dialect-spelling latencies.

    python3 scripts/check_release_u.py --base http://127.0.0.1:8792 --out release-u.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request

STANZA = ("φαίνεται πόντῳ πέρι νῦν σελάννα,\nκαὶ πόθος θῦμόν με δόνει μάλ’ αὖτε·\n"
          "Ἄτθι, πήλοθεν δὲ σὺ μ’ οὐκ ὄρησθα·\nνύκτα κατεύδω.")
EDITED = STANZA.replace("νύκτα κατεύδω", "ἔγω δὲ μόνα κατεύδω")


def call(base, path, body=None, params=None):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"content-type": "application/json"} if data else {})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
    return json.loads(raw), round((time.perf_counter() - t) * 1000), len(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    B = args.base
    checks, timings = [], {}

    def check(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name, json.dumps(detail, ensure_ascii=False)[:300], flush=True)

    # 1. draft analysis
    runs = []
    for text in (STANZA, STANZA, EDITED, STANZA, EDITED):
        data, ms, size = call(B, "/api/analyze-text", {"text": text, "author": "Sappho"})
        runs.append({"ms": ms, "kB": size // 1024})
    timings["analyze_text"] = {"first": runs[0], "repeat": [r["ms"] for r in runs[1:]],
                               "repeat_median_ms": statistics.median(r["ms"] for r in runs[1:])}
    words = {w["text"]: w for w in data["words"]}
    check("draft: Lesbian readings of the exercise stanza",
          words["σελάννα"]["lemma"] == "σελήνη" and "sg." in (words["σελάννα"]["parse"] or "")
          and words["θῦμόν"]["lemma"] == "θυμός" and words["αὖτε"]["lemma"] == "αὖτε"
          and words["πήλοθεν"]["lemma"] == "τηλόθεν" and "Atthis" in (words["Ἄτθι"]["gloss"] or ""),
          {k: (words[k]["lemma"], words[k]["parse"], words[k]["gloss"]) for k in ("σελάννα", "θῦμόν", "αὖτε", "πήλοθεν", "Ἄτθι")})
    check("draft: compact response under 200 kB", runs[0]["kB"] < 200, runs[0])

    # 3. dialect spellings
    want = {"τηλόθεν": "πήλοθεν", "σελήνη": "σελάννα", "ἥλιος": "ἀέλιος", "φέρουσα": "φέροισα", "ἄγειν": "ἄγην",
            "μόνος": "μόνα"}
    data, ms, _ = call(B, "/api/dialectize", {"forms": list(want), "dialect": "lesbian"})
    _, ms2, _ = call(B, "/api/dialectize", {"forms": list(want), "dialect": "lesbian"})
    timings["dialectize_6_forms"] = {"first_ms": ms, "repeat_ms": ms2}
    found = {r["form"]: [c["form"] for c in r["candidates"]] for r in data["results"]}
    check("dialectize: Attic -> Lesbian spellings", all(want[f] in found.get(f, []) for f in want), found)

    # 4. one edition per fragment
    freq, _, _ = call(B, "/api/lemma/frequency", params={"q": "σελήνη"})
    sappho = next((r["count"] for r in freq["by_author"] if r["author"] == "Sappho"), None)
    search, _, _ = call(B, "/api/lemma/search", params={"q": "σελήνη", "author": "Sappho"})
    forms = {f["form"]: f["count"] for f in search["forms_found"]}
    check("counts: σελήνη in Sappho = 4 places (fr. 34, 96, 154, 168B)", sappho == 4 and forms.get("σελάννα") == 3
          and search["total_passages"] == 4, {"frequency": sappho, "forms_found": forms, "passages": search["total_passages"]})
    pothos, _, _ = call(B, "/api/lemma/frequency", params={"q": "πόθος"})
    check("counts: πόθος in Sappho = 4 (fr. 22, 48, 94, 102)",
          next((r["count"] for r in pothos["by_author"] if r["author"] == "Sappho"), None) == 4, None)
    # Sappho 1.1 ποικιλόθρον’ ἀθανάτ’ is one line of one poem: five editions made it a count of 4-5 (minimum 3).
    ngrams, _, _ = call(B, "/api/lemma/ngrams", params={"kind": "author", "name": "Sappho", "n": 2, "q": "ποικιλόθρονος"})
    rows = ngrams.get("ngrams") or ngrams.get("results") or []
    check("n-grams: Sappho 1.1 (one poem) is no longer a repeated bigram",
          not any((g.get("count") or 0) >= 3 for g in rows), [(g.get("lemmas") or g.get("text"), g.get("count")) for g in rows[:5]])

    # 5. fast lookup
    head, ms, _ = call(B, "/api/words/headlines", {"forms": ["θῦμόν", "εὔδω", "σελάννα", "μόνα", "αὖτε", "Ἄτθι", "τεθνάκην"],
                                                   "author": "Sappho"})
    t = {x["printed"]: x for x in head["tokens"]}
    ok = (t["θῦμόν"]["lemma"] == "θυμός" and t["εὔδω"]["lemma"] == "εὕδω" and t["σελάννα"]["parses"][0] == "nom. fem. sg."
          and t["μόνα"]["parses"][0] == "nom. fem. sg." and t["αὖτε"]["lemma"] == "αὖτε"
          and "Atthis" in (t["Ἄτθι"]["gloss"] or "") and t["τεθνάκην"]["lemma"] == "θνῄσκω")
    check("headlines: enclitic accent, psilosis, ᾱ singulars, αὖτε, Atthis, τεθνάκην", ok,
          {k: (v["lemma"], v["parses"][:2], v["gloss"]) for k, v in t.items()})
    timings["headlines_7_forms_ms"] = ms

    # 6. concept search
    con, ms, size = call(B, "/api/concept/diachrony", params={"q": "longing"})
    names = [r["lemma"] for r in con["lemmas"]]
    check("concept: longing finds πόθος and ἵμερος, not μακρός or λέων",
          "πόθος" in names and "ἵμερος" in names and "μακρός" not in names and "λέων" not in names, names)
    con_s, ms_s, _ = call(B, "/api/concept/diachrony", params={"q": "longing", "author": "Sappho"})
    timings["concept_ms"] = {"all": ms, "sappho": ms_s, "all_kB": size // 1024}
    check("concept: author scope (Sappho)", all(all(a["author"] == "Sappho" for a in r["by_author"]) for r in con_s["lemmas"]),
          [(r["lemma"], r["tokens"]) for r in con_s["lemmas"]])
    prox, _, _ = call(B, "/api/lemma/proximity", params={"q": "ἔρως δονέω", "window": 6, "author": "Sappho"})
    check("proximity: Ἔρος … δόνει (fr. 130) found with variants combined by default", prox.get("total", 0) >= 1,
          [(r.get("citation"), r.get("match_text") or r.get("id")) for r in prox.get("results", [])[:3]])

    # 7. line-level parallels
    res, ms, _ = call(B, "/api/search", params={"q": "moon over the sea", "mode": "hybrid", "author": "Sappho", "limit": 10})
    with_line = [r for r in res["results"] if r.get("best_line")]
    check("search: results carry the line holding the query's headwords", len(with_line) >= 1,
          [(r.get("citation"), r["best_line"]["text"], r["best_line"]["citation"]) for r in with_line[:3]])
    ex = [e for r in con["lemmas"] for p in r["by_period"] for e in p.get("examples") or []]
    check("concept: examples carry their line", ex and all(e.get("line", {}).get("text") for e in ex), len(ex))
    cite, _, _ = call(B, "/api/cite", params={"q": "Il. 1.5"})
    lines = [r.get("cited_line") for r in cite.get("results", []) if r.get("cited_line")]
    check("cite: Il. 1.5 returns the cited line", bool(lines), lines[:2])

    # coordinator: variant labels
    var, _, _ = call(B, "/api/lemma/variants", params={"q": "ἔρως"})
    labels = [link.get("dictionary") for m in (var.get("variant_group") or {}).get("members", []) for link in m["links"]]
    check("variants: no null dictionary label (ἔρως)", all(labels), labels)

    out = {"base": B, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": checks, "timings": timings,
           "passed": sum(c["pass"] for c in checks), "total": len(checks)}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(timings, ensure_ascii=False))
    print(f"{out['passed']}/{out['total']} checks passed")


if __name__ == "__main__":
    main()
