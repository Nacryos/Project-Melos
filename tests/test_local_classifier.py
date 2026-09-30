"""Safety checks for the local provider's bounded interface."""

import pytest

from backend.local_classifier import _parse_choice, local_model_status


def test_local_status_does_not_load_model():
    status = local_model_status()
    assert status["model"].startswith("Qwen/Qwen3-1.7B@")
    assert status["license"] == "Apache-2.0"
    assert status["loaded"] is False
    assert status["validated"] is False
    assert status["recommended"] is False


@pytest.mark.parametrize("output,expected", [
    ('{"choice":"candidate-a"}', "candidate-a"),
    ('{"choice":"abstain"}', "abstain"),
    ('```json\n{"choice":"candidate-a"}\n```', "candidate-a"),
])
def test_choice_is_bounded_to_supplied_ids(output, expected):
    assert _parse_choice(output, {"candidate-a"}) == expected


@pytest.mark.parametrize("output", [
    "candidate-a", '{"choice":"invented"}', '{"choice":17}',
    '{"candidate_id":"candidate-a"}',
])
def test_unknown_or_malformed_choice_is_rejected(output):
    with pytest.raises(RuntimeError):
        _parse_choice(output, {"candidate-a"})
