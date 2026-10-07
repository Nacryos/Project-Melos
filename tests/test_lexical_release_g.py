"""Prospective G scope and baseline guards, offline only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_g as tool
import lexical_release_f as previous
import lexical_transport_g as transport
import lexical_transport_f as previous_transport
import lexical_baseline_g as baseline


class ReleaseGTests(unittest.TestCase):
    def test_exact_scope(self):
        self.assertEqual(len(tool.MODULES), 10)
        self.assertEqual(tool.NEW_MODULES, baseline.NEW_FILES)
        self.assertEqual(tool.BASELINE_MODULES, baseline.FILES)
        self.assertIn('interlinear.py', tool.MODULES)
        self.assertNotIn('morphology.py', tool.MODULES)
        self.assertNotIn('translation_comparisons_data.json', tool.MODULES)

    def test_identity_and_immutable_previous(self):
        self.assertEqual(tool.BASE_CONTAINER, baseline.BASE_CONTAINER)
        self.assertEqual(tool.RELEASE.name, 'lexical-20261007g')
        self.assertEqual(tool.CANARY, 'melos-api-lexical-canary-g')
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007g')
        self.assertEqual(previous.RELEASE.name, 'lexical-20261007f')
        self.assertEqual(previous_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007f')

    def test_exact_f_mounts_and_preserved_sidecars(self):
        mounts = {row[0]: row for row in tool.base_mounts()}
        self.assertEqual(len(mounts), 23)
        for name in previous.MODULES:
            self.assertIn('lexical-20261007f', mounts['/app/backend/' + name][1])
        self.assertIn('lexical-20261007e', mounts['/app/backend/edition_commentary_data.json'][1])
        self.assertIn('campbell-20261007b', mounts['/app/data/corpus.sqlite'][1])
        self.assertTrue(mounts['/app/runtime'][2])
        self.assertFalse(mounts['/run/secrets/jev.env'][2])

    def test_private_runtime_does_not_mutate_saved_baseline(self):
        old = {'HostConfig': {'Binds': [str(tool.core.guard.ROOT / 'runtime') + ':/app/runtime:rw', '/x:/app/data:ro']}}
        receipt = {'verdict': 'PASS', 'base_container_id': tool.BASE_CONTAINER,
                   'path': str(tool.PRIVATE_RUNTIME), 'backup_method': 'sqlite_backup_api',
                   'databases': {'classifier.sqlite': {}, 'machine_morphology.sqlite': {}}}
        with patch.object(Path, 'read_text', return_value=json.dumps(receipt)):
            candidate = tool.private_baseline(old)
        self.assertNotEqual(candidate, old)
        self.assertNotIn('canary-runtime', old['HostConfig']['Binds'][0])
        self.assertIn('canary-runtime', candidate['HostConfig']['Binds'][0])
        self.assertEqual(candidate['HostConfig']['Binds'][1], old['HostConfig']['Binds'][1])

    def test_production_start_does_not_use_private_runtime(self):
        old = {'sentinel': True}
        with patch.object(tool, 'private_baseline', side_effect=AssertionError('private forbidden')):
            with patch.object(tool, '_original_start') as start:
                tool.start(tool.BASE, 'melos-api', 8791, old)
                start.assert_called_once_with(tool.BASE, 'melos-api', 8791, old)


if __name__ == '__main__':
    unittest.main()
