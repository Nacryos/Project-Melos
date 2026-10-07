"""Archived LSJ subordinate orthographies, never inferred morphology.

Only explicit non-primary ``orth`` nodes which own a safely extracted English
definition are indexed. Parent-entry definitions and dialect labels are not
inherited. Search removes internal printed segmentation hyphens only; the
original orthography and source locator remain authoritative.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from .lexicon_render import (_entry_offsets, _raw_digest, _render_spans,
                             _source_path, read_entry)
from .lexicon_senses import dictionary_senses

VERSION = "lsj-explicit-subentry-v2"
OFFSET_BASIS = "uncompacted Greek-span-rendered TEI entry"
HYPHENS = "-\u2010"
EXCLUDED = {"bibl", "cit", "quote", "etym", "xr"}
_DEPENDENT_ENGLISH_FRAGMENT = re.compile(r"(?:at|in|on|of|to|from|by|with|for|into|upon|under|over)(?:\s+(?:a|an|the))?\Z", re.I)


def lookup_key(text):
    """NFC plus internal print segmentation only, not accent/dialect folding.

    A leading/trailing hyphen denotes an incomplete printed stem and cannot
    be used as a full lookup key. No missing prefix/suffix is reconstructed.
    """
    text = unicodedata.normalize("NFC", text.strip())
    if not text or text[0] in HYPHENS or text[-1] in HYPHENS:
        return None
    output = []
    for index, char in enumerate(text):
        if char in HYPHENS:
            if index == 0 or index + 1 == len(text) or text[index - 1] in HYPHENS or text[index + 1] in HYPHENS:
                return None
            continue
        if unicodedata.category(char).startswith("L") and "GREEK" in unicodedata.name(char, ""):
            output.append(char)
        elif unicodedata.category(char).startswith("M") and output:
            output.append(char)
        else:
            return None
    return "".join(output) or None


def _plain(text):
    return re.sub(r"\s+", " ", text).strip()


def _locator(node, spans):
    start, end = spans[node]
    return {"node_path": node.getroottree().getpath(node),
            "rendered_start": start, "rendered_end": end,
            "offset_basis": OFFSET_BASIS}


def _incomplete_definition(sense, entry, text, spans):
    """Reject a demonstrably unsafe TEI layout, without repairing its prose.

    Archived LSJ sometimes labels a definition's place-name complement as
    ``bibl/author``. A bare English preposition followed by such an unlocated
    name is not a safe complete gloss. Other definitions remain unchanged.
    """
    if not _DEPENDENT_ENGLISH_FRAGMENT.fullmatch(sense.get("text", "").strip(" ,;")):
        return False
    locator = sense.get("source_locator") or {}
    nodes = entry.getroottree().xpath(locator.get("node_path", "/nonexistent"))
    if len(nodes) != 1:
        return True
    node = nodes[0]
    following = node.getnext()
    return (following is not None and following.tag == "bibl"
            and not following.get("n")
            and bool(following.findall("author"))
            and all(child.tag == "author" for child in following)
            and not text[spans[node][1]:spans[following][0]].strip())


def extract_subentries(record):
    """Fail closed on missing provenance; all values derive from archived XML."""
    if record.get("source") != "PerseusDL LSJ TEI":
        return []
    required = ("raw_path", "raw_sha256", "entry_id", "id", "source_url")
    if not all(record.get(key) for key in required):
        raise ValueError("Missing LSJ subentry provenance")
    path = _source_path(record["raw_path"])
    stat = path.stat()
    if _raw_digest(path, stat.st_mtime_ns, stat.st_size) != record["raw_sha256"]:
        raise ValueError("LSJ source hash mismatch")
    entry, entities = read_entry(record["raw_path"], record["entry_id"])
    orths = [node for node in entry.iter("orth")
             if not any(a.tag in EXCLUDED for a in node.iterancestors())]
    if len(orths) < 2:
        return []
    senses_result = dictionary_senses(record)
    if senses_result.get("dictionary_senses_status") not in {"source_structured", "no_safe_definition_spans"}:
        raise ValueError("Subentry definition source unavailable")
    text, spans = _render_spans(entry, entities)
    entry_start, entry_end = _entry_offsets(path, stat.st_mtime_ns, stat.st_size)[record["entry_id"]]
    rows = []
    for orth in orths[1:]:
        locator = _locator(orth, spans)
        rendered = _plain(text[slice(*spans[orth])])
        key = lookup_key(rendered)
        if key is None:
            continue
        definitions = [deepcopy(sense) for sense in senses_result.get("dictionary_senses", [])
                       if sense.get("form_scope", {}).get("relation") == "variant"
                       and sense.get("form_scope", {}).get("source_locator", {}).get("node_path") == locator["node_path"]
                       and not _incomplete_definition(sense, entry, text, spans)]
        if not definitions:
            continue
        scope = next((a for a in orth.iterancestors() if a.tag == "sense"), entry)
        next_orth = next((node for node in orths if spans[node][0] > spans[orth][0]
                          and spans[node][0] < spans[scope][1]), None)
        end = spans[next_orth][0] if next_orth is not None else spans[scope][1]
        citations = [{"text": _plain(text[slice(*spans[node])]), "reference": node.get("n"),
                      "source_locator": _locator(node, spans)}
                     for node in scope.iter("bibl")
                     if spans[orth][1] <= spans[node][0] < end]
        qualifiers = []
        previous = orth.getprevious()
        if (previous is not None and previous.tag == "gramGrp"
                and not text[spans[previous][1]:spans[orth][0]].strip()):
            qualifiers = [{"text": _plain(text[slice(*spans[node])]),
                           "type": node.get("type"), "source_locator": _locator(node, spans)}
                          for node in previous.iter("gram")]
        rows.append({
            "id": f"{record['id']}:{VERSION}:{locator['node_path']}",
            "evidence_type": "dictionary_explicit_subentry",
            "scope": "source_dictionary_orthography_not_morphological_analysis",
            "parent_lexicon_entry_id": record["id"], "parent_entry_id": record["entry_id"],
            "parent_headword": record.get("lemma"), "parent_lemma_beta": record.get("lemma_beta"),
            "orthography": rendered, "orthography_raw": "".join(orth.itertext()),
            "orthography_raw_encoding": "Perseus Beta Code",
            "orth_extent": orth.get("extent"), "lookup_key": key,
            "spelling_validation": "literal_source_spelling_not_independently_validated_full_form",
            "morphology_status": "not_supplied",
            "lookup_method": "NFC; internal printed segmentation hyphens removed for retrieval only; no case/accent/dialect folding",
            "source_locator": locator,
            "entry_byte_start": entry_start, "entry_byte_end": entry_end,
            "dictionary_senses": definitions, "citations": citations,
            "citation_scope": "following_orthographic_source_block_not_verified_passage_alignment",
            "qualifiers": qualifiers, "qualifier_scope": "immediately_preceding_gramGrp_only",
            "source": record["source"], "source_url": record["source_url"],
            "entry_url": record.get("entry_url"), "raw_path": record["raw_path"],
            "raw_sha256": record["raw_sha256"], "license": record.get("license"),
            "extraction_method": VERSION,
        })
    after = path.stat()
    if (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, stat.st_size):
        raise ValueError("LSJ source changed during extraction")
    return rows


class SubentryIndex:
    """Read-only isolated evidence lookup; no implicit morphology integration."""
    def __init__(self, path):
        self.connection = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
        version = self.connection.execute("SELECT value FROM metadata WHERE key='version'").fetchone()
        if not version or version[0] != VERSION:
            self.connection.close()
            raise ValueError("Subentry index version mismatch")

    def lookup(self, query, limit=8):
        key = lookup_key(query)
        if key is None:
            return []
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT record_json FROM subentries WHERE lookup_key=? ORDER BY id LIMIT ?",
            (key, max(1, min(int(limit), 20))))]

    def close(self):
        self.connection.close()
