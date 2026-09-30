"""Evidence and alignment checks for the accepted-commentary note extractor."""

import hashlib
import json
import unittest
from pathlib import Path

from scripts.extract_p2_notes import ROOT, OUTPUT, features, fold


class NotesExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claims = [json.loads(line) for line in OUTPUT.read_text(encoding="utf-8").splitlines()]
        cls.source_lines = {}
        cls.records = {}
        for line in (ROOT / "data/processed/sappho.jsonl").read_bytes().splitlines():
            record = json.loads(line)
            cls.source_lines[record["id"]] = line
            cls.records[record["id"]] = record

    def test_all_claims_trace_to_accepted_parent_and_raw_artifact(self):
        raw_hashes = {}
        for claim in self.claims:
            for ev in claim["evidence"]:
                record = self.records[ev["record_id"]]
                self.assertIn(ev["quote"], record["text"])
                self.assertEqual(ev["parent_sha256"], hashlib.sha256(self.source_lines[record["id"]]).hexdigest())
                self.assertEqual(ev["raw_sha256"], record["raw_sha256"])
                self.assertEqual(ev["source_url"], record["source_url"])
                path = ev["raw_path"]
                if path not in raw_hashes:
                    raw_hashes[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                self.assertEqual(ev["raw_sha256"], raw_hashes[path])

    def test_all_linked_offsets_are_exact_python_slices(self):
        for claim in self.claims:
            subject = claim["subject"]
            if "passage_id" not in subject:
                self.assertNotIn("start", subject)
                self.assertNotIn("end", subject)
                continue
            source_text = self.records[subject["passage_id"]]["text"]
            surface = source_text[subject["start"]:subject["end"]]
            self.assertTrue(surface)
            self.assertEqual(fold(surface, diacritics=True), fold(subject["form"], diacritics=True))
            if claim["metadata"]["match_type"] == "casefold_nfd":
                self.assertEqual(fold(surface), fold(subject["form"]))

    def test_brothers_pemp_is_explicit_and_linked(self):
        pemp = [c for c in self.claims if c["subject"]["form"] == "πέμπην"
                and c["source_family"] == "DCC Sappho"]
        self.assertEqual({c["predicate"] for c in pemp}, {"equivalent_form", "morphology"})
        self.assertTrue(all(c["subject"]["passage_id"] == "dcc-sappho:brothers-poem" for c in pemp))
        self.assertEqual(next(c for c in pemp if c["predicate"] == "equivalent_form")["object"]["form"], "πέμπειν")
        self.assertEqual(next(c for c in pemp if c["predicate"] == "morphology")["object"]["features"],
                         {"tense": "present", "voice": "active", "mood": "infinitive"})

    def test_no_split_crasis_or_neighbor_grammar(self):
        self.assertFalse(any(c["subject"]["form"] == "μή" and c["predicate"] == "morphology"
                             for c in self.claims))
        self.assertFalse(any(c["subject"]["form"] == "κἄμμε" and c["object"].get("form") == "καί"
                             for c in self.claims))

    def test_abbreviation_expansion(self):
        self.assertEqual(features("1st pl. aor. pass. opt."),
                         {"person": 1, "number": "plural", "tense": "aorist",
                          "voice": "passive", "mood": "optative"})


if __name__ == "__main__":
    unittest.main()
