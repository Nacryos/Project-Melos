"""Regression checks use accepted local source records, not invented lexica."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.dictionary_crossrefs import lookup_crossreference_meanings, project_crossreference_meanings
from backend.evidence import EvidenceIndex


class DictionaryCrossreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = EvidenceIndex()
        cls.outputs = {word: lookup_crossreference_meanings(word, cls.index)
                       for word in ("δᾶμον", "γᾶς", "πέμπων", "μέσσον", "δ’", "ἔρχεσθ’")}

    def project(self, output, form="δᾶμον"):
        return project_crossreference_meanings(form, output["supporting_claims"], output["supporting_source_records"])

    def test_target_homographs_remain_distinct(self):
        rows = self.outputs["δᾶμον"]["candidates"]
        self.assertEqual(len(rows), 11)
        self.assertEqual({r["target_entry_id"] for r in rows},
                         {"wiktionary:kaikki:line:894", "wiktionary:kaikki:line:895"})
        self.assertEqual({r["target_etymology_number"] for r in rows}, {"1", "2"})
        self.assertTrue(all(r["target_identity_status"] == "ambiguous_page_target" for r in rows))
        self.assertTrue(all(not r["contextually_selected"] for r in rows))

    def test_literal_pos_difference_is_retained_not_silently_joined(self):
        rows = self.outputs["μέσσον"]["candidates"]
        self.assertEqual(len(rows), 6)
        self.assertEqual({r["target_dictionary_pos"] for r in rows}, {"adj", "noun"})
        self.assertTrue(all(r["source_dictionary_pos"] == "adj" for r in rows))
        self.assertEqual(sum(r["literal_pos_agreement"] for r in rows), 3)

    def test_identical_glosses_keep_source_target_pair_provenance(self):
        rows = self.outputs["δ’"]["candidates"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({(r["source_entry_id"], r["target_entry_id"]) for r in rows}), 4)
        self.assertEqual(sum(r["literal_pos_agreement"] for r in rows), 2)
        self.assertEqual(len({r["id"] for r in rows}), 4)

    def test_unique_dictionary_targets_gain_literal_senses(self):
        self.assertEqual(len(self.outputs["γᾶς"]["candidates"]), 3)
        self.assertEqual(len(self.outputs["πέμπων"]["candidates"]), 1)
        self.assertEqual(self.outputs["πέμπων"]["candidates"][0]["sense"]["glosses"], ["five"])

    def test_form_page_target_is_terminal_not_transitively_resolved(self):
        result = self.outputs["ἔρχεσθ’"]
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["relations"][0]["target_results"][0]["status"], "terminal_form_page")
        self.assertNotIn("wiktionary:kaikki:line:19316:lemma:entry", [r["id"] for r in result["candidates"]])
        self.assertEqual(self.project(result, "ἔρχεσθ’")["candidates"], [])

    def test_no_morphology_or_contextual_selection_created(self):
        for result in self.outputs.values():
            for row in result["candidates"]:
                self.assertIsNone(row["analysis"])
                self.assertIsNone(row["features"])
                self.assertNotIn("lemma", row)
                self.assertEqual(row["candidate_kind"], "dictionary_crossreference_meaning")

    def test_complete_proof_replays_without_input_mutation(self):
        result = deepcopy(self.outputs["δᾶμον"])
        before = deepcopy(result)
        replayed = self.project(result)
        self.assertEqual(replayed["candidates"], result["candidates"])
        self.assertEqual(result, before)
        replayed["candidates"][0]["sense"]["glosses"].clear()
        self.assertEqual(result, before)

    def test_missing_source_form_proof_abstains(self):
        result = deepcopy(self.outputs["δᾶμον"])
        result["supporting_claims"] = [c for c in result["supporting_claims"]
                                       if c["id"] != "wiktionary:kaikki:line:9399:morphology:entry"]
        self.assertEqual(self.project(result)["candidates"], [])

    def test_modified_form_array_rejected_by_parent_record(self):
        result = deepcopy(self.outputs["δᾶμον"])
        next(c for c in result["supporting_claims"] if c["id"] ==
             "wiktionary:kaikki:line:9399:morphology:entry")["object"]["forms"][20]["tags"] = []
        self.assertEqual(self.project(result)["candidates"], [])

    def test_modified_source_link_rejected_even_with_unchanged_gloss(self):
        result = deepcopy(self.outputs["δᾶμον"])
        next(c for c in result["supporting_claims"] if c["id"] ==
             "wiktionary:kaikki:line:9399:sense:0")["object"]["source_sense"]["links"] = []
        self.assertEqual(self.project(result)["candidates"], [])

    def test_source_relation_binding_must_match_exact_entry_proof(self):
        result = deepcopy(self.outputs["δᾶμον"])
        next(c for c in result["supporting_claims"] if c["id"] ==
             "wiktionary:kaikki:line:9399:sense:0")["metadata"]["source_raw_line_sha256"] = "0" * 64
        self.assertEqual(self.project(result)["candidates"], [])

    def test_tampered_record_content_fails_bound_hash(self):
        result = deepcopy(self.outputs["δᾶμον"])
        next(r for r in result["supporting_source_records"] if r["id"] ==
             "wiktionary:kaikki:line:9399")["entry"]["forms"][20]["tags"] = []
        self.assertEqual(self.project(result)["candidates"], [])

    def test_wrong_target_headword_proof_rejected(self):
        result = deepcopy(self.outputs["δᾶμον"])
        for claim in result["supporting_claims"]:
            if claim["id"] == "wiktionary:kaikki:line:894:lemma:entry":
                claim["object"]["lemma"] = "δᾶμος"
        self.assertEqual({r["target_entry_id"] for r in self.project(result)["candidates"]},
                         {"wiktionary:kaikki:line:895"})

    def test_no_accent_folding(self):
        self.assertEqual(self.project(self.outputs["δᾶμον"], "δαμον")["candidates"], [])

    def test_duplicate_source_identity_abstains(self):
        result = deepcopy(self.outputs["δᾶμον"])
        result["supporting_claims"].append(next(c for c in result["supporting_claims"] if
                                              c["id"] == "wiktionary:kaikki:line:9399:sense:0"))
        self.assertEqual(self.project(result)["candidates"], [])

    def test_no_network_required(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            self.assertTrue(lookup_crossreference_meanings("δᾶμον", self.index)["candidates"])


if __name__ == "__main__":
    unittest.main()
