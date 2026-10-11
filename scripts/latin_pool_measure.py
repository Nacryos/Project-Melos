#!/usr/bin/env python3
"""Measure the Latin pool on the local dev stack (docs/composer/agent.md's method, for Latin):
a longer English source, the warm-up (research + stanza batch of whole lines), next-words fills at line 1 and mid-line
(with a prefix), and a whole-line fill for line 2 after an accepted line 1. Records seconds to the first passing
candidate, passing/rejected counts by check, and the agent's own cost per fill.
Usage: .venv/bin/python scripts/latin_pool_measure.py [--minutes 8] [--source plain|allusive] [--chat]
  -> docs/latin/pool/<timestamp>.json + a table on stdout. --source allusive uses a longer English source that echoes
  Catullus (5, 8, 31, 46, 101) so the research has something to find; --chat opens with a chat turn asking for the
  echoes and the Latin phrases behind them (tool calls, time and cost recorded) before the fills.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "private" / "dev-stack"
API = "http://127.0.0.1:8797"
ENGLISH = ("Come, friends, tonight we drink the dark Falernian; tomorrow the rain can keep the whole city to itself. "
           "Pour it unmixed, boy, the way old Postumia orders when she has had her share, and send the water away "
           "to the sober men. Let the lamps burn down; whoever counts the cups tonight is no friend of mine.")
ENGLISH_ALLUSIVE = (
    "Sirmio, bright eye of every peninsula and island, I am home. The lake laughs under the wind the way it did when I "
    "was a boy, and I set down the pack of Bithynia on the doorstep. Let us live, old friend, and count the kisses "
    "again until the counting itself is lost; the short light goes down once and the night is one unbroken sleep. "
    "Be stubborn, heart, and do not run after what runs away; the girl who shone for me is shining for someone else. "
    "Now spring brings back the warm days and the sky is no longer hoarse with storms; the mind itches to travel "
    "and the feet grow glad. Through many nations and many seas I came to my brother's grave to say what the dust "
    "cannot answer: hail and farewell, for ever.")
TEMPLATE = "xx-uu-u-u-F"


def chat(c, pid, message, minutes, t0, record, label):
    """One chat turn on the poem: records the agent's tool calls, text length, candidates and cost."""
    out = {"label": label, "message": message, "tools": [], "candidates": [], "text_chars": 0, "first_text_s": None, "cost_usd": 0.0}
    deadline = time.perf_counter() + minutes * 60
    with c.stream("POST", f"/api/composer/poems/{pid}/chat", json={"message": message}, timeout=minutes * 60 + 30) as s:
        s.raise_for_status()
        for line in s.iter_lines():
            if time.perf_counter() > deadline:
                break
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            k = ev.get("type")
            stamp = round(time.perf_counter() - t0, 1)
            if k == "text":
                out["first_text_s"] = out["first_text_s"] or stamp
                out["text_chars"] += len(ev.get("text") or ev.get("delta") or "")
            elif k == "tool":
                out["tools"].append(ev.get("name"))
                print(f"  [{stamp}s] tool {ev.get('name')}: {str(ev.get('summary') or '')[:100]}", flush=True)
            elif k == "candidate":
                out["candidates"].append({"t": stamp, "greek": ev.get("greek"), "english_span": ev.get("english_span")})
            elif k == "done":
                out["cost_usd"] = float(ev.get("cost_usd") or 0)
                out["final_chars"] = len(ev.get("text") or ev.get("content") or "")
                break
            elif k == "error":
                out.setdefault("errors", []).append(ev)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    record["chat"] = out
    print(f"{label}: {len(out['tools'])} tool calls {Counter(out['tools']).most_common(6)}, {out['text_chars']} chars, "
          f"{len(out['candidates'])} candidates, first text {out['first_text_s']}s, {out['seconds']}s, ${out['cost_usd']:.3f}", flush=True)
    return out


def stream(c, pid, body, minutes, t0, record, label):
    out = {"label": label, "body": body, "candidates": [], "rejected": 0, "rejected_by": Counter(), "tools": [], "first_s": None,
           "cost_usd": 0.0, "fills": []}
    deadline = time.perf_counter() + minutes * 60
    with c.stream("POST", f"/api/composer/poems/{pid}/pool", json=body, timeout=minutes * 60 + 30) as s:
        s.raise_for_status()
        for line in s.iter_lines():
            if time.perf_counter() > deadline or not line.startswith("data:"):
                if time.perf_counter() > deadline:
                    break
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            k = ev.get("type")
            stamp = round(time.perf_counter() - t0, 1)
            if k == "candidate":
                out["first_s"] = out["first_s"] or stamp
                fits = (ev.get("scansion") or {}).get("fit") or []
                out["candidates"].append({"t": stamp, "greek": ev.get("greek"), "english_span": ev.get("english_span"), "mode": ev.get("mode"),
                                          "slot_key": ev.get("slot_key"), "line_position": ev.get("line_position"),
                                          "whole_line": bool(fits) and fits[-1].get("remaining_template") == "",
                                          "pattern": fits[0].get("pattern") if fits else None})
                print(f"  [{stamp}s] {ev.get('mode')} L{ev.get('line_position')}: {ev.get('greek')!r} ({ev.get('english_span')})", flush=True)
            elif k == "rejected":
                out["rejected"] += int(ev.get("count") or 0)
                out["rejected_by"].update(ev.get("reasons") or {})
            elif k == "tool":
                out["tools"].append(ev.get("name"))
            elif k == "fill":
                out["fills"].append({"t": stamp, **{x: ev.get(x) for x in ("slot_key", "mode", "cold", "cost_usd", "terminal_reason", "shared")}})
            elif k == "done":
                out["cost_usd"] = float(ev.get("cost_usd") or 0)
                break
            elif k == "error":
                out.setdefault("errors", []).append(ev)
                print(f"  [{stamp}s] error: {ev}", flush=True)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    out["rejected_by"] = dict(out["rejected_by"])
    out["whole_lines"] = sum(1 for x in out["candidates"] if x["whole_line"])
    record["runs"].append(out)
    print(f"{label}: {len(out['candidates'])} passed ({out['whole_lines']} whole lines), {out['rejected']} rejected {out['rejected_by']}, "
          f"first {out['first_s']}s, {out['seconds']}s, ${out['cost_usd']:.3f}, tools {Counter(out['tools']).most_common(4)}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--source", default="plain", choices=["plain", "allusive"])
    ap.add_argument("--chat", action="store_true", help="open with a chat turn asking for the source's Catullan echoes")
    args = ap.parse_args()
    english = ENGLISH_ALLUSIVE if args.source == "allusive" else ENGLISH
    password = (DEV / "secrets" / "owner_password.txt").read_text().strip()
    record = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": args.source, "english": english, "runs": []}
    jar: dict = {}

    def keep(r):
        for sc in r.headers.get_list("set-cookie"):
            name, _, rest = sc.partition("=")
            jar[name.strip()] = rest.split(";", 1)[0]

    with httpx.Client(base_url=API, timeout=60, event_hooks={"response": [keep]}) as c:
        c.cookies = None
        token = c.get("/api/owner/login-token").json()["token"]
        c.post("/api/owner/login", json={"username": "Owner", "password": password}, headers={"Origin": API, "X-Melos-CSRF": token}, cookies=jar).raise_for_status()
        c.headers["Origin"] = API
        c.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        poem = c.post("/api/composer/poems", json={"title": f"{args.source} source (pool measurement)", "english": english,
                                                   "settings": {"language": "la", "author": "Catullus", "metre": "phalaecian", "dialect": ""}}).json()
        pid = poem["id"]
        record["poem_id"] = pid
        if args.chat:
            t0 = time.perf_counter()
            chat(c, pid, "Which poems of Catullus does this English echo? For each echo give the Latin phrase (checked with "
                         "the tools: attested forms, the headword's use by Catullus, a concordance line) and say which "
                         "phrases could be reused whole in a Phalaecian hendecasyllable.", args.minutes, t0, record, "chat: echoes")
        # A: next words at line 1, first request of the poem (starts the research; a cold words fill runs alongside)
        t0 = time.perf_counter()
        a = stream(c, pid, {"caret": {"line_position": 0, "char_offset": 0, "prefix": ""}, "prefix": "", "remaining_template": TEMPLATE,
                            "n": 8, "ahead_lines": 0, "mode": "words"}, args.minutes, t0, record, "A words L1 (cold, research starting)")
        # B: whole lines for line 1 and the next 3 lines (stanza batch, forked from the research)
        t0 = time.perf_counter()
        b = stream(c, pid, {"caret": {"line_position": 0, "char_offset": 0, "prefix": ""}, "prefix": "", "remaining_template": TEMPLATE,
                            "n": 6, "ahead_lines": 3, "mode": "line"}, args.minutes, t0, record, "B lines L1 + 3 ahead")
        # accept the first whole line of line 1
        first = next((x for x in b["candidates"] if x["whole_line"] and x["line_position"] in (0, None)), None)
        if first:
            line = c.post(f"/api/composer/poems/{pid}/lines", json={"position": 0, "greek": first["greek"], "source": "agent"}).json()
            record["accepted_line_1"] = first["greek"]
            words = first["greek"].split()
            prefix = " ".join(words[:2])
            # C: next words mid-line 1 with a two-word prefix (elision across the caret possible)
            scan = c.post("/api/scan", json={"text": prefix, "language": "la", "lexicon": True}).json()
            used = len(scan["units"])
            t0 = time.perf_counter()
            stream(c, pid, {"line_id": line.get("id"), "caret": {"line_position": 0, "char_offset": len(prefix), "prefix": prefix}, "prefix": prefix,
                            "remaining_template": TEMPLATE[used:], "n": 8, "ahead_lines": 0, "mode": "words"}, args.minutes, t0, record,
                   f"C words mid-L1 after {prefix!r} ({used} syllables used)")
            # D: whole lines for line 2 (line 1 now written), forked
            t0 = time.perf_counter()
            stream(c, pid, {"caret": {"line_position": 1, "char_offset": 0, "prefix": ""}, "prefix": "", "remaining_template": TEMPLATE,
                            "n": 6, "ahead_lines": 0, "mode": "line"}, args.minutes, t0, record, "D lines L2 after an accepted L1")
        record["total_cost_usd"] = round(sum(r["cost_usd"] for r in record["runs"]), 3)
    out = ROOT / "docs" / "latin" / "pool"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n| Run | First passing | Passed (whole lines) | Rejected (by check) | Time | Cost |")
    print("|---|---|---|---|---|---|")
    for r in record["runs"]:
        print(f"| {r['label']} | {r['first_s']} s | {len(r['candidates'])} ({r['whole_lines']}) | {r['rejected']} {r['rejected_by']} | {r['seconds']} s | ${r['cost_usd']:.2f} |")
    print(f"total ${record['total_cost_usd']}; record {path.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
