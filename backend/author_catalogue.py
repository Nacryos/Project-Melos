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
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .author_aliases import canonical as canonical_author, fold

ROOT = Path(__file__).resolve().parents[1]
CHRONOLOGY = ROOT / "data/metadata/chronology.json"
GENRE_BASIS = "Editorial classification by conventional genre (release O catalogue), not a source claim"
DATE_BASIS = ("Wikidata biographical claim (birth or floruit envelope) for the author, from "
              "data/metadata/chronology.json; not a composition date")

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
    if not CHRONOLOGY.exists():
        return {}
    data = json.loads(CHRONOLOGY.read_text(encoding="utf-8"))
    out = {}
    for row in data.get("authors", []):
        claim = row.get("author_chronology")
        if not claim:
            continue
        for label in [row.get("site_author"), row.get("source_author"), *row.get("source_aliases_en", [])]:
            if label:
                out[fold(canonical_author(label))] = claim
                out[fold(label)] = claim
    return out


def author_date(label):
    """Sourced claim for an author label, or None (undated). Never estimated."""
    stamp = CHRONOLOGY.stat().st_mtime_ns if CHRONOLOGY.exists() else 0
    table = _chronology(stamp)
    return table.get(fold(canonical_author(label or ""))) or table.get(fold(label or ""))


def period_of(year):
    if year is None:
        return None
    for label, first, last in PERIODS:
        if first <= year <= last:
            return label
    return None


def author_record(label):
    """{author, label, genre, genre_basis, date{...}|None, period, date_note}."""
    name = canonical_author(label or "") or (label or "")
    genre = _GENRE_OF.get(fold(name))
    claim = author_date(label)
    date = None
    period = None
    note = "Undated: no sourced biographical date claim in data/metadata/chronology.json."
    if claim and claim.get("sort_start") is not None:
        start, end = claim.get("sort_start"), claim.get("sort_end")
        period = period_of(claim.get("sort_year"))
        spans = period_of(start) != period_of(end)
        date = {"start": start, "end": end, "year": claim.get("sort_year"), "kind": claim.get("claim_kind"),
                "source_url": claim.get("source_url"), "approximate": start != end,
                "range_years": (end - start) if (start is not None and end is not None) else None,
                "crosses_period_boundary": spans}
        note = (DATE_BASIS + (". Approximate: the claim is a range" if start != end else "")
                + ("; the range crosses a period boundary" if spans else "") + ".")
    return {"author": name, "label": label, "genre": genre, "genre_basis": GENRE_BASIS if genre else None,
            "date": date, "period": period, "date_note": note}


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
