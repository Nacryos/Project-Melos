"""D target isolation tests. No remote access or scholarly data."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import lexical_release_d as tool
import lexical_release_c as prior
import lexical_transport_d as transport
import lexical_transport_c as prior_transport
import stage_lexical_d as stage


class ReleaseDTests(unittest.TestCase):
    def test_d_targets_are_new(self):
        self.assertEqual(tool.RELEASE.name, 'lexical-20261007d')
        self.assertEqual(tool.core.RELEASE, tool.RELEASE)
        self.assertEqual(tool.core.guard.RELEASE, tool.RELEASE)
        self.assertEqual(tool.core.guard.CANARY, 'melos-api-lexical-canary-d')
        self.assertEqual(tool.core.guard.OLD, 'melos-api-before-lexical-20261007d')

    def test_independent_c_module_unchanged(self):
        self.assertEqual(prior.RELEASE.name, 'lexical-20261007c')
        self.assertEqual(prior.guard.RELEASE, prior.RELEASE)
        self.assertEqual(prior.CANARY, 'melos-api-lexical-canary-c')

    def test_b_baseline_and_modules_unchanged(self):
        self.assertEqual(tool.BASE_CONTAINER, prior.BASE_CONTAINER)
        self.assertEqual(tool.MODULES, prior.MODULES)
        self.assertEqual(tool.core.base_mounts(), prior.base_mounts())

    def test_d_remote_is_posix(self):
        self.assertEqual(transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007d')
        self.assertEqual(prior_transport.REMOTE, '/home/alvin/services/melos/releases/lexical-20261007c')

    def test_d_stage_is_not_c(self):
        self.assertNotEqual(stage.OUTPUT.parent, stage.C_CODE.parent)
        self.assertEqual(stage.C_CODE.parent.name, 'lexical-release-c')

    def test_missing_interlinear_freeze_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Frozen interlinear'):
            stage.stage('not-ready')


if __name__ == '__main__':
    unittest.main()
