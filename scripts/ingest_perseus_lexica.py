"""Stage Middle Liddell and Cunliffe TEI as entries.jsonl-compatible records.

Run:  python -I scripts/ingest_perseus_lexica.py [--download] [--report]

Sources (pinned; raw files are verified by SHA-256 before parsing):
  * Middle Liddell (Liddell & Scott, Intermediate Greek-English Lexicon, 1889):
    Classics/LSJ/opensource/ml.xml inside the Perseus Hopper open-source
    "Greek and Roman collection" tarball (Last-Modified 2011-05-27), licensed
    CC BY-SA 3.0 US per https://www.perseus.tufts.edu/hopper/opensource/download .
    It is NOT in github.com/PerseusDL/lexica (that repo holds only LSJ and
    Latin lexica at 56061ca1).
  * Cunliffe, A Lexicon of the Homeric Dialect (1924), Perseus TEI edited by
    G. Crane: gregorycrane/Homerica@d71ed43c cunliffe.lexentries.unicode.xml
    (the same pinned repository commit as the production Autenrieth rows).
  * Slater, Lexicon to Pindar: no openly published TEI was located; nothing
    is ingested for it (see docs/lexica-perseus-ingestion.md).

Nothing is authored here. Sense text is the whitespace-normalized text content
of each TEI sense node; Greek Beta Code spans (Middle Liddell only) are also
rendered to Unicode with the ``betacode`` package following the Perseus Beta
Code convention (https://www.perseus.tufts.edu/hopper/help/greek). Named
character entities are resolved only through the WHATWG HTML named character
reference table (Python ``html.entities.html5``); unknown names stay literal.
Output goes to data/staging/lexica/ only; production JSONL is never touched.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html.entities import html5 as HTML5_ENTITIES
import io
import json
from pathlib import Path
import re
import tarfile
import unicodedata
from urllib.parse import quote
from urllib.request import Request, urlopen

from betacode import beta_to_uni
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "perseus-lexica"
STAGING = ROOT / "data" / "staging" / "lexica"
USER_AGENT = "melos-source-ingestion/1.0 (research corpus)"
SPACE = re.compile(r"\s+")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
HOMOGRAPH_NUMBER = re.compile(r"\d+$")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9_.:-]*);")
ML_ENTRY = re.compile(rb"<entry\b[^>]*>.*?</entry>", re.S)

HOPPER_TARBALL_URL = ("https://www.perseus.tufts.edu/hopper/opensource/downloads/"
                      "texts/hopper-texts-GreekRoman.tar.gz")
HOMERICA_COMMIT = "d71ed43cc912d3e053cbb0dd6341f798ea058378"
SOURCES = {
    "middle-liddell": {
        "label": "Perseus Middle Liddell TEI (Hopper open-source texts)",
        "raw_path": "data/raw/perseus-lexica/hopper-2011-05-27/Classics/LSJ/opensource/ml.xml",
        "raw_sha256": "cff0a7e50111bb86b282e11db5c725351cb37723900659371396fe835bcc1d7c",
        "source_url": HOPPER_TARBALL_URL + "#Classics/LSJ/opensource/ml.xml",
        "archive": {"url": HOPPER_TARBALL_URL, "last_modified": "Fri, 27 May 2011 14:52:41 GMT",
                    "bytes": 124801865, "member": "Classics/LSJ/opensource/ml.xml",
                    "path": "data/raw/perseus-lexica/hopper-2011-05-27/hopper-texts-GreekRoman.tar.gz",
                    "sha256": "b88ef05d73fabce6245ba387410e1b854abf6337925a6a594f0f8e3e35c1862c"},
        "license": "CC-BY-SA-3.0-US",
        "license_evidence": "https://www.perseus.tufts.edu/hopper/opensource/download",
        "perseus_doc": "Perseus:text:1999.04.0058",
    },
    "cunliffe": {
        "label": "Perseus Cunliffe TEI via Homerica",
        "raw_path": f"data/raw/perseus-lexica/homerica-{HOMERICA_COMMIT}/cunliffe.lexentries.unicode.xml",
        "raw_sha256": "4c4dd04000ad73a77f5d33c4440337f3d1c3758a9c436ffed71ebd22d44d4d7a",
        "git_blob_sha": "3454855639a0513d3953556962d87ad586426a07",
        "source_url": ("https://raw.githubusercontent.com/gregorycrane/Homerica/"
                       f"{HOMERICA_COMMIT}/cunliffe.lexentries.unicode.xml"),
        "repository": "gregorycrane/Homerica", "commit": HOMERICA_COMMIT,
        # The repository has no LICENSE file; same label as Autenrieth rows.
        "license": "unknown",
        "license_evidence": "https://github.com/gregorycrane/Homerica (no license file at pinned commit)",
    },
}
NOT_INGESTED = {"slater": "No openly published TEI of Slater's Lexicon to Pindar was located "
                          "(absent from PerseusDL/lexica, gregorycrane/Homerica and the Perseus "
                          "Hopper open-source tarball). Not ingested."}


# ---------------------------------------------------------------- download

def _request(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=600) as response:
        return response.read()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name: str) -> None:
    """Fetch a pinned raw file into its (new) raw directory; verify hashes."""
    cfg = SOURCES[name]
    target = ROOT / cfg["raw_path"]
    if target.exists() and sha256_file(target) == cfg["raw_sha256"]:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if name == "middle-liddell":
        archive = ROOT / cfg["archive"]["path"]
        if not archive.exists() or sha256_file(archive) != cfg["archive"]["sha256"]:
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(_request(cfg["archive"]["url"]))
        if sha256_file(archive) != cfg["archive"]["sha256"]:
            raise RuntimeError(f"Archive SHA-256 mismatch: {archive}")
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember(cfg["archive"]["member"])
            if not member.isfile():
                raise RuntimeError("Archive member is not a regular file")
            target.write_bytes(tar.extractfile(member).read())
    else:
        body = _request(cfg["source_url"])
        blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
        if blob != cfg["git_blob_sha"]:
            raise RuntimeError(f"Git blob checksum mismatch: {cfg['source_url']}")
        target.write_bytes(body)
    if sha256_file(target) != cfg["raw_sha256"]:
        raise RuntimeError(f"Raw SHA-256 mismatch: {target}")


# ---------------------------------------------------------------- helpers

def compact(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def node_text(node, render_greek: bool = False, greek: bool = False,
              skip=lambda n: False) -> str:
    """Element text in document order (comments/PIs dropped, tails kept).

    With ``render_greek`` only text inside lang="greek" elements is converted
    from Beta Code; English/Latin prose is copied unchanged.
    """
    greek = greek or node.get("lang") == "greek"
    conv = (lambda s: beta_to_uni(s)) if (render_greek and greek) else (lambda s: s)
    parts = [conv(node.text or "")]
    for child in node:
        if isinstance(child.tag, str) and not skip(child):
            parts.append(node_text(child, render_greek, greek, skip))
        parts.append(conv(child.tail or "") if render_greek and greek else (child.tail or ""))
    return "".join(parts)


def sibling_path(node, stop) -> str:
    """Relative XPath from ``stop`` using local names and sibling positions."""
    steps = []
    while node is not None and node is not stop:
        parent = node.getparent()
        same = [c for c in parent if c.tag == node.tag]
        steps.append(f"{local(node.tag)}[{same.index(node) + 1}]")
        node = parent
    return "/".join(reversed(steps))


def resolve_entities(fragment: bytes, unresolved: list[str]) -> bytes:
    text = fragment.decode("utf-8")

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return match.group(0)
        value = HTML5_ENTITIES.get(name + ";")
        if value is None:
            unresolved.append(name)
            return "&amp;" + name + ";"   # keep the literal reference visible
        return value.replace("&", "&amp;").replace("<", "&lt;")

    return ENTITY.sub(repl, text).encode("utf-8")


def base_record(cfg: dict) -> dict:
    return {"source": cfg["label"], "source_url": cfg["source_url"],
            "raw_path": cfg["raw_path"], "raw_sha256": cfg["raw_sha256"],
            "license": cfg["license"]}


# ---------------------------------------------------------------- Middle Liddell

def parse_middle_liddell(cfg: dict, entries, forms, xrefs, counters: Counter) -> None:
    body = (ROOT / cfg["raw_path"]).read_bytes()
    seen_ids: set[str] = set()
    for match in ML_ENTRY.finditer(body):
        counters["entries_seen"] += 1
        unresolved: list[str] = []
        entry = etree.fromstring(resolve_entities(match.group(0), unresolved))
        entry_id, key = entry.get("id"), entry.get("key", "")
        orth = next(entry.iter("orth"), None)
        lemma_beta = compact(node_text(orth)) if orth is not None else ""
        lemma = nfc(compact(beta_to_uni(lemma_beta))) if lemma_beta else ""
        if not entry_id or not GREEK.search(lemma):
            counters["entries_skipped_no_id_or_greek_orth"] += 1
            continue
        if lemma != nfc(compact(beta_to_uni(HOMOGRAPH_NUMBER.sub("", key)))):
            counters["orth_differs_from_key"] += 1
        anchor = f'//entry[@id="{entry_id}"]'
        senses = []
        for sense in entry.iter("sense"):
            text = compact(node_text(sense))
            senses.append({
                "sense_id": sense.get("id"), "n": sense.get("n"), "level": sense.get("level"),
                "text": text,
                "text_unicode": compact(node_text(sense, render_greek=True)),
                "locator": {"xpath": f"{anchor}/{sibling_path(sense, entry)}",
                            "byte_start": match.start(), "byte_end": match.end()}})
        translations, seen = [], set()
        for tr in entry.iter("tr"):
            value = compact(node_text(tr))
            if value and value not in seen:
                translations.append(value)
                seen.add(value)
            if len(translations) >= 4:
                break
        # Three source ids are reused by two different entries (e.g. n16257);
        # a repeat gets the entry's byte offset appended to stay unique.
        record_id = f"middle-liddell:{entry_id}"
        if entry_id in seen_ids:
            record_id += f"@{match.start()}"
            counters["duplicate_source_ids_suffixed"] += 1
        seen_ids.add(entry_id)
        record = {"id": record_id, "lemma": lemma, "lemma_beta": lemma_beta,
                  "key": key, "entry_type": entry.get("type"),
                  "gloss": "; ".join(translations),
                  "entry_text": compact(node_text(entry)),
                  "entry_text_unicode": compact(node_text(entry, render_greek=True)),
                  "entry_text_encoding": "Perseus Beta Code for Greek spans",
                  **base_record(cfg),
                  "entry_url": "https://www.perseus.tufts.edu/hopper/text?doc="
                  + quote(f"{cfg['perseus_doc']}:entry={key}", safe=""),
                  "entry_id": entry_id, "senses": senses,
                  "locator": {"xpath": anchor, "byte_start": match.start(),
                              "byte_end": match.end()}}
        if unresolved:
            record["unresolved_entities"] = sorted(set(unresolved))
            counters["entries_with_unresolved_entities"] += 1
        entries.write(json.dumps(record, ensure_ascii=False) + "\n")
        counters["entries_written"] += 1
        counters["senses_written"] += len(senses)
        counters["entries_without_marked_translation"] += not translations
        counters["entries_without_sense"] += not senses
        for ref in entry.iter("ref"):
            ref_beta = compact(node_text(ref))
            if not ref_beta:
                continue
            xrefs.write(json.dumps({
                "from_id": record["id"], "from_lemma": lemma, "ref_text": ref_beta,
                "ref_text_unicode": nfc(compact(beta_to_uni(ref_beta)))
                if ref.get("lang") == "greek" else ref_beta,
                "context": local(ref.getparent().getparent().tag) if ref.getparent().getparent() is not None else "",
                "relation": "source cross-reference (TEI xr/ref); not an inflection",
                **base_record(cfg),
                "locator": {"xpath": f"{anchor}/{sibling_path(ref, entry)}"}},
                ensure_ascii=False) + "\n")
            counters["xrefs_written"] += 1


# ---------------------------------------------------------------- Cunliffe

def parse_cunliffe(cfg: dict, entries, forms, xrefs, counters: Counter) -> None:
    tree = etree.parse(str(ROOT / cfg["raw_path"]),
                       etree.XMLParser(load_dtd=False, no_network=True,
                                       resolve_entities=False, huge_tree=True))
    body = tree.find(f"{TEI}text/{TEI}body")
    for entry in body.iterchildren(f"{TEI}div"):
        counters["entries_seen"] += 1
        entry_id, lemma = entry.get(XML_ID), nfc(compact(entry.get("n", "")))
        head = entry.find(f"{TEI}head")
        head_text = nfc(compact(node_text(head))) if head is not None else ""
        lemma_from = "div/@n"
        if entry.get("n") == "crossref" and head_text:
            # Cross-reference stubs carry n="crossref"; their headword is the
            # printed <head>, e.g. "δεδμημένος1," -> strip the trailing comma
            # and the source's homograph digit (as for LSJ keys).
            lemma = HOMOGRAPH_NUMBER.sub("", head_text.rstrip(" ,.")).strip()
            lemma_from = "head (n=crossref; trailing punctuation and homograph digit removed)"
        if not entry_id or not GREEK.search(lemma):
            counters["entries_skipped_no_id_or_n"] += 1
            SKIPPED.setdefault("cunliffe", []).append(
                {"xml_id": entry_id, "n": entry.get("n"), "head": head_text,
                 "sourceline": entry.sourceline,
                 "reason": "top-level div without a Greek headword in @n (mis-nested sub-sense?)"})
            continue
        anchor = f'//tei:div[@xml:id="{entry_id}"]'
        paragraphs = [{"text": nfc(compact(node_text(p))),
                       "locator": {"xpath": f"{anchor}/{sibling_path(p, entry)}"}}
                      for p in entry.iterchildren(f"{TEI}p")]
        senses = []
        for div in entry.iter(f"{TEI}div"):
            if div is entry:
                continue
            # A sense's own text, excluding nested sub-sense divs.
            text = nfc(compact(node_text(div, skip=lambda n: n.tag == f"{TEI}div")))
            senses.append({"sense_id": div.get(XML_ID), "n": div.get("n"),
                           "depth": sum(1 for a in div.iterancestors(f"{TEI}div")),  # 1 = under entry
                           "text": text,
                           "locator": {"xpath": f"{anchor}/{sibling_path(div, entry)}"}})
        glosses, seen = [], set()
        for gloss in entry.iter(f"{TEI}gloss"):
            value = nfc(compact(node_text(gloss)))
            if value and value not in seen:
                glosses.append(value)
                seen.add(value)
            if len(glosses) >= 4:
                break
        record = {"id": f"cunliffe:{entry_id}", "lemma": lemma, "lemma_beta": None,
                  "lemma_from": lemma_from, "headword_printed": head_text or None,
                  "paragraphs": paragraphs,
                  "gloss": "; ".join(glosses),
                  "entry_text": nfc(compact(node_text(entry))),
                  "entry_text_encoding": "Unicode (source)",
                  **base_record(cfg), "entry_url": None, "entry_id": entry_id,
                  "senses": senses, "locator": {"xpath": anchor}}
        entries.write(json.dumps(record, ensure_ascii=False) + "\n")
        counters["entries_written"] += 1
        counters["senses_written"] += len(senses)
        counters["entries_without_marked_gloss"] += not glosses
        counters["entries_without_sense_div"] += not senses
        for term in entry.iter(f"{TEI}term"):
            if term.get("type") != "orth":
                continue
            parent = term.getparent()
            before = list(term.itersiblings(f"{TEI}term", preceding=True))
            label = next((t for t in before if t.get("type") is None), None)
            cites = []
            for sib in term.itersiblings():
                if sib.tag == f"{TEI}term" and sib.get("type") == "orth":
                    break
                cites += [b.get("n") for b in sib.iter(f"{TEI}bibl") if b.get("n")]
            form = nfc(compact(node_text(term)))
            forms.write(json.dumps({
                "form": form, "lemma": lemma, "lemma_raw": lemma,
                "analysis": nfc(compact(node_text(label))) if label is not None else None,
                "analysis_format": "Cunliffe printed grammatical label (verbatim nearest "
                                   "preceding <term> in the same paragraph; may be elliptical)",
                **base_record(cfg),
                "citation": " | ".join(cites), "document_id": entry_id,
                "sentence_id": "", "token_id": "",
                "quality": "printed_lexicon_form",
                "locator": {"xpath": f"{anchor}/{sibling_path(term, entry)}",
                            "paragraph_xpath": f"{anchor}/{sibling_path(parent, entry)}"}},
                ensure_ascii=False) + "\n")
            counters["forms_written"] += 1
            counters["forms_without_label"] += label is None
            counters["forms_with_parenthetical"] += "(" in form
        for ref in entry.iter(f"{TEI}ref"):
            text = nfc(compact(node_text(ref)))
            if not text and not ref.get("target"):
                continue
            xrefs.write(json.dumps({
                "from_id": record["id"], "from_lemma": lemma, "ref_text": text,
                "target": ref.get("target"), "ref_n": ref.get("n"),
                "relation": "source cross-reference (TEI ref); not an inflection",
                **base_record(cfg),
                "locator": {"xpath": f"{anchor}/{sibling_path(ref, entry)}"}},
                ensure_ascii=False) + "\n")
            counters["xrefs_written"] += 1


SKIPPED: dict[str, list] = {}
PARSERS = {"middle-liddell": parse_middle_liddell, "cunliffe": parse_cunliffe}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    parser.add_argument("--download", action="store_true",
                        help="fetch missing raw files at the pinned versions")
    parser.add_argument("--report", action="store_true",
                        help="print counts per source and five sample entries each")
    args = parser.parse_args()
    if hasattr(__import__("sys").stdout, "reconfigure"):
        __import__("sys").stdout.reconfigure(encoding="utf-8")
    names = list(SOURCES) if args.source == "all" else [args.source]
    STAGING.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name in names:
        cfg = SOURCES[name]
        if args.download:
            download(name)
        actual = sha256_file(ROOT / cfg["raw_path"])
        if actual != cfg["raw_sha256"]:
            raise RuntimeError(f"{name}: raw SHA-256 {actual} != pinned {cfg['raw_sha256']}")
        counters: Counter = Counter()
        paths = {kind: STAGING / f"{name}.{kind}.jsonl" for kind in ("entries", "forms", "xrefs")}
        with paths["entries"].open("w", encoding="utf-8", newline="\n") as entries, \
                paths["forms"].open("w", encoding="utf-8", newline="\n") as forms, \
                paths["xrefs"].open("w", encoding="utf-8", newline="\n") as xrefs:
            PARSERS[name](cfg, entries, forms, xrefs, counters)
        for kind, path in paths.items():
            if path.stat().st_size == 0:
                path.unlink()       # no such rows in this source
        summary[name] = {"counts": dict(counters),
                         "outputs": {k: p.relative_to(ROOT).as_posix() for k, p in paths.items()
                                     if p.exists()},
                         "raw_sha256": cfg["raw_sha256"], "license": cfg["license"],
                         "skipped": SKIPPED.get(name, [])}
    manifest = STAGING / "perseus-lexica.manifest.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    previous.update({"sources": {**previous.get("sources", {}),
                                 **{n: {**{k: v for k, v in SOURCES[n].items()}, **summary[n]}
                                    for n in names}},
                     "not_ingested": NOT_INGESTED})
    manifest.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    if args.report:
        for name in names:
            print(f"== {name}: {json.dumps(summary[name]['counts'], ensure_ascii=False)}")
            with (STAGING / f"{name}.entries.jsonl").open(encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            step = max(1, len(rows) // 5)
            for row in rows[::step][:5]:
                first = row["senses"][0]["text"] if row["senses"] else "(no sense element)"
                print(f"  {row['id']}  {row['lemma']}  | gloss: {row['gloss'][:80]!r}"
                      f"  | first sense: {first[:120]!r}")
        for name, why in NOT_INGESTED.items():
            print(f"== {name}: {why}")
    else:
        print(json.dumps({n: s["counts"] for n, s in summary.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
