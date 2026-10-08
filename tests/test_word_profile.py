"""Diagnostic selection and outbound-network guard, not lexical assertions."""
import cProfile
import json
from pathlib import Path
import socket
from unittest.mock import patch

import pytest

from scripts.profile_word_lookup import forbid_network, select_forms, top_stats


def test_actual_approved_source_forms_are_bounded_unique_and_unmodified():
    artifact = Path(__file__).resolve().parents[1] / 'data/campbell_glp/alcaeus_five_corrected.jsonl'
    for line in artifact.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        result = select_forms(record, 5)
        assert 0 < len(result) <= 5
        assert len(result) == len(set(result))
        assert all(form in record['text'] for form in result)


def test_missing_or_invalid_source_boundaries_are_not_replaced_with_whole_text():
    for metadata in ({}, {'verse_segments': [{'start_line_index': 0, 'end_line_index_exclusive': 99}]}):
        with pytest.raises(ValueError):
            select_forms({'text': 'synthetic', 'metadata': metadata}, 5)


def test_diagnostic_does_not_call_dot_adjacent_letters_intact():
    artifact = Path(__file__).resolve().parents[1] / 'data/campbell_glp/alcaeus_five_corrected.jsonl'
    record = next(json.loads(line) for line in artifact.read_text(encoding='utf-8').splitlines()
                  if json.loads(line)['id'] == 'campbell-glp:alcaeus:130b')
    # This exact surviving suffix is in the source; its word boundary is not
    # established. Exclusion does not assert a restoration or lexical identity.
    assert record['text'][27:29] == 'ις'
    assert 'ις' not in select_forms(record, 5)


def test_socket_guard_prevents_any_connection_without_resolving_destination():
    with patch.object(socket.socket, 'connect', forbid_network), patch.object(socket.socket, 'connect_ex', forbid_network):
        with socket.socket() as connection:
            for method in (connection.connect, connection.connect_ex):
                with pytest.raises(RuntimeError, match='network is disabled'):
                    method(('example.invalid', 1))


def test_profile_summary_is_bounded_and_contains_no_source_contents():
    profiler = cProfile.Profile()
    profiler.runcall(sum, [1, 2, 3])
    rows = top_stats(profiler, 2)
    assert 0 < len(rows) <= 2
    assert all(set(row) == {'file', 'line', 'function', 'primitive_calls', 'total_calls',
                           'own_seconds', 'cumulative_seconds'} for row in rows)
