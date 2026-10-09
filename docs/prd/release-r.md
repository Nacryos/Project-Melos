# Release R brief (owner, 2026-10-09)

Standing goal: every word and phrase in the Alcaeus and Sappho fragments, and ideally every fragment, is
accurately parsed in full, ranked by morphology, with multi-word breakdowns. Fix with general rules, never
per-word patches.

1. **Lyric gold set.** A hand-checkable gold set of lemma + parse for lyric, starting from the five audited
   Alcaeus poems (`data/campbell_glp/alcaeus_five_corrections.json`) and Campbell's commentary, plus
   Sappho 1, 16, 31, 34, 44, 94, 96 and Alcaeus 130b, 346, 347. Evidence only from Campbell's notes, LSJ
   entries for the form, Aeolic grammar in the project docs; unclear tokens marked uncertain. Hold out half.
   Report lemma and full-parse accuracy on lyric, before and after.
2. **Aeolic rules**, general, measured on the gold set: αἰ = εἰ; κε/κεν = ἄν; ἀ- for ἡ- (article ἀ = ἡ);
   -οισα participles; -μμι verbs (ἔμμι = εἰμί, φίλημι = φιλέω); infinitives in -ην/-μεναι; datives in
   -αισι/-οισι; psilosis; barytone accent; πεδά = μετά; ὀνίαισι, τύιδε and similar. Find and fix other
   systematic Aeolic and Doric error classes in the gold set.
3. **Derived forms.** Adverbs in -ως link to their adjective (ταχέως → ταχύς); comparatives and superlatives to
   the positive. Lemma, glosses and calibration use the link.
4. **Variant links.** Restore genuine links lost in Q (γαῖα/γῆ and similar) without the false ones (ἅλιος/ἥλιος,
   πᾶς/πατήρ, κοῦρος/κόρος): sense agreement plus dictionary cross-reference evidence; report precision on a
   hand-checked sample.
5. **Calibration** with genre and dialect as features, the lyric gold set in the training half; reliability bins
   for lyric reported separately.
6. **Human check.** Live reader, 10 Alcaeus and 10 Sappho fragments, Python Playwright headless at 1440x900 and
   390x844, real clicks; every word clicked in 4 of them (headword, gloss, parse, multi-word breakdown). Fix what
   is wrong or confusing with general rules (backend for data, frontend for small UI issues; Vercel deploy with a
   rollback URL recorded).
7. **Release R** in the usual way (canary 8792, smoke, 237 poems identical, span check, 42-query evaluation,
   sampler seeds, citation test, memory), promote, release record in `docs/deployment.md`.

Constraints: no personal data in requests to external sites (generic User-Agent "Melos/1.0
(+https://greeklyric.com)"); commit without Co-Authored-By lines, do not push, never commit
`assets/edition-excerpts/` or `sources/`; on the box never pkill broadly or touch other sessions' trees.
