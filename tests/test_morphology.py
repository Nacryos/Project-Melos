"""Synthetic fixtures exercise lookup mechanics, not corpus content."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unicodedata

from backend.morphology import Morphology, describe_postag, normalize, query_variants, tokenize


class MorphologyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        entries = root / "entries.jsonl"
        forms = root / "forms.jsonl"
        with entries.open("w", encoding="utf-8") as target:
            for row in [
                {"lemma": "θεός", "gloss": "god", "entry_text": "A longer sourced entry.",
                 "source": "Fixture lexicon", "source_url": "https://example.test/lexicon/theos"},
                {"lemma": "Θεός", "gloss": "a name", "source_url": "https://example.test/lexicon/name"},
                {"lemma": "λύω", "gloss": "release", "source_url": "https://example.test/lexicon/luo"},
            ]:
                target.write(json.dumps(row, ensure_ascii=False) + "\n")
        with forms.open("w", encoding="utf-8") as target:
            for row in [
                {"form": "θεός", "lemma": "θεός", "analysis": "n-s---mn-",
                 "analysis_format": "fixture postag", "quality": "annotated_treebank_token",
                 "source": "Fixture treebank", "source_url": "https://example.test/treebank/1"},
                {"form": "θεός", "lemma": "θεός", "analysis": "n-s---mn-",
                 "analysis_format": "fixture postag", "quality": "annotated_treebank_token",
                 "source": "Fixture treebank", "source_url": "https://example.test/treebank/4"},
                {"form": "θεός", "lemma": "Θεός", "analysis": "n-s---mn-",
                 "source_url": "https://example.test/treebank/2"},
                {"form": "λύει", "lemma": "λύω", "analysis": "v3spia---",
                 "source_url": "https://example.test/treebank/3"},
            ]:
                target.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.service = Morphology(entries, forms)

    def test_normalize_keeps_text_separate_from_folded_key(self):
        self.assertEqual(normalize("Ἔρως ῥόδων ς ϲ"), "ερωσ ροδων σ σ")
        self.assertEqual(normalize("μ’ ἔφη"), "μ' εφη")
        self.assertEqual(tokenize("μ’ ἔφη, λόγον."), ["μ’", "ἔφη", "λόγον"])

    def test_ascii_query_conventions(self):
        self.assertEqual(query_variants("QEO/S")[0], "θεοσ")
        self.assertEqual(query_variants("theos")[0], "θεοσ")
        self.assertEqual(query_variants("m’")[0], "μ'")
        self.assertEqual(query_variants("λύει"), ["λυει"])

    def test_transliterated_apostrophes_never_add_bare_word_fallback(self):
        for mark in "'’᾽ʼ":
            self.assertEqual(query_variants('kamm' + mark), ["καμμ'"])
            self.assertEqual(query_variants('KAMM' + mark), ["καμμ'"])
        self.assertEqual(query_variants("KA/MM'"), ["καμμ'", "κα μμ'"])
        self.assertEqual(query_variants('kamm᾿'), ['καμμ᾿'])
        self.assertEqual(query_variants('κἄμμ᾿'), ['καμμ᾿'])
        self.assertNotEqual(normalize('κἄμμ᾿'), normalize('κἄμμ’'))

    def test_transliteration_does_not_delete_boundaries_and_invent_joined_words(self):
        for boundary in (',', '-', '[123]', '.', ';', '123', '—', '_'):
            self.assertEqual(query_variants('a' + boundary + 'b'), ['α β'])
        self.assertEqual(query_variants('a[b]c'), ['α β κ', 'α β ξ'])
        self.assertEqual(query_variants('A)/')[0], 'α')
        self.assertEqual(query_variants('A?')[0], 'α')

    def test_exact_retains_ambiguity_and_provenance(self):
        response = self.service.analyze("θεός")
        self.assertEqual(response["normalized"], "θεοσ")
        self.assertEqual(self.service.counts(), {"entries": 3, "forms": 4})
        lemmas = {item["lemma"] for item in response["candidates"]}
        self.assertEqual(lemmas, {"θεός", "Θεός"})
        self.assertTrue(all(item["source_url"] for item in response["candidates"]))
        self.assertTrue(any(item["analysis"] == "n-s---mn-" for item in response["candidates"]))
        self.assertEqual(response["analysis_match_status"], "source_analysis_available")
        self.assertFalse(any("No exact indexed morphological analysis" in warning
                             for warning in response["warnings"]))
        self.assertTrue(any(item["entry_text"] == "A longer sourced entry." for item in response["candidates"]))
        self.assertTrue(any(item["analysis_format"] == "fixture postag" for item in response["candidates"]))
        self.assertEqual(len([item for item in response["candidates"]
                              if item["lemma"] == "θεός" and item["analysis"]]), 1)
        self.assertEqual(len(next(item for item in response["candidates"]
                                  if item["lemma"] == "θεός" and item["analysis"])["supporting_sources"]), 2)
        # Folded retrieval also offers the capitalized proper-name lemma.
        # An unresolved query must not pool either lemma's recorded forms.
        self.assertEqual(response["attested_forms"], [])
        self.assertTrue(response["observed_form_groups"])
        self.assertEqual(self.service.forms_for_lemma("LUW"), ["λύει"])
        self.assertEqual(self.service.forms_for_lemma("ἀνύπαρκτος"), [])

    def test_context_requires_actual_annotated_occurrence(self):
        occurrence = {"lemma": "Θεός", "analysis": "n-s---mn-", "passage_id": "p1",
                      "author": "A", "source_url": "https://example.test/treebank/2"}
        result = self.service.analyze("θεός", {"id": "p1", "author": "A"},
                                      occurrence_lookup=lambda key, limit: [occurrence])
        self.assertEqual(result["candidates"][0]["lemma"], "Θεός")
        self.assertIn("annotated parse in this passage", result["candidates"][0]["reason"])
        raw_only = self.service.analyze("θεός", {"id": "p1", "author": "A"},
                                        occurrence_lookup=lambda key, limit: [{"passage_id": "p1", "author": "A"}])
        self.assertFalse(any("annotated parse" in row["reason"] for row in raw_only["candidates"]))
        self.assertIn("Context shown; these analyses are alternatives, not a resolved sense.",
                      raw_only["warnings"])
        named_only = self.service.analyze(
            "θεός", {"id": "different", "author": "A"},
            occurrence_lookup=lambda key, limit: [
                {"lemma": "Θεός", "analysis": "n-s---mn-", "author": "A",
                 "source_url": "https://example.test/treebank/2"}])
        self.assertFalse(any("author's corpus" in row["reason"]
                             for row in named_only["candidates"]))

    def test_typo_suggests_only_attested_candidate(self):
        result = self.service.analyze("λυεο")
        self.assertTrue(any(row["lemma"] == "λύω" and "edit" in row["reason"]
                            for row in result["candidates"]))
        self.assertEqual(result["analysis_match_status"], "spelling_suggestions_only")
        self.assertEqual(result["warnings"][0],
                         "No exact indexed morphological analysis was found for this form. "
                         "The following analyses belong to nearby spellings, not necessarily the queried form.")
        self.assertTrue(all(row["edit_distance"] > 0 and row["matched_form"]
                            for row in result["candidates"]))
        self.assertTrue(all(row["matched_form"] in row["reason"]
                            for row in result["candidates"]))
        self.assertFalse(any(row.get("analysis") == "invented" for row in result["candidates"]))

    def test_missing_files_do_not_invent_parse(self):
        root = Path(self.scratch.name)
        result = Morphology(root / "absent-entries", root / "absent-forms").analyze("ἀφανές")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["warnings"])

    def test_nfc_duplicates_group_without_folding_distinct_accents(self):
        forms = Path(self.scratch.name) / "forms.jsonl"
        with forms.open("a", encoding="utf-8") as target:
            for lemma, raw in [
                ("ὄρος", "ὄρος"),
                (unicodedata.normalize("NFD", "ὄρος"), unicodedata.normalize("NFD", "ὄρος")),
                ("ὄρος", "ὄρος1"),
                ("ὀρός", "ὀρός"),
            ]:
                target.write(json.dumps({"form": "ὀρέων", "lemma": lemma, "lemma_raw": raw,
                                         "analysis": "n-p---ng-",
                                         "analysis_format": "Perseus treebank 1.6 postag",
                                         "source_url": f"https://example.test/treebank/{len(raw)}"},
                                        ensure_ascii=False) + "\n")
        result = self.service.analyze("ὀρέων")
        mountain = [item for item in result["candidates"] if item["lemma"] == "ὄρος"]
        self.assertEqual(len(mountain), 1)
        self.assertEqual(mountain[0]["analysis_text"], "noun · plural · neuter · genitive")
        self.assertIn("ὄρος1", mountain[0]["lemma_raw_variants"])
        self.assertEqual(len([item for item in result["candidates"] if item["lemma"] == "ὀρός"]), 1)

    def test_postag_expansion_is_structural_only(self):
        self.assertEqual(describe_postag("n-p---ng-"), "noun · plural · neuter · genitive")
        self.assertEqual(describe_postag("v3spia---"),
                         "verb · third person · singular · present · indicative · active")
        self.assertIsNone(describe_postag("n-p---?g-"))
        self.assertIsNone(describe_postag("not a tag"))


if __name__ == "__main__":
    unittest.main()
