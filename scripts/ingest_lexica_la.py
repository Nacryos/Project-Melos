#!/usr/bin/env python3
"""Ingest ready-made structured Latin dictionaries into data/lexica/lex_<name>.sqlite, one file per dictionary.

Shared contract (three builders write it, backend/latin_lexica.py reads it):
  entries(id INTEGER PRIMARY KEY, headword TEXT, folded TEXT, text TEXT), index on folded;
  meta(key, value): name, title, language, direction, source_url, licence (verbatim), retrieved, n_entries.
Extra here: forms(folded, entry_id) for alternative headwords, and entries_fts (FTS5 over headword and text).
Latin headwords fold as backend/latin_dictionary.fold does; English and German headwords fold to lowercase.

Sources are files that their keepers publish as structured text (StarDict archives of the latin-dict project on
GitHub, the Gaffiot 2016 JSON). Raw downloads go to data/raw/latin/lexica/<name>/ and every fetch is appended to
data/raw/latin/fetch-log.jsonl; the built stores stay local (data/lexica/ is gitignored); a small manifest per
dictionary is committed under data/open/latin/lexica/. Private use: several of these may not be redistributed.

    .venv/bin/python scripts/ingest_lexica_la.py            # every source
    .venv/bin/python scripts/ingest_lexica_la.py gaffiot    # one
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import io
import json
import re
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.latin_dictionary import fold  # noqa: E402

RAW = ROOT / "data/raw/latin/lexica"
LOG = ROOT / "data/raw/latin/fetch-log.jsonl"
OUT = ROOT / "data/lexica"
OPEN = ROOT / "data/open/latin/lexica"
USER_AGENT = "Melos/1.0 (+https://greeklyric.com)"
PAUSE = 1.1                      # seconds between requests
GH = "https://github.com/latin-dict"
GHRAW = "https://raw.githubusercontent.com/latin-dict"

SOURCES: dict[str, dict] = {
    "smith_hall": {
        "title": "W. Smith and T. D. Hall, A Copious and Critical English-Latin Dictionary (1871)",
        "language": "en", "direction": "en-la", "reader": "stardict", "source_url": f"{GH}/SmithHall1871",
        "files": [f"{GH}/SmithHall1871/releases/download/v0.2/SmithHall1871-stardict.zip"],
        "licence_files": [f"{GHRAW}/SmithHall1871/main/README.md", f"{GHRAW}/SmithHall1871/main/LICENSE"]},
    "riddle_arnold": {
        "title": "J. E. Riddle and T. K. Arnold, A Copious and Critical English-Latin Lexicon (1864)",
        "language": "en", "direction": "en-la", "reader": "stardict", "source_url": f"{GH}/Riddle1864",
        "files": [f"{GH}/Riddle1864/releases/download/v1.0/Riddle1864-stardict.zip"],
        "licence_files": [f"{GHRAW}/Riddle1864/main/README.md"]},
    "lewis_elementary": {
        "title": "C. T. Lewis, An Elementary Latin Dictionary (1890)",
        "language": "en", "direction": "la-en", "reader": "stardict", "source_url": f"{GH}/Lewis1890",
        "files": [f"{GH}/Lewis1890/releases/download/v1.1/Lewis1890-stardict.zip"],
        "licence_files": [f"{GHRAW}/Lewis1890/master/README.md", f"{GHRAW}/Lewis1890/master/LICENSE"]},
    "doederlein": {
        "title": "L. Doederlein, Hand-book of Latin Synonymes, tr. H. H. Arnold (1874)",
        "language": "en", "direction": "la-en", "reader": "stardict", "source_url": f"{GH}/Doederlein1874",
        "files": [f"{GH}/Doederlein1874/releases/download/v1.1/Doederlein1875-stardict.zip"],
        "licence_files": [f"{GHRAW}/Doederlein1874/main/README.md", f"{GHRAW}/Doederlein1874/main/LICENSE"]},
    "georges_de_la": {
        "title": "K. E. Georges, Kleines deutsch-lateinisches Handwoerterbuch (1910)",
        "language": "de", "direction": "de-la", "reader": "stardict", "source_url": f"{GH}/Georges1910",
        "files": [f"{GH}/Georges1910/releases/download/v1.0/Georges1910-stardict.zip"],
        "licence_files": [f"{GHRAW}/Georges1910/main/README.md", f"{GHRAW}/Georges1910/main/LICENSE"]},
    "georges": {
        "title": "K. E. Georges, Ausfuehrliches lateinisch-deutsches Handwoerterbuch, 8th ed. (1913-1918)",
        "language": "de", "direction": "la-de", "reader": "stardict", "source_url": "https://tuxor1337.frama.io/firedict/dictionaries.html",
        "files": ["https://tovotu.de/data/stardict/georges_lat-de.zip"],
        "licence_files": ["https://tuxor1337.frama.io/firedict/dictionaries.html"],
        "licence": "Public Domain (copyright expired, published 1913) [the keeper's list, tuxor1337.frama.io/firedict/dictionaries.html; "
                   "the text was converted from zeno.org with the keeper's tool dictmaster, and zeno.org states its own terms for its edition]"},
    "gaffiot": {
        "title": "F. Gaffiot, Dictionnaire latin-francais (1934), ed. Gaffiot 2016 (Greco, De Wilde, Marechal, Okubo), komarov",
        "language": "fr", "direction": "la-fr", "reader": "gaffiot_json", "source_url": "https://github.com/Gaffiot/digital-gaffiot-json",
        "files": ["https://raw.githubusercontent.com/Gaffiot/digital-gaffiot-json/master/gaffiot.json"],
        "licence_files": ["https://raw.githubusercontent.com/Gaffiot/digital-gaffiot-json/master/README.md"]},
}


def fetch(url: str, dest: Path, note: str) -> Path:
    """Download once (a file already on disk is kept), politely, and log the fetch."""
    if dest.exists() and dest.stat().st_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    status, data = 0, b""
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, data = r.status, r.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
    finally:
        time.sleep(PAUSE)
    if status == 200 and data:
        dest.write_bytes(data)
    row = {"url": url, "path": str(dest.relative_to(ROOT)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest() if data else "",
           "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "http_status": status, "licence_note": note}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if status != 200 or not data:
        raise RuntimeError(f"{url}: HTTP {status}")
    return dest


_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<(?:br|/p|/div|/li|/tr|/h\d|/blockquote|/dd|/dt|/orth|/sense|/entryfree|/k|/def)\b[^>]*>", re.I)
_SENSE = re.compile(r"<sense\b[^>]*?\bmarker=\"([^\"]*)\"[^>]*>", re.I)


def plain(markup: str) -> str:
    """Dictionary markup (HTML, XDXF) -> text: block ends become newlines, tags go, entities resolve."""
    t = re.sub(r"<(style|script)\b.*?</\1>", " ", markup, flags=re.S | re.I)
    t = _SENSE.sub(lambda m: f"\n{m.group(1)} ", t)             # Smith & Hall: the sense number is an attribute
    t = html.unescape(_TAG.sub("", _BREAK.sub("\n", t)))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\s*\n\s*", "\n", t).strip()


def read_stardict(archive: Path) -> tuple[dict, list[tuple[str, str, list[str]]]]:
    """(ifo, [(headword, article, alternative headwords)]) from a zipped StarDict dictionary, in file order."""
    z = zipfile.ZipFile(archive)
    names = {n.lower().rsplit(".", 2)[-1] if not n.lower().endswith((".dict.dz", ".idx.gz")) else n.lower()[-7:].lstrip("."): n
             for n in z.namelist() if not n.endswith("/")}
    pick = lambda *ends: next((n for n in z.namelist() if n.lower().endswith(ends)), None)  # noqa: E731
    ifo = dict(line.split("=", 1) for line in z.read(pick(".ifo")).decode("utf-8").splitlines() if "=" in line)
    del names
    idx_name, dict_name, syn_name = pick(".idx", ".idx.gz"), pick(".dict.dz", ".dict"), pick(".syn", ".syn.dz")
    idx = z.read(idx_name)
    if idx_name.lower().endswith(".gz"):
        idx = gzip.decompress(idx)
    body = z.read(dict_name)
    if dict_name.lower().endswith(".dz"):
        body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
    wide = ifo.get("idxoffsetbits") == "64"
    fmt, step = (">QI", 12) if wide else (">II", 8)
    seq = ifo.get("sametypesequence", "")
    words, i = [], 0
    while i < len(idx):
        j = idx.index(b"\0", i)
        off, size = struct.unpack(fmt, idx[j + 1:j + 1 + step])
        art = body[off:off + size]
        if not seq:                      # typed fields: one type byte, then a NUL-terminated string
            art = art[1:].split(b"\0", 1)[0]
        words.append([idx[i:j].decode("utf-8"), art.decode("utf-8", "replace"), []])
        i = j + 1 + step
    if syn_name:
        syn = z.read(syn_name)
        if syn_name.lower().endswith(".dz"):
            syn = gzip.decompress(syn)
        i = 0
        while i < len(syn):
            j = syn.index(b"\0", i)
            (k,) = struct.unpack(">I", syn[j + 1:j + 5])
            if k < len(words):
                words[k][2].append(syn[i:j].decode("utf-8"))
            i = j + 5
    merged: dict[tuple[int, int], int] = {}      # several index words may point at one article
    out: list[tuple[str, str, list[str]]] = []
    for w, art, alts in words:
        key = (hash(art), len(art))
        if key in merged:
            out[merged[key]][2].extend([w, *alts])
            continue
        merged[key] = len(out)
        out.append((w, art, alts))
    return ifo, out


def read_gaffiot_json(path: Path) -> tuple[dict, list[tuple[str, str, list[str]]]]:
    """Gaffiot 2016 as converted to JSON for the Gaffiot app: [{id, latin_raw, latin, french}], the article in the
    komarov TeX markup. The headword is `latin` (homograph number in front, quantities marked)."""
    out = []
    for r in json.loads(path.read_text(encoding="utf-8")):
        head = (r.get("latin") or r.get("latin_raw") or "").strip()
        if head:
            out.append((head.rstrip(" ,"), gaffiot_text(f"{head} {r.get('french', '')}"), []))
    return {}, out


_TEX_KEEP = re.compile(r"\\(?:[a-zA-Z]+)\s*\{([^{}]*)\}")


def gaffiot_text(tex: str) -> str:
    """The komarov TeX markup -> text: \\macro{body} keeps its body, bare macros and braces go."""
    t = tex
    for _ in range(6):
        t, n = _TEX_KEEP.subn(r"\1", t)
        if not n:
            break
    t = re.sub(r"\\par\b", "\n", t)
    t = re.sub(r"\\[a-zA-Z]+\*?\s?", "", t).replace("{", "").replace("}", "").replace("~", " ").replace("\\,", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\s*\n\s*", "\n", t).strip()


READERS = {"stardict": read_stardict, "gaffiot_json": read_gaffiot_json}
SCHEMA = """
CREATE TABLE entries (id INTEGER PRIMARY KEY, headword TEXT, folded TEXT, text TEXT);
CREATE TABLE forms (folded TEXT, entry_id INTEGER);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE entries_fts USING fts5(headword, text, content='entries', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');
"""


def fold_head(word: str, direction: str) -> str:
    """Latin headwords fold as the L&S store does; English and German ones to lowercase."""
    w = re.sub(r"^\d+\s*|\s*\d+$|\s*\(.*?\)", "", word.strip())
    if direction.startswith("la-"):
        return fold(re.split(r"[,;]| or ", w)[0])
    return re.sub(r"\s+", " ", w.lower()).strip(" .,;:")


def licence_of(name: str, texts: list[str]) -> str:
    """The licence statement, verbatim, from the keeper's README or LICENSE (first lines that state it)."""
    for t in texts:
        m = re.search(r"(?im)^.*(creative commons|public domain|unlicense|cc0|cc[ -]by|licen[cs]e\b.*:).*$", t)
        if m:
            start = m.start()
            return re.sub(r"\s+", " ", t[start:start + 400]).strip()
    return "no licence statement in the keeper's repository"


def build(name: str) -> dict:
    src = SOURCES[name]
    raw = RAW / name
    note = f"{src['title']}; private local use, built store not redistributed"
    files = [fetch(u, raw / u.rsplit("/", 1)[-1], note) for u in src["files"]]
    texts = []
    for u in src["licence_files"]:
        try:
            texts.append(fetch(u, raw / u.rsplit("/", 1)[-1], f"licence text for {name}").read_text(encoding="utf-8", errors="replace"))
        except RuntimeError:
            pass
    licence = src.get("licence") or licence_of(name, texts)
    info, rows = READERS[src["reader"]](files[0])
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f"lex_{name}.sqlite.tmp"
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    forms = []
    for i, (head, art, alts) in enumerate(rows, 1):
        text = plain(art) if src["reader"] == "stardict" else art.strip()
        key = fold_head(head, src["direction"])
        db.execute("INSERT INTO entries VALUES (?,?,?,?)", (i, head.strip(), key, text))
        seen = {key}
        for alt in [*re.split(r"[,;]| or ", head)[1:], *alts]:
            k = fold_head(alt, src["direction"])
            if k and k not in seen:
                seen.add(k)
                forms.append((k, i))
    db.executemany("INSERT INTO forms VALUES (?,?)", forms)
    db.execute("INSERT INTO entries_fts(rowid, headword, text) SELECT id, headword, text FROM entries")
    retrieved = datetime.now().astimezone().strftime("%Y-%m-%d")
    meta = {"name": name, "title": src["title"], "language": src["language"], "direction": src["direction"],
            "source_url": src["source_url"], "licence": licence, "retrieved": retrieved, "n_entries": str(len(rows))}
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.executescript("CREATE INDEX entries_folded ON entries(folded); CREATE INDEX forms_folded ON forms(folded);")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(OUT / f"lex_{name}.sqlite")
    OPEN.mkdir(parents=True, exist_ok=True)
    manifest = {**meta, "n_entries": len(rows), "n_alternative_forms": len(forms), "store": f"data/lexica/lex_{name}.sqlite (local, gitignored)",
                "stardict_info": {k: info[k] for k in ("bookname", "wordcount", "synwordcount", "sametypesequence") if k in info},
                "raw_files": [{"url": u, "path": str(f.relative_to(ROOT)), "bytes": f.stat().st_size,
                               "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for u, f in zip(src["files"], files)]}
    (OPEN / f"{name}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help=f"which to build (default all): {', '.join(SOURCES)}")
    args = ap.parse_args()
    failed = 0
    for name in args.names or list(SOURCES):
        try:
            m = build(name)
            print(f"{name}: {m['n_entries']} entries, {m['n_alternative_forms']} alternative forms; licence: {m['licence'][:90]}")
        except Exception as exc:  # noqa: BLE001 - one source failing must not stop the others
            failed += 1
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
