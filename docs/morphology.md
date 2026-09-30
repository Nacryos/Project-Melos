# Morphology and query matching

`backend.morphology` reads only `data/lexica/entries.jsonl` and
`data/lexica/forms.jsonl`. Form rows are source-derived attestations; no
paradigm, dialect equivalence, definition, or parse is generated. A lexical
headword without an attested form is returned with `analysis: null`.

The public Python interface is:

```python
from backend.morphology import Morphology, normalize, tokenize, query_variants

service = Morphology()                 # lazy load on first query
service.counts()                       # {"entries": int, "forms": int}
service.forms_for_lemma(lemma)         # distinct attested form spellings
service.analyze(form, passage=None, occurrence_lookup=None, limit=12)
```

`normalize` makes a lossy search key: Unicode NFD, lowercase, removal of
combining marks (including breathings and iota subscript), medial/final/lunate
sigma folded to σ, standardized apostrophes, and whitespace in place of other
punctuation. It never changes a stored passage or source form. `tokenize`
returns the original spelling of tokens. `query_variants` accepts Greek,
Beta Code, or Latin-letter queries; ambiguous ASCII input produces more than
one candidate key. The Beta Code letter/mark table follows the [TLG Beta Code
Manual](https://stephanus.tlg.uci.edu/encoding.php). Conventional Latin
digraphs and letter alternatives follow the Ancient Greek ALA-LC column in
[Pedersen's Greek transliteration comparison](https://transliteration.eki.ee/pdf/Greek.pdf).
ASCII alternatives are retrieval hints, not reversible transliteration.

Lookup first checks exact/folded form and headword keys. If neither is found,
it searches a trigram or short-key index and accepts at most two character
edits (one for short words). This is a spelling suggestion, not a dialect
rule. It may miss some unusual spellings; a match never supplies an unattested
parse. Distinct candidate analyses and source URLs remain separate.

Results expose `form`, `normalized`, `candidates`, `lexicon_entries`,
`observed_form_groups`, `attested_forms`, `occurrences`, `context`,
`method`, and `warnings`. Candidate fields include `lemma`, `analysis`,
`gloss`, `entry_text`, `source`, `source_url`, `analysis_format`, `quality`,
`supporting_sources`, and `reason`; `gloss_source_url` is supplied when its source differs from
the form record. Source homograph markers appear as `lemma_raw` or `entry_id`.
Missing data remains null. A form with several possible
same-source homographs receives no arbitrarily chosen gloss. Where LSJ and
Autenrieth each have one matching entry, the first source entry is used as
the candidate's display gloss/text; all matching dictionary texts appear
once in top-level `lexicon_entries` and are linked by
`lexicon_entry_ids`. This display default does not affect parse rank.
The original `entry_text` stays verbatim. `rendered_entry_text` is a separate
display version built on demand from `raw_path` and `entry_id` in the saved
TEI source. The renderer converts only `lang="greek"` (and Greek `orth`)
spans using the same `betacode` converter as the extractor, preserving
English/Latin prose. It resolves standard semicolon-terminated references
from the [HTML named character reference table](https://html.spec.whatwg.org/multipage/named-characters.html),
keeps unknown references visible, and never loads an external DTD. Its
`rendering_method` and any `rendering_warning` travel with each source entry.
Byte offsets are cached per source XML file so lookup parses only the chosen
entry. The mapping follows the [Perseus Greek Beta Code guidance](https://www.perseus.tufts.edu/hopper/help/greek).
Ranking follows:
edit distance, source-annotated parse for the exact passage, source-annotated
parse for the same author, exact original spelling, transliteration variant,
then source type and stable lexical ordering. An `occurrence_lookup(key, limit)`
callback may supply corpus rows. A raw occurrence without explicit `lemma`
and `analysis` cannot influence parse ranking. Same-author evidence also
requires matching source-backed `author_id` values and a source URL; display
names and occurrence counts do not count. Without an annotated link to the
passage, the result warns that its analyses are alternatives, not a resolved
sense. The order is an evidence heuristic, never a probability.

Repeated treebank tokens with the same lemma and analysis appear as one
candidate, with distinct source links in `supporting_sources`; neither token
counts nor number of sources increase rank. Raw homograph indices are kept
separate when they distinguish readings. Lemmas with canonically equivalent
Unicode spelling (NFD/NFC) are grouped; source spellings remain in
`lemma_raw_variants`. A bare lemma can join its sole numbered treebank
homograph, but different numbered homographs stay separate. Accent placement
is retained for candidate identity, so `ὄρος` and `ὀρός` do not merge.
`observed_form_groups` keeps recorded form inventories separate by NFC lemma,
raw lemma identity (including source homograph markers), and source label.
It does not merge accent-distinct lemmas through their folded search keys.
Each group identifies its relation to the query, matched source spellings and
candidate indices. A `spelling_suggestion` group concerns a nearby spelling;
it does not establish a lemma or paradigm for the queried word.

Groups carry `total_forms`, `shown_forms`, and `truncated`; each displayed form
has its source references and explicit reference counts/truncation. These
references describe indexed annotations, not independently adjudicated parses.
Each reference also exposes source-provided `locations` containing `citation`,
`document_id`, `sentence_id`, and `token_id`. Missing values remain null. Later
tokens are not lost when identical morphological readings in the same source
file are deduplicated. `location_total`, `locations_shown`, and
`locations_truncated` count distinct recorded locator tuples, not inferred
unique ancient occurrences. Conflicting or incomplete locators are not silently
completed; no work names, line references, or token URLs are invented. The
location preview retains at most 20 locators per reference.
The inventories are not filtered to the selected passage, author, or dialect.
Unnumbered homograph ambiguity stays explicit instead of being resolved by
spelling proximity. `complete_paradigm` is always false.

The legacy flat `attested_forms` field is conservative: no fuzzy-only or
unresolved multi-identity inventory is presented as forms of the query. The
reader uses the grouped inventories, not that flat field. These are recorded
in the indexed source texts, not a complete Aeolic or other dialect paradigm.
An exact spelling reason
means exact agreement with an indexed source form; it does not assert that
the letters survive in an ancient witness rather than an edition.

`analysis_text` expands the nine-character Perseus treebank `postag` into
its documented grammatical slots, for example `n-p---ng-` becomes
“noun · plural · neuter · genitive.” The source code and
`analysis_format` remain alongside it. Unknown or malformed codes have no
readable expansion. The decoder follows [PerseusDL's morphology tagset](https://github.com/PerseusDL/treebank_data/blob/master/AGDT2/guidelines/Greek_guidelines.md)
and [Perseus's nine-slot code description](https://nlp.perseus.tufts.edu/docs/latech.pdf).
This expansion describes a source annotation, not the chosen contextual
meaning or the syntactic role of the word in the reader's passage.

When no exact indexed form or headword matches, edit-distance results are
spelling suggestions only. The API sets
`analysis_match_status: "spelling_suggestions_only"` and puts a prominent
warning first: analyses belong to nearby spellings, not necessarily to the
queried form. Each candidate identifies its actual `matched_form`,
`match_kind`, `edit_distance`, and source spelling in `reason`. The original
query is never assigned a nearby form's grammatical parse.

The two JSONL files are authoritative. `data/lexicon.json` is an old visual
sample and is intentionally excluded. The reader should state missing form
coverage and show all plausible readings to the user.
