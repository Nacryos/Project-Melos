"""Readable names for corpus collection ids (the `source` field stays the internal id).

Labels name the collection as its collector documents it (scripts/ingest_*.py,
scripts/build_campbell_glp.py). Unknown ids fall back to their words, title-cased.
"""
from __future__ import annotations

SOURCE_LABELS = {
    "campbell_assignment": "Campbell, Greek Lyric Poetry (1967)",
    "commentary": "Duke Collection of Literary Papyri (commentary and apparatus)",
    "lyra": "Lyra Graeca and Bergk, page OCR (reference index)",
    "lyric_web": "Greek Wikisource",
    "ogc": "Open Greek and Latin",
    "ogc_derived": "Open Greek and Latin (derived passages)",
    "p2_alcaeus": "Greek Wikisource (Alcaeus, after Edmonds)",
    "p2_cgl_anthology": "Centre for the Greek Language, Anthology of Archaic Lyric Poetry",
    "p2_editions": "Public-domain lyric editions, page OCR",
    "p2_elegy": "Elegiac and iambic witnesses",
    "p2_grammar": "Dickinson College Commentaries (dialect grammar)",
    "p2_ibycus": "Ibycus bibliography and fragment locators",
    "p2_melic": "Greek Wikisource (melic poetry)",
    "p2_ogc": "Open Greek and Latin (additional editions)",
    "p2_perseus": "First1KGreek (Pindar scholia and testimonia)",
    "p2_perseus_notes": "Perseus Digital Library (notes)",
    "p2_scholarship": "Dickinson College Commentaries (notes)",
    "p2_stesichorus": "Pitotto, Stesichorus edition",
    "perseus": "Perseus Digital Library",
    "reception": "Perseus Digital Library (Latin reception texts)",
    "sappho": "Digital Sappho and Dickinson Sappho",
}


def source_label(source):
    if not isinstance(source, str) or not source:
        return None
    return SOURCE_LABELS.get(source) or " ".join(word.capitalize() for word in source.replace("-", "_").split("_") if word)


def with_source_label(record):
    if isinstance(record, dict) and record.get("source") and "source_label" not in record:
        record["source_label"] = source_label(record["source"])
    return record
