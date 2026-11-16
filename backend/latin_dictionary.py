"""Reader over the Lewis & Short store data/lexica/lewis_short_la.sqlite (scripts/build_dictionary_la.py;
docs/latin/dictionary.md) and check L14 "period and register".

lookup: a headword or an inflected form (through backend.latin_lemma.readings) -> entries with senses, usage labels,
authors cited and the Catullus citations with their sense. reverse: English -> headwords ranked by how well a sense
gloss matches (the primary sense counts double), with Catullus's and Horace's use of the lemma. check (L14): for each
word of a draft, warn when Lewis & Short labels the word post-classical, post-Augustan, late or ecclesiastical, or
cites for it no author active before A.D. 14 (data/open/latin/lewis-short/authors.json, L&S's own list of authors);
note poetic and ante-classical labels and the places L&S cites from the target author. A late label on an entry that
cites classical-period authors qualifies a form or a sense, so it is a note; a word the target author is cited for,
or whose lemma stands in his text (lemma index), never warns. Advisory: it never blocks, and a missing store returns ok with "unavailable:".
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from .latin_text import normalize_la, tokenize_la

_local = threading.local()
LATE = ("post-class.", "post-Aug.", "late Lat.", "eccl. Lat.")       # labels that warn
NOTED = ("ante-class.", "poet.", "rare", "very rare", "jurid. Lat.")  # labels that are reported only
AUTHOR_ABBR = {"catullus": "Cat.", "horace": "Hor.", "virgil": "Verg.", "vergil": "Verg."}
CLASSICAL_FROM = -85    # an author dated from Sulla's time on counts as classical-period (Cicero, Lucretius, Catullus ...)
ENCLITICS = ("que", "ne", "ue")
# Prefix spellings: LASLA and the editions print the unassimilated prefix, L&S often the assimilated one (or the reverse).
ASSIMILATION = (("adc", "acc"), ("adf", "aff"), ("adg", "agg"), ("adl", "all"), ("adn", "ann"), ("adp", "app"),
                ("adr", "arr"), ("ads", "ass"), ("adt", "att"), ("conl", "coll"), ("conm", "comm"), ("conr", "corr"),
                ("conp", "comp"), ("conb", "comb"), ("inl", "ill"), ("inm", "imm"), ("inr", "irr"), ("inp", "imp"),
                ("inb", "imb"), ("obc", "occ"), ("obf", "off"), ("obp", "opp"), ("subc", "succ"), ("subf", "suff"),
                ("subm", "summ"), ("subp", "supp"), ("subr", "surr"), ("exs", "ex"), ("ecf", "eff"))


def db_path() -> Path:
    if os.environ.get("MELOS_DICTIONARY_LA"):
        return Path(os.environ["MELOS_DICTIONARY_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "lexica" / "lewis_short_la.sqlite"


def available() -> bool:
    return db_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(db_path()):
        db = sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        _local.db, _local.path = db, str(db_path())
    return db


@lru_cache(maxsize=4)
def _authors(path: str) -> dict[str, dict]:
    """abbreviation -> {name, year, kind, before_ad14}; an abbreviation two authors share is before A.D. 14 only if both are."""
    out: dict[str, dict] = {}
    for r in _db().execute("SELECT abbr, name, kind, year, before_ad14 FROM authors ORDER BY abbr, year"):
        cur = out.get(r["abbr"])
        row = {"name": r["name"], "kind": r["kind"], "year": r["year"],
               "before_ad14": None if r["before_ad14"] is None else bool(r["before_ad14"])}
        if cur is None:
            out[r["abbr"]] = row
        elif row["before_ad14"] is False or cur["before_ad14"] is None:
            out[r["abbr"]] = {**row, "name": cur["name"] + " / " + row["name"]}
    return out


def authors() -> dict[str, dict]:
    return _authors(str(db_path())) if available() else {}


def fold(word: str) -> str:
    return re.sub(r"[^a-z]", "", normalize_la(word))


def _spellings(key: str) -> list[str]:
    out = [key]
    for a, b in ASSIMILATION:
        for x, y in ((a, b), (b, a)):
            if key.startswith(x):
                out.append(y + key[len(x):])
    return out


def _entry_ids(key: str) -> list[int]:
    for k in _spellings(key):
        rows = _db().execute("SELECT entry_id FROM forms WHERE folded=? ORDER BY main DESC, entry_id", (k,)).fetchall()
        if rows:
            return [r["entry_id"] for r in rows]
    return []


def _date(abbr: str, table: dict) -> str:
    a = table.get(abbr) or {}
    if a.get("year") is None:
        return abbr
    y = a["year"]
    return f"{abbr} ({'ob.' if a['kind'] == 'ob' else 'fl.'} {'B.C.' if y < 0 else 'A.D.'} {abs(y)})"


def period(entry: dict) -> dict:
    """What an entry says about period: late and noted labels, the dated authors cited, how many of them wrote
    before A.D. 14, and the earliest."""
    table = authors()
    dated = [(table[a]["year"], a) for a in entry["authors"] if table.get(a, {}).get("year") is not None]
    early = [a for a in entry["authors"] if table.get(a, {}).get("before_ad14")]
    return {"late": [x for x in entry["labels"] if x in LATE], "noted": [x for x in entry["labels"] if x in NOTED],
            "dated_authors": len(dated), "authors_before_ad14": early,
            "classical_authors": [a for a in early if table[a]["year"] >= CLASSICAL_FROM],
            "earliest": _date(min(dated)[1], table) if dated else "", "undated_only": bool(entry["authors"]) and not dated}


@lru_cache(maxsize=4096)
def _entry(entry_id: int, target: str = "Cat.") -> dict:
    db = _db()
    e = db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    senses, gloss_of, last = [], {}, ""
    for s in db.execute("SELECT * FROM senses WHERE entry_id=? ORDER BY ord", (entry_id,)):
        last = s["glosses"] or last
        gloss_of[s["id"]] = (s["n"], last)
        senses.append({"ord": s["ord"], "level": s["level"], "n": s["n"], "labels": json.loads(s["labels"]),
                       "glosses": s["glosses"], "translations": s["trans"], "text": s["text"]})
    cited = [{"author": c["author"], "work": c["work"], "locus": c["locus"], "quote": c["quote"],
              "sense": gloss_of.get(c["sense_id"], ("", ""))[0], "gloss": gloss_of.get(c["sense_id"], ("", ""))[1]}
             for c in db.execute("SELECT * FROM citations WHERE entry_id=? AND author=?", (entry_id, target))]
    out = {"id": e["id"], "headword": e["headword"], "key": e["key"], "folded": e["folded"], "type": e["type"],
           "pos": e["pos"], "gender": e["gender"], "inflection": e["itype"], "head": e["head"],
           "labels": json.loads(e["labels"]), "authors": json.loads(e["authors"]), "citations": e["n_citations"],
           "senses": senses, "catullus" if target == "Cat." else "target_citations": cited, "text": e["text"]}
    out["period"] = period(out)
    return out


def lookup(word: str) -> list[dict]:
    """Entries for a headword or an inflected form: the headword's own entries first, then those of each lemma the
    form can be read as. Each entry: headword, grammar, labels, authors cited (counts), senses, Catullus citations
    with their sense, and `how` (headword, or the lemma the form was resolved through). [] when nothing is found
    or the store is missing."""
    if not available():
        return []
    key = fold(word)
    if not key:
        return []
    found: list[tuple[int, str]] = [(i, "headword") for i in _entry_ids(key)]
    from . import latin_lemma
    try:
        reads = latin_lemma.readings(word)
    except Exception:  # noqa: BLE001 - the lemma index is optional here
        reads = []
    for r in reads[:4]:
        lem = fold(r["lemma"])
        if lem and lem != key:
            found.extend((i, f"form of {lem} ({r['source']})") for i in _entry_ids(lem))
    out, seen = [], set()
    for i, how in found:
        if i not in seen:
            seen.add(i)
            out.append({**_entry(i), "how": how})
    return out


def _attested(lemma: str) -> tuple[int, int]:
    from . import latin_lemma
    try:
        by = latin_lemma.lemma_attestation(lemma).get("by_author", {})
    except Exception:  # noqa: BLE001
        return 0, 0
    return by.get("Catullus", {}).get("tokens", 0), by.get("Horace", {}).get("tokens", 0)


def _plain(gloss: str) -> str:
    return re.sub(r"^(?:to|a|an|the)\s+", "", re.sub(r"[^a-z' -]", "", gloss.lower()).strip())


ENGLISH_STOP = frozenset("""a an the and or but nor so yet for of to in on at by with from into out up down off over under
as is are was were be been being am do does did done have has had having i me my mine we us our you your yours he him
his she her hers it its they them their this that these those who whom whose which what when where why how if than then
there here not no o oh may might shall should will would can could must let now even also too very more most much many
all any some each every one such own same just only still ever never once thus while though because since until
whether either neither both nor again away about after before between through upon without within""".split())


def english_stem(word: str) -> str:
    """A light stem: kisses, kissed, kissing -> kiss; trifles, trifling -> trifl; joke, joking -> jok."""
    w = re.sub(r"'s$|[^a-z]", "", word.lower())
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "ches", "shes", "xes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def english_stems(text: str) -> list[str]:
    """Stems of the content words of an English line or query."""
    return [s for s in (english_stem(w) for w in re.findall(r"[A-Za-z']+", text) if w.lower() not in ENGLISH_STOP) if len(s) > 1]


def _interlinear(english: str) -> dict[str, dict]:
    """lemma -> {count, g2, loci, locus, latin, english}: Latin lemmas that stand in the same line as the query's
    words in the audited literal English of Catullus (table `interlinear`, built by scripts/build_dictionary_la.py)."""
    stems = english_stems(english)
    if not stems:
        return {}
    try:
        rows = _db().execute(f"SELECT * FROM interlinear WHERE stem IN ({','.join('?' * len(stems))}) ORDER BY g2 DESC", stems).fetchall()
    except sqlite3.Error:      # a store built before the table existed
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.get(r["lemma"])
        if cur is None:
            out[r["lemma"]] = {"count": r["k"], "g2": r["g2"], "rank": r["rank"], "loci": r["loci"], "locus": f"{r['poem']}.{r['line']}",
                               "latin": r["latin"], "english": r["english"], "_stems": {r["stem"]}}
        else:
            cur["g2"], cur["rank"] = round(cur["g2"] + r["g2"], 2), min(cur["rank"], r["rank"])
            cur["_stems"].add(r["stem"])
    need = len(set(stems))
    return {lem: {k: v for k, v in d.items() if k != "_stems"} for lem, d in out.items() if len(d["_stems"]) == need}


def reverse(english: str, limit: int = 20) -> list[dict]:
    """English -> Latin headwords from two sources, each row saying which found it (`sources`): Lewis & Short's
    glosses (`lewis-short`) and the audited literal English of Catullus (`catullus-interlinear`: the lemma stands in
    the same line as the English word more often than chance; `interlinear` gives count, G2, loci and the first
    line in Latin and English). Order: words both sources give (strongest Catullan association first), then
    Catullus's own words that L&S glosses otherwise (two lines or more, the lemma's own strongest English word, G2 >= 10.83, five at most), then L&S's other
    headwords. A Catullan hit is a co-occurrence, so a neighbour in the same lines can intrude: read the line given."""
    if not available():
        return []
    ls = _reverse_ls(english, max(limit * 3, 200))
    cat = _interlinear(english)
    table = authors()
    both, only_cat, only_ls = [], [], []
    for r in ls:
        hit = cat.pop(r["lemma"], None)
        if hit:
            both.append({**r, "sources": ["lewis-short", "catullus-interlinear"], "interlinear": hit})
        else:
            only_ls.append({**r, "sources": ["lewis-short"], "interlinear": None})
    for lem, hit in sorted(cat.items(), key=lambda kv: -kv[1]["g2"]):
        if hit["g2"] < 10.83 or len(only_cat) >= 5:
            break
        if hit["count"] < 2 or hit["rank"] > 1:    # without L&S's agreement: two lines, and the lemma's own best English
            continue
        es = [_entry(i) for i in _entry_ids(fold(lem))]
        e = min(es, key=lambda x: (x["folded"] != fold(lem), x["folded"][-2:] != fold(lem)[-2:], -x["citations"])) if es else None
        if e and any(o["headword"] == e["headword"] for o in both + only_cat):
            continue
        c, h = _attested(lem)
        only_cat.append({"headword": e["headword"] if e else lem, "lemma": lem, "pos": e["pos"] if e else "",
                         "gender": e["gender"] if e else "", "inflection": e["inflection"] if e else "",
                         "match": "catullus line", "score": 0.0,
                         "sense": {"n": "", "glosses": next((s["glosses"] for s in e["senses"] if s["glosses"]), "") if e else "",
                                   "translations": ""},
                         "labels": e["labels"] if e else [], "late": bool(e and e["period"]["late"]),
                         "before_ad14": bool(e and e["period"]["authors_before_ad14"]) if e else True,
                         "catullus": c, "horace": h, "cites_catullus": e["authors"].get("Cat.", 0) if e else 0,
                         "sources": ["catullus-interlinear"], "interlinear": hit})
    both.sort(key=lambda d: (d["_tier"] == 2 and d["interlinear"]["rank"] > 2, -d["interlinear"]["g2"]))
    out = both + only_cat + only_ls
    for d in out:
        d.pop("_tier", None)
    return out[:limit]


def _reverse_ls(english: str, limit: int = 20) -> list[dict]:
    """English -> Latin headwords in three tiers: a gloss equal to the query in the entry's primary (first glossed)
    sense; an equal gloss in a later sense or a gloss containing the query in the primary sense; anything else
    (by match score). Inside the first two tiers the lemma Catullus uses most comes first, then Horace. Each row:
    headword, grammar, match tier, the matching sense, labels, late (bool), catullus and horace token counts."""
    if not available():
        return []
    words = re.findall(r"[a-z']+", english.lower())
    query = _plain(" ".join(words))
    terms = [w for w in words if w not in ("to", "a", "an", "the")] or words
    if not terms:
        return []
    match = "{glosses trans} : (" + " AND ".join('"' + t.replace('"', "") + '"' for t in terms) + ")"
    try:
        rows = _db().execute(
            "SELECT s.id, s.entry_id, s.ord, s.level, s.n, s.glosses, s.trans, e.headword, e.folded, e.pos, e.gender, e.itype,"
            " e.labels, e.n_citations, e.authors,"
            " (SELECT MIN(ord) FROM senses p WHERE p.entry_id=s.entry_id AND p.glosses<>'') AS first_ord"
            " FROM sense_fts f JOIN senses s ON s.id=f.rowid JOIN entries e ON e.id=s.entry_id"
            " WHERE sense_fts MATCH ? ORDER BY bm25(sense_fts, 0.0, 10.0, 1.0) LIMIT 3000", (match,)).fetchall()
    except sqlite3.Error:
        return []
    stem = re.compile(r"\b" + r"\W+".join(re.escape(t[:max(3, len(t) - 2)]) + r"\w*" for t in terms) + r"\b")
    best: dict[int, dict] = {}
    for r in rows:
        score = 0.0
        for k, item in enumerate(r["glosses"].split("; ")):
            g = _plain(item)
            if not g:
                continue
            if g == query or g in (query + "s", query + "ing") or g + "s" == query:
                fit = 3.0
            elif stem.search(g):
                fit = 1.5 * min(1.0, len(terms) / len(g.split()))
            else:
                continue
            score = max(score, fit * (1.0 if k == 0 else 0.85))
        if not score:
            score = 0.3 if stem.search(r["trans"].lower()) else 0.1
        primary = r["ord"] == r["first_ord"]
        exact = score >= 2.5
        tier = 0 if exact and primary else 1 if exact or (primary and score >= 0.75) else 2
        score = score * (2.0 if primary else 1.0 if r["level"] <= 1 else 0.7) + 0.15 * math.log10(1 + r["n_citations"])
        cur = best.get(r["entry_id"])
        if cur is None or (tier, -score) < (cur["tier"], -cur["score"]):
            best[r["entry_id"]] = {"score": score, "row": r, "primary": primary, "tier": tier}
    table = authors()
    out = []
    for b in sorted(best.values(), key=lambda b: (b["tier"], -b["score"]))[:max(limit * 6, 60)]:
        r = b["row"]
        labels = json.loads(r["labels"])
        cited = json.loads(r["authors"])
        cat, hor = _attested(r["folded"])
        out.append({"headword": r["headword"], "lemma": r["folded"], "pos": r["pos"], "gender": r["gender"],
                    "inflection": r["itype"], "match": ("primary sense", "sense", "phrase")[b["tier"]], "score": round(b["score"], 2),
                    "sense": {"n": r["n"], "glosses": r["glosses"], "translations": r["trans"][:200]},
                    "labels": labels, "late": any(x in LATE for x in labels),
                    "before_ad14": any(table.get(a, {}).get("before_ad14") for a in cited),
                    "catullus": cat, "horace": hor, "cites_catullus": cited.get("Cat.", 0), "_tier": b["tier"]})
    out.sort(key=lambda d: (d["_tier"], -d["catullus"], -d["horace"], -d["score"]) if d["_tier"] < 2 else (2, -d["score"]))
    return out[:limit]


def _candidates(word: str) -> list[tuple[str, list[dict]]]:
    """[(lemma, entries)] for a word of a draft: each reading that has an entry, else the spelling as a headword,
    else the same with an enclitic taken off."""
    from . import latin_lemma
    for w in (word, *(word[:-len(e)] for e in ENCLITICS if len(word) > len(e) + 2 and fold(word).endswith(e))):
        try:
            reads = latin_lemma.readings(w)
        except Exception:  # noqa: BLE001
            reads = []
        out, seen = [], set()
        for lem in [fold(r["lemma"]) for r in reads[:3]] + [fold(w)]:
            if lem and lem not in seen:
                seen.add(lem)
                ids = _entry_ids(lem)
                if ids and (out == [] or lem != fold(w)):
                    out.append((lem, ids))
        if out:
            return out
    return []


def _judge(entry: dict, target: str) -> tuple[str, str]:
    """(status, reason) for one entry: warn / note / ok."""
    p = entry["period"]
    loci = entry.get("catullus") if target == "Cat." else entry.get("target_citations")
    cites_target = bool(loci) or target in entry["authors"]
    why, soft = [], []
    if p["late"] and not p["classical_authors"]:
        why.append("labelled " + ", ".join(p["late"]))
        if p["authors_before_ad14"]:
            why.append("before A.D. 14 only in " + ", ".join(p["authors_before_ad14"][:4]))
    elif p["late"]:      # the label qualifies a form, a sense or a construction: classical authors are cited
        soft.append("labelled " + ", ".join(p["late"]) + " in part (cited from " + ", ".join(p["classical_authors"][:3]) + ")")
    if p["dated_authors"] and not p["authors_before_ad14"]:
        why.append(f"no author before A.D. 14 (earliest {p['earliest']})")
    if why and not cites_target:
        return "warn", "; ".join(why)
    notes = why + soft
    if p["noted"]:
        notes.append(", ".join(p["noted"]))
    if p["undated_only"]:
        notes.append("only undated sources (" + ", ".join(entry["authors"]) + ")")
    if not entry["authors"]:
        notes.append("entry cites no author")
    if loci:
        places = "; ".join((c["work"] + " " + c["locus"]).strip() for c in loci[:4])
        gloss = next((c["gloss"] for c in loci if c["gloss"]), "")
        notes.append(f"{target} {places}" + (f" ('{gloss.split('; ')[0]}')" if gloss else ""))
    return ("note", "; ".join(notes)) if notes else ("ok", "")


def word_report(word: str, author: str = "Catullus", *, corpus: bool = True, proper: bool = False) -> dict:
    """One word of a draft against the dictionary: status warn / note / ok / no entry, with the entry judged. With
    `corpus`, a lemma the target author's own text holds (lemma index) is never a warning, whatever L&S cites."""
    target = AUTHOR_ABBR.get(author.lower(), "Cat.")
    cands = _candidates(word)
    row = {"word": word, "status": "no entry", "lemma": "", "headword": "", "labels": [], "reason": ""}
    if not cands:
        return row
    judged = []
    for lem, ids in cands:
        per = [(_judge(e, target), e) for e in (_entry(i, target) for i in ids)]
        # a lemma is as good as its best homograph: one that does not warn, then the one citing the author, then the fullest
        (status, reason), e = min(per, key=lambda x: (x[0][0] == "warn", target not in x[1]["authors"], -x[1]["citations"]))
        judged.append((status, reason, lem, e))
    status, reason, lem, e = judged[0]
    if status == "warn" and any(j[0] != "warn" for j in judged[1:]):      # another reading of the form is unobjectionable
        other = next(j for j in judged[1:] if j[0] != "warn")
        status, reason = "note", f"as {lem}: {reason}; unobjectionable as {other[2]}"
    if status == "warn" and proper:       # a name: L&S cites names thinly, and Marce is not marcus 'a hammer'
        status, reason = "note", f"capitalised, read as a name; the period rule is not applied ({e['headword']}: {reason})"
    held = 0
    if corpus:
        from . import latin_lemma
        try:
            held = latin_lemma.lemma_attestation(lem, author).get("author_tokens") or 0
        except Exception:  # noqa: BLE001
            held = 0
        if status == "warn" and held:
            status, reason = "note", f"{reason}; but {author} has the lemma {held} time{'s' if held > 1 else ''}"
    p = e["period"]
    loci = e.get("catullus") if target == "Cat." else e.get("target_citations")
    return {"word": word, "in_author": held, "status": status, "lemma": lem, "headword": e["headword"], "labels": e["labels"], "reason": reason,
            "authors_before_ad14": len(p["authors_before_ad14"]), "earliest": p["earliest"],
            "cited": [(c["work"] + " " + c["locus"]).strip() for c in (loci or [])][:8]}


def check(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L14 period and register (never blocks): ok is False when a word warns; evidence has one row per distinct word."""
    base = {"id": "L14", "name": "period and register", "ok": True, "blocking": False, "detail": "", "evidence": []}
    try:
        if not available():
            return {**base, "detail": f"unavailable: {db_path().name} not built (scripts/build_dictionary_la.py)"}
        rows, seen = [], set()
        for line in str(text or "").splitlines():
            for j, w in enumerate(tokenize_la(line)):
                k = normalize_la(w)
                if k and k not in seen:
                    seen.add(k)
                    rows.append(word_report(w, author or "Catullus", proper=j > 0 and w[:1].isupper()))
        warn = [r for r in rows if r["status"] == "warn"]
        note = [r for r in rows if r["status"] == "note"]
        missing = [r["word"] for r in rows if r["status"] == "no entry"]
        parts = [f"{len(warn)} of {len(rows)} words warn" if warn else f"no period warning in {len(rows)} words"]
        parts += [f"{r['word']} ({r['headword']}): {r['reason']}" for r in warn]
        if note:
            parts.append("notes: " + " | ".join(f"{r['word']}: {r['reason']}" for r in note[:12]))
        if missing:
            parts.append("no entry: " + ", ".join(missing[:20]))
        return {**base, "ok": not warn, "detail": "; ".join(parts), "evidence": rows}
    except Exception as exc:  # noqa: BLE001 - the contract: nothing raises
        return {**base, "detail": f"unavailable: {type(exc).__name__}: {exc}"}


def status() -> dict:
    if not available():
        return {"available": False}
    row = _db().execute("SELECT value FROM metadata WHERE key='build'").fetchone()
    return {"available": True, **(json.loads(row["value"]) if row else {})}
