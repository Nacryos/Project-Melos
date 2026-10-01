"""Synthetic boundary mechanics only: these strings are not literary evidence."""
from scripts.build_translation_pairings import boundary_proof, source_slice, build, text_hash
from scripts.build_translation_pairings import CachedSources, sha, BASE, unlineated_reading_text
import xml.etree.ElementTree as ET
import zipfile
import pytest
from scripts.ingest_perseus import passages


def record(labels, prefix='SYNTHETIC'):
    return {'lines': [{'label': label, 'text': f'{prefix} {label}'} for label in labels]}


def source(record, following=None, count=2):
    sequence = [(line['label'], line['text']) for line in record['lines']]
    if following:
        sequence.append((following, 'SYNTHETIC FOLLOWING TEXT'))
    return {'sequence': sequence, 'reading_record_count': count, 'unlineated_reading_text': False}


def test_equal_anchors_also_require_equal_successor_boundary():
    parent, tr = record(['1', '2']), record(['1', '2'], 'SYNTHETIC TRANSLATION')
    assert boundary_proof(parent, tr, source(parent, '3'), source(tr, '4')) is None
    assert boundary_proof(parent, tr, source(parent, '3'), source(tr, '3'))['method'] == 'identical_ordered_source_anchors_and_successor'


def test_complete_source_bodies_can_have_different_printed_anchor_counts():
    parent, tr = record(['1', '2', '3']), record(['1'], 'SYNTHETIC TRANSLATION')
    assert boundary_proof(parent, tr, source(parent, count=1), source(tr, count=1))['method'] == 'complete_source_bodies'
    assert boundary_proof(parent, tr, source(parent, '4', count=1), source(tr, count=1)) is None


def test_ambiguous_or_noncontiguous_source_slice_rejected():
    r = record(['1', '2']); seq = source(r)['sequence']
    assert source_slice(r, seq + seq) is None
    assert source_slice(r, [seq[0], ('extra', 'SYNTHETIC'), seq[1]]) is None


def test_first_overlap_link_and_equal_citation_are_not_proof():
    parent, tr = record(['1', '2']), record(['1', '5'])
    parent['citation'] = tr['citation'] = 'SAME SYNTHETIC LABEL'
    assert boundary_proof(parent, tr, source(parent, '3'), source(tr, '9')) is None


def test_missing_line_arrays_and_unlinked_rows_are_logged_without_source_reads():
    class NoSourceReads:
        def load(self, record):
            raise AssertionError('Unexpected source read')
    parent = {'id': 'p', 'source': 'perseus', 'kind': 'text', 'language': 'grc', 'quality': 'source_text'}
    tr = {'id': 't', 'source': 'perseus', 'kind': 'translation', 'language': 'eng', 'quality': 'source_text', 'parent_id': 'p'}
    pairs, excluded = build([parent, tr, tr | {'id': 'orphan', 'parent_id': 'missing'}], NoSourceReads())
    assert pairs == []
    assert {r['reason'] for r in excluded} == {'no_source_line_arrays', 'no_explicit_present_parent'}


def test_exact_text_hash_is_not_whitespace_normalized():
    assert text_hash('SYNTHETIC A\nB') != text_hash('SYNTHETIC A B')


def test_whole_body_rejects_unrepresented_paragraph_or_tail_text():
    for xml in ['<body><l>SYNTHETIC LINE</l><p>SYNTHETIC OMITTED PROSE</p></body>',
                '<body><l>SYNTHETIC LINE</l>SYNTHETIC OMITTED TAIL</body>']:
        assert unlineated_reading_text(ET.fromstring(xml))
    parent, tr = record(['1', '2']), record(['1'])
    bad = source(parent, count=1) | {'unlineated_reading_text': True}
    assert boundary_proof(parent, tr, bad, source(tr, count=1)) is None
    assert not unlineated_reading_text(ET.fromstring('<body><head>SYNTHETIC HEADING</head><l>SYNTHETIC LINE</l><note>SYNTHETIC NOTE</note></body>'))


def test_cached_source_reparse_and_hash_binding(tmp_path):
    # Synthetic TEI and archive test mechanics, never copied into corpus data.
    commit = 'a' * 40
    urn = 'tlg9999.tlg001.perseus-eng1'
    raw_rel = f'data/raw/perseus/tlg9999/tlg001/{urn}.xml'
    remote_rel = f'data/tlg9999/tlg001/{urn}.xml'
    xml = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><l n="1">SYNTHETIC TEXT</l></div></body></text></TEI>'
    raw = tmp_path / raw_rel; raw.parent.mkdir(parents=True); raw.write_bytes(xml)
    archive = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr(f'canonical-greekLit-{commit}/{remote_rel}', xml)
    parsed = passages(ET.fromstring(xml), 'eng')[0]
    r = {'id': 'synthetic', 'source_url': BASE + commit + '/' + remote_rel,
         'raw_path': raw_rel, 'raw_sha256': sha(xml), 'language': 'eng', 'kind': 'translation',
         'citation': parsed[0], 'text': parsed[1], 'lines': parsed[2],
         'metadata': {'commit': commit, 'cts_urn': urn}}
    sources = CachedSources(tmp_path, archive, commit)
    try:
        assert sources.load(r)['reading_record_count'] == 1
        with pytest.raises(ValueError, match='Raw hash mismatch'):
            sources.load(r | {'raw_sha256': '0' * 64})
        with pytest.raises(ValueError, match='does not uniquely reparse'):
            sources.load(r | {'text': 'ALTERED SYNTHETIC TEXT'})
        with pytest.raises(ValueError, match='Source identity mismatch'):
            sources.load(r | {'source_url': 'https://example.test/other'})
    finally:
        sources.archive.close()
