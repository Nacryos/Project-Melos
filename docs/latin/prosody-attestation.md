# L12 prosody attestation (2026-11-15)

Check L12 of `docs/prd/catullan-hendecasyllable-checks.md`: every word's quantities, as a line uses them, against the
places where the poets put the same form. Code: `backend/latin_prosody.py` (`attested(form, author="")`,
`check(text, *, metre_name="phalaecian", author="Catullus")`), index builder `scripts/build_prosody_index_la.py`,
Virgil ingester `scripts/ingest_open_hypotactic_virgil.py`, tests `tests/test_prosody_la.py`.

## The gold and the index

Source: David Chamberlain's hand scansion, hypotactic.com/latin, CC BY 4.0 (attribution "David Chamberlain,
hypotactic.com"; licence text and page sha256 in `data/open/latin/hypotactic/manifest.json` and `manifest-virgil.json`).

| poet | works | lines | word tokens |
|---|---|---|---|
| Catullus | all poems | 2,286 | 12,840 |
| Virgil | Aeneid 1-12, Georgics 1-4, Eclogues 1-10 | 12,913 | 83,566 |
| Horace | Odes 1-4, Epodes | 3,735 | 16,617 |
| all | | 18,934 | 113,023 (27,138 distinct forms) |

`data/scansion/prosody_la.sqlite` (gitignored; rebuilt in 5 s) holds one row per word token: the folded form (the
scanner's own key: lower case, u for v, i for j, no marks), poet, work, locus, metre, the syllables with the weight
the hand scansion gives each (L long, S short, E elided), and the context that tells nature from position:

- `final_ctx`: the final syllable stands at line end (END: anceps, tells nothing), is elided (E), or stands before a
  vowel or h (V), one consonant (C), mute + liquid (ML), another cluster (CC); `final_open`: the word ends in a vowel;
- `mcl`: the syllables whose vowel stands before mute + liquid inside the word (pa-tris); `mcl_boundary`: an open
  final before a word beginning mute + liquid;
- `synizesis`, `prodelision` (elided before est / es), `line_end`, and the hand scansion's own licence marks per
  syllable (lengthening, diastole, systole, hiatus, semihiatus).

A `lemmas` table maps each form to its lemmas (`backend/latin_lemma.py`, 36,094 rows) for the stem verdict.

## Verdict rules

The line is scanned by the Latin scanner and fitted to the metre; each syllable takes the weight the fit gives it.
At an anceps place (the two base syllables and the last syllable of a Phalaecian) the metre asks nothing, so the
weight is shown in lower case and is not compared. For every other syllable:

- a non-final syllable is compared with every token of the same form with the same number of syllables;
- a final syllable is compared only with tokens in like context (before a vowel; before a consonant, where a closed
  final is long by position and an open one shows its nature; before a cluster; never at line end, never elided).

| verdict | rule | blocks |
|---|---|---|
| confirmed | every compared syllable has this weight for this form in the chosen poet (loci shown, up to 3) | no |
| confirmed-virgil | the same, with Virgil needed for at least one syllable (confirmed-other: Horace needed) | no |
| variant | a syllable is attested both ways (counts per poet each way, and the way this line takes); or the line lengthens before mute + liquid or shortens final -o where the form is attested only the other way (allowed by rule); or the spelling is a true homograph (below); or the poets take the form with and without synizesis | no (warns) |
| conflict | the form has at least N = 1 token (`MIN_CONFLICT`) in like context, none with this weight on that syllable, and it is not a true homograph. Tokens the hand scansion marks as a licence on that syllable (lengthening, diastole, systole, hiatus) do not count | yes |
| stem | the form is not in the gold; other forms of its lemma share its stem syllables (same letters up to the next vowel) with these weights | no |
| unattested | neither the form nor a comparable form of its lemma is in the gold: the quantity rests on the lexicon alone | no (warns) |
| lexicon-conflict | the verdict would be stem or unattested, and a non-final syllable's weight goes against the quantity lexicon the scanner reads (`data/scansion/quantities_la.sqlite`): a vowel it marks long used short, or a short vowel in an open syllable (not before mute + liquid) used long. The row names the lexicon's source | yes (`LEXICON_BLOCKS`) |

A missing index returns `ok: True` with detail `unavailable: ...`; nothing raises.

**True homograph.** A weight the poets never give the form is let through as a warning only when one source of the
quantity lexicon gives the spelling two readings that differ on that vowel: two lemmas (lēvis / lĕvis, pōpulus /
pŏpulus, mālum / mălum, lepōrem / lepŏrem) or two forms of one lemma (vēnit / vĕnit, lēgit / lĕgit). A lexicon row
that leaves the vowel open ("either", unmarked) is no reading, and a proper-noun lemma is passed over, so the
lexicon's Matrae no longer makes mătris a word: short matris is a conflict (Catullus 8, Vergil 13, Horace 4 tokens,
all long; the stem's 98 too). The row names both readings with the counts and a locus of each and asks which is
meant; the same naming is given when the gold itself has both.

**Mute + liquid.** Whenever a compared syllable is a vowel before mute + liquid that is short anywhere in the gold,
the row carries `mute_liquid` and `detail` says so, with long / short counts for Catullus and for Virgil separately
(both always listed, other poets when they have it): "patris: Catullus long 0 / short 3, Vergil long 0 / short 16".
When the form shows one weight only, or is not in the gold at all, the counts are pooled over the other forms of its
lemma that share the stem (patre, patrem, patres, patri) and the row says they are pooled. Short before mute +
liquid where the form itself is only long passes when the stem has it short; where the stem is long everywhere
(māter) it is a conflict.

**Synizesis and prodelision.** The hand scansion's synizesis mark is stored per token. A form the poets take both
ways (dehinc: 4 with, 6 without) is a variant with counts and loci of each, whichever way the line takes it; a
syllable count the gold does not have is a variant with the reason, never a conflict. Before est / es the gold
writes the junction as elision of the first word, the scanner as prodelision: the final syllable is then not
compared and the row gives the count and loci of the form's tokens in that junction.

`python scripts/la_prosody.py <form>` prints `attested()`: patterns, counts per poet, final contexts, loci.

## Measured (leave-one-line-out, run 2026-11-15 23:12 PST)

`python scripts/build_prosody_index_la.py --measure`: L12 on each of Catullus's 552 hendecasyllables (macrons
stripped) with that line's own tokens kept out of the evidence; 2,774 word tokens. Scanner as of 23:12 (after the
fixes to aere, iambus, Italia); it now rejects 5 of the 552 lines (38.2, 55.9, 55.10, 55.11, 57.5).

| verdict | tokens | share |
|---|---|---|
| confirmed (another place in Catullus) | 1,642 | 59.2% |
| confirmed-virgil | 311 | 11.2% |
| confirmed-other (Horace) | 71 | 2.6% |
| stem | 382 | 13.8% |
| variant | 189 | 6.8% |
| unattested | 177 | 6.4% |
| lexicon-conflict | 2 | 0.07% |
| conflict | 0 | 0% |

**The threshold N** (tokens of the form, all the other way, needed to block):

| N | false conflicts (of 2,774 genuine tokens) | confirmed syllables where a flipped quantity would still block (of 2,672) |
|---|---|---|
| 1 | 0 (0%) | 2,672 (100%) |
| 2 | 0 (0%) | 2,171 (81.2%) |
| 3 | 0 (0%) | 1,851 (69.3%) |

N = 1 is chosen: no false conflict at any N, and a higher N only gives up blocking power. (Before enclitic forms
were looked up under their host in the homograph test, N = 1 had one false conflict, malisque at 15.10, mălīs
against Virgil's one mālīs, Aeneid 7.114; N = 2 and 3 had none.) The four false conflicts of the first run (aere
10.8; meos 40.2; iterum, meis 54.6) are gone with the scanner fixes.

**The lexicon against the gold.** On the same run the lexicon disagrees with the weight a genuine line gives a
non-final syllable on 2 of 2,774 tokens (0.07%; 0.36% of the 561 stem / unattested tokens it decides): Cyrenis 7.4
and Pegaseo 58b.3, Greek names whose vowel Catullus has short and Winge long. That is under the 0.5% bar, so
lexicon-conflict blocks (`LEXICON_BLOCKS = True`). Planted the other way, 300 forms absent from the gold with a
lexicon-long first vowel, set where the metre needs a short (`Cui dono lepidum X libellum`): 226 (75%) get
lexicon-conflict; the rest have a lexicon row the other way or no clear reading, and stay stem / unattested.

Why the 189 variants (syllables): homograph named from the lexicon 87, iambic shortening 41, final syllable in like
context 31, -is / -us / -es / -e endings 11, diastole marked in the gold 9, mute + liquid 7, homograph not in the
lexicon 5, genitive -ius 3, final -o 2.

Broken quantities: `Cui dono lepidum donum libellum` passes L7 and L12 blocks it ("donum [SL]: syllable 1 is short
here, but the other way in every like place (Vergil 5), e.g. Vergil Aeneid 1.652"); `... matris libellum` blocks
(long in 25 tokens, and in 98 of the stem); `... levis libellum` warns and asks which levis is meant.

## Limits

- A homograph the lexicon does not separate within one source, attested one way only, is a conflict; a wrong
  quantity that happens to match a second lexicon reading is only a warning.
- With N = 1 a single token decides. The measured false-conflict rate is 0 of 2,774; if a hand-scansion slip turns
  up, raise `MIN_CONFLICT` (N = 2 keeps 81.2% of the blocking power).
- The lexicon check leaves the final syllable alone and trusts a short only in an open syllable; it misses about a
  quarter of planted errors (above).
- The stem verdict needs `data/lemma_index_la.sqlite`; perfect and present stems that differ (mōvī / moveō) are
  reported as "stem forms scan differently" under unattested, never as a conflict.
- No Latin hendecasyllables besides Catullus's are in the gold.

## Forms with both weights on a syllable (Catullus, Virgil, Horace)

`python scripts/build_prosody_index_la.py --variants 50`. Counted per (form, syllable, context); a final syllable
only in like context. By cause, of all cases: final -a 222, homograph 201, -is / -us / -es / -e / -i endings 115,
mute + liquid 84, iambic shortening 13, marked licences 36 (diastole 25, lengthening 9, hiatus and semihiatus 2), other finals 25,
genitive -ius 5, final -o 3, -erunt 1. The mute + liquid forms with most tokens: sacrum, tenebris, sacra, retro, agros,
agris, volucres, suprema, sacris, utrumque, patri, pharetra.

706 (form, syllable, context) cases have both weights; the 50 with the most tokens on the rarer side:

| form | syll. | context | long | short | cause | e.g. long | e.g. short |
|---|---|---|---|---|---|---|---|
| mihi | 2 | final, before a consonant | Catullus 17, Horace 6, Vergil 35 | Catullus 43, Horace 20, Vergil 139 | iambic shortening | Catullus 10.32 mihī | Catullus 2b.1 mihi |
| tibi | 2 | final, before a consonant | Catullus 13, Horace 5, Vergil 30 | Catullus 46, Horace 35, Vergil 125 | iambic shortening | Catullus 8.3 tibī | Catullus 1.3 tibi: |
| multa | 2 | final, before a consonant | Catullus 1, Horace 6, Vergil 22 | Catullus 12, Horace 9, Vergil 57 | final -a (short nominative / neuter plural, long ablative) | Catullus 64.113 multā | Catullus 5.10 multa |
| magna | 2 | final, before a consonant | Vergil 29 | Catullus 5, Horace 4, Vergil 32 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.497 magnā | Catullus 34.6 magna |
| qua | 1 | final, before a consonant | Catullus 9, Horace 17, Vergil 80 | Catullus 1, Vergil 27 | final -a (short nominative / neuter plural, long ablative) | Catullus 15.11 quā | Catullus 61.84 qua |
| omnis | 2 | final, before a vowel | Horace 4, Vergil 18 | Catullus 1, Horace 4, Vergil 24 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Horace Odes 1.28.15 omnīs | Catullus 63.92 omnis, |
| uenit | 1 | any (not final) | Catullus 2, Vergil 27 | Catullus 2, Vergil 20 | homograph (different words or tenses spelt alike) | Catullus 61.18 vēnit | Catullus 64.86 venit |
| fugit | 1 | any (not final) | Catullus 2, Horace 8, Vergil 11 | Catullus 4, Horace 3, Vergil 25 | homograph (different words or tenses spelt alike) | Catullus 10.29 fūgit | Catullus 8.10 fugit |
| uiris | 1 | any (not final) | Horace 1, Vergil 21 | Catullus 1, Horace 2, Vergil 15 | homograph (different words or tenses spelt alike) | Vergil Aeneid 1.214 vīrīs, | Catullus 61.179 virīs |
| summa | 2 | final, before a consonant | Catullus 2, Horace 1, Vergil 15 | Horace 1, Vergil 18 | final -a (short nominative / neuter plural, long ablative) | Catullus 64.242 summā | Horace Odes 1.4.15 summa |
| solum | 1 | any (not final) | Catullus 5, Vergil 13 | Catullus 1, Horace 3, Vergil 14 | homograph (different words or tenses spelt alike) | Catullus 64.300 sōlum, | Catullus 68.109 solum, |
| manus | 2 | final, before a vowel | Horace 1, Vergil 16 | Horace 1, Vergil 15 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Vergil Aeneid 1.455 manūs | Vergil Aeneid 2.29 manus, |
| dea | 2 | final, before a consonant | Horace 1, Vergil 14 | Catullus 7, Vergil 24 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.382 deā | Catullus 34.17 dea, |
| una | 2 | final, before a consonant | Catullus 6, Horace 1, Vergil 8 | Catullus 3, Horace 4, Vergil 17 | final -a (short nominative / neuter plural, long ablative) | Catullus 37.8 ūnā | Catullus 5.6 ūna |
| sua | 2 | final, before a consonant | Catullus 1, Vergil 13 | Catullus 3, Horace 2, Vergil 36 | final -a (short nominative / neuter plural, long ablative) | Catullus 17.18 suā | Catullus 62.65 sua |
| terra | 2 | final, before a consonant | Catullus 2, Horace 3, Vergil 8 | Catullus 1, Horace 4, Vergil 21 | final -a (short nominative / neuter plural, long ablative) | Catullus 64.390 terrā | Catullus 61.73 terra |
| uidere | 1 | any (not final) | Horace 1, Vergil 12 | Catullus 4, Horace 3, Vergil 6 | homograph (different words or tenses spelt alike) | Vergil Aeneid 6.490 vīdēre | Catullus 22.19 vidēre |
| tua | 2 | final, before a consonant | Catullus 7, Horace 1, Vergil 4 | Catullus 9, Horace 4, Vergil 70 | final -a (short nominative / neuter plural, long ablative) | Catullus 3.17 tuā | Catullus 12.7 tua |
| sibi | 2 | final, before a consonant | Catullus 2, Horace 1, Vergil 9 | Catullus 7, Horace 3, Vergil 22 | iambic shortening | Catullus 10.30 sibī | Catullus 10.23 sibi |
| mea | 2 | final, before a consonant | Catullus 4, Horace 3, Vergil 3 | Catullus 17, Horace 4, Vergil 61 | final -a (short nominative / neuter plural, long ablative) | Catullus 36.2 meā | Catullus 5.1 mea |
| prima | 2 | final, before a consonant | Horace 1, Vergil 9 | Catullus 1, Vergil 58 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.372 prīmā | Catullus 29.17 prīma |
| alta | 2 | final, before a consonant | Horace 2, Vergil 8 | Catullus 4, Horace 2, Vergil 49 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.26 altā | Catullus 63.1 alta |
| noua | 2 | final, before a consonant | Horace 3, Vergil 7 | Catullus 6, Horace 5, Vergil 15 | final -a (short nominative / neuter plural, long ablative) | Horace Odes 1.7.29 novā | Catullus 61.91 nova |
| modo | 2 | final, before a consonant | Catullus 1, Vergil 9 | Catullus 6, Horace 3, Vergil 14 | final -o | Catullus 10.7 modō | Catullus 1.2 modo |
| longa | 2 | final, before a consonant | Catullus 2, Vergil 8 | Horace 4, Vergil 11 | final -a (short nominative / neuter plural, long ablative) | Catullus 40.8 longā | Horace Odes 1.28.35 longa; |
| uita | 2 | final, before a consonant | Catullus 5, Vergil 5 | Catullus 2, Horace 3, Vergil 9 | final -a (short nominative / neuter plural, long ablative) | Catullus 65.9 vītā | Catullus 45.13 vīta |
| caua | 2 | final, before a consonant | Horace 2, Vergil 12 | Catullus 2, Vergil 8 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 2.360 cavā | Catullus 63.10 cava |
| tota | 2 | final, before a consonant | Catullus 6, Vergil 7 | Catullus 5, Horace 1, Vergil 4 | final -a (short nominative / neuter plural, long ablative) | Catullus 62.14 tōtā | Catullus 41.2 tōta |
| dextra | 2 | final, before a consonant | Catullus 2, Horace 1, Vergil 28 | Vergil 9 | final -a (short nominative / neuter plural, long ablative) | Catullus 33.3 dextrā | Vergil Aeneid 2.388 dextra, |
| leuis | 1 | any (not final) | Horace 3, Vergil 6 | Catullus 2, Horace 7, Vergil 16 | homograph (different words or tenses spelt alike) | Vergil Aeneid 5.558 lēvīs | Catullus 61.97 levis |
| hymen | 1 | any (not final) | Catullus 8 | Catullus 38 | homograph (different words or tenses spelt alike) | Catullus 62.5 Hȳmēn | Catullus 61.4 Hymēn, |
| sacra | 2 | final, before a consonant | Horace 2, Vergil 6 | Catullus 3, Horace 1, Vergil 27 | final -a (short nominative / neuter plural, long ablative) | Horace Odes 1.18.1 sacrā | Catullus 17.6 sacra |
| uere | 2 | final, before a consonant | Catullus 6, Horace 1, Vergil 1 | Horace 1, Vergil 11 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Catullus 8.8 vērē | Vergil Georgics 1.43 Vēre |
| sacrum | 1 | any (not final) | Horace 1, Vergil 7 | Catullus 2, Horace 4, Vergil 4 | mute + liquid | Vergil Aeneid 2.230 sacrum | Catullus 7.6 sacrum |
| laeua | 2 | final, before a consonant | Vergil 8 | Catullus 2, Vergil 7 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 2.552 laevā, | Catullus 4.19 laeva |
| tenebris | 2 | any (not final) | Horace 1, Vergil 7 | Horace 1, Vergil 7 | mute + liquid | Vergil Aeneid 3.195 tenebrīs. | Vergil Aeneid 2.92 tenebrīs |
| illa | 2 | final, before a consonant | Catullus 2, Vergil 5 | Catullus 19, Horace 3, Vergil 57 | final -a (short nominative / neuter plural, long ablative) | Catullus 64.16 illā, | Catullus 5.11 illa, |
| sacra | 1 | any (not final) | Catullus 3, Horace 1, Vergil 35 | Horace 5, Vergil 2 | mute + liquid | Catullus 17.6 sacra | Horace Odes 1.18.1 sacrā |
| domus | 2 | final, before a vowel | Catullus 1, Vergil 6 | Catullus 3, Horace 5, Vergil 26 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Catullus 64.247 domūs | Catullus 61.149 domus |
| mala | 1 | any (not final) | Horace 1, Vergil 6 | Catullus 12, Horace 6, Vergil 7 | homograph (different words or tenses spelt alike) | Vergil Georgics 2.33 māla | Catullus 7.12 mala |
| sola | 2 | final, before a consonant | Catullus 2, Vergil 5 | Catullus 5, Horace 1, Vergil 19 | final -a (short nominative / neuter plural, long ablative) | Catullus 64.58 sōlā | Catullus 61.140 sōla |
| troia | 2 | final, before a consonant | Vergil 7 | Catullus 3, Vergil 8 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 2.108 Trōjā | Catullus 68.87 Trōja |
| notus | 1 | any (not final) | Catullus 2, Horace 3, Vergil 3 | Horace 4, Vergil 3 | homograph (different words or tenses spelt alike) | Catullus 40.6 nōtus | Horace Odes 1.7.16 Notus |
| forma | 2 | final, before a consonant | Vergil 8 | Horace 1, Vergil 6 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.72 fōrmā | Vergil Aeneid 3.591 fōrma |
| pedes | 2 | final, before a vowel | Catullus 1, Horace 1, Vergil 5 | Vergil 7 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Catullus 64.319 pedēs | Vergil Aeneid 6.880 pedes |
| leui | 1 | any (not final) | Catullus 1, Horace 2, Vergil 4 | Catullus 3, Vergil 4 | homograph (different words or tenses spelt alike) | Catullus 64.318 lēvī | Catullus 64.9 levī |
| ubi | 2 | final, before a consonant | Catullus 1, Horace 5 | Catullus 9, Horace 8, Vergil 123 | iambic shortening | Catullus 63.22 ubī | Catullus 55.2 ubi |
| fama | 2 | final, before a consonant | Vergil 6 | Catullus 4, Horace 2, Vergil 32 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.379 fāmā | Catullus 61.62 fāma |
| quis | 1 | final, before a vowel | Catullus 3, Horace 1, Vergil 2 | Catullus 6, Horace 8, Vergil 20 | ending spelt alike with a long and a short vowel (-is, -us, -es, -e, -i) | Catullus 63.46 quīs | Catullus 29.1 Quis |
| fuga | 2 | final, before a consonant | Vergil 24 | Horace 1, Vergil 5 | final -a (short nominative / neuter plural, long ablative) | Vergil Aeneid 1.317 fugā | Vergil Aeneid 8.251 fuga |
