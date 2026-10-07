"""The live probe must reject missing person and changed literal sources."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.check_machine_dictionary_live import verify_envelope


def fixture():
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/machine-subentry-word-actual.json'
    return json.loads(path.read_text(encoding='utf-8'))['machine_dictionary']


def test_full_source_bound_fixture_passes():
    expected = fixture()
    assert verify_envelope(deepcopy(expected), expected, expected['query_form'])['parse_short'].startswith('1st ')


def test_person_omission_and_source_mutation_fail():
    expected = fixture()
    changed = deepcopy(expected)
    del changed['interlinear']['readings'][0]['tokens'][0]['features']['Person']
    with pytest.raises(AssertionError):
        verify_envelope(changed, expected, expected['query_form'])
    changed = deepcopy(expected)
    changed['machine_subentry_evidence']['subentries'] = {}
    with pytest.raises(AssertionError):
        verify_envelope(changed, expected, expected['query_form'])
