"""Read API over the corpus headword index (data/lemma_index.sqlite, release O).

Built by scripts/build_lemma_index.py: every Greek word token of the corpus carries its
top-ranked headword, a confidence (normalised evidence score, not a calibrated probability)
and source bits; each spelling keeps its ranked alternatives. This module answers
Logeion/TLG-style questions from it: lemma search over all inflected forms, frequency,
concordance (KWIC), collocations, distribution by author/genre/period, phrase and proximity
search by lemma, English -> Greek headwords through dictionary glosses, and concept diachrony.

Default scope is the searchable edited Greek text (kind 'text', quality source_text or
machine_corrected_ocr), as for passage search; `include_reference` widens it to every
indexed Greek record (OCR pages, commentary, apparatus). Dates are author biography claims
(backend.author_catalogue); undated authors are counted separately, never placed in time.
"""
from __future__ import annotations

import json
import re
import math
import os
import sqlite3
import threading
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from .author_catalogue import PERIODS, author_record, display_work, passage_date
from .lemma_calibration import probability as calibrated_probability, summary as calibration_summary
from .lemma_glosses_index import english_terms, stem
from .lemma_tokens import fold

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data/lemma_index.sqlite"
SEARCHABLE = ("source_text", "machine_corrected_ocr")
GREEK = lambda text: any("Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿" for c in text or "")  # noqa: E731
SOURCE_BITS = {1: "parser", 2: "recorded_form", 4: "generated_spelling", 8: "printed_headword",
               16: "context_agrees", 32: "context_chose", 64: "damaged_word", 128: "elision_model"}
MAX_SCAN_PASSAGES = 40000
SMALL_GROUP_TOKENS = 50000   # release P: rates over fewer words are flagged small_sample
UNMAPPED_ORDER = 9999
COUNTING_NOTE = ("Each text is counted once: where several collections hold the same TLG work, only the collection "
                 "with the most words of it in the scope; a fragment printed by several editions (same author, at least "
                 "half of the shorter text's words shared, the rule search uses to fold editions) once, in the edition "
                 "holding most of it; a passage repeated word for word within one work (a refrain) once.")


def rate_fields(count, total):
    """Rate per 10,000 words with a 95% Wilson score interval; small_sample when the group has
    fewer than 50,000 words (one poem can move the rate)."""
    if not total:
        return {"per_10k": None, "per_10k_ci95": None, "small_sample": True}
    z, p = 1.96, count / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return {"per_10k": round(p * 1e4, 2), "per_10k_ci95": [round(max(0.0, centre - half) * 1e4, 2),
                                                           round((centre + half) * 1e4, 2)],
            "small_sample": total < SMALL_GROUP_TOKENS}
PERIOD_ORDER = [label for label, _, _ in PERIODS]
SCHEMA = """
      
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE lemma(id INTEGER PRIMARY KEY, lemma TEXT NOT NULL, key TEXT NOT NULL, pos TEXT,
                         normalisation TEXT, tokens INTEGER, passages INTEGER, gloss TEXT, gloss_source TEXT);
      CREATE TABLE form(id INTEGER PRIMARY KEY, form TEXT NOT NULL, key TEXT NOT NULL, tokens INTEGER,
                        status TEXT, normalised TEXT);
      CREATE TABLE form_lemma(form_id INTEGER, lemma_id INTEGER, rank INTEGER, prob REAL, src INTEGER, parses TEXT,
                              PRIMARY KEY(form_id, rank)) WITHOUT ROWID;
      CREATE TABLE passage(pid INTEGER PRIMARY KEY, id TEXT NOT NULL, kind TEXT, quality TEXT, language TEXT,
                           author TEXT, author_label TEXT, work TEXT, citation TEXT, source TEXT,
                           ntok INTEGER, nlemma INTEGER);
      CREATE TABLE tok(pid INTEGER PRIMARY KEY, lemmas BLOB, forms BLOB, conf BLOB, src BLOB, starts BLOB, ends BLOB);
      CREATE TABLE posting(lemma_id INTEGER, pid INTEGER, n INTEGER, PRIMARY KEY(lemma_id, pid)) WITHOUT ROWID;
      CREATE TABLE lemma_gloss_term(term TEXT, lemma_id INTEGER, field INTEGER, weight REAL);
      CREATE TABLE lemma_prior(lemma_id INTEGER PRIMARY KEY, tokens INTEGER);
      CREATE TABLE lemma_variant(lemma_id INTEGER, target_id INTEGER, relation TEXT, dictionary TEXT, evidence TEXT);
      CREATE TABLE token_alt(pid INTEGER, i INTEGER, lemma_id INTEGER, prob REAL, PRIMARY KEY(pid, i)) WITHOUT ROWID;
      CREATE TABLE passage_repeat(pid INTEGER PRIMARY KEY, first_pid INTEGER);
      CREATE TABLE token_flag(pid INTEGER, i INTEGER, flags INTEGER, PRIMARY KEY(pid, i)) WITHOUT ROWID;
      CREATE TABLE lemma_alias(alias TEXT, lemma_id INTEGER, relation TEXT, entry_id TEXT);
    """


def index_path():
    return Path(os.getenv("MELOS_LEMMA_INDEX", str(DEFAULT_PATH)))


def edition_groups_path():
    """Release U: edition groups (scripts/build_edition_groups.py); env MELOS_EDITION_GROUPS."""
    return Path(os.getenv("MELOS_EDITION_GROUPS", str(ROOT / "data/edition_groups.sqlite")))


def load_attributions():
    """{passage id: attributed poet or collection label} (release P); {} when absent."""
    path = Path(os.getenv("MELOS_ATTRIBUTIONS", str(ROOT / "data/metadata/attributions.json")))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {pid: label for pid, label in data.get("passages", {}).items()}


def _nfc(text):
    return unicodedata.normalize("NFC", str(text or "")).strip()


def _headword_key(text):
    from .lemma_glosses import headword_key
    return headword_key(text)


_LINE_NUMBER = re.compile(r"(?<!\S)\d{1,4}[a-z]?(?!\S)")


def display_context(text, start, end, width):
    """Release Q: (left, right, printed line numbers) around text[start:end] for display. A number
    standing alone between words is an edition's printed line number (Corinna "57 … 58"): it is
    removed from the display text and returned as line metadata."""
    left_raw, right_raw = text[max(0, start - width):start], text[end:end + width]
    numbers = _LINE_NUMBER.findall(left_raw) + _LINE_NUMBER.findall(right_raw)
    left = " ".join(_LINE_NUMBER.sub(" ", left_raw).split())
    right = " ".join(_LINE_NUMBER.sub(" ", right_raw).split())
    return left, right, numbers


def describe_source(bits):
    return [name for bit, name in SOURCE_BITS.items() if bits & bit]


class LemmaIndex:
    def __init__(self, path=None):
        self.path = Path(path or index_path())
        if not self.path.exists():
            raise FileNotFoundError("Lemma index not built: " + str(self.path))
        self._local = threading.local()
        con = self.con()
        self.manifest = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        rows = con.execute("SELECT pid,id,kind,quality,author,author_label,work,citation,source,ntok FROM passage ORDER BY pid").fetchall()
        n = (rows[-1][0] + 1) if rows else 1
        self.pid_id = [None] * n
        self.meta = [None] * n
        self.ntok = np.zeros(n, dtype=np.int32)
        self.edited = np.zeros(n, dtype=bool)
        self.author_of = [""] * n
        self.id_pid = {}
        for pid, pid_text, kind, quality, author, label, work, citation, source, ntok in rows:
            self.pid_id[pid] = pid_text
            self.id_pid[pid_text] = pid
            self.meta[pid] = (kind, quality, label, work, citation, source)
            self.ntok[pid] = ntok
            self.edited[pid] = kind == "text" and quality in SEARCHABLE
            self.author_of[pid] = author or label or ""
        self.authors = {}
        for name in set(self.author_of):
            self.authors[name] = author_record(name)
        # Release P: a passage's date is its author's sourced claim, else the sourced claim of the
        # poet its record names (Greek Anthology epigrams) or of its collection (CTS tlg0013 ->
        # Homeric Hymns): data/metadata/attributions.json, built by scripts/collect_chronology.py.
        attributions = load_attributions()
        self.pid_period = [None] * n
        self.pid_year = np.full(n, 99999.0)
        self.pid_date = [None] * n
        cache = {}
        for pid, pid_text in enumerate(self.pid_id):
            if pid_text is None:
                continue
            key = (self.author_of[pid], attributions.get(pid_text))
            if key not in cache:
                cache[key] = passage_date(*key)
            date, period, basis = cache[key]
            self.pid_period[pid] = period
            self.pid_date[pid] = date
            if date and date.get("year") is not None:
                self.pid_year[pid] = date["year"]
        self._scope_counts = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ basics
    def con(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def status(self):
        m = self.manifest
        return {"ready": True, "version": m.get("version"), "built_at": m.get("built_at"), "lemmas": m.get("lemmas"),
                "forms": m.get("forms"), "passages": m.get("passages"), "tokens": m.get("tokens"),
                "bytes": self.path.stat().st_size, "method": m.get("method"),
                "context_passages": m.get("context_passages"), "calibration": calibration_summary()}

    def scope_mask(self, include_reference=False, author="", genre=""):
        mask = np.ones(len(self.pid_id), dtype=bool) if include_reference else self.edited.copy()
        mask[0] = False
        if author or genre:
            wanted_a = fold(author_record(author)["author"]) if author else None
            keep = np.zeros_like(mask)
            for pid, name in enumerate(self.author_of):
                if not mask[pid]:
                    continue
                info = self.authors.get(name) or {}
                if wanted_a and fold(info.get("author") or name) != wanted_a:
                    continue
                if genre and (info.get("genre") or "").casefold() != genre.casefold():
                    continue
                keep[pid] = True
            mask = keep
        return mask

    def lemma_row(self, lemma_id):
        row = self.con().execute("SELECT * FROM lemma WHERE id=?", (int(lemma_id),)).fetchone()
        return dict(row) if row else None

    def lemma_brief(self, lemma_id):
        row = self.lemma_row(lemma_id) or {}
        out = {"lemma_id": row.get("id"), "lemma": row.get("lemma"), "gloss": row.get("gloss"),
               "gloss_source": row.get("gloss_source"), "pos": row.get("pos"), "tokens_all_records": row.get("tokens")}
        if row.get("id") and not row.get("gloss"):
            # Release P: a variant headword without its own gloss (πότνα) shows the gloss of the
            # headword its dictionary entry names (πότνια), labelled as such.
            for link in self.variant_links().get(int(row["id"]), []):
                if link["direction"] != "variant_of":
                    continue
                target = self.lemma_row(link["lemma_id"]) or {}
                if target.get("gloss"):
                    out.update(gloss=target["gloss"], gloss_source=target.get("gloss_source"),
                               gloss_via_variant=target.get("lemma"))
                    break
        return out

    def variant_links(self):
        """{lemma_id: [{lemma_id, direction (variant_of | has_variant), relation, dictionary, evidence}]}."""
        with self._lock:
            if getattr(self, "_variants", None) is not None:
                return self._variants
        links = defaultdict(list)
        try:
            rows = self.con().execute("SELECT lemma_id, target_id, relation, dictionary, evidence FROM lemma_variant").fetchall()
        except sqlite3.OperationalError:
            rows = []  # an index built before release P
        for a, b, relation, dictionary, evidence in rows:
            links[a].append({"lemma_id": b, "direction": "variant_of", "relation": relation, "dictionary": dictionary,
                             "evidence": evidence})
            links[b].append({"lemma_id": a, "direction": "has_variant", "relation": relation, "dictionary": dictionary,
                             "evidence": evidence})
        with self._lock:
            self._variants = dict(links)
        return self._variants

    def variant_group(self, lemma_id):
        """The headwords linked to this one as dialect/poetic variants (one hop each way, then their
        own links: the connected group), or None. Counts are not merged unless asked."""
        links = self.variant_links()
        lemma_id = int(lemma_id)
        if lemma_id not in links:
            return None
        group, todo = {lemma_id}, [lemma_id]
        while todo and len(group) < 12:
            for link in links.get(todo.pop(), []):
                if link["lemma_id"] not in group:
                    group.add(link["lemma_id"])
                    todo.append(link["lemma_id"])
        # Release Q: headwords differing only in capitalisation (ἔρως / Ἔρως) are counted with the group,
        # so they are named as members too.
        case_of = {}
        for i in list(group):
            for j in self.case_variants(i):
                if j not in group:
                    case_of[j] = i
        group |= set(case_of)
        members = []
        for i in sorted(group, key=lambda i: -(self.lemma_row(i) or {}).get("tokens", 0)):
            row = self.lemma_row(i) or {}
            members.append({"lemma_id": i, "lemma": row.get("lemma"), "gloss": row.get("gloss"),
                            "tokens_all_records": row.get("tokens"),
                            "links": [dict(l, lemma=(self.lemma_row(l["lemma_id"]) or {}).get("lemma"))
                                      for l in links.get(i, []) if l["lemma_id"] in group]
                            + ([{"lemma_id": case_of[i], "direction": "capitalisation_of",
                                 "relation": "capitalised spelling",
                                 # Release U: never a null label (the lexicon page printed "(null)").
                                 "dictionary": "Melos capitalisation rule (no dictionary link)",
                                 "evidence": "same letters, other capitalisation",
                                 "lemma": (self.lemma_row(case_of[i]) or {}).get("lemma") or ""}]
                               if i in case_of else [])})
        return {"lemma_ids": [m["lemma_id"] for m in members], "members": members,
                "note": ("Headwords a dictionary entry names as dialect or poetic forms of one another; they stay "
                         "separate headwords. Pass combine_variants=true to count them together.")}

    def expand_variants(self, lemma_ids):
        out = list(lemma_ids)
        for lemma_id in lemma_ids:
            group = self.variant_group(lemma_id)
            for i in (group or {}).get("lemma_ids", []):
                for j in self.case_variants(i):
                    if j not in out:
                        out.append(j)
        return out

    # ------------------------------------------------------------------ release P: works, periods
    def work_info(self):
        """From the citation index: per passage the work order (TLG work number, else last) and
        whether the passage belongs to a second collection of a text another collection holds in
        full (same TLG work; the collection with the most cited passages is primary). None when
        the citation index is not deployed."""
        with self._lock:
            if getattr(self, "_work_info", None) is not None:
                return self._work_info or None
        try:
            from .citations import get_citation_index
            cit = get_citation_index()
        except (FileNotFoundError, ImportError):
            with self._lock:
                self._work_info = {}
            return None
        n = len(self.pid_id)
        order = np.full(n, UNMAPPED_ORDER, dtype=np.int32)
        duplicate = np.zeros(n, dtype=bool)
        work_key = [None] * n
        tlg_group = np.full(n, -1, dtype=np.int32)
        group_ids = {}
        works = {w["work_key"]: w for w in cit.works}
        rows = cit.con().execute("SELECT work_key, passage_id, source FROM locus").fetchall()
        # The collection (source) holding most cited passages of a TLG work is primary; the same
        # work in another collection (Perseus 20-line chunks beside OGC lines) is a duplicate.
        size = Counter()
        for key, passage_id, source in rows:
            w = works.get(key) or {}
            if w.get("tlg_work"):
                size[(w["tlg_author"], w["tlg_work"], source)] += 1
        primary = {}
        for (a, w, source), count in size.items():
            if (a, w) not in primary or count > size[(a, w, primary[(a, w)])]:
                primary[(a, w)] = source
        for key, passage_id, source in rows:
            pid = self.id_pid.get(passage_id)
            if pid is None:
                continue
            w = works.get(key) or {}
            work_key[pid] = key
            if w.get("tlg_work"):
                digits = "".join(c for c in w["tlg_work"] if c.isdigit())
                order[pid] = int(digits or UNMAPPED_ORDER)
                duplicate[pid] = primary.get((w["tlg_author"], w["tlg_work"])) != source
                tlg_group[pid] = group_ids.setdefault((w["tlg_author"], w["tlg_work"]), len(group_ids))
            else:
                order[pid] = UNMAPPED_ORDER - 1
        value = {"order": order, "duplicate": duplicate, "work_key": work_key, "works": works, "citations": cit,
                 "tlg_group": tlg_group}
        with self._lock:
            self._work_info = value
        return value

    def token_flags(self, pid):
        """{token i: flags} (release Q table token_flag; bit 1 = the contextual model named another
        reading of the spelling). Empty for an older index."""
        try:
            return dict(self.con().execute("SELECT i, flags FROM token_flag WHERE pid=?", (int(pid),)).fetchall())
        except sqlite3.OperationalError:
            return {}

    def repeated(self):
        """Boolean per passage: a word-for-word repeat of an earlier passage of the same collection
        and work (release Q index table passage_repeat; all False for an older index)."""
        with self._lock:
            if getattr(self, "_repeated", None) is not None:
                return self._repeated
        out = np.zeros(len(self.pid_id), dtype=bool)
        try:
            for (pid,) in self.con().execute("SELECT pid FROM passage_repeat"):
                if pid < len(out):
                    out[pid] = True
        except sqlite3.OperationalError:
            pass
        with self._lock:
            self._repeated = out
        return out

    def edition_groups(self):
        """Release U: per passage the edition group id (-1 none) and whether the passage is counted
        (False for another edition's copy of a fragment the group's primary collection holds). From
        scripts/build_edition_groups.py; no groups (every passage counted) when the file is absent."""
        with self._lock:
            if getattr(self, "_edition_groups", None) is not None:
                return self._edition_groups
        n = len(self.pid_id)
        group = np.full(n, -1, dtype=np.int64)
        counted = np.ones(n, dtype=bool)
        primary = {}
        path = edition_groups_path()
        manifest = None
        if path.exists():
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                for pid_text, grp, is_counted, source in con.execute(
                        "SELECT passage_id, grp, counted, primary_source FROM edition_group"):
                    pid = self.id_pid.get(pid_text)
                    if pid is None:
                        continue
                    group[pid] = grp
                    counted[pid] = bool(is_counted)
                    primary[grp] = source
                row = con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
                manifest = json.loads(row[0]) if row else None
            finally:
                con.close()
        value = {"group": group, "counted": counted, "primary": primary, "manifest": manifest}
        with self._lock:
            self._edition_groups = value
        return value

    def count_mask(self, mask):
        """Release Q: the passages counted in frequency tables. One collection of each text (where
        several collections hold the same TLG work, the one with the most cited passages, as n-grams
        and collocations count, chosen by its words inside the scope) and a passage repeated word for word
        within one work once. Release U: one edition of each fragment (edition groups, the search
        folding identity), so Sappho 154 printed by five editions counts once."""
        key = ("count_mask", hash(mask.tobytes()))
        with self._lock:
            if key in self._scope_counts:
                return self._scope_counts[key]
        out = mask & ~self.repeated() & self.edition_groups()["counted"]
        info = self.work_info()
        if info is not None:
            # The primary collection is chosen inside the scope (most tokens of the work in scope), so
            # a text whose larger collection lies outside the scope (OGC Anthology records that are
            # not searchable edited text) keeps its in-scope copy.
            group = info["tlg_group"]
            sel = np.flatnonzero(out & (group >= 0))
            size = Counter()
            for pid in sel.tolist():
                size[(int(group[pid]), self.meta[pid][5])] += int(self.ntok[pid])
            primary = {}
            for (g, source), n in size.items():
                if g not in primary or n > size[(g, primary[g])]:
                    primary[g] = source
            for pid in sel.tolist():
                if primary[int(group[pid])] != self.meta[pid][5]:
                    out[pid] = False
        with self._lock:
            self._scope_counts[key] = out
        return out

    def period_mask(self, period):
        """Passages of one period label, or 'undated'."""
        labels = getattr(self, "_period_labels", None)
        if labels is None:
            labels = self._period_labels = np.asarray([p or "undated" for p in self.pid_period], dtype=object)
        if period != "undated" and period not in PERIOD_ORDER:
            raise ValueError("period must be one of: " + ", ".join(PERIOD_ORDER + ["undated"]))
        return labels == period

    def sort_key(self, order):
        """Concordance/search ordering: by author date (sourced), author, work order (TLG work
        number where known, else after), then the passage's place in its collection."""
        info = self.work_info()
        work_order = info["order"] if info else None

        def chronological(pid):
            return (self._year(pid), self.author_of[pid], int(work_order[pid]) if work_order is not None else 0, pid)

        def by_author(pid):
            return (self.author_of[pid], int(work_order[pid]) if work_order is not None else 0, pid)
        return chronological if order == "chronological" else by_author

    def _edition_record(self, pid):
        kind, quality, label, work, citation, source = self.meta[pid]
        return {"id": self.pid_id[pid], "source": source, "citation": citation, "quality": quality, "work": work,
                "display_work": display_work(work)}

    def other_collections(self, pid):
        """Passages of other collections holding the same TLG work at an overlapping locus."""
        info = self.work_info()
        if not info or not info["work_key"][pid]:
            return []
        cit = info["citations"]
        key = info["work_key"][pid]
        w = info["works"].get(key) or {}
        if not w.get("tlg_work"):
            return []
        row = cit.con().execute("SELECT start, end FROM locus WHERE passage_id=? LIMIT 1", (self.pid_id[pid],)).fetchone()
        if not row:
            return []
        others = [x for x in cit.works if x["tlg_author"] == w["tlg_author"] and x["tlg_work"] == w["tlg_work"]]
        hits, _ = cit.loci(others, json.loads(row["start"]), json.loads(row["end"]), limit=12)
        out = []
        for h in hits:
            if h["source"] == self.meta[pid][5]:
                continue
            other = self.id_pid.get(h["passage_id"])
            if other is not None and self.edited[other] == self.edited[pid]:
                out.append(self._edition_record(other))
        return out[:4]

    def fold_lines(self, keyed):
        """keyed: [(pid, key)] in display order. Lines with the same key from another collection
        (source) are folded under the first: {(pid, key): primary (pid, key)}."""
        first, folded = {}, {}
        for pid, key in keyed:
            if key in first:
                primary = first[key]
                if self.meta[primary[0]][5] != self.meta[pid][5]:
                    folded[(pid, key)] = primary
            else:
                first[key] = (pid, key)
        return folded


    def calibration_group(self, pid):
        """Release R: the calibration group (genre group | dialect) of a passage."""
        from .lemma_calibration import context_group
        from .passage_dialect import passage_dialect
        label = self.author_of[pid]
        info = self.authors.get(label) or {}
        return context_group(info.get("genre"), passage_dialect({"author": label, "id": self.pid_id[pid]}))

    def tokens(self, pid):
        row = self.con().execute("SELECT lemmas,forms,conf,src,starts,ends FROM tok WHERE pid=?", (int(pid),)).fetchone()
        if not row:
            return None
        return (np.frombuffer(row[0], dtype=np.uint32), np.frombuffer(row[1], dtype=np.uint32),
                np.frombuffer(row[2], dtype=np.uint8), np.frombuffer(row[3], dtype=np.uint8),
                np.frombuffer(row[4], dtype=np.uint32), np.frombuffer(row[5], dtype=np.uint16))

    def postings(self, lemma_id):
        rows = self.con().execute("SELECT pid,n FROM posting WHERE lemma_id=?", (int(lemma_id),)).fetchall()
        if not rows:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
        arr = np.asarray(rows, dtype=np.int64)
        return arr[:, 0], arr[:, 1]

    def _posting_array(self):
        with self._lock:
            if getattr(self, "_postings_all", None) is None:
                rows = self.con().execute("SELECT lemma_id,pid,n FROM posting").fetchall()
                self._postings_all = np.asarray(rows, dtype=np.int32).reshape(-1, 3)
            return self._postings_all

    def scope_counts(self, include_reference=False, mask=None):
        """Token count per lemma id inside the scope (cached per scope)."""
        mask = self.scope_mask(include_reference) if mask is None else mask
        key = ("counts", hash(mask.tobytes()))
        with self._lock:
            if key in self._scope_counts:
                return self._scope_counts[key]
        rows = self._posting_array()
        n_lemmas = int(rows[:, 0].max()) + 1 if len(rows) else 1
        keep = mask[rows[:, 1]] if len(rows) else np.zeros(0, dtype=bool)
        counts = np.bincount(rows[keep, 0], weights=rows[keep, 2], minlength=n_lemmas).astype(np.int64)
        with self._lock:
            if len(self._scope_counts) > 32:
                self._scope_counts.clear()
            self._scope_counts[key] = counts
        return counts

    def period_masks(self, include_reference=False):
        key = ("periods", bool(include_reference))
        with self._lock:
            if key in self._scope_counts:
                return self._scope_counts[key]
        mask = self.scope_mask(include_reference)
        labels = np.asarray([p or "" for p in self.pid_period], dtype=object)
        out = {label: mask & (labels == label) for label in PERIOD_ORDER}
        with self._lock:
            self._scope_counts[key] = out
        return out

    def function_words(self, include_reference=False, top=80):
        """Very frequent lemmas and closed-class words (article, particles, conjunctions, prepositions, pronouns)."""
        key = ("function", bool(include_reference))
        with self._lock:
            if key in self._scope_counts:
                return self._scope_counts[key]
        counts = self.scope_counts(include_reference)
        frequent = set(np.argsort(-counts)[:top].tolist())
        closed = {r[0] for r in self.con().execute(
            "SELECT id FROM lemma WHERE pos IN ('article','particle','conjunction','preposition','pronoun') "
            "OR normalisation IS NULL")}  # and strings that are no dictionary headword (annotation noise)
        out = frequent | closed
        with self._lock:
            self._scope_counts[key] = out
        return out

    # ------------------------------------------------------------------ resolution
    def resolve(self, query, limit=8):
        """Headwords a query names: lemma (exact, folded), else the ranked readings of a printed form."""
        q = _nfc(query)
        if not q:
            return []
        con = self.con()
        if q.startswith("lemma:"):
            q = q[6:].strip()
        out, seen = [], set()

        def add(row, via, prob=None):
            if row["id"] in seen:
                return
            seen.add(row["id"])
            out.append({"lemma_id": row["id"], "lemma": row["lemma"], "gloss": row["gloss"], "pos": row["pos"],
                        "tokens_all_records": row["tokens"], "via": via, **({"form_probability": prob} if prob is not None else {})})

        if GREEK(q):
            for value in dict.fromkeys([q, _headword_key(q)]):
                for row in con.execute("SELECT * FROM lemma WHERE lemma=? ORDER BY tokens DESC", (value,)):
                    add(row, "headword")
            try:
                # Release R: a headword counted under another (ταχέως under ταχύς, πώνω under πίνω)
                for row in con.execute("SELECT l.*, a.relation AS relation FROM lemma_alias a JOIN lemma l "
                                       "ON l.id=a.lemma_id WHERE a.alias IN (?, ?)", (q, _headword_key(q))):
                    add(row, "alias_" + row["relation"])
            except sqlite3.OperationalError:
                pass  # an index older than release R has no lemma_alias table
            if not out:
                for row in con.execute("SELECT * FROM lemma WHERE key=? ORDER BY tokens DESC LIMIT ?", (fold(q), limit)):
                    add(row, "headword_without_accents")
            form_rows = con.execute("SELECT l.*, fl.prob FROM form f JOIN form_lemma fl ON fl.form_id=f.id "
                                    "JOIN lemma l ON l.id=fl.lemma_id WHERE f.form=? ORDER BY fl.rank", (q,)).fetchall()
            if not form_rows:
                form_rows = con.execute("SELECT l.*, max(fl.prob) prob FROM form f JOIN form_lemma fl ON fl.form_id=f.id "
                                        "JOIN lemma l ON l.id=fl.lemma_id WHERE f.key=? GROUP BY l.id ORDER BY prob DESC LIMIT ?",
                                        (fold(q), limit)).fetchall()
            for row in form_rows:
                add(row, "printed_form_reading", round(row["prob"], 3))
            return out[:limit]
        out.extend(self.transliterated_lemmas(q))
        seen = {item["lemma_id"] for item in out}
        # Release Q: English is read through dictionary sense head meanings (whole words: "moon" is
        # σελήνη, μήνη, not Ἰώ "identified with the moon"), as concept diachrony does; the release O
        # stem match answers only when no sense has the word as its head meaning. Search keeps stems.
        english = self.head_meaning_lemmas(q, limit=limit * 3)
        if english:
            # A headword whose own (displayed) gloss has the word as its head meaning comes first; one
            # that has it only in a secondary sense (Ἰώ "Io", sense "the moon") is kept only when no
            # headword has it as its main meaning.
            from .lemma_glosses_index import head_meanings
            primary = [r for r in english if set(r["matched_terms"]) & set(head_meanings(r.get("gloss") or ""))]
            english = (primary or english)[:limit]
        else:
            english = self.english_lemmas(q, limit=limit)
        for item in english:
            if item["lemma_id"] not in seen:
                out.append(item)
        return out[:limit]

    def transliterated_lemmas(self, query, limit=3):
        """A Latin-letter word read as a Greek headword (eros -> ἔρως, ἔρος); retrieval keys only."""
        if len(query.split()) != 1:
            return []
        try:
            from .morphology import query_variants
            keys = [k for k in query_variants(query) if GREEK(k)]
        except Exception:  # noqa: BLE001
            return []
        # Latin o/e do not say whether omicron/omega or epsilon/eta was meant: try both (bounded).
        expanded = []
        for key in dict.fromkeys(fold(k) for k in keys):
            variants = [""]
            for ch in key:
                options = {"ο": "οω", "ω": "ωο"}.get(ch, ch)
                variants = [v + o for v in variants for o in options][:32]
            expanded.extend(variants)
        out = []
        for key in dict.fromkeys(expanded):
            for row in self.con().execute("SELECT * FROM lemma WHERE key=? AND tokens>=5 ORDER BY tokens DESC LIMIT ?",
                                          (key, limit)):
                out.append({"lemma_id": row["id"], "lemma": row["lemma"], "gloss": row["gloss"], "pos": row["pos"],
                            "tokens_all_records": row["tokens"], "via": "transliterated_headword"})
        out.sort(key=lambda r: -r["tokens_all_records"])
        return out[:limit]

    def head_meaning_terms(self, query, lemma_ids=()):
        """Release U: '=word' head-meaning terms of a concept: its own words and the head meanings of the
        first chosen headwords (lemma_gloss_term field 3, weight at least 0.2), without stop words."""
        from .lemma_glosses_index import STOP, _WORD, singular
        terms = {"=" + singular(w.lower()) for w in _WORD.findall(query or "") if w.lower() not in STOP and len(w) > 1}
        for lemma_id in list(lemma_ids)[:4]:
            for term, weight in self.con().execute(
                    "SELECT term, weight FROM lemma_gloss_term WHERE lemma_id=? AND field=3", (int(lemma_id),)):
                if weight >= 0.2 and term[1:] not in STOP and len(term) > 3:
                    terms.add(term)
        return terms

    def head_meaning_lemmas(self, query, limit=6):
        """Release P (concepts): Greek headwords one of whose dictionary senses has a query word as
        its head meaning (lemma_glosses_index.head_meanings: "the moon" -> moon; "Io, identified with
        the moon" -> io only). Whole words, not stems: "love" matches ἔρως "love", not φίλος
        "loved, dear". Empty for an index built before release P."""
        from .lemma_glosses_index import STOP, _WORD, singular
        words = [singular(w.lower()) for w in _WORD.findall(query or "") if w.lower() not in STOP and len(w) > 1]
        words = list(dict.fromkeys(words))
        if not words:
            return []
        con = self.con()
        score, matched = defaultdict(float), defaultdict(set)
        for word in words:
            for lemma_id, weight in con.execute(
                    "SELECT lemma_id, weight FROM lemma_gloss_term WHERE term=? AND field=3", ("=" + word,)):
                score[lemma_id] += weight
                matched[lemma_id].add(word)
        need = len(words) if len(words) <= 2 else math.ceil(len(words) * 2 / 3)
        ids = [i for i in score if len(matched[i]) >= need]
        if not ids:
            return []
        rows = {r["id"]: r for r in con.execute(f"SELECT * FROM lemma WHERE id IN ({','.join('?' * len(ids))})", ids)}
        ranked = sorted(((score[i] * (1 + 0.15 * math.log1p(rows[i]["tokens"])), i) for i in ids
                         if i in rows and rows[i]["tokens"]), reverse=True)
        if not ranked:
            return []
        best = ranked[0][0]
        out = []
        for value, i in ranked:
            if value < 0.35 * best or len(out) >= limit:
                break
            row = rows[i]
            out.append({"lemma_id": i, "lemma": row["lemma"], "gloss": row["gloss"], "gloss_source": row["gloss_source"],
                        "pos": row["pos"], "tokens_all_records": row["tokens"], "via": "english_dictionary_head_meaning",
                        "gloss_match": round(value / best, 3), "matched_terms": sorted(matched[i]),
                        "matched_words": sorted(matched[i])})
        return out

    def english_lemmas(self, query, limit=6):
        """Greek headwords whose dictionary glosses use the query's English words.

        Every content word of the query must appear in the headword's glosses; a word in a
        head gloss counts 1/len(that gloss), a word only in the entry body 0.25. Ties go to the
        headword more frequent in the corpus. A retrieval bridge, not a translation."""
        terms = [t for t in english_terms(query) if "-" not in t]
        compounds = [t for t in english_terms(query) if "-" in t]
        if not terms:
            return []
        con = self.con()
        score, head_hit, matched = defaultdict(float), defaultdict(int), defaultdict(set)
        for term in terms + compounds:
            for lemma_id, field, weight in con.execute("SELECT lemma_id, field, weight FROM lemma_gloss_term WHERE term=?", (term,)):
                if term in compounds:
                    score[lemma_id] += 0.5 * weight
                    continue
                score[lemma_id] += weight
                matched[lemma_id].add(term)
                head_hit[lemma_id] += field == 1
        need = len(terms) if len(terms) <= 2 else math.ceil(len(terms) * 2 / 3)
        ids = [i for i in score if len(matched[i]) >= need]
        if not ids:
            return []
        rows = {r["id"]: r for r in con.execute(f"SELECT * FROM lemma WHERE id IN ({','.join('?' * len(ids))})", ids)}
        ranked = []
        for i in ids:
            row = rows.get(i)
            if not row or not row["tokens"]:
                continue
            if head_hit[i] == 0:
                continue  # the words are only in the entry's body text: too weak
            ranked.append((score[i] * (1 + 0.15 * math.log1p(self.prior_tokens(i, row["tokens"]))), i))
        ranked.sort(reverse=True)
        if not ranked:
            return []
        # A headword whose gloss matches much more weakly than the best (Io, "the moon" deep in
        # a longer head) is not kept, however frequent.
        best_raw = max(score[i] for _, i in ranked)
        ranked = [(v, i) for v, i in ranked if score[i] >= 0.5 * best_raw]
        best = ranked[0][0]
        out = []
        for value, i in ranked[: limit * 2]:
            if value < 0.35 * best or len(out) >= limit:
                break
            row = rows[i]
            out.append({"lemma_id": i, "lemma": row["lemma"], "gloss": row["gloss"], "gloss_source": row["gloss_source"],
                        "pos": row["pos"], "tokens_all_records": row["tokens"], "via": "english_dictionary_gloss",
                        "gloss_match": round(value / best, 3), "matched_terms": sorted(matched[i]),
                        "matched_words": sorted({w for w in _query_words(query) if stem(w) in matched[i]})})
        return out

    def prior_tokens(self, lemma_id, fallback):
        """Frequency prior of an English reading: tokens as release O counted them (the contextual
        model's choices in edited text only), so the re-read OCR pages and scholia do not move search."""
        table = getattr(self, "_prior", None)
        if table is None:
            try:
                table = dict(self.con().execute("SELECT lemma_id, tokens FROM lemma_prior").fetchall())
            except sqlite3.OperationalError:
                table = {}
            self._prior = table
        return table.get(lemma_id, fallback if not table else 0)

    def case_variants(self, lemma_id):
        """Headwords spelled with the same letters and accents, differing only in capitalisation
        (ἠώς / Ἠώς: the parser capitalises the name). Used together by search-type features."""
        row = self.lemma_row(lemma_id)
        if not row:
            return [lemma_id]
        target = unicodedata.normalize("NFC", row["lemma"]).casefold()
        ids = [r[0] for r in self.con().execute("SELECT id, lemma FROM lemma WHERE key=?", (row["key"],))
               if unicodedata.normalize("NFC", r[1]).casefold() == target]
        return sorted(set(ids) | {lemma_id}, key=lambda i: i != lemma_id)

    # ------------------------------------------------------------------ features
    def _filter_pids(self, pids, mask):
        return pids[mask[pids]] if len(pids) else pids

    def lemma_passages(self, lemma_ids, mask):
        """{pid: total count of these lemmas} inside the scope."""
        hits = Counter()
        for lemma_id in lemma_ids:
            pids, ns = self.postings(lemma_id)
            keep = mask[pids] if len(pids) else np.zeros(0, dtype=bool)
            for pid, n in zip(pids[keep].tolist(), ns[keep].tolist()):
                hits[pid] += n
        return hits

    def record(self, pid):
        kind, quality, label, work, citation, source = self.meta[pid]
        info = self.authors.get(self.author_of[pid]) or {}
        return {"id": self.pid_id[pid], "author": info.get("author") or label, "author_label": label,
                "work": work, "display_work": display_work(work), "citation": citation, "kind": kind,
                "quality": quality, "source": source, "genre": info.get("genre"), "period": self.pid_period[pid],
                "author_date": info.get("date"),
                **({"attributed_date": self.pid_date[pid]} if self.pid_date[pid] and not info.get("date") else {})}

    def search(self, lemma_ids, *, include_reference=False, author="", genre="", limit=30, offset=0, order="frequency",
               text_lookup=None, width=80):
        mask = self.scope_mask(include_reference, author, genre)
        hits = self.lemma_passages(lemma_ids, mask)
        items = list(hits.items())
        if order == "chronological":
            key = self.sort_key("chronological")
            items.sort(key=lambda kv: key(kv[0]))
        else:
            items.sort(key=lambda kv: (-kv[1] / math.sqrt(max(self.ntok[kv[0]], 1)), self.pid_id[kv[0]]))
        # Release U: one edition of each text is counted (count_mask: TLG collections, word-for-word
        # repeats, edition groups); the other editions are listed under it, not as further passages.
        counted = self.count_mask(mask)
        items, copies = self.fold_edition_items(items, counted)
        forms, form_loci = Counter(), defaultdict(int)
        for pid, _ in items[: 400]:
            if not counted[pid]:
                continue
            toks = self.tokens(pid)
            if toks is None:
                continue
            sel = np.isin(toks[0], np.asarray(lemma_ids, dtype=np.uint32))
            fids = toks[1][sel].tolist()
            for form_id in fids:
                forms[form_id] += 1
            for form_id in set(fids):
                form_loci[form_id] += 1
        form_names = self._form_names(list(forms))
        results = []
        for pid, n in items[offset: offset + limit]:
            item = self._with_excerpt(dict(self.record(pid), occurrences=n), pid, lemma_ids, text_lookup, width)
            editions = [self._edition_record(c) for c in copies.get(pid, [])]
            item.update(editions=editions, edition_count=1 + len(editions))
            results.append(item)
        return {"total_passages": len(items), "total_tokens": int(sum(n for p, n in items if counted[p])),
                "editions_folded": int(sum(len(v) for v in copies.values())),
                "results": results,
                "forms_found": [{"form": form_names.get(fid), "count": n, "passages": form_loci[fid]}
                                for fid, n in forms.most_common(40)],
                "forms_note": ("Forms counted once per text: other editions of the same fragment or passage are "
                               "listed under it (editions) and not counted again"
                               + ("; counted in the first 400 listed passages." if len(items) > 400 else "."))}

    def fold_edition_items(self, items, counted):
        """Release U: [(pid, n)] in display order -> (items without other editions' copies,
        {representative pid: [copy pids]}). A copy is a passage that count_mask does not count and
        that shares an edition group, TLG work locus or repeat with a listed counted passage."""
        groups = self.edition_groups()["group"]
        first = {}
        for pid, _ in items:
            g = int(groups[pid])
            if counted[pid] and g >= 0 and g not in first:
                first[g] = pid
        kept, copies = [], defaultdict(list)
        for pid, n in items:
            g = int(groups[pid])
            if not counted[pid] and g >= 0 and g in first:
                copies[first[g]].append(pid)
                continue
            kept.append((pid, n))
        return kept, copies

    def _with_excerpt(self, item, pid, lemma_ids, text_lookup, width=80):
        """Release P: the first occurrence in context and every match offset (code points in the
        stored passage text, as /api/passage)."""
        toks = self.tokens(pid)
        if toks is None:
            return item
        idx = np.flatnonzero(np.isin(toks[0], np.asarray(lemma_ids, dtype=np.uint32))).tolist()
        item["match_offsets"] = [[int(toks[4][i]), int(toks[4][i]) + int(toks[5][i])] for i in idx[:20]]
        text = text_lookup(self.pid_id[pid]) if text_lookup else None
        if text is not None and idx:
            start, end = item["match_offsets"][0]
            left, right, numbers = display_context(text, start, end, width)
            item["excerpt"] = {"left": left, "keyword": text[start:end], "right": right, "offset": start,
                               "line_numbers": numbers}
        return item

    def _form_names(self, ids):
        if not ids:
            return {}
        out = {}
        for start in range(0, len(ids), 900):
            chunk = ids[start: start + 900]
            for fid, form in self.con().execute(f"SELECT id,form FROM form WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                out[fid] = form
        return out

    def _year(self, pid):
        return float(self.pid_year[pid])

    def frequency(self, lemma_id, *, include_reference=False):
        """Counts for one headword, or a list of ids counted together (capitalisation variants)."""
        ids = [int(i) for i in (lemma_id if isinstance(lemma_id, (list, tuple)) else [lemma_id])]
        mask = self.count_mask(self.scope_mask(include_reference))
        counts = self.scope_counts(include_reference, mask)
        total_tokens = int(self.ntok[mask].sum())
        n = int(sum(counts[i] for i in ids if i < len(counts)))
        rank = int((counts > n).sum()) + 1
        parts = [self.postings(i) for i in ids]
        pids = np.concatenate([p for p, _ in parts]) if parts else np.zeros(0, dtype=np.int64)
        ns = np.concatenate([c for _, c in parts]) if parts else np.zeros(0, dtype=np.int64)
        keep = mask[pids] if len(pids) else np.zeros(0, dtype=bool)
        pids, ns = pids[keep], ns[keep]
        by_author, by_genre, by_period = Counter(), Counter(), Counter()
        for pid, c in zip(pids.tolist(), ns.tolist()):
            info = self.authors.get(self.author_of[pid]) or {}
            by_author[info.get("author") or self.author_of[pid]] += c
            by_genre[info.get("genre") or "unclassified"] += c
            by_period[self.pid_period[pid] or "undated"] += c
        totals = self._totals(mask)
        alt = self.con().execute("SELECT coalesce(sum(f.tokens),0) FROM form_lemma fl JOIN form f ON f.id=fl.form_id "
                                 f"WHERE fl.lemma_id IN ({','.join('?' * len(ids))}) AND fl.rank>0", ids).fetchone()[0]
        lemma_id = ids[0]
        pids = np.unique(pids)

        def table(counter, denominators, key):
            rows = []
            for name, c in counter.most_common():
                d = denominators.get(name, 0)
                row = {key: name, "count": c, "tokens_in_group": d, **rate_fields(c, d)}
                if key == "author":
                    info = author_record(name)
                    row.update(genre=info["genre"], period=info["period"], date=info["date"], date_note=info["date_note"])
                rows.append(row)
            return rows

        return {"lemma": self.lemma_brief(lemma_id), "tokens": n, "passages": int(len(pids)),
                "scope_tokens": total_tokens, "per_10k": round(n * 1e4 / total_tokens, 3) if total_tokens else None,
                "rank": rank, "lemmas_in_scope": int((counts > 0).sum()), "variant_group": self.variant_group(lemma_id),
                "rate_note": ("per_10k_ci95 is a 95% Wilson interval; small_sample marks groups under "
                              f"{SMALL_GROUP_TOKENS:,} words, where one poem can move the rate."),
                "possible_additional_tokens": int(alt),
                "possible_additional_note": ("Tokens whose spelling has this headword as a lower-ranked reading "
                                             "(counted under another headword); an upper bound, not occurrences."),
                "by_author": table(by_author, totals["author"], "author"),
                "by_genre": table(by_genre, totals["genre"], "genre"),
                "by_period": sorted(table(by_period, totals["period"], "period"),
                                    key=lambda r: PERIOD_ORDER.index(r["period"]) if r["period"] in PERIOD_ORDER else 99),
                "date_note": ("Periods come from the author's sourced biographical date claim (Wikidata), not from "
                              "composition dates; 'undated' collects authors without a claim."),
                "counting_note": COUNTING_NOTE}

    def _totals(self, mask):
        key = ("totals", hash(mask.tobytes()))
        with self._lock:
            if key in self._scope_counts:
                return self._scope_counts[key]
        author, genre, period = Counter(), Counter(), Counter()
        for pid in np.flatnonzero(mask).tolist():
            info = self.authors.get(self.author_of[pid]) or {}
            n = int(self.ntok[pid])
            author[info.get("author") or self.author_of[pid]] += n
            genre[info.get("genre") or "unclassified"] += n
            period[self.pid_period[pid] or "undated"] += n
        value = {"author": author, "genre": genre, "period": period}
        with self._lock:
            self._scope_counts[key] = value
        return value

    def concordance(self, lemma_ids, *, include_reference=False, author="", genre="", width=60, limit=50, offset=0,
                    order="chronological", text_lookup=None, period="", fold_editions=True):
        """KWIC lines. Release P: `period` (a period label or 'undated'); other collections' copies
        of the same line are folded under one line (`editions`), as search does: a second collection
        of a TLG work another collection holds in full is not listed separately, and among
        unnumbered texts (fragments) a line with the same headwords around the keyword in another
        collection is folded. A formula repeated within one collection stays separate."""
        mask = self.scope_mask(include_reference, author, genre)
        if period:
            mask = mask & self.period_mask(period)
        hits = self.lemma_passages(lemma_ids, mask)
        info = self.work_info() if fold_editions else None
        folded_collection = 0
        if info is not None:
            for pid in [p for p in hits if info["duplicate"][p]]:
                folded_collection += hits.pop(pid)
        pids = sorted(hits, key=self.sort_key(order))
        wanted = np.asarray(lemma_ids, dtype=np.uint32)
        folded, copies = {}, defaultdict(list)
        group_copies = {}
        if fold_editions:
            # Release U: another edition of a fragment whose counted edition is listed is folded under it.
            counted = self.count_mask(mask)
            kept, group_copies = self.fold_edition_items([(p, hits[p]) for p in pids], counted)
            for rep, cs in group_copies.items():
                for c in cs:
                    folded_collection += hits.pop(c)
            pids = [p for p, _ in kept]
        if fold_editions:
            loose = [p for p in pids if info is None or info["order"][p] >= UNMAPPED_ORDER - 1]
            by_author = defaultdict(set)
            for p in loose:
                by_author[self.author_of[p]].add(self.meta[p][5])
            keyed = []
            for p in loose:
                if len(by_author[self.author_of[p]]) < 2:
                    continue
                toks = self.tokens(p)
                if toks is None:
                    continue
                lem = toks[0]
                for i in np.flatnonzero(np.isin(lem, wanted)).tolist():
                    keyed.append((p, (self.author_of[p], tuple(lem[max(0, i - 3):i + 4].tolist()), i)))
            # the key without the token index identifies the line; keep the index to address it
            first = {}
            for p, (a, window, i) in keyed:
                k = (a, window)
                if k in first and self.meta[first[k][0]][5] != self.meta[p][5]:
                    folded[(p, i)] = first[k]
                    copies[first[k]].append(p)
                elif k not in first:
                    first[k] = (p, i)
        total = int(sum(hits.values())) - len(folded)
        folded_count = Counter(p for p, _ in folded)
        lines, seen = [], 0
        for pid in pids:
            n = hits[pid] - folded_count.get(pid, 0)
            if seen + n <= offset:
                seen += n
                continue
            toks = self.tokens(pid)
            text = text_lookup(self.pid_id[pid]) if text_lookup else None
            if toks is None or text is None:
                seen += n
                continue
            for i in np.flatnonzero(np.isin(toks[0], wanted)).tolist():
                if (pid, i) in folded:
                    continue
                if seen < offset:
                    seen += 1
                    continue
                start, end = int(toks[4][i]), int(toks[4][i]) + int(toks[5][i])
                left, right, numbers = display_context(text, start, end, width)
                editions = [self._edition_record(c) for c in dict.fromkeys(copies.get((pid, i), []) + group_copies.get(pid, []))]
                if fold_editions:
                    editions += self.other_collections(pid)
                lines.append(dict(self.record(pid), left=left, keyword=text[start:end], right=right, offset=start,
                                  line_numbers=numbers,
                                  token_index=i, confidence=round(int(toks[2][i]) / 255, 3),
                                  probability=calibrated_probability(int(toks[2][i]), int(toks[3][i]),
                                                                     self.token_flags(pid).get(i, 0),
                                                                     self.calibration_group(pid)),
                                  source=describe_source(int(toks[3][i])), editions=editions,
                                  edition_count=1 + len(editions)))
                seen += 1
                if len(lines) >= limit:
                    break
            if len(lines) >= limit:
                break
        return {"total": total, "lines": lines, "order": order, "period": period or None,
                "folded_other_collections": int(folded_collection + len(folded)),
                "fold_note": ("Copies of a line in another collection are listed under it (editions) and not counted "
                              "again." if fold_editions else None)}

    def collocations(self, lemma_id, *, window=5, min_count=3, measure="log_likelihood", include_reference=False,
                     author="", genre="", limit=30, mask=None, function_words=False):
        mask = self.scope_mask(include_reference, author, genre) if mask is None else mask
        pids, _ = self.postings(lemma_id)
        cmask = self.count_mask(mask)  # one collection of each text within the scope (release P/Q)
        pids = pids[cmask[pids]] if len(pids) else pids
        sampled = False
        if len(pids) > MAX_SCAN_PASSAGES:
            pids = pids[:: math.ceil(len(pids) / MAX_SCAN_PASSAGES)]
            sampled = True
        co, slots, nodes = Counter(), 0, 0
        example = {}
        contexts, repeated = set(), 0
        for pid in pids.tolist():
            toks = self.tokens(pid)
            if toks is None:
                continue
            lem = toks[0]
            work = (self.meta[pid][5], self.meta[pid][2], self.meta[pid][3])
            for i in np.flatnonzero(lem == lemma_id).tolist():
                # Release P: a repeated line within one work (a refrain, Theocritus 2's
                # "φράζεό μευ τὸν ἔρωθ᾽ ὅθεν ἵκετο, πότνα Σελάνα") is counted once.
                key = (work, tuple(lem[max(0, i - window):i + 1 + window].tolist()))
                if key in contexts:
                    repeated += 1
                    continue
                contexts.add(key)
                nodes += 1
                ctx = np.concatenate([lem[max(0, i - window):i], lem[i + 1:i + 1 + window]])
                ctx = ctx[(ctx != 0) & (ctx != lemma_id)]
                slots += len(ctx)
                for x in set(ctx.tolist()):
                    co[x] += 1
                    example.setdefault(x, self.pid_id[pid])
        counts = self.scope_counts(include_reference, cmask)
        N = int(self.ntok[cmask].sum())
        out = []
        skip = set() if function_words else self.function_words(include_reference)
        for x, c in co.items():
            if c < min_count or x in skip:
                continue
            fx = int(counts[x]) if x < len(counts) else 0
            if fx <= 0:
                continue
            e11 = slots * fx / N if N else 0
            pmi = math.log2(c / e11) if e11 > 0 else None
            ll = _log_likelihood(c, slots, fx, N)
            if pmi is not None and pmi <= 0:
                continue
            out.append({"lemma_id": x, "count": c, "collocate_frequency": fx, "expected": round(e11, 3),
                        "log_likelihood": round(ll, 2), "pmi": round(pmi, 3) if pmi is not None else None,
                        "example_passage": example.get(x)})
        out.sort(key=lambda r: -(r["log_likelihood"] if measure == "log_likelihood" else (r["pmi"] or 0)))
        out = out[:limit]
        for row in out:
            row.update({k: v for k, v in self.lemma_brief(row["lemma_id"]).items() if k in ("lemma", "gloss", "pos")})
        return {"node": self.lemma_brief(lemma_id), "occurrences_scanned": nodes, "context_slots": slots,
                "scope_tokens": N, "window": window, "min_count": min_count, "measure": measure,
                "sampled": sampled, "collocates": out, "function_words_excluded": not function_words,
                "repeated_contexts_skipped": repeated,
                "method": (f"Lemmas within ±{window} tokens of the node in the same stored passage; counts are passages-"
                           "occurrence pairs (a collocate counted once per node occurrence; an identical context repeated "
                           "within one work, such as a refrain, counted once). Log-likelihood (Dunning G²) "
                           "and PMI (log₂ observed/expected) against the collocate's frequency in the same scope; only "
                           f"positive associations with at least {min_count} co-occurrences.")}

    def continuation(self):
        """next_pid[pid]: the following stored passage when it continues the same edition's text
        (same source, author label and work; its first line is the next line after this passage's
        last line within the same book), else 0. Fragments and unnumbered records never continue."""
        with self._lock:
            if getattr(self, "_next_pid", None) is not None:
                return self._next_pid
        from .citations import parse_range
        n = len(self.pid_id)
        nxt = np.zeros(n, dtype=np.int64)
        prev_key = prev_end = None
        for pid in range(1, n):
            if self.pid_id[pid] is None:
                prev_key = prev_end = None
                continue
            kind, quality, label, work, citation, source = self.meta[pid]
            rng = parse_range(citation)
            key = (source, label, work)
            if rng and prev_end is not None and key == prev_key:
                start = rng[0]
                if (len(start) == len(prev_end) and start[:-1] == prev_end[:-1]
                        and start[-1][0] in (prev_end[-1][0], prev_end[-1][0] + 1)):
                    nxt[pid - 1] = pid
            prev_key, prev_end = key, (rng[1] if rng else None)
        with self._lock:
            self._next_pid = nxt
        return nxt

    def proximity(self, terms, *, window=0, ordered=True, include_reference=False, author="", genre="", limit=30,
                  offset=0, text_lookup=None, cross_passages=False):
        """Passages where each term (a set of lemma ids) occurs within `window` extra tokens of the next.

        With cross_passages the match may run on into the following stored passages of the same
        edition when they continue its numbering (continuation()); such a result names every
        passage it spans."""
        mask = self.scope_mask(include_reference, author, genre)
        sets = []
        for ids in terms:
            hits = self.lemma_passages(ids, mask)
            sets.append(set(hits))
        candidates = sorted(set.intersection(*sets)) if sets else []
        results = []
        span = len(terms) - 1 + window
        for pid in candidates:
            toks = self.tokens(pid)
            if toks is None:
                continue
            lem = toks[0]
            positions = [np.flatnonzero(np.isin(lem, np.asarray(ids, dtype=np.uint32))).tolist() for ids in terms]
            match = _find_span(positions, span, ordered)
            if match:
                results.append((pid, match, None))
        crossing_checked = 0
        if cross_passages and sets:
            nxt = self.continuation()
            matched_inside = {pid for pid, _, _ in results}
            for pid in sorted(set().union(*sets)):
                if not nxt[pid] or pid in matched_inside:
                    continue
                chain = [pid]
                while len(chain) < 8 and nxt[chain[-1]] and mask[nxt[chain[-1]]] and \
                        int(self.ntok[chain[1:]].sum()) < span + 1:
                    chain.append(int(nxt[chain[-1]]))
                if len(chain) < 2 or not all(any(c in s for c in chain) for s in sets):
                    continue
                crossing_checked += 1
                parts = [self.tokens(c) for c in chain]
                if any(t is None for t in parts):
                    continue
                lem = np.concatenate([t[0] for t in parts])
                first_len = len(parts[0][0])
                positions = [np.flatnonzero(np.isin(lem, np.asarray(ids, dtype=np.uint32))).tolist() for ids in terms]
                if ordered:
                    positions[0] = [x for x in positions[0] if x < first_len]
                match = _find_span(positions, span, ordered)
                if match and match[0] < first_len <= match[1]:
                    results.append((pid, match, (chain, parts)))
        # Release P: fold other collections' copies (as the concordance does).
        info = self.work_info()
        folded_collection = 0
        if info is not None:
            kept = [r for r in results if not info["duplicate"][r[0]]]
            folded_collection = len(results) - len(kept)
            results = kept
        first_key, copies, kept = {}, defaultdict(list), []
        for pid, match, crossing in results:
            if crossing is None and (info is None or info["order"][pid] >= UNMAPPED_ORDER - 1):
                toks = self.tokens(pid)
                key = (self.author_of[pid], tuple(toks[0][match[0]:match[1] + 1].tolist()))
                if key in first_key and self.meta[first_key[key]][5] != self.meta[pid][5]:
                    copies[first_key[key]].append(pid)
                    continue
                first_key.setdefault(key, pid)
            kept.append((pid, match, crossing))
        folded_lines = len(results) - len(kept)
        results = kept
        total = len(results)
        out = []
        for pid, (first, last), crossing in results[offset: offset + limit]:
            if crossing is None:
                toks = self.tokens(pid)
                start, end = int(toks[4][first]), int(toks[4][last]) + int(toks[5][last])
                text = text_lookup(self.pid_id[pid]) if text_lookup else None
                item = dict(self.record(pid), match_start=start, match_end=end, crosses_passages=False)
                editions = [self._edition_record(c) for c in copies.get(pid, [])] + self.other_collections(pid)
                item.update(editions=editions, edition_count=1 + len(editions))
                if text is not None:
                    left, right, numbers = display_context(text, start, end, 50)
                    item.update(match_text=" ".join(_LINE_NUMBER.sub(" ", text[start:end]).split()), left=left,
                                right=right, line_numbers=numbers + _LINE_NUMBER.findall(text[start:end]))
                out.append(item)
                continue
            chain, parts = crossing
            bounds = np.cumsum([0] + [len(t[0]) for t in parts])
            last_part = int(np.searchsorted(bounds, last, side="right") - 1)
            local_last = last - int(bounds[last_part])
            start = int(parts[0][4][first])
            end = int(parts[last_part][4][local_last]) + int(parts[last_part][5][local_last])
            item = dict(self.record(pid), match_start=start, match_end=end, crosses_passages=True,
                        match_passages=[self.pid_id[c] for c in chain[:last_part + 1]],
                        match_end_passage=self.pid_id[chain[last_part]])
            if text_lookup:
                texts = [text_lookup(self.pid_id[c]) or "" for c in chain[:last_part + 1]]
                middle = [" ".join(t.split()) for t in texts[1:-1]]
                pieces = [texts[0][start:]] + middle + [texts[-1][:end]]
                item.update(match_text=" / ".join(" ".join(x.split()) for x in pieces),
                            left=" ".join(texts[0][max(0, start - 50):start].split()),
                            right=" ".join(texts[-1][end:end + 50].split()))
            out.append(item)
        return {"total": total, "candidate_passages": len(candidates), "crossing_chains_checked": crossing_checked,
                "folded_other_collections": int(folded_collection + folded_lines), "results": out}

    # ------------------------------------------------------------------ diachrony
    def _kwic(self, pid, lemma_ids, text_lookup, width=60):
        toks = self.tokens(pid)
        text = text_lookup(self.pid_id[pid]) if text_lookup else None
        if toks is None or text is None:
            return None
        idx = np.flatnonzero(np.isin(toks[0], np.asarray(lemma_ids, dtype=np.uint32))).tolist()
        if not idx:
            return None
        start, end = int(toks[4][idx[0]]), int(toks[4][idx[0]]) + int(toks[5][idx[0]])
        left, right, numbers = display_context(text, start, end, width)
        from .line_spans import line_at
        record = self.record(pid)
        # Release U: the whole line holding the keyword, with its line number and citation.
        return dict(record, left=left, keyword=text[start:end], right=right, offset=start,
                    line_numbers=numbers, line=line_at(text, start, record.get("citation")))

    def _examples(self, lemma_ids, pids, ns, text_lookup, per_group=3):
        """One line from each of the (up to three) authors using the headword most in this group."""
        if not text_lookup:
            return []
        info = self.work_info()
        by_author = defaultdict(list)
        for pid, c in zip(pids, ns):
            if info is not None and info["duplicate"][pid]:
                continue
            by_author[self.author_of[pid]].append((pid, c))
        ranked = sorted(by_author.items(), key=lambda kv: -sum(c for _, c in kv[1]))
        out = []
        for name, items in ranked[:per_group]:
            pid = min((p for p, _ in items), key=self.sort_key("chronological"))
            line = self._kwic(pid, lemma_ids, text_lookup)
            if line:
                out.append(line)
        return out

    def diachrony(self, concept, *, dense_ids=(), include_reference=False, max_lemmas=8, collocates=5,
                  text_lookup=None, combine_variants=False, author="", genre=""):
        """Headwords expressing a concept, each with counts by period and by dated author, typical
        collocates and example passages per period (and for undated authors). Honest output: counts,
        sources, date uncertainty, interval and small-sample flag on every rate. Release U: `author` /
        `genre` scope every count and example."""
        mask = self.count_mask(self.scope_mask(include_reference, author, genre))
        english = not GREEK(concept) and not concept.startswith("lemma:")
        # A single Latin-letter word that spells a Greek headword (eros -> ἔρως) is that headword.
        chosen = self.transliterated_lemmas(concept) if english else []
        resolution_rule = "transliterated_headword" if chosen else None
        if english and not chosen:
            chosen = self.head_meaning_lemmas(concept, limit=max_lemmas * 2)
            resolution_rule = "head_meaning" if chosen else None
        resolution_rule = resolution_rule or "gloss_terms"
        if not chosen:
            chosen = self.resolve(concept, limit=max_lemmas * 2)
        dense = [self.id_pid[i] for i in dense_ids if i in self.id_pid]
        dense_set = set(dense)
        semantic_candidates = []
        if dense:
            # Headwords over-represented in the passages nearest the concept in meaning, kept only
            # when a dictionary gloss of theirs shares a word with the concept's dictionary glosses.
            inside, n_inside = Counter(), 0
            for pid in dense:
                if not mask[pid]:
                    continue
                toks = self.tokens(pid)
                if toks is None:
                    continue
                n_inside += len(toks[0])
                inside.update(toks[0][toks[0] > 0].tolist())
            counts = self.scope_counts(include_reference, mask)
            N = int(self.ntok[mask].sum()) or 1
            # Release U: a neighbour must share a head meaning (a whole word that heads one of its dictionary
            # senses) with the concept or with a chosen headword, not a word stem: "longing" no longer brings
            # in μακρός "long" or λέων (a lion's skin, "long" in the body of the entry).
            concept_terms = self.head_meaning_terms(concept, [row["lemma_id"] for row in chosen])
            known = {row["lemma_id"] for row in chosen}
            scored = []
            for lemma_id, c in inside.items():
                if c < 5 or lemma_id in known:
                    continue
                expected = n_inside * counts[lemma_id] / N
                if expected <= 0 or c / expected < 3:
                    continue
                scored.append((_log_likelihood(c, n_inside, int(counts[lemma_id]), N), lemma_id, c, expected))
            scored.sort(reverse=True)
            for ll, lemma_id, c, expected in scored[:200]:
                brief = self.lemma_brief(lemma_id)
                terms = set(t for t, in self.con().execute(
                    "SELECT term FROM lemma_gloss_term WHERE lemma_id=? AND field=3", (lemma_id,)))
                shared = sorted(terms & concept_terms)
                if not shared:
                    continue
                semantic_candidates.append(dict(brief, via="semantic_neighbourhood_and_shared_gloss_word",
                                                shared_gloss_terms=shared, in_nearest_passages=c,
                                                expected=round(expected, 2), log_likelihood=round(ll, 1),
                                                gloss_match=0.5))
                if len(semantic_candidates) >= 5:
                    break
        period_masks = {label: m & mask for label, m in self.period_masks(include_reference).items()}
        undated_mask = mask & self.period_mask("undated")
        totals = self._totals(mask)
        n_scope_passages = int(mask.sum()) or 1
        lemmas_out = []
        absent = []
        dropped = []
        counted = set()
        for row in chosen + semantic_candidates:
            lemma_id = row["lemma_id"]
            if lemma_id in counted:
                continue  # release Q: already counted with an earlier headword of its variant group
            ids = [lemma_id]
            group = self.variant_group(lemma_id)
            if combine_variants and group:
                ids = self.expand_variants([lemma_id])
                counted.update(ids)
            parts = [self.postings(i) for i in ids]
            pids = np.concatenate([p for p, _ in parts]) if parts else np.zeros(0, dtype=np.int64)
            ns = np.concatenate([c for _, c in parts]) if parts else np.zeros(0, dtype=np.int64)
            keep = mask[pids] if len(pids) else np.zeros(0, dtype=bool)
            pids, ns = pids[keep], ns[keep]
            if not len(pids):
                absent.append({k: row.get(k) for k in ("lemma", "gloss", "via")})
                continue
            support, enrichment = None, None
            occurrence_passages = len(set(pids.tolist()))
            if dense_set:
                inside_n = int(sum(1 for p in set(pids.tolist()) if p in dense_set))
                enrichment = round((inside_n / len(dense_set)) / (occurrence_passages / n_scope_passages), 2)
                support = {"occurrence_passages": occurrence_passages, "in_nearest_passages": inside_n,
                           "enrichment": enrichment}
                # Weight by the meaning index: a dictionary-only reading whose passages are not
                # among those nearest the concept, and whose gloss matched weakly, is dropped.
                # Release U: a head-meaning match (the query word heads one of its senses: ἵμερος "longing") is
                # dictionary evidence of the concept itself and is kept.
                if inside_n == 0 and occurrence_passages >= 5 and row.get("via") not in (
                        "headword", "headword_without_accents", "transliterated_headword", "printed_form_reading",
                        "english_dictionary_head_meaning"):
                    dropped.append({k: row.get(k) for k in ("lemma", "gloss", "via", "gloss_match")})
                    continue
            score = (row.get("gloss_match") or 1.0) * (1 + math.log1p(enrichment or 0))
            # Release U: a headword with a handful of tokens in the scope (θέλημα, 1) is not the scope's word for
            # the concept; its score shrinks below five tokens.
            score *= min(1.0, int(ns.sum()) / 5)
            per_period, per_author = Counter(), Counter()
            for pid, c in zip(pids.tolist(), ns.tolist()):
                info = self.authors.get(self.author_of[pid]) or {}
                per_period[self.pid_period[pid] or "undated"] += c
                per_author[info.get("author") or self.author_of[pid]] += c
            periods = []
            for label in PERIOD_ORDER + ["undated"]:
                d = totals["period"].get(label, 0)
                c_here = per_period.get(label, 0)
                entry = {"period": label, "count": c_here, "tokens_in_period": d, **rate_fields(c_here, d)}
                if c_here >= 2:
                    group_mask = undated_mask if label == "undated" else period_masks[label]
                    col = self.collocations(lemma_id, min_count=2, limit=collocates, mask=group_mask)
                    entry["collocates"] = [{"lemma": c["lemma"], "gloss": c["gloss"], "count": c["count"],
                                            "log_likelihood": c["log_likelihood"]} for c in col["collocates"]]
                if c_here and text_lookup:
                    sel = [(p, c) for p, c in zip(pids.tolist(), ns.tolist())
                           if (self.pid_period[p] or "undated") == label]
                    entry["examples"] = self._examples(ids, [p for p, _ in sel], [c for _, c in sel], text_lookup)
                periods.append(entry)
            authors = []
            for name, c in per_author.most_common():
                info = author_record(name)
                d = totals["author"].get(name, 0)
                authors.append({"author": name, "count": c, **rate_fields(c, d),
                                "period": info["period"], "date": info["date"], "genre": info["genre"]})
            authors.sort(key=lambda a: (a["date"]["year"] if a["date"] else 99999, a["author"]))
            lemmas_out.append(dict(row, tokens=int(ns.sum()), passages=occurrence_passages,
                                   undated_count=per_period.get("undated", 0), by_period=periods,
                                   by_author=authors, semantic_support=support, concept_score=round(score, 3),
                                   variant_group=group, counted_lemma_ids=ids,
                                   counted_lemmas=[(self.lemma_row(i) or {}).get("lemma") for i in ids]))
        lemmas_out.sort(key=lambda r: -r["concept_score"])
        lemmas_out = lemmas_out[:max_lemmas]  # release U: max_lemmas is the number returned
        dated = sum(v for k, v in totals["period"].items() if k != "undated")
        return {"concept": concept, "lemmas": lemmas_out, "headwords_without_occurrences": absent,
                "dropped_without_semantic_support": dropped, "resolution_rule": resolution_rule,
                "scope": "searchable edited Greek text" if not include_reference else "all indexed Greek records",
                "scope_tokens": int(self.ntok[mask].sum()), "dated_tokens": int(dated),
                "undated_tokens": int(totals["period"].get("undated", 0)),
                "nearest_passages_used": len(dense),
                "notes": [
                    "English concepts are read through the head meaning of dictionary senses (a sense whose head "
                    "word is the query word: 'the moon', not 'Io, identified with the moon'); when none has one, "
                    "through any gloss word (resolution_rule gloss_terms). "
                    "'semantic_neighbourhood_and_shared_gloss_word' rows are over-represented in the passages "
                    "nearest the concept in the meaning index and share a gloss word with it. concept_score = "
                    "gloss match x (1 + log(1 + enrichment in the nearest passages)); a dictionary reading with at least "
                    "five passages none of which is among the nearest is dropped (dropped_without_semantic_support). "
                    "A Latin-letter word that spells a Greek headword (eros) is read as that headword.",
                    "Periods use a passage's sourced date: its author's Wikidata biographical claim, or for a Greek "
                    "Anthology epigram its attributed poet's; never composition dates; ranges can be wide. Undated "
                    "passages form their own column (period 'undated') and are never placed in time.",
                    "Counts are top-ranked headword readings of each token (machine lemmatisation with "
                    "confidence); rates are per 10,000 indexed tokens of the same period or author, with a 95% "
                    "Wilson interval (per_10k_ci95) and small_sample for groups under 50,000 words.",
                    "Collocates are lemmas within ±5 tokens in the same passage, ranked by log-likelihood "
                    "(minimum 2 co-occurrences in that period; a context repeated within one work counted once). "
                    "Examples: one line from each of the three authors using the headword most in the period."]}

    # ------------------------------------------------------------------ search signal
    def passage_signal(self, groups, limit=400, include_reference=False):
        """Ranked passage ids for retrieval fusion: BM25-like weight of query headword groups.

        `groups` is a list of {lemma_id: weight}; a passage scores per group by its best lemma,
        with term saturation and passage-length normalisation (k1 1.2, b 0.75)."""
        mask = self.scope_mask(include_reference)
        avg = float(self.ntok[mask].mean()) if mask.any() else 1.0
        n_docs = int(mask.sum()) or 1
        score = defaultdict(float)
        covered = defaultdict(int)
        for group in groups:
            best = defaultdict(float)
            for lemma_id, weight in group.items():
                pids, ns = self.postings(lemma_id)
                if not len(pids):
                    continue
                keep = mask[pids]
                pids, ns = pids[keep], ns[keep]
                idf = math.log(1 + (n_docs - len(pids) + 0.5) / (len(pids) + 0.5))
                lengths = self.ntok[pids].astype(np.float64)
                tf = ns * 2.2 / (ns + 1.2 * (0.25 + 0.75 * lengths / avg))
                values = weight * idf * tf
                for pid, v in zip(pids.tolist(), values.tolist()):
                    if v > best[pid]:
                        best[pid] = v
            for pid, v in best.items():
                score[pid] += v
                covered[pid] += 1
        ranked = sorted(score, key=lambda p: (-covered[p], -score[p], self.pid_id[p]))[:limit]
        return [{"id": self.pid_id[p], "score": round(score[p], 4), "groups_matched": covered[p]} for p in ranked]


def _query_words(query):
    import re
    return [w.lower() for w in re.findall(r"[A-Za-z]+", query or "")]


def _find_span(positions, span, ordered):
    """First (first_index, last_index) where one position per term fits within span; ordered keeps term order."""
    if any(not p for p in positions):
        return None
    if ordered:
        for start in positions[0]:
            cur, ok, last = start, True, start
            for nxt in positions[1:]:
                cand = [p for p in nxt if p > cur]
                if not cand:
                    ok = False
                    break
                cur = cand[0]
                last = cur
            if ok and last - start <= span:
                return start, last
        return None
    events = sorted((p, k) for k, plist in enumerate(positions) for p in plist)
    need, have, left = len(positions), Counter(), 0
    best = None
    for right in range(len(events)):
        have[events[right][1]] += 1
        while len(have) == need:
            lo, hi = events[left][0], events[right][0]
            if hi - lo <= span and (best is None or hi - lo < best[1] - best[0]):
                best = (lo, hi)
            have[events[left][1]] -= 1
            if not have[events[left][1]]:
                del have[events[left][1]]
            left += 1
    return best


def _log_likelihood(o11, r1, c1, n):
    """Dunning G² for a 2x2 table (observed pair count o11, row total r1, column total c1, grand total n)."""
    o12, o21 = r1 - o11, c1 - o11
    o22 = n - r1 - c1 + o11
    total = 0.0
    for o, e in ((o11, r1 * c1 / n), (o12, r1 * (n - c1) / n), (o21, (n - r1) * c1 / n), (o22, (n - r1) * (n - c1) / n)):
        if o > 0 and e > 0:
            total += o * math.log(o / e)
    return 2 * total


_INDEX = None
_INDEX_LOCK = threading.Lock()


def get_index():
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is None or _INDEX.path != index_path():
            _INDEX = LemmaIndex()
            # Warm the scope tables in the background so the first frequency request is fast.
            threading.Thread(target=_warm, args=(_INDEX,), daemon=True).start()
        return _INDEX


def _warm(index):
    try:
        index.scope_counts()
        index.period_masks()
        index._totals(index.scope_mask())
        counted = index.count_mask(index.scope_mask())
        index.scope_counts(False, counted)
        index._totals(counted)
    except Exception:  # noqa: BLE001 - warming is an optimisation only
        pass


__all__ = ["LemmaIndex", "get_index", "index_path", "describe_source"]
