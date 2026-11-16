# PRD: Catullan hendecasyllable composer checks (2026-11-15)

Branch `catullan-composer` (from `latin-composer` 73ed499). Owner request, 2026-11-15: the Latin twin of the Greek
composer must be as strict for Catullus's Phalaecian hendecasyllables as the Greek one is for Sapphics: accurate
Latin, scanned the way late Republican verse scans, every word, phrase and image in Catullus's manner, and every
quantity vetted against where the word actually stands in Catullus (then Virgil).

## What exists (latin-composer, 2026-10-10)

Scanner (`backend/scansion/*_la.py`, `rules_la.yaml`, `metres_la.yaml`, quantity lexicon of 1.07 M forms), held-out
Catullan hendecasyllables 284 of 285 accepted; Catullus and Horace in `data/corpus_la.sqlite`; LASLA lemma index;
lints L7 metre, L1 forms, L4 attestation, L11 verbatim; audited interlinear; agent tools `la_concordance`, `la_forms`,
`la_lemma`.

## What this PRD adds

Lint numbers follow `docs/composer/loop-design.md` where a Greek counterpart exists.

| id | name | what it decides | blocks |
|---|---|---|---|
| L12 | prosody attestation | each word's quantities as the line uses them, against every place the form (then its stem) stands in Catullus, then Virgil, in the Hypotactic hand scansion; mute + liquid, final -o, iambic shortening and synizesis variants shown with loci | a quantity the poets never use blocks; an unattested form warns |
| L13 | Phalaecian manner | base (spondee / trochee / iamb), word-end after the 5th or 6th syllable, elisions, line-end word shape, against a profile counted from all Catullus's hendecasyllables | never |
| L8 | elision and hiatus | hiatus, elision of a monosyllable, prodelision, as Catullus allows them | hiatus blocks |
| L3 | agreement | preposition + case, adjective / noun, subject / verb, from the morphological readings | warns |
| L10 | word order | enclitics and postpositives in a possible place | warns |
| L14 | period and register | Lewis & Short entry: authors cited, ante-/post-classical and late labels; a word with no author before A.D. 14 warns | never |
| L5 | collocation | word pairs printed together in Catullus (then Horace, Virgil) | never |
| L6 | manner evidence | where the word and its lemma stand in Catullus (polymetrics 1-60, long poems, epigrams), line position, diminutives and urbane vocabulary counted from the corpus | never |

Reference stores, each with a lookup function, an API route and an agent tool: Lewis & Short (whole dictionary),
Merrill's commentary and introduction (1893, public domain), Allen & Greenough's New Latin Grammar (public domain).
A critic prompt for the best model (style, imagery, idiom, grammar in context) that must cite these stores.
One command, `scripts/la_check.py`, runs every check on a draft and prints one report.

## Contract (every new check)

`check(text, *, metre_name="phalaecian", author="Catullus") -> {"id", "name", "ok", "blocking", "detail", "evidence"}`
as in `backend/composer_lint.py`; `text` may hold several lines; a missing data file returns `ok: True` with
`detail` beginning `unavailable:`; nothing raises.

## Acceptance

1. Every genuine Catullan hendecasyllable in the Hypotactic gold is run through the scanner and L12/L13; the
   false-alarm rate is reported per check, and every line the scanner rejects is listed with its cause.
2. A perturbed line (one quantity broken) is caught by L7 or L12.
3. Each check has tests; the earlier Latin tests still pass.
4. A fresh five-line poem is composed with the loop and passes every blocking check, with the report kept.

## Not in this pass

Thesaurus Linguae Latinae and the Oxford Latin Dictionary (survey of open access only); Ellis's and Fordyce's
commentaries; deployment to greeklyric.com.
