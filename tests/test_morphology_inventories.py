"""Synthetic inventory mechanics, not authored corpus or philological truth."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unicodedata

from backend.morphology import Morphology


class ObservedFormInventoryTests(unittest.TestCase):
    def service(self, rows, entries=()):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, values in [('forms', rows), ('entries', entries)]:
            with (root / (name + '.jsonl')).open('w', encoding='utf-8') as handle:
                for value in values:
                    handle.write(json.dumps(value, ensure_ascii=False) + '\n')
        return Morphology(root / 'entries.jsonl', root / 'forms.jsonl')

    def row(self, form='αβγ', lemma='αβδ', raw=None, source='Fixture treebank', url=None):
        return {'form': form, 'lemma': lemma, 'lemma_raw': raw or lemma,
                'analysis': 'n-s---mn-', 'source': source,
                'source_url': url or 'https://example.test/form/' + form,
                'license': 'fixture', 'quality': 'fixture'}

    def test_fuzzy_forms_are_scoped_suggestions_not_query_inventory(self):
        result = self.service([self.row(), self.row('αβδε')]).analyze('αβχ')
        self.assertEqual(result['attested_forms'], [])
        self.assertTrue(result['observed_form_groups'])
        group = result['observed_form_groups'][0]
        self.assertEqual(group['query_relation'], 'spelling_suggestion')
        self.assertTrue(all(match['edit_distance'] > 0 for match in group['matches']))
        self.assertEqual({item['form'] for item in group['forms']}, {'αβγ', 'αβδε'})
        self.assertFalse(group['complete_paradigm'])
        self.assertEqual(group['scope'], 'whole_imported_index')

    def test_exact_unambiguous_legacy_inventory_retained_with_form_provenance(self):
        result = self.service([self.row(), self.row('αβδε')], [{
            'lemma': 'αβδ', 'source': 'Fixture dictionary',
            'source_url': 'https://example.test/dictionary', 'gloss': 'fixture',
        }]).analyze('αβγ')
        self.assertEqual(result['attested_forms'], ['αβγ', 'αβδε'])
        group = result['observed_form_groups'][0]
        self.assertEqual(group['query_relation'], 'exact_or_folded_match')
        self.assertEqual(group['total_forms'], 2)
        self.assertEqual(group['shown_forms'], 2)
        self.assertFalse(group['truncated'])
        for item in group['forms']:
            self.assertEqual(item['source_refs'][0]['source_url'],
                             'https://example.test/form/' + item['form'])
            self.assertNotIn('dictionary', item['source_refs'][0]['source_url'])

    def test_accent_distinct_lemmas_are_not_pooled(self):
        result = self.service([
            self.row(lemma='άβδ'), self.row('άβδη', lemma='άβδ'),
            self.row(lemma='αβδ'), self.row('αβδη', lemma='αβδ'),
        ]).analyze('αβγ')
        groups = {group['lemma']: group for group in result['observed_form_groups']}
        self.assertEqual(set(groups), {'άβδ', 'αβδ'})
        self.assertEqual({item['form'] for item in groups['άβδ']['forms']}, {'αβγ', 'άβδη'})
        self.assertEqual({item['form'] for item in groups['αβδ']['forms']}, {'αβγ', 'αβδη'})
        self.assertEqual(result['attested_forms'], [])

    def test_numbered_and_unnumbered_homographs_remain_separate(self):
        result = self.service([
            self.row(raw='αβδ1'), self.row('αβδε', raw='αβδ1'),
            self.row(raw='αβδ2'), self.row('αβδη', raw='αβδ2'),
            self.row(), self.row('αβδθ'),
        ]).analyze('αβγ')
        groups = {group['lemma_raw']: group for group in result['observed_form_groups']}
        self.assertEqual(set(groups), {'αβδ', 'αβδ1', 'αβδ2'})
        self.assertEqual({item['form'] for item in groups['αβδ1']['forms']}, {'αβγ', 'αβδε'})
        self.assertEqual({item['form'] for item in groups['αβδ2']['forms']}, {'αβγ', 'αβδη'})
        self.assertEqual({item['form'] for item in groups['αβδ']['forms']}, {'αβγ', 'αβδθ'})
        self.assertEqual(groups['αβδ']['identity_status'], 'unnumbered_homograph_ambiguous')
        self.assertEqual(result['attested_forms'], [])

    def test_source_local_homograph_numbers_are_not_cross_source_identities(self):
        result = self.service([
            self.row(raw='αβδ1', source='Source A'), self.row('αβδε', raw='αβδ1', source='Source A'),
            self.row(raw='αβδ1', source='Source B'), self.row('αβδη', raw='αβδ1', source='Source B'),
        ]).analyze('αβγ')
        groups = {group['source']: group for group in result['observed_form_groups']}
        self.assertEqual(len(groups), 2)
        self.assertNotIn('αβδη', {item['form'] for item in groups['Source A']['forms']})
        self.assertEqual(result['attested_forms'], [])

    def test_display_limit_does_not_hide_query_ambiguity(self):
        result = self.service([self.row(), self.row(lemma='ζ')]).analyze('αβγ', limit=1)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['attested_forms'], [])
        self.assertTrue(result['observed_form_groups'][0]['query_lemma_ambiguous'])

    def test_flattened_candidate_sources_do_not_create_raw_source_cross_product(self):
        result = self.service([
            self.row(raw='αβδ1', source='Source A'),
            self.row(source='Source B'),
            # Same numbered lemma exists in B, but does not analyze this query.
            self.row('αβδε', raw='αβδ1', source='Source B'),
        ]).analyze('αβγ')
        identities = {(group['lemma_raw'], group['source'])
                      for group in result['observed_form_groups']}
        self.assertEqual(identities, {('αβδ1', 'Source A'), ('αβδ', 'Source B')})
        self.assertTrue(all('_inventory_identity_keys' not in candidate
                            for candidate in result['candidates']))

    def test_matched_spelling_metadata_stays_with_its_source_identity(self):
        result = self.service([
            self.row('άβγ', source='Source A'), self.row('αβγ', source='Source B'),
        ]).analyze('αβγ')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(set(result['candidates'][0]['matched_form_variants']), {'άβγ', 'αβγ'})
        groups = {group['source']: group for group in result['observed_form_groups']}
        for source, spelling in [('Source A', 'άβγ'), ('Source B', 'αβγ')]:
            self.assertEqual(groups[source]['matches'][0]['matched_form'], spelling)
            self.assertEqual(groups[source]['matches'][0]['matched_form_variants'], [spelling])
        self.assertTrue(all(not key.startswith('_inventory_')
                            for candidate in result['candidates'] for key in candidate))

    def test_fuzzy_match_distance_stays_with_actual_source_spelling(self):
        result = self.service([
            self.row('αβγδεζ', source='Source A'),
            self.row('αβγδζθ', source='Source B'),
        ]).analyze('αβγδεη')
        self.assertEqual(len(result['candidates']), 1)
        groups = {group['source']: group for group in result['observed_form_groups']}
        self.assertEqual(groups['Source A']['matches'][0]['edit_distance'], 1)
        # Two substitutions for B; A's one-edit candidate score must not leak.
        self.assertEqual(groups['Source B']['matches'][0]['edit_distance'], 2)

    def test_nfc_equivalence_is_not_false_homography(self):
        result = self.service([
            self.row(lemma='άβδ'),
            self.row('αβδε', lemma=unicodedata.normalize('NFD', 'άβδ')),
        ]).analyze('αβγ')
        self.assertEqual(len(result['observed_form_groups']), 1)
        self.assertEqual(result['observed_form_groups'][0]['total_forms'], 2)

    def test_truncation_counts_and_selection_are_deterministic(self):
        # Synthetic alphabetic suffixes avoid corpus assertions and folded
        # numeric suffix collisions in the fixture form keys.
        rows = [self.row('αβ' + chr(0x3b1 + i // 20) + chr(0x3b1 + i % 20)) for i in range(63)]
        rows.extend(self.row(url='https://example.test/ref/' + str(i)) for i in range(15))
        first = self.service(rows).analyze('αβγ')
        second = self.service(list(reversed(rows))).analyze('αβγ')
        a, b = first['observed_form_groups'][0], second['observed_form_groups'][0]
        self.assertEqual(a['forms'], b['forms'])
        self.assertEqual(a['total_forms'], 64)
        self.assertEqual(a['shown_forms'], 50)
        self.assertTrue(a['truncated'])
        item = next(item for item in a['forms'] if item['form'] == 'αβγ')
        self.assertEqual(item['source_ref_total'], 15)
        self.assertEqual(item['source_refs_shown'], 10)
        self.assertTrue(item['source_refs_truncated'])
        self.assertEqual(first['attested_forms_total'], 64)


if __name__ == '__main__':
    unittest.main()
