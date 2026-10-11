#!/usr/bin/env python3
"""Ingest Horace from the Perseus Digital Library TEI (PerseusDL/canonical-latinLit, CC BY-SA 4.0):
the Latin Odes (Shorey & Laing 1919; phi001 perseus-lat2), the Carmen Saeculare (Shorey & Laing 1919; phi002
perseus-lat2), the Epodes (Vollmer, Teubner 1912; phi003 perseus-lat2) and John Conington's public-domain verse
translation of the Odes (Bell 1882; phi001 perseus-eng2), aligned to the Latin by (book, poem).

Inputs are the raw files under data/raw/latin/perseus/ (downloaded 2026-10-11, URL / sha256 / time in
data/raw/latin/fetch-log.jsonl). Nothing in the output is written from memory: every line comes from the TEI.
Editorial elements are rendered with the the rules of scripts/ingest_open_perseus_catullus.py and the raw XML
of each line is kept beside the text:
  <gap reason="lost" rend="..."/>  ->  the rend text itself (the edition's own dots or asterisk), or "[...]" when absent
  <supplied>x</supplied> -> ⟨x⟩   <del>x</del> -> [x]   <add>x</add> -> x   <sic>/<corr> -> text
  <choice><sic/><corr/></choice> -> the <corr> text only
  <note> -> removed from the text, kept in `notes`   <persName>, <placeName>, <emph>, <quote> ... -> text only
  <pb/>, <lb/>, <milestone/> inside a line -> nothing (their tail text is kept)
Lines are flat; where the TEI groups them in <lg> stanzas the line carries a 1-based `stanza` index within the
poem, and where they sit inside an <sp> (the Horace/Lydia dialogue, Odes 3.9) the line carries `speaker`.
Record shape (one record per poem per file): id, source_file, urn, book ("" for the Carmen Saeculare and the
Epodes), poem, language, kind, edition (editor; publisher, place date, from the TEI header), metre_milestone,
head, lines [{n, text, xml, (stanza), (speaker)}], notes, line_count.
Anything the parser cannot handle is logged to stderr and listed in manifest.json under "problems"; nothing is
guessed or typed in. Outputs (data/open/latin/perseus-horace/): poems.jsonl and manifest.json.
Usage: python -I scripts/ingest_open_perseus_horace.py
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
OUT = ROOT / "data" / "open" / "latin" / "perseus-horace"
TEI = "{http://www.tei-c.org/ns/1.0}"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
FILES = {
    "phi0893.phi001.perseus-lat2.xml": {"work": "odes", "language": "la", "kind": "text"},
    "phi0893.phi002.perseus-lat2.xml": {"work": "carmen-saeculare", "language": "la", "kind": "text"},
    "phi0893.phi003.perseus-lat2.xml": {"work": "epodes", "language": "la", "kind": "text"},
    "phi0893.phi001.perseus-eng2.xml": {"work": "odes", "language": "en", "kind": "translation"},
}
# Elements the renderer knows how to handle inside a line; anything else is rendered as text and logged.
KNOWN_INLINE = {"gap", "supplied", "del", "add", "sic", "corr", "choice", "note", "persName", "placeName", "name",
                "emph", "hi", "quote", "q", "foreign", "pb", "lb", "milestone", "seg", "w", "abbr", "expan", "unclear",
                "title", "num", "date"}
# Children a poem div may have without comment.
KNOWN_POEM_CHILDREN = {"l", "lg", "head", "note", "milestone", "pb", "sp", "div"}


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


def render(el, problems: list[str], where: str) -> tuple[str, list[str]]:
    """Text of a <l> with editorial elements rendered and notes removed (returned separately)."""
    notes: list[str] = []

    def walk(e) -> str:
        if not isinstance(e.tag, str):  # comment / processing instruction
            return e.tail or ""
        tag = etree.QName(e).localname
        if tag == "note":
            notes.append(re.sub(r"\s+", " ", "".join(e.itertext())).strip())
            return e.tail or ""
        if tag == "choice":
            corr = e.find(f"{TEI}corr")
            inner = walk_inner(corr) if corr is not None else "".join(walk(c) for c in e)
            return inner + (e.tail or "")
        if tag not in KNOWN_INLINE:
            problems.append(f"{where}: unknown inline element <{tag}> rendered as text")
        inner = walk_inner(e)
        if tag == "gap":
            body = (e.get("rend") or "").strip() or "[...]"
        elif tag == "supplied":
            body = "⟨" + inner + "⟩"
        elif tag == "del":
            body = "[" + inner + "]"
        else:
            body = inner
        return body + (e.tail or "")

    def walk_inner(e) -> str:
        return (e.text or "") + "".join(walk(c) for c in e)

    text = walk_inner(el)
    text = unicodedata.normalize("NFC", re.sub(r"\s+", " ", text)).strip()
    return text, notes


def header(tree) -> dict:
    h: dict = {}
    def texts(xp):
        return [re.sub(r"\s+", " ", "".join(v.itertext())).strip() for v in tree.xpath(xp, namespaces=NS)]
    for xp, key in (("//t:titleStmt/t:title", "title"), ("//t:titleStmt/t:author", "author"),
                    ("//t:sourceDesc//t:title", "source_title"), ("//t:sourceDesc//t:publisher", "source_publisher"),
                    ("//t:sourceDesc//t:date", "source_date"), ("//t:sourceDesc//t:pubPlace", "source_place"),
                    ("//t:sourceDesc//t:author", "source_author")):
        vals = texts(xp)
        if vals:
            h[key] = vals[0]
    h["editors"] = texts("//t:titleStmt/t:editor")
    h["source_editors"] = texts("//t:sourceDesc//t:editor")
    roles = [e.get("role", "") for e in tree.xpath("//t:titleStmt/t:editor", namespaces=NS)]
    if any(roles):
        h["editor_roles"] = roles
    lic = tree.xpath("//t:availability/t:licence", namespaces=NS)
    if lic:
        h["licence"] = re.sub(r"\s+", " ", "".join(lic[0].itertext())).strip()
        h["licence_url"] = lic[0].get("target", "")
    return h


def edition_label(h: dict) -> str:
    eds = h.get("source_editors") or h.get("editors") or []
    imprint = ", ".join(x for x in (h.get("source_publisher", ""),
                                    " ".join(y for y in (h.get("source_place", ""), h.get("source_date", "")) if y)) if x)
    return "; ".join(x for x in (", ".join(eds), imprint) if x)


def licence_from_repo(path: Path) -> str:
    """The licence title line of the repo's license.md (the TEI headers carry no <availability>)."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.search(r"Attribution.*4\.0", line):
            return line.lstrip("# ").strip()
    return ""


def poem_records(tree, name: str, info: dict, urn: str, edition: str, problems: list[str]) -> list[dict]:
    ver = name.split(".perseus-")[1].split(".xml")[0]
    recs = []
    seen_keys: set[tuple[str, str]] = set()
    for p in tree.xpath("//t:div[@subtype='poem']", namespaces=NS):
        num = p.get("n", "")
        par = p.getparent()
        book = par.get("n", "") if par is not None and par.get("subtype") == "book" else ""
        ref = f"{book}.{num}" if book else num
        rid = f"perseus:{info['work']}:{ver}:{ref}"
        if not num:
            problems.append(f"{rid}: poem div without @n")
        if (book, num) in seen_keys:
            problems.append(f"{rid}: duplicate (book, poem) key")
        seen_keys.add((book, num))
        for ch in p:
            if isinstance(ch.tag, str) and etree.QName(ch).localname not in KNOWN_POEM_CHILDREN:
                problems.append(f"{rid}: unexpected child <{etree.QName(ch).localname}> of poem div")
        if (p.text or "").strip():
            problems.append(f"{rid}: stray text directly inside poem div: {p.text.strip()[:60]!r}")
        metre = [m.get("n", "") for m in p.findall(f"{TEI}milestone") if m.get("unit") == "meter"]
        met_attr = (p.get("met") or "").strip()        # Perseus labels every ode's metre here (audit 2026-10-11)
        if met_attr and met_attr not in metre:
            metre.append(met_attr)
        head = [re.sub(r"\s+", " ", "".join(x.itertext())).strip() for x in p.findall(f"{TEI}head")]
        lgs = list(p.iter(f"{TEI}lg"))
        lg_index = {id(lg): i + 1 for i, lg in enumerate(lgs)}
        lines, notes, seen_n = [], [], set()
        for l in p.iter(f"{TEI}l"):
            n = l.get("n", "")
            text, ns_ = render(l, problems, f"{rid} l.{n}")
            notes += ns_
            rec_l = {"n": n, "text": text,
                     "xml": etree.tostring(l, encoding="unicode", with_tail=False).strip()}
            a = l.getparent()
            while a is not None and a is not p:
                tag = etree.QName(a).localname if isinstance(a.tag, str) else ""
                if tag == "lg" and "stanza" not in rec_l:
                    rec_l["stanza"] = lg_index[id(a)]
                elif tag == "sp" and "speaker" not in rec_l:
                    sp = a.find(f"{TEI}speaker")
                    rec_l["speaker"] = re.sub(r"\s+", " ", "".join(sp.itertext())).strip() if sp is not None else ""
                a = a.getparent()
            if not n:
                problems.append(f"{rid}: line without @n: {text[:40]!r}")
            elif not n.isdigit():
                problems.append(f"{rid}: non-numeric line number {n!r}")
            if n in seen_n:
                problems.append(f"{rid}: duplicate line number {n}")
            seen_n.add(n)
            if not text:
                problems.append(f"{rid} l.{n}: empty line after rendering")
            lines.append(rec_l)
        for x in p.findall(f"{TEI}note"):
            notes.append(re.sub(r"\s+", " ", "".join(x.itertext())).strip())
        if not lines:
            problems.append(f"{rid}: poem div with no <l>")
        recs.append({"id": rid, "source_file": name, "urn": urn, "book": book, "poem": num,
                     "language": info["language"], "kind": info["kind"], "edition": edition,
                     "metre_milestone": metre, "head": head, "lines": lines, "notes": notes, "line_count": len(lines)})
    return recs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetched = fetch_records()
    manifest = {"name": "Horace, Odes, Carmen Saeculare, Epodes: Perseus Digital Library TEI (PerseusDL/canonical-latinLit) "
                        "with John Conington's public-domain verse translation of the Odes",
                "date": time.strftime("%Y-%m-%d"), "user_agent": "Melos/1.0 (+https://greeklyric.com)",
                "repo": "https://github.com/PerseusDL/canonical-latinLit",
                "licence": {"name": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/",
                            "quote": "", "quote_source": "",
                            "repo_license_md_sha256": sha(RAW / "license.md") if (RAW / "license.md").exists() else ""},
                "files": {}, "counts": {}, "alignment": {}, "problems": []}
    problems: list[str] = manifest["problems"]
    keys: dict[str, set[tuple[str, str]]] = {}
    n_records = 0
    n_no_metre = 0
    header_licence_seen = False
    with open(OUT / "poems.jsonl", "w", encoding="utf-8") as out:
        for name, info in FILES.items():
            path = RAW / name
            tree = etree.parse(str(path))
            h = header(tree)
            if h.get("licence"):
                header_licence_seen = True
                if info["language"] == "la" and not manifest["licence"]["quote"]:
                    manifest["licence"]["quote"] = h["licence"]
                    manifest["licence"]["quote_source"] = f"{name} <availability><licence>"
            urn = tree.xpath("string(//t:div[@type='edition' or @type='translation']/@n)", namespaces=NS) \
                or f"urn:cts:latinLit:{name.replace('.xml', '')}"
            edition = edition_label(h)
            recs = poem_records(tree, name, info, urn, edition, problems)
            n_lines = 0
            for rec in recs:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_lines += rec["line_count"]
                n_no_metre += not rec["metre_milestone"]
            n_records += len(recs)
            keys[name] = {(r["book"], r["poem"]) for r in recs}
            fr = fetched.get(name, {})
            manifest["files"][name] = {"url": fr.get("url", ""), "sha256": sha(path), "bytes": path.stat().st_size,
                                       "fetched_at": fr.get("fetched_at", ""), "fetch_log_sha256": fr.get("sha256", ""),
                                       "header": h, "urn": urn, "edition": edition, "poems": len(recs), "lines": n_lines,
                                       "books": sorted({r["book"] for r in recs if r["book"]}, key=int), **info}
            print(name, len(recs), "poems", n_lines, "lines", edition, file=sys.stderr)
    if not manifest["licence"]["quote"]:
        manifest["licence"]["quote"] = licence_from_repo(RAW / "license.md") if (RAW / "license.md").exists() else ""
        manifest["licence"]["quote_source"] = ("data/raw/latin/perseus/license.md (repo licence file); none of the four TEI "
                                               "headers has an <availability><licence> element")
    la, en = keys["phi0893.phi001.perseus-lat2.xml"], keys["phi0893.phi001.perseus-eng2.xml"]
    sort_key = lambda k: (int(k[0] or 0), int(k[1]) if k[1].isdigit() else 0)
    manifest["alignment"] = {
        "odes_latin_poems": len(la), "odes_conington_poems": len(en), "shared": len(la & en),
        "latin_only": [".".join(k) for k in sorted(la - en, key=sort_key)],
        "conington_only": [".".join(k) for k in sorted(en - la, key=sort_key)],
        "conington_has_carmen_saeculare_div": any(not b for b, _ in en),
    }
    manifest["counts"] = {"records": n_records, "poems_without_metre_milestone": n_no_metre,
                          "problems": len(problems)}
    manifest["files"]["poems.jsonl"] = {"sha256": sha(OUT / "poems.jsonl"), "bytes": (OUT / "poems.jsonl").stat().st_size}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for pr in problems:
        print("PROBLEM", pr, file=sys.stderr)
    print("alignment", json.dumps(manifest["alignment"]), file=sys.stderr)
    print("licence quote:", manifest["licence"]["quote"], "|", manifest["licence"]["quote_source"], file=sys.stderr)


if __name__ == "__main__":
    main()
