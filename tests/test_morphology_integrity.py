"""Synthetic mechanics fixtures; no philological assertions or corpus writes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.morphology import Morphology


class MorphologyIntegrityTests(unittest.TestCase):
    def service(self, forms, entries=()):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        for filename, rows in [('forms', forms), ('entries', entries)]:
            with (root / (filename + '.jsonl')).open('w', encoding='utf-8') as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        return Morphology(root / 'entries.jsonl', root / 'forms.jsonl')

    def row(self, form, lemma, analysis='n-s---mn-', suffix='one'):
        return {'form': form, 'lemma': lemma, 'analysis': analysis,
                'source_url': 'https://example.test/fixture/' + suffix}

    def test_conflicting_links_are_preserved_but_not_expanded(self):
        service = self.service([
            self.row('αβγ', 'αβδ', 'v3spia---'),
            self.row('αβγ', 'ζ', 'p-s---md-', 'two'),
            self.row('ζη', 'ζ'),
            self.row('αβδε', 'αβδ'),
        ])
        result = service.analyze('αβγ')
        self.assertEqual({c['lemma'] for c in result['candidates']}, {'αβδ', 'ζ'})
        self.assertEqual(result['expansion_lemmas'], [])
        self.assertTrue(all(not c['automatic_expansion_eligible'] for c in result['candidates']))
        self.assertTrue(all(c['source_url'] for c in result['candidates']))
        self.assertTrue(any('legitimate homography or a source error' in w for w in result['warnings']))
        self.assertEqual(service.forms_for_lemma('ζ'), ['αβγ', 'ζη'])
        self.assertEqual(service.expansion_forms_for_lemma('ζ'), ['ζη'])

    def test_multiple_parses_of_one_lemma_are_not_conflicts(self):
        service = self.service([
            self.row('αβγ', 'αβδ', 'n-s---mn-'),
            self.row('αβγ', 'αβδ', 'n-s---ma-', 'two'),
        ])
        result = service.analyze('αβγ')
        self.assertEqual(result['expansion_lemmas'], ['αβδ'])
        self.assertEqual(len(result['candidates']), 2)
        self.assertTrue(all(c['automatic_expansion_eligible'] for c in result['candidates']))

    def test_legitimate_homography_is_not_declared_invalid(self):
        service = self.service([
            self.row('αβγ', 'αβδ'), self.row('αβγ', 'αβε', suffix='two'),
            self.row('αβδη', 'αβδ'),
        ], [{'lemma': 'αβδ', 'source_url': 'https://example.test/headword'}])
        result = service.analyze('αβγ')
        self.assertEqual(len(result['candidates']), 2)
        self.assertTrue(all(c['lemma_link_status'] == 'ambiguous_source_lemmas'
                            for c in result['candidates']))
        self.assertEqual(service.expansion_lemmas_for_form('αβδ'), ['αβδ'])
        self.assertEqual(service.expansion_forms_for_lemma('αβδ'), ['αβδη'])

    def test_truncated_candidates_do_not_hide_conflict(self):
        service = self.service([
            self.row('αβγ', 'αβδ'), self.row('αβγ', 'ζ', suffix='two'),
        ])
        result = service.analyze('αβγ', limit=1)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['expansion_lemmas'], [])
        self.assertFalse(result['candidates'][0]['automatic_expansion_eligible'])

    def test_fuzzy_suggestions_never_drive_query_expansion(self):
        service = self.service([self.row('αβγ', 'αβδ')])
        result = service.analyze('αβχ')
        self.assertTrue(result['candidates'])
        self.assertEqual(result['expansion_lemmas'], [])
        self.assertFalse(result['candidates'][0]['automatic_expansion_eligible'])

    def test_diacritic_folded_conflict_is_not_silently_resolved(self):
        service = self.service([
            self.row('άβγ', 'αβδ'), self.row('αβγ', 'ζ', suffix='two'),
        ])
        self.assertEqual(service.expansion_lemmas_for_form('άβγ'), [])
        self.assertEqual(service.expansion_forms_for_lemma('ζ'), [])

    def test_duplicate_source_votes_do_not_resolve_conflict(self):
        rows = [self.row('αβγ', 'αβδ', suffix=str(i)) for i in range(20)]
        rows.append(self.row('αβγ', 'ζ', suffix='other'))
        service = self.service(rows)
        self.assertEqual(service.expansion_lemmas_for_form('αβγ'), [])


if __name__ == '__main__':
    unittest.main()
