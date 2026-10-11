# Latin open sources, survey pass A (2026-10-10/11)

Method as in `docs/open-sources-survey-2026-10-09.md`: every fetch with `User-Agent: Melos/1.0 (+https://greeklyric.com)`,
robots.txt honoured (Zenodo's `/api/` is disallowed, so Zenodo was reached only through web search), no logins, nothing
over 50 MB downloaded (Lewis & Short XML and the Kaikki Latin dump were sized, not fetched), licences quoted verbatim from
the fetched page or file with its sha256 (`rows-a.jsonl`; raw pages and `fetch-log.jsonl` in the session scratchpad
`survey-a/`). Anything not verified that way says "unverified". Rows: 22.

| Resource | Approach / what it is | Licence (quoted in rows-a.jsonl) | Accuracy claimed | What we can take |
|---|---|---|---|---|
| **Hypotactic Latin** (Chamberlain) | Hand scansion as static HTML: `div.poem[data-author,data-metre,data-number,data-work]` > `div.line` > `span.word` > `span.syll.{long,short,elided}` + modifier classes (hiatus, synizesis, lengthening, diastole, systole, resolved res1/res2, hypermetric, semihiatus, halffoot) | **CC BY 4.0**, stated on hypotactic.com/latin/about.html itself: "All the data on this site is/are licensed as CC-BY 4.0 …" | hand-made, no error rate | **Gold.** catullus.html: 118 poems (1–116 + 2b, 14b, 58b; 18–20 absent as in editions), 2,301 lines, 29,528 syllables; odes1.html: 38 poems, 876 lines. Odes 1–4, Epodes, Sermones, Epistulae, Ars in the menu; Carmen Saeculare absent. Site zip 29 MB |
| **Pedecerto / MQDQ** | Machine scansion of the MQDQ corpus; XML per author and `allpedecertoscans.zip` (12.0 MB, 2025-08-18) offered on the site; only hexameter (H) and pentameter (P) lines analysed; word attrs sy/wb/mf (synaloephe, hiatus, prodelision, s caduca) | "Tutti i diritti riservati"; non-commercial only; offline reproduction "ad esclusivo uso scientifico, didattico o documentario"; mirroring and automatic capture forbidden without agreement | none stated | **ask_author** (mqdq-galaxy@unive.it) before any use; covers Catullus 62/64/65–116 and Horace's hexameters only, so not the hendecasyllable gold anyway |
| **Winge, latin-macronizer** `macrons.txt` | RFTagger (LDT) + lookup in a Morpheus-generated lexicon; 812,588 rows / 283,023 forms, TSV `form, tag, lemma, form_with_ _/^`; separable data file | repo **GPL-3.0** (LICENSE + README); no data licence; content = Perseus Morpheus output (CC BY-SA 3.0 US) + overrides | site: "about 98% to 99%"; thesis: "about 98% of the vowel lengths" on four texts | **ask_author** for data terms; use now for coverage/eval. Best form-level macron table that exists |
| **CLTK** `prosody.lat` + `lat_models_cltk/taggers/macrons` | Rule scanners (hexameter, pentameter, hendecasyllable; v1.5.0, MIT) and a POS-tag macronizer over `vowel_len_map`; its `macrons.txt` (755,557 rows, 257,615 forms, committed 2016-07-23) is a 2016 snapshot of Winge's file (same format, same first rows, 348,182 rows shared) | **MIT** (code and models repos) — but the data is Morpheus-derived, so keep Perseus attribution/share-alike | none in source | evaluate_only for the scanners (pin `cltk==1.5.1`; **CLTK 2.x has no prosody module**); the data is superseded by Winge's current file |
| **Collatinus** lexicon | Lemma lexicon with quantities as precomposed ā/ă: `lemmes.la` 24,072 rows (LASLA core), `lem_ext.la` 57,909 rows (collated from L&S, Gaffiot 2016 by permission, Georges, Jeanneau), `modeles.la` paradigms with ending quantities, `irregs.la` | **GPL-2.0-or-later in every data file header** (© Ouvrard 2011–2017; lem_ext © Verkerk 2015); repo GPL-3 | none | **use** (derived table stays GPL-compatible, attributed); quantities are lemma + paradigm, so forms must be generated |
| **Perseus Morpheus** stemlib | Upstream of every Latin macron list | **CC BY-SA 3.0 US** (PerseusDL/morpheus README) | — | use: regenerate a form list if Winge declines |
| **Wiktionary Latin** (Kaikki) | 842,381 distinct word forms; JSONL 1.1 GB; headwords and inflection tables carry macrons (amo page: amō, amōnis, amōnēs) | **CC BY-SA + GFDL** (kaikki.org/dictionary/ and Wiktionary:Copyrights) | crowd-sourced | **use**; same pipeline as the Greek extraction |
| **Lewis & Short** (PerseusDL/lexica) | TEI XML 77.4 MB; `<orth>` carries breves/macrons (250 of the first 319) | **CC BY-SA 4.0** with Perseus credit line | — | use (lemma-level); fetch when disk allows |
| **Gaffiot 2016** (Gréco) | Headwords with quantities; gaffiot.fr serves a 21.6 MB JS blob "Tous droits réservés" | **CC BY-NC-ND 4.0**, Wiktionary excluded (Gréco's page, Wayback copy) | — | no (ND/NC); its lemmas reach us only via Collatinus `lem_ext.la` |
| **Whitaker's Words** | Dictionary + morphology, "does not currently support vowel length" | permissive: "Permission is hereby freely given for any and all use of program and data" | — | no for quantities (lemmatiser fallback at most) |
| **Anceps** (Fedchin) | Metre-as-constraint scanner over Winge's lexicon + MQDQ frequency dictionaries (`MqDqMacrons.json` 18.9 MB); manual scansions only for Seneca *Agamemnon* | **no licence file** (unverified) | "around 10%" of trimeters need a human | ask_author; the method is already ours |
| **latin_scansion** (CUNY-CL) | Pynini FST grammars for Virgil's hexameter | **Apache-2.0** | none | evaluate_only (hexameter baseline) |
| **Scandroid** (Hartman) | "scans metrical English verse" | GPL | — | no (English only; no Latin version) |
| Ycreak NN scanner / Nolden thesis; Signatrix; latin-scanner (npm MIT); LASY (MIT); 20-odd student scanners; porphyrii | Hexameter toys, NN experiments on Pedecerto data, forks of Winge | mostly none/unverified | none | no |
| KaanGoker HF hexameter corpus; macronised texts on GitHub (Nova Vulgata by hand; Latin Library auto) | Texts, not scansions | MIT / none | — | no (Nova Vulgata: ask if an eval text is wanted) |
| Logeion | — | none published | — | no (off limits) |

## Findings that matter

**1. Hypotactic Latin is the gold set, and its licence is now verified on the Latin side.** The Latin `about.html`
carries Chamberlain's full CC BY 4.0 statement (the Greek survey only had it second-hand from the Urdatorn README). Files
are `https://hypotactic.com/latin/<id>.html`; ids come from `authors.html` (`loadup('catullus')`, `odes1`–`odes4`,
`epodes`, `arspoetica`, …). The whole of Catullus is one file (sha256 `ff1ac5d6…14b8`, 3,037 lines): 43 hendecasyllable
poems, 54 elegiac, 8 scazon, 2 Sapphic (`sapadon`), 2 glyconic/pherecratean, galliambic, priapean, etc. Each syllable is
`<span class="syll long|short|elided">` with the letters kept (elided syllables are tagged, not deleted), macrons in the
text, and rare phenomena as extra classes. `odes1.html` (sha256 `3ea6ee35…6901`) has all 38 odes with per-poem metre
ids (alcaic, sapadon, asc1–5, alcmanic_strophe, arch4, sapphic2) and per-line ids inside stanzas (`line glyconic`, `line
iambic`, `line d4_tr3`). Epodes have their own file; **Carmen Saeculare is not in the menu**. A 29 MB zip of the Latin
data (17 Jun 2025) exists for a later full ingest; this pass fetched only the two files asked for.

**2. The best macronised lexicon we can legally use today is Collatinus + Wiktionary; Winge's file needs one email.**
Winge's `macrons.txt` (812k rows, every inflected form, `_`/`^` marks) is the richest and is a plain separable TSV, but
the repo licenses only the code (GPL-3) and the data is Morpheus output (Perseus CC BY-SA 3.0 US) plus his overrides —
no statement covers redistribution of a derived table. CLTK's "MIT" copy is the same data frozen in 2016 and does not
launder it. Collatinus is the one source whose data files state their own licence (GPL-2+ headers, 82k lemmas with
quantities and paradigm models), and Wiktionary via Kaikki (CC BY-SA, 842k forms with macrons in headwords and tables)
is the one per-form source with a clean licence. Lewis & Short `<orth>` (CC BY-SA 4.0) adds lemma-level marks. Gaffiot
2016 is CC BY-NC-ND and out. Plan: build `quantities_la.sqlite` from Wiktionary + Collatinus (+ L&S), run Winge's file as
an evaluation/coverage comparator, and ask Winge whether the table may be redistributed under CC BY-SA like its source.

**3. Pedecerto may not be used without asking.** Its scansions are downloadable from the site (per-author XML and a
12 MB zip), but the footer terms reserve all rights, forbid commercial use without agreement, forbid mirroring and
automatic capture, and permit only offline reproduction for scientific/teaching use. An offline evaluation is arguably
"uso scientifico", yet greeklyric.com is a product, so the PRD's "second gold set" needs written permission from
mqdq-galaxy@unive.it. It would in any case only cover dactylic lines (H/P), not the Catullan hendecasyllables.

**4. CLTK dropped its prosody module.** CLTK 2.x (PyPI 2.5.1) has no `cltk.prosody`; the hexameter, pentameter and
hendecasyllable scanners exist only up to v1.5.1 (MIT, Todd Cook), make no accuracy claim, and fit a single template
deterministically. They remain a cheap baseline to score on the Hypotactic gold, nothing more. No open Latin scanner
found (CLTK, anceps, CUNY FST, a score of student projects) publishes a measured accuracy on a hand-scanned gold set.

Paths: `data/open/latin/survey-2026-10-10/rows-a.jsonl` (22 rows), this file; raw fetches and `fetch-log.jsonl` under the
session scratchpad `survey-a/` (not in git).
