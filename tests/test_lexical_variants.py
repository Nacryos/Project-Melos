from copy import deepcopy
import unittest

from backend.evidence import EvidenceIndex
from backend.lexical_variants import lookup_variants, project_variants, literal_sense_crossreferences


class LexicalVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = EvidenceIndex()
        cls.talais = lookup_variants("τάλαις", cls.index)
        cls.oppai = lookup_variants("ὄππᾳ", cls.index)

    def test_exact_aeolic_variant_has_source_meaning_not_invented_parse(self):
        rows = self.talais["lexical_variants"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lemma"], "τάλας")
        self.assertEqual(rows[0]["source_tags"], ["alternative", "Aeolic"])
        self.assertTrue(rows[0]["entry_senses"])
        self.assertIsNone(rows[0]["analysis"])
        self.assertIsNone(rows[0]["features"])

    def test_iota_subscript_not_folded_into_noun(self):
        rows = self.oppai["lexical_variants"]
        self.assertEqual([row["lemma"] for row in rows], ["ὅπῃ"])
        self.assertTrue(rows[0]["entry_senses"])
        self.assertNotIn("ὄππα", [row["lemma"] for row in rows])

    def test_mutated_quoted_form_abstains(self):
        claims = deepcopy(self.talais["supporting_claims"])
        for claim in claims:
            if claim["predicate"] == "dialect_label":
                claim["evidence"][0]["quote"] = "{}"
        self.assertEqual(project_variants("τάλαις", claims), [])

    def test_different_accents_do_not_match(self):
        self.assertEqual(project_variants("ταλαις", self.talais["supporting_claims"]), [])

    def test_missing_headword_proof_abstains(self):
        claims = [claim for claim in self.talais["supporting_claims"] if not claim["id"].endswith(":lemma:entry")]
        self.assertEqual(project_variants("τάλαις", claims), [])

    def test_duplicate_claim_identity_abstains(self):
        claims = deepcopy(self.talais["supporting_claims"])
        claims.append(next(claim for claim in claims if claim["predicate"] == "dialect_label"))
        self.assertEqual(project_variants("τάλαις", claims), [])

    def test_explicit_linked_lyric_crossreference_retained_unresolved(self):
        result = lookup_variants("δᾶμον", self.index)
        self.assertEqual(result["lexical_variants"], [])
        refs = result["dictionary_crossreferences"]
        self.assertEqual([ref["target_headword"] for ref in refs], ["δῆμος"])
        self.assertEqual(refs[0]["relation_text"], "Lyric form of δῆμος (dêmos)")
        self.assertEqual(refs[0]["resolution_status"], "unresolved_dictionary_crossreference")
        self.assertEqual(refs[0]["query_anchors"][0]["source_form"]["form"], "δᾶμον")
        anchor_id = refs[0]["query_anchors"][0]["claim_id"]
        proof = next(claim for claim in result["supporting_claims"] if claim["id"] == anchor_id)
        ordinal = refs[0]["query_anchors"][0]["form_index"]
        self.assertEqual(proof["object"]["forms"][ordinal], refs[0]["query_anchors"][0]["source_form"])

    def test_relation_without_literal_source_link_abstains(self):
        claim = deepcopy(self.index.get_claim("wiktionary:kaikki:line:9399:sense:0"))
        claim["object"]["source_sense"]["links"] = []
        self.assertEqual(literal_sense_crossreferences(claim), [])

    def test_source_examples_do_not_leak_into_english_variant_previews(self):
        result = lookup_variants("ἐς", self.index)
        senses = [sense for variant in result["lexical_variants"] for sense in variant["entry_senses"]]
        self.assertTrue(senses)
        for sense in senses:
            for gloss in sense["glosses"]:
                self.assertNotIn("\n", gloss)
                self.assertFalse(any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff" for char in gloss))

    def test_dictionary_pos_requires_agreeing_bound_source_fields(self):
        variant = self.oppai["lexical_variants"][0]
        self.assertEqual(variant["dictionary_pos"], "adv")
        proofs = {claim["id"]: claim for claim in self.oppai["supporting_claims"]}
        self.assertEqual(len(variant["dictionary_pos_claim_ids"]), 2)
        self.assertTrue(all(proofs[identifier]["object"]["pos"] == "adv"
                            for identifier in variant["dictionary_pos_claim_ids"]))
        self.assertIsNone(variant["features"])
        self.assertIsNone(variant["analysis"])

    def test_variant_entry_adjective_pos_does_not_supply_case_or_gender(self):
        variant = self.talais["lexical_variants"][0]
        self.assertEqual(variant["dictionary_pos"], "adj")
        self.assertIsNone(variant["features"])
        self.assertIsNone(variant["analysis"])

    def test_disagreeing_entry_pos_remains_unprojected(self):
        claims = deepcopy(self.oppai["supporting_claims"])
        for claim in claims:
            if claim["id"].endswith(":morphology:entry"):
                claim["object"]["pos"] = "verb"
        variant = project_variants("ὄππᾳ", claims)[0]
        self.assertNotIn("dictionary_pos", variant)
        self.assertNotIn("dictionary_pos_claim_ids", variant)

    def test_missing_entry_pos_remains_unprojected(self):
        claims = deepcopy(self.oppai["supporting_claims"])
        for claim in claims:
            if claim["id"].endswith(":lemma:entry"):
                claim["object"].pop("pos")
        variant = project_variants("ὄππᾳ", claims)[0]
        self.assertNotIn("dictionary_pos", variant)


if __name__ == "__main__":
    unittest.main()
