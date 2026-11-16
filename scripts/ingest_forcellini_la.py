#!/usr/bin/env python3
"""Ingest Forcellini's Lexicon Totius Latinitatis (Latin-Latin) into data/lexica/lex_forcellini.sqlite.

Source: the archive.org OCR text (ABBYY FineReader 11, `_djvu.txt`) of the five physical volumes of the Padua
edition revised by Furlanetto, Corradini and Perin (items forcellini2, forcellini3, forcellini4, 5forcellini,
forcellini6; A-C, D-K, L-Q, R-S, T-Z), each marked Public Domain Mark 1.0. The clean electronic text
(lexica.linguax.com/forc2.php) answers robots.txt "User-agent: * / Disallow: /" and an HTTP 511 proof-of-work
and CAPTCHA page, so it is not scraped (docs/latin/lexica-forcellini.md).

Steps, all re-runnable: (1) fetch each volume's OCR text and item metadata once into
data/raw/latin/lexica/forcellini/ (a file already there is not fetched again; every fetch is appended to
data/raw/latin/fetch-log.jsonl); (2) cut each volume into entries at lines that open with a capitalised headword in
the volume's running alphabetical position; (3) repair a misread headword against the Lewis & Short headwords and
the lemma index when exactly one known lemma lies between its neighbours within a small edit distance; (4) store
entries(id, headword, folded, text) and meta(key, value), skipping entries already stored (table `source`, keyed by
volume and position); (5) write the manifest data/open/latin/lexica/forcellini.json.

  .venv/bin/python scripts/ingest_forcellini_la.py                  # everything
  .venv/bin/python scripts/ingest_forcellini_la.py --lemmas catullus # only entries for Catullus's lemmas
  .venv/bin/python scripts/ingest_forcellini_la.py --limit 500       # at most 500 new entries this run
  .venv/bin/python scripts/ingest_forcellini_la.py --rebuild         # drop the store and cut the raw text again
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_dictionary import fold  # noqa: E402  (the shared folding: lowercase, no diacritics, j->i, v->u)

UA = "Melos/1.0 (+https://greeklyric.com)"
RAW = ROOT / "data/raw/latin/lexica/forcellini"
LOG = ROOT / "data/raw/latin/fetch-log.jsonl"
OUT = ROOT / "data/lexica/lex_forcellini.sqlite"
MANIFEST = ROOT / "data/open/latin/lexica/forcellini.json"
LEMMA_INDEX = ROOT / "data/lemma_index_la.sqlite"
LEWIS_SHORT = ROOT / "data/lexica/lewis_short_la.sqlite"
TITLE = "Aegidii Forcellini Lexicon Totius Latinitatis (ed. Furlanetto, Corradini, Perin; Patavii, Typis Seminarii)"
SOURCE_URL = "https://archive.org/details/forcellini2"
LICENCE_NOTE = "archive.org item metadata licenseurl: http://creativecommons.org/publicdomain/mark/1.0/ (Public Domain Mark 1.0)"
# (archive.org item, OCR text file, volume label, letters)
VOLUMES = (("forcellini2", "2 Forcellini_djvu.txt", "I", "A-C"),
           ("forcellini3", "3 Forcellini_djvu.txt", "II", "D-K"),
           ("forcellini4", "4 Forcellini_djvu.txt", "III", "L-Q"),
           ("5forcellini", "5 Forcellini_djvu.txt", "IVa", "R-S"),
           ("forcellini6", "6 Forcellini_djvu.txt", "IVb", "T-Z"))
PARSER = "13"   # bump when the cutting changes; a store cut by another version is rebuilt

_last_request = 0.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, path: Path, licence_note: str) -> Path:
    """GET url into path unless it is already there; one request a second, back off on 429/503; log the fetch."""
    global _last_request
    if path.exists() and path.stat().st_size:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    wait = 5.0
    for attempt in range(6):
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
                data, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 5:
                time.sleep(float(e.headers.get("Retry-After") or wait) if str(e.headers.get("Retry-After") or "").isdigit() else wait)
                wait *= 2
                continue
            raise SystemExit(f"refused: HTTP {e.code} for {url}")
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        with LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"url": url, "path": str(path.relative_to(ROOT)), "bytes": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest(),
                                  "fetched_at": datetime.now(timezone.utc).isoformat(), "http_status": status,
                                  "licence_note": licence_note}, ensure_ascii=False) + "\n")
        return path
    raise SystemExit(f"gave up on {url}")


def fetch_all() -> list[dict]:
    out = []
    for item, name, label, letters in VOLUMES:
        meta = fetch(f"https://archive.org/metadata/{item}", RAW / f"{item}.metadata.json",
                     "archive.org item metadata (carries the item's licence statement)")
        text = fetch(f"https://archive.org/download/{item}/{urllib.parse.quote(name)}", RAW / f"{item}_djvu.txt",
                     f"Forcellini, Lexicon Totius Latinitatis vol. {label} ({letters}), OCR text; {LICENCE_NOTE}")
        md = json.loads(meta.read_text(encoding="utf-8")).get("metadata", {})
        out.append({"item": item, "volume": label, "letters": letters, "path": text, "sha256": sha256(text),
                    "bytes": text.stat().st_size, "licenseurl": md.get("licenseurl"), "ocr": md.get("ocr"),
                    "title": md.get("title"), "date": md.get("date")})
    return out


# A headword opens a line in capitals (the OCR drops in the odd lower-case letter or a stray mark before it) and is
# followed by a comma, or by lower-case text when the line before closed a sentence ("strict"). The long entries
# often have a damaged opening ("v ANlMUS j i, m. 2."); such a line counts ("loose") when the capitals read as a
# lemma Lewis & Short or the lemma index knows, grammar follows it, the line before does not end in a
# cross-reference cue, and the word falls between the strict headwords around it.
HEAD = re.compile(r"^[^A-Za-zÆŒ]{0,4}([A-ZÆŒ][A-Za-zÆŒæœ®01\-]{1,30}?)(\s*,|\s+(?=[a-zæœ(]))")
MIDLINE = re.compile(r"(?<=[a-z.,;:)»\-] )(?=[A-ZÆŒ][A-ZÆŒ®]{2,}(?:, | vel [a-z]+, )[a-zæ0-9(])")
LOOSE = re.compile(r"^(?:[^A-Za-zÆŒ]{0,4}|[a-z] )([A-ZÆŒ][A-Za-zÆŒæœ01\-]{2,30})(?![A-Za-z])(\s?[.;:jl!|]?\s{0,2}[a-zæœ0-9«(][^A-Z]{0,12},)")
XREF = re.compile(r"\b(?:V|F|P|Cf|cf|vide|voce|voc|in|sub|et)\.?$")
GRAMMAR = re.compile(r"^(\S{3,22}?)[,.;]? (?:\S{1,9} ){0,5}?(?:[mfnc]\. ?[1-5Il][.,]|[an]\. ?[1-4][.,]|adject\.|adjeci|adverb\.|pronom\.|conjunct\.|praepos\.)")
CUE = re.compile(r"(?:\b(?:V|F|P|Cf|cf|vide|voce|voc|in|sub|et|ad|a|ab|ex|pro)\.?|[,;(-])$")
RUNNING_HEAD = re.compile(r"^[^a-z]{1,60}$")
ROMAN = re.compile(r"^[IVXLCDM]+$")


def capitals(token: str) -> bool:
    letters = [c for c in token if c.isalpha()]
    return len(letters) >= 2 and sum(c.isupper() for c in letters) / len(letters) >= 0.75 and (letters[1].isupper() or len(letters) >= 4)


def read_caps(token: str) -> str:
    """The token as capitals with the OCR's l/1 -> I and 0 -> O put right."""
    return token.replace("l", "I").replace("1", "I").replace("0", "O").replace("®", "AE")


def head_of(line: str, prev: str, known: set[str]) -> tuple[str, bool | None] | None:
    """(headword token, strict) when the line opens an entry; strict is None for a damaged opening known only by
    the grammar after it ("op.MCS, us, f. 4." = DOMUS), which stays an entry only if repair() can name it."""
    m = HEAD.match(line)
    if m:
        token = read_caps(m.group(1).strip("-"))
        if capitals(token) and ("," in m.group(2) or not (ROMAN.match(token) or (prev and prev[-1] not in ".)?!:;"))):
            return token, True
    m = LOOSE.match(line)
    if m and known:
        token = read_caps(m.group(1).strip("-"))
        if capitals(token) and fold(token) in known and not CUE.search(prev):
            return token, False
    m = GRAMMAR.match(line)
    if m and known and (not prev or prev[-1] in ".)?!:;") and not XREF.search(prev):
        letters = [c for c in m.group(1) if c.isalpha()]
        if len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) >= 0.5:
            return read_caps(m.group(1)), None
    return None


def clean(lines: list[str]) -> str:
    """Entry text: running heads dropped, line-end hyphenation closed, lines of a paragraph joined."""
    paras, cur = [], ""
    for raw in lines:
        line = raw.strip()
        if not line:
            if cur:
                paras.append(cur)
                cur = ""
            continue
        if RUNNING_HEAD.match(line) and len(line) < 40 and not cur.endswith(("¬", "-")) and paras + [cur] != [""]:
            continue
        if cur.endswith("¬") or (cur.endswith("-") and line[:1].islower() and not cur.endswith(" -")):
            cur = cur[:-1] + line
        else:
            cur = f"{cur} {line}" if cur else line
    if cur:
        paras.append(cur)
    return re.sub(r"[ \t]+", " ", "\n".join(paras)).replace("¬", "").strip()


def cut(text: str, known: set[str]) -> list[tuple[str, str, bool]]:
    """[(printed headword, entry text, weak)] in printed order; weak = known only by its grammar (head_of)."""
    lines = []
    for line in text.splitlines():
        if len(line) > 70:      # two or three columns run together: a headword in mid-line opens a line of its own
            start = 0
            for m in MIDLINE.finditer(line):
                if not XREF.search(line[start:m.start()].rstrip()):
                    lines += [line[start:m.start()], ""]
                    start = m.start()
            line = line[start:]
        lines.append(line)
    cands, prev = [], ""
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            prev = ""     # a blank line counts as a closed sentence
            continue
        found = head_of(s, prev, known)
        if found and fold(found[0]):
            cands.append((i, found[0], found[1]))
        prev = s
    letters = [fold(t)[0] for _, t, _ in cands]
    inletter = []
    for k, cand in enumerate(cands):       # a headword stands in its volume's running letter
        window = letters[max(0, k - 20):k + 21]
        if cand[2] is None or letters[k] == Counter(window).most_common(1)[0][0]:
            inletter.append(cand)
    # a loose headword must fall between the nearest strict headwords that are known lemmas (first three letters)
    anchors = [(k, fold(t)[:3]) for k, (_, t, strict) in enumerate(inletter) if strict and fold(t) in known]
    anchor_pos = [k for k, _ in anchors]
    keep = []
    for k, (i, token, strict) in enumerate(inletter):
        if strict is False:
            a = bisect.bisect_left(anchor_pos, k)
            before = anchors[a - 1][1] if a else ""
            after = anchors[a][1] if a < len(anchors) else "zzz"
            if not (before <= fold(token)[:3] <= after):
                continue
        keep.append((i, token, strict is None))
    out = []
    for (i, token, weak), nxt in zip(keep, keep[1:] + [(len(lines), "", False)]):
        body = clean(lines[i:nxt[0]])
        if len(body) > len(token) + 3:
            out.append((token, body, weak))
    return out


# Letter pairs the OCR confuses in these capitals (after folding): swapping them, or losing or gaining a thin letter,
# costs half of any other change.
CONFUSED = {frozenset(pair) for pair in ("uo uc ul uq ud uy un ui eb ef ec ek er es eo il it iy rh rb rp rk rn oq oc "
                                         "od og mn mh cg pf tf ty xk hn hb hk db sg sb lt").split()}
CHEAP, THIN, DEAR = 0.5, 0.6, 1.2


def ocr_cost(a: str, b: str, limit: float) -> float:
    """Weighted edit distance from the printed reading a to the lemma b; anything over the limit returns limit + 1."""
    if abs(len(a) - len(b)) * THIN > limit:
        return limit + 1
    row = [0.0]
    for cb in b:
        row.append(row[-1] + (THIN if cb in "ilt" else DEAR))
    for ca in a:
        new = [row[0] + (THIN if ca in "ilt" else DEAR)]
        for j, cb in enumerate(b, 1):
            swap = 0.0 if ca == cb else CHEAP if frozenset((ca, cb)) in CONFUSED else DEAR
            new.append(min(row[j] + (THIN if ca in "ilt" else DEAR), new[j - 1] + (THIN if cb in "ilt" else DEAR), row[j - 1] + swap))
        if min(new) > limit:
            return limit + 1
        row = new
    return row[-1] if row[-1] <= limit else limit + 1


def flat(word: str) -> str:
    return word.replace("ae", "e").replace("oe", "e")


def known_lemmas() -> set[str]:
    known: set[str] = set()
    for path, sql in ((LEWIS_SHORT, "SELECT DISTINCT folded FROM entries"), (LEMMA_INDEX, "SELECT DISTINCT lemma FROM lemma")):
        if path.exists():
            db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            known.update(f for (w,) in db.execute(sql) if (f := fold(w)))
            db.close()
    return known


def repair(entries: list[tuple[str, str, bool]], known: set[str]) -> list[tuple[str, str, str, int]]:
    """[(headword, folded, text, repaired)]: a headword no lexicon knows takes the one known lemma that lies between
    its nearest known neighbours and differs from it only by letters the OCR confuses (VENUSTATOS -> uenustatus)."""
    ordered = sorted(known)
    folded = [fold(h) for h, _, _ in entries]
    present = set(folded)
    out = []
    for k, (head, text, weak) in enumerate(entries):
        f, fixed = folded[k], None
        if known and f not in known:
            before = next((folded[j] for j in range(k - 1, max(-1, k - 9), -1) if folded[j] in known), None)
            after = next((folded[j] for j in range(k + 1, min(len(entries), k + 9)) if folded[j] in known), None)
            near = set(folded[max(0, k - 3):k + 4])     # a homograph stands next to its twin
            # the ligatures: the OCR reads AE as JE, TE, vE, iE, zE and OE as CE, GE
            variants = [f[:m.start()] + ("o" if m.group(0) in "cg" else "a") + f[m.start() + 1:]
                        for m in re.finditer(r"[itusz](?=e)|[cg](?=e)", f)]
            # or drops the ligature's first half altogether (SEPE for SAEPE, CELUM for CAELUM)
            variants += [f[:m.start()] + v + f[m.start():] for m in re.finditer("e", f) for v in "ao"]
            # whole stretches (CAE-, LAE-, PRAE-) are misread alike, so the known neighbours are sought further off
            # and the order is tested on the spelling without ae/oe
            wide_lo = next((folded[j] for j in range(k - 1, max(-1, k - 41), -1) if folded[j] in known), None)
            wide_hi = next((folded[j] for j in range(k + 1, min(len(entries), k + 41)) if folded[j] in known), None)
            if wide_lo and wide_hi:
                for v in variants:
                    if v in known and (v not in present or v in near) and flat(wide_lo) <= flat(v) <= flat(wide_hi):
                        fixed = v
                        break
            if fixed:
                present.add(fixed)
                folded[k] = fixed
                out.append((fixed, fixed, text, 1))
                continue
            if before and after:
                lo, hi = sorted((before, after))
                between = [w for w in ordered[bisect.bisect_left(ordered, lo):bisect.bisect_right(ordered, hi)]
                           if w not in present or w in near]
                if len(between) <= 400:
                    limit = (0.6 if len(f) < 5 else 1.0 if len(f) < 8 else 1.2 if len(f) < 11 else 1.7) * (2 if weak else 1)
                    scored = sorted((d, w) for w in between if (d := ocr_cost(f, w, limit)) <= limit
                                    and (w not in near or d <= CHEAP))
                    if scored and (len(scored) == 1 or scored[1][0] > scored[0][0]):
                        fixed = scored[0][1]
                    elif weak and not scored:      # a damaged opening: the one lemma still missing between its neighbours
                        missing = [w for w in between if w not in present]
                        if len(missing) == 1 and len(between) <= 12 and ocr_cost(f, missing[0], 0.3 * len(missing[0]) * DEAR) < 99 \
                                and ocr_cost(f, missing[0], 0.3 * len(missing[0]) * DEAR) <= 0.3 * len(missing[0]) * DEAR:
                            fixed = missing[0]
        if weak and not fixed and f not in known:        # not an entry after all: its text goes back to the entry before
            if out:
                out[-1] = (out[-1][0], out[-1][1], out[-1][2] + "\n" + text, out[-1][3])
            folded[k] = ""
            continue
        if fixed:
            present.add(fixed)
            folded[k] = fixed
            out.append((fixed, fixed, text, 1))
        else:
            out.append((head.lower().replace("æ", "ae").replace("œ", "oe"), f, text, 0))
    return out


def author_lemmas(author: str) -> set[str]:
    if not LEMMA_INDEX.exists():
        return set()
    db = sqlite3.connect(f"file:{LEMMA_INDEX.as_posix()}?mode=ro", uri=True)
    rows = db.execute("SELECT DISTINCT lemma FROM author_lemma WHERE lower(author) = ? AND in_corpus = 1", (author,)).fetchall()
    db.close()
    return {f for (w,) in rows if (f := fold(w))}


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, headword TEXT, folded TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS entries_folded ON entries(folded);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS source (entry_id INTEGER PRIMARY KEY, volume TEXT, seq INTEGER, printed TEXT, repaired INTEGER,
  UNIQUE(volume, seq));
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="store at most N new entries this run (0 = no limit)")
    ap.add_argument("--lemmas", choices=("catullus", "all"), default="all",
                    help="catullus: only entries whose headword is one of Catullus's lemmas; all: every entry")
    ap.add_argument("--rebuild", action="store_true", help="drop the store and cut the raw text again")
    args = ap.parse_args()

    volumes = fetch_all()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUT)
    db.executescript(SCHEMA)
    stored_parser = db.execute("SELECT value FROM meta WHERE key = 'parser'").fetchone()
    if args.rebuild or (stored_parser and stored_parser[0] != PARSER):
        db.executescript("DROP TABLE entries; DROP TABLE meta; DROP TABLE source;" + SCHEMA)
    done = {(v, s) for v, s in db.execute("SELECT volume, seq FROM source")}
    known = known_lemmas()
    wanted = author_lemmas("catullus") if args.lemmas == "catullus" else None
    added, cut_counts, repaired = 0, {}, 0
    for vol in volumes:
        entries = repair(cut(vol["path"].read_text(encoding="utf-8", errors="replace"), known), known)
        cut_counts[vol["volume"]] = len(entries)
        for seq, (head, folded, text, fixed) in enumerate(entries):
            if (vol["volume"], seq) in done or (wanted is not None and folded not in wanted):
                continue
            if args.limit and added >= args.limit:
                break
            cur = db.execute("INSERT INTO entries(headword, folded, text) VALUES (?,?,?)", (head, folded, text))
            printed = text.split(",")[0][:40]
            db.execute("INSERT INTO source(entry_id, volume, seq, printed, repaired) VALUES (?,?,?,?,?)",
                       (cur.lastrowid, vol["volume"], seq, printed, fixed))
            added += 1
        db.commit()
    n = db.execute("SELECT count(*) FROM entries").fetchone()[0]
    repaired = db.execute("SELECT count(*) FROM source WHERE repaired = 1").fetchone()[0]
    retrieved = datetime.now(timezone.utc).date().isoformat()
    for key, value in (("name", "forcellini"), ("title", TITLE), ("language", "la"), ("direction", "la-la"),
                       ("source_url", SOURCE_URL), ("licence", LICENCE_NOTE), ("retrieved", retrieved),
                       ("n_entries", str(n)), ("parser", PARSER),
                       ("source_items", ", ".join(f"https://archive.org/details/{v['item']}" for v in volumes)),
                       ("text_quality", "uncorrected OCR (ABBYY FineReader 11); headwords cut by rule")):
        db.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    db.commit()

    have = {f for (f,) in db.execute("SELECT DISTINCT folded FROM entries")}
    coverage = {}
    for author in ("catullus", "horace"):
        lemmas = author_lemmas(author)
        if lemmas:
            coverage[author] = {"lemmas": len(lemmas), "with_entry": len(lemmas & have),
                                "share": round(len(lemmas & have) / len(lemmas), 4)}
    entry_hash = hashlib.sha256()
    for head, text in db.execute("SELECT headword, text FROM entries ORDER BY id"):
        entry_hash.update(f"{head}\t{text}\n".encode("utf-8"))
    total_cut = sum(cut_counts.values())
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "name": "forcellini", "title": TITLE, "language": "la", "direction": "la-la",
        "source": "archive.org OCR text (_djvu.txt) of the five volumes; not the linguax.com electronic text",
        "source_url": SOURCE_URL, "licence": LICENCE_NOTE, "retrieved": retrieved,
        "store": str(OUT.relative_to(ROOT)), "n_entries": n, "distinct_folded_headwords": len(have),
        "headwords_repaired_against_known_lemmas": repaired,
        "entries_cut_per_volume": cut_counts, "complete": n >= total_cut,
        "coverage": coverage, "entries_sha256": entry_hash.hexdigest(),
        "raw_files": [{"item": v["item"], "volume": v["volume"], "letters": v["letters"],
                       "url": f"https://archive.org/download/{v['item']}/{urllib.parse.quote(dict((i, n_) for i, n_, _, _ in VOLUMES)[v['item']])}",
                       "path": str(v["path"].relative_to(ROOT)), "bytes": v["bytes"], "sha256": v["sha256"],
                       "licenseurl": v["licenseurl"], "ocr": v["ocr"], "item_title": v["title"], "item_date": v["date"]}
                      for v in volumes],
        "missing": ["the Onomasticon (proper names; De-Vit / Perin) is not part of these five volumes",
                    "one-letter headwords (A, E, O ...) and headwords whose capitals the OCR broke are not cut out; their text sits at the end of the entry before",
                    "entry text is uncorrected OCR: Greek is garbled, letters are misread (u/n, s/a, l/i), citations are not marked up",
                    "lexica.linguax.com (the corrected electronic text) refused automated access: robots.txt Disallow: / for all agents and an HTTP 511 proof-of-work / CAPTCHA page"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    db.close()
    print(json.dumps({"added": added, "n_entries": n, "cut": cut_counts, "repaired": repaired, "coverage": coverage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
