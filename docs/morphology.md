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

## Full parses for every printed word (2026-10-07)

**Editor's reading.** `tokenize_span` keeps one word token for a printed word
interrupted by square brackets (νᾶ̣]σον, θύ[μ]ῳ, λίποντε[ς). `token.text` is
the lossless printed span; `token.form` is the editor's reading with brackets
and underdots removed, and every lookup (dictionary, Morpheus, Jev, subentries)
uses `form`. `editorial_reconstruction`, `supplied_letters`,
`supplied_whole_word` and `uncertain_letters` label what the editor supplied or
doubted. Pieces around a lacuna of unknown length (α…β, α†β) stay
`editorial_fragment` and are never joined. The syntax provider drops the same
brackets from its analysis view and maps its offsets back to the source, so the
prediction covers the whole printed word.

**Parser coverage.** `scripts/warm_morphology_forms.py` fetches Morpheus
receipts for every word of given passages (plus the normalisations below) into
a cache database that `deploy/sync_morphology_receipts.py` can export and
import. `POST /api/passage-morphology/warm {passage_id, max_fetches≤10}` does
the same progressively for an opened passage under a server-side visitor
identity; the reader calls it once per opened Greek text, and single-word
clicks request a fetch for the clicked form.

**Aeolic normalisations** (`backend/aeolic_variants.py`). When the exact printed
form has no analysis, a few labelled spelling rules produce query variants:
psilotic rho and psilosis (ῤήα→ῥήα, ὐπ’→ὑπ’), apocope of ἀνα-/κατα-/μετα-
(ὀντρέχοντες→ἀνατρέχοντες), the Lesbian recessive accent (τήλοθεν→τηλόθεν),
gemination (Ἐρίννυς→Ἐρίνυς), -ζω for -σσω, and ὄνυμα for ὄνομα. Every parse
obtained this way carries `normalised_query`, `normalisation_rule` and
`normalisation_note`, is labelled `machine_analysis_normalised`, and ranks
below any analysis of the exact printed form.

**Last tier** (`backend/pattern_morphology.py`, `PassageAnalysisService._last_tier`).
A word that no source attests, no parser knows and no normalisation rescues
gets labelled ending-based analyses (`candidate_kind: pattern_analysis`, no
lemma, no gloss, a note naming the ending; machine status `ok_pattern`), using
the contextual prediction's part of speech to pick the nominal or verbal table.
Letters surviving beside a lacuna (one or two letters, or any run that no
analysis of the exact letters fits) are labelled `damaged_piece`: they are not
counted as words, not selected, and the reader says so. A lacuna-adjacent word
with doubtfully read edge letters (ς̣βιότοις̣) is also queried without those
edge letters (`uncertain_edge_letters_dropped_*`) and shown conditionally.
A short Lesbian lexical table (ἤπειτα → ἔπειτα, κῆνος → ἐκεῖνος, …) and the
rules elision-mark-dropped, ὀ-/οἰ-, η/ει and circumflex-for-acute complete the
normalisations.

**Ranking by morphology** (`backend/interlinear.py`). Candidate parses are
ranked by `_affinity`: +1 per grammatical feature agreeing with the contextual
prediction, −1.5 per stated disagreement, +1 for lemma agreement, +0.1 per
additional feature the candidate states (a full parse beats a partial one),
±0.75 per case/number/gender agreement with the predicted head noun or
modifiers (`_agreement_partners`), +0.25 for an Aeolic dialect label, −0.5 for
a normalised query. A differing predicted lemma is a ranking signal and a
flagged `syntax_conflict`, never a veto (the model mislemmatises dialect
spellings). Selection bases: `unique_compatible_candidate`,
`morphology_ranked_by_syntax`, `morphology_ranked_despite_syntax_conflict`
(best parse still agrees on something), `single_candidate_despite_syntax_conflict`
(only one full parse exists), `morphology_ranked_parse_consensus` (tied
candidates share a parse, lemma left open), then the older consensus and
prediction fallbacks. Every word row carries `morphology_ranking`, the ordered
list with scores, which the reader shows as "Parses ranked by fit to the
context".

## Random-sample fixes across all Campbell GLP poems (release M, 2026-10-08)

Measured with `scripts/sample_glp_quality.py` (random 1–6 word spans from all
237 `campbell-glp` passages, stratified by dialect group and poet; each word row
scored for complete parse fields, a lemma, a short gloss, a plausible gloss and
a plausible lemma, with a failure class). Every fix below is a rule or a lookup
improvement, never an answer for a sampled word; unit tests use other words
(`tests/test_glp_quality_rules.py`).

**Lemma → headword** (`backend/lemma_glosses.py`, tried in order and labelled in
`gloss.lemma_dictionary.lemma_normalisation`): macrons/breves and stray leading
breathings or apostrophes removed from parser lemmas (πῑ́νω, ̓Αλέξανδρος); an
elided lemma (τ’) restored to the one headword its stem can be, or to the
contextual model's lemma when that is one of the restorations; a lemma that is
itself a recorded inflected form (Μοῦσαι) read back to the one lemma its
recorded analyses name (`Morphology.form_lemmas`); Lesbian psilosis in the
lemma (ὀ → ὁ); a table of dialect correspondences (Ionic η/Attic ᾱ, Doric ᾱ/η,
ει/ε, ου/ο, σσ/ττ, ρσ/ρρ, Doric ω and Aeolic οι for ου, Ionic ευ for ου) that
must land on a printed headword. Folded (accentless) matches that cover
several accent-distinct headwords are not used.

**Contextual-model lemma.** A word with no parser or source lemma may take the
odyCy model's lemma when it is a printed dictionary headword, shares a run of
letters (or its consonant skeleton) with the word, the word has at least three
letters, and no ranked parser lemma contradicts it. Labelled
`lemma_source.basis = syntax_model_lemma_dictionary_headword`; the gloss is
`syntax_model_lemma_dictionary_headword_first_sense_not_contextual`.

**Recorded spellings of labelled variants** (`PassageAnalysisService._recorded_form_variants`,
`aeolic_variants.offline_variants`). When the parser has no receipt or no
analysis and the source index has no parse of the printed form, labelled
variants are looked up as recorded forms (at most 40 lookups per request): the
Aeolic parser normalisations, the elided vowel restored (ἀλλ’ → ἀλλά, every
short vowel tried), the second word of a crasis (κἀγώ → ἐγώ, τοὔνομα → ὄνομα,
χὠ → ὁ), and Doric/Aeolic ᾱ for η (νάσω → νήσω). A recorded analysis of the
variant is listed with `candidate_kind: source_analysis_normalised`, its rule and
the variant spelling, and ranks below any exact analysis.

**Choosing the gloss.** A sense that is only grammatical metalanguage
("comparative", "Adv.") is skipped; a preposition does not take a sense the
dictionary labels adverbial (and vice versa); and the head phrase another
dictionary prints word-for-word is preferred (`short_gloss.corroborated_choice`):
Middle Liddell's Latin equivalent "alius" yields to "another", and a first
sense found in no other entry yields to the next dictionary's confirmed one.
The gloss stays the dictionary's own words with its source.

**Part of speech.** The contextual model's SCONJ, PROPN, AUX and INTJ classes
are now kept (they were dropped, leaving πρίν with no class); SCONJ~CCONJ,
PROPN~NOUN and AUX~VERB count as the same class in ranking.

**Parser receipts.** `scripts/warm_morphology_forms.py --order frequency`
fetches the most frequent forms first under the daily budget; 870 new
receipts for GLP forms ship with release M.
