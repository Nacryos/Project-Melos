"""Catullan style evidence for the Latin composer: L5 collocation and L6 manner evidence
(docs/prd/catullan-hendecasyllable-checks.md; the Greek counterparts are L5/L6 of docs/composer/loop-design.md).

Both checks only count and cite; neither blocks. Everything is counted from two stores, not from hand lists:
the lemma index's token table (data/lemma_index_la.sqlite: LASLA's human lemma, part of speech and features for every
word of Catullus and Horace, by poem and line) and the Hypotactic hand scansion
(data/open/latin/hypotactic/lines.jsonl.gz: a metre label per line and every word's syllables, so the syllable at
which a word starts in the hendecasyllable is known).

  L5 collocation      each pair of content words (noun, verb, adjective, proper name, by lemma) in a line or in two
                      adjacent lines: is the pair printed within the same window by the poet, else by the other
                      indexed poets (Horace); adjacent word pairs printed verbatim. The draft's share of pairs with a
                      parallel is set against the poet's own poems in the metre, each held out against the rest.
  L6 manner evidence  per content word: tokens of the lemma in the polymetrics (1-60), long poems (61-68), epigrams
                      (69-116) and in the hendecasyllabic poems; the syllable at which the form and the lemma start
                      in the hendecasyllable and their line-final share; a warning when the lemma is absent from the
                      polymetrics or from Catullus. Then the countable markers (diminutives, interjections, vocatives,
                      second person, repeated line openings, repeated lemmas, run-on lines) per 100 lines in the
                      poet's hendecasyllables against the draft.

Contract: check_*(text, *, metre_name="phalaecian", author="Catullus") -> {id, name, ok, blocking, detail, evidence};
``ok`` False is a warning; a missing data file gives ok True with a detail beginning "unavailable:"; nothing raises.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from . import latin_backend, latin_lemma
from .latin_text import normalize_la

CONTENT_UPOS = ("NOUN", "VERB", "ADJ", "PROPN")          # the parts of speech paired by L5 and listed by L6
BOOK_GROUPS = {"Catullus": (("polymetrics", 1, 60), ("long poems", 61, 68), ("epigrams", 69, 116))}
GOLD_METRE = {"phalaecian": "hendecasyllables"}           # composer metre name -> Hypotactic metre label
LOCI = 3                                                  # loci shown per pair
# A diminutive is a noun or adjective lemma that Lewis & Short marks dim. (diminutive_info). For a lemma with no
# entry the suffix rule decides: one of these suffixes, and a base (the stem with one of the listed endings) that is
# itself a noun or adjective lemma of the index: libellus < liber, ocellus < oculus, flosculus < flos.
DIMINUTIVE_BASES = (("cul", ("", "s", "is", "es")), ("ell", ("er", "ra", "rum", "ulus", "ula", "ulum", "us", "a", "um")),
                    ("ill", ("us", "a", "um", "is")), ("ol", ("us", "a", "um")), ("ul", ("us", "a", "um")))
_DIM_END = re.compile(r"(us|a|um)$")
_PUNCT_END = ".,;:!?"


def _data_dir() -> Path:
    return Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


def gold_path() -> Path:
    return _data_dir() / "open" / "latin" / "hypotactic" / "lines.jsonl.gz"


def available() -> bool:
    return latin_lemma.available() and latin_backend.available()


def _unavailable(check_id: str, name: str, reason) -> dict:
    return {"id": check_id, "name": name, "ok": True, "blocking": False,
            "detail": f"unavailable: {str(reason) or type(reason).__name__}", "evidence": []}


def _lem(lemma: str) -> str:
    return (lemma or "").rstrip("0123456789")


def _poem_no(citation: str) -> int:
    m = re.search(r"\d+", citation or "")
    return int(m.group(0)) if m else 0


def _letters(form: str) -> str:
    return "".join(ch for ch in normalize_la(form) if ch.isalpha())


def _rate(count: int, lines: int) -> float:
    return round(100 * count / lines, 1) if lines else 0.0


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[round(q * (len(s) - 1))] if s else 0.0


# ----------------------------------------------------------------------------------------------- the stores

@lru_cache(maxsize=1)
def _authors() -> tuple[str, ...]:
    return tuple(r[0] for r in latin_lemma._db().execute("SELECT author FROM token GROUP BY author ORDER BY author"))


@lru_cache(maxsize=1)
def _nominal_lemmas() -> frozenset:
    return frozenset(r[0] for r in latin_lemma._db().execute("SELECT lemma FROM lemma WHERE upos IN ('NOUN','ADJ')"))


LS_HEAD = 120          # characters of a Lewis & Short entry read for "dim." (the entry's head, before the senses)
_LS_DIM = re.compile(r"\bdim\.")
_LS_BASE = re.compile(r"\bdim\.,?\s*(?:of\s+)?\[?\s*(?:\d\.\s*)?([a-z]+)")
_LS_FROM = re.compile(r"\bfrom\s+([a-z]+)")
_DIM_SHAPE = re.compile(r"l(us|a|um)$")          # only lemmas of this shape are looked up


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(ch)).replace("v", "u").replace("j", "i")


def _suffix_base(lemma: str) -> str | None:
    """The base by suffix: the stripped stem is itself a noun or adjective of the lemma index (see DIMINUTIVE_BASES)."""
    m = _DIM_END.search(lemma)
    if not m:
        return None
    body = lemma[:m.start()]
    for suffix, endings in DIMINUTIVE_BASES:
        if body.endswith(suffix) and len(body) - len(suffix) >= 2:
            stem = body[:-len(suffix)]
            for e in endings:
                if stem + e != lemma and stem + e in _nominal_lemmas():
                    return stem + e
    return None


def _ls_entries(lemma: str) -> list[dict] | None:
    """The lemma's own Lewis & Short entries (not proper names), or None when the dictionary cannot be read."""
    for attempt in (0, 1):                       # the module may be mid-edit by its owner: one retry
        try:
            from . import latin_dictionary
            rows = latin_dictionary.lookup(lemma) or []
            break
        except Exception:  # noqa: BLE001 - no dictionary: the suffix rule decides
            if attempt:
                return None
    return [e for e in rows if isinstance(e, dict) and str(e.get("key") or "")[:1].islower()
            and _fold(str(e.get("key") or "")).rstrip("0123456789") == lemma]


@lru_cache(maxsize=4096)
def diminutive_info(lemma: str) -> tuple[str, str] | None:
    """(base, how) of a diminutive lemma, or None. how = "Lewis & Short" when the lemma's entry says dim. in its
    first LS_HEAD characters (base "" when the entry names none); a lemma with an entry that does not say so is not a
    diminutive (puella, tabula, oraculum). how = "by suffix" only for a lemma with no entry: suffix and base both
    read from the lemma index."""
    lemma = _lem(lemma)
    if not _DIM_SHAPE.search(lemma):
        return None
    entries = _ls_entries(lemma)
    if entries:
        for e in entries:
            head = _fold(str(e.get("text") or e.get("head") or "")[:LS_HEAD])
            if _LS_DIM.search(head):
                m = _LS_BASE.search(head)
                base = m.group(1) if m else ""
                if base == "for":
                    m = _LS_FROM.search(head)
                    base = m.group(1) if m else ""
                return ("" if base in ("id", "cf", "from", "of", "v", "a", "ab", "the", "etym", "perh", "dub") else base, "Lewis & Short")
        return None
    base = _suffix_base(lemma)
    return (base, "by suffix") if base else None


def diminutive_base(lemma: str) -> str | None:
    """The base of a diminutive lemma ("" when Lewis & Short marks it dim. without naming one), None when it is none."""
    info = diminutive_info(lemma)
    return info[0] if info else None


@lru_cache(maxsize=4)
def _corpus(author: str) -> dict:
    """The poet's lines from the token table, in the book's order: each {pid, poem, cite, text, toks, content};
    a token is (normalized, lemma, upos, feats)."""
    rows = latin_lemma._db().execute("SELECT passage_id, citation, work, line_n, idx, normalized, lemma, upos, feats, form "
                                     "FROM token WHERE author=? ORDER BY rowid", (author,)).fetchall()
    texts = {r["id"]: r["text"].split("\n") for r in latin_backend._db().execute(
        "SELECT id, text FROM passages WHERE author=? AND kind='text'", (author,))}
    lines, at = [], {}
    for r in rows:
        if r["line_n"] in (None, ""):
            continue
        key = (r["passage_id"], r["line_n"])
        if key not in at:
            at[key] = len(lines)
            lines.append({"pid": r["passage_id"], "poem": _poem_no(r["citation"]), "work": r["work"],
                          "cite": f"{r['citation']}.{r['line_n']}", "n": r["line_n"], "toks": [], "forms": []})
        lines[at[key]]["toks"].append((r["idx"], r["normalized"], _lem(r["lemma"]), r["upos"], r["feats"] or ""))
        lines[at[key]]["forms"].append((r["idx"], r["form"]))
    for line in lines:
        line["toks"] = [t[1:] for t in sorted(line["toks"])]
        printed = texts.get(line["pid"]) or []
        n = int(line["n"]) if str(line["n"]).isdigit() else 0
        text = printed[n - 1] if 0 < n <= len(printed) else ""
        line["printed"] = bool(text) and bool(line["toks"]) and line["toks"][0][0] in _letters_words(text)
        line["text"] = text if line["printed"] else " ".join(f for _, f in sorted(line.pop("forms")))
        line.pop("forms", None)
        line["content"] = sorted({t[1] for t in line["toks"] if t[2] in CONTENT_UPOS and t[1]})
    return {"lines": lines}


def _letters_words(text: str) -> set[str]:
    return {normalize_la(w) for w in latin_backend.latin_words(text)}


@lru_cache(maxsize=4)
def _pair_index(author: str) -> dict:
    """{(lemma, lemma): [(window, line index)]}: window 0 = both in one line, 1 = in that line and the next."""
    lines = _corpus(author)["lines"]
    index = defaultdict(list)
    for i, line in enumerate(lines):
        for pair in combinations(line["content"], 2):
            index[pair].append((0, i))
        if i + 1 < len(lines) and lines[i + 1]["pid"] == line["pid"]:
            for a in line["content"]:
                for b in lines[i + 1]["content"]:
                    if a != b:
                        index[tuple(sorted((a, b)))].append((1, i))
    return dict(index)


@lru_cache(maxsize=1)
def _gold() -> tuple:
    with gzip.open(gold_path(), "rt", encoding="utf-8") as fh:
        return tuple(json.loads(line) for line in fh if line.strip())


@lru_cache(maxsize=8)
def _metre_poems(author: str, metre_name: str) -> frozenset:
    """Poem numbers of the poet's poems in the metre (the gold's metre label); empty when the gold has none."""
    label = GOLD_METRE.get(metre_name, metre_name)
    return frozenset(_poem_no(r["poem_number"]) for r in _gold() if r["author"] == author and r["metre"] == label)


def _metre_lines(author: str, metre_name: str) -> list[dict]:
    poems = _metre_poems(author, metre_name)
    return [l for l in _corpus(author)["lines"] if l["poem"] in poems]


@lru_cache(maxsize=4)
def _lemma_counts(author: str, metre_name: str) -> dict:
    """{lemma: Counter(group -> tokens)} with the groups of BOOK_GROUPS (else the work's name), 'metre' and 'total'."""
    poems = _metre_poems(author, metre_name)
    groups = BOOK_GROUPS.get(author)
    out = defaultdict(Counter)
    for line in _corpus(author)["lines"]:
        group = next((g for g, lo, hi in groups if lo <= line["poem"] <= hi), "other") if groups else line["work"]
        for _n, lemma, _u, _f in line["toks"]:
            c = out[lemma]
            c[group] += 1
            c["total"] += 1
            if line["poem"] in poems:
                c["metre"] += 1
    return dict(out)


@lru_cache(maxsize=4)
def _form_lemmas(author: str) -> tuple[dict, dict]:
    """({(poem, spelling): lemma}, {spelling: commonest lemma}) of the poet, to give a gold word its lemma."""
    by_poem, counts = {}, defaultdict(Counter)
    for line in _corpus(author)["lines"]:
        for n, lemma, _u, _f in line["toks"]:
            by_poem.setdefault((line["poem"], n), lemma)
            counts[n][lemma] += 1
    return by_poem, {n: c.most_common(1)[0][0] for n, c in counts.items()}


@lru_cache(maxsize=4)
def _positions(author: str, metre_name: str) -> dict:
    """Where words start in the poet's lines of the metre (gold hand scansion; elided syllables take no place):
    {"form": {spelling: Counter(start)}, "lemma": {...}, "form_final": Counter, "lemma_final": Counter, "lines": n}."""
    label = GOLD_METRE.get(metre_name, metre_name)
    by_poem, commonest = _form_lemmas(author)
    out = {"form": defaultdict(Counter), "lemma": defaultdict(Counter), "form_final": Counter(), "lemma_final": Counter(), "lines": 0}
    for r in _gold():
        if r["author"] != author or r["metre"] != label:
            continue
        out["lines"] += 1
        poem, pos = _poem_no(r["poem_number"]), 1
        for k, w in enumerate(r["words"]):
            n = _letters(w["form"])
            lemma = by_poem.get((poem, n)) or commonest.get(n) or n
            out["form"][n][pos] += 1
            out["lemma"][lemma][pos] += 1
            if k == len(r["words"]) - 1:
                out["form_final"][n] += 1
                out["lemma_final"][lemma] += 1
            pos += sum(1 for s in w["syl"] if s["q"] != "E")
    return out


@lru_cache(maxsize=8192)
def _spelling_feats(normalized: str) -> str:
    """LASLA's commonest features for a spelling (any poet of the index): the draft's vocatives and second persons."""
    row = latin_lemma._db().execute("SELECT feats, COUNT(*) AS c FROM token WHERE normalized=? GROUP BY feats ORDER BY c DESC LIMIT 1",
                                    (normalized,)).fetchone()
    return (row["feats"] or "") if row else ""


@lru_cache(maxsize=8192)
def _lemma_upos(lemma: str) -> str:
    row = latin_lemma._db().execute("SELECT upos FROM lemma WHERE lemma=? ORDER BY count DESC LIMIT 1", (lemma,)).fetchone()
    return row["upos"] if row else ""


# ----------------------------------------------------------------------------------------------- the draft

def read_draft(text: str, author: str = "Catullus") -> list[dict]:
    """The draft's lines: [{text, words: [{form, normalized, lemma, upos, content, feats}]}], lemma by the index's
    commonest reading of the spelling (LatinCy's reading in context first when the sidecar runs). Readings the index
    cannot rank (equal counts: "basium" = basis or basium) go to the lemma the author uses most."""
    try:
        used = _lemma_counts(author, "phalaecian")
    except Exception:  # noqa: BLE001 - the tie-break is optional
        used = {}
    raw = [l.strip() for l in str(text or "").replace(" / ", "\n").split("\n") if l.strip()]
    per_line = [latin_backend.latin_words(l) for l in raw]
    ctx = latin_lemma.context_lemmas([w for ws in per_line for w in ws])
    out, k = [], 0
    for line, ws in zip(raw, per_line):
        words = []
        for w in ws:
            n = normalize_la(w).replace("'", "")
            reads = latin_lemma.readings(w)
            if not reads:
                for e in latin_backend.ENCLITICS:
                    if n.endswith(e) and len(n) > len(e) + 1 and latin_lemma.readings(n[:-len(e)]):
                        reads = latin_lemma.readings(n[:-len(e)])
                        break
            reads, _how = latin_lemma.choose_reading(reads, ctx.get(k))
            k += 1
            if len(reads) > 1 and used:
                tied = [r for r in reads if r.get("count") == reads[0].get("count")]
                reads = sorted(tied, key=lambda r: -used.get(_lem(r["lemma"]), {}).get("total", 0)) + reads[len(tied):]
            lemma = _lem(reads[0]["lemma"]) if reads else ""
            upos = (reads[0].get("upos") or _lemma_upos(lemma)) if reads else ""
            morph = _analyses(w)
            cands = [(_lem(r["lemma"]), r.get("upos") or _lemma_upos(_lem(r["lemma"]))) for r in reads]
            if reads:                              # readings the index does not hold for the spelling (bella = bellus)
                cands += [(_lem(a["lemma"]), a.get("pos") or "") for a in morph if a.get("pos") in CONTENT_UPOS]
            seen = set()
            cands = [c for c in cands if c[0] and not (c[0] in seen or seen.add(c[0]))]
            words.append({"form": w, "normalized": n, "lemma": lemma or n, "upos": upos, "read": bool(reads),
                          "content": upos in CONTENT_UPOS or not upos, "feats": _spelling_feats(n),
                          "candidates": cands, "_morph": morph})
        _agreement_first(words)
        out.append({"text": line, "words": words})
    return out


MAX_READINGS = 4          # candidate lemmas of one spelling for which L5 and L6 gather evidence
NEAR = 2                  # "neighbouring": within two words either side (whole-line agreement promoted bellus in
                          # "bella gerunt alii, tu felix nube puella" through felix and nube)


def _analyses(form: str) -> list[dict]:
    """latin_morph.analyses(form), [] when the store or the module is missing (one retry: it may be mid-edit)."""
    for attempt in (0, 1):
        try:
            from . import latin_morph
            return list(latin_morph.analyses(form) or [])
        except Exception:  # noqa: BLE001 - no morphology: the index's first reading stands
            if attempt:
                return []
    return []


def _agreement_first(words: list[dict]) -> None:
    """Put first, among a word's candidate lemmas, the one that agrees best with its neighbours (NEAR words either
    side): in case, number and gender with an adjective or noun (one of the two an adjective), and as a nominative
    with the number of a finite verb. Ties, and a first reading the morphology does not know, keep the index's
    order. The first candidate becomes the word's lemma."""
    for k, w in enumerate(words):
        cands = w.get("candidates") or []
        if len(cands) < 2:
            continue
        others = [a for j, o in enumerate(words) if j != k and abs(j - k) <= NEAR for a in o.get("_morph") or []]
        finite = {a.get("number") for a in others if a.get("person") and a.get("number")}

        def score(lemma: str) -> int | None:
            best = None                            # None: the morphology has no nominal analysis under this lemma
            for a in w.get("_morph") or []:
                if _lem(a.get("lemma") or "") != lemma or not a.get("case"):
                    continue
                best = best or 0
                agrees = any(b.get("case") == a["case"] and b.get("number") == a.get("number") and a.get("gender")
                             and b.get("gender") == a["gender"] and "ADJ" in (a.get("pos"), b.get("pos")) for b in others)
                best = max(best, int(agrees) + int(a["case"] == "nom" and a.get("number") in finite))
            return best

        scores = {lemma: score(lemma) for lemma, _u in cands}
        first = scores[cands[0][0]]                # None (unknown to the morphology): the index's order stands
        best = max(cands, key=lambda c: scores[c[0]] or 0)
        if first is not None and (scores[best[0]] or 0) > first:
            cands = [best] + [c for c in cands if c != best]
        w["candidates"] = cands = cands[:MAX_READINGS]
        if cands[0][0] != w["lemma"]:
            w["lemma"], w["upos"] = cands[0][0], cands[0][1] or w["upos"]
            w["content"] = w["upos"] in CONTENT_UPOS or not w["upos"]
            w["by_agreement"] = True
    for w in words:
        w.pop("_morph", None)


def _draft_starts(text: str) -> list[dict] | None:
    """Per draft line {word index: starting syllable} from the Latin scanner (elided syllables take no place)."""
    try:
        from .scansion import api as scan_api
        lines = scan_api._scanner(None, True, "none", "la").scan_lines("\n".join(l["text"] for l in read_draft(text)))
    except Exception:  # noqa: BLE001 - positions are evidence only
        return None
    out = []
    for units in lines:
        starts, pos = {}, 0
        for u in units:
            if u.label != "E":
                pos += 1
            starts.setdefault(u.word, pos if u.label != "E" else pos + 1)
        out.append(starts)
    return out


# ----------------------------------------------------------------------------------------------- L5 collocation

def _locus(author: str, hit: tuple[int, int]) -> dict:
    lines = _corpus(author)["lines"]
    window, i = hit
    text = lines[i]["text"] + (" / " + lines[i + 1]["text"] if window else "")
    return {"author": author, "citation": lines[i]["cite"], "window": "adjacent lines" if window else "line", "text": text}


@lru_cache(maxsize=8192)
def _bigram(first: str, second: str, author: str) -> dict | None:
    """Two words printed side by side in the corpus: the poet's passage first, with the number of passages."""
    rows = latin_backend._db().execute(
        "SELECT p.author, p.citation FROM passage_fts f JOIN passages p ON p.id=f.id WHERE passage_fts MATCH ? "
        "AND p.kind='text' LIMIT 200", (f'normalized : "{first} {second}"',)).fetchall()
    if not rows:
        return None
    cites = sorted({(r["author"] != author, r["author"], r["citation"]) for r in rows})
    return {"author": cites[0][1], "citation": cites[0][2], "passages": len(cites),
            "in_author": sum(1 for c in cites if not c[0])}


@lru_cache(maxsize=8)
def collocation_baseline(author: str = "Catullus", metre_name: str = "phalaecian") -> dict:
    """The poet's own poems in the metre, each held out: the share of its content-word pairs (same windows) that
    stand together in another poem of the poet or in another indexed poet. The warning threshold of L5 is the 10th
    percentile of these shares; drafts with fewer pairs than the smallest poem are not judged."""
    lines = _metre_lines(author, metre_name)
    index = {a: _pair_index(a) for a in _authors()}
    own = _corpus(author)["lines"]
    by_poem = defaultdict(set)
    position = {id(l): i for i, l in enumerate(own)}
    for line in lines:
        i = position[id(line)]
        for pair in combinations(line["content"], 2):
            by_poem[line["pid"]].add(pair)
        if i + 1 < len(own) and own[i + 1]["pid"] == line["pid"]:
            for a in line["content"]:
                for b in own[i + 1]["content"]:
                    if a != b:
                        by_poem[line["pid"]].add(tuple(sorted((a, b))))
    shares, sizes, found, total = [], [], 0, 0
    for pid, pairs in by_poem.items():
        hit = sum(1 for p in pairs if any(own[i]["pid"] != pid for _w, i in index[author].get(p, ()))
                  or any(p in index[a] for a in index if a != author))
        shares.append(hit / len(pairs))
        sizes.append(len(pairs))
        found += hit
        total += len(pairs)
    return {"author": author, "metre": metre_name, "poems": len(shares), "pairs": total, "with_parallel": found,
            "pooled": round(found / total, 3) if total else 0.0, "median": round(_quantile(shares, 0.5), 3),
            "p10": round(_quantile(shares, 0.1), 3), "min_pairs": min(sizes) if sizes else 0}


def _collocation(text: str, metre_name: str, author: str) -> dict:
    draft = read_draft(text, author)
    others = [a for a in _authors() if a != author]
    seen, rows = set(), []
    seen_alt, readings = set(), []                # pairs under a word's other lemma: shown, kept out of the share
    for i, line in enumerate(draft):
        here = [w for w in line["words"] if w["content"]]
        nxt = [w for w in draft[i + 1]["words"] if w["content"]] if i + 1 < len(draft) else []
        for window, a, b in [(0, a, b) for a, b in combinations(here, 2)] + [(1, a, b) for a in here for b in nxt]:
            key = tuple(sorted((a["lemma"], b["lemma"])))
            if a["lemma"] == b["lemma"] or key in seen:
                continue
            seen.add(key)
            row = {"pair": f"{a['lemma']} + {b['lemma']}", "forms": f"{a['form']} ... {b['form']}", "line": i + 1,
                   "window": "adjacent lines" if window else "line", "author": None, "count": 0, "same_line": 0, "loci": []}
            for poet in [author, *others]:
                hits = _pair_index(poet).get(key)
                if hits:
                    hits = sorted(hits)
                    row.update(author=poet, count=len(hits), same_line=sum(1 for w, _ in hits if w == 0),
                               loci=[_locus(poet, h) for h in hits[:LOCI]])
                    break
            rows.append(row)
            for la, ua in (a.get("candidates") or [(a["lemma"], a["upos"])]):
                for lb, ub in (b.get("candidates") or [(b["lemma"], b["upos"])]):
                    alt = tuple(sorted((la, lb)))
                    if alt == key or la == lb or alt in seen_alt or ua not in CONTENT_UPOS or ub not in CONTENT_UPOS:
                        continue
                    for poet in [author]:          # the poet only: the other lemma is asked of his lines
                        hits = sorted(_pair_index(poet).get(alt) or [])
                        if hits:
                            seen_alt.add(alt)
                            readings.append({"kind": "pair", "pair": f"{la} + {lb}", "forms": f"{a['form']} ... {b['form']}", "line": i + 1,
                                             "window": "adjacent lines" if window else "line", "author": poet, "count": len(hits),
                                             "same_line": sum(1 for w, _ in hits if w == 0), "loci": [_locus(poet, h) for h in hits[:LOCI]],
                                             "reading": ", ".join(f"{x['form']} read as {l}" for x, l in ((a, la), (b, lb)) if l != x["lemma"])})
                            break
    bigrams = []
    for i, line in enumerate(draft):
        for a, b in zip(line["words"], line["words"][1:]):
            hit = _bigram(a["normalized"], b["normalized"], author) if a["normalized"] and b["normalized"] else None
            bigrams.append({"words": f"{a['form']} {b['form']}", "line": i + 1, **(hit or {"author": None, "passages": 0})})
    in_poet = [r for r in rows if r["author"] == author]
    elsewhere = [r for r in rows if r["author"] and r["author"] != author]
    none = [r for r in rows if not r["author"]]
    printed = [b for b in bigrams if b["passages"]]
    base = collocation_baseline(author, metre_name)
    share = (len(in_poet) + len(elsewhere)) / len(rows) if rows else 0.0
    judged = bool(rows) and len(rows) >= base["min_pairs"] > 0
    ok = not (judged and share < base["p10"])
    parts = [f"{len(in_poet) + len(elsewhere)}/{len(rows)} content-word pairs have a parallel: {len(in_poet)} in {author} "
             f"({sum(1 for r in in_poet if r['same_line'])} within one line)"
             + "".join(f", {sum(1 for r in elsewhere if r['author'] == o)} only in {o}" for o in others)
             + (f"; without parallel: {', '.join(r['pair'] for r in none[:8])}" + (" ..." if len(none) > 8 else "") if none else "")]
    if readings:
        parts.append("under another reading: " + ", ".join(f"{r['pair']} ({r['reading']}; {r['author']} x{r['count']})" for r in readings[:6]))
    parts.append(f"{len(printed)}/{len(bigrams)} adjacent word pairs printed verbatim"
                 + (": " + ", ".join(f"{b['words']} ({b['author']} {b['citation']})" for b in printed[:6]) if printed else ""))
    if base["poems"]:
        parts.append(f"{author}'s own {base['poems']} poems in the metre, each held out: {round(100 * base['pooled'])}% of "
                     f"{base['pairs']} pairs recur (median poem {round(100 * base['median'])}%, 10th percentile "
                     f"{round(100 * base['p10'])}% = the warning line; draft {round(100 * share)}%"
                     + ("" if judged else f", not judged: fewer than {base['min_pairs']} pairs") + ")")
    if "Virgil" not in _authors():
        parts.append("Virgil is not in the lemma index")
    readings = [r for r in readings if tuple(sorted(r["pair"].split(" + "))) not in seen]
    evidence = ([{"kind": "pair", **r} for r in sorted(rows, key=lambda r: (r["author"] is not None, r["line"]))]
                + readings + [{"kind": "adjacent", **b} for b in bigrams] + [{"kind": "baseline", **base}])
    return {"id": "L5", "name": "collocation", "ok": ok, "blocking": False, "detail": "; ".join(parts), "evidence": evidence}


def check_collocation(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L5: content-word pairs and adjacent word pairs of the draft against the poet's lines. Never blocks."""
    if not available():
        return _unavailable("L5", "collocation", "the Latin corpus or the lemma index is not built")
    try:
        return _collocation(text, metre_name or "phalaecian", author or "Catullus")
    except Exception as exc:  # noqa: BLE001 - the contract: nothing raises
        return _unavailable("L5", "collocation", exc)


# ----------------------------------------------------------------------------------------------- L6 manner evidence

MARKERS = ("diminutives", "interjections", "vocatives", "second person", "repeated line openings",
           "repeated content lemmas", "run-on lines")
_SECOND = re.compile(r"Person(\[psor\])?=2")


def _marker_counts(lines: list[dict]) -> tuple[Counter, dict]:
    """(counts by marker, {marker: [the words or lines counted]}) over one poem's lines; a line is
    {text, toks: [(normalized, lemma, upos, feats)], printed}."""
    counts, words = Counter(), defaultdict(list)
    seen, previous = set(), None

    def add(marker, what):
        counts[marker] += 1
        words[marker].append(what)

    for line in lines:
        for n, lemma, upos, feats in line["toks"]:
            if upos in ("NOUN", "ADJ") and diminutive_info(lemma):
                add("diminutives", n)
            if upos == "INTJ":
                add("interjections", n)
            if "Case=Voc" in feats:
                add("vocatives", n)
            if _SECOND.search(feats):
                add("second person", n)
            if upos in CONTENT_UPOS and lemma:
                if lemma in seen:
                    add("repeated content lemmas", n)
                seen.add(lemma)
        first = line["toks"][0][0] if line["toks"] else None
        if first and first == previous:
            add("repeated line openings", first)
        previous = first
        if line.get("printed"):
            counts["printed lines"] += 1
            if line["text"].rstrip(" \"'”’)")[-1:] not in _PUNCT_END:
                add("run-on lines", line["text"][-24:])
    return counts, words


@lru_cache(maxsize=8)
def marker_profile(author: str = "Catullus", metre_name: str = "phalaecian") -> dict:
    """Each marker in the poet's poems of the metre: tokens, lines, rate per 100 lines, and the per-poem rates'
    10th percentile, median and 90th percentile. Counted from the lemma index's features and the printed text."""
    poems = defaultdict(list)
    for line in _metre_lines(author, metre_name):
        poems[line["pid"]].append(line)
    total, per_poem, n_lines = Counter(), defaultdict(list), 0
    for lines in poems.values():
        counts, _ = _marker_counts(lines)
        total.update(counts)
        n_lines += len(lines)
        for m in MARKERS:
            denom = counts["printed lines"] if m == "run-on lines" else len(lines)
            per_poem[m].append(_rate(counts[m], denom))
    out = {"author": author, "metre": metre_name, "poems": len(poems), "lines": n_lines, "markers": {}}
    for m in MARKERS:
        denom = total["printed lines"] if m == "run-on lines" else n_lines
        out["markers"][m] = {"count": total[m], "lines": denom, "per_100": _rate(total[m], denom),
                             "poem_p10": _quantile(per_poem[m], 0.1), "poem_median": _quantile(per_poem[m], 0.5),
                             "poem_p90": _quantile(per_poem[m], 0.9)}
    return out


def diminutives(author: str = "Catullus", metre_name: str = "phalaecian") -> list[tuple[str, str, int, str]]:
    """(lemma, base, tokens, how) of the diminutives counted in the poet's poems of the metre, commonest first;
    how = "Lewis & Short" or "by suffix" (see diminutive_info)."""
    c = Counter(lemma for line in _metre_lines(author, metre_name) for _n, lemma, upos, _f in line["toks"]
                if upos in ("NOUN", "ADJ") and diminutive_info(lemma))
    return [(lemma, diminutive_info(lemma)[0], n, diminutive_info(lemma)[1]) for lemma, n in c.most_common()]


def _place(counter: Counter, final: int, at: int | None) -> dict | None:
    n = sum(counter.values())
    if not n:
        return None
    start, k = counter.most_common(1)[0]
    return {"n": n, "usual_start": start, "at_usual_start": k, "line_final": final,
            "starts": {str(p): c for p, c in sorted(counter.items())},
            **({"at_draft_start": counter.get(at, 0)} if at else {})}


def _manner(text: str, metre_name: str, author: str) -> dict:
    draft = read_draft(text, author)
    counts = _lemma_counts(author, metre_name)
    others = {a: _lemma_counts(a, metre_name) for a in _authors() if a != author}
    groups = [g for g, _lo, _hi in BOOK_GROUPS.get(author, ())]
    home = groups[0] if groups else None           # the group holding the metre: the polymetrics for Catullus
    has_gold = gold_path().exists() and bool(_metre_poems(author, metre_name))
    pos = _positions(author, metre_name) if has_gold else None
    starts = _draft_starts(text)
    rows, absent, elsewhere, unread, alternatives = [], [], [], [], []
    for i, line in enumerate(draft):
        aligned = starts is not None and i < len(starts) and len(starts[i]) == len(line["words"])
        for k, w in enumerate(line["words"]):
            if not w["content"]:
                continue
            c = counts.get(w["lemma"], Counter())
            at = starts[i].get(k) if aligned else None
            row = {"kind": "word", "form": w["form"], "lemma": w["lemma"], "upos": w["upos"], "line": i + 1,
                   "start": at, "line_final": k == len(line["words"]) - 1,
                   "tokens": {**{g: c[g] for g in groups}, "in_metre": c["metre"], "total": c["total"]},
                   "other_poets": {a: o.get(w["lemma"], Counter())["total"] for a, o in others.items()},
                   "diminutive_of": None, "diminutive": None,
                   "position": None, "warning": None}
            dim = diminutive_info(w["lemma"]) if w["upos"] in ("NOUN", "ADJ") else None
            if dim:                                # "diminutive": Lewis & Short | by suffix
                row["diminutive_of"], row["diminutive"] = dim
            if pos is not None:
                row["position"] = {"form": _place(pos["form"].get(w["normalized"], Counter()), pos["form_final"][w["normalized"]], at),
                                   "lemma": _place(pos["lemma"].get(w["lemma"], Counter()), pos["lemma_final"][w["lemma"]], at)}
            if not w["read"]:
                row["warning"] = "no headword reading"
                unread.append(w["form"])
            elif not c["total"]:
                row["warning"] = f"lemma not in {author}" + "".join(f"; {a} {n}" for a, n in row["other_poets"].items() if n)
                absent.append(w["form"])
            elif home and not c[home]:
                row["warning"] = (f"lemma not in the {home}: " + ", ".join(f"{g} {c[g]}" for g in groups[1:] if c[g])
                                  + " (wrong register for the metre?)")
                elsewhere.append(f"{w['form']} ({', '.join(f'{g} {c[g]}' for g in groups[1:] if c[g])})")
            rows.append(row)
            alts = [(l, u) for l, u in (w.get("candidates") or [])[1:] if u in CONTENT_UPOS] if w["read"] else []
            if not alts:
                continue
            row["reading"] = (f"{w['lemma']} (agrees with the line)" if w.get("by_agreement") else w["lemma"]) \
                + "; also read as " + ", ".join(l for l, _u in alts)
            for lemma, upos in alts:               # the same evidence under each other lemma the poets use
                ca = counts.get(lemma, Counter())
                if not ca["total"] and not any(o.get(lemma, Counter())["total"] for o in others.values()):
                    continue
                alt = {"kind": "word", "form": w["form"], "lemma": lemma, "upos": upos, "line": i + 1, "start": at,
                       "line_final": row["line_final"], "alternative_to": w["lemma"],
                       "tokens": {**{g: ca[g] for g in groups}, "in_metre": ca["metre"], "total": ca["total"]},
                       "other_poets": {a: o.get(lemma, Counter())["total"] for a, o in others.items()},
                       "diminutive_of": None, "diminutive": None, "position": None, "warning": None}
                dim = diminutive_info(lemma) if upos in ("NOUN", "ADJ") else None
                if dim:
                    alt["diminutive_of"], alt["diminutive"] = dim
                if pos is not None:
                    alt["position"] = {"form": row["position"]["form"],
                                       "lemma": _place(pos["lemma"].get(lemma, Counter()), pos["lemma_final"][lemma], at)}
                alternatives.append(alt)
                if row["warning"] and (ca[home] if home else ca["total"]):     # one reading is at home: no warning
                    row["warning"] = None
                    for bucket in (absent, elsewhere):
                        if bucket and bucket[-1].split(" (")[0] == w["form"]:
                            bucket.pop()
    two = [r for r in rows if r.get("reading")]
    n_lines = len(draft)
    toks = [{"text": l["text"], "printed": any(ch in _PUNCT_END for l2 in draft for ch in l2["text"]),
             "toks": [(w["normalized"], w["lemma"], w["upos"], w["feats"]) for w in l["words"]]} for l in draft]
    mine, mine_words = _marker_counts(toks)
    profile = marker_profile(author, metre_name) if has_gold else None
    markers = []
    for m in MARKERS:
        denom = mine["printed lines"] if m == "run-on lines" else n_lines
        ref = profile["markers"][m] if profile else None
        markers.append({"kind": "marker", "marker": m, "draft": mine[m] if denom else None, "draft_lines": denom,
                        "draft_per_100": _rate(mine[m], denom) if denom else None, "draft_words": mine_words[m][:12],
                        "poet_per_100": ref and ref["per_100"], "poet_count": ref and ref["count"], "poet_lines": ref and ref["lines"],
                        "poet_poem_p10_median_p90": ref and [ref["poem_p10"], ref["poem_median"], ref["poem_p90"]]})
    for m in markers:
        if m["marker"] == "diminutives":
            m["note"] = "a diminutive is a lemma Lewis & Short marks dim. (by suffix only where it has no entry); puella is not one"
    label = home or author
    parts = [f"{len(rows)} content words: {len(rows) - len(absent) - len(elsewhere) - len(unread)} with a lemma in "
             f"{author}'s {label}" if home else f"{len(rows)} content words: {len(rows) - len(absent) - len(unread)} with a lemma in {author}"]
    if elsewhere:
        parts.append(f"in {author} but not in the {home}: " + ", ".join(elsewhere))
    if absent:
        parts.append(f"not in {author}: " + ", ".join(absent))
    if unread:
        parts.append("no headword reading: " + ", ".join(unread))
    if two:
        parts.append("more than one lemma: " + ", ".join(
            f"{r['form']} = " + " / ".join(f"{a['lemma']} ({label} {a['tokens'][home] if home else a['tokens']['total']})"
                                           for a in [r] + [x for x in alternatives if x["line"] == r["line"] and x["form"] == r["form"]])
            for r in two[:6]))
    if pos is not None:
        placed = [r for r in rows if r["position"]["lemma"] and r["start"]]
        usual = [r for r in placed if r["position"]["lemma"]["at_draft_start"]]
        parts.append(f"{len(usual)}/{len(placed)} of the words {author} uses in the metre start at a syllable where he "
                     f"starts the lemma" + ("; never there: " + ", ".join(f"{r['form']} (draft {r['start']}, his usual "
                                           f"{r['position']['lemma']['usual_start']})" for r in placed if r not in usual) if len(usual) < len(placed) else ""))
    else:
        parts.append(f"no hand-scanned lines of {author} in {metre_name}: positions not counted")
    for m in markers:
        if m["poet_per_100"] is not None and m["draft"] is not None:
            parts.append(f"{m['marker']} {m['draft']} in {m['draft_lines']} lines ({m['draft_per_100']} per 100; {author} "
                         f"{m['poet_per_100']} per 100 over {m['poet_lines']} lines)")
    return {"id": "L6", "name": "manner evidence", "ok": not (absent or elsewhere), "blocking": False,
            "detail": "; ".join(parts), "evidence": rows + alternatives + markers}


def check_manner(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L6: where each content word's lemma stands in the poet (groups of the book, the metre, the place in the
    line) and the countable markers of the manner against the draft. Never blocks."""
    if not available():
        return _unavailable("L6", "manner evidence", "the Latin corpus or the lemma index is not built")
    try:
        return _manner(text, metre_name or "phalaecian", author or "Catullus")
    except Exception as exc:  # noqa: BLE001 - the contract: nothing raises
        return _unavailable("L6", "manner evidence", exc)
