import json
from pathlib import Path
import unittest

from backend.lexicon_subentries import extract_subentries, lookup_key
from backend.lexicon_render import _render_spans, read_entry

ROOT = Path(__file__).resolve().parents[1]


class SubentriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = next(json.loads(line) for line in (ROOT / "data/lexica/entries.jsonl").open(encoding="utf8")
                          if json.loads(line)["id"] == "lsj:1:n16814")
        cls.rows = extract_subentries(cls.record)

    def test_source_has_two_distinct_subentries(self):
        self.assertEqual(len(self.rows), 2)
        self.assertEqual([r["lookup_key"] for r in self.rows], ["ἀσυνετέω", "ἀσυνέτημι"])
        self.assertEqual([r["dictionary_senses"][0]["text"] for r in self.rows],
                         ["to be without understanding", "fail to understand"])
        self.assertNotIn("stupidity", json.dumps([r["dictionary_senses"][0]["text"] for r in self.rows]))

    def test_exact_source_offsets(self):
        entry, entities = read_entry(self.record["raw_path"], self.record["entry_id"])
        text, _ = _render_spans(entry, entities)
        for row in self.rows:
            loc = row["source_locator"]
            self.assertEqual(text[loc["rendered_start"]:loc["rendered_end"]].strip(), row["orthography"])
            self.assertEqual(row["raw_sha256"], self.record["raw_sha256"])

    def test_dialect_does_not_inherit_from_parent(self):
        self.assertEqual(self.rows[0]["qualifiers"], [])
        self.assertEqual([q["text"] for q in self.rows[1]["qualifiers"]], ["Aeol."])
        self.assertEqual([q["text"] for q in self.rows[1]["citations"]], ["Alc. 18"])

    def test_never_invents_campbell_gemination(self):
        self.assertNotIn(lookup_key("ἀσυννέτημμι"), [r["lookup_key"] for r in self.rows])
        self.assertNotEqual(lookup_key("ἀσυνέτημι"), lookup_key("ἀσυννέτημμι"))

    def test_rejects_incomplete_or_editorial_forms(self):
        for query in ("ἀσυν-", "-έτημι", "ἀ[συν]έτημι", "ἀσυν έτημι", "ἀσυν--έτημι", "abc"):
            self.assertIsNone(lookup_key(query))
        self.assertNotEqual(lookup_key("ἄντλος"), lookup_key("ἀντλος"))

    def test_hash_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            extract_subentries({**self.record, "raw_sha256": "0" * 64})

    def test_mistagged_place_complement_does_not_become_bare_preposition(self):
        with (ROOT / "data/lexica/entries.jsonl").open(encoding="utf8") as handle:
            record = next(row for row in map(json.loads, handle) if row["id"] == "lsj:11:n59120")
        rows = extract_subentries(record)
        self.assertFalse(any(row["lookup_key"] == "Κορινθόθι" for row in rows))

    def test_source_spelling_is_not_promoted_to_validated_morphology(self):
        for row in self.rows:
            self.assertEqual(row["morphology_status"], "not_supplied")
            self.assertEqual(row["spelling_validation"], "literal_source_spelling_not_independently_validated_full_form")


if __name__ == "__main__":
    unittest.main()
