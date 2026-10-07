"""Read-only source replay; negative fixtures mutate temporary copies only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.machine_morphology import project
from backend.machine_subentries import MachineSubentryResolver, _connect, _preview_eligibility
from backend.lexicon_senses import VERSION as SENSE_VERSION

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/staging/lyric-subentries-20261006-v2/subentries.sqlite"
MANIFEST = ROOT / "data/lexica/entries.jsonl"
INDEX_SHA = "33f9a798232948baa3efa13f402ffd8e278414b987a2230f63b5fff89fafcb81"
RESULTS = ROOT / "runtime/alcaeus-morpheus-maintenance/intact-results.json"
FORM = "\u1f00\u03c3\u03c5\u03bd\u03bd\u03ad\u03c4\u03b7\u03bc\u03bc\u03b9"
LEMMA = "\u1f00\u03c3\u03c5\u03bd\u03b5\u03c4\u03ad\u03c9"


class MachineSubentriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(p.is_file() for p in (INDEX, MANIFEST, RESULTS)):
            raise unittest.SkipTest("Archived subentry and machine-receipt fixtures unavailable")
        cls.resolver = MachineSubentryResolver(INDEX, MANIFEST, expected_index_sha256=INDEX_SHA)
        cls.case = next(row for row in json.loads(RESULTS.read_text(encoding="utf8"))["results"] if row["form"] == FORM)
        cls.raw = Path(cls.case["raw_path"]).read_bytes()
        cls.token = {"kind": "word", "text": FORM, "machine": deepcopy(cls.case["result"])}

    def loader(self, receipt_id, *, form):
        receipt = self.case["result"]["receipt"]
        metadata = {k: v for k, v in receipt.items() if k != "id"}
        digest = hashlib.sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        if receipt_id != receipt["id"] or digest != receipt_id or form != receipt["request_form"]:
            return {"status": "invalid_receipt"}
        return project(self.raw, form, receipt)

    def resolve(self, token=None, resolver=None):
        return (resolver or self.resolver).resolve(deepcopy(token or self.token), receipt_loader=self.loader)

    def test_actual_parser_lemma_finds_own_subentry_without_surface_bridge(self):
        result = self.resolve()
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["candidates"]), 1)
        path = result["candidates"][0]
        self.assertEqual(path["lemma"], LEMMA)
        self.assertFalse(path["surface_equivalence_inferred"])
        self.assertFalse(path["occurrence_attested"])
        self.assertFalse(path["contextually_selected"])
        evidence = result["supporting_subentries"]
        self.assertEqual(len(evidence), 1)
        row = evidence[0]["source_subentry"]
        self.assertEqual(row["parent_lexicon_entry_id"], "lsj:1:n16814")
        self.assertEqual(row["qualifiers"], [])
        self.assertEqual([s["text"] for s in row["dictionary_senses"]], ["to be without understanding"])
        self.assertTrue(evidence[0]["english_preview"]["eligible"])
        self.assertEqual(row["dictionary_senses"][0]["form_scope"]["relation"], "variant")
        self.assertEqual(self.resolver.lookup_lemma(FORM)["status"], "no_exact_subentry")

    def test_neighbor_aeolic_subentry_is_separate(self):
        other = self.resolver.lookup_lemma("\u1f00\u03c3\u03c5\u03bd\u03ad\u03c4\u03b7\u03bc\u03b9")
        self.assertEqual(other["status"], "available")
        self.assertEqual(other["subentries"][0]["dictionary_senses"][0]["text"], "fail to understand")
        self.assertNotIn(other["subentries"][0]["id"], self.resolve()["candidates"][0]["subentry_ids"])

    def test_source_currently_reextracted_not_stale_index_senses(self):
        row = self.resolver.lookup_lemma(LEMMA)["subentries"][0]
        self.assertTrue(all(s["extraction_method"] == SENSE_VERSION for s in row["dictionary_senses"]))
        with _connect(INDEX) as db:
            staged = json.loads(db.execute("SELECT record_json FROM subentries WHERE id=?", (row["id"],)).fetchone()[0])
        self.assertNotEqual(staged["dictionary_senses"][0]["id"], row["dictionary_senses"][0]["id"])
        self.assertEqual(staged["source_locator"], row["source_locator"])

    def test_all_matching_source_identities_retained(self):
        result = self.resolver.lookup_lemma("\u03c0\u03b5\u03c1\u03af\u03c4\u03c4\u03c9")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["matching_count"], 6)
        self.assertEqual(len({r["id"] for r in result["subentries"]}), 6)

    def test_accent_case_and_editorial_text_are_not_folded_into_match(self):
        for lemma in (LEMMA.upper(), LEMMA.replace("\u03ad", "\u03b5"), LEMMA + "1", "[" + LEMMA + "]"):
            with self.subTest(lemma=lemma):
                self.assertEqual(self.resolver.lookup_lemma(lemma)["subentries"], [])

    def test_compact_bindings_and_no_private_paths(self):
        result = self.resolve()
        self.assertNotIn(str(ROOT), json.dumps(result["dependencies"]))
        self.assertEqual(len(result["supporting_receipts"]), 1)
        self.assertNotIn("machine_candidate", result["candidates"][0])
        self.assertNotIn("subentries", result["candidates"][0])
        self.assertEqual(result["candidates"][0]["subentry_ids"], [r["id"] for r in result["supporting_subentries"]])

    def test_tampered_machine_analysis_is_not_a_valid_lemma_bridge(self):
        for field, value in (("lemma", "\u1f00\u03c3\u03c5\u03bd\u03ad\u03c4\u03b7\u03bc\u03b9"),
                             ("id", "machine:forged"), ("features", {}), ("receipt_id", "0" * 64)):
            token = deepcopy(self.token)
            token["machine"]["machine_candidates"][0][field] = value
            result = self.resolve(token)
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["status"], "unavailable")

    def test_editorial_partial_unknown_and_mismatched_form_do_not_join(self):
        for field in ("partial_word", "editorial_fragment"):
            token = {**deepcopy(self.token), field: True}
            self.assertEqual(self.resolve(token)["status"], "not_applicable")
        token = deepcopy(self.token)
        token["text"] = LEMMA
        self.assertEqual(self.resolve(token)["status"], "machine_unavailable")
        token["machine"]["form"] = LEMMA
        self.assertEqual(self.resolve(token)["status"], "unavailable")

    def test_homograph_marker_refused_and_display_enrichment_not_semantic_mutation(self):
        token = deepcopy(self.token)
        candidate = token["machine"]["machine_candidates"][0]
        candidate["homograph_id"] = "1"
        self.assertEqual(self.resolve(token)["status"], "unavailable")
        candidate.pop("homograph_id")
        candidate["dictionary_join"] = {"status": "no_exact_headword"}
        candidate["lexicon_entry_ids"] = []
        self.assertEqual(self.resolve(token)["status"], "available")

    def test_dependency_absence_or_hash_mismatch_not_empty_success(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            MachineSubentryResolver(INDEX, MANIFEST, expected_index_sha256="0" * 64)
        with self.assertRaises(FileNotFoundError):
            MachineSubentryResolver(INDEX.parent / "missing.sqlite", MANIFEST, expected_index_sha256=INDEX_SHA)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "wrong-manifest.jsonl"
            manifest.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "manifest SHA-256 mismatch"):
                MachineSubentryResolver(INDEX, manifest, expected_index_sha256=INDEX_SHA)

    def test_sqlite_connection_is_really_readonly(self):
        with _connect(INDEX) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM metadata")

    def test_reextraction_failure_is_unavailable_not_absence(self):
        with patch("backend.machine_subentries.extract_subentries", side_effect=ValueError("source mismatch")):
            found = self.resolver.lookup_lemma(LEMMA)
        self.assertEqual(found["status"], "unavailable")
        self.assertIn("source mismatch", found["warning"])

    def test_staged_locator_tampering_fails_even_with_new_index_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "subentries.sqlite"
            shutil.copyfile(INDEX, index)
            with sqlite3.connect(index) as db:
                identifier, raw = db.execute("SELECT id,record_json FROM subentries WHERE lookup_key=?", (LEMMA,)).fetchone()
                row = json.loads(raw)
                row["source_locator"]["rendered_start"] += 1
                db.execute("UPDATE subentries SET record_json=? WHERE id=?", (json.dumps(row), identifier))
            db.close()
            pinned = hashlib.sha256(index.read_bytes()).hexdigest()
            resolver = MachineSubentryResolver(index, MANIFEST, expected_index_sha256=pinned)
            self.assertEqual(resolver.lookup_lemma(LEMMA)["status"], "unavailable")

    def test_changed_dependency_requires_revalidation(self):
        with patch("backend.machine_subentries._stamp", return_value=(0, 0)):
            result = self.resolver.lookup_lemma(LEMMA)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("revalidation", result["warning"])

    def test_single_letter_and_glossary_language_are_not_automatic_english(self):
        for row in self.resolver.lookup_lemma("\u03b9")["subentries"]:
            eligibility = _preview_eligibility(row)
            self.assertFalse(eligibility["eligible"])
            self.assertIn("subentry_completeness_unverified_single_letter", eligibility["reasons"])
        rows = self.resolver.lookup_lemma("\u03ba\u03b1\u03c0\u03cd\u03c1\u03b9\u03bf\u03bd")["subentries"]
        self.assertEqual(rows[0]["dictionary_senses"][0]["text"], "crustulum")
        self.assertEqual(_preview_eligibility(rows[0])["reasons"], ["language_unverified_glossary_equivalence"])


if __name__ == "__main__":
    unittest.main()
