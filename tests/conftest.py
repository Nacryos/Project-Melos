import platform

import pytest

# Windows: platform.win32_ver() can deadlock inside WMI under pytest.
platform._wmi = None


@pytest.fixture(autouse=True)
def _clear_morphology_precedents():
    """Readings settled in one test must not bias the fixtures of another."""
    from backend import interlinear
    interlinear._PRECEDENTS.clear()
    yield
    interlinear._PRECEDENTS.clear()
