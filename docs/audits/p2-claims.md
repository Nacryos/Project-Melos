# Phase-two structured claim audit

## Verdict

**PASS for the exact claim and author-profile hashes in
`data/reports/p2-claim-acceptance.json`.** The independent gate is
`python scripts/audit_p2_claims.py`. It checks source artifacts, accepted
parent records, quotes, JSON pointers or TEI byte spans, source-specific claim
objects, and original-passage Unicode offsets. Acceptance requires a separate
manual decision and is revoked when file bytes change. The derived evidence
database may ingest only claims with a `PASS` verdict and matching SHA-256.

| Accepted output | Records | SHA-256 |
| --- | ---: | --- |
| `p2_notes.jsonl` | 1,214 | `c46fce81f2c76e8a4744d755790c7ccaf5df1d51a56607884aa96b64e369fb1b` |
| `p2_apparatus.jsonl` | 7,868 | `0200725be237696e0f4f3dcc15ca0f0e33025b81fe41d3252d942a95c50e5a7d` |
| `p2_grammar.jsonl` | 22 | `3d09bfaa929f027a34e736d9a8eedd76e1c54bf8ddc7f200c60a0b814d0fa694` |
| `p2_wiktionary.jsonl` | 289,208 | `42b022848f10329603078090adb7d955a794c080cda546bf70cc812336724514` |
| `p2_authors.jsonl` | 104 | `83b0afb4334050083efa4e39cd56ec5f8c065ea187d2574aeda0f624b8d163cf` |
| `p2-author-profiles.json` (metadata) | 11 | `67551fed5c35ae8fa5c000428eb369e7d6016b6128d43de1f8d59ff37eb0c220` |

## Evidence checks

The source and rights decisions are in `docs/audits/p2-sources.md` and
`docs/audits/p2-edition-sources.md`. Previously accepted Sappho, Perseus,
DCLP, and Wiktionary inputs are bound to their existing acceptance manifests;
the new DCC grammar parent is bound to `data/reports/p2-text-acceptance.json`.
The audit compares saved raw SHA-256 and source URLs, reads accepted parent
records at their exact output hashes, and rejects missing or changed parents.
Collectors have no acceptance authority.

| Extraction stage | Independent result |
| --- | --- |
| Source discovery/download | Source- and edition-audit decisions checked; pinned saved artifacts and raw hashes verified. No new source is inferred from claim text. |
| Parsing/transformation | All claim JSONL parsed; every evidence quote found in its accepted parent, exact raw byte span, or JSON-pointer source value. Source-specific objects compared with original TEI or complete Wiktionary entry fields. |
| Output/integration | Required claim fields, IDs, source families, predicates, status, and assertion layers checked; exact output SHA-256 and counts bound to acceptance manifest. |
| Final trace | All 289,208 Wiktionary claims checked against source pointer and object, including 1,611,458 retained form rows. All 7,868 TEI quote byte spans and element tags/attributes checked. All 1,214 note quotes and 483 linked original Unicode slices checked. All 104 author claims and 11 profiles checked. |

The first notes pass rejected 62 normalized spellings stored as if they were
exact passage substrings. The collector repaired the subject forms and then
removed two false glosses; the final 1,214-record file was re-audited at its
new hash. Eleven ambiguous note matches remain form-only, with no passage
offset. Fifteen seeded note samples were inspected across gloss, morphology,
and explicit form-equivalence claims.

The apparatus pass also exposed an overbroad predicate: only 119 `<app>`
elements state explicit alternatives. The remaining 7,749 `<gap>`,
`<supplied>`, `<unclear>`, `<add>`, and `<del>` records now have the distinct
`editorial_state` predicate. They are source-local edition/witness states,
not proven readings of a different edition or the ancient archetype. Nested
markup and raw sigla remain in their source objects.

The DCC/Goodell grammar claims retain source table cells and qualified
author-level literary dialect descriptions. They do not assert that every
Aeolic reference form occurs in Sappho, classify a passage token from an
author label, or infer a universal substitution from a table juxtaposition.
Wiktionary dialect tags likewise remain dictionary annotation scoped to a
particular source form or sense. Form lists include table labels,
romanization, and alternative forms in source order; they are not lyric
attestations. All Wiktionary sense objects, relationship targets, tags,
headword labels, inflection templates, and form arrays were compared to the
accepted parent entry.

The 11 author profiles point through 99 exact alias claims and five
literary-dialect claims to source identity or broad context. CTS/TLG
identifiers, 33 source descriptions, and profile evidence IDs were checked.
Unresolved mixed or uncertain corpus author labels remain unresolved. The
profiles do not adjudicate the authorship of an individual passage.

## Limits

This PASS certifies source reproduction, scoped mapping, and provenance at
the listed hashes, not the philological truth of every dictionary entry or
editorial proposal. Kaikki is a postprocessed Wiktionary export with merged
fields whose per-field rights remain unresolved in the parent source audit.
The grammar is historical source commentary, and apparatus alternatives are
attributed edition claims. Model proposals are a separate inference layer;
none of these accepted files turns a model score or similarity into a source
claim.
