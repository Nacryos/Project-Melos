"""Synthetic regression fixtures; none of these rows are corpus evidence."""
from backend.reference_lookup import parse_reference_query, rank_reference_records


AUTHORS = ["Sappho", "Ibycus", "Alcaeus of Mytilene", "Horace"]


def row(identifier, citation, **kwargs):
    return {"id": identifier, "author": "Ibycus", "work": "Fragments", "citation": citation,
            "kind": "text", "quality": "source_text", "language": "grc", "text": "SYNTHETIC FIXTURE", **kwargs}


def lookup(query, records, **kwargs):
    intent = parse_reference_query(query, AUTHORS)
    assert intent is not None
    return rank_reference_records(intent, records, **kwargs)


def test_author_and_marker_and_case():
    intent = parse_reference_query(" IBYCUS Fr. 286 ", AUTHORS)
    assert intent.author == "Ibycus"
    assert intent.number == "286"


def test_selected_author_and_verified_alias():
    aliases = lambda a: ["Alcaeus", "Alcaeus of Mytilene"] if a.casefold().startswith("alcaeus") else [a]
    intent = parse_reference_query("Alcaeus 18", AUTHORS, alias_resolver=aliases)
    assert "Alcaeus of Mytilene" in intent.author_labels
    assert parse_reference_query("31", AUTHORS, selected_author="Sappho").number == "31"


def test_not_arbitrary_numbers_prose_or_unknown_author():
    for query in ["286", "Unknown 286", "Sappho's 31", "Sappho 31 love", "love 31", "Ibycus 286-287"]:
        assert parse_reference_query(query, AUTHORS) is None


def test_reference_only_is_returned_honestly_not_other_author_or_body_mentions():
    records = [row("pointer", "απ. 286 Page", kind="reference", language="mul",
                   metadata={"greek_text_extracted": False}),
               row("wrong_author", "Fragment 286", author="Horace"),
               row("body_only", "Fragment 1", text="Mentions Ibycus 286")]
    result = lookup("Ibycus 286", records)
    assert result["total"] == 1
    assert result["results"][0]["reference_match"]["coverage"] == "reference_only"
    assert any("Greek reading text is not indexed" in warning for warning in result["warnings"])


def test_number_boundaries_and_no_page_year_or_range_matches():
    records = [row("valid", "fr. 286"), row("long", "fr. 1286"), row("suffix", "fr. 286a"),
               row("page", "Edmonds fr. 1, line 2, p. 286"), row("year", "ZPE 286 (2026), p. 2"),
               row("range", "fr. 286–287"), row("subdivision", "fr. 286.1"),
               row("book", "286", work="Odes")]
    assert [r["id"] for r in lookup("Ibycus 286", records)["results"]] == ["valid"]


def test_explicit_edition_does_not_cross_numbering_schemes():
    records = [row("crossref", "Wikisource main fragment 18; Edmonds 37", author="Alcaeus of Mytilene"),
               row("edmonds18", "Edmonds fr. 18", author="Alcaeus of Mytilene")]
    assert [r["id"] for r in lookup("Alcaeus of Mytilene 18 Edmonds", records)["results"]] == ["edmonds18"]
    assert [r["id"] for r in lookup("Alcaeus of Mytilene 37 Edmonds", records)["results"]] == ["crossref"]


def test_explicit_metadata_cross_reference_only():
    records = [row("linked", "fragment 18", metadata={"edmonds_fragment_number": "37"}),
               row("unlinked", "fragment 18", metadata={"printed_page": "37"})]
    assert [r["id"] for r in lookup("Ibycus 37 Edmonds", records)["results"]] == ["linked"]


def test_primary_text_before_notes_and_partial_or_reference():
    records = [row("ref", "fr. 286", kind="reference"), row("note", "fr. 286", kind="commentary"),
               row("part", "fr. 286", metadata={"partial_fragment_line": True}), row("full", "286")]
    assert [r["id"] for r in lookup("Ibycus 286", records)["results"]] == ["full", "part", "note", "ref"]


def test_filters_and_empty_result_do_not_fall_back():
    records = [row("pointer", "fr. 286", kind="reference", language="mul", edition="A")]
    assert lookup("Ibycus 286", records, language="grc")["total"] == 0
    assert lookup("Ibycus 286", records, edition="B")["total"] == 0
    assert lookup("Ibycus 999", records)["mode"] == "reference"


def test_conflicting_author_filter_is_explained():
    intent = parse_reference_query("Ibycus 286", AUTHORS, selected_author="Sappho")
    result = rank_reference_records(intent, [row("match", "fr. 286")])
    assert result["total"] == 0
    assert any("conflicts" in warning for warning in result["warnings"])


def test_review_quality_is_never_relabelled_clean():
    result = lookup("Ibycus 286", [row("review", "fr. 286", quality="needs_review")])
    assert result["results"][0]["reference_match"]["coverage"] == "needs_review"
    assert result["results"][0]["quality"] == "needs_review"


def test_pagination_and_no_input_mutation():
    records = [row(str(n), "fr. 286") for n in range(3)]
    result = lookup("Ibycus 286", records, offset=1, limit=1)
    assert result["total"] == 3
    assert len(result["results"]) == 1
    assert "reference_match" not in records[0]


def test_greek_suffixes_match_literally_without_global_latin_equivalence():
    records = [row('greek-suffix', 'Fragment 44Α', author='Sappho'),
               row('latin-suffix', 'Fragment 44A', author='Sappho')]
    assert [r['id'] for r in lookup('Sappho 44α', records)['results']] == ['greek-suffix']
    assert [r['id'] for r in lookup('Sappho 44a', records)['results']] == ['latin-suffix']
    assert lookup('Sappho 44', records)['total'] == 0


def test_qualified_heading_retains_edition_and_does_not_infer_parenthetical_equivalence():
    records = [row('qualified', '178 Campbell (= Voigt, and Lobel & Page 168A)', author='Sappho'),
               row('other-edition', '178 Voigt', author='Sappho'),
               row('not-a-heading', 'See page 178 Campbell', author='Sappho'),
               row('not-fragments', '178 Campbell (source qualification)', author='Sappho', work='Odes')]
    assert [r['id'] for r in lookup('Sappho 178 Campbell', records)['results']] == ['qualified']
    assert [r['id'] for r in lookup('Sappho 178 Voigt', records)['results']] == ['other-edition']
    assert lookup('Sappho 168A Page', records)['total'] == 0
    assert lookup('Sappho 168A Voigt', records)['total'] == 0
    assert records[0]['citation'] == '178 Campbell (= Voigt, and Lobel & Page 168A)'


def test_source_local_heading_alias_requires_matching_provenance():
    url = 'https://example.test/synthetic-fragment-page'
    alias = {'label': '44A', 'body_heading': 'Fragment 44Α', 'source_url': url,
             'scope': 'fragment_heading', 'locator': '#synthetic-table tr3'}
    def fixture(identifier, entry, **metadata):
        return row(identifier, 'Fragment 44Α — source column', author='Sappho', source_url=url,
                   metadata={'source_heading': 'Fragment 44Α', 'source_citation_aliases': [entry], **metadata})
    records = [fixture('linked', alias),
               fixture('wrong-page', alias | {'source_url': 'https://example.test/other'}),
               fixture('wrong-heading', alias | {'body_heading': 'Fragment 45Α'}),
               fixture('no-locator', alias | {'locator': ''}),
               fixture('unscoped', alias | {'scope': 'page'})]
    result = lookup('Sappho 44A', records)
    assert [r['id'] for r in result['results']] == ['linked']
    assert 'synthetic-table tr3' in result['results'][0]['reference_match']['evidence'][0]
    assert lookup('Sappho 44A Voigt', records)['total'] == 0


def test_explicit_source_column_is_not_reported_as_whole_fragment_scope():
    result = lookup('Sappho 44Α', [row('column', 'Fragment 44Α — (a) Column i',
        author='Sappho', metadata={'source_section': '(a) Column i'})])
    assert result['results'][0]['reference_match']['coverage'] == 'section_text'
    assert 'not whole-fragment scope' in result['results'][0]['match_reason']
    assert any('source sections' in warning for warning in result['warnings'])
