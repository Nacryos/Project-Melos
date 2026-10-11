#!/usr/bin/env python3
"""Ingest Catullus from the Perseus Digital Library TEI (PerseusDL/canonical-latinLit, CC BY-SA 4.0):
the Latin (E. T. Merrill, Ginn 1893; perseus-lat2) and two public-domain translations aligned poem by poem:
Smithers 1894 prose (perseus-eng4; chunks keyed to Latin line numbers) and Burton 1894 verse (perseus-eng3).

Inputs are the raw files under data/raw/latin/perseus/ (downloaded 2026-10-10, URL / sha256 / time in
data/raw/latin/fetch-log.jsonl). Nothing in the output is written from memory: every line comes from the TEI.
Editorial elements are rendered deterministically and the XML of each line is kept beside the text (`xml`: as lxml
serialises it, so the TEI xmlns is added and tag whitespace normalised; the raw bytes are the file in data/raw):
  <gap reason="lost" rend="..."/>  ->  the rend text itself (the edition's own dots or asterisk, padded with one
                                       space on each side), or "[...]" when absent
  <supplied>x</supplied> -> ⟨x⟩   <del>x</del> -> [x]   <add>x</add> -> x   <sic>/<corr> -> text
  <note> -> removed from the text, kept in `notes`   <persName>, <placeName>, <quote> ... -> text only
Outputs (data/open/latin/perseus-catullus/): poems.jsonl (one record per poem per file) and manifest.json.
Usage: python -I scripts/ingest_open_perseus_catullus.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "latin" / "perseus"
LOG = ROOT / "data" / "raw" / "latin" / "fetch-log.jsonl"
OUT = ROOT / "data" / "open" / "latin" / "perseus-catullus"
TEI = "{http://www.tei-c.org/ns/1.0}"
FILES = {
    "phi0472.phi001.perseus-lat2.xml": {"language": "la", "kind": "text", "label": "Merrill 1893 Latin"},
    "phi0472.phi001.perseus-eng4.xml": {"language": "en", "kind": "translation", "label": "Smithers 1894 prose"},
    "phi0472.phi001.perseus-eng3.xml": {"language": "en", "kind": "translation", "label": "Burton 1894 verse"},
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fetch_records() -> dict:
    out = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("path"):
                out[os.path.basename(r["path"])] = r
    return out


def render(el) -> tuple[str, list[str]]:
    """Text of a <l> with editorial elements rendered and notes removed (returned separately)."""
    notes: list[str] = []

    def walk(e) -> str:
        tag = etree.QName(e).localname if isinstance(e.tag, str) else ""
        if tag == "note":
            notes.append("".join(e.itertext()).strip())
            return e.tail or ""
        inner = (e.text or "") + "".join(walk(c) for c in e)
        if tag == "gap":
            body = " " + ((e.get("rend") or "").strip() or "[...]") + " "
        elif tag == "supplied":
            body = "⟨" + inner + "⟩"
        elif tag == "del":
            body = "[" + inner + "]"
        else:
            body = inner
        return body + (e.tail or "")

    text = (el.text or "") + "".join(walk(c) for c in el)
    text = unicodedata.normalize("NFC", re.sub(r"\s+", " ", text)).strip()
    return text, notes


def header(tree) -> dict:
    h = {}
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    for xp, key in (("//t:titleStmt/t:title", "title"), ("//t:titleStmt/t:editor", "editor"),
                    ("//t:sourceDesc//t:editor", "source_editor"), ("//t:sourceDesc//t:publisher", "source_publisher"),
                    ("//t:sourceDesc//t:date", "source_date"), ("//t:sourceDesc//t:pubPlace", "source_place"),
                    ("//t:availability/t:licence", "licence"), ("//t:sourceDesc//t:author", "author")):
        vals = tree.xpath(xp, namespaces=ns)
        if vals:
            h[key] = "".join(vals[0].itertext()).strip()
            if key == "licence":
                h["licence_url"] = vals[0].get("target", "")
    return h


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = fetch_records()
    manifest = {"name": "Catullus, Carmina: Perseus Digital Library TEI (PerseusDL/canonical-latinLit) with two public-domain translations",
                "date": time.strftime("%Y-%m-%d"), "user_agent": "Melos/1.0 (+https://greeklyric.com)",
                "repo": "https://github.com/PerseusDL/canonical-latinLit",
                "licence": {"name": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/",
                            "quote": "", "repo_license_md_sha256": sha(RAW / "license.md") if (RAW / "license.md").exists() else ""},
                "files": {}, "counts": {}}
    n_records = 0
    with open(OUT / "poems.jsonl", "w", encoding="utf-8") as out:
        for name, info in FILES.items():
            path = RAW / name
            tree = etree.parse(str(path))
            h = header(tree)
            if info["language"] == "la" and h.get("licence"):
                manifest["licence"]["quote"] = h["licence"]
            urn = tree.getroot().xpath("string(//t:div[@type='edition']/@n)", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
            # poem divs, plus a textpart div that itself holds lines (Smithers 67 is typed so in the eng4 file)
            poems = tree.xpath("//t:div[@subtype='poem' or (@subtype='textpart' and .//t:l and not(.//t:div))]",
                               namespaces={"t": "http://www.tei-c.org/ns/1.0"})
            n_lines = 0
            for p in poems:
                num = p.get("n", "")
                metre = [m.get("n", "") for m in p.findall(f"{TEI}milestone") if m.get("unit") == "meter"]
                # heads and speaker labels anywhere in the poem (62's Youths / Maidens, Burton's section heads in 64)
                head = [re.sub(r"\s+", " ", "".join(x.itertext())).strip() for x in p.iter(f"{TEI}head", f"{TEI}speaker")]
                lines, notes = [], []
                for l in p.iter(f"{TEI}l"):
                    text, ns_ = render(l)
                    notes += ns_
                    lines.append({"n": l.get("n", ""), "text": text,
                                  "xml": etree.tostring(l, encoding="unicode", with_tail=False).strip()})
                for x in p.findall(f"{TEI}note"):
                    notes.append(re.sub(r"\s+", " ", "".join(x.itertext())).strip())
                notes = [re.sub(r"\s+", " ", n) for n in notes]
                n_lines += len(lines)
                rec = {"id": f"perseus:{name.split('.perseus-')[1].split('.xml')[0]}:{num}", "source_file": name,
                       "urn": urn or f"urn:cts:latinLit:{name.replace('.xml', '')}", "poem": num, "language": info["language"],
                       "kind": info["kind"], "edition": info["label"], "metre_milestone": metre, "head": head,
                       "lines": lines, "notes": notes, "line_count": len(lines)}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_records += 1
            fr = fetched.get(name, {})
            manifest["files"][name] = {"url": fr.get("url", ""), "sha256": sha(path), "bytes": path.stat().st_size,
                                       "fetched_at": fr.get("fetched_at", ""), "fetch_log_sha256": fr.get("sha256", ""),
                                       "header": h, "poems": len(poems), "lines": n_lines, **info}
            print(name, len(poems), "poems", n_lines, "lines", h.get("editor") or h.get("source_editor"), file=sys.stderr)
    manifest["counts"]["records"] = n_records
    manifest["files"]["poems.jsonl"] = {"sha256": sha(OUT / "poems.jsonl"), "bytes": (OUT / "poems.jsonl").stat().st_size}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
