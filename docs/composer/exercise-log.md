# Composer exercise: one Sapphic stanza built with Melos tools only

Date: 2026-10-09 (Pacific). Live API https://greeklyric.com, generic User-Agent, one request at a time with a
1.1 s gap (48 calls). The scanner is not deployed. The `/api/scan` steps were emulated by running the work
tree of the `scansion` branch (`C:\Users\alvin\melos-scansion`, layer 1 quantities with the quantity lexicon,
plus layer 2 `metre.fit(..., "sapphic")`) read-only on the laptop. Raw responses were kept in the session
scratchpad and are not committed.

**English source (written for the exercise):** *The moon shows over the sea; / and longing shakes my heart
again; / Atthis, you are far away and do not see me; / I sleep alone.*

## Result

```
φαίνεται πόντῳ πέρι νῦν σελάννα,        –⏑–––⏑⏑–⏑––   fits
καὶ πόθος θῦμόν με δόνει μάλ’ αὖτε·      –⏑–––⏑⏑–⏑––   fits
Ἄτθι, πήλοθεν δὲ σὺ μ’ οὐκ ὄρησθα·      –⏑–⏑–⏑⏑–⏑––   fits
νύκτα κατεύδω.                          –⏑⏑––         fits
```

It took three drafts. Every repair came from a tool finding (see the timeline). "Alone" was lost in line 4,
because no adonic shape for μόνα or αὔτα fits. A human would carry it into line 3 instead.

Parallels the tools found for each image:

| Image | Parallel | Tool and call |
|---|---|---|
| Moon over the sea | Sappho 96 (σελάννα … φάος δ’ ἐπίσχει θάλασσαν ἐπ’ ἀλμύραν); 34; 154 | concept #3, themes search #6, proximity #41 |
| Longing (or Eros) shakes | 130 (Ἔρος δηὖτέ μ’ ὀ λυσιμέλης δόνει); 47 (Ἔρος δ’ ἐτίναξέ μοι φρένας); 22 (πόθος … ἀμφιπόταται) | hybrid search #7, forms search #43, proximity #45 |
| Atthis, absent | 131 (Ἄτθι, σοὶ δ’ ἔμεθεν μὲν ἀπήχθετο); 96 | lemma search #39, hybrid search #48 |
| Lying alone at night | 168B (ἔγω δὲ μόνα κατεύδω) | themes search #6, lemma search #15–16 |
| πήλοθεν (Lesbian for τηλόθεν) | Alcaeus 34a | lemma search, genre "melic lyric" #37 |

## Call timeline

Times are the server round trip measured from the laptop.

| # | Call | ms | What it gave | What was missing or awkward |
|---|---|---|---|---|
| 1–2 | `GET /api/status`, `/api/lemma/status` | 675, 354 | 288,821 passages; 52,775 headwords, 3.9 M tokens | — |
| 3 | `concept/diachrony?q=moon` | 2528 | σελήνη, μήνη first, with Sappho 154, 96, 34 as examples; dropped Ἰώ and Οὐρανία | No `author=` or `genre=` filter. The 185 kB answer is periods-first; the composer wants "Sappho's words for X". `max_lemmas` was ignored (10 came back for 6). |
| 4 | `concept/diachrony?q=longing` | 2209 | πόθος first | Noise: μακρός, λέων ("a lion's skin"), κῦμα (the "long" stem). **ἵμερος is missing**, though `lemma/resolve` gives it (#28). |
| 5 | `concept/diachrony?q=desire` | 1395 | ἔρως, πόθος, ἱμείρω, λιλαίομαι | θέλημα (1 token) ranked first: the score does not discount tiny counts. |
| 6 | `search mode=themes author=Sappho` "moon shining over the sea at night" | 1598 | Excellent: 96, 30, 154, 168B, 34, 151 | Whole passages only, with no line or span. The "Fragment 96" vs "154" labelling mixes numberings. |
| 7 | `search mode=hybrid author=Sappho` "longing loosens my limbs" | 1256 | 130 (λυσιμέλης), 48 (πόθῳ), 1, 26 | — |
| 8 | `POST words/headlines {forms:[25 draft forms]}` | 420 | Most forms parsed in 1 call | **θῦμόν** (accent thrown back by the enclitic) is unknown. **εὔδω** (psilosis) is unknown. **σελάννα** is read only as a *dual*. **μόνα / μοῦνα** only as neut. pl. (no Aeolic fem. sg. in ᾱ). **αὖτε** → αὐτός voc. **Ἄτθι** glossed "Attic". The invented ὀρήσθα / ὄρησθα are unknown (correct). No per-author attestation flag. |
| 9–11 | `lemma/frequency` σελήνη, πόθος, δονέω | 438–505 | Per-author rates with CI: Sappho is the top user of σελήνη and πόθος | **Sappho = 13 tokens for both σελήνη and πόθος, but the concordance has 4 and 5 loci** (#12–13). These author counts do not look edition-folded. |
| 12–13 | `lemma/concordance author=Sappho` | 448, 428 | Clean KWIC: 154, 168B, 34, 96; 102, 22, 48, 94 | 94 is also listed as "απ. 94 Lobel-Page" (fold missed a renumbered copy) |
| 14–16 | `lemma/search author=Sappho` σελήνη, μόνος, καθεύδω | 464–744 | `forms_found` is the author's form inventory: σελάννα, σελάνναν; μόνα; κατεύδω. This is the most useful attestation tool. | **Counts are per record, not per locus**: σελάννα shows 12 for 4 loci; μόνα shows 4 for 1 locus (168B appears 3 times, plus adesp. 976). |
| 17–20 | `lemma/variants` σελήνη, μόνος, θυμός, ἔρως | 285–823 | ἔρως ↔ ἔρος, Ἔρως linked | Dictionary-headword links only. There is **no generator for "the Lesbian spelling of X"** (σελήνη → σελάννα, θυμός → θῦμος, τηλόθεν → πήλοθεν). |
| 21–22 | `lemma/collocations` πόθος (melic), σελήνη (Sappho) | 342, 440 | Real Sapphic neighbours: ἀποκρύπτω, ἀστήρ, Πλειάδες, ῥοδοδάκτυλος | **Edition duplicates inflate counts**: κρέκω / ἱστός ×4 come from the single fr. 102, and ἀποκρύπτω ×4 from the single fr. 34 |
| 23–26 | `lemma/ngrams` Sappho n=2; `q=πόθος`; genre `q=σελήνη` | 271–403 | γῆ μέλας, ἐπί ἁλμυρός, δονέω γλυκύπικρος | Same ×4 inflation: every line of fr. 1 and fr. 2 reaches count 4 and G² 70.8. **Lemma n-grams only**: no surface-form or metrical-shape n-grams. |
| 27 | `word?form=δονέω&lemma=δονέω&compact=true` | 292 | Middle Liddell senses (shake; drive about) | `author_profile` is null; `attested_forms` is empty in compact mode |
| 28–29 | `lemma/resolve` longing, alone | 290, 300 | πόθος, ἵμερος; μόνος | **οἶος "alone" has 1 token** in the whole index (its tokens are presumably absorbed by οἷος "such as") |
| 30 | `cite?q=Sappho 96 V` | 347 | campbell-glp:sappho:96, strength `convention` with a warning | The answer is one record. Line-level loci for a parallel inside a 20-line fragment are not returned. |
| 31 | `POST machine-analysis ὄρησθα` | 431 | ὁράω pres. ind. 2nd sg., dial. "epic Aeolic" (local Morpheus) | It works, but it is **rate-limited (20 a day per visitor)**. A composer checks hundreds of candidate forms per line. |
| 32 | `POST machine-analysis θῦμόν` | 442 | θυμός | The index lookup (#8) failed on the same form |
| 33 | `lemma/frequency` ἄμμορος | 347 | Nonnus 13, Homer 4, Pindar 2; Sappho 0 | (good: shows "not Sapphic, epic") |
| 34, 36 | `lemma/search εὕδω author=Sappho`; `machine-analysis εὔδω` | 585, 416 | none; `no_analyses` | The psilotic Lesbian spelling cannot be parsed; only κατεύδω is attested |
| 35 | `lemma/search ὁράω author=Sappho` | 868 | ἴδην, ἴδωμεν, ὄρημ’, ὄρημμ’ | Confirms the athematic Lesbian ὄρημι conjugation; this supports ὄρησθα indirectly |
| 37 | `lemma/search τηλόθεν genre=melic lyric` | 330 | **πήλοθεν** (Alcaeus 34a): the Lesbian labial reflex, found by luck | A dialect linter needs this as a rule, not luck |
| 38 | `search mode=words τήλοθεν` | 633 | 87 hits, all epic or Hellenistic | — |
| 39 | `lemma/search Ἀτθίς author=Sappho` | 453 | Ἄτθι ×9, Ἄτθιδος, 131, 49, 8 | — |
| 40, 42 | `lemma/proximity` ἔρως+τινάσσω (Sappho); θυμός+δονέω (melic) | 410, 319 | **0 hits**, although fr. 47 has Ἔρος … ἐτίναξε | ἔρος and Ἔρος are separate headwords. `combine_variants` is off by default. |
| 41 | `lemma/proximity` σελήνη+θάλασσα (Sappho, window 12) | 444 | fr. 96 span | — |
| 43 | `search mode=forms ἐτίναξε author=Sappho` | 355 | fr. 47 in 3 copies | — |
| 44–46 | proximity ἔρως+δονέω, plus `combine_variants=true`; ἔρος+δονέω | 344–552 | With variants: Sappho 130 and Bion 6.5 | The default misses Sappho's best parallel |
| 47 | `POST words/headlines {passage_id: Sappho 154}` | 294 | In context: σελάννα is still "nom. fem. du.", and πλήρης is "acc. masc. pl." | The release R dialect gates apply in `analyze-passage`, not in the headline index. **No text-only analysis exists**: `analyze-passage` needs a stored `passage_id`, so a draft cannot be parsed in context or syntax-checked. |
| 48 | hybrid search for the moon-simile commentary | 1299 | 34, 31, 68a, 96, 131 | Commentary appears only as a retrieval bridge; no commentary passage itself was returned |

## Scanner emulation (POST /api/scan stand-in)

The scansion work tree loads in 55–140 ms and scans and fits a stanza in 5–46 ms. Checked first on Sappho 1.1–4:
all four lines fit (`–⏑–⏑–⏑⏑–⏑––`, `–⏑⏑––`).

| Draft | Scanner verdict | What happened |
|---|---|---|
| 1. `φαίνεται πλήθοισα σελάννα πόντῳ` | Fits, but **wrongly**: σελάννα's final ᾱ (Aeolic for Attic η, long) was scored 0.50 and used as the short 9th position | **False pass.** The quantity lexicon does not carry η → ᾱ length to Aeolic spellings. Repaired by putting σελάννα at the line end (–⏑ F), as Sappho always does (96, 154, 168B). |
| 2. `καὶ πόθος δηὖτ’ ὀ λυσιμέλης δόνει με` | 12 syllables; no parse | λυσιμέλης (⏑⏑⏑–) cannot stand in any Sapphic hendecasyllable, because the line never has three shorts in a row. A slot-aware synonym search would have said so before drafting. |
| 3. `…οὐκ ὀρήσθα` vs `ὄρησθα` | Metre is the same either way | The accent is wrong (Lesbian is recessive). Only Morpheus (#31) and the attested ὄρημμ’ (#35) settle the form. |
| 4. adonic `οἴα / αὔτα / μοῦνα / ἄμμορος εὔδω / νύκτα κατεύδω` | οἴα and αὔτα break: "acute on a long penult, so the final α is long" (correct); μοῦνα, ἄμμορος εὔδω and νύκτα κατεύδω fit | μοῦνα is Ionic (Sappho has μόνα, 168B); ἄμμορος is epic (#33); εὔδω cannot be parsed (#36). **νύκτα κατεύδω** is chosen. |
| Final | All 4 lines fit. Uncertain units: πέρι (ρι 0.55), σὺ μ’ (0.55), Ἄτθι (0.50). | Dichrona that a lexicon or the dialect could settle |

## What a composer would have needed (feeds the gap list in loop-design.md)

1. Text-in analysis (parse, dialect gates and syntax for a draft that is not a stored passage).
2. Unlimited batch form generation and parsing (Morpheus without the per-visitor quota) plus a generator for the Lesbian spelling of an Attic form.
3. Per-author attestation counted by **locus**, not record, everywhere (frequency, `forms_found`, collocations, n-grams).
4. `combine_variants` on by default for composer queries.
5. Concept search filtered by author or genre, with fewer false neighbours and ἵμερος included.
6. A scanner with Aeolic vowel lengths, and a metrical-slot query ("words of shape ⏑⏑– meaning X in Sappho").
7. Line-level parallels (a span inside a fragment), not whole fragments.
8. Enclitic accent normalisation and psilosis in the headline index (θῦμόν, εὔδω).
