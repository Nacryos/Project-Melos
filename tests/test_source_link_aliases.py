"""Actual accepted-source regressions for quantity-marked link spellings."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.evidence import EvidenceIndex
from backend.source_link_aliases import lookup_form_link_aliases, project_form_link_aliases


class SourceLinkAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = EvidenceIndex()
        cls.result = lookup_form_link_aliases("παχέων", cls.index)

    def project(self, result, form="παχέων"):
        return project_form_link_aliases(form, result["supporting_claims"], result["supporting_source_records"])

    def test_source_link_recovers_cubit_candidate_with_literal_genitive_plural(self):
        aliases = [a for a in self.result["aliases"] if a["entry_headword"] == "πᾶχυς"]
        self.assertEqual(len(aliases), 1)
        alias = aliases[0]
        self.assertEqual(alias["printed_form"], "πᾱχέων")
        self.assertEqual(alias["matched_link_target"], "παχέων")
        self.assertEqual(alias["source_grammatical_tags"], ["genitive", "plural"])
        self.assertEqual(alias["source_locator"], "/entry/forms/11/links/0")
        self.assertIsNone(alias["features"])

    def test_explicit_structured_alternative_links_to_cubit_sense(self):
        relation = next(r for r in self.result["relations"] if r["source_entry_id"] == "wiktionary:kaikki:line:11786")
        self.assertEqual(relation["source_display"], "πῆχῠς")
        self.assertEqual(relation["target_headword"], "πῆχυς")
        cubit = next(m for m in self.result["meaning_candidates"] if
                     m["sense"]["claim_id"] == "wiktionary:kaikki:line:7510:sense:4")
        self.assertEqual(cubit["source_entry_id"], "wiktionary:kaikki:line:11786")
        self.assertEqual(cubit["relation_id"], relation["id"])
        self.assertTrue(cubit["sense"]["glosses"][0].startswith("cubit ("))
        self.assertFalse(cubit["contextually_selected"])

    def test_adjective_and_thickness_noun_remain_available(self):
        self.assertEqual({a["entry_headword"] for a in self.result["aliases"]}, {"πᾶχυς", "παχύς", "πάχος"})
        self.assertIn("παχύς", {m["target_headword"] for m in self.result["meaning_candidates"]})
        self.assertIn("πάχος", {m["target_headword"] for m in self.result["meaning_candidates"]})
        self.assertTrue(all(not a["contextually_selected"] for a in self.result["aliases"]))

    def test_no_global_accent_or_quantity_stripping(self):
        self.assertEqual(self.project(self.result, "παχεων")["aliases"], [])
        self.assertEqual(self.project(self.result, "πᾱχέων")["aliases"], [])

    def test_complete_packet_replays_without_mutation(self):
        original = deepcopy(self.result)
        result = self.project(original)
        self.assertEqual(result, original)
        result["aliases"][0]["matched_object_form"]["tags"].clear()
        self.assertEqual(original, self.result)

    def test_altered_link_in_claim_rejected_by_parent(self):
        result = deepcopy(self.result)
        claim = next(c for c in result["supporting_claims"] if c["id"] == "wiktionary:kaikki:line:11786:morphology:entry")
        claim["object"]["forms"][11]["links"] = []
        self.assertNotIn("πᾶχυς", {a["entry_headword"] for a in self.project(result)["aliases"]})

    def test_altered_parent_link_fails_hash(self):
        result = deepcopy(self.result)
        record = next(r for r in result["supporting_source_records"] if r["id"] == "wiktionary:kaikki:line:11786")
        record["entry"]["forms"][11]["links"] = []
        self.assertNotIn("πᾶχυς", {a["entry_headword"] for a in self.project(result)["aliases"]})

    def test_altered_structured_relation_cannot_reach_target(self):
        result = deepcopy(self.result)
        claim = next(c for c in result["supporting_claims"] if c["id"] == "wiktionary:kaikki:line:11786:sense:0")
        claim["object"]["source_sense"]["alt_of"] = []
        projected = self.project(result)
        self.assertIn("πᾶχυς", {a["entry_headword"] for a in projected["aliases"]})
        self.assertNotIn("πῆχυς", {m["target_headword"] for m in projected["meaning_candidates"]})

    def test_changed_sense_binding_prevents_relation(self):
        result = deepcopy(self.result)
        claim = next(c for c in result["supporting_claims"] if c["id"] == "wiktionary:kaikki:line:11786:sense:0")
        claim["metadata"]["source_raw_line_sha256"] = "0" * 64
        self.assertNotIn("πῆχυς", {m["target_headword"] for m in self.project(result)["meaning_candidates"]})

    def test_missing_target_proof_keeps_alias_but_not_target_sense(self):
        result = deepcopy(self.result)
        result["supporting_source_records"] = [r for r in result["supporting_source_records"]
                                               if r["id"] != "wiktionary:kaikki:line:7510"]
        self.assertIn("πᾶχυς", {a["entry_headword"] for a in self.project(result)["aliases"]})
        self.assertNotIn("πῆχυς", {m["target_headword"] for m in self.project(result)["meaning_candidates"]})

    def test_no_placeholder_translation_used_as_meaning(self):
        self.assertTrue(all("please add" not in gloss.lower() for m in self.result["meaning_candidates"]
                            for gloss in m["sense"]["glosses"]))

    def test_no_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            self.assertTrue(lookup_form_link_aliases("παχέων", self.index)["aliases"])


if __name__ == "__main__":
    unittest.main()
