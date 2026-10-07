"""Bounded J code/index/environment overrides without changing prior releases."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_j as tool
import lexical_release_i as previous
import lexical_transport_j as transport
import lexical_transport_i as previous_transport


class ReleaseJTests(unittest.TestCase):
    def test_exact_scope(self):
        self.assertEqual(tool.MODULES, {'server.py', 'passage_routes.py', 'passage_analysis.py', 'interlinear.py',
                                      'machine_subentries.py', 'lexicon_subentries.py', 'morphology.py'})
        self.assertEqual(tool.NEW_MODULES, {'machine_subentries.py', 'lexicon_subentries.py'})
        self.assertIn('sense_ranker.py', tool.BASELINE_MODULES - tool.MODULES)
        self.assertNotIn('commentary_retrieval.py', tool.MODULES)

    def test_prior_configuration_unchanged(self):
        self.assertEqual(previous.RELEASE.name, 'lexical-20261007i')
        self.assertEqual(previous_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007i')
        self.assertEqual(len(tool.base_mounts()), 28)

    def test_only_four_settings_and_no_original_mutation(self):
        old = {'Config': {'Env': ['EXAMPLE=unchanged', 'MELOS_PUBLICATION_POLICY=source-labels']}}
        changed = tool.configured(old)
        self.assertEqual(old['Config']['Env'], ['EXAMPLE=unchanged', 'MELOS_PUBLICATION_POLICY=source-labels'])
        actual = dict(row.split('=', 1) for row in changed['Config']['Env'])
        self.assertEqual(actual, {'EXAMPLE': 'unchanged', 'MELOS_PUBLICATION_POLICY': 'source-labels', **tool.CONFIG})
        self.assertEqual(len(tool.CONFIG), 4)

    def test_index_mount_readonly_and_collision_rejected(self):
        with patch.object(tool, '_binds', return_value=['/source:/app/data:ro']):
            result = tool.expected_binds({})
            self.assertEqual(result[0], '/source:/app/data:ro')
            self.assertTrue(result[1].endswith(':' + tool.INDEX_DEST + ':ro'))
        with patch.object(tool, '_binds', return_value=['/other:' + tool.INDEX_DEST + ':ro']):
            with self.assertRaises(RuntimeError):
                tool.expected_binds({})

    def test_unrelated_upload_rejected_before_connection(self):
        with self.assertRaises(ValueError):
            transport.upload_new(None, None, 'candidate-code/sense_ranker.py')


if __name__ == '__main__':
    unittest.main()
