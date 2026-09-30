"""Synthetic source-locator mechanics; no authored corpus or citation claims."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unicodedata

from backend.morphology import Morphology


class InventoryLocationTests(unittest.TestCase):
    def service(self, rows):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        path = root / 'forms.jsonl'
        with path.open('w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        return Morphology(root / 'missing-entries', path)

    def row(self, **fields):
        row = {'form': 'αβγ', 'lemma': 'αβδ', 'lemma_raw': 'αβδ1',
               'analysis': 'n-s---mn-', 'source': 'Synthetic fixture',
               'source_url': 'https://example.test/source.xml', 'quality': 'fixture',
               'document_id': 'urn:fixture:document', 'sentence_id': '1', 'token_id': '2',
               'citation': 'urn:fixture:document:1.2', 'raw_path': 'private/raw/source.xml'}
        row.update(fields)
        return row

    def refs(self, service):
        return service.analyze('αβγ')['observed_form_groups'][0]['forms'][0]['source_refs']

    def test_later_locations_survive_source_reading_deduplication(self):
        service = self.service([self.row(), self.row(sentence_id='3', token_id='4', citation='')])
        result = service.analyze('αβγ')
        self.assertEqual(len(result['candidates']), 1)
        ref = self.refs(service)[0]
        self.assertEqual(ref['location_total'], 2)
        self.assertEqual(ref['locations_shown'], 2)
        self.assertFalse(ref['locations_truncated'])
        self.assertEqual(ref['locations'][0]['citation'], 'urn:fixture:document:1.2')
        self.assertEqual(ref['locations'][1], {'citation': None, 'document_id': 'urn:fixture:document',
                                              'sentence_id': '3', 'token_id': '4'})
        self.assertNotIn('private/raw', json.dumps(result))
        self.assertFalse(any(key.startswith('_location') for candidate in result['candidates'] for key in candidate))

    def test_exact_duplicate_records_do_not_inflate_counts(self):
        ref = self.refs(self.service([self.row(), self.row(), self.row()]))[0]
        self.assertEqual(ref['location_total'], 1)

    def test_source_metadata_variants_keep_locations_without_changing_candidates(self):
        for field in ('quality', 'license', 'analysis_format'):
            with self.subTest(field=field):
                original = self.row()
                variant = self.row(sentence_id='3', token_id='4', **{field: 'alternative metadata'})
                baseline = self.service([original]).analyze('αβγ')
                result = self.service([original, variant]).analyze('αβγ')
                self.assertEqual(result['candidates'], baseline['candidates'])
                refs = result['observed_form_groups'][0]['forms'][0]['source_refs']
                self.assertEqual(len(refs), 2)
                self.assertEqual({location['sentence_id'] for ref in refs for location in ref['locations']}, {'1', '3'})
                self.assertTrue(all(ref['location_total'] == 1 for ref in refs))

    def test_citation_aliases_are_preserved_not_counted_as_unique_occurrences(self):
        ref = self.refs(self.service([self.row(), self.row(citation='urn:fixture:alternative:1.2')]))[0]
        self.assertEqual(ref['location_total'], 2)
        self.assertEqual({item['citation'] for item in ref['locations']},
                         {'urn:fixture:document:1.2', 'urn:fixture:alternative:1.2'})
        self.assertEqual({item['token_id'] for item in ref['locations']}, {'2'})

    def test_entirely_missing_location_is_not_an_occurrence(self):
        ref = self.refs(self.service([self.row(citation='', document_id=None, sentence_id='', token_id=None)]))[0]
        self.assertEqual(ref['locations'], [])
        self.assertEqual(ref['location_total'], 0)

    def test_partial_locations_are_explicitly_partial(self):
        ref = self.refs(self.service([self.row(citation='', document_id='urn:fixture:only-document',
                                               sentence_id='', token_id='')]))[0]
        self.assertEqual(ref['locations'], [{'citation': None, 'document_id': 'urn:fixture:only-document',
                                            'sentence_id': None, 'token_id': None}])

    def test_source_and_homograph_locations_do_not_cross_contaminate(self):
        result = self.service([
            self.row(), self.row(lemma_raw='αβδ2', sentence_id='22', citation=''),
            self.row(source='Other fixture', sentence_id='33', citation=''),
            self.row(source_url='https://example.test/other.xml', sentence_id='44', citation=''),
        ]).analyze('αβγ')
        for group in result['observed_form_groups']:
            refs = group['forms'][0]['source_refs']
            sentences = {location['sentence_id'] for ref in refs for location in ref['locations']}
            if group['source'] == 'Other fixture':
                self.assertEqual(sentences, {'33'})
            elif group['lemma_raw'] == 'αβδ2':
                self.assertEqual(sentences, {'22'})
            else:
                self.assertEqual(sentences, {'1', '44'})
                self.assertEqual(len(refs), 2)

    def test_nfc_equivalent_rows_share_complete_reference_location_totals(self):
        result = self.service([
            self.row(lemma='άβδ', lemma_raw='άβδ1'),
            self.row(lemma=unicodedata.normalize('NFD', 'άβδ'),
                     lemma_raw=unicodedata.normalize('NFD', 'άβδ1'), sentence_id='3'),
        ]).analyze('αβγ')
        refs = result['observed_form_groups'][0]['forms'][0]['source_refs']
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['location_total'], 2)

    def test_truncation_counts_all_locations_and_is_order_independent(self):
        rows = [self.row(citation='', sentence_id=str(i), token_id='1') for i in range(27)]
        rows.extend([self.row(), self.row()])
        a = self.refs(self.service(rows))[0]
        b = self.refs(self.service(list(reversed(rows))))[0]
        self.assertEqual(a, b)
        self.assertEqual(a['location_total'], 28)
        self.assertEqual(a['locations_shown'], 20)
        self.assertTrue(a['locations_truncated'])
        self.assertEqual(a['locations'][0]['citation'], 'urn:fixture:document:1.2')


if __name__ == '__main__':
    unittest.main()
