#!/usr/bin/env python3
"""End-to-end check of the Latin composer loop on the local dev stack (scripts/latin_dev_stack.sh):
sign in as the owner, create a Latin poem (Catullus, Phalaecian hendecasyllables) with an English source, ask the
pool for the first line, read the streamed candidates (each already linted by melos-api's Latin bank), save the first
passing one as the line's version, and report what the saved version's checks say, with seconds and dollars.

Usage: .venv/bin/python scripts/latin_e2e.py [--english "..."] [--n 3] [--mode line|words] [--minutes 8]
Writes docs/latin/e2e/<timestamp>.json (the run record) and prints a plain summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "private" / "dev-stack"
API = "http://127.0.0.1:8797"
ENGLISH = ("Come, friends, tonight we drink the dark Falernian; tomorrow the rain can keep the whole city to itself.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--english", default=ENGLISH)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--mode", default="line", choices=["line", "words"])
    ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--title", default="Falernian (e2e)")
    args = ap.parse_args()
    password = (DEV / "secrets" / "owner_password.txt").read_text().strip()
    record = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "english": args.english, "events": [],
              "settings": {"language": "la", "author": "Catullus", "metre": "phalaecian", "dialect": ""}}
    t0 = time.perf_counter()
    # The site's cookies are Secure; over the dev stack's plain http the jar would drop them, so they are carried by hand.
    jar: dict = {}

    def keep(r):
        for sc in r.headers.get_list("set-cookie"):
            name, _, rest = sc.partition("=")
            jar[name.strip()] = rest.split(";", 1)[0]

    with httpx.Client(base_url=API, timeout=60, event_hooks={"response": [keep]}) as c:
        c.cookies = None
        r = c.get("/api/owner/login-token")
        token = r.json()["token"]
        r = c.post("/api/owner/login", json={"username": "Owner", "password": password}, headers={"Origin": API, "X-Melos-CSRF": token}, cookies=jar)
        r.raise_for_status()
        c.headers["Origin"] = API
        c.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        poem = c.post("/api/composer/poems", json={"title": args.title, "settings": record["settings"], "english": args.english}).json()
        pid = poem["id"]
        record["poem_id"] = pid
        body = {"caret": {"line_position": 0, "char_offset": 0, "prefix": ""}, "prefix": "", "remaining_template": "xx-uu-u-u-F",
                "n": args.n, "ahead_lines": 0, "mode": args.mode}
        candidates, rejected, tools, first_ms, cost = [], 0, [], None, 0.0
        deadline = time.perf_counter() + args.minutes * 60
        with c.stream("POST", f"/api/composer/poems/{pid}/pool", json=body, timeout=args.minutes * 60 + 30) as s:
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
                kind = ev.get("type")
                stamp = round(time.perf_counter() - t0, 1)
                if kind == "candidate":
                    if first_ms is None:
                        first_ms = stamp
                    candidates.append(ev)
                    record["events"].append({"t": stamp, "type": "candidate", "greek": ev.get("greek"), "english_span": ev.get("english_span"),
                                             "checks": [(ch.get("id"), ch.get("ok")) for ch in ev.get("checks", [])],
                                             "pattern": (ev.get("scansion") or {}).get("fit", [{}])[0].get("pattern") if (ev.get("scansion") or {}).get("fit") else None})
                    print(f"[{stamp}s] candidate: {ev.get('greek')!r}  ({ev.get('english_span')})", flush=True)
                elif kind == "rejected":
                    rejected += int(ev.get("count") or 0)
                    record["events"].append({"t": stamp, "type": "rejected", "count": ev.get("count"), "reasons": ev.get("reasons")})
                    print(f"[{stamp}s] rejected {ev.get('count')}: {ev.get('reasons')}", flush=True)
                elif kind == "tool":
                    tools.append(ev.get("name"))
                    record["events"].append({"t": stamp, "type": "tool", "name": ev.get("name"), "summary": (ev.get("summary") or "")[:120]})
                elif kind in ("fill", "done", "error"):
                    record["events"].append({"t": stamp, "type": kind, **{k: v for k, v in ev.items() if k != "type"}})
                    if kind == "done":
                        cost = float(ev.get("cost_usd") or 0)
                        break
                    if kind == "error":
                        print(f"[{stamp}s] error: {ev}", flush=True)
        elapsed = round(time.perf_counter() - t0, 1)
        accepted = None

        def whole_line(ev) -> bool:
            """The candidate fills every open slot (its fit leaves no template) and its metre check passed."""
            fits = (ev.get("scansion") or {}).get("fit") or []
            l7 = next((ch for ch in ev.get("checks", []) if ch.get("id") == "L7"), {})
            return bool(fits) and fits[-1].get("remaining_template") == "" and l7.get("ok") is True

        full = [ev for ev in candidates if whole_line(ev)]
        if full or candidates:
            best = (full or candidates)[0]
            line = c.post(f"/api/composer/poems/{pid}/lines", json={"position": 0, "greek": best["greek"], "source": "agent",
                                                                     "note": "e2e: first passing candidate of the pool"}).json()
            full = c.get(f"/api/composer/poems/{pid}/full").json()
            saved = next((l for l in full.get("lines", []) if l.get("id") == line.get("id")), line)
            accepted = {"line_id": line.get("id"), "greek": best["greek"], "english_span": best.get("english_span"),
                        "version": saved.get("version") or line.get("version")}
        record.update({"seconds": elapsed, "first_candidate_seconds": first_ms, "candidates": len(candidates),
                       "whole_line_candidates": len(full) if candidates else 0, "rejected": rejected,
                       "tools": tools, "cost_usd": cost, "accepted": accepted})
    out = ROOT / "docs" / "latin" / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(candidates)} passing candidate(s) ({record['whole_line_candidates']} whole lines), {rejected} rejected, first at {first_ms}s, {elapsed}s in all, ${cost:.3f}; tools: {tools[:12]}")
    if accepted:
        v = accepted["version"] or {}
        print("accepted:", accepted["greek"], "|", accepted["english_span"])
        print("saved version checks:", [(ch.get("id"), ch.get("ok")) for ch in (v.get("checks") or [])], "pattern:",
              ((v.get("scansion") or {}).get("fit") or [{}])[0].get("pattern"))
    print("record:", path.relative_to(ROOT))
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
