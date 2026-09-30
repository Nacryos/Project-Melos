"""Read-only regression probes for failures reproduced in the live browser.

These checks inspect known source-backed records, not model accuracy rates.
No classifier/provider request is made. They supplement, not replace, browser QA.
"""
import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(origin):
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
    assert result['total'] == 1
    assert result['results'][0]['reference_match']['coverage'] == 'reference_only'
    print('Ibycus 286: exact catalogue-only result; no unrelated fallback.', flush=True)
    result = get('/api/word', form='φαίνεταί', passage_id='dcc-sappho:frag-31')
    assert result['expansion_lemmas'] == []
    assert any(row['lemma'] == 'ἐγώ' for row in result['candidates']), 'Original conflicting evidence must remain visible'
    assert not any(row['automatic_expansion_eligible'] for row in result['candidates'])
    print('Conflicting source lemma links remain visible but do not drive automatic expansion.', flush=True)
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    verify(parser.parse_args().origin)
