"""Exact parser-lemma -> explicitly printed LSJ subordinate dictionary evidence.

This isolated helper does not alter morphology, the corpus, or the reader.
Its staged SQLite dependency is an explicitly pinned locator inventory, never
authority for meanings: matching rows are re-extracted from the hash-verified
archive with the current extractor. A trusted cache-only receipt loader binds
each parser hypothesis to the unchanged input form. No spelling/dialect bridge
is inferred, and no source definition becomes contextual adjudication.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from .lexicon_subentries import VERSION as SUBENTRY_VERSION, extract_subentries, lookup_key
from .lexicon_senses import VERSION as SENSE_VERSION

VERSION = "receipt-lemma-explicit-subentry-v1"
MAX_MATCHES = 20
HEX = re.compile(r"[0-9a-f]{64}\Z")
LOCATOR_FIELDS = ("id", "parent_lexicon_entry_id", "parent_entry_id", "parent_headword",
                  "parent_lemma_beta", "orthography", "orthography_raw", "lookup_key",
                  "source_locator", "entry_byte_start", "entry_byte_end", "source",
                  "source_url", "raw_path", "raw_sha256")


def _stamp(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@contextmanager
def _connect(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _artifact(path):
    root = Path(__file__).resolve().parents[1]
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name


def _preview_eligibility(row):
    """Conservative display limits, not claims that spelling is correct.

    Single-letter subordinate orthographies can encode an ending rather than
    a headword despite a source ``extent=full`` tag. Partial extent declarations
    require review unless the printed suffix entry includes its full prefix
    across an internal segmentation hyphen. ``Gloss.``-only equivalences do
    not establish English, even when the older sense projection says ``en``.
    Original definitions and language labels remain untouched in evidence.
    """
    letters = [c for c in row.get("lookup_key", "") if unicodedata.category(c).startswith("L")]
    reasons = []
    if len(letters) < 2:
        reasons.append("subentry_completeness_unverified_single_letter")
    extent = row.get("orth_extent")
    if extent not in {"full", "suff"} or (extent == "suff" and not any(
            h in row.get("orthography", "") for h in ("-", "\u2010"))):
        reasons.append("subentry_completeness_unverified_declared_extent")
    citations = row.get("citations") or []
    if citations and all(c.get("text", "").strip() == "Gloss." for c in citations):
        reasons.append("language_unverified_glossary_equivalence")
    return {"eligible": not reasons, "reasons": reasons,
            "scope": "parser_lemma_matched_literal_subentry_not_independently_validated_lemma"}


class MachineSubentryResolver:
    """Explicitly configured, read-only dictionary dependency.

    Construction validates the pinned index and its exact entries.jsonl input.
    Deployment must supply all three arguments; there is deliberately no
    production fallback to an unapproved staging path or an empty index.
    """

    def __init__(self, index_path, manifest_path, *, expected_index_sha256):
        self.index_path = Path(index_path).resolve(strict=True)
        self.manifest_path = Path(manifest_path).resolve(strict=True)
        if not isinstance(expected_index_sha256, str) or not HEX.fullmatch(expected_index_sha256):
            raise ValueError("An explicit audited subentry-index SHA-256 is required")
        index_stamp = _stamp(self.index_path)
        if _sha(self.index_path) != expected_index_sha256:
            raise ValueError("Subentry-index SHA-256 mismatch")
        with _connect(self.index_path) as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            if metadata.get("version") != SUBENTRY_VERSION:
                raise ValueError("Subentry-index extraction version mismatch")
            staged = [json.loads(row[0]) for row in db.execute("SELECT record_json FROM subentries")]
            if str(len(staged)) != metadata.get("subentries"):
                raise ValueError("Subentry-index count mismatch")
            parent_ids = {row["parent_lexicon_entry_id"] for row in staged}
        before = _stamp(self.manifest_path)
        digest = hashlib.sha256()
        records = {}
        with self.manifest_path.open("rb") as handle:
            for line in handle:
                digest.update(line)
                record = json.loads(line)
                identifier = record.get("id")
                if identifier in parent_ids:
                    if identifier in records:
                        raise ValueError("Ambiguous duplicate dictionary manifest identity")
                    records[identifier] = record
        manifest_sha = digest.hexdigest()
        if not HEX.fullmatch(metadata.get("input_sha256", "")) or manifest_sha != metadata["input_sha256"]:
            raise ValueError("Subentry-index input manifest SHA-256 mismatch")
        if records.keys() != parent_ids:
            raise ValueError("Subentry-index parent missing from dictionary manifest")
        if before != _stamp(self.manifest_path) or index_stamp != _stamp(self.index_path):
            raise ValueError("Subentry dependency changed during verification")
        self.records = records
        self.stamps = (index_stamp, before)
        self.dependencies = {"index_artifact": _artifact(self.index_path), "index_sha256": expected_index_sha256,
                             "index_version": SUBENTRY_VERSION, "manifest_artifact": _artifact(self.manifest_path),
                             "manifest_sha256": manifest_sha, "sense_extractor_version": SENSE_VERSION,
                             "index_rows": len(staged), "use": "locator_only_reextract_current_archived_source"}

    def _check_dependencies(self):
        if self.stamps != (_stamp(self.index_path), _stamp(self.manifest_path)):
            raise ValueError("Subentry dependency changed; explicit revalidation is required")

    def lookup_lemma(self, lemma):
        """Exact NFC/printed-segmentation lookup; all matching identities survive."""
        key = lookup_key(lemma) if isinstance(lemma, str) else None
        if key is None:
            return {"status": "ineligible_lemma", "lookup_key": None, "subentries": []}
        try:
            self._check_dependencies()
            with _connect(self.index_path) as db:
                count = db.execute("SELECT count(*) FROM subentries WHERE lookup_key=?", (key,)).fetchone()[0]
                if count > MAX_MATCHES:
                    return {"status": "candidate_limit", "lookup_key": key, "subentries": [],
                            "matching_count": count, "limit": MAX_MATCHES}
                staged = [json.loads(row[0]) for row in db.execute(
                    "SELECT record_json FROM subentries WHERE lookup_key=? ORDER BY id", (key,))]
            resolved = []
            fresh_by_parent = {}
            for locator in staged:
                parent = locator.get("parent_lexicon_entry_id")
                if parent not in self.records:
                    raise ValueError("Subentry parent is not manifest-bound")
                if parent not in fresh_by_parent:
                    fresh_by_parent[parent] = extract_subentries(self.records[parent])
                exact = [row for row in fresh_by_parent[parent]
                         if row.get("id") == locator.get("id") and row.get("lookup_key") == key
                         and all(row.get(field) == locator.get(field) for field in LOCATOR_FIELDS)]
                if len(exact) != 1:
                    raise ValueError("Staged subentry locator does not reproduce from archived source")
                resolved.append(deepcopy(exact[0]))
            self._check_dependencies()
            return {"status": "available" if resolved else "no_exact_subentry", "lookup_key": key,
                    "subentries": resolved, "matching_count": count,
                    "source_status": "hash_verified_current_extraction"}
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            return {"status": "unavailable", "lookup_key": key, "subentries": [], "warning": str(exc)}

    def resolve(self, token, *, receipt_loader):
        """Return source alternatives under existing, replayed machine hypotheses.

        ``receipt_loader`` must be the application's trusted cache-only
        ``MachineMorphologyService.load_receipt`` or equivalent, NOT request
        data. It is injected so this helper itself never opens a morphology
        database, initiates a download, or writes a cache.
        """
        output = {"version": VERSION, "status": "not_applicable", "form": token.get("form") or token.get("text"),
                  "candidates": [], "issues": [], "dependencies": deepcopy(self.dependencies),
                  "supporting_subentries": [], "supporting_receipts": [],
                  "scope": "dictionary_definitions_for_parser_lemma_not_occurrence_attestation",
                  "contextually_selected": False}
        form = token.get("form") or token.get("text")
        if (token.get("kind") != "word" or token.get("partial_word") or token.get("editorial_fragment")
                or not isinstance(form, str) or not form or len(form) > 200):
            return output
        machine = token.get("machine") or {}
        if machine.get("status") != "ok" or machine.get("form") != form:
            output["status"] = "machine_unavailable"
            return output
        supplied = machine.get("machine_candidates") or []
        if not isinstance(supplied, list) or len(supplied) > 100:
            output["status"] = "invalid_machine_inventory"
            return output
        receipts, looked_up, seen = {}, {}, set()
        source_evidence, receipt_evidence = {}, {}
        for candidate in supplied:
            if not isinstance(candidate, dict):
                output["issues"].append({"status": "invalid_candidate"})
                continue
            candidate_id, receipt_id = candidate.get("id"), candidate.get("receipt_id")
            if not isinstance(receipt_id, str) or not HEX.fullmatch(receipt_id):
                output["issues"].append({"candidate_id": candidate_id, "status": "missing_receipt"})
                continue
            if receipt_id not in receipts:
                try:
                    receipts[receipt_id] = receipt_loader(receipt_id, form=form)
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    receipts[receipt_id] = None
            replay = receipts[receipt_id]
            replayed = [row for row in (replay or {}).get("machine_candidates", [])
                        if row.get("id") == candidate_id]
            if (not replay or replay.get("status") != "ok" or replay.get("form") != form
                    or (replay.get("receipt") or {}).get("id") != receipt_id or len(replayed) != 1
                    or any(candidate.get(k) != v for k, v in replayed[0].items())):
                output["issues"].append({"candidate_id": candidate_id, "status": "invalid_machine_evidence"})
                continue
            source_candidate = replayed[0]
            lemma = source_candidate.get("lemma")
            if (source_candidate.get("basis") != "machine_analysis"
                    or source_candidate.get("candidate_kind") != "machine_analysis"
                    or any(candidate.get(k) for k in ("homograph_id", "lemma_identity"))
                    or any(re.search(r"\d", str(candidate.get(k) or "")) for k in ("lemma", "lemma_raw", "lemma_beta"))):
                output["issues"].append({"candidate_id": candidate_id, "status": "ineligible_candidate_identity"})
                continue
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            key = lookup_key(lemma) if isinstance(lemma, str) else None
            if key not in looked_up:
                looked_up[key] = self.lookup_lemma(lemma)
            found = looked_up[key]
            if found["status"] not in {"available", "no_exact_subentry"}:
                output["issues"].append({"candidate_id": candidate_id, **deepcopy(found)})
                continue
            if not found["subentries"]:
                continue
            for row in found["subentries"]:
                source_evidence[row["id"]] = {"id": row["id"], "source_subentry": deepcopy(row),
                                               "english_preview": _preview_eligibility(row)}
            receipt_evidence[receipt_id] = {key: deepcopy(replay["receipt"].get(key)) for key in
                ("id", "raw_sha256", "url", "parser_version", "source_form", "request_form", "http_status")}
            evidence = {"candidate_id": candidate_id, "form": form, "lemma": lemma,
                        "receipt_id": receipt_id, "machine_candidate_sha256": _digest(source_candidate),
                        "match_method": "exact_parser_lemma_to_explicit_subentry_orthography",
                        "lookup_key": key, "subentry_ids": [row["id"] for row in found["subentries"]],
                        "english_preview_subentry_ids": [row["id"] for row in found["subentries"]
                                                          if source_evidence[row["id"]]["english_preview"]["eligible"]],
                        "occurrence_attested": False, "contextually_selected": False,
                        "surface_equivalence_inferred": False}
            evidence["id"] = "machine-subentry:" + _digest(evidence)
            output["candidates"].append(evidence)
        output["supporting_subentries"] = list(source_evidence.values())
        output["supporting_receipts"] = list(receipt_evidence.values())
        output["status"] = ("partial" if output["candidates"] else "unavailable") if output["issues"] else (
            "available" if output["candidates"] else "no_exact_subentry")
        if output["status"] == "available" and not any(c["english_preview_subentry_ids"] for c in output["candidates"]):
            output["status"] = "source_evidence_only"
        output["inventory_sha256"] = _digest(output)
        return output


__all__ = ["MachineSubentryResolver", "VERSION"]
