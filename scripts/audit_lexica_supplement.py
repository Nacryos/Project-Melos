"""Independently re-check data/lexica/supplement-entries.jsonl against its raw XML.

Run:  python -I scripts/audit_lexica_supplement.py

For EVERY row: the raw file is inside data/raw, its SHA-256 equals the row's
raw_sha256; the recorded byte range parses (lxml, no DTD/network) to one entry
element of the expected tag whose own identity attribute equals entry_id; the
row's lemma equals the printed headword read here with a separate rule per
source; source, licence and provenance fields are present and consistent; and
a non-empty gloss occurs verbatim (whitespace-collapsed) in the entry's text.
Writes data/reports/audit-lexica-supplement.json; backend.server only loads
the supplement when this report says PASS for the file's current SHA-256.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from html.entities import html5 as HTML5_ENTITIES
import json
from pathlib import Path
import re
import sys
import time
import unicodedata

from betacode import beta_to_uni
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / "data" / "lexica" / "supplement-entries.jsonl"
REPORT = ROOT / "data" / "reports" / "audit-lexica-supplement.json"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED = {
    "Perseus Middle Liddell TEI (Hopper open-source texts)": ("entry", "CC-BY-SA-3.0-US"),
    "LSJ (Logeion edition, H. Dik) TEI": ("div2", "CC-BY-SA-4.0"),
    "Perseus Cunliffe TEI via Homerica": ("div", "unknown"),
    "Dodson Greek Lexicon (NT; public domain)": ("entry", "CC0-1.0"),
}
ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9_.:-]*);")
SPACE = re.compile(r"\s+")
DIGITS = re.compile(r"\d+$")


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", SPACE.sub(" ", value).strip())


def parse(fragment: bytes):
    text = fragment.decode("utf-8")
    def entity(match):
        name = match.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return match.group(0)
        value = HTML5_ENTITIES.get(name + ";")
        return "&amp;" + name + ";" if value is None else value.replace("&", "&amp;").replace("<", "&lt;")
    text = ENTITY.sub(entity, text)
    return etree.fromstring(text.encode("utf-8"), etree.XMLParser(load_dtd=False, no_network=True,
                                                                  resolve_entities=False, recover=False))


def headword(source: str, element) -> tuple[str, str]:
    """(identity attribute value, printed headword) by an explicit per-source rule."""
    if source.startswith("Perseus Middle Liddell"):
        orth = next(element.iter("orth"))
        return element.get("id"), nfc(beta_to_uni(nfc("".join(orth.itertext()))))
    if source.startswith("LSJ (Logeion"):
        return element.get("id"), nfc("".join(element.find("head").itertext()))
    if source.startswith("Perseus Cunliffe"):
        n = element.get("n") or ""
        if n == "crossref":
            head = nfc("".join(element.find("head").itertext()))
            n = DIGITS.sub("", head.rstrip(" ,.")).strip()
        return element.get(XML_ID), nfc(n)
    n = element.get("n") or ""
    lemma, _, number = n.partition("|")
    return number.strip(), nfc(lemma)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    began = time.time()
    digests: dict[str, str] = {}
    handles: dict[str, bytes] = {}
    failures, counts = [], Counter()
    raw_root = (ROOT / "data" / "raw").resolve()
    with SUPPLEMENT.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            source = row.get("source")
            counts[source] += 1
            problems = []
            expected = EXPECTED.get(source)
            if not expected:
                problems.append("unknown source label")
            elif row.get("license") != expected[1]:
                problems.append("licence label differs from the documented source licence")
            for field in ("id", "lemma", "entry_id", "source_url", "raw_path", "raw_sha256", "locator", "attribution"):
                if not row.get(field):
                    problems.append("missing " + field)
            path = (ROOT / str(row.get("raw_path") or "")).resolve()
            if not path.is_relative_to(raw_root) or not path.is_file():
                problems.append("raw path outside data/raw or missing")
            if problems:
                failures.append({"line": number, "id": row.get("id"), "problems": problems})
                continue
            key = str(path)
            if key not in digests:
                handles[key] = path.read_bytes()
                digests[key] = hashlib.sha256(handles[key]).hexdigest()
            if digests[key] != row["raw_sha256"]:
                failures.append({"line": number, "id": row["id"], "problems": ["raw SHA-256 mismatch"]})
                continue
            locator = row["locator"]
            try:
                element = parse(handles[key][locator["byte_start"]:locator["byte_end"]])
                identity, printed = headword(source, element)
            except Exception as exc:  # report every unreadable row
                failures.append({"line": number, "id": row["id"], "problems": [f"unparseable byte range: {exc}"]})
                continue
            if element.tag != expected[0]:
                problems.append(f"tag {element.tag!r} != {expected[0]!r}")
            if identity != row["entry_id"]:
                problems.append(f"identity {identity!r} != entry_id {row['entry_id']!r}")
            if printed != row["lemma"]:
                problems.append(f"headword {printed!r} != lemma {row['lemma']!r}")
            if row.get("gloss"):
                text = nfc("".join(element.itertext()))
                if source.startswith("Perseus Middle Liddell"):
                    text = nfc(beta_to_uni(text)) + " " + text
                if nfc(row["gloss"]) not in text and nfc(row["gloss"]) not in nfc(row.get("entry_text") or ""):
                    problems.append("gloss not found verbatim in the source entry")
                else:
                    counts["gloss_verified"] += 1
            if problems:
                failures.append({"line": number, "id": row["id"], "problems": problems})
            else:
                counts["rows_passed"] += 1
    with SUPPLEMENT.open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    report = {"verdict": "PASS" if not failures else "FAIL", "file": SUPPLEMENT.relative_to(ROOT).as_posix(),
              "sha256": sha, "rows_by_source": {k: v for k, v in counts.items() if k in EXPECTED},
              "rows_passed": counts["rows_passed"], "glosses_verified_verbatim": counts["gloss_verified"],
              "failures": len(failures), "failure_examples": failures[:50],
              "raw_files": {Path(k).relative_to(ROOT).as_posix(): v for k, v in digests.items()},
              "seconds": round(time.time() - began, 1), "audited_at_unix": time.time(),
              "method": __doc__.strip().splitlines()[0]}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("raw_files", "failure_examples")}, ensure_ascii=False))
    for item in failures[:10]:
        print(item)


if __name__ == "__main__":
    main()
