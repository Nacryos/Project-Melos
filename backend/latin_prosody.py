"""L12 prosody attestation: each word's quantities as a line uses them, against where the poets put the same form.

Reader over data/scansion/prosody_la.sqlite (scripts/build_prosody_index_la.py; docs/latin/prosody-attestation.md): one
row per word token of the Hypotactic hand scansion (David Chamberlain, CC BY 4.0; Catullus, Virgil, Horace's lyrics)
with the weight the hand scansion gives each syllable and the context that tells nature from position. A line is
scanned by the Latin scanner against the metre, the weight the fit gives each syllable is mapped to its word, and each
word gets a verdict:

  confirmed         every compared syllable has this weight for this form in the chosen poet (loci shown)
  confirmed-virgil  the same, but only in Virgil (confirmed-other: only in another reference poet, e.g. Horace)
  variant           the form is attested with both weights on a syllable (mute + liquid, final -o, iambic shortening,
                    homographs: counts each way per poet, and which way this line takes), or the line takes the
                    lengthening before mute + liquid that the rule allows but this form does not show
  conflict          the form is attested at least MIN_CONFLICT times, never with this weight on a syllable whose weight
                    does not hang on the context, and it is not one of two words spelt alike: the blocking case
  stem              the form is not in the gold; other forms of its lemma (backend/latin_lemma.py) that share the stem
                    syllables scan the same way
  unattested        nothing to compare: the quantity rests on the lexicon alone (a warning)
  lexicon-conflict  stem or unattested, and a non-final syllable's weight goes against the quantity lexicon the scanner
                    reads (a long vowel used short, a short open syllable used long): blocking while LEXICON_BLOCKS

A non-final syllable's weight belongs to the word (vowel nature, or position made inside the word), so every token is
evidence for it. A final syllable is compared only in like context (before a vowel, before one consonant, before a
cluster, elided); at line end it is anceps and tells nothing. Nothing here raises; without the index the check returns
ok True with a detail beginning "unavailable:".
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path

from .scansion.latin import VOWELS, key as la_key

ENCLITICS = ("que", "ne", "ue")
VIRGIL = ("vergil", "virgil")
MCL = re.compile(r"^[bcdgkptf]h?[lr]$")          # stop (or f) + liquid: backend/scansion/latin.py MCL_FIRST / LIQUIDS
LOCI = 3
LICENCES = ("lengthening", "diastole", "systole", "hiatus", "semihiatus")   # syllable marks of the hand scansion
MIN_CONFLICT = 1    # tokens of the form, all the other way, that block: 0 false conflicts in 2,774 at N = 1, 2 and 3 (see the doc)
LEXICON_BLOCKS = True    # lexicon-conflict blocks: it fires on 2 of 2,774 genuine tokens (0.07 %, under the 0.5 % bar; see the doc)
REFERENCE = ("Catullus", "Vergil")               # the two poets every mute + liquid count is given for
_local = threading.local()


def index_path() -> Path:
    if os.environ.get("MELOS_PROSODY_LA"):
        return Path(os.environ["MELOS_PROSODY_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "scansion" / "prosody_la.sqlite"


def available() -> bool:
    return index_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(index_path()):
        db = sqlite3.connect(f"file:{index_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        _local.db, _local.path = db, str(index_path())
    return db


# ------------------------------------------------------------------------------ letters and contexts (shared with the builder)

def fold(form: str) -> str:
    """The scanner's lookup key (lower case, u for v, i for j, no marks) without punctuation."""
    return "".join(ch for ch in la_key(form) if ch.isalpha())


def bare(form: str) -> str:
    """Lower-case letters without marks; a written v or j is kept (the gold writes v for the consonant)."""
    t = unicodedata.normalize("NFD", form or "").lower()
    return "".join(ch for ch in t if ch.isascii() and ch.isalpha())


def first_vowel(syllable: str) -> int:
    """Index of the syllable's nucleus in its bare letters (qu's u and an initial i / u before a vowel are consonants)."""
    b = bare(syllable)
    for i, ch in enumerate(b):
        if ch not in VOWELS:
            continue
        if ch == "u" and i > 0 and b[i - 1] == "q":
            continue
        if i == 0 and ch in "iu" and len(b) > 1 and b[1] in VOWELS and b[1] != ch:
            continue
        return i
    return 0


def initial_class(word: str) -> str:
    """How a word begins, for the syllable before it: V (vowel or h), C (one consonant), ML (mute + liquid), CC (cluster)."""
    b = bare(word)
    if not b or b.startswith("h"):
        return "V"
    k = first_vowel(b)
    onset = b[:k].replace("qu", "q")
    if not onset:
        return "V"
    if len(onset) == 1:
        return "CC" if onset in "xz" else "C"
    return "ML" if MCL.match(onset) else "CC"


def final_open(form: str) -> bool:
    return fold(form)[-1:] in VOWELS


def context_group(open_final: bool, ctx: str) -> str:
    """Final syllables are compared within one group: END, E (elided), V, C (a closed final before any consonant; an open
    final before one consonant or mute + liquid), CC (an open final before a cluster that makes position)."""
    if ctx in ("END", "E", "V"):
        return ctx
    return "C" if (not open_final or ctx in ("C", "ML")) else "CC"


def mcl_after(syllables: list[str]) -> list[int]:
    """Indices of the syllables whose vowel stands directly before mute + liquid inside the word (pa-tris, la-cri-ma)."""
    out = []
    for i in range(len(syllables) - 1):
        a, b = bare(syllables[i]), bare(syllables[i + 1])
        tail = a[first_vowel(a) + 1:].lstrip("aeiouy")
        if MCL.match(tail + b[:first_vowel(b)]):
            out.append(i)
    return out


# ------------------------------------------------------------------------------ the index

@lru_cache(maxsize=32768)
def _tokens_cached(path: str, key: str) -> tuple:
    rows = _db().execute("SELECT t.author, t.locus, t.line_id, t.form, t.nsyl, t.pat, t.final_ctx, t.final_open, t.mcl, "
                         "t.vpos, t.flags, t.synizesis, t.prodelision, l.text FROM tokens t JOIN lines l ON l.line_id = t.line_id WHERE t.key=?", (key,))
    return tuple(dict(r) | {"mcl": json.loads(r["mcl"]), "vpos": json.loads(r["vpos"])} for r in rows)


def _tokens(key: str, exclude: frozenset = frozenset()) -> list[dict]:
    rows = _tokens_cached(str(index_path()), key)
    return [r for r in rows if r["line_id"] not in exclude] if exclude else list(rows)


def _poet_order(author: str):
    a = (author or "").lower()
    return lambda poet: (0 if poet.lower() == a else 1 if poet.lower() in VIRGIL else 2, poet)


def _loci(tokens: list[dict], author: str, n: int = LOCI) -> list[dict]:
    order = _poet_order(author)
    seen, out = set(), []
    for t in sorted(tokens, key=lambda t: order(t["author"])):
        if t["line_id"] in seen:
            continue
        seen.add(t["line_id"])
        out.append({"locus": t["locus"], "text": t["text"], "form": t["form"], "pattern": t["pat"]})
        if len(out) == n:
            break
    return out


def _count(tokens) -> dict:
    out: dict[str, int] = {}
    for t in tokens:
        out[t["author"]] = out.get(t["author"], 0) + 1
    return out


def attested(form: str, author: str = "") -> dict:
    """Every distinct quantity pattern of a form in the gold: counts per poet and up to 3 loci each (with the line).
    Patterns are one letter per syllable: L long, S short, E elided. `author` restricts the evidence to one poet."""
    key = fold(form)
    out = {"form": form, "key": key, "available": available(), "tokens": 0, "patterns": []}
    if not key or not available():
        return out
    try:
        toks = [t for t in _tokens(key) if not author or t["author"].lower() == author.lower()]
    except Exception as exc:                                       # a damaged index is reported, never raised
        return out | {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    groups: dict[str, list[dict]] = {}
    for t in toks:
        groups.setdefault(t["pat"], []).append(t)
    out["tokens"] = len(toks)
    for pat, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        ctx: dict[str, int] = {}
        for t in ts:
            ctx[t["final_ctx"]] = ctx.get(t["final_ctx"], 0) + 1
        out["patterns"].append({"pattern": pat, "count": len(ts), "per_poet": _count(ts), "final_contexts": ctx,
                                "loci": _loci(ts, author)})
    return out


# ------------------------------------------------------------------------------ one word against the gold

def _cause(key: str, i: int, n: int, mcl: bool, toks: list[dict]) -> str:
    """Why a syllable has both weights: named from the form's shape and the hand scansion's own licence marks."""
    marked = lambda t: sorted(f.split(":", 1)[1] for f in t["flags"].split() if f.startswith(f"{i}:") and f.split(":", 1)[1] in LICENCES)
    for side in "LS":
        ts = [t for t in toks if t["pat"][i] == side]
        if ts and all(marked(t) for t in ts):
            return "licence marked in the hand scansion: " + ", ".join(sorted({f for t in ts for f in marked(t)}))
    if mcl:
        return "mute + liquid"
    if i == n - 1:
        if key.endswith("o"):
            return "final -o"
        if key.endswith("a"):
            return "final -a (short nominative / neuter plural, long ablative)"
        if n == 2 and key[-1:] in VOWELS and any(t["pat"][:1] == "S" for t in toks):
            return "iambic shortening"
        if key.endswith(("is", "us", "es", "os", "as")) or key[-1:] in VOWELS:
            return "ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i)"
        return "final syllable in like context (hic / hoc, homograph endings)"
    if key.endswith("ius") and i == n - 2:
        return "genitive -ius"
    if key.endswith(("erunt", "erimus", "eritis")) and i == n - (2 if key.endswith("erunt") else 3):
        return "perfect -erunt / -erimus"
    return "homograph (different words or tenses spelt alike)"


@lru_cache(maxsize=8192)
def _readings(key: str, letter: int) -> dict:
    """{"L": [lemmas], "S": [lemmas], "source"} when one source of the quantity lexicon gives this spelling two readings
    that differ on this vowel (lēvis / lĕvis, vēnit / vĕnit); {} otherwise. A row that leaves the vowel open (A, u) is
    no reading, and a proper-noun lemma is passed over (Matrae does not make mătris a word)."""
    try:
        from .scansion.lexicon_la import LatinQuantityLexicon
        by_source: dict[str, dict] = {}
        lex = LatinQuantityLexicon()
        rows = lex.rows(key) or [r for e in ENCLITICS if key.endswith(e) and len(key) > len(e) + 1 for r in lex.rows(key[: -len(e)])]
        for source, marks, lemma in rows:
            side = {"L": "L", "S": "S", "s": "S"}.get(marks[letter]) if 0 <= letter < len(marks) else None
            if side and not lemma[:1].isupper():
                by_source.setdefault(source, {"L": [], "S": []})[side].append(lemma)
        for source, r in by_source.items():
            if r["L"] and r["S"]:
                return {"L": sorted(set(r["L"])), "S": sorted(set(r["S"])), "source": source}
    except Exception:
        pass
    return {}


def _each_way(tokens, i: int) -> dict:
    """Long / short counts of syllable i, for Catullus and Virgil always and for any other poet that has it."""
    out = {p: {"long": 0, "short": 0} for p in REFERENCE}
    for t in tokens:
        if i < len(t["pat"]) and t["pat"][i] in "LS":
            out.setdefault(t["author"], {"long": 0, "short": 0})["long" if t["pat"][i] == "L" else "short"] += 1
    return out


def _ways(d: dict) -> str:
    return ", ".join(f"{p} long {c['long']} / short {c['short']}" for p, c in d.items())


def _lemma_tokens(key: str, exclude: frozenset) -> tuple[list[str], list[tuple[dict, int]]]:
    """Tokens of the other forms of the word's lemma(s), each with the number of leading syllables it shares with the
    word (same letters up to the next syllable's vowel: pa- of patris / patrem / patre)."""
    try:
        from . import latin_lemma
        lemmas = [r["lemma"] for r in latin_lemma.readings(key)][:3]
    except Exception:
        lemmas = []
    if not lemmas:
        return [], []
    marks = ",".join("?" * len(lemmas))
    keys = [r[0] for r in _db().execute(f"SELECT DISTINCT key FROM lemmas WHERE lemma IN ({marks}) AND key != ?", (*lemmas, key))]
    out = []
    for k in keys[:400]:
        common = 0
        while common < min(len(k), len(key)) and k[common] == key[common]:
            common += 1
        for t in _tokens(k, exclude):
            m = 0
            for i in range(t["nsyl"] - 1):
                nxt = t["vpos"][i + 1]
                if not (common >= nxt and len(key) > nxt and key[nxt] in VOWELS):
                    break
                m += 1
            if m:
                out.append((t, m))
    return lemmas, out


def _synizesis(toks: list[dict], n: int, author: str) -> dict | None:
    """What the hand scansion's synizesis marks say of the form: counts and loci with and without, and which this line takes."""
    syn = [t for t in toks if t["synizesis"]]
    if not syn:
        return None
    plain = [t for t in toks if not t["synizesis"]]
    here = "with" if any(t["nsyl"] == n for t in syn) else "without" if any(t["nsyl"] == n for t in plain) else "neither"
    return {"here": here, "with": {"per_poet": _count(syn), "syllables": sorted({t["nsyl"] for t in syn}), "loci": _loci(syn, author, 2)},
            "without": {"per_poet": _count(plain), "syllables": sorted({t["nsyl"] for t in plain}), "loci": _loci(plain, author, 2)}}


def _evaluate(key: str, weights: str, group: str, line_final: bool, mcl: list[int], author: str, exclude: frozenset,
              skip_final: bool = False, vidx: list[int] | None = None) -> dict | None:
    """Compare a word's weights (L / S / E per syllable) with its tokens in the gold; None when the form is not there."""
    toks = _tokens(key, exclude)
    if not toks:
        return None
    n = len(weights)
    same_n = [t for t in toks if t["nsyl"] == n]
    order = _poet_order(author)
    syn = _synizesis(toks, n, author)
    if not same_n:
        counts = sorted({t["nsyl"] for t in toks})
        why = ("the poets take it with synizesis there" if syn and not syn["without"]["per_poet"] and n > counts[-1] else
               "this line takes a synizesis the hand scansion never marks for the form" if n < counts[0] else "synizesis or a different division")
        return {"verdict": "variant", "syllables": [], "per_poet": _count(toks), "loci": _loci(toks, author),
                "note": f"scanned here as {n} syllable(s); the gold has it with {', '.join(map(str, counts))} ({why})"} | ({"synizesis": syn} if syn else {})
    syllables, agree = [], list(same_n)
    for i, w in enumerate(weights):
        final = i == n - 1
        if w not in "LS":
            continue                                                # elided or undecided: nothing to compare
        if final and (line_final or skip_final):
            continue                                                # anceps at line end; the host's final before an enclitic
        pool = [t for t in same_n if t["pat"][i] in "LS"]
        if final:
            pool = [t for t in pool if context_group(bool(t["final_open"]), t["final_ctx"]) == group]
        if not pool:
            continue
        same = [t for t in pool if t["pat"][i] == w]
        other = [t for t in pool if t["pat"][i] != w]
        agree = [t for t in agree if t in same or t not in pool]
        read = _readings(key, vidx[i]) if vidx and i < len(vidx) and not (same and not other) else {}
        ml = None
        if i in mcl and not final:                                  # a vowel before mute + liquid: counts each way, per poet
            ml = {"form": _each_way(pool, i)}
            if not (same and other):                                # the form shows one weight only: pool the lemma's other forms
                lemmas, lt = _lemma_tokens(key, exclude)
                st = [t for t, m in lt if m > i and t["pat"][i] in "LS"]
                if st:
                    ml |= {"stem": _each_way(st, i), "lemmas": lemmas, "stem_forms": sorted({fold(t["form"]) for t in st})[:6]}
            short = any(c["short"] for part in ("form", "stem") for c in ml.get(part, {}).values()) or w == "S"
            if not short:
                ml = None                                           # never short in the gold: long by nature, no variation to show
        if same and not other:
            status = "ok"
        elif same:
            status = "variant"
        elif i in mcl and w == "L":
            status = "licensed"                                     # lengthening before mute + liquid: allowed by rule
        elif final and w == "S" and key.endswith("o"):
            status = "licensed"                                     # final -o shortened (dabo, Catullus 13.11)
        elif read:
            status = "homograph"                                    # two words spelt alike; the poets' tokens are all the other one
        elif ml and any(c["short"] for c in ml.get("stem", {}).values()):
            status = "licensed"                                     # short before mute + liquid in other forms of the lemma
        elif len([t for t in other if not any(f.split(":", 1)[1] in LICENCES for f in t["flags"].split() if f.startswith(f"{i}:"))]) >= MIN_CONFLICT:
            status = "conflict"                                     # tokens the hand scansion marks as a licence there do not count
        else:
            status = "thin"                                         # the other way, but on fewer tokens than it takes to block
        entry = {"syllable": i + 1, "weight": w, "status": status, "same": _count(same), "other": _count(other)}
        if ml:
            entry["mute_liquid"] = ml
        if status != "ok":
            entry["cause"] = ("mute + liquid" if ml else "homograph" if read else _cause(key, i, n, i in mcl, pool))
            entry["same_loci"] = _loci(same, author, 2)
            entry["other_loci"] = _loci(other, author, 2)
            if read:                                                # name both words and where each stands
                entry["readings"] = [{"lemmas": read[side], "weight": side, "per_poet": _count(ts), "loci": _loci(ts, author, 2)}
                                     for side, ts in ((w, same), ("S" if w == "L" else "L", other))]
        syllables.append(entry)
    statuses = {s["status"] for s in syllables}
    poets = [set(s["same"]) for s in syllables]
    a = (author or "").lower()
    if "conflict" in statuses:
        verdict = "conflict"
    elif statuses & {"variant", "licensed", "homograph", "thin"}:
        verdict = "variant"
    elif not syllables:
        present = {t["author"].lower() for t in toks}
        verdict = "confirmed" if a in present or not a else "confirmed-virgil" if present & set(VIRGIL) else "confirmed-other"
    elif all(any(p.lower() == a for p in ps) for ps in poets) or not a:
        verdict = "confirmed"
    elif all(any(p.lower() == a or p.lower() in VIRGIL for p in ps) for ps in poets):
        verdict = "confirmed-virgil"
    else:
        verdict = "confirmed-other"
    out = {"verdict": verdict, "syllables": syllables, "per_poet": dict(sorted(_count(toks).items(), key=lambda kv: order(kv[0]))),
           "loci": _loci(agree or same_n, author)}
    if not syllables:
        out["note"] = "attested; no syllable to compare (final syllable without a like context, elided or at line end)"
    if syn and syn["here"] != "neither" and syn["with"]["per_poet"] and syn["without"]["per_poet"]:
        out["synizesis"] = syn                                      # the poets take the form both ways: show it, never block on it
        if verdict.startswith("confirmed"):
            out["verdict"] = "variant"
        out["note"] = (f"taken {syn['here']} synizesis here; the hand scansion has it with synizesis "
                       f"{sum(syn['with']['per_poet'].values())} time(s) (e.g. {syn['with']['loci'][0]['locus']}), without "
                       f"{sum(syn['without']['per_poet'].values())} (e.g. {syn['without']['loci'][0]['locus']})")
    return out


def _stem(key: str, weights: str, author: str, exclude: frozenset, mcl: list[int] | None = None) -> dict | None:
    """Forms of the same lemma in the gold that share the word's leading syllables (same letters up to the next vowel)."""
    lemmas, lt = _lemma_tokens(key, exclude)
    if not lemmas:
        return None
    n, same, other, blank, mcl = len(weights), [], [], [], mcl or []
    for t, m in lt:
        shared, differs = 0, False
        for i in range(min(m, n - 1)):
            if t["pat"][i] in "LS" and weights[i] in "LS":           # an anceps place (l / s) is passed over, not compared
                if i in mcl:
                    continue                                        # before mute + liquid both weights are right: counted below
                shared += 1
                differs = differs or t["pat"][i] != weights[i]
            else:
                blank.append(t)                                     # shares stem letters, but the metre fixes nothing there
        if shared:
            (other if differs else same).append((shared, t))
    ml = []
    for i in mcl:                                                   # the form is not in the gold: pool the stem's counts
        st = [t for t, m in lt if m > i and i < n - 1 and t["pat"][i] in "LS"]
        if st and weights[i] in "LS":
            ml.append({"syllable": i + 1, "weight": weights[i], "status": "pooled", "cause": "mute + liquid", "same": {}, "other": {},
                       "mute_liquid": {"form": _each_way([], i), "stem": _each_way(st, i), "lemmas": lemmas,
                                       "stem_forms": sorted({fold(t["form"]) for t in st})[:6]},
                       "same_loci": _loci([t for t in st if t["pat"][i] == weights[i]], author, 2),
                       "other_loci": _loci([t for t in st if t["pat"][i] != weights[i]], author, 2)})
    if ml:
        st = [t for t, m in lt if any(m > e["syllable"] - 1 for e in ml)]
        both = any(sum(c["long"] for c in e["mute_liquid"]["stem"].values()) and sum(c["short"] for c in e["mute_liquid"]["stem"].values()) for e in ml)
        took = all(e["same_loci"] or e["weight"] == "L" for e in ml)     # long before mute + liquid is right by rule
        if took and not other:
            return {"verdict": "variant" if both else "stem", "lemmas": lemmas, "syllables": ml, "per_poet": _count(st), "loci": _loci(st, author),
                    "note": f"not in the gold; mute + liquid counts pooled over the stem forms of {', '.join(lemmas)} "
                            f"({', '.join(ml[0]['mute_liquid']['stem_forms'])})"}
        if not took:
            return {"verdict": "unattested", "lemmas": lemmas, "syllables": ml, "per_poet": _count(st), "loci": _loci(st, author),
                    "note": f"not in the gold; the stem forms of {', '.join(lemmas)} never have the vowel before mute + liquid short: check the quantity"}
    if not same and not other:
        if not blank:
            return None
        return {"verdict": "stem", "lemmas": lemmas, "syllables_shared": 0, "per_poet": _count(blank), "loci": _loci(blank, author),
                "note": f"not in the gold; forms of {', '.join(lemmas)} are, but the shared stem syllables stand where the metre "
                        "fixes no weight (anceps or elided): nothing to compare"}
    best = max((s for s, _ in same), default=0)
    ts = [t for s, t in sorted(same, key=lambda st: -st[0])]
    if same:
        return {"verdict": "stem", "lemmas": lemmas, "syllables_shared": best, "per_poet": _count(ts), "loci": _loci([t for s, t in same if s == best], author),
                "note": f"not in the gold; {len(same)} token(s) of {', '.join(lemmas)} agree on {best} shared stem syllable(s)"
                        + (f"; {len(other)} token(s) of other stems of the lemma differ" if other else "")}
    ot = [t for _, t in other]
    return {"verdict": "unattested", "lemmas": lemmas, "per_poet": _count(ot), "loci": _loci(ot, author),
            "note": f"not in the gold; forms of {', '.join(lemmas)} that share the stem letters scan differently ({len(other)} token(s)): check the quantity"}


def _lexicon_conflicts(key: str, weights: str, vidx: list[int] | None, shape: list[str] | None, mcl: list[int]) -> list[dict]:
    """Syllables whose weight in the line goes against the quantity lexicon the scanner reads: a vowel it marks long
    used short, or a short vowel in an open syllable used long (not before mute + liquid). The final syllable is left
    out: its weight hangs on the next word. A vowel the lexicon leaves open or records both ways is no evidence."""
    out = []
    try:
        from .scansion.lexicon_la import LatinQuantityLexicon
        lex = LatinQuantityLexicon()
        if not lex.available or not vidx:
            return out
        for i, w in enumerate(weights[:-1]):
            if w not in "LS" or i >= len(vidx) or vidx[i] < 0:
                continue
            q, src = lex.vowel_evidence(key, vidx[i])
            if (q == "L" and w == "S") or (q == "S" and w == "L" and i not in mcl and shape and i < len(shape) and shape[i] == "open"):
                out.append({"syllable": i + 1, "weight": w, "lexicon": q, "sources": src})
    except Exception:
        pass
    return out


def _word(form: str, weights: str, ctx: str, line_final: bool, mcl: list[int], author: str, exclude: frozenset,
          vidx: list[int] | None = None, prodelision: str = "", shape: list[str] | None = None) -> dict:
    """Verdict for one word. `weights`: L / S where the metre fixes the weight, l / s at an anceps place (shown, not
    compared), E elided, ? undecided. `vidx`: the key's letter index of each syllable's vowel (for the lexicon)."""
    key = fold(form)
    group = context_group(final_open(form), "E" if weights.endswith("E") else ctx)
    res = _evaluate(key, weights, group, line_final, mcl, author, exclude, skip_final=prodelision == "before", vidx=vidx)
    if res is not None and prodelision:                             # -a est / -um est: the hand scansion writes the junction as elision
        ts = [t for t in _tokens(key, exclude) if t["prodelision"]]
        res["prodelision"] = {"role": prodelision, "per_poet": _count(ts), "loci": _loci(ts, author, 2)}
        res["note"] = ((res.get("note", "") + "; ") if res.get("note") else "") + (
            f"before est / es (prodelision): the final syllable is not compared; the form stands so {len(ts)} time(s) in the gold"
            if prodelision == "before" else f"est / es after a vowel or -m (prodelision): so {len(ts)} time(s) in the gold")
    if res is None:
        for e in ENCLITICS:
            if key.endswith(e) and len(key) > len(e) + 1 and len(weights) > 1:
                res = _evaluate(key[: -len(e)], weights[:-1], "", False, mcl, author, exclude, skip_final=True, vidx=vidx)
                if res is not None:
                    res["note"] = f"as {key[: -len(e)]} + -{e}; the syllable before the enclitic is not compared"
                    break
    if res is None:
        res = _stem(key, weights, author, exclude, mcl)
    if res is None:
        res = {"verdict": "unattested", "syllables": [], "per_poet": {}, "loci": [],
               "note": "not in the gold (Catullus, Virgil, Horace's lyrics), nor any form of its lemma sharing the stem: the quantity rests on the lexicon alone"}
    lc = _lexicon_conflicts(key, weights, vidx, shape, mcl)
    if lc:
        res["lexicon_disagrees"] = lc                               # kept on every row; it decides only where the gold is silent
        if res["verdict"] in ("stem", "unattested"):
            res["verdict"] = "lexicon-conflict"
    return {"word": form, "key": key, "weights": weights, "final_context": "E" if weights.endswith("E") else ctx, **res}


# ------------------------------------------------------------------------------ the check

def _line_words(scanner, line: str, metre_name: str, k: int) -> tuple[list[dict], bool]:
    """[{form, weights, ctx, line_final, mcl}] for one line, with the weight the metre's fit gives every syllable."""
    from .scansion import metre
    from .scansion.syllabify_la import words_of
    units = scanner.scan(line)
    wobj = {w.index: w for w in words_of(line, spelling=scanner.spelling)}
    words = {i: w.text for i, w in wobj.items()}
    weight = {}
    fits = False
    if metre_name in metre.TEMPLATES:
        temps = metre.TEMPLATES[metre_name]
        f = metre.fit_line(units, metre_name, temps[k % len(temps)])
        fits = bool(f.ok)
        for a in f.assignment:
            for j, idx in enumerate(a["syllables"]):
                w = a["weight"].lower() if a.get("symbol") in ("x", "F") else a["weight"]   # anceps: the metre asks nothing
                weight[idx] = w if j == 0 else ""                 # synizesis: the merged unit has no syllable of its own
    per: dict[int, dict] = {}
    for u in units:
        w = weight.get(u.index, {"L": "l", "S": "s", "E": "E"}.get(u.label, "?") if not weight else "?")   # no parse: the scanner's own, not compared
        d = per.setdefault(u.word, {"weights": "", "mcl": [], "vidx": [], "prod": False, "open": [], "onset": [], "nucleus": []})
        d["prod"] = d["prod"] or bool(getattr(u, "prodelision", False))
        if w == "":
            continue
        tail = u.text[max(0, u.nend - u.start):]
        if tail and not tail[:1].isspace() and " " not in tail and MCL.match(bare(tail)):
            d["mcl"].append(len(d["weights"]))
        d["weights"] += w
        d["open"].append(not bare(tail))
        d["onset"].append(bare(u.text[: max(0, u.nstart - u.start)]))
        d["nucleus"].append(bare(u.text[max(0, u.nstart - u.start): max(0, u.nend - u.start)]))
        d["vidx"].append(len(fold(line[wobj[u.word].start:u.nstart])) if u.word in wobj else -1)
    order = sorted(per)
    out = []
    for j, wi in enumerate(order):
        nxt = words.get(order[j + 1]) if j + 1 < len(order) else None
        prod = "before" if per[wi]["prod"] else "self" if j and per[order[j - 1]]["prod"] else ""   # the scanner marks the unit before est / es
        on = per[wi]["onset"][1:] + [""]
        shape = ["open" if o and len(n_) == 1 and len(nx.replace("qu", "q")) == 1 and nx not in ("x", "z", "i") else ""
                 for o, n_, nx in zip(per[wi]["open"], per[wi]["nucleus"], on)]
        out.append({"form": words.get(wi, ""), "weights": per[wi]["weights"], "ctx": initial_class(nxt) if nxt else "END",
                    "line_final": nxt is None, "mcl": per[wi]["mcl"], "vidx": per[wi]["vidx"], "prodelision": prod, "shape": shape})
    return out, fits


def _describe(e: dict) -> str:
    bits = []
    each = lambda d: ", ".join(f"{p} {c}" for p, c in d.items()) or "never"
    eg = lambda xs: f", e.g. {xs[0]['locus']}" if xs else ""
    for s in e.get("syllables", []):
        w = "long" if s["weight"] == "L" else "short"
        ml = s.get("mute_liquid")
        mls = ""
        if ml:
            mls = f"mute + liquid: {e['key']} {_ways(ml['form'])}"
            if ml.get("stem"):
                mls += f"; pooled over the stem ({', '.join(ml['stem_forms'])}) {_ways(ml['stem'])}"
        if s["status"] == "ok":
            if ml:
                bits.append(f"syllable {s['syllable']} {w} here before {mls}")
        elif s["status"] == "pooled":
            bits.append(f"syllable {s['syllable']} {w} here; the form is not in the gold; {mls}")
        elif s["status"] == "conflict":
            bits.append(f"syllable {s['syllable']} is {w} here, but the other way in every like place ({each(s['other'])})" + eg(s.get("other_loci"))
                        + (f" [{mls}]" if ml else ""))
        elif s["status"] == "thin":
            bits.append(f"syllable {s['syllable']} is {w} here; the gold has it only the other way, {each(s['other'])}{eg(s.get('other_loci'))}: "
                        f"fewer than the {MIN_CONFLICT} tokens it takes to block, check the quantity")
        elif s.get("readings"):
            a, b = s["readings"]
            name = lambda r: f"{' / '.join(r['lemmas'])} ({'long' if r['weight'] == 'L' else 'short'}: {each(r['per_poet'])}{eg(r['loci'])})"
            bits.append(f"syllable {s['syllable']} {w} here: the spelling {e['key']} has two readings, {name(a)} and {name(b)}; which is meant?")
        elif s["status"] == "licensed":
            bits.append(f"syllable {s['syllable']} {w} here by rule ({mls or s['cause']}); the form itself is attested only the other way ({each(s['other'])})")
        else:
            bits.append(f"syllable {s['syllable']} {w} here ({each(s['same'])}); the other way {each(s['other'])}: {mls or s['cause']}")
    if e["verdict"] == "lexicon-conflict":
        for s in e["lexicon_disagrees"]:
            bits.append(f"syllable {s['syllable']} is {'long' if s['weight'] == 'L' else 'short'} here, but the quantity lexicon marks the vowel "
                        f"{'long' if s['lexicon'] == 'L' else 'short'} (source: {s['sources']}); the poets do not have the form to settle it")
    note = e.get("note", "")
    return f"{e['word']} [{e['weights']}]: " + ("; ".join(bits + ([note] if note and (not bits or e.get("synizesis") or e.get("prodelision")) else [])) or e["verdict"])


def check(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus", _exclude: frozenset = frozenset()) -> dict:
    """L12 for one or more lines. Blocking; ok is False only when a word has a conflict (or a lexicon-conflict)."""
    out = {"id": "L12", "name": "prosody attestation", "ok": True, "blocking": True, "detail": "", "evidence": []}
    try:
        if not available():
            return out | {"detail": f"unavailable: prosody index not built ({index_path().name}; scripts/build_prosody_index_la.py)"}
        from .scansion import api as scan_api
        scanner = scan_api._scanner(None, True, "none", "la")
        tally: dict[str, int] = {}
        notes = []
        for k, line in enumerate(ln for ln in (text or "").split("\n") if ln.strip()):
            words, fits = _line_words(scanner, line, metre_name, k)
            for w in words:
                if not w["form"] or not w["weights"]:
                    continue
                e = _word(w["form"], w["weights"], w["ctx"], w["line_final"], w["mcl"], author, _exclude, w["vidx"], w["prodelision"], w["shape"])
                e["line"] = k + 1
                if not fits:
                    e["metre"] = "the line does not fit the metre (L7)"
                tally[e["verdict"]] = tally.get(e["verdict"], 0) + 1
                out["evidence"].append(e)
                if e["verdict"] in ("conflict", "lexicon-conflict", "variant", "unattested"):
                    notes.append((e["verdict"], _describe(e)))
                elif any(s.get("mute_liquid") for s in e.get("syllables", [])) or e.get("prodelision"):
                    notes.append(("note", _describe(e)))            # no warning: the references, each time the variation comes up
        order = ["conflict", "lexicon-conflict", "variant", "unattested", "note"]
        notes.sort(key=lambda n: order.index(n[0]))
        summary = ", ".join(f"{v} {tally[v]}" for v in ("confirmed", "confirmed-virgil", "confirmed-other", "variant", "stem",
                                                         "unattested", "lexicon-conflict", "conflict") if tally.get(v))
        out["ok"] = not tally.get("conflict") and not (LEXICON_BLOCKS and tally.get("lexicon-conflict"))
        out["counts"] = tally
        out["detail"] = (summary or "no words") + "".join(f" | {v}: {d}" for v, d in notes)
        return out
    except Exception as exc:                                       # the contract: nothing raises
        return out | {"ok": True, "detail": f"unavailable: {type(exc).__name__}: {exc}", "evidence": []}
