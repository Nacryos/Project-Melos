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

import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from functools import lru_cache

from fastapi import HTTPException

SCAN_DIALECTS = ("none", "aeolic", "doric", "ionic", "attic")
FROM_PASSAGE_DIALECT = {"lesbian": "aeolic", "boeotian": "aeolic", "doric": "doric"}
TO_INDEX_DIALECT = {"aeolic": "lesbian", "doric": "doric", "ionic": "ionic"}
TEMPLATE_SYMBOLS = set("-uxFDRX")
VERBATIM_MIN = 4          # words in a copied run
VERBATIM_SHORT = 3        # ... or this many words
VERBATIM_LETTERS = 15     # ... with at least this many letters
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


# ----------------------------------------------------------------------------------------------- spelling, budget

# Elision is printed with U+2019 in the corpus (ἀθανάτ’); typed text often has ' (U+0027), ᾽ (koronis) or ʼ.
# U+1FBF (psili) is a distinct sign and is left alone (backend/textutils.tokenize).
_ELISION = str.maketrans({"'": "’", "᾽": "’", "ʼ": "’"})
_EDGE = "·,.;:!?\"“”«»()[]⟨⟩"
_POOLS: dict[str, ThreadPoolExecutor] = {}
_POOL_LOCK = threading.Lock()


def corpus_spelling(word: str) -> str:
    """The spelling the corpus index stores: NFC, outer punctuation off, elision marks as ’."""
    from .dialectize import _nfc
    return _nfc(word.strip(_EDGE)).translate(_ELISION)


def budget_seconds() -> float:
    """The hard latency budget of one check (MELOS_COMPOSER_CHECK_BUDGET_MS, default 1500)."""
    try:
        return max(50, int(os.environ.get("MELOS_COMPOSER_CHECK_BUDGET_MS", "1500"))) / 1000
    except ValueError:
        return 1.5


def _executor(name: str, env: str, default: int) -> ThreadPoolExecutor:
    with _POOL_LOCK:
        if name not in _POOLS:
            _POOLS[name] = ThreadPoolExecutor(max_workers=int(os.environ.get(env, default)), thread_name_prefix=name)
        return _POOLS[name]


def _pool() -> ThreadPoolExecutor:
    """Workers for per-word lookups. A lookup that misses the budget keeps running and fills the caches, so the
    next check of the same word is instant."""
    return _executor("composer-lookup", "MELOS_COMPOSER_CHECK_WORKERS", 16)


def _outer() -> ThreadPoolExecutor:
    """Workers for the per-check L1, L2+L4 and L11 tasks: separate from the lookup workers, so checks waiting on
    their lookups can never occupy every lookup worker."""
    return _executor("composer-check", "MELOS_COMPOSER_CHECK_TASKS", 48)


def _wait(future: Future, deadline: float):
    """(done, value, error): the future's result if it finishes before the deadline."""
    try:
        return True, future.result(timeout=max(0.0, deadline - time.perf_counter())), None
    except FutureTimeout:
        return False, None, None
    except Exception as exc:  # noqa: BLE001 - reported on the check
        return True, None, exc


# ----------------------------------------------------------------------------------------------- L1 forms

def headline_rows(words: list[str], author: str = "") -> list[dict]:
    """The corpus headword index's reading of each word (raises HTTPException 503 without the index)."""
    from .word_headlines import headlines
    return headlines(forms=words, author=author or "").get("tokens") or []


def unread_forms(words: list[str], author: str = "") -> tuple[list[dict], list[str]]:
    """(headline rows, words the corpus index has no reading for). Shared with the corpus proposer."""
    rows = headline_rows(words, author)
    return rows, [r.get("printed") for r in rows if not r.get("lemma")]


@lru_cache(maxsize=8192)
def _headline_lemma(spelling: str, author: str) -> str | None:
    rows = headline_rows([spelling], author)
    return rows[0].get("lemma") if rows else None


@lru_cache(maxsize=8192)
def _parser_lemmas(form: str) -> tuple[str, ...]:
    """Local Morpheus headwords of a spelling."""
    from .dialectize import get_dialectizer
    parser = get_dialectizer().parser
    if not parser.available():
        return ()
    return tuple(dict.fromkeys(p["lemma"] for p in parser.parse(form) if p.get("lemma")))


def _timeout_note(words: list[str], budget: float) -> str:
    return f"unresolved within the {round(budget * 1000)} ms budget (timeout): {', '.join(words)}"


def forms_check(words: list[str], author: str = "", *, deadline: float | None = None,
                budget: float | None = None) -> dict:
    """L1 (blocking): every word read by the corpus index, else by local Morpheus. Words still unresolved at the
    deadline fail the check (timeout), they never pass."""
    budget = budget or budget_seconds()
    deadline = deadline or time.perf_counter() + budget
    spellings = {w: corpus_spelling(w) for w in words}
    heads = {w: _pool().submit(_headline_lemma, spellings[w], author or "") for w in words}
    parsed, still, unresolved, errors, parses = {}, [], [], [], {}
    for w in words:
        done, lemma, exc = _wait(heads[w], deadline)
        if not done:
            unresolved.append(w)
        elif exc is not None:
            errors.append(exc)
        elif not lemma:
            parses[w] = _pool().submit(_parser_lemmas, spellings[w])
    for w, future in parses.items():
        done, lemmas, exc = _wait(future, deadline)
        if not done:
            unresolved.append(w)
        elif lemmas:
            parsed[w] = list(lemmas[:3])
        else:
            still.append(w)
    if errors and not unresolved and not still and len(errors) == len(words):
        raise errors[0]                      # the index is missing on this deployment: the check is not run
    notes = []
    if still:
        notes.append(f"no reading for {', '.join(still)}")
    if unresolved:
        notes.append(_timeout_note(unresolved, budget))
    if errors:
        notes.append(f"lookup failed for {len(errors)} word(s)")
    if parsed and not notes:
        notes.append("every word has a reading (" + ", ".join(f"{k}: Morpheus {'/'.join(v)}" for k, v in parsed.items()) + ")")
    ok = not (still or unresolved or errors)
    return {"id": "L1", "name": "forms", "ok": ok, "blocking": True, "detail": "; ".join(notes) or "every word has a reading",
            "evidence": [{"form": f, "reading": None} for f in still] +
                        [{"form": f, "reading": "morpheus", "lemmas": v} for f, v in parsed.items()] +
                        [{"form": f, "reading": "timeout"} for f in unresolved]}


# ----------------------------------------------------------------------------------------------- L2 / L4

def _evidence():
    from .dialectize import get_dialectizer
    return get_dialectizer().index


@lru_cache(maxsize=8192)
def _attestation(spelling: str, target: str, author: str) -> tuple:
    """(tokens, headwords, dialect tokens, author tokens, example, other dialects) of one spelling, cached."""
    ev = _evidence()
    hit = ev.forms([spelling]).get(spelling)
    index_dialect = TO_INDEX_DIALECT.get(target, "")
    if not hit:
        return 0, (), None, None, None, ()
    att = ev.attestation(spelling, hit["form_ids"], [lid for lid, _ in hit["lemmas"]][:3],
                         index_dialect if index_dialect in ("lesbian", "doric") else "", author)
    other = []
    for code, name in ((1, "lesbian"), (2, "doric")):
        table = ev.dialect_forms(code)
        n = sum((table.get(int(fid)) or [0])[0] for fid in hit["form_ids"])
        if n:
            other.append((name, n))
    return (int(hit["tokens"]), tuple(l for _, l in hit["lemmas"][:3]),
            att["dialect_tokens"] if index_dialect in ("lesbian", "doric") else None, att["author_tokens"],
            att["example"], tuple(other))


def attestation_row(printed: str, target: str, author: str) -> dict:
    tokens, heads, dialect_tokens, author_tokens, example, other = _attestation(corpus_spelling(printed), target, author)
    return {"form": printed, "tokens": tokens, "headwords": list(heads), "dialect_tokens": dialect_tokens,
            "author_tokens": author_tokens, "example": example, "other_dialects": dict(other)}


def attestation_rows(words: list[str], target: str, author: str) -> list[dict]:
    """Per word: tokens of the exact spelling in the corpus, in the target dialect's poets, and in the poet."""
    return [attestation_row(w, target, author) for w in words]


@lru_cache(maxsize=8192)
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


def _needs_dialect_lookup(row: dict, target: str) -> bool:
    return TO_INDEX_DIALECT.get(target, "") in ("lesbian", "doric") and not row["dialect_tokens"]


def dialect_check(rows: list[dict], target: str, author: str, *, spellings: dict | None = None,
                  unresolved: list[str] = (), budget: float | None = None) -> dict:
    """L2 from the attestation rows (see the module docstring). ``spellings`` = {form: dialect spellings} already
    looked up; ``unresolved`` = words whose lookups missed the budget (they fail the check)."""
    if target == "none":
        return {"id": "L2", "name": "dialect", "ok": True, "blocking": False, "detail": "no dialect chosen", "evidence": []}
    index_dialect = TO_INDEX_DIALECT.get(target, "")
    timeout = [_timeout_note(list(unresolved), budget or budget_seconds())] if unresolved else []
    unresolved_evidence = [{"form": w, "reading": "timeout"} for w in unresolved]
    if index_dialect in ("lesbian", "doric"):
        wrong, notes = [], []
        for row in rows:
            if not _needs_dialect_lookup(row, target):
                continue
            better = (spellings[row["form"]] if spellings is not None and row["form"] in spellings else
                      _dialect_spellings(corpus_spelling(row["form"]), index_dialect, author or ""))
            if better:
                wrong.append({"form": row["form"], "dialect_spellings": [{"form": s, "example": c} for s, c in better]})
            elif row["tokens"]:
                notes.append(f"{row['form']} is not printed by a {index_dialect} poet (no {index_dialect} spelling known)")
        parts = ["; ".join(f"{w['form']} → {target}: " + ", ".join(s["form"] for s in w["dialect_spellings"]) for w in wrong)
                 ] if wrong else ([] if unresolved else [f"every word is {target} or has no other {target} spelling"])
        if notes and not wrong:
            parts += notes
        return {"id": "L2", "name": "dialect", "ok": not wrong and not unresolved, "blocking": True,
                "detail": "; ".join(parts + timeout), "evidence": wrong + unresolved_evidence}
    foreign = [{"form": r["form"], "dialects": r["other_dialects"]} for r in rows
               if r["tokens"] and r["other_dialects"] and sum(r["other_dialects"].values()) >= r["tokens"]]
    return {"id": "L2", "name": "dialect", "ok": not foreign and not unresolved, "blocking": bool(unresolved),
            "detail": "; ".join((["printed only in " + "; ".join(f"{f['form']} ({', '.join(f['dialects'])})" for f in foreign)]
                                 if foreign else [] if unresolved else ["no word is printed only in Lesbian or Doric poets"])
                                + timeout),
            "evidence": foreign + unresolved_evidence}


def attestation_check(rows: list[dict], author: str, unresolved: list[str] = ()) -> dict:
    unattested = [r["form"] for r in rows if not r["tokens"]]
    in_poet = [r["form"] for r in rows if r["author_tokens"]]
    parts = [f"{len(rows) - len(unattested)}/{len(rows)} spellings printed in the corpus"]
    if author:
        parts.append(f"{len(in_poet)} printed by {author}")
    if unattested:
        parts.append("not printed: " + ", ".join(unattested))
    if unresolved:
        parts.append("not looked up in time: " + ", ".join(unresolved))
    return {"id": "L4", "name": "attestation", "ok": True, "blocking": False, "detail": "; ".join(parts),
            "evidence": [{k: r[k] for k in ("form", "tokens", "dialect_tokens", "author_tokens", "example")} for r in rows]}


def dialect_and_attestation(words: list[str], target: str, author: str, *, deadline: float,
                            budget: float) -> tuple[dict, dict]:
    """L2 and L4 with every per-word lookup run concurrently and bounded by the deadline."""
    index_dialect = TO_INDEX_DIALECT.get(target, "")
    futures = {w: _pool().submit(attestation_row, w, target, author) for w in words}
    rows, unresolved, errors, lookups = [], [], [], {}
    for w in words:
        done, row, exc = _wait(futures[w], deadline)
        if not done:
            unresolved.append(w)
        elif exc is not None:
            errors.append((w, exc))
        else:
            rows.append(row)
            if _needs_dialect_lookup(row, target):
                lookups[w] = _pool().submit(_dialect_spellings, corpus_spelling(w), index_dialect, author or "")
    if errors and not rows and not unresolved:
        raise errors[0][1]                   # the index is missing on this deployment: the checks are not run
    spellings = {}
    for w, future in lookups.items():
        done, better, exc = _wait(future, deadline)
        if not done:
            unresolved.append(w)
        elif exc is not None:
            errors.append((w, exc))
        else:
            spellings[w] = better
    unresolved += [f"{w} (lookup failed: {type(e).__name__})" for w, e in errors]   # failures never pass
    resolved_rows = [r for r in rows if r["form"] not in unresolved and (not _needs_dialect_lookup(r, target)
                                                                          or r["form"] in spellings)]
    return (dialect_check(resolved_rows, target, author, spellings=spellings, unresolved=unresolved, budget=budget),
            attestation_check(rows, author, unresolved))


# ----------------------------------------------------------------------------------------------- L11 verbatim

def _qualifies(words: list[str]) -> bool:
    """A copied run worth flagging: 4+ words, or 3+ words with 15+ letters (a whole short colon such as
    ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα), never a run of short function words."""
    letters = sum(ch.isalpha() for w in words for ch in w)
    return len(words) >= VERBATIM_MIN or (len(words) >= VERBATIM_SHORT and letters >= VERBATIM_LETTERS)


@lru_cache(maxsize=8192)
def _phrase_in_corpus(phrase: str):
    from .server import connect
    with connect() as con:
        row = con.execute("SELECT p.id, p.author, p.citation FROM passage_fts f JOIN passages p ON p.id=f.id "
                          "WHERE passage_fts MATCH ? LIMIT 1", ('normalized : "' + phrase + '"',)).fetchone()
    return None if row is None else (row["id"], row["author"], row["citation"])


def verbatim_check(words: list[str]) -> dict:
    """Copied runs (``_qualifies``) printed word for word in the corpus (FTS phrase match on the normalised text,
    elision marks folded), longest first."""
    from .textutils import normalize
    pairs = [(w, normalize(corpus_spelling(w)).replace("'", " ").replace('"', " ").strip()) for w in words]
    pairs = [(w, k) for w, k in pairs if k]
    printed, keys = [w for w, _ in pairs], [k for _, k in pairs]
    runs = []
    i = 0
    while i + VERBATIM_SHORT <= len(keys):
        hit, j = None, i + VERBATIM_SHORT
        while j <= len(keys):
            row = _phrase_in_corpus(" ".join(keys[i:j]))
            if row is None:
                break
            if _qualifies(printed[i:j]):
                hit = {"words": " ".join(printed[i:j]), "passage_id": row[0], "author": row[1], "citation": row[2]}
            j += 1
        if hit:
            runs.append(hit)
            i += len(hit["words"].split())
        else:
            i += 1
    return {"id": "L11", "name": "verbatim", "ok": not runs, "blocking": False,
            "detail": ("homage: " + "; ".join(f"“{r['words']}” = {r['author']} {r['citation']}" for r in runs)
                       if runs else "no run of 4+ words (or 3 long words) is copied from the corpus"), "evidence": runs}


# ----------------------------------------------------------------------------------------------- the bank

def _unavailable(check_id: str, name: str, exc: Exception) -> dict:
    reason = exc.detail if isinstance(exc, HTTPException) else str(exc) or type(exc).__name__
    return {"id": check_id, "name": name, "ok": None, "blocking": False, "detail": f"not run: {reason}", "evidence": []}


def check(greek: str, *, metre_name: str | None = None, dialect: str | None = None, author: str | None = None,
          remaining_template: str | None = None, prefix: str | None = None, line_index: int = 0,
          require_template: bool = False) -> dict:
    """Run the bank on one candidate within the latency budget. ``prefix`` is the current line before the caret
    (scanned with the candidate so word-boundary quantities are right; only the candidate's syllables are
    fitted). ``require_template`` (the agent's candidates): without remaining_template or a concrete metre the
    metre cannot reject anything, so L7 fails instead of passing."""
    from .scansion import api as scan_api, metre
    t0 = time.perf_counter()
    budget = budget_seconds()
    deadline = t0 + budget
    author = (author or "").strip()
    target = target_dialect(dialect, author)
    if metre_name and metre_name not in metre.TEMPLATES:
        raise HTTPException(422, {"code": "unknown_metre", "message": f"unknown metre {metre_name!r}"})
    if remaining_template is not None and (not remaining_template or set(remaining_template) - TEMPLATE_SYMBOLS):
        raise HTTPException(422, {"code": "bad_template", "message": "remaining_template uses the symbols - u x F D R X"})
    text = greek.strip("\n")
    words = greek_words(text)
    # Lookups start first so they overlap the scansion.
    pending = {}
    if words:
        pending["L1"] = _outer().submit(forms_check, words, author, deadline=deadline, budget=budget)
        pending["L2+L4"] = _outer().submit(dialect_and_attestation, words, target, author, deadline=deadline, budget=budget)
        pending["L11"] = _outer().submit(verbatim_check, words)
    scanner = scan_api._scanner(None, True, target)
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
    elif require_template:
        fits = []
        c = {"id": "L7", "name": "metre", "ok": False, "blocking": True,
             "detail": ("no concrete template: send remaining_template (the open slots at the caret) or a named metre; "
                        "with metre auto or none the metre check cannot reject anything"), "evidence": [],
             "template": "missing"}
    else:
        fits = []
        c = {"id": "L7", "name": "metre", "ok": True, "blocking": False,
             "detail": "no metre chosen; scansion " + " | ".join(pattern_of(u) for u in lines), "evidence": [],
             "template": "missing"}
    checks.append(c)
    ms["L7"] = (time.perf_counter() - t0) * 1000
    names = {"L1": [("L1", "forms")], "L2+L4": [("L2", "dialect"), ("L4", "attestation")], "L11": [("L11", "verbatim")]}
    for key, future in pending.items():
        # The per-word lookups inside each check honour the deadline; this outer wait adds a small grace for
        # assembling the result.
        done, value, exc = _wait(future, deadline + 0.05)
        ms[key] = (time.perf_counter() - t0) * 1000
        if done and exc is None:
            checks.extend(value if isinstance(value, tuple) else [value])
        elif done:
            checks.extend(_unavailable(i, n, exc) for i, n in names[key])
        else:
            for i, n in names[key]:
                blocking = i in ("L1", "L2")
                checks.append({"id": i, "name": n, "ok": False if blocking else None, "blocking": blocking,
                               "detail": _timeout_note(words, budget) if blocking else f"not run: timeout ({round(budget * 1000)} ms)",
                               "evidence": []})
    passed = all(ch["ok"] is not False for ch in checks if ch["blocking"])
    scansion = {"dialect": target, "metre": metre_name, "remaining_template": remaining_template,
                "template": "given" if (remaining_template or metre_name) else "missing",
                "lines": [{"pattern": pattern_of(u),
                           "syllables": [{"text": s.text, "p_long": round(s.p_long, 3), "label": s.label} for s in u]}
                          for u in lines],
                "fit": fits}
    return {"pass": passed, "scansion": scansion, "checks": checks, "budget_ms": round(budget * 1000),
            "ms": {k: round(v, 1) for k, v in ms.items()} | {"total": round((time.perf_counter() - t0) * 1000, 1)}}
