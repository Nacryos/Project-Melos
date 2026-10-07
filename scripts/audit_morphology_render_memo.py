"""Offline, source-bound replay of request-local morphology rendering memo.

Build an in-memory copy of the current module with only the memo removed,
then compare complete /word results on five words printed in Campbell 130b.
No source files, corpus rows, network endpoint, or model state are changed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import types
from unittest.mock import patch

from backend import morphology, server
from backend.lexicon_render import render_source_record
from scripts.profile_word_lookup import select_forms


PASSAGE_ID = 'campbell-glp:alcaeus:130b'
PASSAGE_SHA256 = 'dd1402e22bd6b4f9f7397c92510b66ab5ab8acad66605d07e4f8d1a622ca7a32'
PASSAGE_PATH = Path('runtime/campbell-assignment/campbell_assignment.jsonl')
CURRENT_MODULE_SHA256 = '4baaaf0b276b3f2d02305ee767f9c62a46d2db9cb235a8dc78c0e6949ad8f4a1'
DECLARATION = '        rendered_sources: dict[int, dict[str, Any]] = {}\n'
MEMO = '''                    source_identity = id(entry)
                    if source_identity not in rendered_sources:
                        rendered_sources[source_identity] = render_source_record(entry)
                    display_entry.update(rendered_sources[source_identity])'''
UNMEMOED = '                    display_entry.update(render_source_record(entry))'


def no_network(*_args, **_kwargs):
    raise RuntimeError('Network disabled during render-memo audit.')


def compact_sha(value):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return len(body), hashlib.sha256(body).hexdigest()


def main():
    path = Path(morphology.__file__)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CURRENT_MODULE_SHA256
    source = raw.decode('utf-8')
    assert source.count(DECLARATION) == source.count(MEMO) == 1
    baseline_source = source.replace(DECLARATION, '').replace(MEMO, UNMEMOED)
    baseline = types.ModuleType('backend._morphology_render_unmemoed')
    baseline.__package__ = 'backend'
    baseline.__file__ = str(path)
    exec(compile(baseline_source, str(path), 'exec'), baseline.__dict__)

    with patch.object(socket.socket, 'connect', no_network), \
            patch.object(socket.socket, 'connect_ex', no_network):
        passage = next((json.loads(line) for line in PASSAGE_PATH.read_text(encoding='utf-8').splitlines()
                        if json.loads(line).get('id') == PASSAGE_ID), None)
        assert passage is not None
        assert hashlib.sha256(passage['text'].encode()).hexdigest() == PASSAGE_SHA256
        forms = select_forms(passage, 5)
        assert len(forms) == 5
        results = []
        for form in forms:
            calls = {'baseline': [], 'memo': []}
            active = 'baseline'

            def counted(entry):
                calls[active].append((id(entry), str(entry.get('id'))))
                return render_source_record(entry)

            with patch('backend.lexicon_render.render_source_record', side_effect=counted):
                with patch.object(morphology.Morphology, 'analyze', baseline.Morphology.analyze):
                    old = server.word(form, '')
                active = 'memo'
                new = server.word(form, '')
            old_bytes, old_sha = compact_sha(old)
            new_bytes, new_sha = compact_sha(new)
            assert old == new and old_bytes == new_bytes and old_sha == new_sha
            assert len(calls['memo']) == len(set(identity for identity, _ in calls['memo']))
            results.append({'form': form, 'response_bytes': new_bytes,
                            'response_sha256': new_sha,
                            'render_calls_without_memo': len(calls['baseline']),
                            'render_calls_with_memo': len(calls['memo']),
                            'unique_source_objects': len(set(identity for identity, _ in calls['baseline']))})
    print(json.dumps({'schema': 'melos-render-memo-replay-v1',
                      'source_passage_id': PASSAGE_ID, 'source_text_sha256': PASSAGE_SHA256,
                      'word_context': 'no passage_id because local active corpus lacks approved Campbell record',
                      'module_sha256': CURRENT_MODULE_SHA256,
                      'baseline': 'in-memory current module with only request-local memo removed',
                      'forms': results,
                      'total_render_calls_without_memo': sum(r['render_calls_without_memo'] for r in results),
                      'total_render_calls_with_memo': sum(r['render_calls_with_memo'] for r in results),
                      'full_response_equal': True,
                      'network_calls': 0, 'model_calls': 0}, ensure_ascii=True))


if __name__ == '__main__':
    main()
