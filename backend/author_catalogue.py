"""Author catalogue for display, filtering and diachrony (release O).

- Display names come from the owner alias table (backend/author_aliases.py); one poet is one author.
- Genre is an editorial classification by conventional genre (table below), labelled as such.
- Dates are only the sourced Wikidata biographical claims in data/metadata/chronology.json
  (birth/floruit envelopes, not composition dates). An author without one is "undated";
  nothing is estimated here.
- Work labels: collector slugs (OGC "theogonia", "tlg0199-tlg001") get a readable title; the
  stored label is always kept beside it.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .author_aliases import canonical as canonical_author, fold

ROOT = Path(__file__).resolve().parents[1]
CHRONOLOGY = ROOT / "data/metadata/chronology.json"
GENRE_BASIS = "Editorial classification by conventional genre (release O catalogue), not a source claim"
GENRE_SOURCES = Path(os.getenv("MELOS_GENRE_SOURCES", str(ROOT / "data/metadata/genre_sources.json")))
# Release P: sourced genre labels -> the catalogue's genre names. A source edition's own collection
# or work label (data/metadata/genre_sources.json) is used first, then the author's Wikidata
# "genre" (P136) statements in chronology.json; the editorial table below is the fallback and is
# labelled as such. Labels not listed here (e.g. "poetry", "gnomic poetry") decide nothing.
SOURCE_LABEL_GENRES = (  # (substring of a source-edition label, genre)
    ("ΜΕΛΙΚΟΙ ΠΟΙΗΤΕΣ", "melic lyric"), ("ΕΛΕΓΕΙΕΣ", "elegy"), ("ΙΑΜΒΙΚΑ", "iambus"), ("ΕΠΩΔΟΙ", "iambus"),
    ("ΤΡΟΧΑΪΚΑ", "iambus"), ("Ίαμβοι", "iambus"), ("Επωδοί", "iambus"), ("Ελεγεία", "elegy"), ("Ελεγείαι", "elegy"),
    ("ΕΛΕΓΕΙΟΓΡΑΦΟΙ ΚΑΙ ΙΑΜΒΟΓΡΑΦΟΙ", "elegy and iambus"),
)
WIKIDATA_GENRES = {"iambic poetry": "iambus", "Greek lyric": "melic lyric", "lyric poetry": "melic lyric",
                   "dithyramb": "melic lyric", "epic poem": "epic", "epic poetry": "epic", "Greek tragedy": "tragedy",
                   "tragedy": "tragedy", "comedy": "comedy", "Old Comedy": "comedy", "bucolic poetry": "bucolic",
                   "pastoral": "bucolic", "hymn": "hymn", "epigram": "epigram", "elegy": "elegy",
                   "elegiac poetry": "elegy"}
DATE_BASIS = ("Wikidata biographical claim (birth, floruit, work period or death envelope) for the author, from "
              "data/metadata/chronology.json; not a composition date")
WORK_DATE_BASIS = ("Wikidata inception claim on the anonymous collection's own item, from "
                   "data/metadata/chronology.json; a date range for the collection, not for each poem")
EDITION_DATE_BASIS = ("Date printed by a source edition stored in the corpus (Edmonds, Lyra Graeca; quoted with its "
                      "passage id in data/metadata/chronology.json), used because Wikidata has no referenced date "
                      "claim; an author-period or collection range, not a poem date")

GENRES = {
    "epic": ["Homer", "Apollonius Rhodius", "Quintus Smyrnaeus", "Nonnus", "Musaeus", "Homerica"],
    "didactic and hexameter": ["Hesiod", "Aratus", "Nicander", "Oppian", "Dionysius Periegetes", "Diodorus Periegetes"],
    "hymn": ["Homeric Hymns", "Orphica"],
    "melic lyric": ["Sappho", "Alcaeus", "Anacreon", "Anacreontea", "Ibycus", "Corinna", "Praxilla", "Telesilla",
                    "Timocreon", "Scolia", "Carmina Popularia", "Terpander", "Lasus", "Timotheus", "Philoxenus",
                    "Telestes", "Pratinas", "Erinna"],
    "choral lyric": ["Alcman", "Stesichorus", "Simonides", "Pindar", "Bacchylides"],
    "elegy": ["Theognis", "Solon", "Tyrtaeus", "Mimnermus", "Callinus", "Xenophanes", "Phocylides", "Demodocus"],
    "iambus": ["Archilochus", "Semonides", "Hipponax", "Ananius"],
    "tragedy": ["Aeschylus", "Sophocles", "Euripides", "Lycophron"],
    "comedy": ["Aristophanes"],
    "bucolic": ["Theocritus", "Moschus", "Bion"],
    "Hellenistic hymn, elegy and epigram": ["Callimachus"],
    "epigram": ["Greek Anthology", "Agathias Scholasticus", "Posidippus"],
    "scholia and scholarship": ["Scholia on Pindar", "Scholia on Homer", "Scholia on Hesiod",
                                "Scholia on Apollonius Rhodius", "Scholia on Lycophron", "Scholia on Callimachus",
                                "Scholia on Theocritus", "Hephaestion", "Porphyry"],
}
_GENRE_OF = {fold(name): genre for genre, names in GENRES.items() for name in names}

PERIODS = (  # (label, first year inclusive, last year inclusive); negative = BCE
    ("Archaic (to 480 BCE)", -10000, -481),
    ("Classical (480–323 BCE)", -480, -324),
    ("Hellenistic (323–31 BCE)", -323, -32),
    ("Roman imperial (31 BCE–300 CE)", -31, 299),
    ("Late antique (300–600 CE)", 300, 599),
    ("Byzantine (from 600 CE)", 600, 10000),
)

WORK_TITLES = {
    "ilias": "Iliad", "odyssea": "Odyssey", "theogonia": "Theogony", "opera-et-dies": "Works and Days",
    "scutum": "Shield of Heracles", "olympia": "Olympian Odes", "pythia": "Pythian Odes", "nemea": "Nemean Odes",
    "isthmia": "Isthmian Odes", "tlg0199-tlg001": "Epinicians", "tlg0199-tlg002": "Dithyrambs",
    "dionysiaca": "Dionysiaca", "posthomerica": "Posthomerica", "argonautica": "Argonautica",
    "halieutica": "Halieutica", "idyllia": "Idylls", "alexandra": "Alexandra", "phaenomena": "Phaenomena",
    "theriaca": "Theriaca", "alexipharmaca": "Alexipharmaca", "orbis-descriptio": "Description of the World",
    "hymni": "Hymns", "elegiae": "Elegies", "fragmenta": "Fragments", "fragmentum": "Fragment",
    "epigrammata": "Epigrams", "epigrammata-2": "Epigrams", "hero-et-leander": "Hero and Leander",
    "anthologia-graeca": "Greek Anthology", "sententiae": "Sayings", "europa": "Europa", "hecala": "Hecale",
    "aetia": "Aetia", "iambi": "Iambi", "testimonia": "Testimonia", "anacreontea": "Anacreontea",
    "megara-sp": "Megara (spurious)", "epitaphius-bionis-sp": "Lament for Bion (spurious)",
    "eros-drapeta": "Runaway Love", "epitaphius-adonis": "Lament for Adonis", "syrinx": "Syrinx",
    "in-mercurium": "Hymn to Hermes", "in-cererem": "Hymn to Demeter", "in-venerem": "Hymn to Aphrodite",
    "in-bacchum": "Hymn to Dionysus", "in-pana": "Hymn to Pan", "in-lunam": "Hymn to Selene",
    "in-solem": "Hymn to Helios", "in-martem": "Hymn to Ares", "in-dianam": "Hymn to Artemis",
    "in-minervam": "Hymn to Athena", "in-junonem": "Hymn to Hera", "in-vestam": "Hymn to Hestia",
    "in-neptunum": "Hymn to Poseidon", "in-jovem": "Hymn to Zeus", "in-herculem": "Hymn to Heracles",
    "in-aesculapium": "Hymn to Asclepius", "in-dioscuros": "Hymn to the Dioscuri", "in-volcanum": "Hymn to Hephaestus",
    "in-matrem-deorum": "Hymn to the Mother of the Gods", "in-tellurem-matrem-omnium": "Hymn to Earth",
    "in-musas-et-apollinem": "Hymn to the Muses and Apollo", "in-apollinem": "Hymn to Apollo",
    "in-apollinem-fort-auctore-cynaetho-chio": "Hymn to Apollo",
    "in-delum-hymn-4": "Hymn 4, to Delos", "in-dianam-hymn-3": "Hymn 3, to Artemis",
    "in-lavacrum-palladis-hymn-5": "Hymn 5, on the Bath of Pallas", "in-cererem-hymn-6": "Hymn 6, to Demeter",
    "in-apollinem-hymn-2": "Hymn 2, to Apollo", "in-jovem-hymn-1": "Hymn 1, to Zeus",
    "fragmenta-hymni-in-bacchum": "Hymn to Dionysus (fragments)", "versus-heroici": "Heroic verses",
    "certamen-homeri-et-hesiodi": "Contest of Homer and Hesiod", "vita-herodotea": "Life of Homer (pseudo-Herodotus)",
    "plutarchi-vita": "Life of Homer (pseudo-Plutarch)", "fragmenta-epica": "Epic fragments",
    "fragmenta-lyrica": "Lyric fragments",
}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$|^[a-z]+$")


@lru_cache(maxsize=4)
def _chronology(stamp):
    """({author/collection label: claim}, {attributed poet label: claim}) from chronology.json."""
    if not CHRONOLOGY.exists():
        return {}, {}
    data = json.loads(CHRONOLOGY.read_text(encoding="utf-8"))
    out, attributed = {}, {}
    for row in data.get("authors", []):
        claim = row.get("author_chronology")
        if not claim:
            continue
        claim = dict(claim, scope=row.get("scope") or "author", entity_label=row.get("source_author"))
        if row.get("scope") == "attributed_author":
            # An epigram's attributed poet (Greek Anthology records): never an author-level key.
            attributed[fold(row.get("site_author") or "")] = claim
            continue
        for label in [row.get("site_author"), row.get("source_author"), *row.get("source_aliases_en", [])]:
            if label:
                out[fold(canonical_author(label))] = claim
                out[fold(label)] = claim
    return out, attributed


def _tables():
    return _chronology(CHRONOLOGY.stat().st_mtime_ns if CHRONOLOGY.exists() else 0)


def author_date(label):
    """Sourced claim for an author label, or None (undated). Never estimated."""
    table = _tables()[0]
    return table.get(fold(canonical_author(label or ""))) or table.get(fold(label or ""))


def attributed_date(label):
    """Sourced claim for the poet a record names as an epigram's author, or None."""
    return _tables()[1].get(fold(label or "")) if label else None


def date_fields(claim):
    """(date dict, period) for a claim with a usable interval; (None, None) otherwise."""
    if not claim or claim.get("sort_start") is None:
        return None, None
    start, end = claim.get("sort_start"), claim.get("sort_end")
    # Release Q: the period comes from the floruit when sourced, else the middle of the active life
    # (scripts/collect_chronology.period_anchor), never the raw birth year; older files fall back
    # to the displayed claim's midpoint.
    anchor = claim.get("period_year")
    rule = claim.get("period_rule") if anchor is not None else "selected_claim_midpoint"
    if anchor is None:
        anchor = claim.get("sort_year")
    period = period_of(anchor)
    return ({"start": start, "end": end, "year": claim.get("sort_year"), "kind": claim.get("claim_kind"),
             "period_year": anchor, "period_rule": rule,
             "period_note": claim.get("period_note") or "period from the midpoint of the displayed claim",
             "scope": claim.get("scope", "author"), "entity": claim.get("entity_label"),
             "source_url": claim.get("source_url"), "approximate": start != end or bool(claim.get("approximate")),
             # Release Q: a date printed by a source edition in the corpus (no referenced Wikidata claim).
             **({"source_passage_ids": claim.get("source_passage_ids"),
                 "edition_statement": claim.get("edition_statement")}
                if claim.get("type") == "edition_date_statement" else {}),
             "range_years": (end - start) if (start is not None and end is not None) else None,
             "crosses_period_boundary": period_of(start) != period_of(end)}, period)


def passage_date(author_label, attributed_author=None):
    """Date for one record: its author's claim, else (Greek Anthology) its attributed poet's claim.

    Returns (date dict | None, period | None, basis)."""
    date, period = date_fields(author_date(author_label))
    if date:
        return date, period, "author"
    if attributed_author and attributed_author.startswith("collection:"):
        # A record filed under a generic label whose CTS textgroup is a catalogued collection.
        date, period = date_fields(author_date(attributed_author[len("collection:"):]))
        return (date, period, "collection") if date else (None, None, "undated")
    date, period = date_fields(attributed_date(attributed_author))
    if date:
        return date, period, "attributed_author"
    return None, None, "undated"


def period_of(year):
    if year is None:
        return None
    for label, first, last in PERIODS:
        if first <= year <= last:
            return label
    return None


@lru_cache(maxsize=4)
def _genre_tables(stamp_sources, stamp_chronology):
    sources = {}
    if GENRE_SOURCES.exists():
        for author, labels in json.loads(GENRE_SOURCES.read_text(encoding="utf-8")).get("authors", {}).items():
            sources[fold(author)] = labels
    wikidata = {}
    if CHRONOLOGY.exists():
        for row in json.loads(CHRONOLOGY.read_text(encoding="utf-8")).get("authors", []):
            if row.get("scope") == "attributed_author" or not row.get("genre_claims"):
                continue
            for label in [row.get("site_author"), row.get("source_author")]:
                if label:
                    wikidata[fold(canonical_author(label))] = row["genre_claims"]
    return sources, wikidata


def _stamp(path):
    return path.stat().st_mtime_ns if path.exists() else 0


def sourced_genre(name):
    """(genre, basis, labels) from sourced labels, or (None, None, labels) when they decide nothing."""
    sources, wikidata = _genre_tables(_stamp(GENRE_SOURCES), _stamp(CHRONOLOGY))
    key = fold(name)
    labels = []
    counts = {}
    for text, info in (sources.get(key) or {}).items():
        genre = next((g for needle, g in SOURCE_LABEL_GENRES if needle in text), None)
        labels.append({"label": text, "records": info.get("count"), "source": info.get("source_description"),
                       "genre": genre})
        if genre:
            counts[genre] = counts.get(genre, 0) + info.get("count", 0)
    # Subsection labels (ΕΛΕΓΕΙΕΣ, ΙΑΜΒΙΚΑ ...) are more specific than the joint section heading.
    specific = {g: n for g, n in counts.items() if g != "elegy and iambus"}
    total = sum(specific.values())
    if total:
        best, n = max(specific.items(), key=lambda kv: kv[1])
        if n * 3 >= total * 2:
            return best, "source_edition_label", labels
        if set(specific) <= {"elegy", "iambus"}:
            return "elegy and iambus", "source_edition_label", labels
    elif counts.get("elegy and iambus"):
        return "elegy and iambus", "source_edition_label", labels
    claims = wikidata.get(key) or []
    for claim in claims:
        labels.append({"label": claim.get("label"), "source": "Wikidata P136 " + str(claim.get("statement_id")),
                       "referenced": claim.get("referenced"), "genre": WIKIDATA_GENRES.get(claim.get("label") or "")})
    mapped = [WIKIDATA_GENRES.get(c.get("label") or "") for c in sorted(claims, key=lambda c: not c.get("referenced"))]
    mapped = [g for g in mapped if g]
    if mapped and len(set(mapped)) == 1:
        return mapped[0], "wikidata_p136", labels
    return None, None, labels


def author_record(label):
    """{author, label, genre, genre_basis, genre_source, genre_labels, date{...}|None, period, date_note}."""
    name = canonical_author(label or "") or (label or "")
    sourced, source_kind, genre_labels = sourced_genre(name)
    genre = sourced or _GENRE_OF.get(fold(name))
    genre_source = source_kind or ("editorial" if genre else None)
    date, period = date_fields(author_date(label))
    note = "Undated: no sourced biographical date claim in data/metadata/chronology.json."
    if date:
        basis = (EDITION_DATE_BASIS if date.get("edition_statement") else
                 WORK_DATE_BASIS if date["scope"] == "work" else DATE_BASIS)
        note = (basis + (". Approximate: the claim is a range" if date["approximate"] else "")
                + ("; the range crosses a period boundary" if date["crosses_period_boundary"] else "") + ". "
                + "Period: " + date["period_note"] + ".")
    basis = {"source_edition_label": "Sourced: the genre named by a source edition's own collection or work label "
                                     "(genre_labels)",
             "wikidata_p136": "Sourced: the author's Wikidata genre (P136) statement (genre_labels)",
             "editorial": GENRE_BASIS}.get(genre_source)
    return {"author": name, "label": label, "genre": genre, "genre_basis": basis, "genre_source": genre_source,
            "genre_labels": genre_labels, "date": date, "period": period, "date_note": note}


def display_work(work, author=""):
    """Readable work title for a collector slug; other labels unchanged."""
    value = unicodedata.normalize("NFC", str(work or "")).strip()
    key = value.lower()
    if key in WORK_TITLES:
        return WORK_TITLES[key]
    base = re.sub(r"-\d+$", "", key)
    if base in WORK_TITLES:
        return WORK_TITLES[base]
    if _SLUG.match(key) and "-" in key:
        return key.replace("-", " ").capitalize()
    return value


def display_fields(record):
    """API display fields; the stored labels stay unchanged in the record."""
    author = record.get("author") or ""
    out = {"display_author": canonical_author(author) if author else author,
           "display_work": display_work(record.get("work"), author)}
    info = author_record(author)
    out["author_genre"] = info["genre"]
    out["author_period"] = info["period"]
    return out


__all__ = ["author_record", "author_date", "display_work", "display_fields", "period_of", "PERIODS", "GENRES"]
