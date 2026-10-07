"""Same-entry source gender tests; no generated grammatical source records."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from backend.evidence import EvidenceIndex
from backend.noun_entry_features import lookup_noun_inherent_features, project_noun_inherent_features


class NounEntryFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = EvidenceIndex()
        cls.results = {i: lookup_noun_inherent_features(f"wiktionary:kaikki:line:{i}", cls.index)
                       for i in (11786, 9399, 6188, 3880, 87, 4036, 4037, 59058)}

    def project(self, result):
        return project_noun_inherent_features(result["entry_id"], result["supporting_claims"],
                                             result["supporting_source_records"])

    def test_pachus_gender_from_own_canonical_row_not_crossref_target(self):
        result = self.results[11786]
        self.assertEqual(result["unambiguous_entry_gender"], "masculine")
        self.assertEqual(result["evidence_groups"][0]["source_locator"], "/entry/forms/0/tags")
        self.assertEqual(result["evidence_groups"][0]["literal_source_tags"], ["canonical", "masculine"])
        self.assertEqual({r["id"] for r in result["supporting_source_records"]}, {result["entry_id"]})
        self.assertNotIn("wiktionary:kaikki:line:7510", str(result))

    def test_damos_gender_from_own_sense_tags(self):
        result = self.results[9399]
        self.assertEqual(result["unambiguous_entry_gender"], "masculine")
        self.assertEqual(result["canonical_gender_group_count"], 0)
        self.assertEqual(result["evidence_groups"][0]["source_locator"], "/entry/senses/0/tags")
        self.assertEqual(result["gender_covered_sense_indices"], [0])
        self.assertNotIn("wiktionary:kaikki:line:894", str(result))

    def test_other_noun_identity_preserves_neuter(self):
        self.assertEqual(self.results[6188]["unambiguous_entry_gender"], "neuter")

    def test_adjective_canonical_masculine_not_inherited(self):
        result = self.results[3880]
        self.assertEqual(result["gender_status"], "not_a_noun_entry")
        self.assertEqual(result["dictionary_gender_options"], [])
        self.assertIsNone(result["unambiguous_entry_gender"])

    def test_multiple_noun_genders_remain_alternatives(self):
        result = self.results[87]
        self.assertEqual(result["gender_status"], "multiple_source_genders")
        self.assertEqual(result["dictionary_gender_options"], ["feminine", "masculine"])
        self.assertIsNone(result["unambiguous_entry_gender"])

    def test_same_spelling_homographs_not_merged(self):
        masculine, feminine = self.results[4036], self.results[4037]
        self.assertEqual(masculine["entry_headword"], feminine["entry_headword"])
        self.assertNotEqual(masculine["entry_id"], feminine["entry_id"])
        self.assertEqual(masculine["unambiguous_entry_gender"], "masculine")
        self.assertEqual(feminine["unambiguous_entry_gender"], "feminine")

    def test_proof_replay_and_no_mutation(self):
        original = deepcopy(self.results[9399])
        self.assertEqual(self.project(original), original)
        self.assertEqual(original, self.results[9399])
        self.assertIsNone(original["features"])

    def test_missing_sense_proof_does_not_supply_gender(self):
        result = deepcopy(self.results[9399])
        result["supporting_claims"] = [c for c in result["supporting_claims"] if c["predicate"] != "sense_gloss"]
        projected = self.project(result)
        self.assertEqual(projected["gender_status"], "missing_sense_proof")
        self.assertIsNone(projected["unambiguous_entry_gender"])

    def test_modified_canonical_tags_rejected(self):
        result = deepcopy(self.results[11786])
        next(c for c in result["supporting_claims"] if c["predicate"] == "morphology")["object"]["forms"][0]["tags"] = []
        self.assertIsNone(self.project(result)["unambiguous_entry_gender"])

    def test_modified_sense_tags_rejected(self):
        result = deepcopy(self.results[9399])
        next(c for c in result["supporting_claims"] if c["predicate"] == "sense_gloss")["object"]["source_sense"]["tags"] = []
        self.assertIsNone(self.project(result)["unambiguous_entry_gender"])

    def test_modified_source_parent_rejected(self):
        result = deepcopy(self.results[11786])
        result["supporting_source_records"][0]["entry"]["forms"][0]["tags"] = []
        self.assertIsNone(self.project(result)["unambiguous_entry_gender"])

    def test_duplicate_head_identity_abstains(self):
        result = deepcopy(self.results[9399])
        result["supporting_claims"].append(next(c for c in result["supporting_claims"] if c["id"].endswith(":lemma:entry")))
        self.assertIsNone(self.project(result)["unambiguous_entry_gender"])

    def test_no_spelling_or_target_join(self):
        self.assertEqual(lookup_noun_inherent_features("δᾶμος", self.index)["gender_status"], "unavailable")

    def test_raw_form_page_marker_survives_omitted_sense_claims(self):
        database = Path(__file__).resolve().parents[1] / "data/wiktionary.sqlite"
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            for number in (899, 1398):
                entry_id = f"wiktionary:kaikki:line:{number}"
                record = json.loads(connection.execute("SELECT record_json FROM entries WHERE id=?", (entry_id,)).fetchone()[0])
                claims = [self.index.get_claim(entry_id + suffix) for suffix in (":lemma:entry", ":morphology:entry")]
                result = project_noun_inherent_features(entry_id, claims, [record])
                self.assertEqual(result["gender_status"], "form_page_not_lexical_noun")
                self.assertIsNone(result["unambiguous_entry_gender"])

    def test_no_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            self.assertEqual(lookup_noun_inherent_features("wiktionary:kaikki:line:9399", self.index)["unambiguous_entry_gender"], "masculine")

    def test_actual_differently_gendered_paradigm_blocks_entry_default(self):
        for number in (4052, 33016, 43646):
            result = lookup_noun_inherent_features(f"wiktionary:kaikki:line:{number}", self.index)
            self.assertEqual(result["gender_status"], "explicit_paradigm_gender_conflict")
            self.assertIsNone(result["unambiguous_entry_gender"])
            self.assertTrue(result["paradigm_gender_conflicts"])
            self.assertEqual(result["dictionary_gender_options"], ["masculine"])
            self.assertTrue(all(c["source_locator"].startswith("/entry/forms/")
                                for c in result["paradigm_gender_conflicts"]))


if __name__ == "__main__":
    unittest.main()
