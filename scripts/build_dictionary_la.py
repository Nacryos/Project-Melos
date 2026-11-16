#!/usr/bin/env python3
"""Build the Lewis & Short store data/lexica/lewis_short_la.sqlite from the Perseus TEI (docs/latin/dictionary.md).

Per entry: headword as printed, folded key (backend.latin_text.normalize_la: no macrons, v -> u, j -> i), part of
speech / gender / inflection, the whole entry as plain text, its senses (level, number, English glosses, quote
translations), every tagged citation (author abbreviation, work, locus, CTS URN, sense) and the usage labels found in
the entry's opening (ante-class., class., poet., post-Aug., post-class., late Lat., eccl. Lat., rare ...). An FTS5
table indexes headwords and sense glosses for the English -> Latin lookup. Also writes the author table
data/open/latin/lewis-short/authors.json from L&S's own list of authors (Wikisource transcription, kept beside the
XML) and a manifest with the source, licence, sha256 and counts.

    .venv/bin/python scripts/build_dictionary_la.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.latin_text import normalize_la  # noqa: E402

XML = ROOT / "data/raw/latin/lewis-short/lat.ls.perseus-eng2.xml"
ABBREVIATIONS = ROOT / "data/raw/latin/lewis-short/abbreviations.wikisource.txt"
OUT = ROOT / "data/lexica/lewis_short_la.sqlite"
OPEN = ROOT / "data/open/latin/lewis-short"
ABBREVIATIONS_URL = "https://en.wikisource.org/wiki/A_Latin_Dictionary#ABBREVIATIONS"
AUGUSTUS_DIED = 14          # "an author before A.D. 14"
OBIIT_MARGIN = 20           # an author dead by A.D. 34 wrote under Augustus (Livy and Ovid died in A.D. 17)

# Usage labels, searched in order in an entry's (or a sense's) opening; each match is cut out before the next search
# so that "ante- and post-class." gives both period labels and never a bare "class.".
LABELS: list[tuple[tuple[str, ...], re.Pattern]] = [
    (("ante-class.", "post-class."), re.compile(r"ante\s*-?\s*(?:and|et)\s*post\s*-?\s*class", re.I)),
    (("ante-class.",), re.compile(r"ante\s*-?\s*class", re.I)),
    (("post-class.",), re.compile(r"post\s*-?\s*class", re.I)),
    (("post-Aug.",), re.compile(r"post\s*-?\s*Aug|not ante-Aug", re.I)),
    (("late Lat.",), re.compile(r"\b(?:late|later|latest)\s+Lat", re.I)),
    (("eccl. Lat.",), re.compile(r"\beccl\.", re.I)),
    (("jurid. Lat.",), re.compile(r"\bjurid\.", re.I)),
    (("poet.",), re.compile(r"\bpoet\.", re.I)),
    (("very rare",), re.compile(r"\bvery rare\b", re.I)),
    (("rare",), re.compile(r"\brare\b(?!ly)", re.I)),
    (("class.",), re.compile(r"(?<![a-z-])class\.", re.I)),
]
# Italics that are grammar, not a gloss ("part.", "abl. sing.", "fin.").
GRAMMAR = frozenset("""a abl absol abstr acc act adj adv al c collat comp concr conj constr dat dep dim f fem fin form
fut gen gerund h i ib id imper imperf impers in inch ind indecl inf init interj intr l m masc med n neutr nom num
object om ord p part pass perf plur pos praep prep pres pron prop q rel s sc sing subj subst sup trans v voc fig lit
trop transf meton esp partic""".split())
# Sources L&S's list leaves undated, dated here from the works themselves, and two corrections of the list.
EDITOR = {
    "Vulg.": ("Biblia Vulgatae Editionis", "fl", 405, "Jerome's revision; L&S gives no single date"),
    "Lampr.": ("Aelius Lampridius", "fl", 300, "list prints 'ob. B.C. 300'; Lampridius is a writer of the Historia Augusta, A.D."),
    "Ampel.": ("L. Ampelius", "fl", 200, "list prints 'fl. (?) 200' without era"),
    "Prisc.": ("Priscianus", "fl", 500, "list prints 'fl. B.C. 500'; Priscian taught at Constantinople about A.D. 500"),
    "Cod. Just.": ("Codex Justinianeus", "fl", 534, "promulgation"),
    "Cod. Theod.": ("Codex Theodosianus", "fl", 438, "promulgation"),
    "Dig.": ("Digesta", "fl", 533, "promulgation"),
    "Inst.": ("Institutiones (Justinian)", "fl", 533, "promulgation"),
    "Dion. Cato": ("Dionysius Cato", "fl", 300, "L&S: 'probably of the third or fourth century'"),
    "Not. Tir.": ("Notae Tironianae", "fl", 400, "L&S: 'a late collection'"),
    "Eccl.": ("Scriptores Ecclesiastici", "fl", 300, "Christian writers as a class"),
}
# Spellings of an author in the XML that differ from the list.
# "August." and "Pomp." go by L&S's practice, not by the list: the list has August. = Augustus and Pomp. = L. Pomponius
# (comic, B.C. 90), but the citations under them are Augustine (Conf., C. D., Serm.) and mostly Pompeius's commentary
# on Donatus; both are sent to rows after A.D. 14, so that neither can vouch for a word as early.
ALIASES = {"August.": "Aug.", "Pomp.": "Pompon.", "Suet": "Suet.", "Germ.": "German.", "Caes. Germ.": "German.", "Caes. German.": "German.", "Her.": "Auct. Her.",
           "Auct. Priap.": "Priap.", "Anthol. Lat.": "Antho. Lat.", "Val. Cat.": "Val. Cato."}
SEE = {"Auct. Her.": "Cornif.", "Auct. ad Her.": "Cornif."}      # the list's "see Cornificius" (printed "Cornificus")
_BOLD = re.compile(r"'''(.+?)'''")
_DATE = re.compile(r"(obiit|ob|flor|for|fl|about|circa)\b[.,]?\s*(?:about\s*)?(?:fl\.?\s*)?(\(\?\))?\s*(B\.\s*C\.|A\.\s*D\.)\s*(\d+)", re.I)


def before_augustus_died(kind: str, year: int | None) -> bool | None:
    if year is None:
        return None
    return year <= AUGUSTUS_DIED + OBIIT_MARGIN if kind == "ob" else year <= AUGUSTUS_DIED


def build_authors(wikitext: str) -> dict:
    """L&S abbreviation -> [{name, description, kind (ob/fl), year (B.C. negative), doubtful, before_ad14}]; an
    abbreviation two authors share (Plin., Sen.) keeps both."""
    table: dict[str, list[dict]] = {}
    see: dict[str, str] = {}
    for line in wikitext.splitlines():
        if not line.startswith("*'''"):
            continue
        body = line[1:]
        head = re.match(r"((?:'''.+?'''[,.]?\s*(?:or\s+)?)+)(.*)", body)
        if not head:
            continue
        abbrs = [a.strip().rstrip(",") for a in _BOLD.findall(head.group(1))]
        rest = head.group(2).strip()
        m_see = re.match(r"See\s+(?:''')?([^'.]+\.?(?:\s[^'.]+\.)?)", rest, re.I) or re.search(r"\bsee\s+'''(.+?)'''", rest)
        date = _DATE.search(rest)
        desc = re.search(r"(?<!')''([^']+?)''(?!')", rest)
        name = re.split(r",?\s*''|\s+(?:obiit|ob\.|flor\.|fl\.?|about)\s", _BOLD.sub(r"\1", rest), maxsplit=1)[0].strip(" ,.")
        if date:
            year = int(date.group(4)) * (-1 if date.group(3).upper().startswith("B") else 1)
            kind = "ob" if date.group(1).lower().startswith("ob") else "fl"
            row = {"name": name, "description": (desc.group(1).strip(" ,.") if desc else ""), "kind": kind, "year": year,
                   "doubtful": "(?)" in rest, "before_ad14": before_augustus_died(kind, year), "source": "L&S list"}
        elif m_see and not date:
            for a in abbrs:
                see[a] = m_see.group(1).strip().rstrip(",")
            continue
        else:
            row = {"name": name[:120], "description": "", "kind": "", "year": None, "doubtful": False, "before_ad14": None,
                   "source": "L&S list (undated)"}
        for a in abbrs:
            table.setdefault(a, []).append(dict(row))
    for a, (name, kind, year, why) in EDITOR.items():
        table[a] = [{"name": name, "description": "", "kind": kind, "year": year, "doubtful": False,
                     "before_ad14": before_augustus_died(kind, year), "source": "editor: " + why}]
    full_names = {normalize_la(rows[0]["name"]): a for a, rows in table.items()}
    for a, target in {**see, **SEE}.items():
        t = SEE.get(a) or (target if target in table else ALIASES.get(target) or next(
            (k for n, k in full_names.items() if normalize_la(target).rstrip(".") in n), None))
        if a not in table and t in table:
            table[a] = [dict(r, source=r["source"] + f" (see {t})") for r in table[t]]
    return dict(sorted(table.items()))


def author_key(abbr: str) -> str:
    return re.sub(r"[^a-z]", "", normalize_la(abbr))


def resolve_author(abbr: str, table: dict, index: dict) -> str | None:
    """The table's abbreviation for an author string of the XML, or None (modern scholars, stray tags)."""
    a = ALIASES.get(abbr.strip(), abbr.strip())
    if a in table:
        return a
    k = author_key(a)
    if k in index:
        return index[k]
    if k.startswith("inscr"):
        return "Inscr."
    if k.startswith("gloss"):
        return "Gloss."
    return None


def labels_in(text: str) -> list[str]:
    found: list[str] = []
    for names, rx in LABELS:
        if rx.search(text):
            found.extend(n for n in names if n not in found)
            text = rx.sub(" ", text)
    return found


def is_gloss(text: str) -> bool:
    t = text.strip(" .,;:()[]")
    if not t or len(t) > 120 or not re.search(r"[A-Za-z]{2}", t):
        return False
    return not all(w.strip(".,") in GRAMMAR for w in t.lower().split())


def events(el):
    yield "start", el
    if el.text:
        yield "text", el.text
    for child in el:
        yield from events(child)
        if child.tail:
            yield "text", child.tail
    yield "end", el


def squeeze(text: str) -> str:
    return re.sub(r"\s+([,;:.)])", r"\1", re.sub(r"\s+", " ", text)).strip()


def parse_entry(entry: ET.Element) -> dict:
    """One <entryFree> -> headword, grammar line, plain text, senses, citations, labels."""
    text: list[str] = []
    length = 0
    orths: list[str] = []
    grammar: dict[str, str] = {}
    senses: list[dict] = []
    cites: list[dict] = []
    sense: dict | None = None
    stack: list[str] = []
    buf: dict[str, list[str]] = {}
    last_author = ""
    quote = ""
    gloss_at = bibl_at = None
    bibl_before_gloss = False
    head_end = None
    bibl: dict | None = None
    for kind, el in events(entry):
        if kind == "text":
            if not isinstance(el, str):
                continue
            text.append(el)
            length += len(el)
            if sense is not None:
                sense["parts"].append(el)
            for tag in ("orth", "itype", "gen", "pos", "author", "bibl", "quote", "tr", "hi"):
                if tag in buf:
                    buf[tag].append(el)
            continue
        tag = el.tag
        if kind == "start":
            stack.append(tag)
            if tag == "sense":
                if head_end is None:
                    head_end = length
                sense = {"level": int(el.get("level") or 0), "n": el.get("n") or "", "parts": [], "glosses": [], "trans": [],
                         "first_bibl": None, "start": length}
                senses.append(sense)
            elif tag == "bibl":
                bibl = {"urn": el.get("n") or "", "author": ""}
                buf["bibl"] = []
                if gloss_at is None:
                    bibl_before_gloss = True
                elif bibl_at is None:
                    bibl_at = length
                if sense is not None and sense["first_bibl"] is None:
                    sense["first_bibl"] = length - sense["start"]
            elif tag == "cit":
                quote = ""
            elif tag in ("orth", "itype", "gen", "pos", "author", "quote", "tr") or (tag == "hi" and el.get("rend") == "ital"):
                buf[tag] = []
            continue
        stack.pop()
        if tag == "orth":
            orths.append(squeeze("".join(buf.pop("orth", []))))
        elif tag in ("itype", "gen", "pos"):
            value = squeeze("".join(buf.pop(tag, [])))
            if head_end is None or not senses or len(senses) == 1 and not grammar.get(tag):
                grammar.setdefault(tag, value)
        elif tag == "author":
            name = squeeze("".join(buf.pop("author", [])))
            if bibl is not None:
                bibl["author"] = name
        elif tag == "quote":
            quote = squeeze("".join(buf.pop("quote", [])))
        elif tag == "cit":
            quote = ""
        elif tag == "tr":
            t = squeeze("".join(buf.pop("tr", []))).strip(" ,;.")
            if t and sense is not None:
                sense["trans"].append(t)
        elif tag == "hi" and "hi" in buf:
            t = squeeze("".join(buf.pop("hi")))
            if is_gloss(t) and "bibl" not in stack and "quote" not in stack:
                if sense is not None:
                    sense["glosses"].append(t.strip(" ,;."))
                if gloss_at is None:
                    gloss_at = length
        elif tag == "bibl" and bibl is not None:
            raw = squeeze("".join(buf.pop("bibl", [])))
            name = bibl["author"]
            ref = raw[len(name):].strip() if name and raw.startswith(name) else raw
            if name in ("id.", "ib.", "Id.", "Ib.", "") and last_author:
                if name.lower() == "ib." and not re.match(r"[A-Z]", ref):
                    ref = ref  # same work as the last citation; the locus alone is printed
                name = last_author
            elif name:
                last_author = name
            ref = re.sub(r"^ib\.\s*", "", ref)
            m = re.match(r"((?:[A-Za-z][A-Za-z.]*\.?\s+)*)(.*)", ref)
            cites.append({"author": name, "work": (m.group(1).strip() if m else ""), "locus": (m.group(2).strip(" ;,") if m else ref),
                          "urn": bibl["urn"], "quote": quote[:300], "sense": len(senses) - 1 if sense is not None else -1})
            bibl = None
    plain = squeeze("".join(text))
    joined = "".join(text)
    if gloss_at is None:
        opening = joined[:300]
    else:
        end = min(bibl_at if bibl_at is not None else gloss_at + 300, gloss_at + 300)
        opening = joined[(gloss_at if bibl_before_gloss else 0):end]
    for s in senses:
        body = "".join(s.pop("parts"))
        cut = s.pop("first_bibl")
        s.pop("start")
        s["labels"] = labels_in(body[:min(cut if cut is not None else 200, 200)])
        s["text"] = squeeze(body)
    head = squeeze(joined[:head_end if head_end is not None else 300])[:300]
    return {"orths": [o for o in orths if o], "grammar": grammar, "text": plain, "head": head, "senses": senses,
            "cites": cites, "labels": labels_in(opening)}


INTERLINEAR = ROOT / "data/open/latin/interlinear-catullus/catullus-interlinear.jsonl"


def g2(k: int, n_en: int, n_la: int, n: int) -> float:
    """Dunning's log-likelihood for an English stem and a Latin lemma standing in the same line (lines are the events)."""
    cells = ((k, n_en * n_la / n), (n_en - k, n_en * (n - n_la) / n), (n_la - k, (n - n_en) * n_la / n),
             (n - n_en - n_la + k, (n - n_en) * (n - n_la) / n))
    return 2 * sum(o * math.log(o / e) for o, e in cells if o > 0 and e > 0)


def build_interlinear(db: sqlite3.Connection, path: Path = INTERLINEAR) -> int:
    """English stem <-> Latin lemma association over the audited literal English of Catullus, one line at a time.
    Kept: pairs seen in two lines or more with G2 >= 6.63 and more often than chance, and one-line pairs whose
    English word stands in two lines at most and whose lemma in five at most. Each row keeps its loci, its first line as the example, and the rank of the English word among the
    lemma's own (1 = its strongest), which is what tells `puella` under "girl" from `puella` under "sparrow"."""
    from backend import latin_lemma
    from backend.latin_dictionary import ENCLITICS, english_stems
    from backend.latin_text import tokenize_la
    if not path.exists() or not latin_lemma.available():
        return 0
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    en: Counter = Counter()
    la: Counter = Counter()
    both: dict[tuple[str, str], list[int]] = {}
    for i, row in enumerate(lines):
        stems = set(english_stems(row.get("english", "")))
        lemmas = set()
        for w in tokenize_la(row.get("latin", "")):
            reads = latin_lemma.readings(w) or next((latin_lemma.readings(w[:-len(e)]) for e in ENCLITICS
                                                     if len(w) > len(e) + 2 and w.lower().endswith(e)), [])
            if reads:
                lemmas.add(normalize_la(reads[0]["lemma"]))
        en.update(stems)
        la.update(lemmas)
        for st in stems:
            for lem in lemmas:
                both.setdefault((st, lem), []).append(i)
    n, rows = len(lines), []
    for (st, lem), where in both.items():
        k = len(where)
        score = g2(k, en[st], la[lem], n)
        if k * n <= en[st] * la[lem] or score < 6.63 or (k == 1 and (en[st] > 2 or la[lem] > 5)):
            continue
        first = lines[where[0]]
        loci = "; ".join(f"{lines[j]['poem']}.{lines[j]['n']}" for j in where[:8])
        rows.append([st, lem, k, en[st], la[lem], round(score, 2), 0, loci, first["poem"], first["n"], first["latin"], first["english"]])
    seen: Counter = Counter()
    for row in sorted(rows, key=lambda r: -r[5]):      # rank 1: the English word this lemma goes with most strongly
        seen[row[1]] += 1
        row[6] = seen[row[1]]
    db.executemany("INSERT INTO interlinear VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE INDEX interlinear_stem ON interlinear(stem)")
    return len(rows)


SCHEMA = """
CREATE TABLE entries (id INTEGER PRIMARY KEY, xml_id TEXT, key TEXT, headword TEXT, folded TEXT, type TEXT, pos TEXT,
  gender TEXT, itype TEXT, head TEXT, labels TEXT, authors TEXT, n_citations INTEGER, text TEXT);
CREATE TABLE senses (id INTEGER PRIMARY KEY, entry_id INTEGER, ord INTEGER, level INTEGER, n TEXT, labels TEXT,
  glosses TEXT, trans TEXT, text TEXT);
CREATE TABLE citations (entry_id INTEGER, sense_id INTEGER, author TEXT, work TEXT, locus TEXT, urn TEXT, quote TEXT);
CREATE TABLE forms (folded TEXT, entry_id INTEGER, main INTEGER);
CREATE TABLE authors (abbr TEXT, name TEXT, kind TEXT, year INTEGER, doubtful INTEGER, before_ad14 INTEGER, source TEXT);
CREATE TABLE interlinear (stem TEXT, lemma TEXT, k INTEGER, n_en INTEGER, n_la INTEGER, g2 REAL, rank INTEGER, loci TEXT, poem TEXT,
  line TEXT, latin TEXT, english TEXT);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE sense_fts USING fts5(headword, glosses, trans, tokenize='porter unicode61 remove_diacritics 2');
"""


def fold_headword(orth: str) -> str:
    return re.sub(r"[^a-z]", "", normalize_la(orth))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xml", type=Path, default=XML)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many entries (tests)")
    ap.add_argument("--no-open", action="store_true", help="do not rewrite authors.json and manifest.json")
    args = ap.parse_args()
    t0 = time.time()
    authors_file = OPEN / "authors.json"
    if ABBREVIATIONS.exists():
        table = build_authors(ABBREVIATIONS.read_text(encoding="utf-8"))
    else:
        table = json.loads(authors_file.read_text(encoding="utf-8"))["authors"]
    index = {author_key(a): a for a in table}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    counts: Counter = Counter()
    cited: Counter = Counter()
    unresolved: Counter = Counter()
    labels: Counter = Counter()
    sense_id = 0
    for _, el in ET.iterparse(args.xml, events=("end",)):
        if el.tag != "entryFree":
            continue
        e = parse_entry(el)
        if not e["orths"]:
            el.clear()
            continue
        counts["entries"] += 1
        eid = counts["entries"]
        by_author: Counter = Counter()
        rows = []
        for c in e["cites"]:
            a = resolve_author(c["author"], table, index)
            if a is None:
                unresolved[c["author"]] += 1
                continue
            by_author[a] += 1
            rows.append((eid, sense_id + 1 + c["sense"] if c["sense"] >= 0 else None, a, c["work"], c["locus"], c["urn"], c["quote"]))
        cited.update(by_author)
        labels.update(e["labels"])
        g = e["grammar"]
        headword = e["orths"][0]
        db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (eid, el.get("id"), el.get("key"), headword, fold_headword(headword), el.get("type") or "", g.get("pos", ""),
                    g.get("gen", ""), g.get("itype", ""), e["head"], json.dumps(e["labels"]), json.dumps(dict(by_author.most_common())),
                    len(rows), e["text"]))
        seen = set()
        for i, o in enumerate(e["orths"]):
            f = fold_headword(o)
            if f and f not in seen:
                seen.add(f)
                db.execute("INSERT INTO forms VALUES (?,?,?)", (f, eid, int(i == 0)))
        for ord_, s in enumerate(e["senses"]):
            sense_id += 1
            glosses, trans = "; ".join(s["glosses"]), "; ".join(s["trans"])
            db.execute("INSERT INTO senses VALUES (?,?,?,?,?,?,?,?,?)",
                       (sense_id, eid, ord_, s["level"], s["n"], json.dumps(s["labels"]), glosses, trans, s["text"]))
            if glosses or trans:
                db.execute("INSERT INTO sense_fts (rowid, headword, glosses, trans) VALUES (?,?,?,?)", (sense_id, headword, glosses, trans))
        db.executemany("INSERT INTO citations VALUES (?,?,?,?,?,?,?)", rows)
        counts["senses"] += len(e["senses"])
        counts["citations"] += len(rows)
        el.clear()
        if args.limit and counts["entries"] >= args.limit:
            break
    for a, rows in table.items():
        for r in rows:
            db.execute("INSERT INTO authors VALUES (?,?,?,?,?,?,?)", (a, r["name"], r["kind"], r["year"], int(r["doubtful"]),
                                                                    None if r["before_ad14"] is None else int(r["before_ad14"]), r["source"]))
    db.executescript("CREATE INDEX entries_folded ON entries(folded); CREATE INDEX forms_folded ON forms(folded);"
                     "CREATE INDEX senses_entry ON senses(entry_id); CREATE INDEX citations_entry ON citations(entry_id);"
                     "CREATE INDEX citations_author ON citations(author);")
    try:
        counts["interlinear_pairs"] = build_interlinear(db)
    except Exception as exc:  # noqa: BLE001 - the association table is an extra; the dictionary stands without it
        print(f"interlinear association skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
    sha = hashlib.sha256(args.xml.read_bytes()).hexdigest()
    build = {"source": args.xml.name, "sha256": sha, **counts, "authors": len(table),
             "built": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    db.execute("INSERT INTO metadata VALUES ('build', ?)", (json.dumps(build),))
    db.commit()
    db.execute("INSERT INTO sense_fts(sense_fts) VALUES ('optimize')")
    db.commit()
    db.close()
    tmp.replace(args.out)

    if not args.no_open and not args.limit:
        OPEN.mkdir(parents=True, exist_ok=True)
        authors_file.write_text(json.dumps({
            "source": "Lewis & Short, A Latin Dictionary (Oxford 1879), 'Abbreviations used in referring to ancient authors and "
                      "their works' (dates 'on the authority of Teuffel'), as transcribed at " + ABBREVIATIONS_URL +
                      " (Wikisource text, CC BY-SA 4.0; the dictionary itself is in the public domain); fetched 2026-11-15.",
            "rule": f"before_ad14: floruit by A.D. {AUGUSTUS_DIED}, or death by A.D. {AUGUSTUS_DIED + OBIIT_MARGIN}; "
                    "undated sources (Inscr., Gloss., collections) are null and count for neither side. Years B.C. are negative.",
            "editor_rows": "rows whose source begins 'editor:' are not in L&S's list as dated; the reason follows the colon.",
            "citations": {a: cited.get(a, 0) for a in table},
            "authors": table}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        licence = ""
        m = re.search(r"<availability>\s*<p n=\"([^\"]+)\">([^<]+)</p>", args.xml.read_text(encoding="utf-8")[:20000])
        if m:
            licence = f"{m.group(2).strip()} ({m.group(1)})"
        (OPEN / "manifest.json").write_text(json.dumps({
            "store": "data/lexica/lewis_short_la.sqlite (not committed; rebuild with scripts/build_dictionary_la.py)",
            "source": "Charlton T. Lewis and Charles Short, A Latin Dictionary (Oxford: Clarendon Press, 1879); Perseus Digital "
                      "Library TEI, lat.ls.perseus-eng2.xml (the file the PerseusDL/lexica repository distributes)",
            "licence": licence, "licence_file": "data/raw/latin/lewis-short/license.md",
            "sha256": sha, "bytes": args.xml.stat().st_size,
            "counts": dict(counts), "entries_by_label": dict(labels.most_common()),
            "authors_in_table": len(table), "author_strings_unresolved": dict(unresolved.most_common(40)),
            "built": build["built"]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({**build, "seconds": round(time.time() - t0, 1), "labels": dict(labels.most_common()),
                      "unresolved": dict(unresolved.most_common(25))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
