"""Per-fragment open edition of J. M. Edmonds, *Lyra Graeca* (Loeb), vols I-III.

Reproduces ``data/open/edmonds-lyra-graeca/`` from Internet Archive OCR files.

Sources (all US public domain, published 1922/1924/1927/1928, before 1931):
  * vol. I   (1922 first edition)       IA ``lyragraecabeingr01unse``  (Tesseract grc+eng OCR)
  * vol. I   (1928 revised edition)     IA ``lyragraeca0001jmed_c0b1`` (Tesseract incl. Greek)
  * vol. II  (1924)                     IA ``lyragraecabeingr02unse``  (Tesseract eng+grc OCR)
  * vol. III (1927)                     IA ``lyragraecabeingr03unse``  (Tesseract eng-only OCR;
                                        Greek is Latin-alphabet garbage -> flagged unusable)

No clean TEI/Wikisource/Gutenberg transcription exists (see manifest ``source_search``),
so this script segments IA page OCR (``*_djvu.xml``) by Edmonds' printed fragment numbers.
Nothing is corrected by hand: every text string is a span of the downloaded OCR.  The Greek
is raw OCR.  Segmentation is heuristic; each record carries flags describing how its
boundaries and number were found.

Usage:  python -I scripts/ingest_open_edmonds_lyra.py            (download if missing + build)
"""

from __future__ import annotations

import difflib
import gzip
import hashlib
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "edmonds-lyra-graeca-open"
OUT = ROOT / "data" / "open" / "edmonds-lyra-graeca"
CAMPBELL = ROOT / "data" / "campbell_glp" / "campbell_glp.jsonl"
SPOTCHECK = OUT / "spotcheck.json"
UA = "Melos/1.0 (+https://greeklyric.com)"
BUILD_DATE = "2026-10-09"

# (volume key, IA item, edition label, publication year, Greek OCR usable?)
ITEMS = (
    ("I", "lyragraecabeingr01unse", "Lyra Graeca vol. I, first edition (London: Heinemann; New York: Putnam)", 1922, True),
    ("I-1928", "lyragraeca0001jmed_c0b1", "Lyra Graeca vol. I, revised and augmented edition (London: Heinemann; New York: Putnam)", 1928, True),
    ("II", "lyragraecabeingr02unse", "Lyra Graeca vol. II (London: Heinemann; New York: Putnam)", 1924, True),
    ("III", "lyragraecabeingr03unse", "Lyra Graeca vol. III (London: Heinemann; New York: Putnam)", 1927, False),
)

GREEK = re.compile("[Ͱ-Ͽἀ-῿]")
LATIN = re.compile("[A-Za-z]")
# Function words used only to classify a page as English prose (not data).
STOP = {"the", "and", "of", "to", "in", "a", "is", "that", "for", "with", "his", "her", "as", "by", "was",
        "it", "be", "which", "on", "from", "not", "this", "at", "or", "are", "thou", "thy", "my", "me", "i"}
# Greek capitals that are visually identical to Latin capitals (Unicode TR39 confusables), used
# only to normalise OCR'd running heads such as 'ΟΘΆΑΡΡΗΟ' before fuzzy-matching them.
CONFUSABLE = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧΆΈΉΊΌΎ", "ABEZHIKMNOPTYXAEHIOY")
# A fragment-number line: number (+ optional letter suffix), optional OCR'd footnote digit, optional
# Edmonds title in capitals (e.g. '5 To APHRODITE').
MARKER = re.compile(r"^(?P<num>[0-9lIiO]{1,3})\s?(?P<suf>[a-dA-D]{0,2})"
                    r"(?:\s*(?:,|and|&)\s*(?P<num2>[0-9]{1,3}))?(?:\s*[-–]\s*(?P<range>[0-9]{1,3}))?[.,:;)*}\]]?(?:\s+(?P<fn>[0-9]{1,2}))?(?:\s+(?P<title>\S.*))?$")


# --------------------------------------------------------------------------- download
def fetch(url: str, target: Path) -> bytes:
    if target.exists() and target.stat().st_size:
        return target.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data:
                raise ValueError("empty response")
            target.write_bytes(data)
            time.sleep(0.5)
            return data
        except Exception as exc:  # noqa: BLE001 - logged and re-raised below
            err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"DOWNLOAD FAILED {url}: {err}")


def item_files(item: str) -> dict[str, tuple[str, Path]]:
    d = RAW / item
    return {
        "metadata": (f"https://archive.org/metadata/{item}", d / "metadata.json"),
        "djvu_xml": (f"https://archive.org/download/{item}/{item}_djvu.xml", d / f"{item}_djvu.xml"),
        "scandata": (f"https://archive.org/download/{item}/{item}_scandata.xml", d / f"{item}_scandata.xml"),
        "page_numbers": (f"https://archive.org/download/{item}/{item}_page_numbers.json", d / f"{item}_page_numbers.json"),
        "iiif_manifest": (f"https://iiif.archive.org/iiif/3/{item}/manifest.json", d / "iiif-manifest.json"),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- page model
def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load_pages(item: str) -> list[dict]:
    manifest = json.loads((RAW / item / "iiif-manifest.json").read_text(encoding="utf8"))["items"]
    root = ET.parse(RAW / item / f"{item}_djvu.xml").getroot()
    objs = root.findall(".//OBJECT")
    if len(objs) != len(manifest):
        raise ValueError(f"{item}: {len(objs)} OCR pages but {len(manifest)} IIIF canvases")
    pages = []
    for idx, (obj, canvas) in enumerate(zip(objs, manifest)):
        leaf = int(re.search(r"_(\d{4})\.djvu", obj.get("usemap")).group(1))
        body_id = canvas["items"][0]["items"][0]["body"]["id"]
        if f"_{leaf:04d}.jp2" not in body_id:
            raise ValueError(f"{item}: canvas {idx} image {body_id} does not match OCR leaf {leaf}")
        W, H = int(obj.get("width")), int(obj.get("height"))
        lines = []
        for line in obj.iter("LINE"):
            ws = [w for w in line.findall("WORD") if (w.text or "").strip()]
            if not ws:
                continue
            c = [list(map(int, w.get("coords").split(","))) for w in ws]
            x0 = min(a[0] for a in c); x1 = max(a[2] for a in c)
            yb = max(a[1] for a in c); yt = min(a[3] for a in c)
            text = norm_space(" ".join(w.text for w in ws))
            conf = sum(int(w.get("x-confidence") or 0) for w in ws) / len(ws)
            lines.append({"x0": x0, "x1": x1, "yt": yt, "yb": yb, "h": yb - yt, "text": text, "conf": conf})
        lines.sort(key=lambda l: (l["yt"], l["x0"]))
        pages.append({"idx": idx, "leaf": leaf, "W": W, "H": H, "lines": lines,
                      "image": body_id.replace("/full/max/0/default.jpg", ""), "canvas": canvas["id"]})
    return pages


def is_noise(l: dict) -> bool:
    """Accent rows and specks that Tesseract emits as separate lines above Greek verse."""
    t = l["text"]
    if (MARKER.match(t) and l["h"] >= 30) or (len(t.replace(" ", "")) <= 4 and l["h"] >= 40):
        return False  # possible fragment number (judged later with page geometry)
    letters = len(re.findall(r"[^\W\d_]", t))
    if letters <= 1 and not re.fullmatch(r"[0-9]{1,3}[a-z]?", t):
        return True
    alnum = len(re.findall(r"\w", t))
    return l["h"] < 34 and alnum / max(len(t.replace(" ", "")), 1) < 0.55


def classify(page: dict) -> None:
    toks = re.findall(r"[^\W\d_]+", " ".join(l["text"] for l in page["lines"]))
    g = sum(1 for t in toks if GREEK.search(t))
    stop = sum(1 for t in toks if t.lower() in STOP)
    page["n_tokens"] = len(toks)
    page["greek_ratio"] = g / max(len(toks), 1)
    page["stop_ratio"] = stop / max(len(toks), 1)


def split_page(page: dict, small_large_thr: float) -> None:
    H, W = page["H"], page["W"]
    lines = [l for l in page["lines"] if not is_noise(l)]
    page["noise_lines"] = len(page["lines"]) - len(lines)
    head = None
    if lines and lines[0]["yt"] < 0.12 * H:
        head = lines.pop(0)["text"]
    pnum = None
    # bottom page number; old-style figures are often OCR'd as I/l (1), g (9), o/O (0)
    def is_pnum(l):
        return (l["yt"] > 0.82 * H and re.fullmatch(r"[0-9IlgoO]{1,3}", l["text"])
                and (re.search(r"[0-9]", l["text"]) or len(l["text"]) >= 2))
    # a printer's signature mark ('VOL. I. CC', 'H 2') may sit below the page number
    if len(lines) >= 2 and not is_pnum(lines[-1]) and is_pnum(lines[-2]) and len(lines[-1]["text"]) <= 12:
        lines.pop()
    if lines and is_pnum(lines[-1]):
        pnum = int(lines.pop()["text"].translate(str.maketrans("IlgoO", "11900")))
    page["head"], page["ocr_page_number"] = head, pnum
    hs = [l["h"] for l in lines if len(l["text"]) > 25]
    med_h = statistics.median(hs) if hs else 55
    page["med_h"] = med_h
    # footnote block: last vertical gap >= 0.7 line-height in lower 55% followed by a footnote-like line
    foot_at = None
    lefts = [l["x0"] for l in lines if len(l["text"]) > 30]
    left = min(lefts) if lefts else 0
    for i in range(len(lines) - 1, 0, -1):
        l, prev = lines[i], lines[i - 1]
        if l["yt"] < 0.45 * H:
            break
        gap = l["yt"] - prev["yb"]
        numbered_note = (gap >= 0.7 * med_h and re.match(r"^([0-9]{1,2}|[*†‡§])\s*\S", l["text"])
                         and not number_reading(l["text"]) and l["x0"] < left + 0.25 * W)
        # a note continued from the previous page, or with an OCR-garbled mark, after a wide gap
        wide_gap = gap >= 1.5 * med_h and l["yt"] > 0.55 * H and not number_reading(l["text"])
        if numbered_note or wide_gap:
            block = lines[i:]
            long_h = [b["h"] for b in block if len(b["text"]) > 30] or [l["h"]]
            large = sum(1 for h in long_h if h >= small_large_thr) / len(long_h)
            centred_short = [b for b in block if b["x1"] - b["x0"] < 0.12 * W and b["x0"] > left + 0.25 * W]
            centred_numbers = [b for b in block if number_reading(b["text"]) and b["x0"] > left + 0.2 * W]
            if (statistics.median(long_h) < small_large_thr and large < (0.2 if numbered_note else 0.01) and not centred_numbers
                    and not centred_short and not re.match(r"^\d{1,3}\s*[-–]\s*\d{1,3}\b", l["text"])):
                foot_at = i
    page["body"] = lines[:foot_at] if foot_at is not None else lines
    page["foot"] = lines[foot_at:] if foot_at is not None else []
    wide = [(l["x0"] + l["x1"]) / 2 for l in page["body"] if l["x1"] - l["x0"] > 0.45 * W]
    page["center"] = statistics.median(wide) if wide else W / 2


def number_reading(text: str) -> dict | None:
    """Parse an OCR'd fragment-number line into candidate readings (no guessing of digits:
    alternatives only drop a trailing digit that may be a superscript footnote mark)."""
    m = MARKER.match(text.strip())
    if not m:
        return None
    digits, suf = m.group("num"), m.group("suf").lower()
    title = m.group("title")
    if title:
        letters = re.findall(r"[^\W\d_]", title)
        upper = [c for c in letters if c.isupper()]
        if len(letters) < 2 or len(title) > 45 or (len(upper) / len(letters) < 0.5 and not title.startswith(("[", "To ", "On "))):
            return None
    if not re.search(r"[0-9]", digits) and not suf:
        return None
    d = digits.translate(str.maketrans("lIiO", "1110"))
    if d.startswith("0"):
        return None
    if len(suf) == 2 and suf[0] == suf[1]:
        suf = suf[0]
    elif len(suf) == 2:
        return None
    n2 = int(m.group("num2")) if m.group("num2") else None
    if n2 is not None and not (int(d) < n2 <= int(d) + 3):
        return None
    readings = [(int(d), suf, "as_read")]
    if len(d) >= 2 and not suf and not m.group("fn") and n2 is None and not m.group("range"):
        readings.append((int(d[:-1]), "", "trailing_digit_taken_as_footnote_mark"))
    rd = [{"n": n, "n_end": n2 or n, "suffix": s, "label": f"{n}{s}" + (f", {n2}" if n2 else ""), "how": how}
          for n, s, how in readings]
    return {"ocr": text, "readings": rd, "n": rd[0]["n"], "suffix": rd[0]["suffix"], "label": rd[0]["label"],
            "title": title.strip() if title else None}


def markers(page: dict) -> list[dict]:
    out = []
    body = page["body"]
    for i, l in enumerate(body):
        r = number_reading(l["text"])
        cx = (l["x0"] + l["x1"]) / 2
        if not r:
            # unreadable number: a tiny isolated centred line of number height (e.g. 'We' for 17)
            gap = l["yt"] - body[i - 1]["yb"] if i else l["yt"]
            if (len(l["text"].replace(" ", "")) <= 4 and l["x1"] - l["x0"] < 0.07 * page["W"] and 35 <= l["h"] <= 65
                    and abs(cx - page["center"]) < 0.05 * page["W"] and gap >= 0.4 * page["med_h"]
                    and (page["role"] == "grc" or not GREEK.search(l["text"]))):
                out.append({"ocr": l["text"], "readings": [], "n": None, "suffix": "", "label": None, "title": None,
                            "line": i, "leaf": page["leaf"], "y": l["yt"], "y_rel": l["yt"] / page["H"]})
            continue
        width_max = 0.5 if r["title"] else 0.12
        if abs(cx - page["center"]) > 0.08 * page["W"] or l["h"] < 20 or l["x1"] - l["x0"] > width_max * page["W"]:
            continue
        r.update({"line": i, "leaf": page["leaf"], "y": l["yt"], "y_rel": l["yt"] / page["H"]})
        out.append(r)
    return out


# --------------------------------------------------------------------------- volume structure
def canon_heads(pages: list[dict]) -> None:
    def norm(h):
        return re.sub(r"[^A-Z ]", "", (h or "").upper().translate(CONFUSABLE)).strip()
    # the verso (Greek-page) running head is the book title, never a poet
    book = Counter(norm(p["head"]) for p in pages if p["role"] == "grc" and norm(p["head"])).most_common(1)
    book = book[0][0] if book else None
    counts = Counter(norm(p["head"]) for p in pages if p["role"] == "eng" and norm(p["head"]))
    # spacing variants of one head ('BACCHY LIDES') collapse onto the most frequent spelling
    spelling = {}
    for h, c in counts.most_common():
        spelling.setdefault(h.replace(" ", ""), h)
    canon_set = {spelling[h.replace(" ", "")] for h, c in counts.items()
                 if sum(v for k, v in counts.items() if k.replace(" ", "") == h.replace(" ", "")) >= 2}
    canon = [h for h in canon_set if h != book and len(h) >= 4]
    norm_plain = norm
    norm = lambda x: spelling.get(norm_plain(x).replace(" ", ""), norm_plain(x))  # noqa: E731
    last = None
    for p in pages:
        h = norm(p["head"])
        if p["role"] == "eng":
            raw = re.sub(r"[^A-Z ]", "", (p["head"] or "").translate(CONFUSABLE)).strip()
            if h in canon:
                last = h
            elif h and h != book:
                best = difflib.get_close_matches(h, canon, n=1, cutoff=0.8)
                if best:
                    last = best[0]
                elif raw == (p["head"] or "").strip() and len(raw) >= 4:  # clean one-off capitals head
                    last = h
            p["poet_head"] = last
        else:
            p["poet_head"] = None


def page_numbers(pages: list[dict]) -> None:
    """Printed page = leaf + offset; offset from OCR'd page numbers by local majority."""
    obs = [(p["idx"], p["ocr_page_number"] - p["idx"]) for p in pages if p["ocr_page_number"]]
    for p in pages:
        near = [o for i, o in obs if abs(i - p["idx"]) <= 8]
        if not near:
            p["printed_page"] = None
            continue
        off, c = Counter(near).most_common(1)[0]
        p["printed_page"] = p["idx"] + off if c >= 2 else None


def roles(pages: list[dict]) -> None:
    for p in pages:
        classify(p)
        greekish = p["greek_ratio"] > 0.3 or (p["stop_ratio"] < 0.15 and p["n_tokens"] > 30)
        p["role"] = "grc" if greekish else ("eng" if p["stop_ratio"] >= 0.15 else "other")
    pre = type_thresholds(pages, key="lines", spreads_only=False)
    for p in pages:
        split_page(p, pre.get(p["role"]) or pre["eng"] or 60)
    # facing spreads: Greek page immediately followed by English page
    for i, p in enumerate(pages):
        p["spread"] = None
    for i in range(len(pages) - 1):
        a, b = pages[i], pages[i + 1]
        if a["role"] == "grc" and b["role"] == "eng" and a["spread"] is None:
            a["spread"] = b["spread"] = i
    return pre


def align(gm: list[dict], em: list[dict]) -> list[tuple]:
    """Needleman-Wunsch alignment of Greek-page and English-page number markers of a spread."""
    n, m = len(gm), len(em)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0], B[i][0] = -1.0 * i, "g"
    for j in range(1, m + 1):
        S[0][j], B[0][j] = -1.0 * j, "e"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            a, b = gm[i - 1], em[j - 1]
            # Edmonds' facing pages put corresponding numbers at the same height (|dy| < 0.05 page
            # in a check of 482 agreeing pairs), so pairs far apart vertically are never matched.
            dy = abs(a["y_rel"] - b["y_rel"])
            if dy > 0.12:
                sim = -5.0
            elif a["label"] is None or b["label"] is None:
                sim = 1.2
            else:
                la = {x["label"] for x in a["readings"]}; lb = {x["label"] for x in b["readings"]}
                sim = 2.0 if la & lb else 1.2
            S[i][j], B[i][j] = max((S[i - 1][j - 1] + sim, "d"), (S[i - 1][j] - 1, "g"), (S[i][j - 1] - 1, "e"))
    out, i, j = [], n, m
    while i or j:
        mv = B[i][j]
        if mv == "d":
            out.append((gm[i - 1], em[j - 1])); i -= 1; j -= 1
        elif mv == "g":
            out.append((gm[i - 1], None)); i -= 1
        else:
            out.append((None, em[j - 1])); j -= 1
    return out[::-1]


def fit_sequence(raw: list[dict]) -> tuple[list[dict], list[dict]]:
    """Choose each marker's number so that Edmonds' numbering ascends.

    Pass 1 (greedy): try the reading shared by both pages, then each page's readings
    (as read, then with a trailing superscript-footnote digit removed).
    Pass 2: a marker that fits nowhere but sits alone between two fitted markers whose
    numbers differ by exactly 2 gets the number in between (flagged as inferred).
    Remaining two-page markers stay as boundaries with their English-page reading
    (flagged out_of_sequence); remaining one-page markers are dropped.
    """
    for mk in raw:
        mk["fitted"] = False
        opts = {}
        for side in ("g", "e"):
            for rd in (mk[side]["readings"] if mk[side] else []):
                o = opts.setdefault(rd["label"], dict(rd, support=0))
                o["support"] += 1
                if rd["how"] == "as_read":
                    o["how"] = "as_read"
        mk["opts"] = list(opts.values())
    # longest weighted ascending chain per poet run (dynamic programming over marker x reading)
    runs, cur = [], []
    for i, mk in enumerate(raw):
        if cur and raw[cur[-1]]["poet"] != mk["poet"]:
            runs.append(cur); cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    for run in runs:
        nodes = [(i, o) for i in run for o in raw[i]["opts"]]
        best, back = [], []
        for k, (i, o) in enumerate(nodes):
            w = 1.0 + 0.5 * (o["support"] - 1) - (0.3 if o["how"] != "as_read" else 0)
            b, bk = w, None
            for q in range(k):
                pi, po = nodes[q]
                if pi >= i:
                    continue
                step = o["n"] - po["n_end"]
                if (0 < step <= 200) or (step == 0 and o["label"] != po["label"]):
                    v = best[q] + w - 0.12 * max(step - 1, 0)
                    if v > b:
                        b, bk = v, q
            best.append(b); back.append(bk)
        if not nodes:
            continue
        k = max(range(len(nodes)), key=lambda q: best[q])
        while k is not None:
            i, o = nodes[k]
            mk = raw[i]
            mk.update({"fitted": True, "label": o["label"], "n": o["n"], "n_end": o["n_end"], "suffix": o["suffix"]})
            if o["how"] != "as_read":
                mk["reading_note"] = o["how"]
            both = bool(mk["g"] and mk["e"]) and all(
                o["label"] in {x["label"] for x in r["readings"]} for r in (mk["g"], mk["e"]))
            mk["status"] = "agreed" if both else ("two_sided_resolved_by_sequence" if mk["g"] and mk["e"] else
                                                   ("greek_side_only" if mk["g"] else "english_side_only"))
            k = back[k]
    fitted_idx = [i for i, m in enumerate(raw) if m["fitted"]]
    for a, b in zip(fitted_idx, fitted_idx[1:]):
        between = list(range(a + 1, b))
        A, B = raw[a], raw[b]
        # k unplaced markers between fitted numbers a and a+k+1 take a+1 .. a+k in order
        if (between and A["poet"] == B["poet"] and B["n"] - A["n_end"] == len(between) + 1
                and not A["suffix"] and not B["suffix"] and all(raw[x]["poet"] == A["poet"] for x in between)):
            for off, x in enumerate(between, 1):
                v = A["n_end"] + off
                raw[x].update({"fitted": True, "label": str(v), "n": v, "n_end": v, "suffix": "",
                               "status": "inferred_between_neighbours"})
    accepted, rejected = [], []
    for m in raw:
        if m["fitted"]:
            accepted.append(m)
        elif m["g"] and m["e"] and (m["e"]["readings"] or m["g"]["readings"]):
            r = m["e"] if m["e"]["readings"] else m["g"]
            m.update({"label": r["label"], "n": r["n"], "suffix": r["suffix"], "status": "out_of_sequence_uncertain"})
            accepted.append(m)
        else:
            rejected.append(m)
    return accepted, rejected


# --------------------------------------------------------------------------- segmentation
def build_volume(vol: str, item: str, edition: str, year: int, greek_ok: bool) -> tuple[list[dict], dict]:
    pages = load_pages(item)
    thr = roles(pages)
    canon_heads(pages)
    page_numbers(pages)
    by_leaf = {p["leaf"]: p for p in pages}
    spreads = defaultdict(list)
    for p in pages:
        if p["spread"] is not None:
            spreads[p["spread"]].append(p)
    # 1. fragment markers per spread, aligned across the two pages, then fitted to the sequence
    raw_markers = []
    for key in sorted(spreads):
        g, e = spreads[key]
        for gm, em in align(markers(g), markers(e)):
            raw_markers.append({"spread": key, "g": gm, "e": em, "poet": e["poet_head"]})
    accepted, rejected = fit_sequence(raw_markers)
    # 2. streams of body lines (with section headings as hard breaks)
    def stream(side: str):
        items = []
        for key in sorted(spreads):
            p = spreads[key][0 if side == "g" else 1]
            for i, l in enumerate(p["body"]):
                items.append((p["leaf"], i, l))
        return items
    def is_heading(l, p):
        t = l["text"]
        centred = abs((l["x0"] + l["x1"]) / 2 - p["center"]) < 0.1 * p["W"]
        book = re.match(r"^B[oO0][oO0][kKxX]s?\s+[IVXLl]+\b", t) and len(t) < 30  # 'Book III', 'Books IX and X'
        return centred and (bool(book) or (len(t) >= 6 and not re.search(r"[a-zα-ω]", t)
                                           and len(re.findall(r"[A-Z]", t.translate(CONFUSABLE))) >= 4))
    records = []
    for side in ("g", "e"):
        st = stream(side)
        pos = {(leaf, i): k for k, (leaf, i, _) in enumerate(st)}
        starts = []
        for mi, mk in enumerate(accepted):
            r = mk[side]
            if r:
                starts.append((pos[(r["leaf"], r["line"])], mi, 1))
                continue
            # number not found on this page: facing pages align, so the fragment starts at the
            # first body line at (or just below) the height of the number on the facing page
            other = mk["e" if side == "g" else "g"]
            page = spreads[mk["spread"]][0 if side == "g" else 1]
            idx = next((i for i, l in enumerate(page["body"]) if l["yt"] / page["H"] >= other["y_rel"] - 0.01), None)
            if idx is not None:
                l0 = page["body"][idx]
                # an unrecognised number/title line itself is not fragment text
                if (abs((l0["x0"] + l0["x1"]) / 2 - page["center"]) < 0.06 * page["W"]
                        and l0["x1"] - l0["x0"] < 0.5 * page["W"] and len(l0["text"]) < 40
                        and abs(l0["yt"] / page["H"] - other["y_rel"]) < 0.02 and idx + 1 < len(page["body"])):
                    idx += 1
                k = pos[(page["leaf"], idx)]
            else:  # below the last line: starts on the next page of this side
                k = max(pos[(page["leaf"], i)] for i in range(len(page["body"]))) + 1 if page["body"] else None
            if k is not None:
                starts.append((k, mi, 0))
                mk[f"{side}_boundary_by_position"] = True
        starts.sort()
        for si, (k0, mi, skip) in enumerate(starts):
            k1 = starts[si + 1][0] if si + 1 < len(starts) else len(st)
            seg, poet0 = [], accepted[mi]["poet"]
            for k in range(k0 + skip, k1):
                leaf, i, l = st[k]
                p = by_leaf[leaf]
                partner = spreads[p["spread"]][1]
                if partner["poet_head"] != poet0 or is_heading(l, p):
                    accepted[mi].setdefault(f"{side}_cut", "section_or_poet_change")
                    break
                seg.append((leaf, l["text"], l["h"]))
            accepted[mi][f"{side}_seg"] = seg
    # 3. headings -> section labels (English side), in reading order
    section_at = {}
    current = None
    for key in sorted(spreads):
        e = spreads[key][1]
        for i, l in enumerate(e["body"]):
            if is_heading(l, e):
                current = l["text"]
            section_at[(e["leaf"], i)] = current
    # 4. records
    out = []
    seen = Counter()
    for mk in accepted:
        poet = (mk["poet"] or "").replace("LIFE OF ", "").strip() or None
        seen[(poet, mk["label"])] += 1
        flags = []
        if mk["status"] != "agreed":
            flags.append("number_" + mk["status"])
        for side, name in (("g", "greek"), ("e", "english")):
            if not mk[side]:
                flags.append(f"{name}_boundary_placed_by_facing_page_position" if mk.get(f"{side}_boundary_by_position")
                             else f"no_{name}_boundary_found_{name}_text_merged_into_previous_fragment")
        if mk.get("poet", "") and mk["poet"].startswith("LIFE OF"):
            flags.append("inside_testimonia_section")
        if mk.get("reading_note"):
            flags.append("number_" + mk["reading_note"])
        eseg, gseg = mk.get("e_seg", []), mk.get("g_seg", [])
        etext = "\n".join(t for _, t, _ in eseg)
        gtext = "\n".join(t for _, t, _ in gseg)
        note = split_source_note(etext)
        if etext and note is None:
            flags.append("english_source_line_colon_not_found")
        gref = split_greek_ref(gtext) if greek_ok else None
        if not etext:
            flags.append("english_text_empty")
        if not gtext:
            flags.append("greek_text_empty")
        e_leaves = sorted({lf for lf, _, _ in eseg} | ({mk["e"]["leaf"]} if mk["e"] else set()))
        g_leaves = sorted({lf for lf, _, _ in gseg} | ({mk["g"]["leaf"]} if mk["g"] else set()))
        sec = section_at.get((mk["e"]["leaf"], mk["e"]["line"])) if mk["e"] else None
        rec = {
            "id": f"edmonds-lg:{vol}:{slug(poet)}:{mk['label'].replace(', ', '-')}" +(f"~{seen[(poet, mk['label'])]}" if seen[(poet, mk['label'])] > 1 else ""),
            "volume": vol,
            "edition": edition,
            "publication_year": year,
            "ia_item": item,
            "poet": poet,
            "running_head": mk["poet"],
            "section_heading": sec,
            "edmonds_number": mk["label"],
            "number_ocr_readings": {"greek_page": mk["g"]["ocr"] if mk["g"] else None,
                                    "english_page": mk["e"]["ocr"] if mk["e"] else None},
            "number_status": mk["status"],
            "english_title": (mk["e"] or {}).get("title"),
            "greek_title": (mk["g"] or {}).get("title"),
            "english_source_line": note,
            "english_translation": etext,
            "greek_source_ref": gref,
            "greek_text": gtext,
            "greek_ocr_usable": greek_ok,
            "english_footnotes": footnotes(by_leaf, e_leaves),
            "greek_page_footnotes": footnotes(by_leaf, g_leaves),
            "printed_pages_greek": [by_leaf[x]["printed_page"] for x in g_leaves],
            "printed_pages_english": [by_leaf[x]["printed_page"] for x in e_leaves],
            "ia_leaves_greek": g_leaves,
            "ia_leaves_english": e_leaves,
            "page_images": {str(x): by_leaf[x]["image"] for x in sorted(set(g_leaves) | set(e_leaves))},
            "quality": "machine_ocr_segmented",
            "flags": flags,
            "license": "public_domain_us",
            "pd_basis": f"published {year} - US public domain (pre-1931 publication)",
            "source_url": f"https://archive.org/details/{item}",
        }
        out.append(rec)
    title = next((p for p in pages[:16] if "HEINEMANN" in " ".join(l["text"] for l in p["lines"]).upper()), None)
    stats = {
        "title_page": {"leaf": title["leaf"], "image": title["image"] + "/full/max/0/default.jpg",
                       "ocr_imprint_lines": [l["text"] for l in title["lines"] if re.search(r"M[CDXLVIO]{4,}|EDITION|VOLUME", l["text"].upper())]}
        if title else None,
        "pages": len(pages),
        "type_size_thresholds_px": thr,
        "facing_spreads": len(spreads),
        "noise_lines_dropped": sum(p["noise_lines"] for p in pages),
        "raw_markers": len(raw_markers),
        "accepted_markers": len(accepted),
        "rejected_one_sided_markers": [{"leaf": (m["g"] or m["e"])["leaf"], "ocr": (m["g"] or m["e"])["ocr"]} for m in rejected],
        "number_status": dict(Counter(m["status"] for m in accepted)),
    }
    return out, stats


def footnotes(by_leaf: dict, leaves: list[int]) -> list[dict]:
    return [{"leaf": lf, "text": "\n".join(l["text"] for l in by_leaf[lf]["foot"])} for lf in leaves if by_leaf[lf]["foot"]]


def split_source_note(text: str) -> str | None:
    """Edmonds' italic source line ends with the first colon (e.g. '[Longinus] The Sublime:')."""
    m = re.search(r":", text[:250])
    return text[: m.end()].strip() if m else None


def split_greek_ref(text: str) -> str | None:
    """Leading Latin-alphabet citation before the first Greek word (e.g. '[Longin.] Subl. 10')."""
    m = GREEK.search(text)
    if not m or m.start() == 0 or m.start() > 160:
        return None
    return text[: m.start()].strip() or None


def otsu(values: list[int]) -> float:
    """Otsu threshold separating the two type sizes (Otsu 1979, IEEE SMC 9:62-66)."""
    vs = sorted(values)
    best, thr = -1.0, statistics.median(vs)
    for t in sorted(set(vs))[1:]:
        a = [v for v in vs if v < t]; b = [v for v in vs if v >= t]
        if len(a) < 0.05 * len(vs) or len(b) < 0.05 * len(vs):
            continue
        wa, wb = len(a) / len(vs), len(b) / len(vs)
        var = wa * wb * (statistics.mean(a) - statistics.mean(b)) ** 2
        if var > best:
            best, thr = var, t - 0.5
    return thr


def type_thresholds(pages: list[dict], key: str = "body", spreads_only: bool = True) -> dict:
    """Line-height threshold between small type (notes, footnotes) and large type, per page role.
    Used only to reject footnote-block candidates that are set in large type."""
    out = {}
    for role in ("eng", "grc"):
        hs = [l["h"] for p in pages if (p.get("spread") is not None or not spreads_only) and p["role"] == role
              for l in p[key] if len(l["text"]) > 30]
        med = statistics.median(hs) if hs else 60
        vals = [h for h in hs if h < 1.5 * med]
        out[role] = otsu(vals) if vals else None
    return out


def slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "unknown").lower()).strip("-")


# --------------------------------------------------------------------------- Campbell mapping
def greek_key(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s if "α" <= ch <= "ω" or ch == "ς").replace("ς", "σ")


def campbell_matches(records: list[dict]) -> list[dict]:
    camp = [json.loads(l) for l in CAMPBELL.read_text(encoding="utf8").splitlines() if l.strip()]
    keyed = [(r, greek_key(r["text"])) for r in camp]
    out = []
    for c, ck in keyed:
        inc = ck[:20]
        if len(inc) < 20:
            continue
        hits = []
        for k, r in enumerate(records):
            if not r["greek_ocr_usable"] or not r["poet"]:
                continue
            if c["author"].upper() not in r["poet"].upper():
                continue
            gk = greek_key(r["greek_text"])
            pos = gk.find(inc)
            if pos < 0:
                continue
            # if the next fragment's Greek-page number was not found, its Greek is merged into this
            # record, so the incipit may belong to that next Edmonds number
            nxt = records[k + 1] if k + 1 < len(records) else None
            merged = bool(nxt and nxt["volume"] == r["volume"] and nxt["poet"] == r["poet"]
                          and any(f.startswith("no_greek_boundary_found") or f.startswith("greek_boundary_placed")
                                  for f in nxt["flags"]))
            hits.append({"edmonds_id": r["id"], "edmonds_number": r["edmonds_number"], "volume": r["volume"],
                         "offset_in_greek_text": pos, "greek_text_letters": len(gk),
                         "number_certain": not merged,
                         "possible_alternative": nxt["id"] if merged else None})
        if hits:
            out.append({"campbell_id": c["id"], "campbell_author": c["author"], "campbell_fragment": c["metadata"]["edition_fragment"],
                        "hits": hits, "evidence": "exact_greek_incipit_match", "incipit_key": inc,
                        "note": "first 20 Greek letters of Campbell's text (lower-cased, accents/punctuation stripped, final sigma folded) found verbatim in the OCR Greek of an Edmonds record by the same poet"})
    return out


def provenance_check(records: list[dict]) -> dict:
    """Independent re-read of each djvu.xml: every output text line must be a literal OCR line
    of one of the IA leaves the record cites."""
    lines_by = {}
    for item in {r["ia_item"] for r in records}:
        root = ET.parse(RAW / item / f"{item}_djvu.xml").getroot()
        for obj in root.findall(".//OBJECT"):
            leaf = int(re.search(r"_(\d{4})\.djvu", obj.get("usemap")).group(1))
            lines_by[(item, leaf)] = {norm_space(" ".join(w.text.strip() for w in ln.findall("WORD") if (w.text or "").strip()))
                                      for ln in obj.iter("LINE")}
    checked = missing = 0
    for r in records:
        for field, leaves in (("english_translation", r["ia_leaves_english"]), ("greek_text", r["ia_leaves_greek"])):
            pool = set().union(*[lines_by[(r["ia_item"], lf)] for lf in leaves]) if leaves else set()
            for ln in filter(None, (r[field] or "").split("\n")):
                checked += 1
                missing += ln not in pool
    return {"text_lines_checked": checked, "lines_not_found_in_cited_ocr_pages": missing}


# --------------------------------------------------------------------------- main
def main() -> None:
    inputs = []
    for vol, item, *_ in ITEMS:
        for kind, (url, path) in item_files(item).items():
            fetch(url, path)
            inputs.append({"volume": vol, "item": item, "kind": kind, "url": url,
                           "path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)})
    inputs.append({"volume": None, "item": None, "kind": "campbell_glp (read-only, for incipit matching)",
                   "url": None, "path": str(CAMPBELL.relative_to(ROOT)).replace("\\", "/"),
                   "bytes": CAMPBELL.stat().st_size, "sha256": sha256(CAMPBELL)})
    records, vstats = [], {}
    for vol, item, edition, year, greek_ok in ITEMS:
        recs, st = build_volume(vol, item, edition, year, greek_ok)
        records.extend(recs)
        vstats[vol] = st
        print(vol, item, len(recs), st["number_status"], file=sys.stderr)
    matches = campbell_matches(records)
    by_id = defaultdict(list)
    for m in matches:
        for h in m["hits"]:
            by_id[h["edmonds_id"]].append({"campbell_id": m["campbell_id"], "evidence": m["evidence"],
                                           "number_certain": h["number_certain"]})
    for r in records:
        r["campbell_glp_matches"] = by_id.get(r["id"], [])
    OUT.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf8")
    if len(body) > 25 * 1024 * 1024:
        out_path = OUT / "fragments.jsonl.gz"
        out_path.write_bytes(gzip.compress(body, mtime=0))
    else:
        out_path = OUT / "fragments.jsonl"
        out_path.write_bytes(body)
    counts = defaultdict(Counter)
    for r in records:
        counts[r["volume"]][r["poet"] or "unknown"] += 1
    flags = Counter(f for r in records for f in r["flags"])
    ids = {r["id"] for r in records}

    def spot_summary(path: Path) -> dict | None:
        if not path.exists():
            return None
        sc = json.loads(path.read_text(encoding="utf8"))
        crit = [k for k in sc["records"][0] if k.endswith("_ok")] if sc.get("records") else []
        rates = {}
        for k in crit:
            vals = [x[k] for x in sc["records"] if isinstance(x[k], bool)]
            rates[k] = {"checked": len(vals), "errors": vals.count(False),
                        "error_rate": round(vals.count(False) / len(vals), 3) if vals else None}
        return {"file": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path),
                "checked": sc.get("checked"), "auditor": sc.get("auditor"), "sample": sc.get("sample"),
                "records_checked": len(sc.get("records", [])),
                "sampled_ids_present_in_output": sum(1 for x in sc.get("records", []) if x["id"] in ids),
                "error_rates": rates}

    spot = spot_summary(SPOTCHECK)
    spot_r1 = spot_summary(OUT / "spotcheck_round1_prefix.json")
    if spot_r1:
        spot_r1["note"] = ("first audit, run on an earlier build; its failures (footnotes leaking into fragment ends, "
                           "number/title lines kept as text, missed page-signature lines) led to the footnote and "
                           "boundary fixes in this script. Error rates of the final build are in spot_check.")
    provenance = provenance_check(records)
    manifest = {
        "name": "edmonds-lyra-graeca",
        "title": "J. M. Edmonds, Lyra Graeca (Loeb Classical Library), vols I-III: per-fragment OCR segmentation",
        "date": BUILD_DATE,
        "builder": "scripts/ingest_open_edmonds_lyra.py",
        "license": "public_domain_us",
        "pd_basis": "published 1922/1924/1927 - US public domain (pre-1931 publication); revised vol. I published 1928 - likewise pre-1931",
        "volumes": [{"volume": v, "ia_item": i, "edition": e, "publication_year": y, "greek_ocr_usable": g,
                     "ia_url": f"https://archive.org/details/{i}"} for v, i, e, y, g in ITEMS],
        "inputs": inputs,
        "output": {"path": str(out_path.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
                   "records": len(records)},
        "counts_per_volume": {v: sum(c.values()) for v, c in counts.items()},
        "counts_per_volume_poet": {v: dict(sorted(c.items())) for v, c in counts.items()},
        "flag_counts": dict(flags),
        "segmentation": {
            "quality": "machine_ocr_segmented",
            "method": [
                "IA djvu.xml (Tesseract) lines with coordinates; accent-row/speck lines dropped",
                "running head = first line in top 12% of page; printed page number from bottom-line OCR, propagated by local majority offset",
                "footnote block = highest large vertical gap in the lower page followed by a left-aligned numbered note line, set in small type, with no centred fragment number below it; footnotes are kept per page, not cut per fragment",
                "page role: Greek (Greek-letter ratio > 0.3, or < 15% English function words) vs English; facing spread = Greek page followed by English page",
                "fragment marker = short centred line reading as a number (+ optional a-d suffix, ', N' pair, footnote digit, or capitals title), or an unreadable tiny centred line of number height",
                "markers of the two facing pages aligned (Needleman-Wunsch) with a hard vertical-position constraint (Edmonds prints corresponding numbers at the same height)",
                "numbers chosen per poet by a longest ascending chain (dynamic programming over all OCR readings, incl. dropping a trailing superscript footnote digit); unplaced markers between numbers a and a+k+1 receive a+1..a+k (flagged inferred); unplaced two-page markers kept as boundaries (flagged out_of_sequence); unplaced one-page markers dropped",
                "fragment text = body lines from its marker to the next marker on the same page side; when the number was not found on one page, that page's boundary is placed at the facing number's height (flagged); cut at a centred all-caps heading or a running-head change",
                "english_source_line = English segment up to its first colon within 250 characters (Edmonds' italic source note ends with a colon); greek_source_ref = Latin-letter text before the first Greek letter",
                "Greek is uncorrected OCR (never corrected by hand); vol. III Greek is unusable (Latin-only OCR)",
            ],
            "volume_stats": vstats,
            "spot_check": spot,
            "spot_check_round1_prefix": spot_r1,
            "provenance_check": provenance,
        },
        "campbell_glp_mapping": {"method": "exact Greek incipit match (first 20 normalised Greek letters of the Campbell text found in the same poet's Edmonds Greek OCR segment); Edmonds prints no Campbell cross-references (Campbell 1967 postdates him)",
                                 "campbell_poems_total": sum(1 for l in CAMPBELL.read_text(encoding="utf8").splitlines() if l.strip()),
                                 "matched_campbell_poems": len(matches),
                                 "matched_with_certain_edmonds_number": sum(1 for m in matches if any(h["number_certain"] for h in m["hits"])),
                                 "edmonds_records_matched": len({h["edmonds_id"] for m in matches for h in m["hits"]}),
                                 "matches": matches},
        "source_search": json.loads((OUT / "source_search.json").read_text(encoding="utf8")) if (OUT / "source_search.json").exists() else None,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    print("records", len(records), "campbell matches", len(matches), file=sys.stderr)


if __name__ == "__main__":
    main()
