"""Owner private corpus: drop-folder ingestion and passage links (release T).

Runs on the box only, normally inside the network-less ingest container
(deploy/private_ingest.sh), so it cannot fetch anything:

    private_ingest.py ingest --root /home/alvin/melos-private --originals ~/storagebox/melos-private/originals
    private_ingest.py link   --root ... --corpus /home/alvin/melos-o/data/corpus.sqlite
    private_ingest.py status --root ...

Drop folder: <root>/inbox/. Each file needs a provenance manifest next to it, named
``<file name>.json`` (see docs/private-mode.md for the fields). Files without a valid manifest are
moved to <root>/rejected/ with a reason. Accepted formats: PDF (text layer with page numbers;
OCR per page when the text layer is empty or, for Greek, unreadable), EPUB (printed page breaks
when the book marks them, else sections), plain text / Markdown (form feeds = pages), TEI XML
(<pb n=".."/> = pages), Beta Code text (manifest ``"encoding": "betacode"``; e.g. the owner's own
licensed TLG export). Nothing is downloaded, ever; the pipeline only reads the drop folder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html.parser
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.private_schema import KINDS, SCHEMA, fold  # noqa: E402

FORMATS = {".pdf", ".epub", ".txt", ".md", ".xml", ".tei", ".beta"}
REQUIRED = ("title", "kind", "rights_basis", "citation")
# Shadow libraries: the owner supplies material they own or license, never copies from these.
REFUSED_SOURCES = re.compile(r"lib\s*gen|library\s*genesis|z-?lib|sci-?hub|anna'?s\s*archive|b-?ok\.(?:cc|org)|"
                             r"pdfdrive|1lib|ebook3000|vdoc\.pub", re.I)
MIN_TEXT_LETTERS = 40
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")


# --------------------------------------------------------------------------- manifest

def validate_manifest(manifest: dict) -> list[str]:
    problems = [f"missing {field}" for field in REQUIRED if not str(manifest.get(field, "")).strip()]
    if manifest.get("owner_attestation") is not True:
        problems.append("owner_attestation must be true (the owner owns or is licensed to use this file)")
    if manifest.get("kind") and manifest["kind"] not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    text = json.dumps(manifest, ensure_ascii=False)
    if REFUSED_SOURCES.search(text):
        problems.append("refused: the manifest names a shadow library; only owned or licensed copies are accepted")
    return problems


# --------------------------------------------------------------------------- extraction

def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def ocr_pdf_page(path: Path, page_no: int, languages: str) -> str:
    if not (_have("pdftoppm") and _have("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        _run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(page_no), "-l", str(page_no), str(path), str(prefix)])
        images = sorted(Path(tmp).glob("page*.png"))
        if not images:
            return ""
        out = _run(["tesseract", str(images[0]), "stdout", "-l", languages, "--psm", "3"])
        return out.stdout.decode("utf-8", "replace")


def pdf_page_labels(path: Path) -> list[str] | None:
    try:
        from pypdf import PdfReader
        return list(PdfReader(str(path)).page_labels)
    except Exception:  # noqa: BLE001 - labels are optional
        return None


def extract_pdf(path: Path, manifest: dict) -> list[dict]:
    if _have("pdftotext"):
        raw = _run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"]).stdout.decode("utf-8", "replace")
        texts = raw.split("\f")
        if texts and not texts[-1].strip():
            texts.pop()
    else:
        from pypdf import PdfReader
        texts = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    labels = pdf_page_labels(path)
    offset = int(manifest.get("page_offset", 0) or 0)
    ocr_mode = manifest.get("ocr", "auto")
    languages = manifest.get("ocr_languages", "grc+eng")
    expect_greek = bool(manifest.get("expect_greek", "grc" in str(manifest.get("language", "")) or "grc" in languages))
    pages = []
    for index, text in enumerate(texts, start=1):
        method = "text"
        sparse = _letters(text) < MIN_TEXT_LETTERS
        # A Greek text layer in a legacy font extracts as Latin letters only: treat it as unreadable.
        broken_greek = expect_greek and _letters(text) > 200 and not GREEK.search(text)
        if ocr_mode == "always" or (ocr_mode == "auto" and (sparse or broken_greek)):
            ocr = ocr_pdf_page(path, index, languages)
            if _letters(ocr) > _letters(text) * (0.5 if broken_greek else 1.0) and (not broken_greek or GREEK.search(ocr)):
                text, method = ocr, "ocr"
        if labels and len(labels) == len(texts) and not offset:
            label = labels[index - 1]
        else:
            label = str(index - offset) if index - offset >= 1 else f"[{index}]"
        pages.append({"page_no": index, "page_label": label, "method": method, "text": text.strip()})
    return pages


class _EpubText(html.parser.HTMLParser):
    BLOCKS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pages = [["", []]]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        kind = (attrs.get("epub:type") or "") + " " + (attrs.get("role") or "")
        if "pagebreak" in kind:
            label = attrs.get("title") or attrs.get("aria-label") or re.sub(r"\D+", "", attrs.get("id") or "")
            self.pages.append([label or "", []])
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCKS:
            self.pages[-1][1].append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.pages[-1][1].append(data)


def extract_epub(path: Path, manifest: dict) -> list[dict]:
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read("META-INF/container.xml"))
        opf_path = next(el.get("full-path") for el in container.iter() if el.tag.endswith("rootfile"))
        opf = ET.fromstring(book.read(opf_path))
        base = PurePosixPath(opf_path).parent
        items = {el.get("id"): el.get("href") for el in opf.iter() if el.tag.endswith("item")}
        spine = [el.get("idref") for el in opf.iter() if el.tag.endswith("itemref")]
        parser = _EpubText()
        sections = 0
        for idref in spine:
            href = items.get(idref)
            if not href:
                continue
            sections += 1
            if not any(label for label, _ in parser.pages[1:]):
                parser.pages.append([f"section {sections}", []])
            parser.feed(book.read(str(base / href)).decode("utf-8", "replace"))
    pages = []
    for label, parts in parser.pages:
        text = re.sub(r"\n\s*\n+", "\n\n", "".join(parts)).strip()
        if text:
            pages.append({"page_no": len(pages) + 1, "page_label": label or str(len(pages) + 1), "method": "text", "text": text})
    return pages


def _beta(text: str) -> str:
    from betacode.conv import beta_to_uni
    return "\n".join(beta_to_uni(line) for line in text.splitlines())


def extract_text(path: Path, manifest: dict) -> list[dict]:
    raw = path.read_bytes().decode(manifest.get("file_encoding", "utf-8"), "replace")
    if manifest.get("encoding") == "betacode" or path.suffix == ".beta":
        raw = _beta(raw)
    parts = raw.split("\f") if "\f" in raw else None
    if parts is None:
        parts, current = [], []
        for paragraph in re.split(r"\n\s*\n", raw):
            current.append(paragraph)
            if sum(len(p) for p in current) > 3000:
                parts.append("\n\n".join(current))
                current = []
        if current:
            parts.append("\n\n".join(current))
        label = "part {}"
    else:
        label = "{}"
    return [{"page_no": i, "page_label": label.format(i), "method": "text", "text": unicodedata.normalize("NFC", t).strip()}
            for i, t in enumerate(parts, start=1) if t.strip()]


def extract_tei(path: Path, manifest: dict) -> list[dict]:
    tree = ET.parse(path)
    body = next((el for el in tree.iter() if el.tag.split("}")[-1] == "body"), tree.getroot())
    pages = [["1", []]]

    def walk(el):
        tag = el.tag.split("}")[-1] if isinstance(el.tag, str) else ""
        if tag == "pb":
            pages.append([el.get("n") or str(len(pages) + 1), []])
        elif tag not in ("note",) or manifest.get("include_notes", True):
            if el.text:
                pages[-1][1].append(el.text)
            for child in el:
                walk(child)
                if child.tail:
                    pages[-1][1].append(child.tail)
            if tag in ("l", "p", "lg", "div", "head"):
                pages[-1][1].append("\n")

    walk(body)
    out = []
    for label, parts in pages:
        text = "".join(parts)
        if manifest.get("encoding") == "betacode":
            text = _beta(text)
        text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
        if text:
            out.append({"page_no": len(out) + 1, "page_label": label, "method": "text", "text": text})
    return out


def extract(path: Path, manifest: dict) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path, manifest)
    if suffix == ".epub":
        return extract_epub(path, manifest)
    if suffix in (".xml", ".tei"):
        return extract_tei(path, manifest)
    return extract_text(path, manifest)


# --------------------------------------------------------------------------- store

def open_store(root: Path, work: bool = False) -> sqlite3.Connection:
    """The store, or (``work``) a working copy that ``publish`` swaps in atomically, so the API
    (a read-only reader) never sees a half-written file."""
    (root / "store").mkdir(parents=True, exist_ok=True)
    live = root / "store" / "private.sqlite"
    path = live
    if work:
        path = live.with_name("private.sqlite.work")
        path.unlink(missing_ok=True)
        if live.exists():
            shutil.copy2(live, path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=DELETE")  # read-only readers in the container need no -shm/-wal
    con.executescript(SCHEMA)
    return con


def publish(root: Path, con: sqlite3.Connection) -> None:
    con.commit()
    con.close()
    work = root / "store" / "private.sqlite.work"
    work.chmod(0o600)
    os.replace(work, root / "store" / "private.sqlite")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _log(root: Path, record: dict) -> None:
    (root / "log").mkdir(parents=True, exist_ok=True)
    with (root / "log" / "ingest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(), **record}, ensure_ascii=False) + "\n")


def _reject(root: Path, path: Path, manifest_path: Path | None, reason: str) -> None:
    target = root / "rejected"
    target.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), target / path.name)
    if manifest_path and manifest_path.exists():
        shutil.move(str(manifest_path), target / manifest_path.name)
    (target / (path.name + ".reason.txt")).write_text(reason + "\n", encoding="utf-8")
    _log(root, {"file": path.name, "status": "rejected", "reason": reason})
    print(f"rejected {path.name}: {reason}")


def ingest(root: Path, originals: Path) -> int:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    originals.mkdir(parents=True, exist_ok=True)
    (root / "manifests").mkdir(parents=True, exist_ok=True)
    con = open_store(root, work=True)
    try:
        return _ingest_files(root, originals, con)
    finally:
        publish(root, con)  # documents committed so far are kept even if a later one fails


def _ingest_files(root: Path, originals: Path, con: sqlite3.Connection) -> int:
    inbox = root / "inbox"
    done = 0
    for path in sorted(inbox.iterdir()):
        if path.is_dir() or path.name.endswith(".json") or path.name.startswith("."):
            continue
        manifest_path = path.with_name(path.name + ".json")
        if path.suffix.lower() not in FORMATS:
            _reject(root, path, manifest_path, f"unsupported format {path.suffix}")
            continue
        if not manifest_path.exists():
            _reject(root, path, None, f"no provenance manifest ({manifest_path.name})")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _reject(root, path, manifest_path, f"manifest is not valid JSON: {exc}")
            continue
        problems = validate_manifest(manifest) if isinstance(manifest, dict) else ["manifest must be a JSON object"]
        if problems:
            _reject(root, path, manifest_path, "; ".join(problems))
            continue
        digest = sha256(path)
        doc_id = digest[:16]
        if con.execute("SELECT 1 FROM documents WHERE sha256=?", (digest,)).fetchone():
            _reject(root, path, manifest_path, f"already ingested as {doc_id}")
            continue
        try:
            pages = extract(path, manifest)
        except Exception as exc:  # noqa: BLE001 - report and keep the file for the owner
            _reject(root, path, manifest_path, f"could not read the file: {type(exc).__name__}: {exc}")
            continue
        if not pages:
            _reject(root, path, manifest_path, "no text found (and OCR produced none)")
            continue
        stored = originals / f"{digest}{path.suffix.lower()}"
        shutil.copy2(path, stored)
        if sha256(stored) != digest:
            stored.unlink()
            raise SystemExit(f"copy to {stored} did not verify; nothing ingested for {path.name}")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        ocr_pages = sum(p["method"] == "ocr" for p in pages)
        record = {**manifest, "doc_id": doc_id, "sha256": digest, "source_name": path.name, "pages": len(pages),
                  "ocr_pages": ocr_pages, "ingested_at": now, "original": stored.name,
                  "tools": {name: bool(shutil.which(name)) for name in ("pdftotext", "pdftoppm", "tesseract")}}
        with con:
            con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                doc_id, manifest["title"], manifest.get("author", ""), manifest.get("editor", ""),
                str(manifest.get("year", "")), manifest["kind"], manifest.get("language", ""), manifest["rights_basis"],
                manifest.get("acquired_from", ""), manifest["citation"], path.name, digest, stored.name, len(pages),
                ocr_pages, now, json.dumps(record, ensure_ascii=False)))
            for page in pages:
                con.execute("INSERT INTO pages VALUES (?,?,?,?,?)",
                            (doc_id, page["page_no"], page["page_label"], page["method"], page["text"]))
                con.execute("INSERT INTO page_fts(folded, doc_id, page_no) VALUES (?,?,?)",
                            (fold(page["text"]), doc_id, page["page_no"]))
            known = {p["page_no"] for p in pages}
            for item in manifest.get("passage_links") or []:
                if isinstance(item, dict) and item.get("passage_id") and int(item.get("page", 0) or 0) in known:
                    con.execute("INSERT INTO passage_links VALUES (?,?,?,?,?)",
                                (doc_id, int(item["page"]), str(item["passage_id"]), 1.0, "manifest"))
        (root / "manifests" / f"{doc_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        path.unlink()
        manifest_path.unlink()
        _log(root, {"file": path.name, "status": "ingested", "doc_id": doc_id, "pages": len(pages), "ocr_pages": ocr_pages})
        print(f"ingested {path.name} as {doc_id}: {len(pages)} pages ({ocr_pages} by OCR)")
        done += 1
    return done


# --------------------------------------------------------------------------- passage links

_GREEK_WORD = re.compile(r"[Ͱ-Ͽἀ-῿]+")


def greek_trigrams(text: str) -> set[tuple[str, str, str]]:
    words = [w for w in _GREEK_WORD.findall(fold(text)) if len(w) > 1]
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def link(root: Path, corpus: Path, min_shared: int = 2) -> int:
    """Link private pages to public Greek passages that share at least ``min_shared`` Greek word
    trigrams (a commentary quoting the lines it discusses). Only public passage ids are stored."""
    con = open_store(root, work=True)
    page_grams = {}
    for doc_id, page_no, text in con.execute("SELECT doc_id, page_no, text FROM pages"):
        grams = greek_trigrams(text)
        if grams:
            page_grams[(doc_id, page_no)] = grams
    wanted = set().union(*page_grams.values()) if page_grams else set()
    if not wanted:
        print("no Greek trigrams in the private pages; nothing to link")
        con.close()
        return 0
    public = sqlite3.connect(f"file:{corpus.as_posix()}?mode=ro", uri=True)
    posting: dict[tuple, list[str]] = {}
    for pid, text in public.execute("SELECT id, text FROM passages WHERE language='grc' AND kind='text'"):
        for gram in greek_trigrams(text) & wanted:
            posting.setdefault(gram, []).append(pid)
    total = 0
    with con:
        con.execute("DELETE FROM passage_links WHERE method='greek-trigrams'")
        for (doc_id, page_no), grams in page_grams.items():
            shared: dict[str, int] = {}
            for gram in grams:
                ids = posting.get(gram, ())
                if len(ids) > 50:  # formulaic phrase found everywhere: no evidence of a specific passage
                    continue
                for pid in ids:
                    shared[pid] = shared.get(pid, 0) + 1
            best = sorted(((n, pid) for pid, n in shared.items() if n >= min_shared), reverse=True)[:20]
            for n, pid in best:
                con.execute("INSERT INTO passage_links VALUES (?,?,?,?,?)",
                            (doc_id, page_no, pid, n / (n + 3.0), "greek-trigrams"))
                total += 1
        con.execute("INSERT OR REPLACE INTO meta VALUES ('linked_against', ?)",
                    (json.dumps({"corpus": corpus.name, "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                 "min_shared": min_shared}),))
    publish(root, con)
    print(f"{total} passage links from {len(page_grams)} pages with Greek")
    return total


def status(root: Path) -> None:
    con = open_store(root)
    for row in con.execute("SELECT doc_id, kind, citation, pages, ocr_pages FROM documents ORDER BY citation"):
        print("\t".join(str(v) for v in row))
    print("links:", con.execute("SELECT count(*) FROM passage_links").fetchone()[0])


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("ingest", "link", "status"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--originals", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--min-shared", type=int, default=2)
    args = parser.parse_args(argv)
    if args.command == "ingest":
        ingest(args.root, args.originals or args.root / "originals")
    elif args.command == "link":
        if not args.corpus:
            parser.error("link needs --corpus (the public corpus.sqlite)")
        link(args.root, args.corpus, args.min_shared)
    else:
        status(args.root)


if __name__ == "__main__":
    main()
