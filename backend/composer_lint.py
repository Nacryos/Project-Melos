"""Release W: the deterministic lint bank shared by the corpus proposer (/api/compose/suggest) and the composer
agent (POST /api/composer/check). PRD docs/prd/composer-agent.md §5.

Each check is {id, ok, blocking, detail, evidence}; ``ok`` is None when the check could not run (the index or the
n-gram data is missing on this deployment) and never blocks then. A candidate passes when every blocking check is ok.

  L7 metre        the scanner's syllables fit the metre: a whole line against the metre's template, or a
                  continuation against a prefix of ``remaining_template`` (the slots left after the caret), every
                  following line against a prefix of the next template. Blocking when a metre or template is set.
  L1 forms        every word is read by the corpus headword index, else by local Morpheus. Blocking.
  L2 dialect      Lesbian / Doric targets: a word not printed by a poet of the dialect fails when the dialect has an
                  attested spelling of the same headword (you wrote σελήνη; Sappho prints σελάννα). Blocking.
                  Ionic / Attic targets: a word printed only in Lesbian or Doric passages is flagged, not blocked.
  L4 attestation  tokens of each spelling in the corpus, in the dialect, and in the chosen poet. Never blocks.
  L11 verbatim    runs of 4+ words printed word for word in the corpus (homage). Never blocks.
"""
from __future__ import annotations

import time
from functools import lru_cache

from fastapi import HTTPException

SCAN_DIALECTS = ("none", "aeolic", "doric", "ionic", "attic")
FROM_PASSAGE_DIALECT = {"lesbian": "aeolic", "boeotian": "aeolic", "doric": "doric"}
TO_INDEX_DIALECT = {"aeolic": "lesbian", "doric": "doric", "ionic": "ionic"}
TEMPLATE_SYMBOLS = set("-uxFDRX")
VERBATIM_MIN = 4
PATTERN_SIGN = {"L": "–", "S": "⏑", "A": "?"}


def pattern_of(units) -> str:
    return "".join(PATTERN_SIGN[u.label] for u in units)


def target_dialect(dialect: str | None, author: str | None) -> str:
    """The scanner dialect: the one asked for, else the poet's (Sappho → aeolic), else none."""
    if dialect:
        if dialect not in SCAN_DIALECTS:
            raise HTTPException(422, {"code": "unknown_dialect", "message": f"dialect must be one of {', '.join(SCAN_DIALECTS)}"})
        return dialect
    from .passage_dialect import passage_dialect
    return FROM_PASSAGE_DIALECT.get(passage_dialect({"author": author or ""}) or "", "none")


def greek_words(text: str) -> list[str]:
    from .textutils import tokenize
    return [w for w in tokenize(text) if any(ch.isalpha() for ch in w)]


# ----------------------------------------------------------------------------------------------- L7 metre

def fit_summary(f) -> dict:
    return {"metre": f.metre, "template": f.template, "ok": f.ok, "pattern": f.pattern, "message": f.message,
            "violations": f.violations}


def metre_message(metre_name: str, f) -> str:
    label = metre_name.replace("_", " ")
    if f.ok:
        return f"fits {label}: {f.pattern}"
    return f"{label}: {f.message}" + "".join(f"; {v['text']} needs {v['needs']} ({v['reason']})" for v in f.violations)


def metre_check(units, metre_name: str, template: str) -> tuple[dict, dict]:
    """L7 for one whole line: (check, fit summary). Used by the corpus proposer and for saved versions."""
    from .scansion import metre
    f = metre.fit_line(units, metre_name, template)
    check = {"id": "L7", "name": "metre", "ok": f.ok, "blocking": True, "detail": metre_message(metre_name, f),
             "evidence": [{"rule": v.get("rule"), "syllable": v["text"], "needs": v["needs"], "p_long": v["p_long"]}
                          for v in f.violations]}
    return check, fit_summary(f)


def prefix_fit(units, label: str, template: str, *, whole: bool):
    """Best fit of ``units`` against the template's prefixes (the whole template when ``whole``): the longest
    prefix without violations, else the most likely parse. Returns (fit or None, slots left after it)."""
    from .scansion import metre
    lengths = [len(template)] if whole else range(len(template), 0, -1)
    best = None
    for k in lengths:
        f = metre.fit_line(units, label, template[:k])
        if f.ok:
            return f, template[k:]
        if f.pattern and (best is None or f.per_syllable > best[0].per_syllable):
            best = (f, template[k:])
    return best if best else (None, template)


def continuation_check(line_units: list[list], metre_name: str | None, remaining: str, line_index: int) -> tuple[dict, list]:
    """L7 for a continuation from the caret: first line against ``remaining`` (all of it when the candidate runs
    on into the next line), later lines against the metre's next templates."""
    from .scansion import metre
    label = metre_name or "template"
    fits, problems = [], []
    templates = list(metre.TEMPLATES.get(metre_name or "", []))
    for i, units in enumerate(line_units):
        last = i == len(line_units) - 1
        if i == 0:
            template = remaining
        elif templates:
            template = templates[(line_index + i) % len(templates)]
        else:
            problems.append(f"line {i + 1} of the candidate runs past the template and no metre is set")
            continue
        f, left = prefix_fit(units, label, template, whole=not last)
        if f is None:
            problems.append(f"line {i + 1}: {len(units)} syllables do not parse against {template}")
            continue
        fits.append({**fit_summary(f), "remaining_template": left})
        if not f.ok:
            problems.append(f"line {i + 1}: {metre_message(label, f)}")
    ok = not problems
    detail = ("fits " + " | ".join(f["pattern"] for f in fits) +
              (f"; slots left: {fits[-1]['remaining_template'] or 'none'}" if fits else "")) if ok else "; ".join(problems)
    evidence = [{"syllable": v["text"], "needs": v["needs"], "p_long": v["p_long"], "rule": v.get("rule")}
                for f in fits for v in f["violations"]]
    return {"id": "L7", "name": "metre", "ok": ok, "blocking": True, "detail": detail, "evidence": evidence}, fits


# ----------------------------------------------------------------------------------------------- L1 forms

def headline_rows(words: list[str], author: str = "") -> list[dict]:
    """The corpus headword index's reading of each word (raises HTTPException 503 without the index)."""
    from .word_headlines import headlines
    return headlines(forms=words, author=author or "").get("tokens") or []


def unread_forms(words: list[str], author: str = "") -> tuple[list[dict], list[str]]:
    """(headline rows, words the corpus index has no reading for). Shared with the corpus proposer."""
    rows = headline_rows(words, author)
    return rows, [r.get("printed") for r in rows if not r.get("lemma")]


def _parser_lemmas(form: str) -> tuple[str, ...]:
    """Local Morpheus headwords of a spelling (the parser caches its answers)."""
    from .dialectize import get_dialectizer
    parser = get_dialectizer().parser
    if not parser.available():
        return ()
    return tuple(dict.fromkeys(p["lemma"] for p in parser.parse(form) if p.get("lemma")))


def forms_check(words: list[str], author: str = "") -> tuple[dict, list[dict]]:
    """L1 (blocking): every word read by the corpus index, else by local Morpheus."""
    rows, unread = unread_forms(words, author)
    parsed, still = {}, []
    for form in unread:
        lemmas = _parser_lemmas(form)
        if lemmas:
            parsed[form] = list(lemmas[:3])
        else:
            still.append(form)
    detail = ("every word has a reading" if not unread else
              f"no reading for {', '.join(still)}" if still else
              "every word has a reading (" + ", ".join(f"{k}: Morpheus {'/'.join(v)}" for k, v in parsed.items()) + ")")
    return ({"id": "L1", "name": "forms", "ok": not still, "blocking": True, "detail": detail,
             "evidence": [{"form": f, "reading": None} for f in still] +
                         [{"form": f, "reading": "morpheus", "lemmas": v} for f, v in parsed.items()]}, rows)


# ----------------------------------------------------------------------------------------------- L2 / L4

def _evidence():
    from .dialectize import get_dialectizer
    return get_dialectizer().index


def attestation_rows(words: list[str], target: str, author: str) -> list[dict]:
    """Per word: tokens of the exact spelling in the corpus, in the target dialect's poets, and in the poet."""
    from .dialectize import _nfc
    ev = _evidence()
    spellings = [_nfc(w.strip("·,.;:!?")) for w in words]
    found = ev.forms(spellings)
    index_dialect = TO_INDEX_DIALECT.get(target, "")
    out = []
    for printed, spelling in zip(words, spellings):
        hit = found.get(spelling)
        row = {"form": printed, "tokens": int(hit["tokens"]) if hit else 0,
               "headwords": [l for _, l in (hit or {}).get("lemmas", [])[:3]], "dialect_tokens": None,
               "author_tokens": None, "example": None, "other_dialects": {}}
        if hit:
            att = ev.attestation(spelling, hit["form_ids"], [lid for lid, _ in hit["lemmas"]][:3],
                                 index_dialect if index_dialect in ("lesbian", "doric") else "", author)
            row.update(dialect_tokens=att["dialect_tokens"] if index_dialect in ("lesbian", "doric") else None,
                       author_tokens=att["author_tokens"], example=att["example"])
            for code, name in ((1, "lesbian"), (2, "doric")):
                table = ev.dialect_forms(code)
                n = sum((table.get(int(fid)) or [0])[0] for fid in hit["form_ids"])
                if n:
                    row["other_dialects"][name] = n
        out.append(row)
    return out


@lru_cache(maxsize=4096)
def _dialect_spellings(form: str, index_dialect: str, author: str) -> tuple[tuple[str, str], ...]:
    """Spellings of the same headword that poets of the dialect print ((spelling, example citation), ...)."""
    from .dialectize import get_dialectizer
    result = get_dialectizer().dialectize_one(form, index_dialect, author=author, use_parser=False)
    out = []
    for cand in result["candidates"]:
        if cand["verdict"] == "attested_in_dialect":
            ex = cand["evidence"].get("example_citation") or {}
            out.append((cand["form"], f"{ex.get('author') or ''} {ex.get('citation') or ''}".strip()))
    return tuple(out[:3])


def dialect_check(rows: list[dict], target: str, author: str) -> dict:
    """L2 from the attestation rows (see the module docstring)."""
    if target == "none":
        return {"id": "L2", "name": "dialect", "ok": True, "blocking": False, "detail": "no dialect chosen", "evidence": []}
    index_dialect = TO_INDEX_DIALECT.get(target, "")
    wrong, notes = [], []
    if index_dialect in ("lesbian", "doric"):
        for row in rows:
            if row["dialect_tokens"]:
                continue
            better = _dialect_spellings(row["form"].strip("·,.;:!?"), index_dialect, author or "")
            if better:
                wrong.append({"form": row["form"], "dialect_spellings": [{"form": s, "example": c} for s, c in better]})
            elif row["tokens"]:
                notes.append(f"{row['form']} is not printed by a {index_dialect} poet (no {index_dialect} spelling known)")
        detail = ("; ".join(f"{w['form']} → {target}: " + ", ".join(s["form"] for s in w["dialect_spellings"]) for w in wrong)
                  if wrong else f"every word is {target} or has no other {target} spelling")
        if notes and not wrong:
            detail += "; " + "; ".join(notes)
        return {"id": "L2", "name": "dialect", "ok": not wrong, "blocking": True, "detail": detail, "evidence": wrong}
    foreign = [{"form": r["form"], "dialects": r["other_dialects"]} for r in rows
               if r["tokens"] and r["other_dialects"] and sum(r["other_dialects"].values()) >= r["tokens"]]
    return {"id": "L2", "name": "dialect", "ok": not foreign, "blocking": False,
            "detail": ("printed only in " + "; ".join(f"{f['form']} ({', '.join(f['dialects'])})" for f in foreign)
                       if foreign else f"no word is printed only in Lesbian or Doric poets"), "evidence": foreign}


def attestation_check(rows: list[dict], author: str) -> dict:
    unattested = [r["form"] for r in rows if not r["tokens"]]
    in_poet = [r["form"] for r in rows if r["author_tokens"]]
    parts = [f"{len(rows) - len(unattested)}/{len(rows)} spellings printed in the corpus"]
    if author:
        parts.append(f"{len(in_poet)} printed by {author}")
    if unattested:
        parts.append("not printed: " + ", ".join(unattested))
    return {"id": "L4", "name": "attestation", "ok": True, "blocking": False, "detail": "; ".join(parts),
            "evidence": [{k: r[k] for k in ("form", "tokens", "dialect_tokens", "author_tokens", "example")} for r in rows]}


# ----------------------------------------------------------------------------------------------- L11 verbatim

def verbatim_check(words: list[str]) -> dict:
    """Runs of VERBATIM_MIN+ words printed word for word in the corpus (FTS phrase match), longest first."""
    from .server import connect
    from .textutils import normalize
    keys = [normalize(w).strip("·,.;:!?'\"") for w in words]
    keys = [k for k in keys if k]
    runs = []
    if len(keys) >= VERBATIM_MIN:
        with connect() as con:
            i = 0
            while i + VERBATIM_MIN <= len(keys):
                hit, j = None, i + VERBATIM_MIN
                while j <= len(keys):
                    phrase = " ".join(keys[i:j]).replace('"', "")
                    row = con.execute("SELECT p.id, p.author, p.citation FROM passage_fts f JOIN passages p ON p.id=f.id "
                                      "WHERE passage_fts MATCH ? LIMIT 1", ('normalized : "' + phrase + '"',)).fetchone()
                    if row is None:
                        break
                    hit = {"words": " ".join(words[i:j]), "passage_id": row["id"], "author": row["author"],
                           "citation": row["citation"]}
                    j += 1
                if hit:
                    runs.append(hit)
                    i = j - 1
                else:
                    i += 1
    return {"id": "L11", "name": "verbatim", "ok": not runs, "blocking": False,
            "detail": ("homage: " + "; ".join(f"“{r['words']}” = {r['author']} {r['citation']}" for r in runs)
                       if runs else f"no run of {VERBATIM_MIN}+ words is copied from the corpus"), "evidence": runs}


# ----------------------------------------------------------------------------------------------- the bank

def _unavailable(check_id: str, name: str, exc: Exception) -> dict:
    reason = exc.detail if isinstance(exc, HTTPException) else str(exc) or type(exc).__name__
    return {"id": check_id, "name": name, "ok": None, "blocking": False, "detail": f"not run: {reason}", "evidence": []}


def check(greek: str, *, metre_name: str | None = None, dialect: str | None = None, author: str | None = None,
          remaining_template: str | None = None, prefix: str | None = None, line_index: int = 0) -> dict:
    """Run the bank on one candidate. ``prefix`` is the current line before the caret (scanned with the candidate
    so word-boundary quantities are right; only the candidate's syllables are fitted)."""
    from .scansion import api as scan_api, metre
    t0 = time.perf_counter()
    author = (author or "").strip()
    target = target_dialect(dialect, author)
    if metre_name and metre_name not in metre.TEMPLATES:
        raise HTTPException(422, {"code": "unknown_metre", "message": f"unknown metre {metre_name!r}"})
    if remaining_template is not None and (not remaining_template or set(remaining_template) - TEMPLATE_SYMBOLS):
        raise HTTPException(422, {"code": "bad_template", "message": "remaining_template uses the symbols - u x F D R X"})
    scanner = scan_api._scanner(None, True, target)
    text = greek.strip("\n")
    lead = (prefix or "").rstrip()
    lines = scanner.scan_lines((lead + " " + text) if lead else text)
    if lead:
        skip = sum(len(line) for line in scanner.scan_lines(lead))
        first = lines[0][skip:] if lines else []
        lines = [first] + lines[1:]
    ms = {}
    checks = []
    if remaining_template:
        c, fits = continuation_check(lines, metre_name, remaining_template, line_index)
    elif metre_name:
        templates = metre.TEMPLATES[metre_name]
        results = [metre_check(units, metre_name, templates[(line_index + i) % len(templates)]) for i, units in enumerate(lines)]
        fits = [f for _, f in results]
        bad = [c for c, _ in results if not c["ok"]]
        c = {"id": "L7", "name": "metre", "ok": not bad, "blocking": True,
             "detail": "; ".join(x["detail"] for x in (bad or [r[0] for r in results])),
             "evidence": [e for x, _ in results for e in x["evidence"]]}
    else:
        fits = []
        c = {"id": "L7", "name": "metre", "ok": True, "blocking": False,
             "detail": "no metre chosen; scansion " + " | ".join(pattern_of(u) for u in lines), "evidence": []}
    checks.append(c)
    ms["L7"] = (time.perf_counter() - t0) * 1000
    words = greek_words(text)
    if words:
        t = time.perf_counter()
        try:
            checks.append(forms_check(words, author)[0])
        except Exception as exc:  # noqa: BLE001 - reported on the check, never hidden
            checks.append(_unavailable("L1", "forms", exc))
        ms["L1"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        try:
            rows = attestation_rows(words, target, author)
            checks.append(dialect_check(rows, target, author))
            checks.append(attestation_check(rows, author))
        except Exception as exc:  # noqa: BLE001
            checks.append(_unavailable("L2", "dialect", exc))
            checks.append(_unavailable("L4", "attestation", exc))
        ms["L2+L4"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        try:
            checks.append(verbatim_check(words))
        except Exception as exc:  # noqa: BLE001
            checks.append(_unavailable("L11", "verbatim", exc))
        ms["L11"] = (time.perf_counter() - t) * 1000
    passed = all(ch["ok"] is not False for ch in checks if ch["blocking"])
    scansion = {"dialect": target, "metre": metre_name, "remaining_template": remaining_template,
                "lines": [{"pattern": pattern_of(u),
                           "syllables": [{"text": s.text, "p_long": round(s.p_long, 3), "label": s.label} for s in u]}
                          for u in lines],
                "fit": fits}
    return {"pass": passed, "scansion": scansion, "checks": checks,
            "ms": {k: round(v, 1) for k, v in ms.items()} | {"total": round((time.perf_counter() - t0) * 1000, 1)}}
