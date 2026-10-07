"""Adversarial synthetic TEI layout tests; no dictionary data is authored."""
import pytest
from lxml import etree

from backend.lexicon_senses import _parse


def projection(*, lead=' as pl. of ', gap=', ', prior=None, nested=False,
               foreign_tag='foreign', inside_sense=False):
    entry = etree.Element('entryFree')
    orth = etree.SubElement(entry, 'orth')
    orth.text = 'a'
    orth.tail = lead
    if prior:
        marker = etree.SubElement(entry, prior)
        marker.text = 'synthetic prior source material'
        marker.tail = lead
    parent = etree.SubElement(entry, 'sense') if inside_sense else entry
    if nested:
        parent = etree.SubElement(parent, 'div')
    foreign = etree.SubElement(parent, foreign_tag, lang='greek')
    foreign.text = 'logos'
    foreign.tail = gap
    scope = parent if inside_sense else etree.SubElement(entry, 'sense')
    tr = etree.SubElement(scope, 'tr')
    tr.text = 'synthetic literal text'
    return _parse(entry, {}, {
        'id': 'synthetic-layout', 'entry_id': 'synthetic-layout',
        'source': 'synthetic test fixture',
        'source_url': 'https://example.invalid/synthetic-layout',
        'raw_sha256': '0' * 64, 'raw_path': 'synthetic-layout',
    })


@pytest.mark.parametrize('lead', [' as pl. of ', ' sg. of ', ' dual. of '])
def test_explicit_first_preamble_counterpart_retains_literal_markup(lead):
    assert [row['text'] for row in projection(lead=lead)['dictionary_senses']] == [
        'synthetic literal text']


@pytest.mark.parametrize('options', [
    {'lead': ' e.g. as pl. of '},
    {'lead': ' E. G. as sg. of '},
    {'lead': ' e.g. '},
    {'lead': ', '},
    {'gap': '; '},
    {'prior': 'bibl'},
    {'prior': 'sense'},
    {'nested': True},
    {'foreign_tag': 'quote'},
    {'inside_sense': True},
])
def test_counterpart_exception_never_overrides_example_or_scope_boundary(options):
    result = projection(**options)
    assert result['dictionary_senses'] == []
    assert any(row['reason'] == 'translation_of_preceding_greek_example'
               for row in result['dictionary_senses_excluded'])
