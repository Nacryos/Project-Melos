from copy import deepcopy
import unittest

from backend.linked_dictionary import compact_inventory, lookup_linked_dictionary, validated_candidates
from backend.dictionary_crossrefs import lookup_crossreference_meanings
from backend.source_link_aliases import lookup_form_link_aliases
from backend.noun_entry_features import lookup_noun_inherent_features
from backend.evidence import EvidenceIndex


class LinkedDictionaryTests(unittest.TestCase):
    def test_real_cubit_path_keeps_literal_anchor_and_owned_gender(self):
        inventory = lookup_linked_dictionary('παχέων')
        paths = inventory['candidates']
        cubit = next(r for r in paths if r['lemma'] == 'πᾶχυς')
        self.assertEqual(cubit['features'], {'Case': 'Gen', 'Number': 'Plur', 'POS': 'NOUN', 'Gender': 'Masc'})
        metadata = cubit['linked_path']['source_noun_metadata']
        self.assertEqual(metadata['entry_id'], 'wiktionary:kaikki:line:11786')
        self.assertEqual(metadata['evidence_groups'][0]['source_locator'], '/entry/forms/0/tags')
        self.assertTrue(metadata['applied_to_candidate'])
        self.assertFalse(metadata['contextually_selected'])
        self.assertEqual(cubit['linked_path']['printed_form'], 'πᾱχέων')
        self.assertEqual(cubit['linked_path']['target_headword'], 'πῆχυς')
        self.assertTrue(any(s['text'].startswith('cubit (') for s in cubit['senses']))
        self.assertEqual({r['lemma'] for r in paths}, {'πᾶχυς', 'παχύς', 'πάχος'})
        self.assertEqual(len({s['id'] for r in paths for s in r['senses']}), 15)

    def test_real_damon_homonyms_not_collapsed(self):
        paths = lookup_linked_dictionary('δᾶμον')['candidates']
        self.assertEqual(len(paths), 2)
        self.assertEqual({r['linked_path']['target_etymology_number'] for r in paths}, {'1', '2'})
        self.assertEqual(len({r['gloss_entry_id'] for r in paths}), 2)
        self.assertTrue(all(r['parse_short'] == 'acc. masc. sg.' for r in paths))
        self.assertTrue(all(r['linked_path']['source_noun_metadata']['entry_id'] ==
                            'wiktionary:kaikki:line:9399' for r in paths))
        self.assertTrue(all(r['linked_path']['source_noun_metadata']['evidence_groups'][0]['source_locator'] ==
                            '/entry/senses/0/tags' for r in paths))

    def test_relation_context_and_pos_disagreement_remain_explicit(self):
        paths = lookup_linked_dictionary('μέσσον')['candidates']
        mismatches = [r for r in paths if not r['linked_path']['literal_pos_agreement']]
        self.assertTrue(mismatches)
        for row in mismatches:
            self.assertEqual(row['features']['POS'], 'ADJ')
            self.assertEqual(row['linked_path']['target_dictionary_pos'], 'noun')
            self.assertTrue(row['linked_path']['relation_context']['relation_text'])
            self.assertNotIn('source_noun_metadata', row['linked_path'])
        for row in paths:
            for sense in row['senses']:
                self.assertEqual(sense['text'], sense['scope_text'][-1])

    def test_forged_or_incomplete_views_rejected_and_cache_not_mutable(self):
        original = lookup_linked_dictionary('παχέων')
        token = {'text': 'παχέων', 'linked_dictionary': deepcopy(original)}
        self.assertEqual(validated_candidates(token), original['candidates'])
        token['linked_dictionary']['candidates'].pop()
        self.assertEqual(validated_candidates(token), [])
        self.assertEqual(lookup_linked_dictionary('παχέων'), original)
        token['linked_dictionary'] = deepcopy(original)
        token['linked_dictionary']['candidates'][0]['features']['Gender'] = 'Fem'
        self.assertEqual(validated_candidates(token), [])
        token['linked_dictionary'] = original
        token['partial_word'] = True
        self.assertEqual(validated_candidates(token), [])

    def test_conflicting_paradigm_never_overrides_explicit_form_gender(self):
        paths = lookup_linked_dictionary('λαγῴα')['candidates']
        self.assertTrue(paths)
        for row in paths:
            self.assertEqual(row['features']['Gender'], 'Fem')
            metadata = row['linked_path']['source_noun_metadata']
            self.assertEqual(metadata['gender_status'], 'explicit_paradigm_gender_conflict')
            self.assertFalse(metadata['applied_to_candidate'])
            self.assertEqual(metadata['application_basis'], 'explicit_form_gender_preserved')

    def test_multiple_owned_genders_remain_unselected(self):
        paths = lookup_linked_dictionary('παισί')['candidates']
        self.assertTrue(paths)
        for row in paths:
            self.assertNotIn('Gender', row['features'])
            metadata = row['linked_path']['source_noun_metadata']
            self.assertEqual(metadata['dictionary_gender_options'], ['feminine', 'masculine'])
            self.assertEqual(metadata['gender_status'], 'multiple_source_genders')
            self.assertFalse(metadata['applied_to_candidate'])

    def test_target_metadata_cannot_be_mapped_to_source_entry(self):
        index = EvidenceIndex()
        crossrefs = lookup_crossreference_meanings('δᾶμον', index)
        aliases = lookup_form_link_aliases('δᾶμον', index)
        target = lookup_noun_inherent_features('wiktionary:kaikki:line:894', index)
        inventory = compact_inventory('δᾶμον', crossrefs, aliases,
                                      {'wiktionary:kaikki:line:9399': target})
        self.assertTrue(inventory['candidates'])
        self.assertTrue(all('Gender' not in c['features'] for c in inventory['candidates']))

    def test_tampered_metadata_replay_abstains_and_public_proof_is_checked(self):
        index = EvidenceIndex()
        source = lookup_noun_inherent_features('wiktionary:kaikki:line:9399', index)
        source['unambiguous_entry_gender'] = 'feminine'
        inventory = compact_inventory('δᾶμον', lookup_crossreference_meanings('δᾶμον', index),
                                      lookup_form_link_aliases('δᾶμον', index),
                                      {'wiktionary:kaikki:line:9399': source})
        self.assertTrue(all('Gender' not in c['features'] for c in inventory['candidates']))
        live = lookup_linked_dictionary('δᾶμον')
        live['candidates'][0]['linked_path']['source_noun_metadata']['source_record_proof']['parent_sha256'] = '0' * 64
        self.assertEqual(validated_candidates({'text': 'δᾶμον', 'linked_dictionary': live}), [])
