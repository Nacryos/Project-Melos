"""Build the corpus headword index (release O): every Greek word token -> ranked lemma(s).

Stages (each resumable; state in a staging SQLite file, --build):

  forms     tokenise every Greek-language passage, count distinct lookup spellings
  morph     local Morpheus for every distinct spelling (thread pool, own endpoint)
  generate  release-N generate-and-test spellings for unknown forms of edited text
  context   OdyCy contextual lemma/POS for edited Greek text (optional, --where)
  assemble  canonical headwords, ranking, per-token blobs, postings, aggregates

Run inside the API image so the backend package and its data are the deployed ones:

  python scripts/build_lemma_index.py forms    --corpus /corpus.sqlite --build /out/build.sqlite
  python scripts/build_lemma_index.py morph    --build /out/build.sqlite --endpoint http://melos-morpheus-batch:8080/api/v1/analysis/word
  python scripts/build_lemma_index.py generate --build /out/build.sqlite --endpoint ...
  python scripts/build_lemma_index.py context  --corpus /corpus.sqlite --build /out/build.sqlite --model /syntax-model
  python scripts/build_lemma_index.py assemble --corpus /corpus.sqlite --build /out/build.sqlite --out /out/lemma_index.sqlite

Nothing here edits the corpus. Machine analyses are labelled as such in the index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lemma_tokens import word_tokens, fold  # noqa: E402

FEATURE_KEYS = ("pofs", "case", "num", "gend", "tense", "mood", "voice", "pers", "comp", "dial")
SEARCHABLE = ("source_text", "machine_corrected_ocr")
EDITED_KINDS = ("text", "commentary")


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def staging(path):
    con = sqlite3.connect(path, timeout=60, check_same_thread=False)
    con.executescript("""
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS forms(form TEXT PRIMARY KEY, n INTEGER, n_edited INTEGER, n_damaged INTEGER);
      CREATE TABLE IF NOT EXISTS morph(form TEXT PRIMARY KEY, status TEXT, cands TEXT);
      CREATE TABLE IF NOT EXISTS gen(form TEXT PRIMARY KEY, accepted TEXT, tried INTEGER);
      CREATE TABLE IF NOT EXISTS context(rowid_ INTEGER PRIMARY KEY, preds TEXT);
    """)
    return con


def corpus_rows(corpus, where=""):
    con = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    sql = ("SELECT rowid,id,language,kind,quality,text FROM passages WHERE language IN ('grc','mul')"
           + (" AND " + where if where else "") + " ORDER BY rowid")
    yield from con.execute(sql)


# --------------------------------------------------------------------------- forms
def stage_forms(args):
    st = staging(args.build)
    counts, edited, broken = Counter(), Counter(), Counter()
    passages = tokens = 0
    for rowid, pid, lang, kind, quality, text in corpus_rows(args.corpus):
        passages += 1
        good = kind in EDITED_KINDS and quality in SEARCHABLE
        for _, _, _, form, dmg in word_tokens(text):
            tokens += 1
            counts[form] += 1
            if good:
                edited[form] += 1
            if dmg:
                broken[form] += 1
    with st:
        st.execute("DELETE FROM forms")
        st.executemany("INSERT INTO forms VALUES (?,?,?,?)",
                       ((f, n, edited[f], broken[f]) for f, n in counts.items()))
        st.execute("INSERT OR REPLACE INTO meta VALUES ('forms', ?)",
                   (json.dumps({"passages": passages, "tokens": tokens, "distinct_forms": len(counts)}),))
    log("forms", passages, "passages", tokens, "tokens", len(counts), "distinct forms")


# --------------------------------------------------------------------------- morph
def _project(raw, form, revision):
    from backend.machine_morphology import project, _sha
    receipt = {"id": _sha(raw), "raw_sha256": _sha(raw), "parser_version": "morpheus-local-v1",
               "engine_revision": revision}
    result = project(raw, form, receipt)
    cands = []
    for c in result["machine_candidates"]:
        feats = c.get("features") or {}
        cands.append([unicodedata.normalize("NFC", c["lemma"]), {k: feats[k] for k in FEATURE_KEYS if k in feats}])
    return result["status"], cands


class Engine:
    def __init__(self, endpoint):
        from backend.machine_morphology import request_url, validate_form
        self.endpoint, self.request_url, self.validate = endpoint, request_url, validate_form
        parts = urllib.parse.urlsplit(endpoint)
        health = json.loads(urllib.request.urlopen(
            urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/health", "", "")), timeout=10).read())
        self.revision = (f"alpheios-project/morpheus@{health['morpheus_commit']} (dist/stemlib); "
                         f"alpheios-project/morphsvc@{health['morphsvc_commit']}")

    def analyse(self, form):
        try:
            form = self.validate(form)
        except ValueError:
            return "invalid_form", []
        url = self.request_url(form, self.endpoint)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    raw = response.read()
                return _project(raw, form, self.revision)
            except Exception as exc:  # noqa: BLE001 - recorded, retried twice
                error = exc
                time.sleep(0.5 * (attempt + 1))
        return "error:" + type(error).__name__, []


def _run_pool(st, todo, work, threads, label, write):
    lock = threading.Lock()
    done = [0]
    started = time.time()
    pending = []

    def task(form):
        result = work(form)
        with lock:
            pending.append(write(form, result))
            done[0] += 1
            if len(pending) >= 500:
                flush()
            if done[0] % 20000 == 0:
                rate = done[0] / max(time.time() - started, 1e-6)
                log(label, done[0], "/", len(todo), f"{rate:.0f}/s")

    def flush():
        rows = list(pending)
        pending.clear()
        for sql, values in rows:
            st.execute(sql, values)
        st.commit()

    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(task, todo))
    with lock:
        flush()
    return time.time() - started


def stage_morph(args):
    st = staging(args.build)
    engine = Engine(args.endpoint)
    st.execute("INSERT OR REPLACE INTO meta VALUES ('engine_revision', ?)", (engine.revision,))
    st.commit()
    todo = [r[0] for r in st.execute("SELECT form FROM forms WHERE form NOT IN (SELECT form FROM morph) ORDER BY n DESC")]
    log("morph todo", len(todo))
    seconds = _run_pool(st, todo, engine.analyse, args.threads, "morph",
                        lambda form, res: ("INSERT OR REPLACE INTO morph VALUES (?,?,?)",
                                           (form, res[0], json.dumps(res[1], ensure_ascii=False))))
    retry = [r[0] for r in st.execute("SELECT form FROM morph WHERE status LIKE 'error:%'")]
    if retry:
        log("retrying", len(retry), "errors single-threaded")
        for form in retry:
            status, cands = engine.analyse(form)
            st.execute("INSERT OR REPLACE INTO morph VALUES (?,?,?)", (form, status, json.dumps(cands, ensure_ascii=False)))
        st.commit()
    stats = dict(st.execute("SELECT status,count(*) FROM morph GROUP BY 1").fetchall())
    st.execute("INSERT OR REPLACE INTO meta VALUES ('morph', ?)", (json.dumps({"seconds": round(seconds), "status": stats}),))
    st.commit()
    log("morph done", stats)


def stage_generate(args):
    from backend.dialect_generate import generate_and_test
    st = staging(args.build)
    engine = Engine(args.endpoint)
    cache_lock = threading.Lock()
    known = {}

    def analyse(spelling):
        with cache_lock:
            if spelling in known:
                return known[spelling]
        row = st_read(spelling)
        if row is None:
            status, cands = engine.analyse(spelling)
        else:
            status, cands = row
        result = {"status": status, "machine_candidates": cands}
        with cache_lock:
            known[spelling] = result
        return result

    reader = threading.local()

    def st_read(spelling):
        con = getattr(reader, "con", None)
        if con is None:
            con = reader.con = sqlite3.connect(f"file:{args.build}?mode=ro", uri=True, timeout=60)
        row = con.execute("SELECT status,cands FROM morph WHERE form=?", (spelling,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def work(form):
        accepted, tried = generate_and_test(form, analyse)
        return [[spelling, list(rules), result["machine_candidates"]] for spelling, rules, result in accepted], len(tried)

    todo = [r[0] for r in st.execute(
        "SELECT f.form FROM forms f JOIN morph m ON m.form=f.form WHERE m.status='no_analyses' "
        "AND f.n_edited>0 AND f.n_damaged<f.n AND f.form NOT IN (SELECT form FROM gen) ORDER BY f.n_edited DESC")]
    todo = [f for f in todo if len(fold(f)) >= 3]
    log("generate todo", len(todo))
    seconds = _run_pool(st, todo, work, args.threads, "generate",
                        lambda form, res: ("INSERT OR REPLACE INTO gen VALUES (?,?,?)",
                                           (form, json.dumps(res[0], ensure_ascii=False), res[1])))
    found = st.execute("SELECT count(*) FROM gen WHERE accepted<>'[]'").fetchone()[0]
    st.execute("INSERT OR REPLACE INTO meta VALUES ('generate', ?)",
               (json.dumps({"seconds": round(seconds), "forms": len(todo), "accepted": found}),))
    st.commit()
    log("generate done", found, "of", len(todo))


# --------------------------------------------------------------------------- context
def _model_view(text):
    """Text without brackets/underdots for the model, with a map back to source offsets."""
    keep, mapping = [], []
    for i, ch in enumerate(text):
        if ch in "[]⟦⟧⟨⟩〈〉<>{}̣":
            continue
        keep.append(" " if ch in "\r\n\t" else ch)
        mapping.append(i)
    mapping.append(len(text))
    return "".join(keep), mapping


def stage_context(args):
    import spacy
    st = staging(args.build)
    done = {r[0] for r in st.execute("SELECT rowid_ FROM context")}
    # Release O ran the model on edited text only; release P (--all-records) adds the other
    # Greek records (scholia, commentary, apparatus, OCR pages); finished rows are skipped.
    rows = [(rowid, text) for rowid, _, _, kind, quality, text in corpus_rows(args.corpus, args.where)
            if rowid not in done and (args.all_records or (kind == "text" and quality in SEARCHABLE))]
    shard = [r for r in rows if r[0] % args.shards == args.shard]
    if args.all_records:
        # OCR pages and scholia vary from a few words to whole pages: process them in length
        # order so a batch is not padded to its longest text (order does not change results).
        shard.sort(key=lambda r: len(r[1]))
    log("context todo", len(shard), "of", len(rows))
    nlp = spacy.load(args.model, exclude=["parser", "frequency_lemmatizer"])
    started, n = time.time(), 0
    views = [_model_view(text) for _, text in shard]
    batch = []
    for (rowid, _), (_, mapping), doc in zip(shard, views, nlp.pipe((v[0] for v in views), batch_size=16)):
        preds = []
        for token in doc:
            if not any(ch.isalpha() for ch in token.text):
                continue
            preds.append([mapping[token.idx], mapping[token.idx + len(token.text)],
                          unicodedata.normalize("NFC", token.lemma_ or ""), token.pos_])
        batch.append((rowid, json.dumps(preds, ensure_ascii=False)))
        n += 1
        if len(batch) >= 200:
            st.executemany("INSERT OR REPLACE INTO context VALUES (?,?)", batch)
            st.commit()
            batch.clear()
            log("context", n, "/", len(shard), f"{n / (time.time() - started):.1f} passages/s")
    st.executemany("INSERT OR REPLACE INTO context VALUES (?,?)", batch)
    st.commit()
    log("context shard done", n, round(time.time() - started), "s")


# --------------------------------------------------------------------------- assemble
POS_UD = {"noun": {"NOUN", "PROPN"}, "verb": {"VERB", "AUX"}, "adjective": {"ADJ", "DET", "NUM"},
          "adverb": {"ADV"}, "preposition": {"ADP", "ADV"}, "conjunction": {"CCONJ", "SCONJ", "ADV"},
          "particle": {"PART", "ADV", "CCONJ", "SCONJ"}, "pronoun": {"PRON", "DET"}, "article": {"DET"},
          "numeral": {"NUM", "ADJ"}, "interjection": {"INTJ"}, "irregular": set(), "exclamation": {"INTJ"},
          "verb participle": {"VERB", "ADJ", "AUX"}}


class Headwords:
    """Existence-only dictionary lookups mirroring backend.lemma_glosses.resolve steps 1, 3-6."""

    def __init__(self, morph):
        from backend.lemma_glosses import headword_key
        self.morph = morph
        self.headword_key = headword_key
        morph._load()
        self.entries = morph._entries
        self.cache = {}
        self.derived = {}   # release R: derived headword -> backend.derived_forms link
        self.pointers = {}  # release R: pure-pointer headword -> target headword
        self.degree_aliases = {}  # release R: recorded degree form -> the parser's positive headword

    def pointer_target(self, head, rows):
        """The target of a headword all of whose entries are pure pointers with an equivalence relation
        (no gloss of their own; "= X", "Aeol. for X", "Ep. for X"), when the target is a headword."""
        if not rows or any(str(r.get("gloss") or "").strip() for r in rows):
            return None
        for r in rows:
            text = str(r.get("entry_text") or "")
            greek = any("Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿" for ch in text[:140])
            m = (_POINTER if greek else _POINTER_BETA).search(text[:140])
            if m and not _re.search(r"\b(?:Aeol|Dor|Ep|Ion|Lesb|poet|Boeot|Thess|Lacon|Cypr)\.", text[:m.end()]):
                m = None   # a plain synonym ("= X") keeps its own headword; dialect/poetic forms are read to X
            if m:
                word = m.group(1)
                if not greek:
                    # Perseus LSJ and Autenrieth print the Greek in Beta Code inside English text
                    from betacode import beta_to_uni
                    word = beta_to_uni(word)
                target = self.headword_key(unicodedata.normalize("NFC", word).rstrip(",.;:"))
                match_t, rows_t = self.lookup(target) if target else (None, [])
                if target and target != head and match_t == "exact" and not all(_prefix_entry(x) for x in rows_t):
                    return target
        return None

    def lookup(self, headword):
        from backend.morphology import normalize
        if headword not in self.cache:
            bucket = self.entries.get(normalize(headword), ())
            exact = [r for r in bucket if unicodedata.normalize("NFC", str(r.get("lemma", ""))) == headword]
            if exact:
                self.cache[headword] = ("exact", exact)
            else:
                # Folded match only when every entry prints one headword (ignoring case).
                names = {unicodedata.normalize("NFC", str(r.get("lemma", ""))).lstrip("†").rstrip("0123456789")
                         for r in bucket}
                if bucket and len({self.headword_key(n).casefold() for n in names}) == 1:
                    self.cache[headword] = ("folded", list(bucket))
                else:
                    self.cache[headword] = (None, [])
        return self.cache[headword]

    def canonical(self, lemma):
        """(headword, rule) for a parser lemma; the lemma itself (rule None) when nothing resolves."""
        from backend.lemma_glosses import (elided_lemma_candidates, dialect_headword_variants, _fold,
                                           _initial_upper)
        from backend.aeolic_variants import _initial_breathing_swap
        key = self.headword_key(lemma)
        if not key:
            return lemma, None
        match, rows = self.lookup(key)
        if match and all(_prefix_entry(r) for r in rows):
            match = None   # release R: "ὀ-, insep. Prefix" is not the headword of a word
        if match:
            head = unicodedata.normalize("NFC", str(rows[0].get("lemma"))).lstrip("†").rstrip("0123456789")
            if match == "folded" and _initial_upper(key) != _initial_upper(head):
                head = key  # keep the parser's case for a name; letters agree
            if match == "folded" and _accented(key) and not _accented(head):
                # Release R: an accented lemma is not the unaccented enclitic of its letters (τίς, the
                # interrogative, is not τις; ποῦ not που): the parser's lemma is kept.
                return key, "accented_lemma_not_enclitic"
            head = self.headword_key(head)
            # Release R: an adverb, comparative or superlative whose own entry calls it the derived
            # form of another headword ("ταχέως, Adv. of ταχύς") is counted under that headword.
            from backend.derived_forms import derived_link
            link = derived_link(head, rows if match == "exact" else [], lambda base: self.lookup(base)[0] == "exact")
            if link:
                self.derived[head] = link
                return link["base"], "derived_" + link["relation"]
            # Release R: a headword whose entries are only a pointer to another ("πώνω, Dor. and Aeol.
            # = πίνω", "ἔμμι, Aeol. for εἰμί") has no meaning of its own: it is that headword.
            target = self.pointer_target(head, rows) if match == "exact" else None
            if target:
                self.pointers[head] = target
                return target, "dialect_pointer"
            return head, "headword" if match == "exact" else "folded_headword"
        restored = {o for o in elided_lemma_candidates(lemma) if self.lookup(o)[0] == "exact"}
        if len(restored) == 1:
            return restored.pop(), "elided_lemma_restored"
        others = {self.headword_key(v) for v in self.morph.form_lemmas(key) if self.headword_key(v) != key}
        if not others and _initial_upper(key):
            lower = unicodedata.normalize("NFC", key[:1].lower() + key[1:])
            others = {self.headword_key(v) for v in self.morph.form_lemmas(lower) if self.headword_key(v) != lower}
        if len(others) == 1:
            target = others.pop()
            if self.lookup(target)[0]:
                return target, "lemma_as_attested_form"
        rough = _initial_breathing_swap(key)
        if rough and self.lookup(rough)[0] == "exact":
            return rough, "aeolic_psilosis_lemma"
        if len(_fold(key)) >= 4:
            for variant in dialect_headword_variants(key):
                match, rows = self.lookup(variant["key"])
                if match:
                    head = unicodedata.normalize("NFC", str(rows[0].get("lemma"))).lstrip("†").rstrip("0123456789")
                    return self.headword_key(head), variant["rule"]
        return key, None


def _prefix_entry(entry):
    """An entry for a prefix ("ὀ-, insep. Prefix", "a)- as a prothetic vowel"), not a word."""
    text = str(entry.get("entry_text") or "")[:40]
    return "Prefix" in text or bool(_re.match(r"^\S+?[-‐]\s*[,\s]", text))


def _accented(word):
    nfd = unicodedata.normalize("NFD", str(word or ""))
    return any(mark in nfd for mark in ("\u0301", "\u0300", "\u0342"))


def _pos_of(features):
    return str((features or {}).get("pofs") or "").lower()


import re as _re
_GREEK_WORD = r"([\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+)"
_VARIANT_PATTERNS = (
    # Middle Liddell / LSJ: "= πότνια", "poet. for ἔρως", "Ep. form of ἠώς", "Aeol. for ..."
    ("=", _re.compile(r"^\s*=\s*" + _GREEK_WORD)),
    ("=", _re.compile(r"^[^=.;]{0,40}?\s=\s*" + _GREEK_WORD)),
    ("dialect", _re.compile(r"\b((?:Ep|Ion|Dor|Aeol|Att|Lacon|Boeot|poet|Lesb|Thess|Arc|Cret|Hom|old)\.)"
                            r"(?:\s+(?:and|&)\s+\w+\.)?\s+(?:also\s+)?(?:form\s+)?(?:for|of)\s+" + _GREEK_WORD)),
    # "shorter form of πότνια", "later form of …"
    ("form", _re.compile(r"\b((?:shorter|longer|later|earlier|older|contracted|lengthened)\s+form)\s+of\s+"
                         + _GREEK_WORD)),
)


# "= X", "Aeol. for X", "Dor. and Aeol. = X", "Ep. for X" near the start of a pointer entry
_POINTER = _re.compile(r"(?:=|\b(?:Aeol|Dor|Ep|Ion|Lesb|poet|Att|Boeot|Thess|Lacon|Cypr)\.(?:\s*(?:and|&)\s*\w+\.)?"
                       r"\s*,?\s*(?:=|for))\s*" + _GREEK_WORD)


_POINTER_BETA = _re.compile(r"(?:=|\b(?:Aeol|Dor|Ep|Ion|Lesb|poet|Att|Boeot|Thess|Lacon|Cypr)\.(?:\s*(?:and|&)\s*\w+\.)?"
                            r"\s*,?\s*(?:=|for))\s*([a-z][a-z()/\\=|+']*[a-z/\\=|+])")


_GLOSS_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "by", "as", "at", "from", "be",
               "is", "one", "one's", "any", "some", "which", "that", "this", "also", "form", "used", "esp", "etc"}


def _gloss_words(gloss):
    return {w for w in _re.findall(r"[a-z][a-z'-]+", str(gloss or "").lower()) if len(w) > 2 and w not in _GLOSS_STOP}


def _stems(words):
    return {w[:5] for w in words}


def senses_agree(gloss_a, gloss_b, extra_a=(), extra_b=(), pointer_a=()):
    """A variant link needs the two headwords' meanings to agree. Release Q compared the two short
    glosses only, which lost genuine links whose short glosses use different words (γαῖα "a land", γῆ
    "earth"). Release R compares the content words (5-letter stems: "forgetting" ~ "forgetfulness") of
    every dictionary's gloss of each headword (extra_a, extra_b), plus the words the pointer entry itself
    prints after the target ("λίς, Ep. for λέων, lion": pointer_a). A headword with no meaning of its own
    (a pure pointer, πότνα) takes its meaning from the link."""
    words_a = _gloss_words(gloss_a).union(*(_gloss_words(x) for x in extra_a))
    if not words_a:
        return True
    words_a = words_a.union(*(_gloss_words(x) for x in pointer_a))
    words_b = _gloss_words(gloss_b).union(*(_gloss_words(x) for x in extra_b))
    return bool(_stems(words_a) & _stems(words_b))


_ARTICLES = {"ὁ", "ἡ", "τό", "οἱ", "αἱ", "τά"}


def _header_ending(word):
    """An article or an inflection ending printed in a dictionary header (ά, όν, ίδος, ατος, ὁ):
    a word of at most two letters, an article, or a lower-case vowel-initial word without a breathing
    (a real vowel-initial Greek word always carries one)."""
    if word in _ARTICLES or len(fold(word)) <= 2:
        return True
    nfd = unicodedata.normalize("NFD", word)
    return word == word.lower() and nfd[:1] in "αεηιουω" and "̓" not in nfd[:3] and "̔" not in nfd[:3]


_HOMOGRAPH_LETTER = _re.compile(r"^\s*\S+\s*(?:\[[^\]]*\]\s*)?\(([A-Z])\)")


def lemma_variants(lemma_ids, lemma_tokens, heads, glosses=None):
    """Variant links between headwords (release P): a dictionary entry of headword A says it is
    a dialect or poetic form of headword B ("ἔρος ... poet. for ἔρως", "πότνα = πότνια"), and B
    is itself a corpus headword. Both stay separate headwords; the link lets counts be combined
    and pages cross-reference. Rows (lemma_id, target_id, relation, dictionary, evidence).

    Release R: the evidence must be the dictionary cross-reference itself and the meanings must agree
    (senses_agree over every dictionary's glosses). A pointer printed in a secondary homograph's
    entry ("ἅλιος (C), Dor. for ἥλιος", "πᾶς (C), = πατήρ", "δράω (B), = ὁράω") or naming a secondary
    homograph of the target ("κοῦρος ... for κόρος (B)") does not link the corpus headwords, whose
    tokens are mostly the other homograph."""
    rows = set()
    gloss_cache = {}

    def all_glosses(head):
        if head not in gloss_cache:
            match, entries = heads.lookup(head)
            gloss_cache[head] = [str(e.get("gloss") or "") for e in (entries if match else [])]
        return gloss_cache[head]

    for head, lid in lemma_ids.items():
        if not lemma_tokens.get(lid):
            continue
        match, entries = heads.lookup(head)
        if not match:
            continue
        # A headword with lettered homograph entries ("οὖλος (A) ... form of ὅλος", "οὖλος (B) woolly"): its
        # meaning for the link is its own short gloss only, never the union of the homographs' meanings.
        homographs = any(_HOMOGRAPH_LETTER.match(str(e.get("entry_text") or "")[:220]) for e in entries[:8])
        for entry in entries[:8]:
            texts = [str(entry.get("gloss") or ""), str(entry.get("entry_text") or "")[:220]]
            letter = _HOMOGRAPH_LETTER.match(texts[1])
            if letter and letter.group(1) != "A":
                continue
            for relation, pattern in _VARIANT_PATTERNS:
                for text in texts:
                    m = pattern.search(text)
                    if not m:
                        continue
                    if relation == "=" and any(fold(w) != fold(head) for w in
                                               _re.findall(_GREEK_WORD, text[:m.start(m.lastindex)])
                                               if _re.search(r"[Ͱ-Ͽἀ-῿]", w) and not _header_ending(w)):
                        # "= B" names B as the headword itself only when no other Greek word stands
                        # before it ("Δίς = Ζεύς" in the entry of Δίιος is about Δίς, "*ῥύω = ἐρύω" in
                        # the entry of ῥύμη is about ῥύω); inflection endings and articles of the
                        # header (ά, όν, ίδος, ατος, ὁ) do not count
                        break
                    if relation == "=" and _re.search(r"\b(?!also\b)[a-z]{4,}\b", text[:m.start(m.lastindex)]):
                        # Release R: "φρήν properly = διάφραγμα", "speaking first, and so = πρωταγωνιστής":
                        # an English definition before "=" makes it an explanation, not a variant
                        break
                    after = text[m.end():m.end() + 80]
                    target_letter = _re.match(r"\s*\(([A-Z])\)", after)
                    if target_letter and target_letter.group(1) != "A":
                        break
                    target = heads.headword_key(unicodedata.normalize("NFC", m.groups()[-1]))
                    tid = lemma_ids.get(target)
                    pointer_words = [_re.split(r"[;:]|\b[A-Z][a-z]*\.\s", after, maxsplit=1)[0]]
                    if tid and tid != lid and lemma_tokens.get(tid) and (
                            glosses is None or senses_agree(glosses.get(lid), glosses.get(tid),
                                                            () if homographs else all_glosses(head), all_glosses(target),
                                                            () if homographs else pointer_words)):
                        label = "=" if relation == "=" else m.group(1)
                        rows.add((lid, tid, label, str(entry.get("source") or "")[:80],
                                  text[max(0, m.start() - 30): m.end() + 10]))
                    break
    return sorted(rows)


def stage_assemble(args):
    import numpy as np
    from backend.morphology import Morphology
    started = time.time()
    st = staging(args.build)
    lex = Path(args.lexica)
    morph_service = Morphology(lex / "entries.jsonl", lex / "forms.jsonl",
                               supplement_paths=[p for p in [lex / "supplement-entries.jsonl"] if p.exists()])
    heads = Headwords(morph_service)
    log("lexica loaded", heads.morph.entry_count, "entries")

    forms = {r[0]: (r[1], r[2]) for r in st.execute("SELECT form,n,n_edited FROM forms")}
    morph = {r[0]: (r[1], json.loads(r[2])) for r in st.execute("SELECT form,status,cands FROM morph")}
    gen = {r[0]: json.loads(r[1]) for r in st.execute("SELECT form,accepted FROM gen")}
    log("staging loaded", len(forms), "forms", len(morph), "parsed", len(gen), "generated")

    canon_cache = {}

    def canon(lemma):
        if lemma not in canon_cache:
            canon_cache[lemma] = heads.canonical(lemma)
        return canon_cache[lemma]

    # Candidate evidence per form: {headword: {"src": bits, "w": weight, "pos": set, "rules": set}}
    MORPH, RECORDED, GENERATED, HEADWORD = 1, 2, 4, 8
    from backend.interlinear import canonical_features, compact_parse
    parse_cache = {}

    def parse_text(feats):
        key = json.dumps(feats, sort_keys=True, ensure_ascii=False)
        if key not in parse_cache:
            try:
                parse_cache[key] = compact_parse(canonical_features({"features": feats}))
            except Exception:  # noqa: BLE001 - a display label only
                parse_cache[key] = ""
        return parse_cache[key]

    # Release Q: a lemma recorded for a spelling in a source annotation is kept only when it is a
    # dictionary headword or a lemma the parser itself gives somewhere (a treebank placeholder
    # "other" written in Greek letters, οτηερ, is neither).
    parser_heads = set()
    for _, parsed in morph.values():
        for lemma, _ in parsed:
            parser_heads.add(canon(lemma)[0])
    for accepted in gen.values():
        for _, _, parsed_g in accepted:
            for lemma, _ in parsed_g:
                parser_heads.add(canon(lemma)[0])
    dropped_recorded = Counter()
    evidence = {}
    for form in forms:
        cands = {}
        status, parsed = morph.get(form, ("missing", []))
        for lemma, feats in parsed:
            head, rule = canon(lemma)
            c = cands.setdefault(head, {"src": 0, "n": 0, "pos": set(), "rules": set()})
            c["src"] |= MORPH
            c["n"] += 1
            c["pos"].add(_pos_of(feats))
            c.setdefault("parses", []).append(parse_text(feats))
            if rule and rule not in ("headword",):
                c["rules"].add(rule)
        if not cands:
            for spelling, rules, parsed_g in gen.get(form, []):
                for lemma, feats in parsed_g:
                    head, rule = canon(lemma)
                    c = cands.setdefault(head, {"src": 0, "n": 0, "pos": set(), "rules": set()})
                    c["src"] |= GENERATED
                    c["n"] += 1
                    c["pos"].add(_pos_of(feats))
                    c.setdefault("parses", []).append(parse_text(feats) + f" (from {spelling})")
                    c["rules"].update(["generated:" + "+".join(rules)])
        lookup_form = form.rstrip("’")
        for lemma in heads.morph.form_lemmas(form) or (heads.morph.form_lemmas(lookup_form) if lookup_form != form else []):
            head, rule = canon(lemma)
            if rule is None and head not in parser_heads and not heads.lookup(head)[0]:
                dropped_recorded[head] += forms[form][0]
                continue
            c = cands.setdefault(head, {"src": 0, "n": 0, "pos": set(), "rules": set()})
            c["src"] |= RECORDED
        printed_head = heads.headword_key(form)
        if printed_head in cands and not cands[printed_head]["src"] & MORPH:
            # Release R: a comparative or superlative recorded as its own lemma (μάλιστα) that the parser
            # reads as a degree of another headword (μάλα, sup.) is counted under that headword.
            degree = [h for h, c in cands.items() if c["src"] & MORPH and h != printed_head
                      and any(p.split()[-1:] in (["sup."], ["comp."]) for p in c.get("parses") or [])]
            if len(degree) == 1:
                target = degree[0]
                cands[target]["src"] |= cands.pop(printed_head)["src"]
                heads.degree_aliases.setdefault(printed_head, target)
        if not cands:
            # Release R: a form the parser does not read whose rough-breathing twin it does (Lesbian
            # psilosis: ἀ for the article ἁ, ὀ for ὁ, οἰ for οἱ): the twin's parses, labelled.
            from backend.aeolic_variants import psilotic_variants
            for item in psilotic_variants(form):
                status_t, parsed_t = morph.get(item["form"], ("missing", []))
                for lemma, feats in parsed_t:
                    head, rule = canon(lemma)
                    c = cands.setdefault(head, {"src": 0, "n": 0, "pos": set(), "rules": set()})
                    c["src"] |= GENERATED
                    c["n"] += 1
                    c["pos"].add(_pos_of(feats))
                    c.setdefault("parses", []).append(parse_text(feats) + f" (from {item['form']})")
                    c["rules"].add("generated:psilosis")
        if not cands:
            # Release R: the Lesbian lexical table (ἤπειτα: ἔπειτα) and the second word of a crasis
            # (κωὔτε: οὔτε, backend.aeolic_variants), when the parser reads that spelling.
            from backend.aeolic_variants import lexical_variant, crasis_second_words
            lexical = lexical_variant(form)
            options = ([(lexical[0], "aeolic_lexical")] if lexical else []) + \
                [(item["form"], "crasis_second_word") for item in crasis_second_words(form)]
            for spelling, rule_name in options:
                status_t, parsed_t = morph.get(spelling, ("missing", []))
                for lemma, feats in parsed_t:
                    head, rule = canon(lemma)
                    c = cands.setdefault(head, {"src": 0, "n": 0, "pos": set(), "rules": set()})
                    c["src"] |= GENERATED
                    c["n"] += 1
                    c["pos"].add(_pos_of(feats))
                    c.setdefault("parses", []).append(parse_text(feats) + f" (from {spelling})")
                    c["rules"].add("generated:" + rule_name)
                if cands:
                    break
        if not cands and not form.endswith("’"):
            # The printed form is itself a dictionary headword (indeclinables, adverbs: ἴψοι).
            key = heads.headword_key(form)
            match, rows_h = heads.lookup(key)
            if match == "exact" and not all(_prefix_entry(r) for r in rows_h):
                cands[key] = {"src": HEADWORD, "n": 0, "pos": set(), "rules": set()}
        evidence[form] = cands
    log("evidence built", round(time.time() - started), "s;", len(canon_cache), "parser lemmas canonicalised;",
        len(dropped_recorded), "recorded lemmas that are neither headword nor parser lemma dropped, e.g.",
        dropped_recorded.most_common(12))

    def weight(c, parsed=False):
        # A lemma recorded for the spelling in a source annotation but not among the parser's
        # analyses of a spelling the parser does know is weak evidence (annotation noise).
        w = 0.0
        if c["src"] & MORPH:
            w += 1.0
        if c["src"] & RECORDED:
            w += 1.0 if c["src"] & MORPH else (0.05 if parsed else 0.6)
        if c["src"] & GENERATED:
            w += 0.5
        if c["src"] & HEADWORD:
            w += 0.8
        return w

    # EM over lemma priors (token-weighted); unambiguous forms anchor the priors.
    prior = defaultdict(lambda: 1.0)
    for _ in range(6):
        mass = defaultdict(float)
        for form, cands in evidence.items():
            if not cands:
                continue
            n = forms[form][0]
            scores = {h: weight(c, any(x["src"] & MORPH for x in cands.values())) * math.sqrt(prior[h]) for h, c in cands.items()}
            total = sum(scores.values()) or 1.0
            for h, s in scores.items():
                mass[h] += n * s / total
        prior = defaultdict(lambda: 0.5, {h: m + 0.5 for h, m in mass.items()})
    posterior = {}
    for form, cands in evidence.items():
        if not cands:
            continue
        scores = {h: weight(c, any(x["src"] & MORPH for x in cands.values())) * math.sqrt(prior[h]) for h, c in cands.items()}
        total = sum(scores.values())
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        posterior[form] = [(h, s / total) for h, s in ranked]
    log("posteriors", len(posterior), "forms with a lemma of", len(evidence))

    # Context predictions (by passage rowid): [start, end, lemma, upos]
    context = {}
    for rowid_, preds in st.execute("SELECT rowid_, preds FROM context"):
        context[rowid_] = json.loads(preds)
    log("context passages", len(context))

    out = Path(args.out)
    if out.exists():
        out.unlink()
    ix = sqlite3.connect(out)
    from backend.lemma_index import SCHEMA
    ix.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=8192;" + SCHEMA)

    # ids
    lemma_ids, form_ids = {}, {}
    lemma_tokens, lemma_passages = Counter(), Counter()
    lemma_pos = defaultdict(Counter)
    for form, cands in evidence.items():
        for h, c in cands.items():
            for p in c["pos"]:
                if p:
                    lemma_pos[h][p] += forms[form][0]

    def lid(h):
        if h not in lemma_ids:
            lemma_ids[h] = len(lemma_ids) + 1
        return lemma_ids[h]

    def fid(f):
        if f not in form_ids:
            form_ids[f] = len(form_ids) + 1
        return form_ids[f]

    CONTEXT_AGREES, CONTEXT_CHOSE, DAMAGED, ELIDED = 16, 32, 64, 128
    DIALECT_RULE_FLAG = 2   # token_flag bit (release R): a dialect rule changed the token's reading
    stats = {"tokens": 0, "with_lemma": 0, "context_agrees": 0, "context_changed": 0,
             "elision_model": 0, "elision_ties": 0, "elision_changed": 0, "context_disagrees": 0,
             "dialect_rule_tokens": 0, "dialect_rule_changed": 0}
    from backend.passage_dialect import passage_dialect
    from backend.dialect_rules import index_factors
    feature_cache = {}

    def readings_of(spelling):
        """Canonical features of the parser readings of a spelling (cached)."""
        if spelling not in feature_cache:
            from backend.interlinear import canonical_features
            _, parsed_s = morph.get(spelling, ("missing", []))
            feature_cache[spelling] = [canonical_features({"features": feats}) for _, feats in parsed_s]
        return feature_cache[spelling]

    def dialect_factors(form, heads_ranked, text, toks, index, dialect):
        cands = []
        _, parsed_f = morph.get(form, ("missing", []))
        for lemma, feats in parsed_f:
            cands.append({"lemma": canon(lemma)[0], "features": feats})
        if not cands:
            for spelling, rules, parsed_g in gen.get(form, []):
                for lemma, feats in parsed_g:
                    cands.append({"lemma": canon(lemma)[0], "features": feats, "normalised_query": spelling})
        known = {c["lemma"] for c in cands}
        cands += [{"lemma": h, "features": {}} for h in heads_ranked if h not in known]
        if dialect == "lesbian":
            # Lesbian psilosis: the rough-breathing twin's parses (οἷ for printed οἶ), as fallback readings
            from backend.aeolic_variants import psilotic_variants
            for item in psilotic_variants(form):
                for lemma, feats in morph.get(item["form"], ("missing", []))[1]:
                    cands.append({"lemma": canon(lemma)[0], "features": feats, "normalisation_rule": item["rule"],
                                  "normalised_query": item["form"]})
        return index_factors(form, cands, heads_ranked, text, toks, index, dialect, readings_of)
    flag_bits = defaultdict(int)   # release Q: token_flag (bit 1: the context model named another reading;
    #                                 release R bit 2: a dialect rule changed the reading)
    # Release Q: elided spellings with several readings are ranked per token by the elision model
    # (backend/elision.py): treebank train prior, restored spellings' corpus frequency, context.
    head_class = {h: (c.most_common(1)[0][0] if c else "unknown") for h, c in lemma_pos.items()}
    from backend.lemma_calibration import same_lexeme
    elision = None
    if args.elision_model:
        from backend.elision import ElisionModel, base_distribution, is_elided, is_tie, key as ekey, token_features
        elision = ElisionModel.load(args.elision_model)
        freq_by_key = defaultdict(Counter)
        for f, ranked_f in posterior.items():
            if not is_elided(f):
                for h, p in ranked_f:
                    freq_by_key[ekey(f)][h] += forms[f][0] * p
        log("elision model", args.elision_model, elision.data.get("params"), len(freq_by_key), "restorable spellings")
    elided_mass = defaultdict(Counter)
    alt_rows = []
    # Release Q: a passage repeated word for word within one collection and work (a refrain, a
    # record stored twice) is counted once in frequency tables, as n-grams and collocations do.
    first_copy, repeat_rows = {}, []
    prior_tokens = Counter()
    by_group = defaultdict(Counter)
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    from backend.author_aliases import canonical as canonical_author
    author_cache = {}
    pid = 0
    tok_rows, posting_rows, passage_rows = [], [], []
    for row in con.execute("SELECT rowid,id,language,kind,quality,author,work,citation,source,text FROM passages "
                           "WHERE language IN ('grc','mul') ORDER BY rowid"):
        tokens = word_tokens(row["text"])
        if not tokens:
            continue
        pid += 1
        dialect = passage_dialect({"author": row["author"], "id": row["id"]}) if row["kind"] == "text" else None
        label = row["author"] or ""
        if label not in author_cache:
            author_cache[label] = canonical_author(label) if label else ""
        preds = context.get(row["rowid"]) or []
        pred_at = {p[0]: p for p in preds}
        lemmas = np.zeros(len(tokens), dtype=np.uint32)
        fids = np.zeros(len(tokens), dtype=np.uint32)
        conf = np.zeros(len(tokens), dtype=np.uint8)
        src = np.zeros(len(tokens), dtype=np.uint8)
        starts = np.zeros(len(tokens), dtype=np.uint32)
        ends = np.zeros(len(tokens), dtype=np.uint16)
        here = Counter()
        group = (row["kind"], row["quality"] in SEARCHABLE)
        for i, (s, e, printed, form, dmg) in enumerate(tokens):
            starts[i], ends[i], fids[i] = s, min(e - s, 65535), fid(form)
            ranked = posterior.get(form)
            flags = DAMAGED if dmg else 0
            if ranked:
                choice, prob = ranked[0]
                dist = list(ranked)
                if not (row["kind"] == "text" and row["quality"] in SEARCHABLE):
                    # Release O's reading of non-edited records (no contextual model): kept as the
                    # frequency prior of English readings so search ranks as in release O.
                    prior_tokens[lid(choice)] += 1
                pred = pred_at.get(s)
                if elision is not None and len(ranked) > 1 and is_elided(form):
                    feats = token_features(row["text"], tokens, i, pred_at)
                    base = base_distribution(form, dict(ranked), freq_by_key.get,
                                             feats["next_initial"] == "rough")
                    ranked_e = elision.rank(form, base, head_class, feats, ekey)
                    flags |= ELIDED
                    stats["elision_model"] += 1
                    if ranked_e[0][0] != choice:
                        stats["elision_changed"] += 1
                    tie = is_tie(ranked_e, same=ekey)
                    if tie:
                        stats["elision_ties"] += 1
                        alt_rows.append((pid, i, lid(tie[0]), round(tie[1], 4)))
                    for h, p in ranked_e:
                        elided_mass[form][h] += p
                    choice, prob = ranked_e[0]
                    dist = list(ranked_e)
                elif pred and len(ranked) > 1:
                    plemma, upos = heads.headword_key(pred[2]) if pred[2] else "", pred[3]
                    rescored = []
                    for h, p in ranked:
                        c = evidence[form][h]
                        factor = 1.0
                        if plemma and fold(plemma) == fold(h):
                            factor *= 4.0
                        allowed = set().union(*(POS_UD.get(x, set()) for x in c["pos"])) if c["pos"] else set()
                        if upos and allowed:
                            factor *= 2.0 if upos in allowed else 0.5
                        rescored.append((h, p * factor))
                    total = sum(p for _, p in rescored)
                    rescored = sorted(((h, p / total) for h, p in rescored), key=lambda kv: (-kv[1], kv[0]))
                    # Strong-evidence rule: the context never displaces the only exact
                    # dictionary/recorded reading unless it names the lemma itself.
                    top = evidence[form][ranked[0][0]]
                    protected = (top["src"] & (RECORDED | HEADWORD)) and not any(
                        evidence[form][h]["src"] & (RECORDED | HEADWORD) for h, _ in ranked[1:])
                    if rescored[0][0] != choice and protected and fold(plemma) != fold(rescored[0][0]):
                        rescored = sorted(rescored, key=lambda kv: kv[0] != choice)
                    if rescored[0][0] != choice:
                        flags |= CONTEXT_CHOSE
                        stats["context_changed"] += 1
                    elif plemma and fold(plemma) == fold(choice):
                        flags |= CONTEXT_AGREES
                        stats["context_agrees"] += 1
                    choice, prob = rescored[0]
                    dist = list(rescored)
                    other = next((h for h, _ in ranked if plemma and fold(h) == fold(plemma)), None)
                    if other and fold(other) != fold(choice) and not same_lexeme(
                            choice, other, head_class.get(choice), head_class.get(other), heads.morph.form_lemmas):
                        # the contextual model named another reading of this spelling (not the same word
                        # under another lemmatisation convention: μάλιστα / μάλα) and could not impose it
                        flag_bits[(pid, i)] |= 1
                        stats["context_disagrees"] += 1
                elif pred and pred[2] and fold(heads.headword_key(pred[2])) == fold(choice):
                    flags |= CONTEXT_AGREES
                    stats["context_agrees"] += 1
                if dialect and len(dist) > 1:
                    # Release R: dialect grammar (backend.dialect_rules gates: parser dialect labels, the
                    # article needs a noun, -ην infinitives, iota subscript, μή + imperative, elision,
                    # Lesbian -ας genitives) applied to this token's readings in a Lesbian/Doric passage.
                    factors = dialect_factors(form, [h for h, _ in dist], row["text"], tokens, i, dialect)
                    if factors:
                        top_p = dist[0][1]
                        known_h = {h for h, _ in dist}
                        weighted = [(h, p * factors.get(h, 1.0)) for h, p in dist] +                             [(h, top_p * f) for h, f in factors.items() if h not in known_h]
                        total = sum(p for _, p in weighted) or 1.0
                        weighted = sorted(((h, p / total) for h, p in weighted), key=lambda kv: (-kv[1], kv[0]))
                        stats["dialect_rule_tokens"] += 1
                        if weighted[0][0] != choice:
                            stats["dialect_rule_changed"] += 1
                            flag_bits[(pid, i)] |= DIALECT_RULE_FLAG
                            if flags & (CONTEXT_CHOSE | CONTEXT_AGREES):
                                flags &= ~(CONTEXT_CHOSE | CONTEXT_AGREES)
                        choice, prob = weighted[0]
                flags |= evidence[form].get(choice, {"src": GENERATED})["src"]
                lemmas[i] = lid(choice)
                conf[i] = max(1, min(255, round(prob * 255)))
                here[lemmas[i]] += 1
                if row["kind"] == "text" and row["quality"] in SEARCHABLE:
                    prior_tokens[int(lemmas[i])] += 1
                stats["with_lemma"] += 1
                by_group[group]["with_lemma"] += 1
            src[i] = flags
            stats["tokens"] += 1
            by_group[group]["tokens"] += 1
        if lemmas.any():
            copy_key = (row["source"], label, row["work"], lemmas.tobytes())
            if copy_key in first_copy:
                repeat_rows.append((pid, first_copy[copy_key]))
            else:
                first_copy[copy_key] = pid
        for l, n in here.items():
            lemma_tokens[int(l)] += n
            lemma_passages[int(l)] += 1
            posting_rows.append((int(l), pid, n))
        passage_rows.append((pid, row["id"], row["kind"], row["quality"], row["language"], author_cache[label], label,
                             row["work"], row["citation"], row["source"], len(tokens), len(here)))
        tok_rows.append((pid, lemmas.tobytes(), fids.tobytes(), conf.tobytes(), src.tobytes(), starts.tobytes(),
                         ends.tobytes()))
        if len(tok_rows) >= 5000:
            ix.executemany("INSERT INTO tok VALUES (?,?,?,?,?,?,?)", tok_rows)
            ix.executemany("INSERT INTO passage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", passage_rows)
            tok_rows.clear(); passage_rows.clear()
    ix.executemany("INSERT INTO tok VALUES (?,?,?,?,?,?,?)", tok_rows)
    ix.executemany("INSERT INTO passage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", passage_rows)
    posting_rows.sort()
    ix.executemany("INSERT INTO posting VALUES (?,?,?)", posting_rows)
    ix.executemany("INSERT INTO token_alt VALUES (?,?,?,?)", alt_rows)
    ix.executemany("INSERT INTO passage_repeat VALUES (?,?)", repeat_rows)
    ix.executemany("INSERT INTO token_flag VALUES (?,?,?)", sorted((p, i, f) for (p, i), f in flag_bits.items()))
    stats["repeated_passages"] = len(repeat_rows)
    first_copy.clear()
    log("tokens", stats)

    # lemma table with a short gloss and gloss terms (English -> Greek bridge)
    from backend.lemma_glosses_index import short_gloss_for, gloss_terms
    lemma_rows, term_rows = [], []
    head_rule = {}
    for head, rule in canon_cache.values():
        if rule and not rule.startswith("derived_") and not head_rule.get(head):
            head_rule[head] = rule
    for form, cands in evidence.items():
        for h, c in cands.items():
            if c["src"] & HEADWORD:
                head_rule.setdefault(h, "headword")
    for h, i in lemma_ids.items():
        rule = head_rule.get(h) or ("headword" if heads.lookup(h)[0] else None)
        gloss, gsrc, full = short_gloss_for(h, heads)
        pos = lemma_pos[h].most_common(1)[0][0] if lemma_pos[h] else None
        lemma_rows.append((i, h, fold(h), pos, rule, lemma_tokens[i], lemma_passages[i], gloss, gsrc))
        for term, field, w in gloss_terms(gloss, full):
            term_rows.append((term, i, field, w))
    ix.executemany("INSERT INTO lemma VALUES (?,?,?,?,?,?,?,?,?)", lemma_rows)
    ix.executemany("INSERT INTO lemma_gloss_term VALUES (?,?,?,?)", term_rows)
    ix.executemany("INSERT INTO lemma_prior VALUES (?,?)", sorted(prior_tokens.items()))
    variant_rows = lemma_variants(lemma_ids, lemma_tokens, heads, {r[0]: r[7] for r in lemma_rows})
    ix.executemany("INSERT INTO lemma_variant VALUES (?,?,?,?,?)", variant_rows)
    # Release R: headwords counted under another one (derived forms, dialect pointers), so lookups and the
    # calibration can read a lemma written either way through the link.
    alias_rows = [(alias, lemma_ids[link["base"]], "derived_" + link["relation"], link.get("entry_id"))
                  for alias, link in sorted(heads.derived.items()) if link["base"] in lemma_ids]
    alias_rows += [(alias, lemma_ids[target], "dialect_pointer", None)
                   for alias, target in sorted(heads.pointers.items()) if target in lemma_ids]
    alias_rows += [(alias, lemma_ids[target], "parser_degree", None)
                   for alias, target in sorted(heads.degree_aliases.items())
                   if target in lemma_ids and alias not in heads.derived and alias not in lemma_ids]
    ix.executemany("INSERT INTO lemma_alias VALUES (?,?,?,?)", alias_rows)
    log("lemma aliases", len(alias_rows))
    log("variant links", len(variant_rows))
    # Release R: a headword whose own entries print no meaning (a pure pointer: "πώνω, Dor. and Aeol.
    # = πίνω") takes the short gloss of the headword its variant link names, labelled as such.
    gloss_of = {r[0]: (r[7], r[8]) for r in lemma_rows}
    borrowed = []
    for a, b, rel, dic, ev in variant_rows:
        if not gloss_of.get(a, (None,))[0] and gloss_of.get(b, (None,))[0]:
            target = next((h for h, i in lemma_ids.items() if i == b), "")
            borrowed.append((gloss_of[b][0], f"{gloss_of[b][1]} (via {target})", a))
            gloss_of[a] = (gloss_of[b][0], "borrowed")
    ix.executemany("UPDATE lemma SET gloss=?, gloss_source=? WHERE id=?", borrowed)
    log("glosses borrowed through variant links", len(borrowed))
    rules = {h: r for h, (h2, r) in ((k, v) for k, v in canon_cache.items()) if r}
    form_rows, fl_rows = [], []
    for f, i in form_ids.items():
        status, _ = morph.get(f, ("missing", []))
        cands = evidence.get(f) or {}
        srcs = 0
        for c in cands.values():
            srcs |= c["src"]
        label = ("parsed" if srcs & MORPH else "generated" if srcs & GENERATED else "recorded" if srcs & RECORDED
                 else "headword" if srcs & HEADWORD else "unknown")
        normalised = next((c["rules"] for c in cands.values() if c["rules"]), None)
        form_rows.append((i, f, fold(f), forms.get(f, (0, 0))[0], label,
                          json.dumps(sorted(normalised), ensure_ascii=False) if normalised else None))
        ranked_f = posterior.get(f, [])
        if f in elided_mass:
            # Elided spelling: readings in the order of the elision model's token readings.
            mass = elided_mass[f]
            total = sum(mass.values()) or 1.0
            ranked_f = sorted(((h, mass[h] / total) for h, _ in ranked_f), key=lambda kv: (-kv[1], kv[0]))
        for rank, (h, p) in enumerate(ranked_f[:6]):
            parses = [x for x in dict.fromkeys(cands[h].get("parses") or []) if x][:6]
            fl_rows.append((i, lid(h), rank, round(p, 4), cands[h]["src"],
                            json.dumps(parses, ensure_ascii=False) if parses else None))
    ix.executemany("INSERT INTO form VALUES (?,?,?,?,?,?)", form_rows)
    ix.executemany("INSERT INTO form_lemma VALUES (?,?,?,?,?,?)", fl_rows)
    # lemmas only reached as alternates
    missing = [(i, h, fold(h)) for h, i in lemma_ids.items() if i > len(lemma_rows)]
    for i, h, k in missing:
        gloss, gsrc, full = short_gloss_for(h, heads)
        ix.execute("INSERT INTO lemma VALUES (?,?,?,?,?,?,?,?,?)",
                   (i, h, k, None, head_rule.get(h) or ("headword" if heads.lookup(h)[0] else None), 0, 0, gloss, gsrc))
    ix.executescript("""
      CREATE INDEX lemma_key ON lemma(key); CREATE INDEX lemma_lemma ON lemma(lemma);
      CREATE INDEX form_key ON form(key); CREATE INDEX form_form ON form(form);
      CREATE INDEX passage_id ON passage(id); CREATE INDEX passage_author ON passage(author);
      CREATE INDEX form_lemma_lemma ON form_lemma(lemma_id);
      CREATE INDEX gloss_term ON lemma_gloss_term(term);
    """)
    coverage = {f"{k[0]}|{'edited' if k[1] else 'other'}": dict(v) for k, v in by_group.items()}
    meta = {
        "version": "melos-lemma-index-v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus": str(args.corpus), "corpus_size": os.path.getsize(args.corpus),
        "corpus_mtime_ns": os.stat(args.corpus).st_mtime_ns,
        "engine_revision": (st.execute("SELECT value FROM meta WHERE key='engine_revision'").fetchone() or [None])[0],
        "stages": {k: json.loads(v) for k, v in st.execute("SELECT key,value FROM meta WHERE key IN ('forms','morph','generate')")},
        "tokens": stats, "coverage_by_group": coverage, "lemmas": len(lemma_ids), "forms": len(form_ids),
        "passages": pid, "context_passages": len(context), "assemble_seconds": round(time.time() - started),
        "recorded_lemmas_dropped": {"lemmas": len(dropped_recorded), "examples": dropped_recorded.most_common(20)},
        "derived_links": {"headwords": len(heads.derived),
                          "examples": [[d, l["base"], l["relation"], l["entry_id"]] for d, l in sorted(heads.derived.items())[:40]],
                          "method": "an adverb, comparative or superlative headword whose own dictionary entry calls it "
                                    "the derived form of another headword is counted under that headword (release R)"},
        "dialect_rules": {"tokens": stats.get("dialect_rule_tokens"), "changed": stats.get("dialect_rule_changed")},
        "elision_model": ({k: elision.data.get(k) for k in ("version", "built_at", "split", "params", "train")}
                          if elision is not None else None),
        "source_bits": {"1": "local Morpheus parse of the printed form", "2": "lemma recorded for this spelling in a source annotation (treebank/lexicon form list)",
                        "4": "Morpheus parse of a generated dialect/elision spelling (release N rules)",
                        "8": "printed form is itself a dictionary headword", "16": "contextual model (OdyCy) names the same lemma",
                        "32": "contextual model changed the choice among parser lemmas", "64": "word printed with brackets or underdots",
                        "128": "elided word: reading ranked by the elision model (treebank train prior, restored spellings' frequency, context)"},
        "method": ("Distinct printed spellings are analysed once: local Morpheus, then release-N generate-and-test spellings "
                   "for forms of edited text that Morpheus does not know; parser lemmas are read to dictionary headwords "
                   "(headword, elided lemma, lemma as recorded form, Lesbian psilosis, dialect correspondences). Candidate "
                   "lemmas of one spelling are ranked by evidence weight times a corpus prior (EM over token counts); "
                   "where the contextual model ran, its lemma and POS rescore the candidates, but it never displaces the "
                   "only recorded/headword reading unless it names that lemma itself. Confidence is the normalised score, "
                   "not a calibrated probability."),
    }
    ix.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(meta, ensure_ascii=False),))
    ix.commit()
    ix.execute("VACUUM")
    ix.close()
    log("assembled", out, os.path.getsize(out), "bytes", round(time.time() - started), "s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["forms", "morph", "generate", "context", "assemble"])
    p.add_argument("--corpus", default=str(ROOT / "data/corpus.sqlite"))
    p.add_argument("--build", default=str(ROOT / "runtime/lemma-build.sqlite"))
    p.add_argument("--out", default=str(ROOT / "data/lemma_index.sqlite"))
    p.add_argument("--lexica", default=str(ROOT / "data/lexica"))
    p.add_argument("--endpoint", default=os.getenv("MELOS_MORPHEUS_LOCAL", ""))
    p.add_argument("--threads", type=int, default=16)
    p.add_argument("--model", default="/syntax-model")
    p.add_argument("--where", default="")
    p.add_argument("--all-records", action="store_true", help="context: every Greek record, not only edited text")
    p.add_argument("--elision-model", default="", help="assemble: release Q elided-word model (train_elision_model.py)")
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--shard", type=int, default=0)
    args = p.parse_args()
    {"forms": stage_forms, "morph": stage_morph, "generate": stage_generate,
     "context": stage_context, "assemble": stage_assemble}[args.stage](args)


if __name__ == "__main__":
    main()
