"""Source-backed LSJ display checks; synthetic XML below is test-only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from lxml import etree
import pytest

from backend.lexicon_render import (_comparative_definition, _render_spans,
                                    definition_excerpt, read_entry, render_source_record, SPACE)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BASE = 'https://raw.githubusercontent.com/PerseusDL/lexica/56061ca127f4a2844980baffc5f2b6d1332897b3/'
PREFIX = 'CTS_XML_TEI/perseus/pdllex/grc/lsj/'
RAW_HASHES = {
    1: '15b1b7ca0a6c88e5a14e97f2339a0c7a7dfae71c028bdfb45fcee04c79a754f7',
    17: '237bf71d5e293c8cd5bc6c22e125e180cb11f28597b17c2efe0f9018c03e1fcc',
    16: 'ade343b53f0d695551f786c0caeda9f25e1819a33339cddd68cf50c730bc1c38',
}


def source_record(number, entry_id):
    suffix = PREFIX + f'grc.lsj.perseus-eng{number}.xml'
    record = {'source': 'PerseusDL LSJ TEI', 'entry_id': entry_id,
              'raw_path': 'data/raw/lexica/lsj/' + suffix,
              'raw_sha256': RAW_HASHES[number], 'source_url': SOURCE_BASE + suffix,
              'gloss': 'SYNTHETIC STORED GLOSS MUST REMAIN UNCHANGED'}
    if not (ROOT / record['raw_path']).exists():
        pytest.skip('Accepted raw LSJ artifact unavailable')
    return record


@pytest.mark.parametrize('number,entry_id,opening', [(1, 'n8665', 'man, opp. woman'), (17, 'n80011', 'father')])
def test_source_definition_clause_and_exact_locator(number, entry_id, opening):
    record = source_record(number, entry_id); before = deepcopy(record)
    result = render_source_record(record)
    assert result['definition_excerpt'].startswith(opening)
    assert 'Skt.' not in result['definition_excerpt']
    assert record == before
    assert 'Skt.' in result['rendered_entry_text']  # full source unchanged
    provenance = result['definition_excerpt_provenance']
    assert provenance['raw_sha256'] == RAW_HASHES[number]
    assert provenance['entry_id'] == entry_id
    entry, entities = read_entry(record['raw_path'], entry_id)
    text, _ = _render_spans(entry, entities)
    locator = provenance['source_locator']
    assert locator['sense_id'] == entry_id + '.0'
    assert SPACE.sub(' ', text[locator['rendered_start']:locator['rendered_end']]).strip() == result['definition_excerpt']
    if number == 1:
        assert 'being man as opp. to beast' in result['definition_excerpt']


@pytest.mark.parametrize('entry_id', ['n39', 'n47'])
def test_real_separator_after_valid_meaning_does_not_drop_it(entry_id):
    assert definition_excerpt(source_record(1, entry_id)) == {}


def test_real_next_sense_does_not_leave_dangling_qualification():
    assert definition_excerpt(source_record(16, 'n75267')) == {}


def synthetic(xml):
    return _comparative_definition(etree.fromstring(xml.encode('utf8')), {})


def test_synthetic_qualifiers_preserved_and_first_citation_stops_clause():
    xml = '<entryFree><sense id="synthetic">(cf. Skt. <tr>SYNTHETIC COMPARISON</tr>):—<tr>SYNTHETIC MEANING</tr>, opp. <tr>SYNTHETIC CONTRAST</tr><bibl>SYNTHETIC CITATION</bibl>; later material</sense></entryFree>'
    assert synthetic(xml)['definition_excerpt'] == 'SYNTHETIC MEANING, opp. SYNTHETIC CONTRAST'


def test_citation_inside_parenthetical_qualifier_abstains():
    xml = '<entryFree><sense>(cf. Skt. <tr>SYNTHETIC COMPARISON</tr>):—<tr>SYNTHETIC MEANING</tr> (only in <bibl>SYNTHETIC CITATION</bibl>)</sense></entryFree>'
    assert synthetic(xml) is None


def test_next_sense_after_dangling_qualification_abstains():
    xml = '<entryFree><sense>(cf. Skt. <tr>SYNTHETIC COMPARISON</tr>):—<tr>SYNTHETIC MEANING</tr>; esp.<sense>of SYNTHETIC QUALIFICATION</sense></sense></entryFree>'
    assert synthetic(xml) is None


@pytest.mark.parametrize('preamble', [
    'cf. Skt. <tr>SYNTHETIC</tr>)',  # unmatched close
    '(cf. Skt. <tr>SYNTHETIC</tr>',  # unmatched open
    '(unidentified <tr>SYNTHETIC</tr>)',  # no explicit comparative cue
    '<tr>EARLIER SYNTHETIC MEANING</tr> (cf. Skt. <tr>SYNTHETIC</tr>)',
])
def test_unproven_or_unbalanced_synthetic_layout_abstains(preamble):
    assert synthetic(f'<entryFree><sense>{preamble}:—<tr>SYNTHETIC DEFINITION</tr><bibl>X</bibl></sense></entryFree>') is None


def test_real_source_hash_mismatch_and_non_lsj_fail_closed():
    record = source_record(17, 'n80011')
    assert definition_excerpt(record | {'raw_sha256': '0' * 64}) == {}
    assert definition_excerpt(record | {'source': 'different source'}) == {}


def test_source_signature_drift_abstains(monkeypatch):
    from backend import lexicon_render as renderer
    class ChangingSource:
        calls = 0
        def stat(self):
            self.calls += 1
            return SimpleNamespace(st_mtime_ns=self.calls, st_size=100)
    monkeypatch.setattr(renderer, '_source_path', lambda path: ChangingSource())
    monkeypatch.setattr(renderer, '_raw_digest', lambda *args: 'synthetic-digest')
    monkeypatch.setattr(renderer, 'read_entry', lambda *args: (etree.fromstring(b'<entryFree/>'), {}))
    r = {'source': 'PerseusDL LSJ TEI', 'source_url': 'https://example.test/synthetic',
         'raw_path': 'synthetic', 'entry_id': 'synthetic', 'raw_sha256': 'synthetic-digest'}
    assert renderer.definition_excerpt(r) == {}
