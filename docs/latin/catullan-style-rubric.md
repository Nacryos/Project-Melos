# What makes a hendecasyllable Catullan: the counted rubric

For the composer, the style critic (`docs/latin/critic-brief.md`) and the reader of an L5 or L6 report. Metre and
prosody are in `docs/latin/phalaecian-profile.md` and `docs/latin/prosody-attestation.md`; this page is everything
else. Every claim carries a count or a locus. A claim marked **uncounted** is general knowledge about Catullus that
no script here has measured: treat it as a hypothesis, not as evidence.

## Where the numbers come from

- Corpus: Catullus's hendecasyllabic poems, **41 poems, 552 lines, 2,858 tokens**. Lines and metre labels from the
  Hypotactic gold (`data/open/latin/hypotactic/lines.jsonl.gz`, metre "hendecasyllables"); lemma, part of speech and
  features from the LASLA rows of `data/lemma_index_la.sqlite` (13,129 Catullus tokens, 45,007 Horace tokens);
  printed text and punctuation from `data/corpus_la.sqlite`.
- Marker rates, diminutives and the collocation baseline: `backend/latin_style.py` (`marker_profile()`,
  `diminutives()`, `collocation_baseline()`), the same code that L5 and L6 run, so a draft is counted the way
  Catullus was.
- **Every number on this page is printed by `scripts/catullan_style_counts.py`** (run 2026-11-15;
  `.venv/bin/python scripts/catullan_style_counts.py`, `--json` for the raw result). Its sections carry the numbers
  of the sections here. Re-run it after the corpus, the lemma index or the dictionary is rebuilt, and correct this
  page from its output.
- "Per 100 lines" is the pooled rate; "per poem p10 / median / p90" is the spread over the 41 poems, which is the
  number to hold a short draft against.

## 1. The shape of the short poem

| Measure | Count |
|---|---|
| Length | 3 to 34 lines, median 11 |
| A vocative in line 1 | 25 of 41 poems |
| A vocative in lines 1-2 | 31 of 41 |
| A vocative anywhere | 38 of 41 |
| A second-person form anywhere | 37 of 41 |

The poem is spoken to someone and says so at once. A draft that reaches line 3 with no addressee is in the minority
of 10 poems out of 41. A draft of more than 34 lines is longer than any hendecasyllabic poem he wrote.

Uncounted: the usual movement is occasion, then elaboration, then a turn or a point in the last one to three lines
(1, 3, 5, 13, 49).

## 2. Address and the second person

| Marker | Per 100 lines | Count | Per poem p10 / median / p90 |
|---|---|---|---|
| Vocatives | 24.6 | 136 / 552 | 5.9 / 20.0 / 57.1 |
| Second-person forms (verbs, pronouns, possessives) | 44.0 | 243 / 552 | 3.8 / 42.9 / 81.2 |
| Interjections | 3.3 | 18 / 552 (o 15, a 2, en 1) | 0 / 0 / 12.5 |

By group, per 100 lines:

| Group (lines) | Diminutives | Interjections | Vocatives | Second person | Run-on lines |
|---|---|---|---|---|---|
| Hendecasyllables (552) | 8.9 | 3.3 | 24.6 | 44.0 | 33.7 |
| Other polymetrics (295) | 7.8 | 3.4 | 26.8 | 43.1 | 37.8 |
| Long poems 61-68 (1,122) | 3.7 | 8.3 | 21.5 | 26.3 | 39.5 |
| Epigrams 69-116 (323) | 3.7 | 2.8 | 15.8 | 42.4 | 30.6 |

The hendecasyllables carry about one vocative every four lines and a second-person form nearly every other line.
Vocatives and diminutives separate the polymetrics from the epigrams; interjections do not (they belong to the long
poems, 8.3). A draft with `o` in every line has the rate of the long poems, not of
the hendecasyllables.

## 3. Repetition and ring composition

- First line = last line: **3 poems** (16, 36, 57).
- A whole line repeated inside the poem: **5 poems** (16, 36, 42 twice, 45, 57).
- First and last line share a content lemma: **4 poems** (13, 16, 36, 57).
- Consecutive lines opening on the same word: 11 times (2.0 per 100 lines).
- A content lemma (noun, verb, adjective, proper name) that has already occurred in the poem: 164 tokens, 29.7 per
  100 lines. Repeating a word is the norm, about three in every ten lines; elegant variation is not.

The ring is a device he uses in about one poem in ten, not a rule. Uncounted: repetition with variation, as in the
counting of 5.7-9 and the paired superlatives of 49.5-7.

## 4. Diminutives

**49 tokens, 8.9 per 100 lines; per poem p10 0 / median 7.1 / p90 23.8.** A noun or adjective lemma is counted
when its Lewis & Short entry says *dim.* in its first 120 characters (`latin_style.diminutive_info`). The suffix
rule (-culus, -ellus, -illus, -olus, -ulus with a base in the lemma index) decides only for a lemma with no entry;
those rows are marked "by suffix" (one lemma here: lecticulus).

- **puella is not counted.** Lewis & Short derives it from puellus and does not mark it *dim.*; it is the ordinary
  word for a girl. With its 22 tokens the figure would be 71 tokens, 12.9 per 100 lines.
- The lemmas: ocellus 5, misellus 4, libellus 3, saeculum 3, uersiculus 3, molliculus 2, lucellum 2, tabella 2;
  once each solaciolum, aureolus, turgidulus, scortillum, sacculus, integellus, salillum, lapillus, flosculus,
  uillula, uetulus, sarcinula, turpiculus, catulus, lectulus, pusillus, femella, papilla, lacteolus, pupulus,
  macula, gemellus, lecticulus (by suffix), eruditulus, puellula.
- **Limit of the count.** Lewis & Short marks the formation, not the feeling: saeculum (3), macula, catulus and
  papilla are *dim.* in the dictionary and ordinary words in use. Without those 6 tokens: 43, 7.8 per 100 lines.
- By group, per 100 lines (with puella in brackets): hendecasyllables 8.9 (12.9), other polymetrics 7.8 (11.2),
  long poems 3.7 (4.3), epigrams 3.7 (5.0). The polymetrics carry about twice the rate of the rest.
- **Place in the line.** 17 of the 49 begin at syllable 9 and 19 of 49 end the line; the other cluster is
  syllable 3 (14), then syllable 7 (5). The trisyllabic diminutive closing the line (libellum, ocelle) is the
  commonest position; the one after the base is next.
- More than half the poems have at least one (median 7.1 per 100 lines); at least one poem in ten has none
  (p10 = 0).

## 5. Urbane vocabulary

Tokens in Catullus's polymetrics / in the hendecasyllables / in all Catullus; then all Horace.

| Lemma | Polymetrics | Hendecasyllables | All Catullus | Horace |
|---|---|---|---|---|
| bellus | 8 | 6 | 14 | 3 |
| delicia (deliciae) | 5 | 5 | 8 | 2 |
| uenustus | 4 | 2 | 6 | 0 |
| basium | 4 | 4 | 5 | 0 |
| basio | 4 | 3 | 4 | 0 |
| lepidus | 2 | 2 | 4 | 2 |
| elegans | 3 | 2 | 3 | 0 |
| urbanus | 5 | 1 | 5 | 10 |
| ineptus | 5 | 1 | 5 | 7 |
| delicatus | 2 | 1 | 2 | 0 |
| salsus | 1 | 1 | 2 | 4 |

- For "kiss" the hendecasyllables say basium and basiare. sauium occurs twice, in the epigrams only; osculum once,
  in the long poems (Horace 4). facetus is not in Catullus at all (Horace 4).
- Lemmas with 3 or more tokens in the hendecasyllables and none in Horace: ocellus 5, cinaedus 5, codicillus 5,
  misellus 4, basium 4, irrumo 4, illepidus 3, basio 3, inuenustus 3, paedico 3, sinistra 3.
- Lemmas with 4 or more tokens in the hendecasyllables and none in poems 61-116: poeta 7, fabullus 6, passer 5,
  cinaedus 5, annus 5, codicillus 5, acme 5, iaceo 4, furius 4, uinum 4, lepor 4, seruus 4, arca 4.
- The negatived compounds (illepidus, inuenustus, and uncounted: insulsus, inelegans) are how he says a thing is
  bad.

L6 reports this for every content word of a draft: tokens in the polymetrics, the long poems and the epigrams, and
warns when the lemma is absent from the polymetrics or from Catullus.

## 6. Colloquial syntax and line openings

Line-initial forms, of 552 lines: non 23, et 19, nec 15, nam 13, sed 10, ut 10, quod 10, o 9, si 8. One line in
five opens on one of these nine small words; the line begins with a connective or a negative far more often than
with a noun.

Uncounted, to be checked in the commentary (`la_ref.py word`, `la_ref.py search`) before use: parataxis in place of
subordination, short questions and imperatives, parenthesis, mi for mihi, colloquial intensives (sane, bene with
adjectives), Greek loan-words, the indicative in indirect questions.

## 7. The word at line end

| Syllables in the last word | Lines (of 552) |
|---|---|
| 1 | 17 |
| 2 | 156 |
| 3 | 241 |
| 4 | 76 |
| 5 | 42 |
| 6 | 19 |
| 7 | 1 |

- Trisyllable 44%, disyllable 28%: together 72%. A monosyllable closes 3% of lines (17).
- Part of speech of the last word (an enclitic -que passed over): noun 224, verb 129, adjective 76, proper name
  46, adverb 21, auxiliary 20, determiner 18, pronoun 9, numeral 7. Nouns and names close 49% of lines.
- Commonest line-final lemmas: sum 21, puella 15, amor 11, possum 10, catullus 6, beatus 6, poeta 6, amo 5,
  ocellus 5, annus 5, codicillus 5.
- The long closing word (five or six syllables, 61 lines, 11%) is the rarer close. Uncounted: it is a
  marked effect, where the comic and learned polysyllables go.

L6 reports for each word of a draft the syllable at which Catullus usually starts that form and that lemma, and how
often it ends the line.

## 8. Enjambment

**162 of 481 printed lines carry no punctuation at the end: 33.7 per 100; per poem p10 11.1 / median 33.3 /
p90 53.3.** Two lines in three end with a stop or a comma in the edition's punctuation. The count depends on the
editor's commas, and 71 of the 552 lines could not be matched to printed text. A draft in which every line is a
closed sentence is below the 10th percentile; so is one that runs on everywhere (above 53 per 100).

## 9. Words that keep company (L5)

Take every pair of content lemmas in the same line or in adjacent lines. Holding each of the 41 poems out in turn,
**2,075 of its 5,170 pairs recur elsewhere in Catullus or Horace: 40.1% pooled, median poem 38.8%, 10th percentile
22.2%**; the smallest poem has 8 pairs. L5 warns only when a draft has at least 8 pairs and fewer than 22.2% of
them have a parallel. There is no upper warning line. Catullus 1.1-2, checked against the corpus that
contains it, scores 21 of 21: a share near 100% together with an L11 homage warning means the draft is a cento.

## How to use the rubric

1. Run `scripts/la_check.py`; read L6's marker row for the draft against the p10 / median / p90 columns above.
2. A marker outside p10-p90 is a question, not a fault: answer it from the poem's occasion or change the draft.
3. Cite this page by section when approving or rejecting on style; cite nothing marked uncounted as evidence.
