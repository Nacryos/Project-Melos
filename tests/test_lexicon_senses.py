"""Regression checks read actual archived records; fixtures add no lexicon data."""
import json
from pathlib import Path
import unittest

from backend.lexicon_render import SPACE, _render_spans, read_entry, render_source_record
from backend.lexicon_senses import dictionary_senses, _backward_tense_restrictions

ROOT = Path(__file__).resolve().parents[1]
WANTED = {"lsj:1:n8665", "lsj:5:n30657", "lsj:11:n57100", "lsj:17:n77627",
          "lsj:1:n3", "autenrieth:n1", "autenrieth:n1004", "autenrieth:n2644",
          "lsj:17:n78950", "lsj:5:n43658", "lsj:17:n82545", "lsj:17:n91061",
          "lsj:1:n17907", "lsj:23:n108092", "lsj:4:n24236", "lsj:5:n42827"}


class LexiconSenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / "data/lexica/entries.jsonl"
        if not source.is_file():
            raise unittest.SkipTest("Downloaded dictionary records unavailable")
        cls.records = {}
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record["id"] in WANTED:
                    cls.records[record["id"]] = record
        if cls.records.keys() != WANTED:
            raise unittest.SkipTest("Required archived source entries unavailable")

    def senses(self, entry):
        return dictionary_senses(self.records[entry])["dictionary_senses"]

    def test_man_is_not_sanskrit_or_opposed_woman(self):
        senses = self.senses("lsj:1:n8665")
        texts = [s["text"] for s in senses]
        self.assertEqual(texts[0], "man")
        self.assertIn("husband", texts)
        self.assertIn("male animal", texts)
        self.assertIn("free men", texts)
        self.assertNotIn("woman", texts)
        self.assertNotIn("god", texts)
        self.assertNotIn("beast", texts)
        self.assertNotIn("free", texts)
        self.assertFalse(any("nar-" in t or "ner-" in t for t in texts))
        self.assertIn("opp. woman", senses[0]["scope_text"])

    def test_ego_sanskrit_me_is_not_an_english_definition(self):
        senses = self.senses("lsj:5:n30657")
        self.assertEqual(senses[0]["text"], "I")
        self.assertNotIn("me", [s["text"] for s in senses])
        strengthened = next(s for s in senses if s["text"].startswith("I at least"))
        self.assertEqual(strengthened["form_scope"]["relation"], "variant")
        self.assertEqual(strengthened["form_scope"]["text"], "\u1f14\u03b3\u03c9\u03b3\u03b5")
        autenrieth = self.senses("autenrieth:n2644")
        self.assertEqual(autenrieth[0]["text"], "I, me.")

    def test_qualified_lexical_senses_exclude_example_and_bibliographic_title(self):
        senses = self.senses("lsj:17:n77627")
        self.assertEqual(senses[0]["text"], "of every kind, of all sorts, manifold")
        self.assertIn("of every country", [s["text"] for s in senses])
        self.assertNotIn("A\u00ebr.", [s["text"] for s in senses])
        self.assertNotIn("assumes every shape", [s["text"] for s in senses])
        adverb = next(s for s in senses if s["text"] == "in all kinds of ways")
        self.assertEqual(adverb["form_scope"]["relation"], "variant")
        self.assertIn("Adv.", adverb["scope_text"])

    def test_charm_preserves_citation_and_sense_identity(self):
        sense = self.senses("lsj:11:n57100")[0]
        self.assertEqual(sense["text"], "charm, spell")
        self.assertEqual(sense["sense_path"][0]["id"], "n57100.0")
        self.assertTrue(any("Ibyc." in c["text"] for c in sense["citations"]))
        self.assertEqual(sense["lexicon_entry_id"], "lsj:11:n57100")

    def test_prose_interjection_definition_does_not_use_example_translation(self):
        self.assertEqual(self.senses("lsj:1:n3")[0]["text"],
                         "exclamation expressing pity, envy, contempt, etc.")
        values = [s["text"] for s in self.senses("autenrieth:n1")]
        self.assertEqual(values, ["interjection expressive of pity or horror"])

    def test_explicit_preamble_grammatical_counterpart_is_not_a_usage_example(self):
        senses = self.senses("lsj:4:n24236")
        self.assertEqual(senses[0]["text"], "come hither!")
        self.assertEqual(senses[0]["form_scope"]["relation"], "headword")
        self.assertEqual(senses[0]["source_locator"]["node_path"],
                         "/entryFree/sense/tr")

    def test_all_sample_offsets_reproduce_exact_definition_and_scope(self):
        for record in self.records.values():
            entry, entities = read_entry(record["raw_path"], record["entry_id"])
            rendered, _ = _render_spans(entry, entities)
            for sense in dictionary_senses(record)["dictionary_senses"]:
                with self.subTest(entry=record["id"], sense=sense["id"]):
                    loc = sense["source_locator"]
                    self.assertEqual(sense["text"], SPACE.sub(" ", rendered[
                        loc["rendered_start"]:loc["rendered_end"]]).strip())
                    self.assertTrue(entry.getroottree().xpath(loc["node_path"]))
                    loc = sense["scope_locator"]
                    self.assertEqual(sense["scope_text"], SPACE.sub(" ", rendered[
                        loc["rendered_start"]:loc["rendered_end"]]).strip())
                    self.assertEqual(sense["raw_sha256"], record["raw_sha256"])
                    self.assertEqual(sense["source_url"], record["source_url"])

    def test_hash_mismatch_and_missing_provenance_fail_closed(self):
        record = dict(self.records["lsj:11:n57100"], raw_sha256="0" * 64)
        result = dictionary_senses(record)
        self.assertEqual(result["dictionary_senses"], [])
        self.assertEqual(result["dictionary_senses_status"], "source_hash_mismatch")
        record.pop("raw_sha256")
        self.assertEqual(dictionary_senses(record)["dictionary_senses_status"], "missing_source_provenance")

    def test_render_integration_does_not_overwrite_archived_gloss(self):
        record = self.records["lsj:1:n8665"]
        original = dict(record)
        result = render_source_record(record)
        self.assertEqual(result["dictionary_senses"][0]["text"], "man")
        self.assertEqual(record, original)
        self.assertIn("rendered_entry_text", result)

    def test_unsupported_source_not_reclassified_and_cache_cannot_be_mutated(self):
        self.assertEqual(dictionary_senses({"source": "unrecognized source"}), {})
        result = self.senses("lsj:11:n57100")
        result[0]["text"] = "test-only mutation"
        self.assertEqual(self.senses("lsj:11:n57100")[0]["text"], "charm, spell")

    def test_definition_ids_stable_and_distinct_across_sources(self):
        first = self.senses("lsj:1:n8665")
        second = self.senses("autenrieth:n1004")
        ids = [s["id"] for s in first + second]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(first, self.senses("lsj:1:n8665"))

    def test_emphasis_fragments_are_not_separate_meanings(self):
        values = [s["text"] for s in self.senses("lsj:17:n78950")]
        self.assertIn("turn one from his opinion, change his mind", values)
        self.assertNotIn("from", values)
        self.assertNotIn("opinion, change", values)
        self.assertEqual(self.senses("lsj:17:n91061")[0]["text"], "to be primitive or original")

    def test_dislocated_bibliographic_markup_and_complement_are_excluded(self):
        values = [s["text"] for s in self.senses("lsj:5:n43658")]
        self.assertIn("easily carried off by perspiration or secretion", values)
        self.assertNotIn("secretion", values)
        self.assertNotIn("in de An.", values)
        self.assertEqual([s["text"] for s in self.senses("lsj:17:n82545")], ["exceeding glad"])

    def test_parenthetical_variant_does_not_restrict_every_later_sense(self):
        for entry in ("lsj:1:n17907", "lsj:23:n108092"):
            with self.subTest(entry=entry):
                senses = self.senses(entry)
                self.assertTrue(senses)
                self.assertEqual(senses[0]["form_scope"]["relation"], "headword")
                self.assertFalse(any(s["text"].endswith((", sts", ", freq", ", i")) for s in senses))
                self.assertNotIn("NT", [s["text"] for s in senses])
                self.assertTrue(all(s["qualifier_scope"] == "containing_source_sense_not_individual_definition" for s in senses))

    def test_explicit_two_foregoing_tense_restriction_targets_only_named_units(self):
        record = self.records["lsj:5:n42827"]
        senses = self.senses(record["id"])
        restricted = [s for s in senses if s.get("morphology_restrictions")]
        self.assertEqual([s["text"] for s in restricted], ["start, set out", "walk"])
        self.assertFalse(next(s for s in senses if s["text"] == "come or go").get("morphology_restrictions"))
        entry, entities = read_entry(record["raw_path"], record["entry_id"])
        text, _ = _render_spans(entry, entities)
        for sense in restricted:
            restriction = sense["morphology_restrictions"][0]
            self.assertEqual(restriction["allowed_values"], ["Pres"])
            self.assertEqual(restriction["scope"]["target_source_sense_ids"], ["n42827.1", "n42827.2"])
            loc = restriction["source_locator"]
            self.assertEqual(restriction["source_text"], SPACE.sub(" ", text[loc["rendered_start"]:loc["rendered_end"]]).strip())
            self.assertEqual(restriction["raw_sha256"], record["raw_sha256"])
            self.assertEqual(restriction["source_url"], record["source_url"])
            loc = restriction["tense_source_locator"]
            self.assertEqual(text[loc["rendered_start"]:loc["rendered_end"]], "pres.")

    def test_backward_reference_layout_mutations_abstain(self):
        # Negative unit-test mutations of the real source tree, never saved
        # as corpus data or represented as a hash-verified production source.
        record = self.records["lsj:5:n42827"]
        for mutation in ("negated", "all", "wrong_count", "wrong_headword", "wrong_number",
                         "wrong_level", "nested", "trailing_scope", "missing_previous_meaning",
                         "different_tense", "shifted_previous_sibling"):
            with self.subTest(mutation=mutation):
                entry, entities = read_entry(record["raw_path"], record["entry_id"])
                current = entry.xpath("sense[@id='n42827.2']")[0]
                tense = current.find("tns")
                tail_owner, form = tense.getprevious(), tense.getnext()
                rows = self.senses(record["id"])
                for row in rows:
                    row.pop("morphology_restrictions", None)
                if mutation == "negated":
                    tail_owner.tail = tail_owner.tail.replace("belong only", "do not belong only")
                elif mutation == "all":
                    tail_owner.tail = tail_owner.tail.replace("the two foreg.", "all foreg.")
                elif mutation == "wrong_count":
                    tail_owner.tail = tail_owner.tail.replace("the two foreg.", "the three foreg.")
                elif mutation == "wrong_headword":
                    form.text = entry.xpath("sense[@id='n42827.1']/foreign")[0].text
                elif mutation == "wrong_number":
                    current.set("n", "3")
                elif mutation == "wrong_level":
                    current.set("level", "2")
                elif mutation == "nested":
                    current.getprevious().append(current)
                elif mutation == "trailing_scope":
                    form.tail = " but another scope follows"
                elif mutation == "missing_previous_meaning":
                    rows = [row for row in rows if row["sense_path"][-1]["id"] != "n42827.1"]
                elif mutation == "different_tense":
                    tense.text = "aor."
                elif mutation == "shifted_previous_sibling":
                    entry.insert(entry.index(current), entry.xpath("sense[@id='n42827.3']")[0])
                text, spans = _render_spans(entry, entities)
                _backward_tense_restrictions(entry, text, spans, rows)
                self.assertFalse(any(row.get("morphology_restrictions") for row in rows))


if __name__ == "__main__":
    unittest.main()
