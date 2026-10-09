"""Build a vowel-quantity table (macron/breve marked Greek spellings) from the
Kaikki / Wiktionary Ancient Greek extraction already held in data/raw/wiktionary.

Run: PYTHONIOENCODING=utf8 python scripts/ingest_open_wiktionary_quantities.py [--skip-coverage]

Inputs  (read only): data/raw/wiktionary/kaikki.org-dictionary-AncientGreek.jsonl
                     data/campbell_glp/campbell_glp.jsonl, data/lexica/forms.jsonl (coverage only)
Outputs: data/open/wiktionary-quantities/{quantities.jsonl.gz, forms.jsonl.gz, manifest.json, coverage.json}

Every string in the outputs is a literal span of a raw Kaikki line (identified by raw_line number
and sha256 of the line bytes without the trailing newline). Nothing is guessed: a dichronon vowel
(alpha, iota, upsilon) with no U+0304 / U+0306 in the source is reported 'unmarked'. Circumflexed or
iota-subscript vowels are not interpreted either.
Streaming over the raw file; only the form-level aggregate (distinct plain spellings) is kept in memory.
"""
from __future__ import annotations

import argparse, gzip, hashlib, json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/wiktionary/kaikki.org-dictionary-AncientGreek.jsonl"
AUDIT = ROOT / "data/reports/wiktionary-audit.json"
OUT = ROOT / "data/open/wiktionary-quantities"
CAMPBELL = ROOT / "data/campbell_glp/campbell_glp.jsonl"
LEX_FORMS = ROOT / "data/lexica/forms.jsonl"

SOURCE_URL = "https://kaikki.org/dictionary/Ancient%20Greek/kaikki.org-dictionary-AncientGreek.jsonl"
INDEX_URL = "https://kaikki.org/dictionary/Ancient%20Greek/"
LICENCE_URL = "https://en.wiktionary.org/wiki/Wiktionary:Copyrights"
LICENCE_QUOTE = ("Creative Commons Attribution-ShareAlike 4.0 International License; "
                 "GNU Free Documentation License (as named on Wiktionary:Copyrights)")
ATTRIBUTION = "Wiktionary contributors, via Kaikki.org (Tatu Ylonen, wiktextract)"
DUMP_NOTE = "extracted 2026-10-03 from the enwiktionary dump dated 2026-09-02 (kaikki.org index page; Last-Modified Sat, 03 Oct 2026 10:27:59 GMT; Content-Length 403924438)"
RUN_DATE = "2026-10-09"
MACRON, BREVE = "̄", "̆"
DICHRONA = set("αιυΑΙΥ")
DIALECTS = {"Doric", "Ionic", "Epic", "Attic", "Aeolic", "Koine", "Laconian", "Boeotian", "Old-Attic", "Cretan",
            "Byzantine", "Arcadocypriot", "Thessalian", "Elean", "Lesbian", "Cypriot", "Corinthian",
            "Choral-Doric", "Locrian"}
# Orthographic diphthongs (second element without diaeresis): members are not free dichrona.
DIPH_FIRST, DIPH_SECOND = set("αεουηωΑΕΟΥΗΩ"), set("ιυΙΥ")
TOKEN_RE = re.compile(r"(?:[^\W\d_][̀-ͯ]*)+", re.U)
GREEK = re.compile(r"^[Ͱ-Ͽἀ-῿̀-ͯ]+$")


def clusters(s: str):
    """NFD clusters of s -> list of (base, combining marks string)."""
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch) and out:
            out[-1][1] += ch
        else:
            out.append([ch, ""])
    return [(b, m) for b, m in out]


def analyse(marked: str):
    """-> (plain NFC, annotation [(idx_in_plain, vowel, status)]) for dichrona; also other-mark count."""
    cl = clusters(marked)
    plain, ann, other = "", [], 0
    for i, (b, m) in enumerate(cl):
        cplain = unicodedata.normalize("NFC", b + m.replace(MACRON, "").replace(BREVE, ""))
        idx = len(plain)
        plain += cplain
        has_l, has_s = MACRON in m, BREVE in m
        if b in DICHRONA:
            prev = cl[i - 1][0] if i else ""
            diaer = "̈" in m
            in_diph = (not diaer and b in DIPH_SECOND and prev in DIPH_FIRST) or \
                      (i + 1 < len(cl) and b in DIPH_FIRST and cl[i + 1][0] in DIPH_SECOND and "̈" not in cl[i + 1][1])
            if has_l and has_s:
                st = "ambiguous"
            elif has_l:
                st = "long"
            elif has_s:
                st = "short"
            elif in_diph:
                continue
            else:
                st = "unmarked"
            ann.append([idx, unicodedata.normalize("NFC", b), st])
        elif has_l or has_s:
            other += 1
    assert plain == unicodedata.normalize("NFC", plain)
    return plain, ann, other


def has_mark(s: str) -> bool:
    d = unicodedata.normalize("NFD", s)
    return MACRON in d or BREVE in d


def greek_tokens(s: str):
    for m in TOKEN_RE.finditer(unicodedata.normalize("NFC", s)):
        t = m.group(0)
        if GREEK.match(t):
            yield t


def fold(s: str) -> str:
    d = unicodedata.normalize("NFD", s.lower())
    return unicodedata.normalize("NFC", "".join(c for c in d if not unicodedata.combining(c))).replace("ς", "σ")


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(raw_sha):
    OUT.mkdir(parents=True, exist_ok=True)
    forms = {}  # plain -> {marked: [n_entries, last_line, lemmas[], ann, rows]}
    c = Counter(); dich_rows = Counter(); dich_marked_tokens = Counter()
    with gzip.open(OUT / "quantities.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as qf, open(RAW, "rb") as f:
        for ln, raw in enumerate(f, 1):
            line = raw.rstrip(b"\r\n")
            e = json.loads(line)
            c["entries_scanned"] += 1
            lsha = hashlib.sha256(line).hexdigest()
            lemma, pos = e.get("word", ""), e.get("pos", "")
            acc = {}  # (marked, source_field, table_kind) -> dict

            def add(tok, sfield, tkind, tags, full):
                if not has_mark(tok):
                    return
                tok = unicodedata.normalize("NFC", tok)
                k = (tok, sfield, tkind)
                r = acc.get(k)
                if r is None:
                    r = acc[k] = {"tags": [], "dialects": set(), "full": set()}
                if tags and tags not in r["tags"]:
                    r["tags"].append(tags)
                r["dialects"].update(t for t in tags if t in DIALECTS)
                if full != tok:
                    r["full"].add(full)

            for t in greek_tokens(lemma):
                add(t, "canonical", "", [], lemma)
            for h in e.get("head_templates", []) or []:
                argtoks = set()
                for v in (h.get("args") or {}).values():
                    if isinstance(v, str):
                        for t in greek_tokens(v):
                            argtoks.add(unicodedata.normalize("NFC", t)); add(t, "head_template_arg", h.get("name", ""), [], v)
                for t in greek_tokens(h.get("expansion", "") or ""):
                    if unicodedata.normalize("NFC", t) not in argtoks:
                        add(t, "head_template_expansion", h.get("name", ""), [], h.get("expansion", ""))
            for fm in e.get("forms", []) or []:
                txt = fm.get("form", "")
                tags = fm.get("tags", []) or []
                if "romanization" in tags or not has_mark(txt):
                    continue
                if fm.get("source"):
                    sf, tk = "table", fm["source"]
                elif "canonical" in tags:
                    sf, tk = "canonical", ""
                else:
                    sf, tk = "other_form", ""
                for t in greek_tokens(txt):
                    add(t, sf, tk, tags, txt)
            for (tok, sf, tk), r in acc.items():
                plain, ann, other = analyse(tok)
                row = {"marked": tok, "plain": plain, "lemma": lemma, "pos": pos, "tags": r["tags"],
                       "source_field": sf, "table_kind": tk, "dialects": sorted(r["dialects"]),
                       "quantities": ann, "raw_line": ln, "raw_line_sha256": lsha}
                if r["full"]:
                    row["form_full"] = sorted(r["full"])
                qf.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                c["rows"] += 1; c["rows_" + sf] += 1; c["other_marks_on_non_dichrona"] += other
                for _, _, st in ann:
                    dich_rows[st] += 1
                d = forms.setdefault(plain, {})
                v = d.get(tok)
                if v is None:
                    v = d[tok] = [0, 0, [], ann, 0]
                v[4] += 1
                if v[1] != ln:
                    v[1] = ln; v[0] += 1
                if lemma not in v[2] and len(v[2]) < 10:
                    v[2].append(lemma)
    # form level
    nconf, dich_forms = 0, Counter()
    with gzip.open(OUT / "forms.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as ff:
        for plain in sorted(forms):
            vs = forms[plain]
            per_idx = defaultdict(set)
            for tok, v in vs.items():
                for idx, _, st in v[3]:
                    if st in ("long", "short"):
                        per_idx[idx].add(st)
            conf = sorted(i for i, s in per_idx.items() if len(s) > 1)
            if conf:
                nconf += 1
            var = [{"marked": tok, "n_entries": v[0], "n_rows": v[4], "lemmas": v[2], "quantities": v[3]}
                   for tok, v in sorted(vs.items())]
            for tok, v in vs.items():
                for _, _, st in v[3]:
                    dich_forms[st] += 1
            ff.write(json.dumps({"plain": plain, "variants": var, "conflict": bool(conf),
                                 "conflict_indices": conf}, ensure_ascii=False, separators=(",", ":")) + "\n")
    c["distinct_plain_forms"] = len(forms); c["forms_with_conflicts"] = nconf
    c["distinct_marked_spellings"] = sum(len(v) for v in forms.values())
    manifest = {
        "title": "Wiktionary vowel-quantity table (macron/breve marked Greek spellings)",
        "source_url": SOURCE_URL, "source_index_url": INDEX_URL, "dump_note": DUMP_NOTE,
        "kaikki_newer_dump_available": False,
        "kaikki_check": "2026-10-09: live index page identical size to the held copy, live jsonl Content-Length 403924438 and Last-Modified 2026-10-03 = held file; local file used.",
        "raw_path": str(RAW.relative_to(ROOT)).replace("\\", "/"), "raw_sha256": raw_sha,
        "raw_line_sha256_convention": "sha256 of the raw line bytes without trailing CR/LF",
        "licence": LICENCE_QUOTE, "licence_url": LICENCE_URL, "attribution": ATTRIBUTION,
        "licence_note": "Share-alike: derived tables must carry CC BY-SA 4.0 and the attribution.",
        "date": RUN_DATE, "script": "scripts/ingest_open_wiktionary_quantities.py",
        "counts": {
            "entries_scanned": c["entries_scanned"], "rows": c["rows"],
            "rows_by_source_field": {k[5:]: v for k, v in c.items() if k.startswith("rows_")},
            "distinct_plain_forms": c["distinct_plain_forms"],
            "distinct_marked_spellings": c["distinct_marked_spellings"],
            "forms_with_conflicts": c["forms_with_conflicts"],
            "dichrona_row_level": dict(dich_rows),
            "dichrona_distinct_marked_spelling_level": dict(dich_forms),
            "marks_on_non_dichrona_vowels_or_other_letters_rows": c["other_marks_on_non_dichrona"],
        },
        "schema": {
            "quantities.jsonl.gz": "marked, plain, lemma, pos, tags (list of tag lists from the source form object), source_field (canonical|head_template_arg|head_template_expansion|table|other_form), table_kind, dialects, quantities [[char index in plain, vowel, long|short|ambiguous|unmarked]], raw_line, raw_line_sha256, form_full (multi-word source string)",
            "forms.jsonl.gz": "plain, variants[{marked,n_entries,n_rows,lemmas (<=10),quantities}], conflict (same dichronon index both long and short across variants), conflict_indices",
            "quantity_rule": "long = U+0304 present, short = U+0306 present, ambiguous = both; vowels in orthographic diphthongs without diaeresis are not listed; circumflex/iota subscript not interpreted (stay 'unmarked').",
        },
        "files": {n: {"bytes": (OUT / n).stat().st_size, "sha256": sha_file(OUT / n)}
                  for n in ("quantities.jsonl.gz", "forms.jsonl.gz")},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def coverage():
    qforms, fold_ord = {}, defaultdict(set)  # plain -> set sourced letter ordinals; fold -> ordinals
    plain_set = set()
    with gzip.open(OUT / "forms.jsonl.gz", "rt", encoding="utf-8") as ff:
        for l in ff:
            r = json.loads(l)
            p = r["plain"]; plain_set.add(p)
            cl_idx = {}  # char index -> cluster ordinal in plain
            pos = 0
            for o, (b, m) in enumerate(clusters(p)):
                cl_idx[pos] = o; pos += len(unicodedata.normalize("NFC", b + m))
            s = set()
            for v in r["variants"]:
                for idx, _, st in v["quantities"]:
                    if st != "unmarked" and idx in cl_idx:
                        s.add(cl_idx[idx])
            qforms[p] = s
            if s:
                fold_ord[fold(p)] |= s
    # Campbell word types (lower-cased NFC keeps accents)
    qfold_all = {fold(p) for p in plain_set}
    types = Counter()
    with open(CAMPBELL, encoding="utf-8") as f:
        for l in f:
            for t in greek_tokens(json.loads(l)["text"]):
                types[unicodedata.normalize("NFC", t.lower())] += 1
    res = Counter()
    for w, n in types.items():
        cl = clusters(w)
        dpos = [o for o, (b, m) in enumerate(cl) if b in DICHRONA and not _in_diph(cl, o)]
        res["types"] += 1; res["tokens"] += n; res["dichrona_in_types"] += len(dpos); res["dichrona_in_tokens"] += len(dpos) * n
        ex = qforms.get(w)
        fo = fold_ord.get(fold(w))
        hit_ex = ex is not None
        hit_fold = fold(w) in qfold_all
        # marked-match: quantity-bearing record exists (at least one mark on a dichronon, exact spelling)
        if hit_ex:
            res["types_exact_in_table"] += 1; res["tokens_exact_in_table"] += n
        if hit_ex and ex:
            res["types_exact_with_sourced_length"] += 1
        if hit_fold:
            res["types_fold_in_table"] += 1; res["tokens_fold_in_table"] += n
        sourced_ex = sum(1 for o in dpos if ex and o in ex)
        sourced_fo = sum(1 for o in dpos if (fo and o in fo) or (ex and o in ex))
        res["dichrona_sourced_exact_types"] += sourced_ex; res["dichrona_sourced_exact_tokens"] += sourced_ex * n
        res["dichrona_sourced_fold_types"] += sourced_fo; res["dichrona_sourced_fold_tokens"] += sourced_fo * n
        if sourced_fo:
            res["types_with_any_sourced_dichronon_fold"] += 1
        if dpos:
            res["types_with_dichrona"] += 1
    # lexica forms.jsonl comparison
    lex = set(); lexfold = set()
    with open(LEX_FORMS, encoding="utf-8") as f:
        for l in f:
            i = l.find('"form": "')
            if i < 0:
                continue
            w = json.loads(l)["form"]
            w = unicodedata.normalize("NFC", w)
            lex.add(w)
    lexfold = {fold(w) for w in lex}
    qfold = {fold(p) for p in plain_set}
    lex_lower = {w.lower() for w in lex}
    res2 = {
        "lexica_forms_distinct_nfc": len(lex), "lexica_forms_distinct_fold": len(lexfold),
        "table_plain_forms": len(plain_set),
        "table_plain_forms_present_in_lexica_exact": sum(1 for p in plain_set if p in lex or p.lower() in lex_lower),
        "table_forms_fold_present_in_lexica_fold": sum(1 for p in plain_set if fold(p) in lexfold),
        "lexica_forms_with_quantity_match_exact": sum(1 for w in lex if w in plain_set or w.lower() in plain_set),
        "lexica_forms_with_quantity_match_fold": sum(1 for w in lex if fold(w) in qfold),
        "campbell_types_in_lexica_exact": sum(1 for w in types if w in lex_lower),
        "campbell_types_in_lexica_fold": sum(1 for w in types if fold(w) in lexfold),
        "campbell_types_in_table_not_in_lexica_fold": sum(1 for w in types if w in plain_set and fold(w) not in lexfold),
    }
    rep = {"date": RUN_DATE, "campbell_source": "data/campbell_glp/campbell_glp.jsonl field text",
           "method": "Greek letter runs, NFC, lower-cased; exact = spelling equals a table plain spelling; fold = accents/breathings stripped, final sigma folded; "
                     "'sourced dichronon' = a variant of the matched form carries long/short/ambiguous at that letter (diphthong members excluded); "
                     "for fold matches, letter ordinals are aligned across spellings",
           "campbell": dict(res), "lexica_comparison": res2}
    (OUT / "coverage.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


def _in_diph(cl, i):
    b, m = cl[i]
    prev = cl[i - 1][0] if i else ""
    if "̈" not in m and b in DIPH_SECOND and prev in DIPH_FIRST:
        return True
    return i + 1 < len(cl) and b in DIPH_FIRST and cl[i + 1][0] in DIPH_SECOND and "̈" not in cl[i + 1][1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--skip-coverage", action="store_true"); a = ap.parse_args()
    sha = sha_file(RAW)
    recorded = json.loads(AUDIT.read_text(encoding="utf-8"))["raw_sha256"]
    if sha != recorded:
        sys.exit(f"raw sha256 mismatch: {sha} != {recorded}")
    m = build(sha)
    print(json.dumps(m["counts"], ensure_ascii=False, indent=1))
    if not a.skip_coverage:
        print(json.dumps(coverage(), ensure_ascii=False, indent=1))
