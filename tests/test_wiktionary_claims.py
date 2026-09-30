"""Synthetic fixture tests for scoped Wiktionary claim extraction."""

from __future__ import annotations

from hashlib import sha256
import json
import unittest

from scripts.extract_p2_wiktionary import claims_for_wrapper


class WiktionaryClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = {
            "word": "λέξις", "pos": "noun", "lang_code": "grc",
            "forms": [
                {"form": "Attic declension", "tags": ["table-tags"], "source": "inflection"},
                {"form": "λέξεως", "tags": ["genitive", "singular"], "source": "inflection"},
                {"form": "λέξιος", "tags": ["alternative", "Ionic"]},
            ],
            "senses": [
                {"id": "test-sense-1", "glosses": ["speech"],
                 "tags": ["Ionic", "noun"], "examples": [{"text": "quoted text", "ref": "synthetic citation"}]},
                {"id": "test-sense-2", "glosses": ["form of another word"],
                 "tags": ["form-of"], "form_of": [{"word": "λέγω"}]},
                {"id": "test-sense-3", "glosses": ["alternative"],
                 "tags": ["alt-of"], "alt_of": [{"word": "λέξις2"}]},
                {"id": "test-sense-4", "raw_glosses": ["source-only raw gloss"],
                 "examples": [{"text": "source-only example"}]},
            ],
        }
        self.wrapper = {
            "id": "wiktionary:kaikki:line:1", "source_url": "https://example.test/source",
            "raw_path": "data/raw/test.jsonl", "raw_sha256": "raw-hash",
            "raw_line": 1, "raw_line_sha256": "raw-line-hash",
            "quality": "test_only", "license": "test_only", "entry": self.entry,
        }
        self.line = json.dumps(self.wrapper, ensure_ascii=False) + "\n"
        self.wrapper["_parent_line_sha256"] = sha256(self.line.rstrip("\n").encode()).hexdigest()
        self.rows = list(claims_for_wrapper(self.wrapper, "accepted-parent-hash", self.line))

    def test_full_forms_and_exact_parent_quotes(self) -> None:
        morphology = next(row for row in self.rows if row["predicate"] == "morphology")
        self.assertEqual(morphology["object"]["forms"], self.entry["forms"])
        self.assertEqual(morphology["evidence"][0]["locator"], "/entry/forms")
        for row in self.rows:
            ev = row["evidence"][0]
            self.assertIn(ev["quote"], self.line)
            self.assertEqual(ev["parent_sha256"], self.wrapper["_parent_line_sha256"])
            self.assertEqual(ev["raw_sha256"], "accepted-parent-hash")

    def test_dialect_scope_and_relations(self) -> None:
        dialect = [row for row in self.rows if row["predicate"] == "dialect_label"]
        self.assertEqual(len(dialect), 2)
        by_scope = {row["metadata"]["dialect_scope"]: row for row in dialect}
        self.assertEqual(by_scope["listed_form"]["subject"]["form"], "λέξιος")
        self.assertEqual(by_scope["listed_form"]["object"]["form_index"], 2)
        self.assertEqual(by_scope["sense"]["subject"]["form"], "λέξις")
        self.assertEqual(by_scope["sense"]["object"]["sense_index"], 0)
        senses = [r for r in self.rows if r["predicate"] == "sense_gloss"]
        self.assertEqual(len(senses), 4)
        self.assertEqual(senses[-1]["object"]["raw_glosses"], ["source-only raw gloss"])
        self.assertEqual(senses[-1]["evidence"][0]["locator"], "/entry/senses/3/raw_glosses")
        relations = [r for r in self.rows if r["object"].get("relation")]
        self.assertEqual({r["object"]["relation"] for r in relations}, {"form_of", "alt_of"})
        self.assertTrue(all("passage_id" not in r["subject"] for r in self.rows))


if __name__ == "__main__":
    unittest.main()
