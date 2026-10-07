"""No real credentials/provider: lifetime cap and preflight regressions."""
import sqlite3
from pathlib import Path
import pytest

from scripts import run_commentary_relevance as runner


class Provider:
    def __init__(self, fail=False): self.calls, self.fail = [], fail
    def decide(self, packet):
        self.calls.append(packet)
        if self.fail: raise RuntimeError('secret-error-must-not-leak')
        return {'choice': 'abstain', 'model': 'synthetic-test-only'}


@pytest.mark.parametrize('fail', [False, True])
def test_lifetime_batch_never_retries_or_resumes(tmp_path, fail):
    provider = Provider(fail)
    kwargs = dict(ledger_path=tmp_path/'attempts.sqlite', output=tmp_path, manifest_sha256='synthetic')
    pending = [(0, {'test': 0}), (2, {'test': 2})]
    if fail:
        with pytest.raises(RuntimeError, match='Experiment stopped') as error:
            runner.execute_reserved(provider, pending, **kwargs)
        assert 'secret-error' not in str(error.value)
        assert len(provider.calls) == 1
    else:
        runner.execute_reserved(provider, pending, **kwargs)
        assert len(provider.calls) == 2
    with sqlite3.connect(kwargs['ledger_path']) as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 2
    count = len(provider.calls)
    with pytest.raises(ValueError, match='already reserved'):
        runner.execute_reserved(provider, pending, **kwargs)
    assert len(provider.calls) == count


def test_wrong_approvals_fail_without_network_or_ledger():
    with pytest.raises(ValueError, match='manifest approval'):
        runner.verified_inputs('wrong', 'wrong')
    with pytest.raises(ValueError, match='runner approval'):
        runner.verified_inputs(runner.MANIFEST_SHA256, 'wrong')


def test_actual_frozen_preflight_is_offline_and_exact():
    manifest, pending = runner.verified_inputs(runner.MANIFEST_SHA256, runner.sha(Path(runner.__file__).read_bytes()))
    assert [case for case, _ in pending] == [0, 2]
    assert manifest['model'] == 'jev-1.13.0'
