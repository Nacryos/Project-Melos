"""Release V checks over HTTP (standard library only): the scanner (/api/scan) and the composer's suggestions
(/api/compose/suggest, /api/compose/status), each with its expected outcome, plus their latencies.

    python3 scripts/check_release_v.py --base http://127.0.0.1:8792 --out release-v.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request

STANZA = ("φαίνεται πόντῳ πέρι νῦν σελάννα,\nκαὶ πόθος θῦμόν με δόνει μάλ’ αὖτε·\n"
          "Ἄτθι, πήλοθεν δὲ σὺ μ’ οὐκ ὄρησθα·\nνύκτα κατεύδω.")
ILIAD = "μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος"


def call(base, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data, {**({"content-type": "application/json"} if data else {}), **(headers or {})})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as exc:
        raw, code = exc.read(), exc.code
    return code, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode(errors="replace")), round((time.perf_counter() - t) * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    B = args.base
    checks, timings = [], {}

    def check(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name, json.dumps(detail, ensure_ascii=False)[:400], flush=True)

    code, scan, ms = call(B, "/api/scan", {"text": STANZA, "metre": "sapphic", "dialect": "aeolic"})
    fits = [f["ok"] for f in scan.get("fit", [])] if code == 200 else []
    check("scan: the exercise stanza fits the Sapphic stanza (aeolic, lexicon on)",
          code == 200 and fits == [True, True, True, True] and scan.get("lexicon") is True,
          {"code": code, "fits": fits, "lexicon": scan.get("lexicon") if code == 200 else None, "ms": ms})
    code, il, _ = call(B, "/api/scan", {"text": ILIAD, "metre": "hexameter"})
    check("scan: Iliad 1.1 fits the hexameter", code == 200 and il["fit"][0]["ok"],
          {"code": code, "pattern": il.get("fit", [{}])[0].get("pattern") if code == 200 else il})
    units = il.get("units", []) if code == 200 else []
    check("scan: every unit has p_long, a rule and reasons",
          bool(units) and all("p_long" in u and u.get("rule") and u.get("reasons") for u in units), {"units": len(units)})
    code, auto, _ = call(B, "/api/scan", {"text": ILIAD, "metre": "auto"})
    check("scan: auto-detect ranks the hexameter first", code == 200 and auto["auto"][0]["metre"] == "hexameter",
          {"top": auto.get("auto", [{}])[0] if code == 200 else auto})
    code, bad, _ = call(B, "/api/scan", {"text": ILIAD, "metre": "limerick"})
    check("scan: unknown metre is 422", code == 422, {"code": code})
    code, _, _ = call(B, "/api/scan/rules/save", {"yaml": "x: 1"})
    check("scan: saving the rules file is refused in production", code == 403, {"code": code})
    code, rules, _ = call(B, "/api/scan/rules")
    check("scan: rules tree served", code == 200 and not rules.get("errors") and rules.get("metres"), {"code": code})
    times = []
    for i in range(20):
        _, r, ms = call(B, "/api/scan", {"text": STANZA.replace("νύκτα", "νύκτα" + " " * (i % 3)), "metre": "sapphic", "dialect": "aeolic"})
        times.append(ms)
    timings["scan_stanza_ms"] = {"median": statistics.median(times), "max": max(times), "server_ms_last": r.get("ms")}
    check("scan: 4-line stanza with metre, median round trip under 150 ms", statistics.median(times) < 150, timings["scan_stanza_ms"])

    code, status, _ = call(B, "/api/compose/status")
    check("compose: status names the proposer and says whether a text model is configured",
          code == 200 and status.get("proposers") == ["corpus"] and "configured" in status.get("llm", {}),
          {"code": code, "llm": status.get("llm") if code == 200 else status})
    sugg_times = []
    first = None
    for body in ({"text": STANZA.rsplit("\n", 1)[0], "author": "Sappho", "metre": "sapphic"},
                 {"text": STANZA, "author": "Sappho", "metre": "sapphic"},
                 {"text": "δέδυκε μὲν ἀ σελάννα", "author": "Sappho", "metre": "auto"}):
        code, s, ms = call(B, "/api/compose/suggest", body)
        sugg_times.append(ms)
        first = first or s
        cands = s.get("candidates", []) if code == 200 else []
        ok = code == 200 and cands and all(c.get("checks") and c.get("verdict") in ("pass", "warn", "fail")
                                           and c["source"].get("citation") for c in cands)
        check(f"compose: suggestions with lint and citations ({body['metre']}, {body['text'].count(chr(10)) + 1} lines)", ok,
              {"code": code, "ms": ms, "target": s.get("target") if code == 200 else s,
               "candidates": [[c["greek"], c["verdict"], c["source"]["citation"]] for c in cands]})
    timings["suggest_ms"] = sugg_times
    code, _, _ = call(B, "/api/compose/suggest", {"text": "   "})
    check("compose: empty draft is 422", code == 422, {"code": code})
    code, _, _ = call(B, "/api/compose/suggest", {"text": ILIAD, "metre": "limerick"})
    check("compose: unknown metre is 422", code == 422, {"code": code})
    code, _, _ = call(B, "/api/compose/suggest", {"text": ILIAD, "extra": 1})
    check("compose: extra fields are 422", code == 422, {"code": code})
    # Per-client limit: a forwarded visitor (as through Vercel and Funnel) is limited at 12 a minute.
    hdr = {"x-forwarded-for": "203.0.113.%d, 198.51.100.7" % int(time.time() % 200)}
    codes = [call(B, "/api/compose/suggest", {"text": "   "}, hdr)[0] for _ in range(14)]
    check("compose: per-client rate limit answers 429 after 12 a minute", codes.count(429) >= 1 and codes[0] == 422,
          {"codes": codes})
    json.dump({"checks": checks, "timings": timings, "example": first}, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{sum(c['pass'] for c in checks)}/{len(checks)} passed")


if __name__ == "__main__":
    main()
