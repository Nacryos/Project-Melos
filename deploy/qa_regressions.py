"""Read-only regression probes for failures reproduced in the live browser.

These checks inspect known source-backed records, not model accuracy rates.
No classifier/provider request is made. They supplement, not replace, browser QA.
"""
import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(origin, *, cgl=False):
    def get(path, **params):
        with urlopen(origin.rstrip('/') + path + '?' + urlencode(params), timeout=60) as response:
            return json.load(response)

    for form, identifier in [('τεθυμιάμενοι','dcc-sappho:frag-2'), ('φωνείσας','dcc-sappho:frag-31')]:
        result = get('/api/search', q=form, mode='words', match='exact', author='Sappho', limit=100)
        assert identifier in {row['id'] for row in result['results']}, (form, result)
        source = get('/api/passage', id=identifier)
        assert '-\n' in source['text'], 'Printed source line division must remain intact'
        print(json.dumps({'query': form, 'matches': result['total'], 'source_text_preserved': True}), flush=True)
    result = get('/api/search', q='Ibycus 286', mode='hybrid')
    assert result['mode'] == 'reference'
    if not cgl:
        assert result['total'] == 1
        assert result['results'][0]['reference_match']['coverage'] == 'reference_only'
        print('Ibycus 286: exact catalogue-only result; no unrelated fallback.', flush=True)
    else:
        rows = {row['id']: row for row in result['results']}
        greek_id = 'p2_cgl_anthology:354'
        assert rows[greek_id]['reference_match']['coverage'] == 'text'
        original = get('/api/passage', id=greek_id)
        assert original['language'] == 'grc' and original['text']
        assert original['citation'] == 'απ. 286 Page'
        translated = get('/api/search', q='286 Page', author='Ibycus', language='ell', mode='hybrid')
        credits = {'p2_cgl_anthology:354:tr1': 'Σ. Μενάρδος',
                   'p2_cgl_anthology:354:tr2': 'Ηλ. Βουτιερίδης',
                   'p2_cgl_anthology:354:tr3': 'Ι.Ν. Καζάζης'}
        assert {row['id'] for row in translated['results']} == set(credits)
        for row in translated['results']:
            assert row['reference_match']['coverage'] == 'translation'
            passage = get('/api/passage', id=row['id'])
            assert passage['language'] == 'ell' and passage['kind'] == 'translation'
            assert passage['parent_id'] == greek_id and passage['author'] == credits[row['id']]
            assert passage['citation'] == original['citation'] and passage['text']
        print('Ibycus 286: source Greek and all three explicitly linked, credited Modern Greek translations remain distinct.', flush=True)
    result = get('/api/word', form='φαίνεταί', passage_id='dcc-sappho:frag-31')
    assert result['expansion_lemmas'] == ['φαίνω']
    assert {row['lemma'] for row in result['candidates']} == {'φαίνω'}
    quarantined = result['quarantined_source_analyses']
    assert len(quarantined) == 1
    assert quarantined[0]['lemma'] == 'ἐγώ'
    assert quarantined[0]['sentence_id'] == '2857971' and quarantined[0]['token_id'] == '17'
    assert quarantined[0]['status'] == 'quarantined_source_annotation'
    print('Reviewed erroneous annotation is disclosed separately; only the independently attested verb drives analysis and expansion.', flush=True)
    source = get('/api/passage', id='dcc-sappho:brothers-poem')
    form = 'βασί̣λ̣η̣αν'
    assert form in source['text'], 'Original underdots must remain present in the edition text'
    result = get('/api/word', form=form, passage_id=source['id'])
    assert source['id'] in {row['id'] for row in result['occurrences']}, 'Underdotted word must remain one occurrence token'
    print('Underdotted Brothers Poem form remains intact and its original occurrence is discoverable.', flush=True)
    form = 'κἄμμ’'
    assert form in source['text'], 'The source elision sign must remain present'
    result = get('/api/word', form=form, passage_id=source['id'])
    assert source['id'] in {row['id'] for row in result['occurrences']}, 'Printed elided form must find its own occurrence'
    assert result['analysis_match_status'] == 'spelling_suggestions_only'
    assert result['attested_forms'] == [], 'Nearby lemmas must not be pooled as forms of the query'
    groups = result['observed_form_groups']
    assert {'κάμνω', 'καῦμα', 'ἐγώ'} <= {group['lemma'] for group in groups}
    assert all(group['query_relation'] == 'spelling_suggestion' for group in groups)
    for group in groups:
        assert group['complete_paradigm'] is False
        assert group['shown_forms'] == len(group['forms']) <= group['total_forms']
        assert group['truncated'] == (group['shown_forms'] < group['total_forms'])
        for item in group['forms']:
            assert item['source_refs'], 'Displayed inventory forms need source records'
            assert all(ref['source'] == group['source'] for ref in item['source_refs'])
    print('Nearby-spelling form inventories remain source/lemma-scoped, with explicit limits; no pooled query paradigm.', flush=True)
    heat = next(group for group in groups if group['lemma'] == 'καῦμα')
    genitive = next(item for item in heat['forms'] if item['form'] == 'καύματος')
    locators = [location for ref in genitive['source_refs'] for location in ref['locations']]
    assert any(location['citation'] == 'urn:cts:greekLit:tlg0012.tlg001:5.865'
               and location['sentence_id'] == '2275891' and location['token_id'] == '8'
               for location in locators), 'The explicit token citation must survive lookup'
    assert {('1716136', '7'), ('1716230', '52')} <= {
        (location['sentence_id'], location['token_id']) for location in locators
        if location['document_id'] == 'urn:cts:greekLit:tlg0020.tlg002.perseus-grc1'
        and not location['citation']}, 'Same-file tokens must retain distinct locators without invented citations'
    for ref in genitive['source_refs']:
        assert ref['locations_shown'] == len(ref['locations']) <= ref['location_total']
        assert ref['locations_truncated'] == (ref['locations_shown'] < ref['location_total'])
    print('Token citations and distinct same-file locators survive reading deduplication; missing citations stay absent.', flush=True)
    truncated = get('/api/search', q='κἄμμ', mode='words', match='exact', author='Sappho', limit=100)
    assert source['id'] not in {row['id'] for row in truncated['results']}, 'Exact search must not silently discard the printed elision sign'
    print('Printed elision sign is preserved in lookup; bare-prefix exact search does not claim the Brothers Poem.', flush=True)
    fragment = get('/api/passage', id='dcc-sappho:frag-27')
    printed = 'κἄμμ᾿'
    assert printed in fragment['text'], 'Distinct printed spacing psili must remain in fragment 27'
    result = get('/api/word', form=printed, passage_id=fragment['id'])
    assert fragment['id'] in {row['id'] for row in result['occurrences']}
    assert fragment['id'] not in {row['id'] for row in truncated['results']}
    exact_sets = []
    for query in ('κἄμμ’', "kamm'", 'kamm᾽'):
        result = get('/api/search', q=query, mode='words', match='exact', author='Sappho', limit=100)
        assert result['total'] <= 100, 'Equivalence regression must compare complete results'
        exact_sets.append({row['id'] for row in result['results']})
    assert exact_sets[0] == exact_sets[1] == exact_sets[2]
    print('Spacing psili remains distinct; Greek and Latin elision-sign queries agree without dropping signs.', flush=True)
    description = 'the wedding of Hector and Andromache'
    result = get('/api/search', q=description, mode='words', author='Sappho', limit=30)
    assert not result.get('fallback_terms'), 'English description must not be replaced by accidental Greek keys'
    assert result['results'] and 'fr44' in result['results'][0]['id']
    result = get('/api/search', q=description, mode='hybrid', limit=30)
    assert result['results'][0]['id'] == 'digital-sappho:fr44:1'
    print('Wedding description retrieves Sappho 44 without accidental transliteration.', flush=True)
    for query, target in [
        ('Gygeo tou polychrysou', 'lyric_web:elws:10410:165084:8'),
        ("Eudousin d' oreon koryphai", 'lyric_web:elws:17911:125703:1'),
        ('Eudousin d’ oreon koryphai', 'lyric_web:elws:17911:125703:1'),
        ('ballon chrysokomes Eros', 'lyric_web:elws:17312:140158:1'),
    ]:
        result = get('/api/search', q=query, mode='words', limit=10)
        assert result['results'][0]['id'] == target, (query, result['results'][0]['id'])
        assert result['fallback_terms']['original']
        assert result['results'][0]['query_term_coverage'] >= 3
    print('Romanized lyric phrase controls retain intended first results and explicit original-word coverage.', flush=True)
    wedding = get('/api/passage', id='digital-sappho:fr44:1')
    assert len(wedding['lines']) == 44, 'Source layout lines must stop at the explicit 44A heading'
    columns = get('/api/search', q='Sappho 44A', mode='hybrid')
    column_ids = {'digital-sappho:fr44:section:1c5658026225ae91',
                  'digital-sappho:fr44:section:47d00865cc917d34'}
    assert column_ids <= {row['id'] for row in columns['results']}
    for row in columns['results']:
        if row['id'] in column_ids:
            assert row['reference_match']['coverage'] == 'section_text'
    artemis_note = get('/api/passage', id='digital-sappho:fr44:vocab:138')
    assert artemis_note['parent_id'] == 'digital-sappho:fr44:section:1c5658026225ae91'
    print('44A source columns are separately discoverable; their notes no longer belong to the wedding poem.', flush=True)
    tithonus = get('/api/passage', id='digital-sappho:fr58-59:1')
    assert len(tithonus['lines']) == 12
    preceding_note = get('/api/passage', id='digital-sappho:fr58-59:vocab:69')
    assert 'parent_id' not in preceding_note
    assert preceding_note['metadata']['unresolved_source_heading']
    following = get('/api/passage', id='digital-sappho:fr58-59:section:a7623aca0f7471b6')
    assert len(following['lines']) == 3
    assert any(note.get('description') for note in following['metadata']['source_footnote_links'])
    print('Tithonus, neighbouring witness sections and source dispute notes remain distinct; unresolved notes are not falsely aligned.', flush=True)
    qualified_id = 'digital-sappho:fr169-192:section:8b523a2c33227ace'
    qualified = get('/api/search', q='Sappho 178 Campbell', mode='hybrid')
    assert qualified_id in {row['id'] for row in qualified['results']}
    other_scheme = get('/api/search', q='Sappho 168A Page', mode='hybrid')
    assert qualified_id not in {row['id'] for row in other_scheme['results']}
    print('Edition-qualified heading is discoverable without misreading its parenthetical compound edition name.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--cgl', action='store_true', help='Require the accepted CGL append (omit for QA13 rollback).')
    args = parser.parse_args()
    verify(args.origin, cgl=args.cgl)
