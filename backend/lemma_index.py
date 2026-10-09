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
import math
import os
import sqlite3
import threading
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from .author_catalogue import PERIODS, author_record, display_work
from .lemma_glosses_index import english_terms
from .lemma_tokens import fold

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data/lemma_index.sqlite"
SEARCHABLE = ("source_text", "machine_corrected_ocr")
GREEK = lambda text: any("Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿" for c in text or "")  # noqa: E731
SOURCE_BITS = {1: "parser", 2: "recorded_form", 4: "generated_spelling", 8: "printed_headword",
               16: "context_agrees", 32: "context_chose", 64: "damaged_word"}
MAX_SCAN_PASSAGES = 40000
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
    """


def index_path():
    return Path(os.getenv("MELOS_LEMMA_INDEX", str(DEFAULT_PATH)))


def _nfc(text):
    return unicodedata.normalize("NFC", str(text or "")).strip()


def _headword_key(text):
    from .lemma_glosses import headword_key
    return headword_key(text)


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
                "bytes": self.path.stat().st_size, "method": m.get("method")}

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
        return {"lemma_id": row.get("id"), "lemma": row.get("lemma"), "gloss": row.get("gloss"),
                "gloss_source": row.get("gloss_source"), "pos": row.get("pos"), "tokens_all_records": row.get("tokens")}

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
        labels = np.asarray([(self.authors.get(a) or {}).get("period") or "" for a in self.author_of], dtype=object)
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
        for item in self.english_lemmas(q, limit=limit):
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
            ranked.append((score[i] * (1 + 0.15 * math.log1p(row["tokens"])), i))
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
                        "gloss_match": round(value / best, 3), "matched_terms": sorted(matched[i])})
        return out

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
                "quality": quality, "source": source, "genre": info.get("genre"), "period": info.get("period"),
                "author_date": info.get("date")}

    def search(self, lemma_ids, *, include_reference=False, author="", genre="", limit=30, offset=0, order="frequency"):
        mask = self.scope_mask(include_reference, author, genre)
        hits = self.lemma_passages(lemma_ids, mask)
        items = list(hits.items())
        if order == "chronological":
            items.sort(key=lambda kv: (self._year(kv[0]), self.pid_id[kv[0]]))
        else:
            items.sort(key=lambda kv: (-kv[1] / math.sqrt(max(self.ntok[kv[0]], 1)), self.pid_id[kv[0]]))
        forms = Counter()
        for pid, _ in items[: 400]:
            toks = self.tokens(pid)
            if toks is None:
                continue
            sel = np.isin(toks[0], np.asarray(lemma_ids, dtype=np.uint32))
            for form_id in toks[1][sel].tolist():
                forms[form_id] += 1
        form_names = self._form_names(list(forms))
        return {"total_passages": len(items), "total_tokens": int(sum(hits.values())),
                "results": [dict(self.record(pid), occurrences=n) for pid, n in items[offset: offset + limit]],
                "forms_found": [{"form": form_names.get(fid), "count": n} for fid, n in forms.most_common(40)],
                "forms_note": "Forms counted in the first 400 listed passages." if len(items) > 400 else None}

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
        date = (self.authors.get(self.author_of[pid]) or {}).get("date")
        return date["year"] if date and date.get("year") is not None else 99999

    def frequency(self, lemma_id, *, include_reference=False):
        """Counts for one headword, or a list of ids counted together (capitalisation variants)."""
        ids = [int(i) for i in (lemma_id if isinstance(lemma_id, (list, tuple)) else [lemma_id])]
        mask = self.scope_mask(include_reference)
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
            by_period[info.get("period") or "undated"] += c
        totals = self._totals(mask)
        alt = self.con().execute("SELECT coalesce(sum(f.tokens),0) FROM form_lemma fl JOIN form f ON f.id=fl.form_id "
                                 f"WHERE fl.lemma_id IN ({','.join('?' * len(ids))}) AND fl.rank>0", ids).fetchone()[0]
        lemma_id = ids[0]
        pids = np.unique(pids)

        def table(counter, denominators, key):
            rows = []
            for name, c in counter.most_common():
                d = denominators.get(name, 0)
                row = {key: name, "count": c, "tokens_in_group": d, "per_10k": round(c * 1e4 / d, 2) if d else None}
                if key == "author":
                    info = author_record(name)
                    row.update(genre=info["genre"], period=info["period"], date=info["date"], date_note=info["date_note"])
                rows.append(row)
            return rows

        return {"lemma": self.lemma_brief(lemma_id), "tokens": n, "passages": int(len(pids)),
                "scope_tokens": total_tokens, "per_10k": round(n * 1e4 / total_tokens, 3) if total_tokens else None,
                "rank": rank, "lemmas_in_scope": int((counts > 0).sum()),
                "possible_additional_tokens": int(alt),
                "possible_additional_note": ("Tokens whose spelling has this headword as a lower-ranked reading "
                                             "(counted under another headword); an upper bound, not occurrences."),
                "by_author": table(by_author, totals["author"], "author"),
                "by_genre": table(by_genre, totals["genre"], "genre"),
                "by_period": sorted(table(by_period, totals["period"], "period"),
                                    key=lambda r: PERIOD_ORDER.index(r["period"]) if r["period"] in PERIOD_ORDER else 99),
                "date_note": ("Periods come from the author's sourced biographical date claim (Wikidata), not from "
                              "composition dates; 'undated' collects authors without a claim.")}

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
            period[info.get("period") or "undated"] += n
        value = {"author": author, "genre": genre, "period": period}
        with self._lock:
            self._scope_counts[key] = value
        return value

    def concordance(self, lemma_ids, *, include_reference=False, author="", genre="", width=60, limit=50, offset=0,
                    order="chronological", text_lookup=None):
        mask = self.scope_mask(include_reference, author, genre)
        hits = self.lemma_passages(lemma_ids, mask)
        pids = sorted(hits, key=(lambda p: (self._year(p), self.author_of[p], self.pid_id[p])) if order == "chronological"
                      else (lambda p: (self.author_of[p], self.pid_id[p])))
        total = int(sum(hits.values()))
        wanted = np.asarray(lemma_ids, dtype=np.uint32)
        lines, seen = [], 0
        for pid in pids:
            n = hits[pid]
            if seen + n <= offset:
                seen += n
                continue
            toks = self.tokens(pid)
            text = text_lookup(self.pid_id[pid]) if text_lookup else None
            if toks is None or text is None:
                seen += n
                continue
            for i in np.flatnonzero(np.isin(toks[0], wanted)).tolist():
                if seen < offset:
                    seen += 1
                    continue
                start, end = int(toks[4][i]), int(toks[4][i]) + int(toks[5][i])
                left = " ".join(text[max(0, start - width):start].split())
                right = " ".join(text[end:end + width].split())
                lines.append(dict(self.record(pid), left=left, keyword=text[start:end], right=right, offset=start,
                                  token_index=i, confidence=round(int(toks[2][i]) / 255, 3),
                                  source=describe_source(int(toks[3][i]))))
                seen += 1
                if len(lines) >= limit:
                    return {"total": total, "lines": lines, "order": order}
        return {"total": total, "lines": lines, "order": order}

    def collocations(self, lemma_id, *, window=5, min_count=3, measure="log_likelihood", include_reference=False,
                     author="", genre="", limit=30, mask=None, function_words=False):
        mask = self.scope_mask(include_reference, author, genre) if mask is None else mask
        pids, _ = self.postings(lemma_id)
        pids = pids[mask[pids]] if len(pids) else pids
        sampled = False
        if len(pids) > MAX_SCAN_PASSAGES:
            pids = pids[:: math.ceil(len(pids) / MAX_SCAN_PASSAGES)]
            sampled = True
        co, slots, nodes = Counter(), 0, 0
        example = {}
        for pid in pids.tolist():
            toks = self.tokens(pid)
            if toks is None:
                continue
            lem = toks[0]
            for i in np.flatnonzero(lem == lemma_id).tolist():
                nodes += 1
                ctx = np.concatenate([lem[max(0, i - window):i], lem[i + 1:i + 1 + window]])
                ctx = ctx[(ctx != 0) & (ctx != lemma_id)]
                slots += len(ctx)
                for x in set(ctx.tolist()):
                    co[x] += 1
                    example.setdefault(x, self.pid_id[pid])
        counts = self.scope_counts(include_reference, mask)
        N = int(self.ntok[mask].sum())
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
                "method": (f"Lemmas within ±{window} tokens of the node in the same stored passage; counts are passages-"
                           "occurrence pairs (a collocate counted once per node occurrence). Log-likelihood (Dunning G²) "
                           "and PMI (log₂ observed/expected) against the collocate's frequency in the same scope; only "
                           f"positive associations with at least {min_count} co-occurrences.")}

    def proximity(self, terms, *, window=0, ordered=True, include_reference=False, author="", genre="", limit=30,
                  offset=0, text_lookup=None):
        """Passages where each term (a set of lemma ids) occurs within `window` extra tokens of the next."""
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
                results.append((pid, match))
        total = len(results)
        out = []
        for pid, (first, last) in results[offset: offset + limit]:
            toks = self.tokens(pid)
            start, end = int(toks[4][first]), int(toks[4][last]) + int(toks[5][last])
            text = text_lookup(self.pid_id[pid]) if text_lookup else None
            item = dict(self.record(pid), match_start=start, match_end=end)
            if text is not None:
                item.update(match_text=text[start:end], left=" ".join(text[max(0, start - 50):start].split()),
                            right=" ".join(text[end:end + 50].split()))
            out.append(item)
        return {"total": total, "candidate_passages": len(candidates), "results": out}

    # ------------------------------------------------------------------ diachrony
    def diachrony(self, concept, *, dense_ids=(), include_reference=False, max_lemmas=8, collocates=5):
        """Headwords expressing a concept, each with counts by period and by dated author, and
        typical collocates per period. Honest output: counts, sources, date uncertainty."""
        mask = self.scope_mask(include_reference)
        chosen = self.resolve(concept, limit=max_lemmas)
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
            concept_terms = set(english_terms(concept))
            for row in chosen:
                concept_terms.update(english_terms(row.get("gloss") or ""))
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
                terms = set(t for t, in self.con().execute("SELECT term FROM lemma_gloss_term WHERE lemma_id=?", (lemma_id,)))
                shared = sorted(terms & concept_terms)
                if not shared:
                    continue
                semantic_candidates.append(dict(brief, via="semantic_neighbourhood_and_shared_gloss_word",
                                                shared_gloss_terms=shared, in_nearest_passages=c,
                                                expected=round(expected, 2), log_likelihood=round(ll, 1)))
                if len(semantic_candidates) >= 5:
                    break
        period_masks = self.period_masks(include_reference)
        totals = self._totals(mask)
        lemmas_out = []
        absent = []
        for row in chosen + semantic_candidates:
            lemma_id = row["lemma_id"]
            pids, ns = self.postings(lemma_id)
            keep = mask[pids] if len(pids) else np.zeros(0, dtype=bool)
            pids, ns = pids[keep], ns[keep]
            if not len(pids):
                absent.append({k: row.get(k) for k in ("lemma", "gloss", "via")})
                continue
            per_period, per_author = Counter(), Counter()
            for pid, c in zip(pids.tolist(), ns.tolist()):
                info = self.authors.get(self.author_of[pid]) or {}
                per_period[info.get("period") or "undated"] += c
                per_author[info.get("author") or self.author_of[pid]] += c
            periods = []
            for label in PERIOD_ORDER:
                d = totals["period"].get(label, 0)
                entry = {"period": label, "count": per_period.get(label, 0), "tokens_in_period": d,
                         "per_10k": round(per_period.get(label, 0) * 1e4 / d, 2) if d else None}
                if per_period.get(label, 0) >= 2:
                    col = self.collocations(lemma_id, min_count=2, limit=collocates, mask=period_masks[label])
                    entry["collocates"] = [{"lemma": c["lemma"], "gloss": c["gloss"], "count": c["count"],
                                            "log_likelihood": c["log_likelihood"]} for c in col["collocates"]]
                periods.append(entry)
            authors = []
            for name, c in per_author.most_common():
                info = author_record(name)
                d = totals["author"].get(name, 0)
                authors.append({"author": name, "count": c, "per_10k": round(c * 1e4 / d, 2) if d else None,
                                "period": info["period"], "date": info["date"], "genre": info["genre"]})
            authors.sort(key=lambda a: (a["date"]["year"] if a["date"] else 99999, a["author"]))
            support = None
            if dense_set:
                support = {"occurrence_passages": int(len(pids)),
                           "in_nearest_passages": int(sum(1 for p in pids.tolist() if p in dense_set))}
            lemmas_out.append(dict(row, tokens=int(ns.sum()), passages=int(len(pids)),
                                   undated_count=per_period.get("undated", 0), by_period=periods,
                                   by_author=authors, semantic_support=support))
        dated = sum(v for k, v in totals["period"].items() if k != "undated")
        return {"concept": concept, "lemmas": lemmas_out, "headwords_without_occurrences": absent,
                "scope": "searchable edited Greek text" if not include_reference else "all indexed Greek records",
                "scope_tokens": int(self.ntok[mask].sum()), "dated_tokens": int(dated),
                "undated_tokens": int(totals["period"].get("undated", 0)),
                "nearest_passages_used": len(dense),
                "notes": [
                    "Headwords come from dictionary glosses (English) or the headword/form index (Greek); "
                    "'semantic_neighbourhood_and_shared_gloss_word' rows are over-represented in the passages "
                    "nearest the concept in the meaning index and share a gloss word with it.",
                    "Periods use the author's sourced biographical date claim (Wikidata birth/floruit), not "
                    "composition dates; ranges can be wide (see each author's date). Authors without a claim "
                    "are counted as undated and never placed in time.",
                    "Counts are top-ranked headword readings of each token (machine lemmatisation with "
                    "confidence); rates are per 10,000 indexed tokens of the same period or author.",
                    "Collocates are lemmas within ±5 tokens in the same passage, ranked by log-likelihood "
                    "(minimum 2 co-occurrences in that period)."]}

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
    except Exception:  # noqa: BLE001 - warming is an optimisation only
        pass


__all__ = ["LemmaIndex", "get_index", "index_path", "describe_source"]
