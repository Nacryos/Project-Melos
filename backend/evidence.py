"""Read-only access to independently accepted, source-bearing evidence claims.

The SQLite file is a disposable index. JSONL claims and their independent
acceptance manifest are the authority; see ``scripts/build_evidence.py``.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Any

from backend.morphology import normalize, query_variants


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/evidence.sqlite"


class EvidenceIndex:
    """Retrieve claims without converting them into philological certainty.

    Passage scope only comes from an explicit ``subject.passage_id``. A form
    claim without that link is never presented as an attestation in a passage.
    ``strength`` is a categorical source-link description, not a confidence
    score or probability.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Evidence index not built: {self.db_path}")
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _limit(value: int) -> int:
        return max(1, min(int(value), 100))

    @staticmethod
    def _claim(row: sqlite3.Row, *, strength: str, reason: str,
               compact_forms: bool = False) -> dict[str, Any]:
        obj = json.loads(row["object_json"])
        omitted: list[str] = []
        if compact_forms and isinstance(obj, dict) and isinstance(obj.get("forms"), list):
            obj = dict(obj)
            obj["listed_form_count"] = len(obj.pop("forms"))
            omitted.append("forms")
        claim = {
            "id": row["id"],
            "subject": json.loads(row["subject_json"]),
            "predicate": row["predicate"],
            "object": obj,
            "evidence": json.loads(row["evidence_json"]),
            "assertion_type": row["assertion_type"],
            "status": row["status"],
            "method": row["method"],
            "source_family": row["source_family"],
            "metadata": json.loads(row["metadata_json"]),
            "source_file": row["source_file"],
            "strength": strength,
            "match_reason": reason,
        }
        if omitted:
            claim["object_omitted_fields"] = omitted
        return claim

    @staticmethod
    def _order(rows: list[tuple[sqlite3.Row, str, str, int]]) -> list[tuple[sqlite3.Row, str, str, int]]:
        # Inspectable ordinal ordering, deliberately not a probability.
        status_order = {"source_claim": 0, "needs_review": 1, "machine_proposed": 2}
        predicate_order = {"morphology": 0, "lemma": 1, "equivalent_form": 2,
                           "variant_reading": 3, "dialect_label": 4, "sense_gloss": 5}
        return sorted(rows, key=lambda item: (
            item[3], status_order.get(item[0]["status"], 3),
            predicate_order.get(item[0]["predicate"], 6),
            item[0]["source_family"], item[0]["id"],
        ))

    def lookup(self, form: str, passage_id: str | None = None,
               limit: int = 20) -> dict[str, Any]:
        """Find explicitly linked passage claims and source claims on a form.

        Lookup is accent/case folded for recall. Exact original spelling is
        disclosed separately. It does not imply that a general form occurs in
        ``passage_id``. Caller should show candidate parses separately.
        """
        keys = list(dict.fromkeys(query_variants(form)))
        result: dict[str, Any] = {
            "form": form,
            "normalized": keys[0] if keys else "",
            "passage_id": passage_id,
            "claims": [],
            "total": 0,
            "method": "Accepted source claims; exact form key with explicit passage links ranked first",
            "warnings": [],
        }
        if not keys:
            return result
        marks = ",".join("?" for _ in keys)
        with closing(self._connect()) as con:
            if passage_id:
                # A passage claim may omit a form when it concerns the whole
                # locus. Word lookup includes only a matching stated form.
                rows = con.execute(
                    f"SELECT * FROM claims WHERE normalized_form IN ({marks}) "
                    "AND (passage_id=? OR passage_id IS NULL)",
                    [*keys, passage_id],
                ).fetchall()
            else:
                rows = con.execute(
                    f"SELECT * FROM claims WHERE normalized_form IN ({marks}) "
                    "AND passage_id IS NULL", keys,
                ).fetchall()
        original = unicodedata.normalize("NFC", form)
        ranked: list[tuple[sqlite3.Row, str, str, int]] = []
        listed_by_id: dict[str, list[tuple[int, Any]]] = {}
        with closing(self._connect()) as con:
            edges = con.execute(
                f"SELECT e.claim_id, e.ordinal, e.form AS listed_form, e.object_form_json "
                f"FROM form_edges e JOIN claims c ON c.id=e.claim_id "
                f"WHERE e.normalized_form IN ({marks}) AND c.passage_id IS NULL",
                keys,
            ).fetchall()
            for edge in edges:
                listed_by_id.setdefault(edge["claim_id"], []).append((
                    edge["ordinal"], json.loads(edge["object_form_json"]),
                ))
            listed_rows: dict[str, sqlite3.Row] = {}
            ids = list(listed_by_id)
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                holders = ",".join("?" for _ in batch)
                listed_rows.update((row["id"], row) for row in con.execute(
                    f"SELECT * FROM claims WHERE id IN ({holders})", batch,
                ))
        for row in rows:
            exact_spelling = unicodedata.normalize("NFC", row["form"] or "") == original
            if passage_id and row["passage_id"] == passage_id:
                if row["start_offset"] is not None and row["end_offset"] is not None:
                    strength, priority = "explicit_passage_span", 0
                    reason = "Source claim explicitly links this form to the requested passage and offsets."
                else:
                    strength, priority = "explicit_passage_link", 2
                    reason = "Source claim explicitly links this form to the requested passage."
            else:
                strength, priority = "general_form_claim", 4
                reason = "Source claim concerns this form generally; no occurrence in the requested passage is asserted."
            if not exact_spelling:
                reason += " Matched by accent/case-folded spelling."
                priority += 1
            ranked.append((row, strength, reason, priority))
        existing = {row["id"] for row, _, _, _ in ranked}
        for claim_id, row in listed_rows.items():
            if claim_id in existing:
                continue
            exact_spelling = any(
                unicodedata.normalize("NFC", item if isinstance(item, str) else str(item["form"])) == original
                for _, item in listed_by_id[claim_id]
            )
            reason = "Source entry explicitly lists this form; no passage attestation is asserted."
            priority = 4
            if not exact_spelling:
                reason += " Matched by accent/case-folded spelling."
                priority += 1
            ranked.append((row, "listed_entry_form", reason, priority))
        ordered = self._order(ranked)
        result["total"] = len(ordered)
        result["claims"] = []
        for row, strength, reason, _ in ordered[:self._limit(limit)]:
            claim = self._claim(row, strength=strength, reason=reason,
                                compact_forms=row["id"] in listed_by_id)
            if row["id"] in listed_by_id:
                claim["matched_object_forms"] = [item for _, item in listed_by_id[row["id"]]]
                claim["matched_object_form_ordinals"] = [ordinal for ordinal, _ in listed_by_id[row["id"]]]
            result["claims"].append(claim)
        return result

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch the complete, unprojected claim by its stable source ID."""
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None and (match := re.fullmatch(r"(.+)#form:\d+", claim_id)):
                row = con.execute("SELECT * FROM claims WHERE id=?", (match.group(1),)).fetchone()
        if row is None:
            return None
        return self._claim(row, strength="source_record",
                           reason="Complete accepted claim, fetched by stable ID.")

    def candidate_analyses(self, form: str, passage_id: str | None = None,
                           limit: int = 20) -> dict[str, Any]:
        """Project explicit claim fields into candidate rows for word UI.

        This is a convenience view, not a merged parse. A source may supply
        only a lemma, only a grammatical label, or a listed form's tags.
        Missing pieces stay null and contradictory rows stay separate.
        """
        found = self.lookup(form, passage_id=passage_id, limit=limit)
        candidates: list[dict[str, Any]] = []
        for claim in found["claims"]:
            predicate = claim["predicate"]
            if predicate not in {"lemma", "morphology", "equivalent_form"}:
                continue
            obj = claim["object"]
            if not isinstance(obj, dict):
                obj = {}
            matched_forms = claim.get("matched_object_forms") or [None]
            for matched_index, listed in enumerate(matched_forms):
                listed_obj = listed if isinstance(listed, dict) else ({"form": listed} if isinstance(listed, str) else {})
                raw_label = listed_obj.get("raw_label", listed_obj.get("tags")) if listed is not None else obj.get("raw_label")
                if raw_label is None and listed is None:
                    raw_label = obj.get("source_tags")
                features = listed_obj.get("features") if listed is not None else obj.get("features")
                lemma = obj.get("lemma")
                lemma_targets = obj.get("targets") if predicate == "lemma" else None
                if predicate == "lemma":
                    lemma = obj.get("form", lemma)
                    if lemma is None and isinstance(lemma_targets, list) and len(lemma_targets) == 1:
                        target = lemma_targets[0]
                        lemma = target.get("word") if isinstance(target, dict) else None
                # Entry-level listed forms have the headword as their subject.
                if lemma is None and listed is not None:
                    lemma = claim["subject"].get("form")
                ordinal = (claim.get("matched_object_form_ordinals") or [None])[matched_index]
                candidates.append({
                    "id": f"{claim['id']}#form:{ordinal}" if ordinal is not None else claim["id"],
                    "matched_form": listed_obj.get("form") or claim["subject"].get("form"),
                    "lemma": lemma,
                    "lemma_targets": lemma_targets,
                    "analysis": raw_label,
                    "features": features,
                    "equivalent_form": obj.get("form") if predicate == "equivalent_form" else None,
                    "relation_raw": obj.get("relation_raw", obj.get("relation")),
                    "source_tags": obj.get("source_tags"),
                    "source_raw_tags": obj.get("source_raw_tags"),
                    "claim_ids": [claim["id"]],
                    "evidence_refs": [
                        evidence.get("record_id") or f"{claim['id']}#evidence:{i}"
                        for i, evidence in enumerate(claim["evidence"])
                    ],
                    "status": claim["status"],
                    "assertion_type": claim["assertion_type"],
                    "strength": claim["strength"],
                    "source_family": claim["source_family"],
                    "match_reason": claim["match_reason"],
                    "matched_object_form": listed,
                })
                if len(candidates) >= self._limit(limit):
                    break
            if len(candidates) >= self._limit(limit):
                break
        return {
            "form": form, "passage_id": passage_id,
            "candidates": candidates, "total_claims": found["total"],
            "method": "Fields explicitly present in accepted lemma, morphology, and equivalent-form claims",
            "warnings": [],
        }

    def forms_for_lemma(self, headword: str, limit: int = 500) -> list[str]:
        """List only source-entry forms of a headword, for search expansion.

        These are dictionary listed forms, not attested corpus occurrences.
        Querying actual corpus tokens with them is the caller's next step.
        """
        keys = list(dict.fromkeys(query_variants(headword)))
        if not keys:
            return []
        marks = ",".join("?" for _ in keys)
        with closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT DISTINCT e.form FROM claims c JOIN form_edges e ON e.claim_id=c.id "
                f"WHERE c.normalized_form IN ({marks}) AND c.passage_id IS NULL "
                "AND c.predicate='morphology' ORDER BY e.normalized_form,e.form LIMIT ?",
                [*keys, self._limit_form_expansion(limit)],
            ).fetchall()
        return [row["form"] for row in rows]

    @staticmethod
    def _limit_form_expansion(value: int) -> int:
        return max(1, min(int(value), 500))

    def get_passage_claims(self, passage_id: str, limit: int = 50) -> dict[str, Any]:
        """Return only claims explicitly attached to this passage ID."""
        result: dict[str, Any] = {
            "passage_id": passage_id, "claims": [], "total": 0,
            "method": "Exact explicit subject.passage_id link", "warnings": [],
        }
        if not passage_id:
            return result
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM claims WHERE passage_id=?", (passage_id,)).fetchall()
        ranked = [(
            row,
            "explicit_passage_span" if row["start_offset"] is not None and row["end_offset"] is not None else "explicit_passage_link",
            "Source claim explicitly names this passage ID.",
            0 if row["start_offset"] is not None and row["end_offset"] is not None else 1,
        ) for row in rows]
        ordered = self._order(ranked)
        result["total"] = len(ordered)
        result["claims"] = [self._claim(row, strength=strength, reason=reason)
                            for row, strength, reason, _ in ordered[:self._limit(limit)]]
        return result

    def related_claims(self, claim_id: str, limit: int = 20) -> dict[str, Any]:
        """Traverse shared explicit subject, passage, or form graph edges.

        Shared form is a discovery link only; it does not mean two sources
        agree. Distinct readings and contradictory claims remain separate.
        """
        result: dict[str, Any] = {
            "claim_id": claim_id, "claims": [], "total": 0,
            "method": "Shared explicit subject, passage, or form; no agreement inferred",
            "warnings": [],
        }
        with closing(self._connect()) as con:
            target = con.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if target is None and (match := re.fullmatch(r"(.+)#form:\d+", claim_id)):
                target = con.execute("SELECT * FROM claims WHERE id=?", (match.group(1),)).fetchone()
            if target is None:
                return result
            conditions: list[str] = []
            params: list[Any] = []
            if target["subject_id"]:
                conditions.append("(subject_type=? AND subject_id=?)")
                params.extend((target["subject_type"], target["subject_id"]))
            if target["passage_id"]:
                conditions.append("passage_id=?")
                params.append(target["passage_id"])
            if target["normalized_form"]:
                conditions.append("normalized_form=?")
                params.append(target["normalized_form"])
            if not conditions:
                return result
            rows = con.execute(
                "SELECT * FROM claims WHERE id<>? AND (" + " OR ".join(conditions) + ")",
                [target["id"], *params],
            ).fetchall()
        ranked: list[tuple[sqlite3.Row, str, str, int]] = []
        for row in rows:
            if target["subject_id"] and row["subject_type"] == target["subject_type"] and row["subject_id"] == target["subject_id"]:
                strength, reason, priority = "shared_subject", "Both claims name the same source-specific subject.", 0
            elif target["passage_id"] and row["passage_id"] == target["passage_id"]:
                strength, reason, priority = "shared_passage", "Both claims explicitly name the same passage.", 1
            else:
                strength, reason, priority = "shared_form", "Both claims concern the same folded form; agreement is not implied.", 2
            ranked.append((row, strength, reason, priority))
        ordered = self._order(ranked)
        result["total"] = len(ordered)
        result["claims"] = [self._claim(row, strength=strength, reason=reason)
                            for row, strength, reason, _ in ordered[:self._limit(limit)]]
        return result

    def provenance(self) -> dict[str, Any]:
        """Return the accepted files and hashes bound into this index."""
        with closing(self._connect()) as con:
            files = [dict(row) for row in con.execute(
                "SELECT name,sha256,records FROM input_files ORDER BY name"
            )]
            count = con.execute("SELECT count(*) FROM claims").fetchone()[0]
        return {"files": files, "claims": count}
