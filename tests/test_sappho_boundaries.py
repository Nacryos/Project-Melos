"""Parser regression HTML is synthetic, not literary corpus evidence."""
import json
from pathlib import Path
import pytest
from scripts import ingest_sappho as parser


def parse(html, previous=None):
    return parser.digital_records('https://example.org/fragments/test/',
        parser.ROOT / 'data/raw/synthetic-not-a-source.html', html.encode(), previous)


def test_prefixed_heading_columns_notes_and_source_local_aliases():
    rows = parse('''<div class="post"><h2 class="post_title">Fragment 44</h2>
      <div lang="grc">1. αβγ</div><h4>FRAGMENT 44Α</h4>
      <div><i>(a) Column i</i></div><div lang="grc">5. δεζ</div>
      <div><i>(b) Column ii</i></div><div lang="grc">5. ηθι</div></div>
      <div id="activity_sidebar"><div class="comments_container"><table>
      <tr><td>1</td><td>αβγ synthetic note</td></tr><tr><td><h4>44A</h4></td></tr>
      <tr><td>(a) Column i</td></tr><tr><td>5</td><td>δεζ synthetic note</td></tr>
      <tr><td>(b) Column ii</td></tr><tr><td>5</td><td>ηθι synthetic note</td></tr>
      </table></div></div>''')
    texts = [row for row in rows if row['kind'] == 'text']
    notes = [row for row in rows if row.get('metadata', {}).get('subtype') == 'vocabulary']
    assert len(texts) == 3
    assert [row['text'] for row in texts] == ['1. αβγ', '5. δεζ', '5. ηθι']
    assert [row['parent_id'] for row in notes] == [row['id'] for row in texts]
    assert texts[1]['lines'][0]['section'] == '(a) Column i'
    assert texts[2]['metadata']['source_citation_aliases'][0]['label'] == '44A'
    assert texts[2]['metadata']['source_citation_aliases'][0]['body_heading'] == 'FRAGMENT 44Α'


def test_new_sections_do_not_shift_existing_ids_and_parallel_group_is_not_first_fragment():
    old = [{'kind': 'text', 'id': 'old-a', 'citation': '90a'},
           {'kind': 'text', 'id': 'old-d', 'citation': '90d'}]
    rows = parse('''<div class="post"><h2 class="post_title">Fragment 90</h2>
      <h4>90a</h4><div lang="grc">αβγ</div>
      <h4>90b <span>90c</span></h4><div lang="grc">δεζ <span>ηθι</span></div>
      <h4>90d</h4><div lang="grc">κλμ</div></div>
      <div id="activity_sidebar"><div class="comments_container"><table>
      <tr><td><h4>90b</h4></td></tr><tr><td>1</td><td>δεζ synthetic note</td></tr>
      </table></div></div>''', old)
    texts = [r for r in rows if r['kind'] == 'text']
    assert texts[0]['id'] == 'old-a'
    assert texts[2]['id'] == 'old-d'
    assert ':section:' in texts[1]['id']
    assert texts[1]['citation'] == '90b 90c'
    assert texts[1]['quality'] == 'mixed_content'
    note = next(r for r in rows if r.get('metadata', {}).get('subtype') == 'vocabulary')
    assert 'parent_id' not in note
    assert note['metadata']['scope'] == 'page'


def test_malformed_nested_headings_use_only_inline_heading_and_preserve_witness_boundaries():
    rows = parse('''<div class="post"><h2 class="post_title">Fragments 58-59</h2>
      <h4>The primary poem</h4><div lang="grc">αβγ</div>
      <h4>Preceding lines in witness A <span class="easy-footnote"><a href="#note" title="Source note"><sup>1</sup></a></span>
      <h4></h4><div lang="grc">δεζ</div>
      <h4>Following lines in witness B</h4><div lang="grc">ηθι</div>
      <h4>Fragment 59: Continuation of witness B</h4><div lang="grc">κλμ</div></h4></div>''')
    texts = [r for r in rows if r['kind'] == 'text']
    assert [r['citation'] for r in texts] == ['Fragments 58-59', 'Preceding lines in witness A',
        'Following lines in witness B', 'Fragment 59: Continuation of witness B']
    assert [r['text'] for r in texts] == ['αβγ', 'δεζ', 'ηθι', 'κλμ']
    assert texts[1]['metadata']['source_footnote_links'][0]['title_html'] == 'Source note'


def test_easy_footnote_marker_removed_but_reference_and_printed_line_prefix_retained():
    rows = parse('''<div class="post"><h2 class="post_title">Fragment 1</h2>
      <div lang="grc">5. αβγ<span class="easy-footnote"><a href="#note" title="Explicit note"><sup>1</sup></a></span> δεζ</div></div>''')
    text = rows[0]
    assert text['text'] == '5. αβγ δεζ'
    assert text['lines'][0]['label'] == '5'
    assert text['metadata']['source_footnote_links'] == [{'marker': '1', 'href': '#note',
        'title_html': 'Explicit note', 'description': 'Explicit note', 'line_index': 0}]


def test_qualified_numbering_heading_keeps_exact_qualification():
    rows = parse('''<div class="post"><h2 class="post_title">Fragments</h2>
      <h4>177</h4><p lang="grc">αβγ</p>
      <h4>178 Edition A (= Edition B 168A)</h4><p lang="grc">δεζ</p>
      <h4>179</h4><p lang="grc">ηθι</p></div>''')
    texts = [r for r in rows if r['kind'] == 'text']
    assert texts[1]['citation'] == '178 Edition A (= Edition B 168A)'
    assert [r['text'] for r in texts] == ['αβγ', 'δεζ', 'ηθι']


def test_cached_fr44_stable_split_and_column_notes():
    path = parser.ROOT / 'data/raw/sappho/digitalsappho.org__fragments__fr44.html'
    accepted = parser.ROOT / 'data/processed/sappho.jsonl'
    if not path.exists() or not accepted.exists():
        pytest.skip('Optional local cached-source integration fixture is not distributed')
    url = 'https://digitalsappho.org/fragments/fr44/'
    old = [json.loads(line) for line in accepted.read_text(encoding='utf-8').splitlines()
           if json.loads(line)['source_url'] == url]
    rows = parser.digital_records(url, path, path.read_bytes(), old)
    texts = [r for r in rows if r['kind'] == 'text']
    assert [len(r['lines']) for r in texts] == [44, 12, 6]
    assert texts[0]['id'] == 'digital-sappho:fr44:1'
    assert len({r['id'] for r in texts}) == 3
    artemis = next(r for r in rows if r['id'] == 'digital-sappho:fr44:vocab:138')
    assert artemis['parent_id'] == texts[1]['id']
    assert texts[1]['metadata']['source_citation_aliases'][0]['label'] == '44A'


def test_prose_only_source_section_is_preserved_without_fake_text_parent():
    rows = parse('''<div class="post"><h2 class="post_title">Fragments</h2>
      <h4>Primary poem</h4><div lang="grc">αβγ</div>
      <h4>Following lines in witness A</h4><p>The source rejects attribution to the poet.</p>
      <h4>Following lines in witness B</h4><div lang="grc">δεζ</div></div>''')
    notes = [r for r in rows if 'rejects attribution' in r['text']]
    assert len(notes) == 1
    assert notes[0]['kind'] == 'commentary'
    assert notes[0]['citation'] == 'Following lines in witness A'
    assert 'parent_id' not in notes[0]
    assert notes[0]['metadata']['scope'] == 'source_section'


def test_single_parallel_group_never_becomes_individual_note_parent():
    rows = parse('''<div class="post"><h2 class="post_title">Fragment 28</h2>
      <h4>28a 28b</h4><div lang="grc">αβγ <span>δεζ</span></div></div>
      <div id="activity_sidebar"><div class="comments_container"><table>
      <tr><td>1</td><td>αβγ synthetic note</td></tr></table></div></div>''')
    assert rows[0]['quality'] == 'mixed_content'
    note = next(r for r in rows if r.get('metadata', {}).get('subtype') == 'vocabulary')
    assert 'parent_id' not in note
    assert note['metadata']['scope'] == 'page'


def test_conflicting_edition_heading_cannot_create_citation_alias():
    rows = parse('''<div class="post"><h2 class="post_title">Fragments</h2>
      <h4>177</h4><div lang="grc">αβγ</div>
      <h4>178 Campbell</h4><div lang="grc">δεζ</div></div>
      <div id="activity_sidebar"><div class="comments_container"><table>
      <tr><td><h4>178 Voigt</h4></td></tr><tr><td>1</td><td>δεζ synthetic note</td></tr>
      </table></div></div>''')
    note = next(r for r in rows if r.get('metadata', {}).get('subtype') == 'vocabulary')
    assert 'parent_id' not in note
    assert not any(r.get('metadata', {}).get('source_citation_aliases') for r in rows)


def test_between_table_witness_heading_resets_parent_without_guessing_alias():
    rows = parse('''<div class="post"><h2 class="post_title">Fragments 58-59</h2>
      <h4>The “Primary Poem”</h4><div lang="grc">αβγ</div>
      <h4>Preceding lines in the Cologne Papyrus</h4><div lang="grc">δεζ</div></div>
      <div id="activity_sidebar"><div class="comments_container">
      <h4>The Primary Poem</h4><table><tr><td>1</td><td>αβγ synthetic note</td></tr></table>
      <h4>Preceeding Lines - Cologne Papyrus</h4><table><tr><td>1</td><td>δεζ synthetic note</td></tr></table>
      </div></div>''')
    notes = [r for r in rows if r.get('metadata', {}).get('subtype') == 'vocabulary']
    linked = next(r for r in notes if r['id'].endswith(':vocab:1'))
    unlinked = next(r for r in notes if r['id'].endswith(':vocab:2'))
    assert linked['parent_id'] == rows[0]['id']
    assert 'parent_id' not in unlinked
    assert unlinked['metadata']['unresolved_source_heading'] == 'Preceeding Lines - Cologne Papyrus'


def test_unknown_external_heading_resets_even_a_single_text_page():
    rows = parse('''<div class="post"><h2 class="post_title">Fragment 1</h2><div lang="grc">αβγ</div></div>
      <div id="activity_sidebar"><div class="comments_container"><h4>Another witness section</h4>
      <table><tr><td>1</td><td>αβγ synthetic note</td></tr></table></div></div>''')
    note = next(r for r in rows if r.get('metadata', {}).get('subtype') == 'vocabulary')
    assert 'parent_id' not in note
    assert note['metadata']['unresolved_source_heading'] == 'Another witness section'
