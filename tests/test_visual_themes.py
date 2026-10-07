import json
import sqlite3

import pytest

from backend.visual_themes import annotation_for, source_identity, text_sha256
from scripts.audit_visual_annotations import audit
from scripts.build_visual_annotations import build, validate_decision


def source(record_id='p:1', text='κύματα καὶ θάλασσα', citation='1.1'):
    return {'id': record_id, 'text': text, 'author': 'Pindar', 'work_id': 'w',
            'citation': citation, 'source': 'edition-a', 'kind': 'text',
            'language': 'grc', 'quality': 'source_text'}


def proposal(record_id='p:1', evidence=None):
    return {'id': record_id, 'status': 'label', 'reason': 'Extended sea scene in ode context.',
            'labels': [{'theme': 'sea_coast', 'kind': 'scene', 'strength': 'strong',
                        'modifiers': [], 'evidence': evidence or [{'id': record_id, 'quote': 'κύματα'}]}]}


def sidecar(tmp_path, rows):
    path = tmp_path / 'validated.json'
    path.write_text(json.dumps({'schema_version': 1, 'manifest': {}, 'records': rows}), encoding='utf-8')
    return path


def test_exact_source_and_offsets(tmp_path):
    row = source()
    valid = validate_decision(proposal(), {row['id']: row})
    span = valid['labels'][0]['evidence'][0]
    assert row['text'][span['start']:span['end']] == 'κύματα'
    path = sidecar(tmp_path, [valid])
    assert annotation_for(row, path=path)['themes'] == ['sea_coast']
    assert annotation_for(row | {'text': row['text'] + ' changed'}, path=path) is None
    assert annotation_for(row | {'id': 'different-edition'}, path=path) is None


def test_nonliteral_or_unrelated_context_is_rejected():
    row, other = source(), source('p:2', citation='2.1')
    with pytest.raises(ValueError, match='Nonliteral'):
        validate_decision(proposal(evidence=[{'id': row['id'], 'quote': 'κῦματα'}]), {row['id']: row})
    with pytest.raises(ValueError, match='Unrelated'):
        validate_decision(proposal(evidence=[{'id': row['id'], 'quote': 'κύματα'},
            {'id': other['id'], 'quote': 'κύματα'}]), {row['id']: row, other['id']: other})


def test_scene_context_is_bound_to_edition_and_current_source(tmp_path):
    row, other = source(), source('p:2', 'ἀνέμων πνοαί', '1.2')
    evidence = [{'id': row['id'], 'quote': 'κύματα'}, {'id': other['id'], 'quote': other['text']}]
    sources = {row['id']: row, other['id']: other}
    valid = validate_decision(proposal(evidence=evidence), sources)
    path = sidecar(tmp_path, [valid])
    assert annotation_for(row, sources.get, path)['themes'] == ['sea_coast']
    sources[other['id']] = other | {'work_id': 'unrelated', 'citation': '2.1', 'source': 'edition-b'}
    assert annotation_for(row, sources.get, path) is None
    sources[other['id']] = other
    assert annotation_for(row, path=path) is None
    sources[other['id']] = other | {'text': 'new'}
    assert annotation_for(row, sources.get, path) is None
    with pytest.raises(ValueError, match='Unrelated'):
        validate_decision(proposal(evidence=evidence), {row['id']: row, other['id']: other | {'source': 'edition-b'}})


def test_translation_requires_actual_parent_and_parent_hash(tmp_path):
    greek = source()
    valid = validate_decision(proposal(), {greek['id']: greek})
    translated = {'id': 't:1', 'kind': 'translation', 'language': 'en', 'quality': 'source_text',
                  'text': 'waves and sea', 'parent_id': greek['id']}
    inherited = valid | {'id': translated['id'], 'source_text_sha256': text_sha256(translated['text']),
                         'source_identity': source_identity(translated),
                         'parent_source_identity': source_identity(greek),
                         'parent_id': greek['id'], 'parent_text_sha256': valid['source_text_sha256']}
    path = sidecar(tmp_path, [valid, inherited])
    assert annotation_for(translated, {greek['id']: greek}.get, path)['inherited_from_parent_id'] == greek['id']
    assert annotation_for(translated, path=path) is None
    assert annotation_for(translated | {'parent_id': 'guessed'}, {greek['id']: greek}.get, path) is None
    assert annotation_for(translated, {greek['id']: greek | {'text': 'changed'}}.get, path) is None


def test_abstention_is_recorded_not_exposed_as_a_theme(tmp_path):
    row = source()
    valid = validate_decision({'id': row['id'], 'status': 'abstain',
                               'reason': 'Isolated nature word only.', 'labels': []}, {row['id']: row})
    annotation = annotation_for(row, path=sidecar(tmp_path, [valid]))
    assert annotation['status'] == 'abstain'
    assert annotation['themes'] == []


@pytest.mark.parametrize('field,value', [('theme', 'love'), ('strength', 'moderate'), ('kind', 'subject')])
def test_unknown_taxonomy_is_rejected(field, value):
    raw = proposal()
    raw['labels'][0][field] = value
    with pytest.raises(ValueError):
        validate_decision(raw, {'p:1': source()})


def test_builder_requires_every_review_and_maps_only_real_parents(tmp_path):
    packet_dir, raw_dir = tmp_path / 'packets', tmp_path / 'raw'
    packet_dir.mkdir()
    raw_dir.mkdir()
    row = source()
    (packet_dir / 'packet-01.json').write_text(json.dumps([row]), encoding='utf-8')
    review = {'packet': 'packet-01', 'reviewer': 'test-reviewer', 'reviewed_all_records': True,
              'decisions': [proposal()]}
    review_path = raw_dir / 'packet-01.proposals.json'
    review_path.write_text(json.dumps(review), encoding='utf-8')
    database = tmp_path / 'corpus.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE passages (id,text,source,author_canonical,work_id,citation,language,kind,quality,data)')
        connection.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?)',
            (row['id'], row['text'], row['source'], row['author'], row['work_id'], row['citation'],
             'grc', 'text', 'source_text', json.dumps(row)))
        for record_id, parent in [('translation', row['id']), ('unlinked-translation', 'not-a-real-parent')]:
            connection.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?)',
                (record_id, 'waves', 'translation-source', 'Translator', 't', '1', 'en', 'translation', 'source_text', json.dumps({'parent_id': parent})))
    result = build(packet_dir, raw_dir, database)
    assert result['manifest']['reviewed_records'] == 1
    assert result['manifest']['mapped_translation_records'] == 1
    assert {row['id'] for row in result['records']} == {'p:1', 'translation'}
    review['decisions'] = []
    review_path.write_text(json.dumps(review), encoding='utf-8')
    with pytest.raises(ValueError, match='coverage differs'):
        build(packet_dir, raw_dir, database)
    review['decisions'] = [proposal()]
    review_path.write_text(json.dumps(review), encoding='utf-8')
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE passages SET text='changed' WHERE id='p:1'")
    with pytest.raises(ValueError, match='Frozen source changed'):
        build(packet_dir, raw_dir, database)


def test_audit_rejects_absent_or_empty_packets(tmp_path):
    result = audit(tmp_path / 'missing', tmp_path / 'raw')
    assert result['literal_validation_passed'] is False
    assert result['errors']
