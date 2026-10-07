"""Real retained-source regressions; assertions do not add dictionary rows."""
import json
from pathlib import Path
import unittest

from backend.lexicon_render import SPACE, _render_spans, read_entry
from backend.lexicon_senses import dictionary_senses

ROOT = Path(__file__).resolve().parents[1]
WANTED = {"lsj:5:n44560", "lsj:21:n96270", "lsj:17:n79904", "lsj:17:n79905",
          "lsj:13:n68949", "lsj:1:n16814"}


class LyricDictionaryGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "data/lexica/entries.jsonl"
        if not path.exists():
            raise unittest.SkipTest("Retained source dictionary unavailable")
        cls.records = {}
        with path.open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                if row["id"] in WANTED:
                    cls.records[row["id"]] = row
        if cls.records.keys() != WANTED:
            raise unittest.SkipTest("Required retained entries unavailable")

    def result(self, key):
        return dictionary_senses(self.records[key])

    def test_definition_after_explicit_preamble_boundary(self):
        result = self.result("lsj:5:n44560")
        self.assertEqual([r["text"] for r in result["dictionary_senses"]],
                         ["well-disposed, kindly, friendly"])
        self.assertEqual(result["dictionary_senses"][0]["form_scope"]["relation"], "headword")
        # Subsequent translations of examples do not become lemma meanings.
        self.assertNotIn("well-wishers", [r["text"] for r in result["dictionary_senses"]])

    def test_new_sense_does_not_inherit_foreign_preamble(self):
        senses = self.result("lsj:21:n96270")["dictionary_senses"]
        values = [r["text"] for r in senses]
        self.assertEqual(values[0], "placing, setting")
        self.assertIn("standing still, stationariness", values)
        self.assertIn("faction, sedition, discord", values)
        self.assertNotIn("paying", values)
        self.assertNotIn("sluggishness", values)  # bracketed example is not an editorial note

    def test_homograph_crossreference_not_promoted_to_definition(self):
        ordinary = self.result("lsj:17:n79904")
        cyprian = self.result("lsj:17:n79905")
        self.assertEqual(ordinary["dictionary_senses"][0]["text"], "all")
        self.assertEqual(cyprian["dictionary_senses"], [])
        refs = cyprian["dictionary_crossreferences"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["target_key"], "pai=s")
        self.assertEqual(refs[0]["resolution_status"], "unresolved")
        self.assertEqual(refs[0]["lexicon_entry_id"], "lsj:17:n79905")
        self.assertNotEqual(refs[0]["lexicon_entry_id"], ordinary["dictionary_senses"][0]["lexicon_entry_id"])

    def test_all_definitions_and_edges_are_exact_source_spans(self):
        for key, record in self.records.items():
            entry, entities = read_entry(record["raw_path"], record["entry_id"])
            rendered, _ = _render_spans(entry, entities)
            result = self.result(key)
            for row in result["dictionary_senses"] + result["dictionary_crossreferences"]:
                with self.subTest(entry=key, locator=row["source_locator"]):
                    loc = row["source_locator"]
                    value = row.get("text", row.get("target_text"))
                    self.assertEqual(value, SPACE.sub(" ", rendered[loc["rendered_start"]:loc["rendered_end"]]).strip())
                    self.assertTrue(entry.getroottree().xpath(loc["node_path"]))
                    self.assertEqual(row["raw_sha256"], record["raw_sha256"])
                    self.assertEqual(row["lexicon_entry_id"], key)
                    self.assertEqual(row["source_url"], record["source_url"])
                    if "relation_locator" in row:
                        edge = row["relation_locator"]
                        self.assertEqual(row["relation_text"], SPACE.sub(" ", rendered[edge["rendered_start"]:edge["rendered_end"]]).strip())

    def test_missing_provenance_cannot_emit_crossreferences(self):
        record = dict(self.records["lsj:17:n79905"], raw_sha256="0" * 64)
        result = dictionary_senses(record)
        self.assertEqual(result["dictionary_senses_status"], "source_hash_mismatch")
        self.assertFalse(result.get("dictionary_crossreferences"))

    def test_pre_sense_greek_example_still_excludes_translation(self):
        values = [s["text"] for s in self.result("lsj:13:n68949")["dictionary_senses"]]
        self.assertNotIn("they strove to heave them up with levers", values)
        self.assertNotIn("they strove", values)

    def test_subentry_meanings_remain_bound_to_explicit_orth(self):
        senses = self.result("lsj:1:n16814")["dictionary_senses"]
        noun, verb, aeolic = senses
        self.assertEqual(noun["form_scope"]["relation"], "headword")
        self.assertEqual(verb["form_scope"]["source_locator"]["node_path"], "/entryFree/sense/orth[1]")
        self.assertEqual(aeolic["form_scope"]["source_locator"]["node_path"], "/entryFree/sense/orth[2]")
        self.assertEqual(aeolic["text"], "fail to understand")


if __name__ == "__main__":
    unittest.main()
