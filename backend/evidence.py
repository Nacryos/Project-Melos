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
from backend.publication import publication_restricted, EVIDENCE_HOLD
from backend.normalization_contract import NORMALIZATION_VERSION
from backend.source_grammar import projection_qualification


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/evidence.sqlite"

# Kaikki/Wiktionary form arrays mix grammatical labels with entry metadata.
# These are projection rules only: the accepted source tags remain intact in
# lookup(), get_claim(), source_tags, and matched_object_form.
_ENTRY_METADATA_TAGS = frozenset({
    "canonical", "alternative", "romanization", "transliteration",
    "form-of", "alt-of",
})
_WIKTIONARY_GRAMMAR_TAGS = frozenset({
    "nominative", "genitive", "dative", "accusative", "vocative", "locative",
    "instrumental", "singular", "dual", "plural", "masculine", "feminine",
    "neuter", "first-person", "second-person", "third-person",
    "present", "imperfect", "future", "aorist", "perfect", "pluperfect",
    "future-perfect", "active", "middle", "passive", "mediopassive",
    "indicative", "subjunctive", "optative", "imperative", "infinitive",
    "participle", "positive", "comparative", "superlative",
})


def _grammatical_label(value: Any, *, wiktionary: bool) -> Any:
    """Keep source-stated grammar, not entry-navigation or relation tags."""
    if isinstance(value, list):
        labels = [tag for tag in value if isinstance(tag, str) and tag.strip()]
        labels = [tag for tag in labels if tag.casefold() not in _ENTRY_METADATA_TAGS]
        if wiktionary:
            labels = [tag for tag in labels if tag.casefold() in _WIKTIONARY_GRAMMAR_TAGS]
        return labels or None
    if isinstance(value, str):
        label = value.strip()
        if not label or label.casefold() in _ENTRY_METADATA_TAGS:
            return None
        return label if not wiktionary or label.casefold() in _WIKTIONARY_GRAMMAR_TAGS else None
    return value if value else None


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
        if publication_restricted():
            raise RuntimeError(EVIDENCE_HOLD)
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Evidence index not built: {self.db_path}")
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            version = con.execute("SELECT value FROM lookup_metadata WHERE key='normalization_version'").fetchone()
        except sqlite3.Error as exc:
            con.close()
            raise RuntimeError('Evidence lookup keys require coordinated normalization migration/rebuild.') from exc
        if version is None or version[0] != NORMALIZATION_VERSION:
            con.close()
            raise RuntimeError('Evidence lookup normalization version differs from runtime; migration/rebuild required.')
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
               limit: int | None = 20) -> dict[str, Any]:
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
        selected = ordered if limit is None else ordered[:self._limit(limit)]
        for row, strength, reason, _ in selected:
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

    def _wiktionary_entry_context(self, claims: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Resolve page-headword versus form-of target from accepted sibling claims.

        The extractor stores ``entry.word`` in an object field named ``lemma``
        even for an inflected-form page. Only a source-stated form-of target may
        replace that page title in a parse projection; no spelling equivalence
        or inferred lemma is introduced here.
        """
        record_ids = {
            (claim.get("metadata") or {}).get("source_record_id")
            for claim in claims
            if str(claim.get("source_family", "")).startswith("enwiktionary-kaikki-")
        }
        record_ids = {record_id for record_id in record_ids
                      if isinstance(record_id, str) and
                      re.fullmatch(r"wiktionary:kaikki:line:\d+", record_id)}
        if not record_ids:
            return {}
        context: dict[str, dict[str, Any]] = {}
        with closing(self._connect()) as con:
            for record_id in record_ids:
                entry = {"inflected_entry": False, "targets": [], "target_claim_ids": [],
                         "target_evidence_refs": [], "headword_claim_seen": False}
                for row in con.execute(
                    "SELECT id,predicate,object_json,evidence_json,status,assertion_type "
                    "FROM claims WHERE id GLOB ? ORDER BY id",
                    (record_id + ":*",),
                ):
                    if (not row["id"].startswith(record_id + ":") or
                            row["status"] != "source_claim" or
                            row["assertion_type"] == "model_inference"):
                        continue
                    obj = json.loads(row["object_json"])
                    if not isinstance(obj, dict):
                        continue
                    if row["id"] == record_id + ":lemma:entry":
                        entry["headword_claim_seen"] = True
                        entry["inflected_entry"] |= any(
                            isinstance(template, dict) and
                            str(template.get("name", "")).casefold().endswith(" form")
                            for template in obj.get("head_templates") or []
                        )
                    if row["predicate"] == "lemma" and obj.get("relation") == "form_of":
                        entry["inflected_entry"] = True
                        entry["target_claim_ids"].append(row["id"])
                        for evidence in json.loads(row["evidence_json"]):
                            if isinstance(evidence, dict):
                                entry["target_evidence_refs"].append(
                                    evidence.get("record_id") or f"{row['id']}#evidence")
                        for target in obj.get("targets") or []:
                            if isinstance(target, dict) and isinstance(target.get("word"), str) and target["word"]:
                                if target not in entry["targets"]:
                                    entry["targets"].append(target)
                context[record_id] = entry
        return context

    def candidate_analyses(self, form: str, passage_id: str | None = None,
                           limit: int = 20) -> dict[str, Any]:
        """Project source-stated grammar and form-of links, never page metadata.

        Raw claims remain available through lookup(). Candidates are separate
        source alternatives, not merged parses or passage attestations.
        """
        limit = self._limit(limit)
        # lookup() still caps public previews. Internally traverse the full
        # source-claim set so metadata never consumes the candidate budget.
        found = self.lookup(form, passage_id=passage_id, limit=None)
        wiktionary_entries = self._wiktionary_entry_context(found["claims"])
        candidates: list[dict[str, Any]] = []
        excluded = 0
        projection_warnings = []
        for claim in found["claims"]:
            predicate = claim["predicate"]
            if predicate not in {"lemma", "morphology"}:
                continue
            obj = claim["object"]
            if not isinstance(obj, dict):
                excluded += 1
                continue
            wiktionary = str(claim.get("source_family", "")).startswith("enwiktionary-kaikki-")
            if predicate == "lemma" and obj.get("relation") != "form_of" and wiktionary:
                # /entry/word is a dictionary page headword, including on
                # inflected-form pages; it is not a parse of the queried form.
                excluded += 1
                continue
            record_id = (claim.get("metadata") or {}).get("source_record_id")
            entry = wiktionary_entries.get(record_id) if wiktionary else None
            matched_forms = claim.get("matched_object_forms") or [None]
            for matched_index, listed in enumerate(matched_forms):
                listed_obj = listed if isinstance(listed, dict) else ({"form": listed} if isinstance(listed, str) else {})
                raw_label = listed_obj.get("raw_label", listed_obj.get("tags")) if listed is not None else obj.get("raw_label")
                if raw_label is None and listed is None:
                    raw_label = obj.get("source_tags")
                analysis = _grammatical_label(raw_label, wiktionary=wiktionary)
                features = listed_obj.get("features") if listed is not None else obj.get("features")
                if predicate == "lemma":
                    lemma_targets = obj.get("targets")
                    words = {target.get("word") for target in lemma_targets or []
                             if isinstance(target, dict) and isinstance(target.get("word"), str)
                             and target["word"]}
                    if obj.get("relation") == "form_of":
                        lemma = next(iter(words)) if len(words) == 1 else None
                        candidate_kind = "explicit_form_of"
                    else:
                        # Older non-Kaikki lemma claims are retained as
                        # untyped source alternatives for API compatibility.
                        lemma = obj.get("form", obj.get("lemma"))
                        if lemma is None and len(words) == 1:
                            lemma = next(iter(words))
                        candidate_kind = None
                    claim_ids = [claim["id"]]
                else:
                    if not analysis and not features:
                        excluded += 1
                        continue
                    lemma_targets = None
                    lemma = obj.get("lemma")
                    claim_ids = [claim["id"]]
                    candidate_kind = "grammatical_analysis"
                    if wiktionary:
                        # An inflected-entry page has its surface spelling in
                        # object.lemma. Only an explicit sibling form-of claim
                        # may provide a lemma for its listed grammatical form.
                        if entry is None or entry["inflected_entry"] or not entry["headword_claim_seen"]:
                            targets = entry["targets"] if entry else []
                            words = {target["word"] for target in targets}
                            lemma = next(iter(words)) if len(words) == 1 else None
                            lemma_targets = targets or None
                            claim_ids.extend(entry["target_claim_ids"] if entry else [])
                ordinal = (claim.get("matched_object_form_ordinals") or [None])[matched_index]
                evidence_refs = [
                    evidence.get("record_id") or f"{claim['id']}#evidence:{i}"
                    for i, evidence in enumerate(claim["evidence"])
                ]
                if predicate == "morphology" and entry and lemma_targets:
                    evidence_refs.extend(entry["target_evidence_refs"])
                candidates.append({
                    "id": f"{claim['id']}#form:{ordinal}" if ordinal is not None else claim["id"],
                    "matched_form": listed_obj.get("form") or claim["subject"].get("form"),
                    "lemma": lemma,
                    "lemma_targets": lemma_targets,
                    "entry_headword": obj.get("lemma") if wiktionary else None,
                    "candidate_kind": candidate_kind,
                    "analysis": analysis,
                    "features": features,
                    "relation_raw": obj.get("relation_raw", obj.get("relation")),
                    "source_tags": listed_obj.get("tags") if listed is not None else obj.get("source_tags"),
                    "source_raw_tags": listed_obj.get("raw_tags") if listed is not None else obj.get("source_raw_tags"),
                    "claim_ids": list(dict.fromkeys(claim_ids)),
                    "evidence_refs": list(dict.fromkeys(evidence_refs)),
                    "status": claim["status"],
                    "assertion_type": claim["assertion_type"],
                    "strength": claim["strength"],
                    "source_family": claim["source_family"],
                    "match_reason": claim["match_reason"],
                    "matched_object_form": listed,
                })
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        # "Represented" means present in this returned candidate inventory,
        # not merely somewhere in the unlimited source lookup. A pagination
        # budget must not hide a necessary alternative while lifting the guard.
        projected_ids = {claim_id for candidate in candidates for claim_id in candidate['claim_ids']}
        visible_claims = [claim for claim in found['claims'] if claim['id'] in projected_ids]
        by_claim_id = {claim['id']: claim for claim in visible_claims}
        for candidate in candidates:
            for claim_id in candidate['claim_ids']:
                claim = by_claim_id.get(claim_id)
                qualification = projection_qualification(claim, visible_claims) if claim else {}
                if qualification:
                    candidate.update(qualification)
                    projection_warnings.append(f"{claim_id}: {qualification['source_projection_note']}")
        # A listed spelling can differ from its entry headword, so its
        # source-stated form-of target may not be among lookup(form)'s raw
        # claims. Supply only accepted sibling proof used by these bounded
        # candidates; never rewrite the queried form's raw lookup results.
        fetched_ids = {claim["id"] for claim in found["claims"]}
        required_ids = list(dict.fromkeys(
            claim_id for candidate in candidates for claim_id in candidate["claim_ids"]
            if claim_id not in fetched_ids
        ))
        supporting_claims = []
        for claim_id in required_ids:
            sibling = self.get_claim(claim_id)
            if (not sibling or sibling["status"] != "source_claim" or
                    sibling["assertion_type"] == "model_inference"):
                continue
            subject = sibling.get("subject") or {}
            obj = sibling.get("object") or {}
            if (sibling["predicate"] != "lemma" or not isinstance(subject, dict) or
                    subject.get("passage_id") or not isinstance(obj, dict) or
                    obj.get("relation") != "form_of"):
                continue
            sibling["strength"] = "general_entry_relation"
            sibling["match_reason"] = (
                "Accepted sibling entry form-of relation supports a listed-form lemma; "
                "it is not a claim about the requested passage."
            )
            supporting_claims.append(sibling)
        return {
            "form": form, "passage_id": passage_id,
            "candidates": candidates, "total_claims": found["total"],
            "supporting_claims": supporting_claims,
            "method": "Source-stated grammatical labels and explicit form-of links; lexical entry metadata remains in raw claims",
            "warnings": ([f"{excluded} lexical metadata or non-grammatical claim projection(s) excluded."]
                         if excluded else []) + list(dict.fromkeys(projection_warnings)),
        }

    def equivalent_forms_for_form(self, form: str, limit: int = 500) -> list[str]:
        """Source-stated lexical alternatives for retrieval, never parse choices.

        Only general accepted source claims are used. Multiple source targets
        remain alternatives; this does not decide equivalence in a passage.
        """
        found = self.lookup(form, limit=None)
        alternatives: list[str] = []
        seen: set[str] = set()
        for claim in found["claims"]:
            if (claim["predicate"] != "equivalent_form" or
                    claim["status"] != "source_claim" or
                    claim["assertion_type"] == "model_inference"):
                continue
            obj = claim["object"]
            if not isinstance(obj, dict):
                continue
            values = [obj.get("form")]
            values.extend(target.get("word") for target in obj.get("targets", [])
                          if isinstance(target, dict))
            for value in values:
                if isinstance(value, str) and value.strip() and value not in seen:
                    alternatives.append(value)
                    seen.add(value)
                    if len(alternatives) >= self._limit_form_expansion(limit):
                        return alternatives
        return alternatives

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
