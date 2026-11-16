"""Deterministic Latin grammar checks from morphological readings: L3 agreement and L10 word order
(docs/prd/catullan-hendecasyllable-checks.md; docs/latin/grammar-check.md for sources, counts and false-alarm rates).

The draft is read as sentences (split at . ; ? ! :), since a sentence runs over line ends. Every word takes all its
readings from backend.latin_morph.analyses; a rule passes when ANY combination of readings satisfies it, so this is a
net for plain blunders (*cum puellam*, *bonus puella*, *ego venit*), not a parser. L3 rules: (a) a word no source
reads; (b) a preposition with no word in a case it governs within its phrase (anastrophe and postposed -cum allowed);
(c) an adjective or participle that agrees with no noun or pronoun of its sentence; (d) a nominative with no finite
verb that can agree with it in number and person; (e) a relative pronoun with no possible antecedent in the draft.
L10 rules: a postpositive first in its sentence; -que / -ne / -ve on a host that reads (and told apart from atque,
neque, quoque, which read as words); a preposition last in its sentence. Lists and allowances that can be counted are
counted from the corpus by scripts/build_morph_la.py and quoted in the message. Neither check blocks; rules whose
measured false-alarm rate on Catullus's own hendecasyllables is above about 2 % of lines are notes (NOTE_ONLY).
Where a rule passes only on a reading that is not the form's commonest in LASLA's tags (Catullus, then Horace), or on
a noun far from an adjective whose neighbour it cannot agree with, a 'confirm' note says so and ok stays True.
"""
from __future__ import annotations

import re
from functools import lru_cache

from . import latin_morph
from .latin_text import normalize_la

_TOKEN = re.compile(r"[.;?!:]|[A-Za-zÀ-ɏḀ-ỿ]+(?:['’][A-Za-z]+)?")
# Allen & Greenough §§220-221: the case each preposition governs.
ACCUSATIVE = ("ad aduersus aduersum ante apud circa circum circiter cis citra contra erga extra infra inter intra iuxta ob "
              "penes per pone post praeter prope propter secundum supra trans ultra uersus").split()
ABLATIVE = "a ab abs absque coram cum de e ex prae pro sine palam".split()
EITHER = "in sub subter super clam".split()
GOVERNS = {**{p: ("acc",) for p in ACCUSATIVE}, **{p: ("abl",) for p in ABLATIVE}, **{p: ("acc", "abl") for p in EITHER},
           "tenus": ("abl", "gen")}
ADVERBIAL = set("ante post contra circum circa circiter prope iuxta supra infra extra intra ultra citra coram palam clam "
                "subter super aduersus aduersum pone propter uersus secundum".split())   # also stand alone as adverbs (A&G §219)
POSTPOSITIVE_CANDIDATES = ("enim", "autem", "uero", "quoque", "quidem", "igitur")     # A&G §599; kept when never first
NOMINAL = {"NOUN", "PROPN", "PRON", "NUM"}
FINITE = {"ind", "subj", "imp"}
PERSON = {"ego": "1", "nos": "1", "tu": "2", "uos": "2"}
WINDOW_AFTER, WINDOW_BEFORE = 5, 2
MIN_TOP_TOKENS, MIN_TOP_SHARE = 5, 0.8     # a 'confirm' note needs the commonest reading to have this many tokens and this share
FAR_GAP = 4                                # ... and a far-partner note needs the agreeing noun at least this many words off
POS_NAME = {"NOUN": "noun", "ADJ": "adjective", "PRON": "pronoun", "VERB": "verb", "ADP": "preposition", "CONJ": "conjunction",
            "ADV": "adverb", "NUM": "numeral", "INTJ": "interjection", "PART": "particle"}
CASE_NAME = {"nom": "nominative", "gen": "genitive", "dat": "dative", "acc": "accusative", "abl": "ablative",
             "voc": "vocative", "loc": "locative"}
MOOD_NAME = {"ind": "indicative", "subj": "subjunctive", "imp": "imperative", "inf": "infinitive", "part": "participle",
             "gerund": "gerund", "gerundive": "gerundive", "supine": "supine"}
_CLASS = {"DET": "ADJ", "PROPN": "NOUN", "AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}
_GROUP = {"NOUN": "N", "ADJ": "N", "PRON": "N", "NUM": "N"}      # one word used as noun or adjective is one reading
NOTE_ONLY: set[str] = set()          # rules demoted to notes after measurement (docs/latin/grammar-check.md): none needed


def _result(check_id: str, name: str, ok: bool, detail: str, evidence: list) -> dict:
    return {"id": check_id, "name": name, "ok": ok, "blocking": False, "detail": detail, "evidence": evidence}


def _unavailable(check_id: str, name: str, why: str) -> dict:
    return _result(check_id, name, True, f"unavailable: {why}", [])


def sentences(text: str) -> list[dict]:
    """[{words: [{form, key, line, readings}], end: '.'|'?'|...|''}] for a draft; line numbers start at 1."""
    out, cur = [], []
    for n, line in enumerate(str(text or "").splitlines(), 1):
        for m in _TOKEN.finditer(line):
            tok = m.group(0)
            if tok in ".;?!:":
                if cur:
                    out.append({"words": cur, "end": tok})
                    cur = []
                continue
            reads = latin_morph.analyses(tok)
            own = [r for r in reads if not r.get("enclitic")]
            cur.append({"form": tok, "key": normalize_la(tok), "line": n, "readings": own or reads})
    if cur:
        out.append({"words": cur, "end": ""})
    return out


def _adjectival(r: dict) -> bool:
    return bool(r["case"]) and (r["pos"] in ("ADJ", "DET") or (r["pos"] == "VERB" and r["mood"] in ("part", "gerundive")))


def _nominal(r: dict) -> bool:
    return r["pos"] in NOMINAL


def _finite(r: dict) -> bool:
    return r["pos"] == "VERB" and r["mood"] in FINITE and bool(r["person"])


def _show(word: dict, limit: int = 6) -> list[str]:
    seen = []
    for r in word["readings"]:
        s = " ".join(x for x in (r["lemma"], r["pos"], r["case"], r["number"], r["gender"], r["person"], r["tense"], r["mood"]) if x)
        if s not in seen:
            seen.append(s)
    return seen[:limit]


def _item(rule: str, word: dict, message: str, others: list[dict] = (), *, note: bool = False) -> dict:
    return {"rule": rule, "severity": "note" if note or rule in NOTE_ONLY else "fail", "word": word["form"], "line": word["line"],
            "message": message, "readings": _show(word), "against": {o["form"]: _show(o) for o in others}}


@lru_cache(maxsize=4)
def _lemma_counts(author: str) -> dict:
    from . import latin_lemma
    out: dict = {}
    for lemma, upos, n in latin_lemma._db().execute("SELECT lemma, upos, count FROM author_lemma WHERE author=?", (author,)):
        k = (normalize_la(lemma).rstrip("0123456789"), _CLASS.get(upos, upos))
        out.setdefault(k[0], {})[k] = out.get(k[0], {}).get(k, 0) + n
    return out


@lru_cache(maxsize=16384)
def reading_counts(key: str) -> tuple:
    """((label, {(lemma, pos): tokens}), ...) for a spelling from LASLA's tags in the lemma index, best evidence first:
    the spelling in Catullus, in Horace, then the lemmas it may belong to in Catullus, in Horace. Empty tiers are left out."""
    tiers = []
    try:
        from . import latin_lemma
        if not latin_lemma.available():
            return ()
        for author in ("Catullus", "Horace"):
            counts: dict = {}
            for lemma, upos, n in latin_lemma._db().execute(
                    "SELECT lemma, upos, COUNT(*) FROM token WHERE normalized=? AND author=? GROUP BY lemma, upos", (key, author)):
                if lemma in latin_morph.ENCLITICS and key != lemma and key.endswith(lemma):
                    continue
                k = (normalize_la(lemma).rstrip("0123456789"), _CLASS.get(upos, upos))
                counts[k] = counts.get(k, 0) + n
            tiers.append((author, counts))
        lemmas = {r["lemma"] for r in latin_morph.analyses(key) if not r.get("enclitic")}
        for author in ("Catullus", "Horace"):
            counts = {}
            for lemma in lemmas:
                counts.update(_lemma_counts(author).get(lemma, {}))
            tiers.append((f"{author}, all forms of the lemma", counts))
    except Exception:  # noqa: BLE001 - counts are evidence only
        pass
    return tuple(t for t in tiers if t[1])


def _same(reading: dict, counted: tuple) -> bool:
    cls = _CLASS.get(reading["pos"], reading["pos"])
    return reading["lemma"] == counted[0] and _GROUP.get(cls, cls) == _GROUP.get(counted[1], counted[1])


def _describe(r: dict, by_case: bool) -> str:
    cls = _CLASS.get(r["pos"], r["pos"])
    if cls in ("ADP", "CONJ", "ADV", "INTJ", "PART"):
        return f"the {POS_NAME[cls]}"
    if by_case and r["case"]:
        return f"the {CASE_NAME[r['case']]} of *{r['lemma']}*"
    if cls == "VERB":
        return f"the {MOOD_NAME[r['mood']]} of *{r['lemma']}*" if r["mood"] in MOOD_NAME else f"a form of the verb *{r['lemma']}*"
    return f"the {POS_NAME.get(cls, cls.lower())} *{r['lemma']}*"


def _confirm(w: dict, rescue: list[dict], *, subject: str = "", clause: str = "", by_case: bool = False,
             force: bool = False) -> dict | None:
    """A note that a rule passed only on a reading of w that is not the form's commonest one in Catullus (then Horace).
    force: the neighbouring words already make the reading doubtful, so the note is given whatever the counts say."""
    tiers = reading_counts(w["key"])
    if not rescue or not (tiers or force):
        return None
    strong = [(label, c) for label, c in tiers if max(c.values()) >= MIN_TOP_TOKENS]
    label, counts = (strong or tiers or [("", {})])[0]
    if not force:
        if not strong:
            return None
        top = max(counts, key=counts.get)
        if any(_same(r, top) for r in rescue) or counts[top] / sum(counts.values()) < MIN_TOP_SHARE:
            return None
    r = next((r for r in rescue if any(_same(r, k) for k in counts)), rescue[0])
    tally = ", ".join((POS_NAME.get(c, c.lower()) if lemma == w["key"] and c in ("ADP", "CONJ", "ADV") else
                       f"{POS_NAME.get(c, c.lower())} {lemma}") + f" {n}" for (lemma, c), n in sorted(counts.items(), key=lambda kv: -kv[1]))
    message = (f"{subject + ' ' if subject else ''}passes only if *{w['form']}* is {_describe(r, by_case)} "
               f"({label + ': ' + tally if counts else 'no LASLA tokens in Catullus or Horace'})")
    return {"rule": "confirm", "severity": "note", "word": w["form"], "line": w["line"],
            "message": message + (f"; {clause}" if clause else ""), "readings": _show(w), "against": {}}


def _preposition(words: list[dict], i: int) -> dict | None:
    w = words[i]
    cases = GOVERNS.get(w["key"])
    if not cases or not any(r["pos"] == "ADP" for r in w["readings"]):
        return None
    if w["key"] in ADVERBIAL:
        return None                                           # ante, post, contra ...: may stand as an adverb
    lo, hi = max(0, i - WINDOW_BEFORE), min(len(words), i + 1 + WINDOW_AFTER)
    governed: list[tuple[dict, list[dict]]] = []
    for j in list(range(i + 1, hi)) + list(range(lo, i)):
        x = words[j]
        if not x["readings"]:
            return None                                       # an unread word (a name): cannot judge
        if any(r["pos"] in ("NOUN", "PROPN", "NUM") and not r["case"] for r in x["readings"]):
            return None                                       # indeclinable
        ok = [r for r in x["readings"] if r["case"] in cases and (_nominal(r) or _adjectival(r) or r["mood"] == "gerund")]
        if ok:
            governed.append((x, ok))
    clause = w["key"] == "cum" and any(_finite(r) for x in words[i + 1:] for r in x["readings"])
    if governed:
        if clause:
            return None                                       # cum has a case to govern and a verb to introduce
        notes = [_confirm(x, ok, subject=f"*{w['form']}*", by_case=True) for x, ok in governed]
        return notes[0] if all(notes) else None               # every governed word leans on a rare reading
    if clause:
        nxt = words[i + 1]                                    # cum the conjunction, with its verb
        conj = [r for r in w["readings"] if r["pos"] == "CONJ"]
        bare = all(r["case"] and (_nominal(r) or _adjectival(r)) for r in nxt["readings"])
        return _confirm(w, conj, clause=f"*{nxt['form']}* next to it is not ablative", force=bare) if bare else _confirm(w, conj)
    near = words[i + 1:i + 2]
    return _item("b", w, f"{w['form']} governs the {' or '.join(cases)}; no word in that case within "
                         f"{WINDOW_AFTER} words after or {WINDOW_BEFORE} before", near)


def _agrees(a: dict, b: dict) -> bool:
    return (a["case"] == b["case"] and a["number"] == b["number"]
            and (not a["gender"] or not b["gender"] or a["gender"] == b["gender"]))


def _adjective(words: list[dict], i: int) -> dict | None:
    w = words[i]
    adj = [r for r in w["readings"] if _adjectival(r)]
    if not adj:
        return None
    lemmas = {r["lemma"] for r in adj}
    rescue = [r for r in w["readings"] if not _adjectival(r) and not (r["pos"] == "NOUN" and r["lemma"] in lemmas)]
    others = [x for j, x in enumerate(words) if j != i]
    if any(not x["readings"] for x in others):
        return None

    def noun(x: dict) -> bool:
        return any(_nominal(r) and r["case"] for r in x["readings"])

    partners = [j for j, x in enumerate(words) if j != i and any(_agrees(a, r) for a in adj for r in x["readings"] if _nominal(r) and r["case"])]
    near = [words[k] for k in (i - 1, i + 1) if 0 <= k < len(words) and k not in partners           # a plain noun next to it
            and all(r["pos"] in ("NOUN", "PROPN") and r["case"] for r in words[k]["readings"])]
    name = sorted(lemmas, key=lambda x: all(r["pos"] == "VERB" for r in adj if r["lemma"] == x))[0]
    if partners:
        far = min(partners, key=lambda j: abs(j - i))
        if rescue or not near or any(abs(j - i) == 1 for j in partners) or abs(far - i) < FAR_GAP:
            return None
        return {"rule": "confirm", "severity": "note", "word": w["form"], "line": w["line"], "readings": _show(w), "against": {},
                "message": f"*{w['form']}* agrees with nothing next to it (*{near[0]['form']}*); taken with "
                           f"*{words[far]['form']}* in line {words[far]['line']}"}
    nouns = [x for x in others if noun(x)]
    verbs = [r for x in others for r in x["readings"] if _finite(r)]
    nom_noun = [x for x in nouns if any(_nominal(r) and r["case"] == "nom" for r in x["readings"])]
    loose = not nouns or any(a["case"] == "nom" and ((verbs and not nom_noun) or any(
        v["person"] in ("1", "2") and v["number"] == a["number"] for v in verbs)) for a in adj)
    if rescue:                                                # the form has another reading (noun, verb, adverb)
        known = any((x, "ADJ") in c for _, c in reading_counts(w["key"]) for x in lemmas)     # LASLA knows the adjective
        if near and known and all(r["pos"] == "NOUN" and r["lemma"] not in lemmas for r in rescue):
            return _confirm(w, rescue, force=True, clause=f"as the adjective *{name}* it agrees with no noun of its sentence, "
                                                          f"not with *{near[0]['form']}* next to it")
        return None if loose else _confirm(w, rescue, clause=f"as the adjective *{name}* it agrees with no noun or pronoun "
                                                             "of its sentence")
    if loose:                                                 # substantive, or predicate of an unexpressed subject (ego, tu)
        return _item("c", w, f"{w['form']} agrees with no noun of its sentence: read as a substantive or as the "
                             "predicate of an unexpressed subject", note=True)
    return _item("c", w, f"{w['form']} agrees in case, number and gender with no noun or pronoun of its sentence "
                         "(a substantive, or a clash)", nom_noun[:2] or nouns[:2])


def _nominative(words: list[dict], i: int) -> dict | None:
    w = words[i]
    reads = w["readings"]
    person = PERSON.get(w["key"], "3")                         # ego, tu, nos, uos
    cases = ("nom", "voc") if person != "3" else ("nom",)
    reads = [r for r in reads if r["pos"] == "PRON" and r["case"]] if person != "3" else reads
    if not reads or not all(r["case"] in cases and (_nominal(r) or _adjectival(r)) for r in reads):
        return None
    numbers = {r["number"] for r in reads}
    noun_only = all(r["pos"] in ("NOUN", "PROPN") for r in reads)
    verbs = [(x, r) for j, x in enumerate(words) if j != i for r in x["readings"] if _finite(r)]
    if not verbs:
        return None                                           # est left out, or the verb is in another sentence
    same_number = [(x, r) for x, r in verbs if r["number"] in numbers]
    if person != "3":
        if any(r["person"] == person for _x, r in same_number):
            return None
        return _item("d", w, f"{w['form']} ({'first' if person == '1' else 'second'} person, {'/'.join(sorted(numbers))}) "
                          "has no finite verb that agrees with it", [x for x, _r in verbs][:2])
    if any(r["person"] == "3" for _x, r in same_number):
        return None
    if same_number:
        if not noun_only or any(r["pos"] == "PRON" and r["lemma"] in PERSON for x in words for r in x["readings"]):
            return None                                       # predicate adjective, or apposition to ego / tu
        return _item("d2", w, f"{w['form']} (nominative) stands with a first or second person verb only",
                     [x for x, _r in same_number][:2])
    if numbers == {"sg"} and any(j != i and any(_nominal(r) and r["case"] == "nom" for r in x["readings"])
                                 for j, x in enumerate(words)):
        return None                                           # two singular subjects with a plural verb
    return _item("d", w, f"{w['form']} (nominative {'/'.join(sorted(numbers))}) has no finite verb of that number",
                 [x for x, _r in verbs][:2])


def _relative(sents: list[dict], s: int, i: int) -> dict | None:
    w = sents[s]["words"][i]
    rel = [r for r in w["readings"] if r["lemma"] == "qui" and r["pos"] in ("PRON", "DET", "ADJ") and r["case"]]
    if not rel or sents[s]["end"] == "?" or w["key"] in ("quod", "quam", "quo", "qua"):   # also conjunction / adverb
        return None
    if any(r["gender"] in ("n", "") for r in rel):
        return None                                           # neuter: the antecedent may be a clause
    for t, sent in enumerate(sents):
        for j, x in enumerate(sent["words"]):
            if (t, j) == (s, i):
                continue
            if not x["readings"]:
                return None
            for r in x["readings"]:
                if (_nominal(r) or _adjectival(r)) and any(q["number"] == r["number"] and (q["gender"] == r["gender"] or (not r["gender"] and r["pos"] == "PRON")) for q in rel):
                    return None
    return _item("e", w, f"{w['form']} (relative) agrees in gender and number with no word of the draft")


def check(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L3 agreement over a whole draft. evidence: [{rule, severity, word, line, message, readings, against}]."""
    try:
        if not latin_morph.available():
            return _unavailable("L3", "agreement", "data/morph_la.sqlite is missing (scripts/build_morph_la.py)")
        sents = sentences(text)
        items = []
        for s, sent in enumerate(sents):
            words = sent["words"]
            for i, w in enumerate(words):
                if not w["readings"]:
                    items.append(_item("a", w, f"{w['form']}: no source reads this form"))
                    continue
                for found in (_preposition(words, i), _adjective(words, i), _nominative(words, i), _relative(sents, s, i)):
                    if found:
                        items.append(found)
        fails = [x for x in items if x["severity"] == "fail"]
        notes = [x for x in items if x["severity"] == "note"]
        n_words = sum(len(s["words"]) for s in sents)
        if fails:
            detail = "; ".join(f"line {x['line']}: {x['message']}" for x in fails)
        else:
            detail = f"no clash in {len(sents)} sentence(s), {n_words} word(s)"
        confirm = sum(x["rule"] == "confirm" for x in notes)
        if confirm:
            detail += f" | {confirm} reading{'s' if confirm > 1 else ''} to confirm"
            notes.sort(key=lambda x: x["rule"] != "confirm")
        if notes:
            detail += " | notes: " + "; ".join(f"line {x['line']}: {x['message']}" for x in notes)
        return _result("L3", "agreement", not fails, detail, items)
    except Exception as exc:  # noqa: BLE001 - a check never raises
        return _unavailable("L3", "agreement", f"{type(exc).__name__}: {exc}")


def postpositives() -> dict[str, dict]:
    """The postpositive list: candidates from the grammar that the corpus never puts first in a sentence, with counts."""
    counts = latin_morph.word_order_counts().get("postpositive", {})
    return {w: counts.get(w, {"total": 0, "first": 0}) for w in POSTPOSITIVE_CANDIDATES
            if counts.get(w, {"first": 0})["first"] == 0}


def check_word_order(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L10 word order over a whole draft. evidence: [{rule, severity, word, line, message}]."""
    try:
        if not latin_morph.available():
            return _unavailable("L10", "word order", "data/morph_la.sqlite is missing (scripts/build_morph_la.py)")
        counts = latin_morph.word_order_counts()
        post, prep = postpositives(), counts.get("preposition_catullus", {})
        host_final, encl_total = counts.get("enclitic_host_final", {}), counts.get("enclitic_total", {})
        items = []

        def add(rule: str, severity: str, w: dict, message: str) -> None:
            items.append({"rule": rule, "severity": severity, "word": w["form"], "line": w["line"], "message": message})

        for sent in sentences(text):
            words = sent["words"]
            for i, w in enumerate(words):
                key = w["key"]
                if i == 0 and key in post:
                    c = post[key]
                    add("postpositive", "fail", w, f"{w['form']} stands first in its sentence (first in {c['first']} of "
                                                  f"{c['total']} places in Catullus and Horace)")
                for e in ("que", "ne", "ue"):
                    if not key.endswith(e) or len(key) < len(e) + 2 or latin_morph.lexical(key):
                        continue
                    split = latin_morph.enclitic_of(key)
                    if split is None:
                        add("enclitic", "fail", w, f"{w['form']} ends in -{e} but its host {key[:-len(e)]} has no reading")
                    elif split[1] == e and encl_total.get(e) and not host_final.get(f"{e}:{split[0][-1]}"):
                        add("enclitic", "note", w, f"-{e} on a host ending in -{split[0][-1]}: 0 of {encl_total[e]} hosts "
                                                   "in Catullus and Horace end so")
                    break
                last = i == len(words) - 1 and sent["end"] and len(words) > 1
                if last and key in GOVERNS and any(r["pos"] == "ADP" for r in w["readings"]) \
                        and key not in ADVERBIAL and key != "cum":
                    c = prep.get(key, {"total": 0, "last": 0})
                    if not c["last"]:
                        add("preposition", "fail", w, f"{w['form']} ends its sentence (last in {c['last']} of {c['total']} "
                                                     "places in Catullus)")
        fails = [x for x in items if x["severity"] == "fail"]
        detail = "; ".join(f"line {x['line']}: {x['message']}" for x in items) or "postpositives, enclitics and prepositions stand in possible places"
        return _result("L10", "word order", not fails, detail, items)
    except Exception as exc:  # noqa: BLE001 - a check never raises
        return _unavailable("L10", "word order", f"{type(exc).__name__}: {exc}")
