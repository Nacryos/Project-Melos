#!/usr/bin/env python3
"""Fetch the open-access Thesaurus Linguae Latinae PDFs and build data/lexica/lex_tll.sqlite (docs/latin/lexica-tll.md).

The Bayerische Akademie der Wissenschaften lists the open volumes on
https://thesaurus.badw.de/en/tll-digital/tll-open-access.html; the PDFs sit on publikationen.badw.de ("License: CC
BY-NC-ND"). Private use: the PDFs (data/raw/) and the store (data/lexica/) stay local, only the manifest
data/open/latin/lexica/tll.json is committed.

    .venv/bin/python scripts/ingest_tll_la.py --fetch          # download what is missing (resumable)
    .venv/bin/python scripts/ingest_tll_la.py --build          # text layer -> lex_tll.sqlite + manifest
    .venv/bin/python scripts/ingest_tll_la.py --check          # the 30-lemma precision sample
    .venv/bin/python scripts/ingest_tll_la.py --pdf FILE.pdf --name old --title "Oxford Latin Dictionary"
                                                               # any dictionary PDF the owner supplies

Store: pages (one row per PDF page, with the printed column numbers and the running-head lemmata where the text layer
gives them, FTS5 over the text), entries (articles segmented by headword), meta. Needs pymupdf.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_dictionary import fold  # noqa: E402

RAW = ROOT / "data/raw/latin/lexica/tll"
LEXICA = ROOT / "data/lexica"
OUT = LEXICA / "lex_tll.sqlite"
MANIFEST = ROOT / "data/open/latin/lexica/tll.json"
FETCH_LOG = ROOT / "data/raw/latin/fetch-log.jsonl"
VOLUMES = RAW / "volumes.json"            # local state: one record per PDF (url, file, sha256, bytes)
INDEX_URL = "https://thesaurus.badw.de/en/tll-digital/tll-open-access.html"
LICENCE_URL = "https://publikationen.badw.de/en/thesaurus"
LICENCE = "Lizenz License : CC BY-NC-ND"                      # as printed on LICENCE_URL
ACCESS_NOTE = ("In consultation with the publisher De Gruyter, we offer here an Open Access PDF version (organized by "
               "volumes and lemmas) of the previously published volumes A - M and O - P, as well as parts of N and R. "
               "Access is free of charge.")                    # as printed on INDEX_URL
USER_AGENT = "Melos/1.0 (+https://greeklyric.com)"
DELAY = 1.0                                                    # seconds between requests to one host
_last: dict[str, float] = {}
_PDF = re.compile(r'href="(https?://publikationen\.badw\.de/[^"]+?\.pdf)"')
_NAME = re.compile(r"\{ThLL vol\. (?P<vol>.+?) col\. (?P<c0>\d+)[–-](?P<c1>\d+) \((?P<h0>.+?)[–-](?P<h1>.+?)\)\}")


# ---------------------------------------------------------------- fetch
def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_fetch(url: str, path: Path, status: int, note: str, sha: str = "", size: int = 0) -> None:
    FETCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        shown = str(path.relative_to(ROOT))
    except ValueError:
        shown = str(path)
    row = {"url": url, "path": shown, "bytes": size, "sha256": sha, "fetched_at": now(), "http_status": status,
           "licence_note": note}
    with FETCH_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def polite(url: str) -> None:
    host = urllib.parse.urlsplit(url).netloc
    wait = _last.get(host, 0) + DELAY - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def download(url: str, dest: Path, note: str, tries: int = 6) -> int:
    """GET url into dest (through dest.part, resumed with Range). Returns the HTTP status; logs every attempt."""
    part = dest.with_name(dest.name + ".part")
    for attempt in range(tries):
        polite(url)
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                status = r.status
                mode = "ab" if (have and status == 206) else "wb"
                with part.open(mode) as f:
                    while block := r.read(1 << 20):
                        f.write(block)
            part.replace(dest)
            log_fetch(url, dest, status, note, sha256(dest), dest.stat().st_size)
            return status
        except urllib.error.HTTPError as e:
            log_fetch(url, dest, e.code, note + f"; HTTP error {e.code}")
            if e.code == 416 and have:           # the part is already the whole file
                part.replace(dest)
                log_fetch(url, dest, 200, note + "; completed from part", sha256(dest), dest.stat().st_size)
                return 200
            if e.code in (429, 503):
                time.sleep(min(300, 15 * 2 ** attempt))
                continue
            if e.code in (401, 403, 404, 451):   # a refusal: report, do not retry
                return e.code
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            log_fetch(url, dest, 0, note + f"; {type(e).__name__}: {e}"[:200])
            time.sleep(5 * (attempt + 1))
    return 0


def local_name(url: str) -> tuple[str, dict]:
    decoded = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    m = _NAME.search(decoded)
    if not m:
        return re.sub(r"[^A-Za-z0-9.]+", "_", decoded), {}
    d = m.groupdict()
    vol = d["vol"].replace(",", ".").replace(" ", "")
    info = {"volume": vol, "col_from": int(d["c0"]), "col_to": int(d["c1"]), "head_from": d["h0"], "head_to": d["h1"]}
    return f"tll_{vol}_col{d['c0']}-{d['c1']}_{fold(d['h0'])}-{fold(d['h1'])}.pdf", info


PDF_NOTE = ("Thesaurus Linguae Latinae open access PDF, BAdW; CC BY-NC-ND per publikationen.badw.de/en/thesaurus; "
            "private use, not redistributed")


def is_pdf(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as f:
        return f.read(5) == b"%PDF-"


def resolve(record: str, info: dict, base: str) -> str | None:
    """The PDF link on a volume's record page that has the wanted columns and lemmata."""
    found = []
    for href in re.findall(r'href="([^"]+?\.pdf)"', record):
        u = urllib.parse.urljoin(base, html.unescape(href))
        m = _NAME.search(urllib.parse.unquote(u))
        if not m:
            continue
        heads = (fold(m["h0"]), fold(m["h1"])) == (fold(info.get("head_from", "")), fold(info.get("head_to", "")))
        cols = (int(m["c0"]), int(m["c1"])) == (info.get("col_from"), info.get("col_to"))
        if heads or cols:
            found.append((heads + cols, u))
    return max(found)[1] if found else None


def fetch_all(only: str = "") -> list[dict]:
    RAW.mkdir(parents=True, exist_ok=True)
    index = RAW / "tll-open-access.html"
    status = download(INDEX_URL, index, "TLL open access index page (BAdW); lists the open PDFs")
    if status != 200 and not index.exists():
        raise SystemExit(f"index page: HTTP {status}")
    download(LICENCE_URL, RAW / "publikationen-thesaurus.html", "BAdW publication record of the TLL open access; states 'License: CC BY-NC-ND'")
    urls = []
    for u in _PDF.findall(index.read_text(encoding="utf-8", errors="replace")):
        u = html.unescape(u).replace("http://", "https://")
        if u not in urls:
            urls.append(u)
    state = {v["url"]: v for v in json.loads(VOLUMES.read_text())} if VOLUMES.exists() else {}
    for n, url in enumerate(urls, 1):
        name, info = local_name(url)
        if only and only not in name:
            continue
        dest = RAW / name
        rec = state.get(url, {})
        if is_pdf(dest) and rec.get("sha256") and rec.get("bytes") == dest.stat().st_size:
            continue
        source, status = rec.get("resolved_url") or url, 200
        if not dest.exists():
            status = download(source, dest, PDF_NOTE)
        if dest.exists() and not is_pdf(dest):
            # A stale link on the index page ("vol. 06.2" for "vol. 06,2"): the server answers with the volume's
            # record page, which carries the real link.
            record = dest.with_suffix(".record.html")
            dest.replace(record)
            source = resolve(record.read_text(encoding="utf-8", errors="replace"), info, url)
            status = download(source, dest, PDF_NOTE + "; link taken from the volume's record page") if source else 0
        if not is_pdf(dest):
            print(f"[{n}/{len(urls)}] FAILED {status} {name}", flush=True)
            dest.unlink(missing_ok=True)
            state[url] = {"url": url, "file": name, **info, "http_status": status}
        else:
            state[url] = {"url": url, "resolved_url": source, "file": name, **info, "bytes": dest.stat().st_size,
                          "sha256": sha256(dest), "is_pdf": True, "retrieved": now()}
            print(f"[{n}/{len(urls)}] {state[url]['bytes'] / 1e6:8.1f} MB  {name}", flush=True)
        VOLUMES.write_text(json.dumps(list(state.values()), ensure_ascii=False, indent=1))
    return list(state.values())


# ---------------------------------------------------------------- text layer
WATERMARK = re.compile(r"digiti[sz]ed by Thesaurus|^\W*Linguae Latinae\W*$", re.I)
MAX_ENTRY_CHARS = 30000          # an article's stored text stops here; n_chars keeps the full length
_HYPHEN = re.compile(r"(?<=[A-Za-z])-\n(?=[a-z])")
_NUM = re.compile(r"(?<![\dA-Za-z])(\d{1,4})(?![\dA-Za-z])")
_FIRST = re.compile(r"[A-Za-zÀ-ɏ]+")
_LONG = re.compile(r"([A-Za-z])\u00af")
_SHORT = re.compile(r"([A-Za-z])\u02d8")
BINS = 240


def clean(text: str) -> str:
    """Recent fascicles print a macron or breve as a spacing sign after the vowel, and i as a dotless i."""
    if "\u00af" in text or "\u02d8" in text or "\u0131" in text:
        text = _SHORT.sub("\\1\u0306", _LONG.sub("\\1\u0304", text.replace("\u0131", "i")))
        text = unicodedata.normalize("NFC", text)
    return text


def to_lines(words: list) -> list[tuple[float, float, str]]:
    """Words of one column -> visual lines (x0, y centre, text), top to bottom."""
    if not words:
        return []
    heights = sorted(w[3] - w[1] for w in words)
    h = heights[len(heights) // 2] or 1.0
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    groups, cur, cy = [], [], 0.0
    for w in words:
        y = (w[1] + w[3]) / 2
        if cur and y - cy > 0.6 * h:
            groups.append(cur)
            cur = []
        cur.append(w)
        cy = y if len(cur) == 1 else cy + (y - cy) / len(cur)
    groups.append(cur)
    out = []
    for g in groups:
        g.sort(key=lambda w: w[0])
        out.append((g[0][0], sum((w[1] + w[3]) / 2 for w in g) / len(g), clean(" ".join(w[4] for w in g))))
    return out


def head_of(line: tuple, height: float) -> tuple[int | None, str] | None:
    """A column's first line, if it is a running head: (printed number or None, head word)."""
    _, y, text = line
    if y > 0.085 * height or len(text) > 48:
        return None
    nums = _NUM.findall(text)
    word = " ".join(_FIRST.findall(_NUM.sub(" ", text)))
    if not nums and not (word.isupper() and len(word) > 1):
        return None
    if len(word) > 40 or (not nums and len(word.split()) > 3):
        return None
    return (int(nums[0]) if nums else None), (fold(word) if word.isupper() else word.lower())


def page_layout(page) -> dict:
    """One PDF page -> columns of lines, the running heads and the printed column numbers the text layer gives.

    The gutter is the emptiest vertical strip near the middle; the line numbers the TLL prints in it are dropped.
    """
    width, height = page.rect.width, page.rect.height
    words = [w for w in page.get_text("words") if w[4].strip()]
    if not words or width <= 0:
        return {"two": False, "cols": [[]], "heads": [None]}
    cov = [0] * BINS
    for w in words:
        for i in range(max(0, int(w[0] / width * BINS)), min(BINS - 1, int(w[2] / width * BINS)) + 1):
            cov[i] += 1
    inner = sorted(cov[int(0.12 * BINS):int(0.88 * BINS)])
    med = inner[len(inner) // 2]
    lo, hi = int(0.38 * BINS), int(0.62 * BINS)
    m = min(range(lo, hi), key=lambda i: (cov[i], abs(i - BINS / 2)))
    two = med >= 8 and cov[m] <= 0.25 * med
    if two:
        a = b = m
        while a > lo and cov[a - 1] <= 0.4 * med:
            a -= 1
        while b < hi and cov[b + 1] <= 0.4 * med:
            b += 1
        g0, g1 = a / BINS * width, (b + 1) / BINS * width
        mid = (m + 0.5) / BINS * width
        # the gutter runs from the left column's right margin to the right column's left margin
        ends = sorted(w[2] for w in words if (w[0] + w[2]) / 2 < mid and len(w[4]) > 3)
        starts = sorted(w[0] for w in words if (w[0] + w[2]) / 2 >= mid and len(w[4]) > 3)
        if len(ends) > 50 and len(starts) > 50:
            g0 = min(g0, ends[int(0.99 * (len(ends) - 1))] + 2)
            g1 = max(g1, starts[int(0.01 * (len(starts) - 1))] - 2)
        sides: list[list] = [[], []]
        for w in words:
            if w[0] >= g0 - 1 and w[2] <= g1 + 1 and len(w[4]) <= 3:
                continue                                  # a line number in the gutter
            sides[0 if (w[0] + w[2]) / 2 < mid else 1].append(w)
    else:
        sides = [words]
    cols, heads = [], []
    for ws in sides:
        lines = [ln for ln in to_lines(ws) if not WATERMARK.search(ln[2])]
        head = head_of(lines[0], height) if lines else None
        if head:
            lines = lines[1:]
        cols.append(lines)
        heads.append(head)
    return {"two": two, "cols": cols, "heads": heads}


def settle_columns(pages: list[dict]) -> None:
    """Printed column numbers: a page keeps a number only when its neighbours agree (two columns a page)."""
    offsets: dict[int, list[int]] = {}
    for i, p in enumerate(pages):
        c = []
        if p["two"]:
            if p["heads"][0] and p["heads"][0][0] is not None:
                c.append(p["heads"][0][0] - 2 * i)
            if p["heads"][1] and p["heads"][1][0] is not None:
                c.append(p["heads"][1][0] - 1 - 2 * i)
        offsets[i] = c
    for i, p in enumerate(pages):
        p["col_from"] = p["col_to"] = None
        if not p["two"]:
            continue
        before = [o for j in range(i - 6, i) for o in offsets.get(j, [])]
        after = [o for j in range(i + 1, i + 7) for o in offsets.get(j, [])]
        votes = before + offsets[i] + after
        if not votes:
            continue
        mode, count = max(((o, votes.count(o)) for o in set(votes)), key=lambda t: t[1])
        here, was, will = mode in offsets[i], mode in before, mode in after
        if count >= 3 and (here or (was and will)) and 2 * i + mode >= 1:
            p["col_from"], p["col_to"] = 2 * i + mode, 2 * i + mode + 1
            p["col_read"] = here


def distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


NOT_HEADWORDS = frozenset({"lemmata", "addenda", "corrigenda", "addenda et corrigenda", "index", "praefatio", "contents"})


def title_forms(title: str) -> list[str]:
    """A bookmark such as 'abaeto, abito' or '(abaestumo)' -> folded forms, the first being the main one."""
    out = []
    for part in re.split(r"[,;/=]|\bvel\b|\bet\b", title):
        part = part.strip()
        if part.startswith("-"):
            continue
        key = fold(part)
        if key and key not in out:
            out.append(key)
    return out


_OPENING = re.compile(r"^[^A-Za-z\[(-]{0,3}\s*(?:-|\[|\(|v\.|adv|subst|adi|interi|praep|coni|indecl|nom\.|cogn\.|[nmf]\.)")


def line_matches(text: str, key: str, how: str) -> int | None:
    """Does the line open with the headword? Returns the character offset of the match (0 at a line start).

    exact: the first word is the headword. fuzzy: within OCR tolerance (the bold lemma is what the OCR reads worst).
    opening: either, and what follows looks like an article's opening ("-a, -um", "[", "v."). runin: the headword
    after a full stop inside the line (cross-reference stubs are printed run-in).
    """
    if how != "runin":
        found = _line_matches(text, key, how)
        if found is None and _SIGN.match(text):          # the sign before a major lemma reads as "E"
            found = _line_matches(_SIGN.sub("", text, count=1), key, how)
        return found
    return _line_matches(text, key, how)


_SIGN = re.compile(r"^[^A-Za-z]{0,3}E ?(?=(?:\d\. ?)?[\[?(]*[a-zāēīōū])")


def _spelt(text: str, start: int, key: str) -> bool:
    """The headword read letter by letter from `start` ("e m o ," is emo), ending where the word ends."""
    acc = ""
    for i in range(start, min(len(text), start + 2 * len(key) + 8)):
        acc += fold(text[i])
        if acc == key:
            rest = text[i + 1:].lstrip() if " " in text[start:i + 1] else text[i + 1:]
            return not rest[:1].isalpha()
        if not key.startswith(acc):
            return False
    return False


def _line_matches(text: str, key: str, how: str) -> int | None:
    m = _FIRST.search(text)
    if not m:
        return None
    if how == "runin":
        if len(key) < 3:
            return None
        for w in _FIRST.finditer(text):
            if w.start() and fold(w.group(0)) == key and re.search(r"[.;]\W*$", text[:w.start()]):
                return w.start()
        return None
    if m.start() > 6:
        return None
    token = fold(m.group(0))
    run = fold(text[m.start():m.start() + 2 * len(key) + 8])
    if token == key or (len(key) >= 3 and _spelt(text, m.start(), key)):
        return 0 if how != "opening" or _OPENING.match(text[m.end():]) else None
    if how == "exact" or (how == "opening" and not _OPENING.match(text[m.end():])):
        return None
    tol = 0 if len(key) < 4 else 1 if len(key) < 6 else 2 if len(key) < 9 else 3
    if not tol:
        return None
    if distance(token, key) <= tol or distance(run[:len(key)], key) <= tol:
        return 0
    return 0 if token.endswith(key[1:]) and len(token) <= len(key) + 1 else None    # "foonus" for bonus


def place_bookmarks(marks: list[dict], lines: list[tuple], span: dict[int, tuple[int, int]]) -> None:
    """Find the line each bookmarked headword opens on its page: indented lines first, then the looser tests."""
    by_page: dict[int, list[dict]] = {}
    for mk in marks:
        mk["anchor"], mk["offset"] = None, 0
        by_page.setdefault(mk["page"], []).append(mk)
    for page, group in by_page.items():
        if page not in span:
            continue
        start, end = span[page]
        for how, indented in (("exact", True), ("fuzzy", True), ("opening", False), ("runin", False)):
            same = how == "runin"                         # a run-in headword may share its line with its neighbours
            for n, mk in enumerate(group):
                if mk["anchor"] is not None:
                    continue
                lo = max([g["anchor"] for g in group[:n] if g["anchor"] is not None], default=start - 1) + (0 if same else 1)
                hi = min([g["anchor"] for g in group[n + 1:] if g["anchor"] is not None], default=end - 1) + (1 if same else 0)
                words = mk["title"].split(",")[0].split()
                keys = [k for k in dict.fromkeys([fold(words[0]) if words else "", mk["keys"][0]]) if k]
                weak = None
                for i in range(max(lo, start), min(hi, end)):
                    if indented and not (lines[i][4] or _SIGN.match(lines[i][3])):
                        continue
                    found = next((o for o in (line_matches(lines[i][3], k, how) for k in keys) if o is not None), None)
                    if found is None:
                        continue
                    if how != "exact" or any(line_matches(lines[i][3], k, "opening") is not None for k in keys) \
                            or re.match(r"[^A-Za-z]{0,6}[A-Za-zÀ-ɏ]+ ?,", lines[i][3]):
                        mk["anchor"], mk["offset"] = i, found
                        break
                    weak = weak if weak is not None else i   # "res), quae": the word, but not an article's opening
                else:
                    if weak is not None:
                        mk["anchor"] = weak


def bold_marks(doc, lines: list[tuple], span: dict[int, tuple[int, int]]) -> list[dict]:
    """No bookmarks: take a line that opens in bold type as a headword; kept only if the result runs alphabetically."""
    marks = []
    for pi, page in enumerate(doc):
        if pi not in span:
            continue
        start, end = span[pi]
        if end - start < 5:
            continue
        for block in page.get_text("dict").get("blocks", []):
            for ln in block.get("lines", []):
                spans = [s for s in ln.get("spans", []) if s["text"].strip()]
                bold = lambda sp: bool(sp["flags"] & 16 or "bold" in sp["font"].lower())
                while len(spans) > 1 and not bold(spans[0]) and len(spans[0]["text"].strip()) <= 2:
                    spans = spans[1:]        # a sign printed before the headword
                if not spans:
                    continue
                s = dict(spans[0], text=clean(spans[0]["text"]))
                if not bold(s) or len(spans) < 2 or len(s["text"]) > 40:
                    continue                 # a headword is bold and the line goes on in ordinary type
                m = _FIRST.search(s["text"])
                if not m or len(m.group(0)) < 2 or s["text"].strip().isupper():
                    continue
                title = re.sub(r"[\s,.;:]+$", "", s["text"].strip())
                key = fold(m.group(0))
                y = (s["bbox"][1] + s["bbox"][3]) / 2
                near = [i for i in range(start, end) if abs(lines[i][5] - y) < 6 and key in fold(lines[i][3])[:len(key) + 3]]
                if near:
                    marks.append({"level": 1, "title": title, "page": pi, "keys": title_forms(title) or [key], "anchor": near[0], "offset": 0})
    seen, kept = set(), []
    for mk in marks:
        if mk["anchor"] not in seen:
            seen.add(mk["anchor"])
            kept.append(mk)
    kept.sort(key=lambda mk: mk["anchor"])
    pairs = list(zip(kept, kept[1:]))
    ordered = sum(a["keys"][0][:3] <= b["keys"][0][:3] for a, b in pairs) / len(pairs) if pairs else 0.0
    if len(kept) < 50 or ordered < 0.85:
        print(f"  bold headwords: {len(kept)} found, {ordered:.0%} in alphabetical order: not reliable, entries left empty", flush=True)
        return []
    return kept


def extract_file(job: tuple[str, str, str]) -> dict:
    """One PDF -> page rows and entry rows (worker process)."""
    import pymupdf

    path, volume, headwords = job            # headwords: bookmarks | bold | auto | none
    doc = pymupdf.open(path)
    pages, lines, span = [], [], {}
    for pi, page in enumerate(doc):
        lay = page_layout(page)
        start = len(lines)
        for side, col in enumerate(lay["cols"]):
            xs = sorted(ln[0] for ln in col)
            margin = xs[len(xs) // 5] if xs else 0.0          # a headword opens an indented line
            lines.extend((pi, side, x0, text, x0 - margin > 0.011 * page.rect.width, y) for x0, y, text in col)
        span[pi] = (start, len(lines))
        heads = [h for h in lay["heads"] if h and h[1]]
        pages.append({"two": lay["two"], "heads": lay["heads"],
                      "head_from": heads[0][1] if heads else None, "head_to": heads[-1][1] if heads else None,
                      "text": _HYPHEN.sub("", "\n".join(ln[3] for ln in lines[start:])), "chars": sum(len(ln[3]) for ln in lines[start:])})
    settle_columns(pages)

    def column(i: int) -> int | None:
        p = pages[lines[i][0]]
        return None if p["col_from"] is None else p["col_from"] + lines[i][1]

    marks = [{"level": lvl, "title": re.sub(r"\s+", " ", title).strip(" ,"), "page": pg - 1, "keys": title_forms(title)}
             for lvl, title, pg in doc.get_toc(simple=True) if 0 < pg <= doc.page_count]
    marks = [mk for mk in marks if mk["keys"] and mk["title"].lower() not in NOT_HEADWORDS]
    addenda = [mk for mk in marks if "[ADD]" in mk["title"]]     # these point at the corrigenda pages, out of sequence
    marks = [mk for mk in marks if "[ADD]" not in mk["title"]]
    source = "bookmarks"
    if headwords == "auto":                  # bookmarks count as headwords only when there is about one a page or more
        headwords = "bookmarks" if len(marks) >= doc.page_count else "bold"
    if headwords == "bookmarks":
        place_bookmarks(marks, lines, span)
    elif headwords == "bold":
        marks, source = bold_marks(doc, lines, span), "bold type"
    else:
        marks = []
    entries = []
    for n, mk in enumerate(marks):
        located = mk["anchor"] is not None
        if located:
            start = mk["anchor"]
        else:                                # somewhere on its page after the previous headword
            prev = marks[n - 1] if n and marks[n - 1]["page"] == mk["page"] else None
            start = prev["start"] if prev else span[mk["page"]][0]
        mk["start"] = start
        nxt = next((k for k in marks[n + 1:] if k["level"] <= mk["level"]), None)
        if nxt is None:
            end = span[min(mk["page"] + 2, len(pages) - 1)][1]
        elif nxt["anchor"] is not None:
            end = nxt["anchor"]
        else:
            end = span[nxt["page"]][1]
        end = max(end, start + 1)
        end = min(end, len(lines))
        if start >= len(lines):
            continue
        text = _HYPHEN.sub("", "\n".join(ln[3] for ln in lines[start:end]))[mk.get("offset", 0):]
        sign = re.match(r"([^A-Za-z\[?]*E ?)[\[?]*([A-Za-zÀ-ɏ]+)", text)
        if located and sign and fold(sign.group(2)) == mk["keys"][0]:
            text = text[sign.end(1):]        # the sign the recent fascicles print before a major lemma reads as "E"
        last = max(start, end - 1)
        entries.append({"headword": mk["title"], "keys": mk["keys"], "text": text[:MAX_ENTRY_CHARS], "n_chars": len(text),
                        "col_from": column(start), "col_to": column(last), "page_from": lines[start][0],
                        "page_to": lines[last][0], "level": mk["level"], "located": int(located)})
    for mk in addenda:
        if mk["page"] not in span or span[mk["page"]][0] >= len(lines):
            continue
        start, end = span[mk["page"]]
        text = "\n".join(ln[3] for ln in lines[start:end])
        title = mk["title"].replace("[ADD]", "").strip()
        entries.append({"headword": title + " [addenda]", "keys": title_forms(title) or mk["keys"], "text": text[:MAX_ENTRY_CHARS],
                        "n_chars": len(text), "col_from": column(start), "col_to": column(max(start, end - 1)),
                        "page_from": mk["page"], "page_to": mk["page"], "level": 3, "located": 0})
    n_pages = doc.page_count
    doc.close()
    return {"path": path, "volume": volume, "n_pages": n_pages, "source": source if marks else "none",
            "pages": [{k: p.get(k) for k in ("col_from", "col_to", "head_from", "head_to", "text", "chars", "col_read", "two")} for p in pages],
            "entries": entries}


# ---------------------------------------------------------------- store
SCHEMA = """
CREATE TABLE pages (id INTEGER PRIMARY KEY, volume TEXT, pdf_page INTEGER, col_from INTEGER, col_to INTEGER,
  head_from TEXT, head_to TEXT, text TEXT, file TEXT);
CREATE INDEX pages_volume ON pages(volume, col_from);
CREATE VIRTUAL TABLE pages_fts USING fts5(text, content='pages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TABLE entries (id INTEGER PRIMARY KEY, headword TEXT, folded TEXT, text TEXT, volume TEXT, col_from INTEGER,
  col_to INTEGER, page_from INTEGER, page_to INTEGER, level INTEGER, located INTEGER, n_chars INTEGER, variant_of INTEGER);
CREATE INDEX entries_folded ON entries(folded);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def volume_order(rec: dict) -> tuple:
    vol = rec.get("volume", "")
    nums = [int(x) for x in re.findall(r"\d+", vol)]
    return (vol.startswith("onom"), nums, rec.get("col_from", 0), rec.get("file", ""))


def build(out: Path, jobs: list[tuple[str, str, str]], meta: dict, workers: int) -> dict:
    import multiprocessing as mp

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    stats: dict = {"files": {}, "n_pages": 0, "n_entries": 0, "n_rows": 0, "located": 0, "letters": {}}
    t0 = time.time()
    with mp.get_context("spawn").Pool(max(1, min(workers, len(jobs)))) as pool:
        for res in pool.imap(extract_file, jobs):                # in volume order
            name = Path(res["path"]).name
            page_id: dict[int, int] = {}
            for i, p in enumerate(res["pages"]):
                cur = db.execute("INSERT INTO pages (volume, pdf_page, col_from, col_to, head_from, head_to, text, file) VALUES (?,?,?,?,?,?,?,?)",
                                 (res["volume"], i + 1, p["col_from"], p["col_to"], p["head_from"], p["head_to"], p["text"], name))
                page_id[i] = cur.lastrowid
            located = addenda = 0
            for e in res["entries"]:
                main = None
                for key in e["keys"]:
                    cur = db.execute("INSERT INTO entries (headword, folded, text, volume, col_from, col_to, page_from, page_to, level, located, n_chars, variant_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (e["headword"], key, e["text"], res["volume"], e["col_from"], e["col_to"], page_id[e["page_from"]],
                                      page_id[e["page_to"]], e["level"], e["located"], e["n_chars"], main))
                    main = main or cur.lastrowid
                    stats["n_rows"] += 1
                if e["level"] == 3:
                    addenda += 1
                    continue
                located += e["located"]
                letter = e["keys"][0][0]
                stats["letters"][letter] = stats["letters"].get(letter, 0) + 1
            body = [p for p in res["pages"] if p["two"]]
            stats["files"][name] = {
                "volume": res["volume"], "pages": res["n_pages"], "entries": len(res["entries"]) - addenda, "located": located, "addenda": addenda,
                "headwords_from": res["source"], "two_column_pages": len(body),
                "pages_with_column_numbers": sum(p["col_from"] is not None for p in res["pages"]),
                "column_numbers_read_on_page": sum(bool(p.get("col_read")) for p in res["pages"]),
                "pages_with_running_head": sum(bool(p["head_from"]) for p in res["pages"]),
                "pages_without_text": sum(p["chars"] < 200 for p in res["pages"]),
                "chars": sum(p["chars"] for p in res["pages"])}
            stats["n_pages"] += res["n_pages"]
            stats["n_entries"] += len(res["entries"]) - addenda
            stats["addenda"] = stats.get("addenda", 0) + addenda
            stats["located"] += located
            db.commit()
            f = stats["files"][name]
            print(f"  {name}: {f['pages']} pages, {f['entries']} headwords ({located} placed), columns on {f['pages_with_column_numbers']} pages, {time.time() - t0:.0f}s", flush=True)
    db.execute("INSERT INTO pages_fts (pages_fts) VALUES ('rebuild')")
    stats["letters"] = dict(sorted(stats["letters"].items()))
    meta = {**meta, "n_entries": stats["n_entries"], "n_entry_rows": stats["n_rows"], "n_addenda": stats.get("addenda", 0),
            "n_located": stats["located"], "n_pages": stats["n_pages"],
            "letters": "".join(k for k, n in stats["letters"].items() if n >= 50).upper(),   # stray misfiled titles do not count
            "fts_table": "pages_fts", "built": now(),
            "max_entry_chars": MAX_ENTRY_CHARS}
    db.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    return stats


def build_tll(only: str, workers: int) -> int:
    if not VOLUMES.exists():
        raise SystemExit("no volumes.json: run --fetch first")
    listed = json.loads(VOLUMES.read_text())
    have = sorted((v for v in listed if v.get("sha256") and v.get("is_pdf") and (RAW / v["file"]).exists() and only in v["file"]),
                  key=volume_order)
    missing = [v["file"] for v in listed if v not in have and only in v["file"]]
    if not have:
        raise SystemExit("no PDFs downloaded yet")
    jobs = [(str(RAW / v["file"]), v.get("volume", v["file"]), "auto") for v in have]   # bold type where a file has no bookmarks
    meta = {"name": "tll", "title": "Thesaurus Linguae Latinae (open access PDFs, Bayerische Akademie der Wissenschaften)",
            "language": "la", "direction": "la-la", "source_url": INDEX_URL, "licence": LICENCE_PDF,
            "licence_record": f"{LICENCE} ({LICENCE_URL})", "access_note": ACCESS_NOTE,
            "retrieved": max(v.get("retrieved", "") for v in have)[:10],
            "text_layer": "the publisher's uncorrected OCR (ABBYY FineReader) for scanned volumes; born-digital text for recent fascicles"}
    meta["ranges"] = json.dumps([[v["file"], fold(v.get("head_from") or ""), fold(v.get("head_to") or "")]
                                 for v in have if not str(v.get("volume", "")).startswith("onom")], ensure_ascii=False)
    out = OUT if not only else LEXICA / "lex_tll_partial.sqlite"
    stats = build(out, jobs, meta, workers)
    print(f"{out}: {stats['n_pages']} pages, {stats['n_entries']} headwords ({stats['located']} placed on their line), letters {''.join(k for k, n in stats['letters'].items() if n >= 50).upper()}")
    if missing:
        print("not in:", ", ".join(missing))
    if only:
        return 0
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "tll", "title": meta["title"], "store": "data/lexica/lex_tll.sqlite (local, gitignored)",
        "raw": "data/raw/latin/lexica/tll/ (local, gitignored)", "script": "scripts/ingest_tll_la.py",
        "sources": {"index": INDEX_URL, "record": LICENCE_URL, "pdf_host": "https://publikationen.badw.de/"},
        "access_note": ACCESS_NOTE, "licence_record": f"{LICENCE} ({LICENCE_URL})", "licence_in_each_pdf": LICENCE_PDF,
        "use": "private lookup only; neither the PDFs nor the store is committed or redistributed",
        "retrieved": meta["retrieved"], "n_files": len(have), "n_pages": stats["n_pages"], "n_headwords": stats["n_entries"],
        "n_entry_rows": stats["n_rows"], "headwords_placed_on_their_line": stats["located"], "n_addenda_rows": stats.get("addenda", 0),
        "letters_covered": "".join(k for k, n in stats["letters"].items() if n >= 50).upper(),
        "headwords_by_initial": stats["letters"], "missing": MISSING + ([f"not downloaded: {m}" for m in missing]),
        "volumes": [{"file": v["file"], "url": v["url"], "volume": v.get("volume"), "columns": [v.get("col_from"), v.get("col_to")],
                     "lemmata": [v.get("head_from"), v.get("head_to")], "bytes": v["bytes"], "sha256": v["sha256"],
                     **{k: stats["files"][v["file"]][k] for k in ("pages", "entries", "located", "addenda", "headwords_from", "pages_with_column_numbers",
                                                                 "pages_with_running_head", "pages_without_text", "chars")}}
                    for v in have]}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(MANIFEST)
    return 0


LICENCE_PDF = ("This work is offered to you under a Creative Commons Attribution-NonCommercial-NoDerivs CC BY-NC-ND "
               "license (explanation here). In addition, you are not allowed to print or modify (parts of) this file or "
               "to upload it to a public website (no file-sharing). We kindly ask you to respect these restrictions. "
               "Instead, please refer fellow researchers to our website. Continued access to this version of the ThLL "
               "depends on your acceptance of these conditions. Please also leave this page and the watermark in the "
               "file.")                                        # first page of each PDF
MISSING = ["N after 'netura' (vol. IX 1 in progress)", "Q (not published)", "R after 'resurgo' (vol. XI 2 in progress)",
           "S-Z (not published)", "Onomasticon after D (suspended)"]


def build_pdf(pdf: Path, name: str, title: str, workers: int, headwords: str = "auto") -> int:
    """Any dictionary PDF the owner supplies: pages always, entries when bookmarks or bold headwords give them."""
    if not re.fullmatch(r"[a-z0-9_]+", name) or name == "tll":
        raise SystemExit("--name: lowercase letters, digits, underscore; not 'tll'")
    if not pdf.exists():
        raise SystemExit(f"{pdf}: not found")
    meta = {"name": name, "title": title or pdf.stem, "language": "la", "direction": "", "source_url": "",
            "licence": "supplied by the owner; private use, not redistributed", "retrieved": now()[:10],
            "source_file": pdf.name, "source_sha256": sha256(pdf)}
    out = LEXICA / f"lex_{name}.sqlite"
    stats = build(out, [(str(pdf), name, headwords)], meta, workers)
    f = next(iter(stats["files"].values()))
    print(f"{out}: {stats['n_pages']} pages ({f['pages_without_text']} without a text layer), "
          f"{stats['n_entries']} headwords from {f['headwords_from']}")
    return 0


# ---------------------------------------------------------------- lookup and check
SAMPLE = ("venustus lepidus basium bellus libellus deliciae passer nugae ineptus amo aqua bonus cano caput dico domus "
          "emo facio fero gratia homo iocus ludo mare mollis nox otium puella pius res").split()


def lookup(db: sqlite3.Connection, word: str) -> dict:
    """Entries under the folded headword; failing that, the page where the alphabet puts the word."""
    key = fold(word)
    rows = db.execute("SELECT e.id, e.headword, e.volume, e.col_from, e.col_to, e.level, e.located, e.n_chars, e.text, p.file, p.pdf_page "
                      "FROM entries e JOIN pages p ON p.id = e.page_from WHERE e.folded = ? "
                      "ORDER BY e.volume LIKE 'onom%', e.level = 3, e.located DESC, e.n_chars DESC", (key,)).fetchall()
    cols = "id headword volume col_from col_to level located n_chars text file pdf_page".split()
    near = None
    if not rows:
        ranges = db.execute("SELECT value FROM meta WHERE key = 'ranges'").fetchone()
        where, args = "", [key]
        if ranges:                          # the file whose lemma range holds the word; none: not in the store
            files = sorted(json.loads(ranges[0]), key=lambda r: r[1])
            at = max((i for i, r in enumerate(files) if r[1] <= key), default=None)
            if at is None or files[at][1][:1] != key[:1]:
                return {"key": key, "entries": [], "nearest_before": None}
            f, lo, hi = files[at]
            goes_on = at + 1 < len(files) and files[at + 1][1][:1] == key[:1]
            if not (key <= hi or key.startswith(hi) or hi < lo or goes_on):
                return {"key": key, "entries": [], "nearest_before": None}      # past the last lemma published
            where, args = "AND p.file = ? ", [key, f]
        near = db.execute("SELECT e.headword, e.folded, e.volume, e.col_from, p.file, p.pdf_page FROM entries e JOIN pages p ON p.id = e.page_from "
                          "WHERE e.folded <= ? AND e.level = 1 AND e.variant_of IS NULL AND e.volume NOT LIKE 'onom%' " + where +
                          "ORDER BY e.folded DESC LIMIT 1", args).fetchone()
        if near and near[1][:1] != key[:1]:
            near = None                     # the word's letter is not in the store
    return {"key": key, "entries": [dict(zip(cols, r)) for r in rows],
            "nearest_before": dict(zip("headword folded volume col_from file pdf_page".split(), near)) if near else None}


def check(path: Path, words: list[str]) -> int:
    db = sqlite3.connect(path)
    hit = placed = opens = 0
    for w in words:
        r = lookup(db, w)
        if not r["entries"]:
            n = r["nearest_before"]
            print(f"{w:10} MISS" + (f"   alphabetical neighbour: {n['headword']} (vol. {n['volume']}, col. {n['col_from']}, {n['file']} p. {n['pdf_page']})" if n else "   outside the lemma ranges in the store"))
            continue
        hit += 1
        e = r["entries"][0]
        first = " ".join(e["text"].split())[:110]
        ok = any(line_matches(e["text"].split("\n")[0], r["key"], how) is not None for how in ("exact", "fuzzy"))
        placed += e["located"]
        opens += bool(e["located"] and ok)
        print(f"{w:10} {'placed' if e['located'] else 'page  '} vol. {e['volume']} col. {e['col_from']}-{e['col_to']} p. {e['pdf_page']} "
              f"{e['n_chars']:>7} ch  x{len(r['entries'])}  | {first}")
    print(f"{len(words)} lemmata: {hit} have an entry row, {placed} placed on a line, {opens} open with the headword")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="download the open-access PDFs that are missing")
    ap.add_argument("--build", action="store_true", help="build data/lexica/lex_tll.sqlite from the PDFs present")
    ap.add_argument("--check", nargs="*", metavar="WORD", help="look words up (default: the 30-lemma sample)")
    ap.add_argument("--only", default="", help="with --fetch/--build: only files whose name contains this (build goes to lex_tll_partial.sqlite)")
    ap.add_argument("--pdf", type=Path, help="ingest this dictionary PDF instead of the TLL")
    ap.add_argument("--name", default="", help="with --pdf: store name, writes data/lexica/lex_<name>.sqlite")
    ap.add_argument("--title", default="", help="with --pdf: the dictionary's title")
    ap.add_argument("--headwords", choices=("auto", "bookmarks", "bold", "none"), default="auto",
                    help="with --pdf: where headwords come from (auto: bookmarks if about one a page or more, else bold type)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if args.pdf:
        return build_pdf(args.pdf, args.name, args.title, args.workers, args.headwords)
    if not (args.fetch or args.build or args.check is not None):
        args.fetch = args.build = True
    if args.fetch:
        fetch_all(args.only)
    if args.build:
        build_tll(args.only, args.workers)
    if args.check is not None:
        store = LEXICA / f"lex_{args.name}.sqlite" if args.name else (LEXICA / "lex_tll_partial.sqlite" if args.only else OUT)
        check(store, args.check or SAMPLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
