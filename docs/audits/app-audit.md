# Reader app integration audit

2026-09-30. This audit checks the local reader API against an isolated synthetic
fixture and the final accepted eight-source index. An earlier 14,597-record
Perseus build was withdrawn after editorial review and is not used for the
current-source results below. Synthetic rows in
`tests/test_api.py` are test inputs only, not corpus evidence.

## Executable checks

`python -m pytest tests/test_api.py tests/test_coverage.py -q`: **13 passed**. The tests build a
temporary SQLite index behind a synthetic acceptance manifest. They cover
status and work counts, work paging and passage neighbors, translation parent
links, accent-insensitive whole-word search, author/language and reference
filters, literal URL query syntax, parameter limits, word occurrence lookup,
quarantine of an unapproved JSONL file, inaccessible raw/database URL paths,
and removal of absolute project paths from `/api/sources`. Exact and form
search pagination has stable totals, no repeated IDs, and an empty page after
the end; the synthetic form association in that test is query-mechanics data,
not a morphological assertion. A synthetic semantic ranking also verifies
that its paginated total counts only filtered retrieved records. Author-scope
tests cover canonical case/Unicode equivalence, explicit commentary parent
links, page-scope notes with a shared source URL, and unrelated negative cases.

The synthetic acceptance manifest exists only under pytest's temporary
directory. It is not an independent acceptance decision about source material.
`node --check js/reader.js` and `node --check js/usage-space.js` also passed.
The reader script URL-encodes API parameters, renders corpus text through DOM
text nodes, and limits source links to HTTP(S) URLs.

## Approved source integration smoke test

The accepted index contained 280,016 records across eight source labels,
653 work/edition/language groups, and 90 exact author labels (86
case/Unicode-equivalent author choices). The reproducible source and author
breakdown is in [`coverage.json`](../../data/reports/coverage.json). These
counts do not establish unique ancient passages or independent witnesses.

Using an in-process HTTP client against the actual index:

| Query/check | Observed result |
| --- | --- |
| Exact folded Greek `μουσα` | 70 records; two 5-result pages returned 10 distinct IDs with the same total |
| Lyric web `σησαμίδας`, author `Στησίχορος` | One source-linked passage with citation `Άθλα` |
| A sampled translation `parent_id` | `/api/passage` returned the linked Greek parent in `related` |
| Exact English `muse`, `language=eng` | 72 translation/commentary records |
| Search `Sappho` with reference toggle | 157 ordinary results vs 432 with reference material included |
| Author `Sappho`, query `Obbink` | 5 linked commentary results under their own modern author labels, with source-link scope reason |
| Author `Sappho`, query `acephalus` | 33 linked page-scope notes; author `Pindar` returned none |
| Theme query `longing and separation`, author `Sappho` | Priority semantic index returned linked Heather commentary with score and scope reason; 20,000 indexed embeddings at test time |
| `/api/sources` | No absolute project path appeared in the response |

No generated or mocked passage was used for the approved-source checks. This
app audit confirms that admitted records pass through the API; it does not
replace the separate source and editorial audits.

## Scope and open checks

The index contains large OCR/reference components; only 97,755 records meet
the clean Greek text filter, as defined in [`coverage.md`](../coverage.md).
The final semantic index contains 104,736/104,736 eligible records, represented
by 107,627 token windows. IDs exactly match the eligible database set, and all
vectors are finite and normalized. This establishes index coverage, not
Ancient Greek retrieval quality. Warm theme requests on port 8791 took 0.251s
and 0.215s for the same author-filtered query; the author-scope SQL portion
alone took 0.242s for 1,000 real candidate IDs. Theme pagination now uses a
fixed 1,000-candidate pool with a warning when the bound is reached, so its
total is a retrieval-window count.

Live browser checks confirmed Greek word buttons, transliterated form search,
the separate Wiktionary panel (including sense-scoped Aeolic/Epic/Lesbian labels
for `ἄμμι`), and usage-space passage/source links. A description of the
unreachable apple returned commentary on Sappho 105a as its first candidate;
many other candidates were only loosely relevant. This is a retrieval smoke
test, not a benchmark or a verified intertextual claim.

After the final server restart, API checks confirmed the complete index,
the explicit nearby-spelling warning for `pe/mphn`, and a 12-point usage-space
response carrying actual retrieval reasons. The latter request took 0.25s.
The pinned model's cold startup took 27s on this machine. The browser layout
was checked at 1210px and source Greek typography reduced for readable lines.

The final description-to-text flow was exercised end to end: the 105a
commentary result opened its explicitly linked Greek passage; clicking
`μαλοδρόπηες` displayed the literal source gloss "apple pickers" above the
separately labelled nearby-spelling analyses. At the responsive breakpoint,
the inspector scrolled into view and "Back to passage" restored focus to the
clicked word. All 35 Python tests and both JavaScript syntax checks pass.
