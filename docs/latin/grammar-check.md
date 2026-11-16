# Latin grammar checks: L3 agreement, L10 word order (2026-11-15)

`backend/latin_morph.py` (readings), `backend/latin_grammar.py` (the two checks), `scripts/build_morph_la.py`
(-> `data/morph_la.sqlite`, gitignored), `tests/test_grammar_la.py`. Contract: `docs/prd/catullan-hendecasyllable-checks.md`.
Both checks warn and never block. They are a net for plain blunders, not a parser: a rule passes when ANY combination
of a word's readings satisfies it.

## Readings: `latin_morph.analyses(form) -> list[dict]`

Keys: lemma, pos, case, number, gender, person, tense, mood, voice, degree, source (and `enclitic` when the reading is
of the host of -que / -ne / -ve / -cum). Three sources are united under the normalised spelling:

| source | what it gives | size |
|---|---|---|
| `lasla` | LASLA's hand tags for the forms Catullus and Horace print, from `data/lemma_index_la.sqlite`; split enclitics recorded against the host | 27,973 distinct readings |
| `morpheus` | Winge's table `data/raw/latin/winge/macrons.txt` (GPL): form, nine-place Perseus tag, lemma | 712,100 readings |
| `collatinus` | Collatinus lemmata + paradigm models through the pure-Python port `pycollatinus` 0.1.6 (GPL v2), loaded on first use (0.8 s), skipped when not installed | 81,935 lemmata, every inflected form |

Route chosen for paradigm coverage, and why: the quantity lexicon (`quantities_la.sqlite`) carries only marks and lemmas,
no tags. Winge's table has full tags but turned out to hold the forms of a corpus, not whole paradigms (about half of
a regular paradigm, measured below). Collatinus generates every form; `pycollatinus` already implements its paradigm
engine over the same `lemmes.la` / `modeles.la` that sit in `data/raw/latin/collatinus/`, so it is used as an analyser
at run time instead of re-deriving the engine. It needs one shim on Python 3.12 (`collections.Callable`), applied in
`latin_morph._collatinus_engine`. Collatinus gives nouns no gender in the reading; the gender is taken from its lemma
entry (`ae, f.`). With `MELOS_LATINCY_URL` set, a form no source reads is sent to the LatinCy sidecar.

Measured coverage (2026-11-15):

| measure | result |
|---|---|
| Catullus, all poems, Perseus text: tokens with at least one reading | 12,823 of 12,856 = 99.74 % (Morpheus alone 97.09 %; Morpheus + LASLA 99.57 %) |
| unread | 28 spellings: names (*Aufilena*, *Ipsithilla*, *Maeciliam*) and misprints of the digital text (*arnor*, *flammma*) |
| paradigm forms NOT printed in Catullus or Horace: 3,000 sampled from 10,441 generated for Catullus's lemmata (first-declension nouns, -us nouns, -us adjectives, first-conjugation verbs) | with the expected reading: 52.2 % from LASLA + Morpheus, 93.9 % with Collatinus |

The remaining 6 % is almost wholly non-forms the naive test generator made from irregular verbs (*ferabis*, *coeabunt*,
*aiabam*), which are rightly unread; the figure is a lower bound.

## L3 agreement: `latin_grammar.check(text, *, metre_name="phalaecian", author="Catullus")`

The draft is split into sentences at `. ; ? ! :` across line ends. `evidence` rows: rule, severity (fail / note), word,
line, message, the word's readings, and the readings of the words it was held against.

| rule | what fails |
|---|---|
| a | a word no source reads |
| b | a preposition with no word in a case it governs (Allen & Greenough 220-221) among the 5 words after it or the 2 before (anastrophe); *mecum*, *quibuscum* read as ablative + cum; *cum* also passes as the conjunction when a finite verb follows; prepositions that also stand as adverbs (*ante*, *post*, *contra*, *super* ...) are not checked |
| c | a word that is only adjective / participle / pronominal adjective and shares case, number and gender with no noun or pronoun reading of its sentence. A note, not a failure, when the sentence has no noun at all (substantive) or the adjective is nominative with a first or second person verb of its number, or with a verb and no nominative noun (predicate of an unexpressed subject) |
| d | a word that can only be nominative with no finite verb of its number in the sentence (two singular subjects with a plural verb pass; a sentence with no finite verb passes); *ego*, *tu*, *nos*, *vos* need a verb of their person |
| d2 | a noun that can only be nominative standing with first or second person verbs only, and no *ego* / *tu* beside it |
| e | *quem, quos, quas, cuius* ... (not *quod, quam, quo, qua*, not in a question, not when a neuter reading exists) agreeing in gender and number with no word anywhere in the draft |

### Readings to confirm (notes, rule id `confirm`)

A rule passes when any reading satisfies it, so a blunder can pass on a rare reading. Where that happens the check says
so in a note (ok stays True), puts the count in `detail` ("2 readings to confirm") and lists these notes first, for the
critic model. Counts are LASLA's tags in the lemma index, the first of four tiers whose commonest reading has at least
5 tokens: the spelling in Catullus, the spelling in Horace, all forms of its lemmas in Catullus, the same in Horace.
Without the lemma index there are no such notes.

| note | given when | example |
|---|---|---|
| preposition | every word that satisfies rule b does so on a reading that is not its commonest (commonest at least 5 tokens and 80 %) | *sine puellam vivo*: "*sine* passes only if *vivo* is the ablative of *uiuus* (Catullus, all forms of the lemma: verb uiuo 11, adjective uiuus 1)" |
| *cum* | *cum* passes as the conjunction and the next word is a noun or adjective with no ablative reading (given whatever the counts say: the conjunction is the commoner reading) | *cum puellam amo*: "passes only if *cum* is the conjunction (Catullus: conjunction 57, preposition 25, adverb 1); *puellam* next to it is not ablative" |
| adjective, other reading | rule c is skipped because the form is also a noun, verb or adverb, its adjective readings agree with nothing, and that other reading is not the commonest (same thresholds); or, whatever the counts, it stands next to a plain noun, its other readings are all nouns, and LASLA tags the adjective | *puella bellum*: "passes only if *bellum* is the noun *bellum* (Horace: noun bellum 13, adjective bellus 1); as the adjective *bellus* it agrees with no noun of its sentence, not with *puella* next to it" |
| adjective, far noun | an adjective-only word next to a plain noun it cannot agree with, no agreeing word on either side, the nearest agreeing noun 4 or more words off | *puella magnus venit per vias et hortum amat poeta*: "*magnus* agrees with nothing next to it (*puella*); taken with *poeta* in line 1" |

*sine puellam vivo* is not rescued by *sine* as the imperative of *sino* (rule b never excuses a preposition for a verb
reading: *sine puellam venit* fails); it is rescued by *vivo* read as the ablative of *vivus*, and the note says that.

## L10 word order: `latin_grammar.check_word_order(text, ...)`

Counts are made by the build from the punctuated text of Catullus and of the Horace held in `data/corpus_la.sqlite`.

- **Postpositive first in its sentence.** Candidates from the grammar (A&G 599), kept when never sentence-first in the
  corpus: *enim* 0 of 11, *autem* 0 of 4, *vero* 0 of 5, *quoque* 0 of 17, *igitur* 0 of 3, *quidem* 0 of 1. Counted and
  left out because they do stand first: *tamen* 1 of 31, *nam* 50 of 62, *namque* 13 of 19, *ergo* 4 of 4, *itaque* 2 of 2.
- **Enclitics.** A word ending in -que / -ne / -ve that has a reading of its own is a word (*atque*, *neque*, *quoque*,
  *bene*, *sine*: `latin_morph.lexical`); otherwise the host must read, else it fails. Hosts in the corpus: 596 -que,
  36 -ve, 23 -ne. A host ending in a letter no corpus host ends in is a note (-que after -c: 0 of 596, so *hicque*).
  No position rule: -que is sentence-first 10 times of 596 (-que ... -que), -ne 19 of 23.
- **Preposition last in its sentence** fails unless Catullus does it: 0 of 157 for *in*, 0 of 51 *ad*, 0 of 35 *a*,
  0 of 30 *ex*, 0 of 20 *e*, 0 of 15 *de*, 0 of 14 *per*, 0 of 13 *ab*, 0 of 12 *sine*, 0 of 11 *pro*, 0 of 10 *sub*. The only
  sentence-final ones are adverbial (*contra* 1 of 5, *clam* 1 of 1, *versus* 1 of 1), which the rule does not check.
  *cum* is not checked (conjunction). An unpunctuated last line is not a sentence end.

## False alarms on genuine Latin

Every Catullan poem labelled hendecasyllables in the Hypotactic scansion, each run as one draft: 43 poems, 552 lines.
Each item is a false alarm.

| rule | items | lines | share of lines |
|---|---|---|---|
| L3 a no reading | 2 | 2 | 0.36 % (*Raude*, *avelte*) |
| L3 b preposition | 1 | 1 | 0.18 % (26.2 *flatus ... neque ad Favoni*: the governed noun stands four words before, outside the window) |
| L3 c adjective | 4 | 4 | 0.72 % (6.2 *illepidae*, 7.11 *curiosi*, 36.7 *daturam*, 50.3 *delicatos*: predicates and substantives) |
| L3 c, note only | 14 | 14 | 2.54 % (ok stays True) |
| L3 readings to confirm, note only | 16 | 16 | 2.90 % (ok stays True): 9 adjective with another reading, 7 far noun, 0 preposition, 0 *cum* |
| L3 d, d2, e | 0 | 0 | 0 % |
| **L3, any failure** | 7 | 7 | **1.27 %** |
| L10 postpositive, enclitic, preposition | 0 | 0 | 0 % |

Rule c first fired on 2.36 % of lines; it was tightened (a nominative adjective with a first or second person verb is
the predicate of an unexpressed subject) to 0.72 %. No rule needed demoting (`NOTE_ONLY` is empty). After tightening,
the blunder set of the tests is still caught: *cum puellam*, *ad urbe*, *ex urbem*, *sine puellam*, *in puellae*,
*de meos amores* (b); *bonus puella*, *puellae venit bellus*, *pueri bellus veniunt* (c); *Catullus veniunt*, *ego venit*,
*tu amamus* (d); *Catullus amo* (d2); *puer quas amo* (e); *Enim venit*, *venit puella ad*, *xyzque* (L10).

Readings to confirm, same 552 lines. First cut (any rescuing reading that is not the commonest, no thresholds; far noun
at any distance; any neighbour with a noun reading): 59 notes on 58 lines, 10.51 %, of which 46 lines were the far-noun note:
ordinary hyperbaton (*ad caelum lepido vocare versu*), or a neighbour such as *cum* or *mihi* counted as a noun. After requiring a plain-noun neighbour and dropping the note where *cum*
has both a case and a verb: 7.25 % (far noun 5.07 %, adjective 1.99 %, preposition 0.18 %). After tightening (commonest
reading at least 5 tokens and 80 %; far noun at least 4 words off): 16 lines, **2.90 %** (far noun 1.27 %, adjective
1.63 %). Far-noun distance 3 gives 2.72 % for that note, 6 gives 0.36 %. The notes left on genuine lines are substantives
(*omnia*, *boni*, *impiorum*), vocatives that are also adverbs (*inepte*, *beate*) and long hyperbaton (50.8 *incensus*).
Constants: `MIN_TOP_TOKENS`, `MIN_TOP_SHARE`, `FAR_GAP`.

## What the checks cannot see

- Anything that needs a parse: mood after *ut* / *cum* / *ne*, sequence of tenses, case usage (which case a verb takes,
  genitive and dative constructions), indirect statement. These go to the critic model with Allen & Greenough at hand.
- A blunder hidden by another reading passes, with a note where the hiding reading is rare or the neighbouring word
  speaks against it (above). Where the hiding reading is the commonest one and nothing stands next to it, nothing is said.
- Agreement is tested within the sentence, not within the phrase: an adjective that agrees with the wrong noun passes.
  A relative is tested for gender and number only, its verb not at all.
- A nominative that is also another case (*puella*, *puellae*) is not tested by rule d.
- Forms unread by every source (new names) fail rule a; that is a prompt to check the spelling, not a verdict.
