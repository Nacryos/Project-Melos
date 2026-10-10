"""Local preview of the composer page against a fake API (no corpus, no agent, no key). Standard library only.

Usage: python3 tools/serve_composer_mock.py [--port 8796]  →  http://127.0.0.1:8796/composer.html

Serves the repo's static files and fakes, in memory: /api/composer/* (poems, lines, versions, pool and chat as SSE with
a short delay per event, back-translation), /api/scan (a rough syllable split, vowel-length guesses), /api/compose/suggest
and /api/analyze-text. --agent-down answers 503 {"agent": "unavailable"} for the agent routes.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = {"poems": {}, "lines": {}, "versions": {}, "chat": [], "next": 1}
CANDIDATES = [
    ("κῆνος ἴσος θέοισιν", "that man, equal to the gods", ["κῆνος: Sappho 31.1", "θέοισιν: Sappho 31.1, Alcaeus 34a"]),
    ("ἀ σελάννα", "the moon", ["σελάννα: Sappho 34, 96, 154"]),
    ("κάλα σελάννα", "the lovely moon", ["κάλα: Sappho 34.1 (κάλαν)"]),
    ("ὀππάτα λάμπῃ", "whenever it shines", ["not in Sappho; ὀππάτα Sappho 22.11"]),
    ("ἄστερες μὲν ἀμφὶ κάλαν σελάνναν", "the stars around the lovely moon", ["Sappho 34.1 (homage)"]),
]
ARGS = None


def nid() -> int:
    DB["next"] += 1
    return DB["next"]


def plain(ch: str) -> str:
    return unicodedata.normalize("NFD", ch)[0].lower()


def scan(text: str) -> dict:
    """Rough: one syllable per vowel group; η ω, diphthongs and circumflexes long, ε ο short, others uncertain."""
    units, lines, i = [], [], 0
    for li, line in enumerate(text.split("\n")):
        offset = sum(len(l) + 1 for l in text.split("\n")[:li])
        idx = []
        for m in re.finditer(r"[^αεηιουωΑΕΗΙΟΥΩἀ-῿άέήίόύώ\s]*[αεηιουωΑΕΗΙΟΥΩἀ-῿άέήίόύώ]+[^αεηιουωΑΕΗΙΟΥΩἀ-῿άέήίόύώ\s]*", line):
            seg = m.group(0)
            vowels = [c for c in seg if plain(c) in "αεηιουω"]
            base = "".join(plain(c) for c in vowels)
            circ = any("͂" in unicodedata.normalize("NFD", c) for c in vowels)
            p = 0.92 if (len(base) > 1 or base in ("η", "ω") or circ or len(seg) - len(vowels) > 2) else 0.12 if base in ("ε", "ο") else 0.5
            label = "L" if p > 0.8 else "S" if p < 0.2 else "A"
            units.append({"i": i, "line": li, "start": offset + m.start(), "end": offset + m.end(),
                          "nucleus": [offset + m.start(), offset + m.start() + 1], "text": seg, "p_long": p, "label": label,
                          "reasons": [{"id": "MOCK", "text": "mock scanner: vowel guess"}], "flags": []})
            idx.append(i)
            i += 1
        if idx:
            lines.append({"line": li, "units": idx, "pattern": "".join({"L": "–", "S": "⏑", "A": "?"}[units[k]["label"]] for k in idx)})
    return {"version": 1, "units": units, "lines": lines, "lexicon": True, "ms": 1.2}


def full(pid: int) -> dict:
    lines = sorted((l for l in DB["lines"].values() if l["poem_id"] == pid), key=lambda l: l["position"])
    out = []
    for l in lines:
        vs = [v for v in DB["versions"].values() if v["line_id"] == l["id"]]
        out.append({**l, "versions": vs, "current": next((v for v in vs if v["id"] == l["current_version_id"]), None)})
    return {"poem": DB["poems"][pid], "lines": out, "chat": [c for c in DB["chat"] if c["poem_id"] == pid]}


def version(line_id: int, greek: str, source: str = "owner", current: bool = True) -> dict:
    pat = "".join(l["pattern"] for l in scan(greek)["lines"])
    v = {"id": nid(), "line_id": line_id, "greek": greek, "back_translation": None, "source": source, "note": "",
         "created_at": time.time(), "archived": False,
         "scansion": {"pass": True, "lines": [{"pattern": pat}], "fit": []},
         "checks": [{"id": "L7", "name": "metre", "ok": True, "blocking": True, "detail": "fits (mock)"},
                    {"id": "L1", "name": "forms", "ok": True, "blocking": True, "detail": "every form found (mock)"},
                    {"id": "L2", "name": "dialect", "ok": "ου" not in greek, "blocking": False, "detail": "mock dialect check"},
                    {"id": "L4", "name": "attestation", "ok": True, "blocking": False, "detail": "mock"}]}
    DB["versions"][v["id"]] = v
    if current:
        DB["lines"][line_id]["current_version_id"] = v["id"]
    return v


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def sse(self, events, delay=0.35):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for ev in events:
                time.sleep(delay)
                self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/composer/poems":
            return self.send_json({"poems": sorted(DB["poems"].values(), key=lambda p: -p["updated_at"])})
        m = re.fullmatch(r"/api/composer/poems/(\d+)/full", path)
        if m:
            return self.send_json(full(int(m[1])))
        if re.fullmatch(r"/api/composer/poems/(\d+)/pool", path):      # stored candidates: none in the mock
            return self.send_json({"pool": []})
        if path in ("/composer", "/"):
            self.path = "/composer.html"
        return super().do_GET()

    def do_PATCH(self):
        b, path = self.body(), self.path
        m = re.fullmatch(r"/api/composer/poems/(\d+)", path)
        if m:
            p = DB["poems"][int(m[1])]
            p.update({k: v for k, v in b.items() if v is not None}, updated_at=time.time())
            return self.send_json(p)
        m = re.fullmatch(r"/api/composer/versions/(\d+)", path)
        if m:
            v = DB["versions"][int(m[1])]
            line = DB["lines"][v["line_id"]]
            if b.get("archived") is not None:
                v["archived"] = b["archived"]
                if b["archived"] and line["current_version_id"] == v["id"]:
                    live = sorted((x for x in DB["versions"].values() if x["line_id"] == line["id"] and not x["archived"]), key=lambda x: -x["id"])
                    line["current_version_id"] = live[0]["id"] if live else None
            if b.get("back_translation") is not None:
                v["back_translation"] = b["back_translation"]
            if b.get("make_current"):
                line["current_version_id"] = v["id"]
            return self.send_json(v)
        self.send_json({"detail": "not found"}, 404)

    def do_POST(self):
        b, path = self.body(), self.path
        if path == "/api/scan":
            return self.send_json(scan(b.get("text", "")))
        if path == "/api/analyze-text":
            return self.send_json({"words": []})
        if path == "/api/compose/suggest":
            return self.send_json({"target": {"template": None}, "candidates": [
                {"greek": "ἄστερες μὲν ἀμφὶ κάλαν σελάνναν", "verdict": "pass", "fit": {"pattern": "–⏑–––⏑⏑–⏑––"},
                 "source": {"author": "Sappho", "citation": "34.1"}, "checks": [{"id": "L7", "verdict": "info", "message": "mock"}]}]})
        if path == "/api/composer/poems":
            pid = nid()
            DB["poems"][pid] = {"id": pid, "title": b.get("title", ""), "settings": b.get("settings", {}), "english": b.get("english", ""),
                                "created_at": time.time(), "updated_at": time.time(), "archived": False}
            return self.send_json(DB["poems"][pid])
        m = re.fullmatch(r"/api/composer/poems/(\d+)/lines", path)
        if m:
            pid = int(m[1])
            pos = b.get("position")
            count = sum(1 for l in DB["lines"].values() if l["poem_id"] == pid)
            pos = count if pos is None else min(pos, count)
            for l in DB["lines"].values():
                if l["poem_id"] == pid and l["position"] >= pos:
                    l["position"] += 1
            lid = nid()
            DB["lines"][lid] = {"id": lid, "poem_id": pid, "position": pos, "current_version_id": None}
            out = dict(DB["lines"][lid])
            if b.get("greek"):
                out["version"] = version(lid, b["greek"], b.get("source", "owner"))
                out["current_version_id"] = out["version"]["id"]
            return self.send_json(out)
        m = re.fullmatch(r"/api/composer/lines/(\d+)/versions", path)
        if m:
            return self.send_json(version(int(m[1]), b["greek"], b.get("source", "owner"), b.get("make_current", True)))
        agent = re.fullmatch(r"/api/composer/(?:poems/(\d+)/(pool|chat|warm)|backtranslate)", path)
        if agent and ARGS.agent_down:
            return self.send_json({"agent": "unavailable", "detail": "the agent service is not reachable (ConnectError)"}, 503)
        if agent and agent[2] == "warm":
            return self.send_json({"started": False, "reason": "mock"}, 200)
        if path == "/api/composer/backtranslate":
            time.sleep(0.8)
            return self.send_json({"english": f"(mock) {len(b['greek'].split())} Greek words, rendered literally", "cost_usd": 0.021})
        if agent and agent[2] == "pool":
            cands = [{"type": "candidate", "greek": g, "english_span": e, "evidence": ev, "slots": "",
                      "checks": [{"id": "L7", "name": "metre", "ok": True, "blocking": True, "detail": "fits"}],
                      "scansion": {"fit": [{"remaining_template": "x"}]}} for g, e, ev in CANDIDATES]
            return self.sse([{"type": "tool", "name": "lemma_search", "summary": "σελάννα"}, {"type": "tool", "name": "scan"},
                             *cands, {"type": "rejected", "count": 3, "reasons": {"L7": 2, "L2": 1}},
                             {"type": "done", "usage": {"input_tokens": 9000, "output_tokens": 1500}, "cost_usd": 0.165}])
        if agent and agent[2] == "chat":
            pid = int(agent[1])
            DB["chat"].append({"id": nid(), "poem_id": pid, "role": "user", "content": b["message"], "trace": None, "created_at": time.time()})
            words = "In Sappho the moon is σελάννα (fr. 34, 96, 154). Two Lesbian options that scan as the next stretch: ".split(" ")
            trace = [{"type": "tool", "name": "lemma_search", "summary": "σελήνη, author Sappho"}, {"type": "tool", "name": "concordance"},
                     {"type": "tool", "name": "lemma_search"}]
            cands = [{"type": "candidate", "greek": g, "english_span": e, "evidence": ev} for g, e, ev in CANDIDATES[1:3]]
            done = {"type": "done", "usage": {"input_tokens": 14200, "output_tokens": 820}, "cost_usd": 0.183}
            DB["chat"].append({"id": nid(), "poem_id": pid, "role": "assistant", "content": " ".join(words), "created_at": time.time(),
                               "trace": [{"event": e["type"], "data": e} for e in [*trace, *cands, done]]})
            return self.sse([*trace, *({"type": "text", "delta": w + " "} for w in words), *cands, done], delay=0.08)
        self.send_json({"detail": "not found"}, 404)


def main():
    global ARGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--agent-down", action="store_true")
    ARGS = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
