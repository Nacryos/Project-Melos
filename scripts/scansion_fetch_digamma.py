"""Extract Monro's lists of Homeric words with a lost initial digamma (ϝ) into a JSON table.

Source: D. B. Monro, *A Grammar of the Homeric Dialect* (2nd ed., Oxford 1891; public domain),
§§ 390-395, in the Dickinson College Commentaries online edition (ed. Meagan Ayer, 2014,
ISBN 978-1-947822-04-7), licensed CC BY-SA (https://dcc.dickinson.edu/terms-use).

The pages are downloaded (generic User-Agent, no personal data) to data/raw/scansion/monro/ and
parsed; nothing in the output is typed by hand. Headwords are the short paragraphs that open each
entry in §§ 390-392 (a comma-separated list of single words, optional parenthesised forms,
optional "etc."); the δϝ (§ 394) and ϝρ (§ 395) groups are printed in running prose and are read
from the sentence that introduces them. Two letters typed as Latin in the online transcription
(ἄστu, ἰάxω) are read as the Greek letters they stand for (u → υ, x → χ); this is recorded per row.

    python scripts/scansion_fetch_digamma.py [--offline]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(__import__("os").environ.get("MELOS_DATA_DIR", ROOT / "data")) / "raw" / "scansion" / "monro"
OUT = ROOT / "backend" / "scansion" / "data" / "digamma_monro.json"
UA = "Melos/1.0 (+https://greeklyric.com)"
BASE = "https://dcc.dickinson.edu/grammar/monro/"
PAGES = {
    # file name: (url slug, section, evidence kind)
    "words-initial-w.html": ("words-initial-%CF%9D", "§390 Words with initial ϝ-", "headword_paragraphs"),
    "words-initial-sw.html": ("words-initial-%CF%83%CF%9D", "§391 Words with initial σϝ-", "headword_paragraphs"),
    "meter-only.html": ("%CF%9D-inferred-meter-only", "§392 ϝ inferred from meter only", "headword_paragraphs"),
    "words-initial-dw.html": ("words-initial-%CE%B4%CF%9D", "§394 Words with initial δϝ", "prose_dw"),
    "words-initial-w-rho.html": ("words-initial-%CF%9D%CF%81-etc", "§395 Initial ϝρ", "prose_wr"),
}
GREEK = r"[Ͱ-Ͽἀ-῿ux̀-ͯ]+"
WORD = rf"{GREEK}\.?"
ITEM = rf"{WORD}(?:\s*\([^)]*\))?"
HEADWORD_PARA = re.compile(rf"^{ITEM}(?:\s*,\s*{ITEM})*(?:\s*,?\s*etc\.)?\.?$")
LATIN_FOR_GREEK = {"u": "υ", "x": "χ"}
# Monro § 391 names the possessive ὅς among σϝ- words; its spelling is identical to the relative
# pronoun (which never had ϝ), so a spelling match cannot tell them apart: listed, not matched.
UNMATCHABLE = {"ὅς": "homograph of the relative pronoun ὅς, which had no ϝ; a spelling cannot tell them apart"}


def fetch(offline: bool) -> dict[str, bytes]:
    RAW.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (slug, _, _) in PAGES.items():
        path = RAW / name
        if not offline:
            req = urllib.request.Request(BASE + slug, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status != 200:
                    sys.exit(f"DOWNLOAD FAILED {BASE + slug}: HTTP {resp.status}")
                path.write_bytes(resp.read())
        if not path.exists():
            sys.exit(f"missing raw page {path}")
        out[name] = path.read_bytes()
    return out


def body_text(raw: bytes) -> tuple[list[str], str]:
    s = raw.decode("utf-8")
    s = s[s.find("<article"):]
    s = s[: s.find("Suggested Citation")]
    paras = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", s, re.S)]
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))
    return paras, text


def greekify(word: str) -> tuple[str, str | None]:
    fixed = "".join(LATIN_FOR_GREEK.get(ch, ch) for ch in word)
    return fixed, (f"Latin letter(s) in the online transcription read as Greek: {word} → {fixed}" if fixed != word else None)


def words_in(fragment: str) -> list[str]:
    fragment = re.sub(GREEK + r"-", " ", fragment)  # stems printed as prefixes (ῥυ-) are not words
    fragment = re.sub(r"\([^)]*\)", lambda m: " " + m.group(0)[1:-1] + " ", fragment)
    return [w.rstrip(".") for w in re.findall(GREEK + r"\.?", fragment) if w.rstrip(".") not in ("etc",)]


def rows_for(name: str, raw: bytes) -> list[dict]:
    slug, section, kind = PAGES[name]
    paras, text = body_text(raw)
    url = BASE + slug
    rows = []

    def add(word: str, quote: str, effect: str):
        greek, note = greekify(word)
        if not re.search(r"[Ͱ-Ͽἀ-῿]", word):  # a lone Latin letter is not a word
            return
        row = {"word": greek, "section": section, "source_url": url, "quote": quote, "effect": effect}
        if note:
            row["transcription_note"] = note
        if greek in UNMATCHABLE:
            row["match"] = False
            row["match_note"] = UNMATCHABLE[greek]
        rows.append(row)

    if kind == "headword_paragraphs":
        for p in paras:
            if 0 < len(p) < 60 and HEADWORD_PARA.match(p):
                for w in words_in(p):
                    add(w, p, "initial ϝ (hiatus before it / lengthening of a preceding short syllable)")
    elif kind == "prose_dw":
        m = re.search(r"δϝει- \(δϝι-\)(.*?)A short vowel is frequently lengthened", text)
        if not m:
            sys.exit("§394 sentence not found")
        for w in words_in(m.group(1)):
            add(w, "δϝει- (δϝι-)" + m.group(1).strip(), "initial δϝ: a preceding short vowel is frequently lengthened")
        m = re.search(r"(δὴν, δηρόν, δηθά)", text)
        if m:
            for w in words_in(m.group(1)):
                add(w, m.group(1), "initial δϝ: a preceding short vowel is frequently lengthened")
    elif kind == "prose_wr":
        m = re.search(r"double consonant in (.*?) But lengthening is optional in (.*?), thus", text)
        if not m:
            sys.exit("§395 sentence not found")
        always, optional = m.group(1), m.group(2)
        always = re.sub(r"\[fn\].*?\[/fn\]", "", always)
        for w in words_in(always):
            if not w.endswith("-"):
                add(w, m.group(0)[:300], "initial ϝρ: always lengthens a preceding short syllable")
        for w in words_in(optional):
            add(w, m.group(0)[:300], "initial ϝρ: lengthening of a preceding short syllable optional")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="parse the saved pages without downloading")
    args = ap.parse_args()
    pages = fetch(args.offline)
    rows, seen = [], set()
    for name, raw in pages.items():
        for row in rows_for(name, raw):
            if (row["word"], row["section"]) not in seen:
                seen.add((row["word"], row["section"]))
                rows.append(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "source": "D. B. Monro, A Grammar of the Homeric Dialect (2nd ed., Oxford 1891), §§390-395",
        "edition": "Dickinson College Commentaries, ed. Meagan Ayer (2014), ISBN 978-1-947822-04-7",
        "license": "CC BY-SA (Dickinson College Commentaries terms of use); Monro 1891 is public domain",
        "raw_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in pages.items()},
        "extraction": "scripts/scansion_fetch_digamma.py",
        "rows": rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
