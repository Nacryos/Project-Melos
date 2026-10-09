"""Citation resolution (release P): "Il. 1.1", "Pind. O. 1.1", "Sappho fr. 31", CTS URNs -> passages.

The index (data/citation_index.sqlite, env MELOS_CITATION_INDEX) is built offline by
scripts/build_citation_index.py from the corpus: every stored passage's printed citation parsed
into a locus range, works grouped by author and title, and TLG author/work numbers attached only
where a record or an open catalogue states them (each mapping keeps its source).

Line and book citations resolve to the stored passages whose locus range contains the cited
locus (all editions; edited text first). Fragment citations keep the release-O rule: only a
record's explicit fragment citation matches, numbering stays edition-specific. Release Q adds
numbering schemes ("Sappho fr. 31 V", "Alc. 346 L-P", "Sappho Campbell 16"): records citable in a
scheme (their own citation names it, or their edition states its numbering), and equal numbers in
other schemes where a record prints both or a cited source states them (data/fragment_concordance.json),
each result labelled with that evidence.

The abbreviation table below is query syntax (the conventional LSJ / Oxford Classical Dictionary
abbreviations of the authors and works in this corpus), not a claim about the texts.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data/citation_index.sqlite"
URN = re.compile(r"^urn:cts:greekLit:(tlg\d{4})(?:\.(tlg\d{3}[a-z]?))?(?:\.([\w-]+))?(?::([\w.\-–]+))?$", re.I)
SEARCHABLE = ("source_text", "machine_corrected_ocr")

# ---------------------------------------------------------------------------------------------
# Locus parsing (shared with the builder)
_COMPONENT = re.compile(r"^(\d{1,5})([a-z]{0,2})$", re.I)
_DASH = re.compile(r"\s*[–—-]\s*")


def parse_end(text):
    """'1.20' -> ((1, ''), (20, '')). Leading alphabetic labels ('trochaic.1529') are dropped and a
    trailing label ('1.0.metr') ends the locus; any other component (page codes, OCR file names)
    means the citation is not a locus (None)."""
    parts = [p for p in str(text or "").strip().strip(".").split(".") if p != ""]
    out = []
    for part in parts:
        match = _COMPONENT.match(part)
        if match:
            out.append((int(match[1]), match[2].lower()))
        elif part.isalpha():
            if out:
                break
        else:
            return None
    return tuple(out) or None


def parse_range(citation):
    """(start, end) tuples for a printed citation '1.1–1.20', '622–643', '46.131'; None if not a locus."""
    text = unicodedata.normalize("NFC", str(citation or "")).strip()
    if not text or len(text) > 40:
        return None
    pieces = _DASH.split(text)
    if len(pieces) > 2:
        return None
    start = parse_end(pieces[0])
    end = parse_end(pieces[1]) if len(pieces) == 2 else start
    if not start or not end:
        return None
    if len(end) < len(start):
        end = start[: len(start) - len(end)] + end
    if len(end) > len(start):
        end = end[-len(start):]
    return start, end


def normalise_depth(locus, depth):
    """Keep the last `depth` components (a structural prefix such as a drama's section number)."""
    return locus[-depth:] if len(locus) > depth else locus


def contains(start, end, locus):
    """True when `locus` (possibly shorter: a book) falls inside [start, end] (component-wise)."""
    n = len(locus)
    if n == 0:
        return False
    lo, hi = start[:n], end[:n]
    return lo <= locus <= hi


# ---------------------------------------------------------------------------------------------
# Query syntax
def _fold(text):
    text = unicodedata.normalize("NFD", str(text or "")).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("ς", "σ")
    return re.sub(r"[\s.,]+", " ", text).strip()


# Author abbreviations and names -> canonical author (as in backend/author_aliases.json).
AUTHORS = {
    "hom": "Homer", "homer": "Homer", "hes": "Hesiod", "hesiod": "Hesiod", "pi": "Pindar", "pind": "Pindar",
    "pindar": "Pindar", "b": "Bacchylides", "bacch": "Bacchylides", "bacchylides": "Bacchylides",
    "sapph": "Sappho", "sappho": "Sappho", "sa": "Sappho", "alc": "Alcaeus", "alcaeus": "Alcaeus",
    "anacr": "Anacreon", "anacreon": "Anacreon", "alcm": "Alcman", "alcman": "Alcman", "ibyc": "Ibycus",
    "ibycus": "Ibycus", "stes": "Stesichorus", "stesich": "Stesichorus", "stesichorus": "Stesichorus",
    "simon": "Simonides", "simonides": "Simonides", "archil": "Archilochus", "archilochus": "Archilochus",
    "semon": "Semonides", "semonides": "Semonides", "hippon": "Hipponax", "hipponax": "Hipponax",
    "sol": "Solon", "solon": "Solon", "tyrt": "Tyrtaeus", "tyrtaeus": "Tyrtaeus", "mimn": "Mimnermus",
    "mimnermus": "Mimnermus", "thgn": "Theognis", "theogn": "Theognis", "theognis": "Theognis",
    "xenoph": "Xenophanes", "xenophanes": "Xenophanes", "corinn": "Corinna", "corinna": "Corinna",
    "a": "Aeschylus", "aesch": "Aeschylus", "aeschylus": "Aeschylus", "s": "Sophocles", "soph": "Sophocles",
    "sophocles": "Sophocles", "e": "Euripides", "eur": "Euripides", "euripides": "Euripides",
    "ar": "Aristophanes", "aristoph": "Aristophanes", "aristophanes": "Aristophanes",
    "a r": "Apollonius Rhodius", "ap rh": "Apollonius Rhodius", "apollonius rhodius": "Apollonius Rhodius",
    "theoc": "Theocritus", "theocr": "Theocritus", "theocritus": "Theocritus", "call": "Callimachus",
    "callim": "Callimachus", "callimachus": "Callimachus", "nonn": "Nonnus", "nonnus": "Nonnus",
    "q s": "Quintus Smyrnaeus", "qs": "Quintus Smyrnaeus", "quint smyrn": "Quintus Smyrnaeus",
    "quintus smyrnaeus": "Quintus Smyrnaeus", "quintus": "Quintus Smyrnaeus", "opp": "Oppian", "oppian": "Oppian",
    "arat": "Aratus", "aratus": "Aratus", "nic": "Nicander", "nicander": "Nicander", "lyc": "Lycophron",
    "lycophron": "Lycophron", "mosch": "Moschus", "moschus": "Moschus", "bion": "Bion", "mus": "Musaeus",
    "musae": "Musaeus", "musaeus": "Musaeus", "d p": "Dionysius Periegetes", "dion per": "Dionysius Periegetes",
    "dionysius periegetes": "Dionysius Periegetes", "h hom": "Homeric Hymns", "hymn hom": "Homeric Hymns",
    "homeric hymns": "Homeric Hymns", "orph": "Orphica", "orph h": "Orphica", "orphica": "Orphica",
    "anacreont": "Anacreontea", "anacreontea": "Anacreontea", "ap": "Greek Anthology", "a p": "Greek Anthology",
    "anth pal": "Greek Anthology", "greek anthology": "Greek Anthology", "anthologia graeca": "Greek Anthology",
}
# Work abbreviations and titles per author -> display work title (author_catalogue.display_work).
WORKS = {
    "Homer": {"il": "Iliad", "iliad": "Iliad", "od": "Odyssey", "odyssey": "Odyssey"},
    "Hesiod": {"th": "Theogony", "theog": "Theogony", "theogony": "Theogony", "op": "Works and Days",
               "erga": "Works and Days", "works and days": "Works and Days", "sc": "Shield of Heracles",
               "scut": "Shield of Heracles", "shield": "Shield of Heracles"},
    "Pindar": {"o": "Olympian Odes", "ol": "Olympian Odes", "olympian": "Olympian Odes", "p": "Pythian Odes",
               "pyth": "Pythian Odes", "pythian": "Pythian Odes", "n": "Nemean Odes", "nem": "Nemean Odes",
               "nemean": "Nemean Odes", "i": "Isthmian Odes", "isthm": "Isthmian Odes", "isthmian": "Isthmian Odes"},
    "Apollonius Rhodius": {"arg": "Argonautica", "argonautica": "Argonautica"},
    "Nonnus": {"d": "Dionysiaca", "dion": "Dionysiaca", "dionysiaca": "Dionysiaca"},
    "Quintus Smyrnaeus": {"posthom": "Posthomerica", "posthomerica": "Posthomerica"},
    "Oppian": {"h": "Halieutica", "hal": "Halieutica", "halieutica": "Halieutica"},
    "Aratus": {"phaen": "Phaenomena", "phaenomena": "Phaenomena"},
    "Nicander": {"th": "Theriaca", "ther": "Theriaca", "theriaca": "Theriaca", "al": "Alexipharmaca",
                 "alex": "Alexipharmaca", "alexipharmaca": "Alexipharmaca"},
    "Lycophron": {"alex": "Alexandra", "alexandra": "Alexandra"},
    "Musaeus": {"hero": "Hero and Leander", "hero and leander": "Hero and Leander"},
    "Theocritus": {"id": "Idylls", "idylls": "Idylls", "ep": "Epigrams", "epigr": "Epigrams", "epigrams": "Epigrams"},
}
# A work abbreviation that names its author by itself ("Il. 1.1").
STANDALONE = {"il": ("Homer", "Iliad"), "iliad": ("Homer", "Iliad"), "od": ("Homer", "Odyssey"),
              "odyssey": ("Homer", "Odyssey"), "theog": ("Hesiod", "Theogony"), "theogony": ("Hesiod", "Theogony"),
              "works and days": ("Hesiod", "Works and Days"), "argonautica": ("Apollonius Rhodius", "Argonautica"),
              "dionysiaca": ("Nonnus", "Dionysiaca"), "posthomerica": ("Quintus Smyrnaeus", "Posthomerica"),
              "halieutica": ("Oppian", "Halieutica"), "phaenomena": ("Aratus", "Phaenomena"),
              "alexandra": ("Lycophron", "Alexandra")}
_LOCUS = r"(?P<locus>\d{1,5}[a-zA-Z]{0,2}(?:\.\d{1,5}[a-zA-Z]{0,2}){0,3}(?:\s*[–-]\s*\d{1,5}[a-zA-Z]{0,2}(?:\.\d{1,5}[a-zA-Z]{0,2}){0,3})?)"
_SCHEMES = {"v": "Voigt", "voigt": "Voigt", "lp": "Lobel-Page", "l-p": "Lobel-Page", "lobel-page": "Lobel-Page",
            "lobelpage": "Lobel-Page", "lobel&page": "Lobel-Page",
            "pmg": "PMG", "page": "Page", "pmgf": "PMGF", "campbell": "Campbell", "c": "Campbell",
            "w": "West", "west": "West", "d": "Diehl", "diehl": "Diehl", "edmonds": "Edmonds", "bergk": "Bergk",
            "f": "Finglass", "finglass": "Finglass", "slg": "SLG",
            # release Q
            "lobelandpage": "Lobel-Page", "lobel-and-page": "Lobel-Page", "plf": "Lobel-Page",
            "campbellglp": "Campbell GLP", "glp": "Campbell GLP", "campbell-glp": "Campbell GLP"}
# A query naming "Campbell" means either Campbell edition in this corpus: the Loeb Greek Lyric (as the
# Digital Sappho records name it) or Greek Lyric Poetry (1967), whose own records are cited by heading.
_QUERY_SCHEMES = {"Campbell": ("Campbell", "Campbell GLP")}
# Scheme names spelled out in full may stand before the number ("Sappho Campbell 16", "Voigt 31");
# single-letter sigla only after it ("Sappho 31 V").
_LEADING_SCHEMES = {k for k in _SCHEMES if len(k.replace("-", "")) >= 2 and k not in ("lp",)} | {"l-p", "lp"}


def scheme_name(text):
    """Canonical numbering-scheme name for a siglum or name ('L.P.', 'lobel page', 'V'), else None."""
    key = _fold(text)
    return _SCHEMES.get(key.replace(" ", "")) or _SCHEMES.get(key)


def query_schemes(scheme):
    """The stored scheme names a queried scheme covers."""
    return _QUERY_SCHEMES.get(scheme, (scheme,)) if scheme else ()


def parse_citation(query):
    """{kind: urn|locus|fragment, ...} for a citation-shaped query, else None. Never guesses an author."""
    q = unicodedata.normalize("NFC", str(query or "")).strip()
    if not q or len(q) > 120 or not re.search(r"\d", q):
        return None
    m = URN.match(q)
    if m:
        locus = parse_range(m[4]) if m[4] else None
        return {"kind": "urn", "tlg_author": m[1].lower(), "tlg_work": (m[2] or "").lower() or None,
                "edition": m[3], "locus": list(locus[0]) if locus else None,
                "locus_end": list(locus[1]) if locus else None, "query": q}
    if q.lower().startswith("urn:"):
        return {"kind": "urn", "invalid": True, "query": q}
    scheme = ""
    tail = re.search(r"(?<=\d)(?:[a-zA-Z]?)\s+([A-Za-z][A-Za-z.&-]*(?:\s?[&-]?\s?[A-Za-z.]+)?)\s*$", q)
    if tail:
        name = _SCHEMES.get(_fold(tail[1]).replace(" ", "")) or _SCHEMES.get(_fold(tail[1]))
        if not name:
            return None
        scheme, q_core = name, q[: tail.start(1)].strip()
    else:
        q_core = q
    loc = re.search(_LOCUS + r"\s*$", q_core)
    if not loc:
        return None
    if loc.start() == 0 or q_core[loc.start() - 1] not in " . ":
        return None  # "a123b" is a word with digits, not "A. 123b"
    head = q_core[: loc.start()].strip().rstrip(",")
    marker = re.search(r"(?i)(?:^|\s)(?:fr(?:ag(?:ment)?)?s?|frr|f)\.?\s*$", head)
    if marker:
        head = head[: marker.start()].strip()
    if not scheme:
        # Release Q: a spelled-out scheme before the number ("Sappho Campbell 16", "Voigt 31",
        # "Sapph. L-P 31", "Alc. Lobel & Page 346").
        lead = re.search(r"(?:^|[\s,])([A-Za-z][A-Za-z.&-]*(?:\s?[&-]\s?[A-Za-z.]+)?)\s*$", head)
        if lead:
            folded = _fold(lead[1])
            name = None
            for k in (folded.replace(" ", ""), folded):
                if k in _LEADING_SCHEMES:
                    name = _SCHEMES[k]
                    break
            if name:
                scheme = name
                head = head[: lead.start(1)].strip().rstrip(",")
                inner = re.search(r"(?i)(?:^|\s)(?:fr(?:ag(?:ment)?)?s?|frr|f)\.?\s*$", head)
                if inner:
                    head = head[: inner.start()].strip()
                    marker = marker or inner
                if not head:
                    rng = parse_range(loc["locus"])
                    if not rng or len(rng[0]) != 1:
                        return None
                    # No poet named: every poet with that number in that numbering (resolution time).
                    return {"kind": "fragment", "author": None, "work": None, "work_prefix": None,
                            "locus": list(rng[0]), "locus_end": list(rng[1]), "scheme": scheme, "query": query}
    key = _fold(head)
    words = key.split()
    author = work = None
    work_prefix = None
    for split in range(len(words), 0, -1):
        author_key, rest = " ".join(words[:split]), " ".join(words[split:])
        if author_key not in AUTHORS:
            continue
        found = AUTHORS[author_key]
        if rest:
            title = WORKS.get(found, {}).get(rest)
            if not title:
                # Any other title is matched against the author's stored work titles at
                # resolution time ("Eur. Med." -> Medea): a unique title starting with it.
                if not rest.replace(" ", "").isalpha() or len(rest) > 30:
                    continue
                work_prefix = rest
            work = title
        author = found
        break
    if not author and key in STANDALONE:
        author, work = STANDALONE[key]
    if not author:
        return None
    rng = parse_range(loc["locus"])
    if not rng:
        return None
    is_fragment = bool(marker or scheme) or (work is None and len(rng[0]) == 1 and author not in _LINE_AUTHORS)
    if work_prefix:
        is_fragment = False
    return {"kind": "fragment" if is_fragment else "locus", "author": author, "work": work,
            "work_prefix": work_prefix, "locus": list(rng[0]), "locus_end": list(rng[1]),
            "scheme": scheme or None, "query": query}


# Authors whose bare "Author N" means a poem/line locus rather than a fragment number.
_LINE_AUTHORS = {"Theognis", "Bacchylides", "Musaeus", "Lycophron", "Aratus", "Theocritus", "Moschus", "Bion",
                 "Anacreontea"}


# ---------------------------------------------------------------------------------------------
class CitationIndex:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MELOS_CITATION_INDEX", str(DEFAULT_PATH)))
        if not self.path.exists():
            raise FileNotFoundError("Citation index not built: " + str(self.path))
        self._local = threading.local()
        con = self.con()
        self.manifest = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        self.works = [dict(r) for r in con.execute("SELECT * FROM work")]
        self.by_key = {w["work_key"]: w for w in self.works}

    def con(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def works_for(self, author=None, work=None, tlg_author=None, tlg_work=None):
        out = []
        for w in self.works:
            if tlg_author and w["tlg_author"] != tlg_author:
                continue
            if tlg_work and w["tlg_work"] != tlg_work:
                continue
            if author and w["author"] != author:
                continue
            if work and w["display_work"] != work:
                continue
            out.append(w)
        return out

    def loci(self, works, locus, locus_end=None, limit=40):
        """Passages of these works whose range overlaps [locus, locus_end] (book-level prefix allowed)."""
        hits = []
        locus = tuple(tuple(x) for x in locus)
        end = tuple(tuple(x) for x in (locus_end or locus))
        for w in works:
            depth = w["depth"] or len(locus)
            lo = normalise_depth(locus, depth)
            hi = normalise_depth(end, depth)
            rows = self.con().execute(
                "SELECT * FROM locus WHERE work_key=? AND s0<=? AND e0>=? ORDER BY seq",
                (w["work_key"], hi[0][0], lo[0][0])).fetchall()
            for row in rows:
                start = tuple(tuple(x) for x in json.loads(row["start"]))
                stop = tuple(tuple(x) for x in json.loads(row["end"]))
                n = min(len(lo), len(start))
                if start[:n] <= hi[:n] and lo[:n] <= stop[:n]:
                    exact = start[:len(lo)] == lo or contains(start, stop, lo)
                    hits.append(dict(row, work=w, exact=bool(exact)))
        rank = {"text": 0, "reference": 2, "commentary": 3, "apparatus": 4}
        hits.sort(key=lambda h: (not h["exact"], rank.get(h["kind"], 5), h["quality"] not in SEARCHABLE,
                                 h["work"]["work_key"], h["seq"]))
        return hits[:limit], len(hits)

    def equivalents(self, author, number, scheme=""):
        rows = self.con().execute("SELECT * FROM equiv WHERE author=? AND (num_a=? OR num_b=?)",
                                  (author, number.lower(), number.lower())).fetchall()
        out = []
        for r in rows:
            if r["num_a"] == number.lower() and (not scheme or r["scheme_a"] == scheme):
                out.append({"scheme": r["scheme_b"], "number": r["num_b"], "from_scheme": r["scheme_a"],
                            "record": r["passage_id"], "evidence": r["evidence"]})
            elif r["num_b"] == number.lower() and (not scheme or r["scheme_b"] == scheme):
                out.append({"scheme": r["scheme_a"], "number": r["num_a"], "from_scheme": r["scheme_b"],
                            "record": r["passage_id"], "evidence": r["evidence"]})
        return out

    # ------------------------------------------------------------------ fragment numbers (release Q)
    def has_fragment_refs(self):
        if not hasattr(self, "_has_frag"):
            self._has_frag = bool(self.con().execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fragment_ref'").fetchone())
        return self._has_frag

    def fragment_refs(self, author, scheme, number):
        """Records citable as `number` in `scheme` (rows: passage_id, scheme, number, basis, evidence)."""
        if not self.has_fragment_refs():
            return []
        sql = "SELECT * FROM fragment_ref WHERE scheme=? AND number=?" + (" AND author=?" if author else "")
        args = (scheme, str(number).lower()) + ((author,) if author else ())
        return [dict(r) for r in self.con().execute(sql + " ORDER BY passage_id", args)]

    def ref_number_ids(self, number, corpus_path):
        """Ids of every record whose citation/metadata states this fragment number (release-O reading),
        or None when the index has no such table or was built from another corpus file."""
        if not hasattr(self, "_has_ref_numbers"):
            self._has_ref_numbers = bool(self.con().execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ref_number'").fetchone())
        if not self._has_ref_numbers:
            return None
        try:
            st = os.stat(corpus_path)
        except OSError:
            return None
        if (st.st_size, st.st_mtime_ns) != (self.manifest.get("corpus_size"), self.manifest.get("corpus_mtime_ns")):
            return None
        return [r[0] for r in self.con().execute("SELECT passage_id FROM ref_number WHERE number=?", (number,))]

    def fragment_authors(self, scheme, number):
        """Poets with a record citable as `number` in this (queried) scheme, or with an equivalence row."""
        out = []
        for s in query_schemes(scheme):
            if self.has_fragment_refs():
                out += [r[0] for r in self.con().execute(
                    "SELECT DISTINCT author FROM fragment_ref WHERE scheme=? AND number=?", (s, str(number).lower()))]
            out += [r[0] for r in self.con().execute(
                "SELECT DISTINCT author FROM equiv WHERE (scheme_a=? AND num_a=?) OR (scheme_b=? AND num_b=?)",
                (s, str(number).lower(), s, str(number).lower()))]
        return sorted(set(out))

    def concordance(self, author, scheme, number):
        """Every (scheme, number) equal to the query for this poet, nearest first.

        Edges: an equivalence printed by a record or stated by a cited source (strength 'printed'
        / 'source'), and a source's general statement that two numberings agree (strength
        'convention'; used only when no explicit equivalence names either number). Returns dicts
        {scheme, number, strength, via: [edge evidence...]}; the query node itself is first."""
        number = str(number).lower()
        rows = [dict(r) for r in self.con().execute("SELECT * FROM equiv WHERE author=?", (author,))]
        edges = {}
        for r in rows:
            a, b = (r["scheme_a"], r["num_a"]), (r["scheme_b"], r["num_b"])
            ev = r["evidence"]
            try:
                parsed = json.loads(ev) if ev and ev.startswith("{") else None
            except ValueError:
                parsed = None
            edge = ({"strength": "source", "source": parsed} if parsed and not r["passage_id"]
                    else {"strength": "printed", "record": r["passage_id"], "evidence": ev})
            edges.setdefault(a, []).append((b, edge))
            edges.setdefault(b, []).append((a, edge))
        conventions = [c for c in ((self.manifest.get("concordance") or {}).get("conventions") or [])
                       if author in (c.get("authors") or [])]

        def convention_edges(node):
            out = []
            for c in conventions:
                pair = c.get("schemes") or []
                if node[0] not in pair or len(pair) != 2:
                    continue
                other = pair[1] if node[0] == pair[0] else pair[0]
                target = (other, node[1])
                # An explicit equivalence between these two numberings that names either number
                # overrides the convention (e.g. Voigt 105B = L-P 105C).
                explicit = any(nb[0] == other for nb, _ in edges.get(node, [])) or \
                    any(nb[0] == node[0] for nb, _ in edges.get(target, []))
                if not explicit:
                    out.append((target, {"strength": "convention", "relation": c.get("relation"),
                                         "source": c.get("source")}))
            return out

        order = {"query": 0, "printed": 1, "source": 1, "convention": 2}
        start = [(s, number) for s in query_schemes(scheme)]
        seen = {n: {"scheme": n[0], "number": n[1], "strength": "query", "via": []} for n in start}
        frontier = list(start)
        while frontier:
            node = frontier.pop(0)
            here = seen[node]
            for nb, edge in edges.get(node, []) + convention_edges(node):
                # A path is as strong as its weakest edge.
                rank = max(order[here["strength"]], order[edge["strength"]])
                strength = ("convention" if rank == 2 else
                            edge["strength"] if here["strength"] == "query" else here["strength"])
                if nb in seen and (order[seen[nb]["strength"]], len(seen[nb]["via"])) <= (rank, len(here["via"]) + 1):
                    continue
                seen[nb] = {"scheme": nb[0], "number": nb[1], "strength": strength, "via": here["via"] + [edge]}
                frontier.append(nb)
        return sorted(seen.values(), key=lambda n: (order[n["strength"]], len(n["via"]), n["scheme"], n["number"]))

    def status(self):
        out = {"ready": True, **{k: self.manifest.get(k) for k in ("version", "built_at", "works", "loci",
                                                                  "tlg_mapped_works", "equivalences", "fragment_refs",
                                                                  "fragment_ref_bases")}}
        return out


_INDEX = None
_LOCK = threading.Lock()


def get_citation_index():
    global _INDEX
    with _LOCK:
        if _INDEX is None:
            _INDEX = CitationIndex()
        return _INDEX


def _locus_text(locus):
    return ".".join(f"{n}{s}" for n, s in locus)


def resolve(query, limit=20):
    """Resolve a citation query. Returns None when the query is not citation-shaped."""
    parsed = parse_citation(query)
    if not parsed:
        return None
    if parsed.get("invalid"):
        return {"query": query, "parsed": parsed, "results": [], "total": 0,
                "warnings": ["Not a CTS URN of the form urn:cts:greekLit:tlgNNNN.tlgNNN[.edition][:passage]."]}
    index = get_citation_index()
    warnings = []
    if parsed["kind"] == "urn":
        works = index.works_for(tlg_author=parsed["tlg_author"], tlg_work=parsed["tlg_work"])
        if not works:
            return {"query": query, "parsed": parsed, "results": [], "total": 0, "works": [],
                    "warnings": ["No work in this corpus is mapped to that TLG number (mappings come only from "
                                 "records and open catalogues; see /api/cite/catalogue)."]}
        if not parsed["locus"]:
            first = [dict(w, first_passage=w.get("first_passage")) for w in works]
            return {"query": query, "parsed": parsed, "works": first, "results": [], "total": 0,
                    "warnings": ["The URN names a work, not a passage: add :book.line to go to a passage."]}
        hits, total = index.loci(works, parsed["locus"], parsed["locus_end"], max(limit, 40))
        if parsed.get("edition"):
            # A URN naming an edition puts that edition's passage first.
            hits.sort(key=lambda h: f".{parsed['edition']}:" not in h["passage_id"] + ":")
        hits = hits[:limit]
    elif parsed["kind"] == "locus":
        works = index.works_for(author=parsed["author"], work=parsed["work"])
        if parsed.get("work_prefix"):
            prefix = _fold(parsed["work_prefix"])
            titles = {w["display_work"] for w in works if _fold(w["display_work"]).startswith(prefix)}
            works = [w for w in works if w["display_work"] in titles] if len(titles) == 1 else []
            if len(titles) > 1:
                warnings.append("The work abbreviation matches several titles: " + ", ".join(sorted(titles)))
        # Other collections of the same text (same TLG work number, e.g. Perseus "Olympian" and
        # OGC "olympia") are cited the same way.
        numbers = {(w["tlg_author"], w["tlg_work"]) for w in works if w["tlg_work"]}
        works += [w for w in index.works if (w["tlg_author"], w["tlg_work"]) in numbers and w not in works]
        works = [w for w in works if w["depth"] and (parsed["work"] or w["loci"] >= 1)]
        if not parsed["work"]:
            # "Bacchylides 17.1", "Theognis 237": every work of the author with that locus shape.
            works = [w for w in works if w["depth"] == len(parsed["locus"]) or len(parsed["locus"]) < (w["depth"] or 0)]
        hits, total = index.loci(works, parsed["locus"], parsed["locus_end"], limit) if works else ([], 0)
        if not works:
            warnings.append("No stored work of this author is cited by line or book in this corpus.")
    else:
        return {"query": query, "parsed": parsed, "results": [], "total": 0, "fragment": True, "warnings": []}
    if total and not any(h["exact"] for h in hits):
        warnings.append("No stored passage starts at or contains exactly this locus; overlapping passages are listed.")
    if not total:
        warnings.append("No stored passage of this work covers that locus (the edition may number differently, "
                        "or the passage is not in the corpus).")
    results = [{"id": h["passage_id"], "author": h["work"]["author"], "work": h["work"]["display_work"],
                "citation": h["citation"], "source": h["source"], "edition": h["edition"], "kind": h["kind"],
                "quality": h["quality"], "locus_start": _locus_text(json.loads(h["start"])),
                "locus_end": _locus_text(json.loads(h["end"])), "contains_locus": h["exact"],
                "tlg": (f"{h['work']['tlg_author']}.{h['work']['tlg_work']}" if h["work"]["tlg_work"] else None)}
               for h in hits]
    return {"query": query, "parsed": parsed, "results": results, "total": total, "warnings": warnings,
            "method": "Printed citations of stored passages parsed as locus ranges; every edition whose range "
                      "contains the cited locus, edited text first."}


__all__ = ["parse_citation", "parse_range", "resolve", "get_citation_index", "CitationIndex", "scheme_name",
           "query_schemes"]
