# Catullus's Phalaecian hendecasyllable: the measured manner

Counted from every line the Hypotactic hand scansion (David Chamberlain, CC BY 4.0) labels `hendecasyllables` in
Catullus, by `scripts/build_phalaecian_profile.py`; the numbers live in
`data/open/latin/phalaecian-profile/profile.json` and are read by the checks L13 (Phalaecian manner) and L8 (elision
and hiatus) in `backend/latin_metre_style.py`. Nothing here is a hand-made list: each figure is a count.

Template `x x - u u - u - u - x`; decasyllable variant (poems 55, 58b) `x x - - - u - u - x`.

**Against the Sapphic hendecasyllable.** The Phalaecian puts its choriamb early, at syllables 3-6, straight after a
free two-syllable base, while the Sapphic (`- u - x - u u - u - x`) puts it at syllables 5-8, after a fixed
trochaic opening. The Sapphic has a regular caesura after the 5th syllable (in Horace nearly always; after the 6th
as his later variant), whereas the Phalaecian has no fixed caesura: Catullus ends a word after the 6th in 61 % of
lines and after the 5th in 48 %, and in 9 % after neither.

## What was counted

| | Lines |
|---|---|
| Lines labelled `hendecasyllables` in the gold (43 poems) | 552 |
| Of 10 or 11 sounded syllables (denominator for base, elision, line end) | 550 |
| Hendecasyllables (denominator for word-ends and the main break) | 536 |
| Decasyllables | 14 |
| Left out: 55.10 (`Camerium`, resolved base, 12 syllables) and 55.11 (7-syllable fragment) | 2 |

A feature is called rare when it stands in under 2 % of the lines it could stand in (the task's threshold; of 550
lines that is 10 lines or fewer).

## Base (first two syllables), of 550 lines

| Base | Lines | Share |
|---|---|---|
| spondee (- -) | 477 | 86.7 % |
| iamb (u -) | 40 | 7.3 % |
| trochee (- u) | 33 | 6.0 % |
| pyrrhic (u u) | 0 | none |

Per poem (spondee / trochee / iamb of the poem's lines). Twenty-two poems have nothing but spondaic bases: 2b, 5, 6,
9, 10, 12, 13, 14, 14b, 15, 16, 21, 23, 24, 26, 28, 43, 46, 48, 56, 57, 58b. The other twenty-one:

| Poem | Lines | Spondee | Trochee | Iamb |
|---|---|---|---|---|
| 1 | 10 | 6 | 3 | 1 |
| 2 | 10 | 9 | 0 | 1 |
| 3 | 18 | 17 | 0 | 1 |
| 7 | 12 | 11 | 0 | 1 |
| 27 | 7 | 4 | 1 | 2 |
| 32 | 11 | 5 | 2 | 4 |
| 33 | 8 | 7 | 0 | 1 |
| 35 | 18 | 12 | 2 | 4 |
| 36 | 20 | 15 | 2 | 3 |
| 38 | 8 | 4 | 2 | 2 |
| 40 | 8 | 4 | 1 | 3 |
| 41 | 8 | 3 | 3 | 2 |
| 42 | 24 | 13 | 7 | 4 |
| 45 | 26 | 18 | 4 | 4 |
| 47 | 7 | 6 | 1 | 0 |
| 49 | 7 | 3 | 2 | 2 |
| 50 | 21 | 20 | 1 | 0 |
| 53 | 5 | 4 | 0 | 1 |
| 54 | 7 | 3 | 1 | 3 |
| 55 | 20 | 19 | 0 | 1 |
| 58 | 5 | 4 | 1 | 0 |

The free bases cluster: poems 27-58 hold 66 of the 73 non-spondaic bases; poems 1-26 hold 7 (four in poem 1, one
each in poems 2, 3 and 7).

## Word-end after each syllable, of 536 hendecasyllables

"Clear" counts a word-end with no elision across it; the last column also counts word-ends bridged by elision.

| After syllable | Clear | Share | With elided word-ends |
|---|---|---|---|
| 1 | 235 | 43.8 % | 261 |
| 2 | 262 | 48.9 % | 312 |
| 3 | 271 | 50.6 % | 285 |
| 4 | 38 | 7.1 % | 48 |
| 5 | 257 | 47.9 % | 300 |
| 6 | 327 | 61.0 % | 335 |
| 7 | 105 | 19.6 % | 144 |
| 8 | 251 | 46.8 % | 267 |
| 9 | 141 | 26.3 % | 154 |
| 10 | 6 | 1.1 % | 6 |

## Main break, of 536 hendecasyllables

| Word-end after | Clear | Share | Counting word-ends in elision | Share |
|---|---|---|---|---|
| the 5th only | 159 | 29.7 % | 181 | 33.8 % |
| the 6th only | 229 | 42.7 % | 216 | 40.3 % |
| both | 98 | 18.3 % | 119 | 22.2 % |
| neither | 50 | 9.3 % | 20 | 3.7 % |

## Elision

250 elisions in 205 of 550 lines.

| Elisions in the line | Lines | Share |
|---|---|---|
| 0 | 345 | 62.7 % |
| 1 | 165 | 30.0 % |
| 2 | 35 | 6.4 % |
| 3 | 5 | 0.9 % |

| Elision falls in the (the sounded syllable that takes up the elided one) | Elisions | Share of 250 |
|---|---|---|
| 1st | 4 | 1.6 % |
| 2nd | 31 | 12.4 % |
| 3rd | 62 | 24.8 % |
| 4th | 15 | 6.0 % |
| 5th | 11 | 4.4 % |
| 6th | 47 | 18.8 % |
| 7th | 8 | 3.2 % |
| 8th | 39 | 15.6 % |
| 9th | 19 | 7.6 % |
| 10th | 14 | 5.6 % |

| Kind | Elisions | Share of 250 |
|---|---|---|
| short vowel | 98 | 39.2 % |
| long vowel or diphthong | 90 | 36.0 % |
| -m | 62 | 24.8 % |

Monosyllables elided, 30 in all: te 8, me 5, cum 3, nam 2, quem 2, se 2, si 2, tu 2, quae 1, quam 1, qui 1, sum 1.

**Prodelision** (est losing its vowel after a vowel or -m): 20 lines of 550 (3.6 %); after -m 9, after a short
vowel 8, after a long vowel 3; 10 of them at line end. First loci: 2b.1, 3.2, 7.10, 9.10, 10.3. Fused spellings
(`malest`, 38.1) are not counted: the gold prints them as one word.

## Hiatus and synizesis

| Locus | Words | After syllable | Kind |
|---|---|---|---|
| 3.16 | `male! ō` | 5 | beside an interjection |
| 38.2 | `hercule, et` | 5 | at punctuation |
| 55.4 | `tē in` | 4 | semihiatus of a long monosyllable |

Three in 550 lines. L8 lets a hiatus pass only when it is of one of these three kinds and names the locus; each
kind rests on a single line, and 38.2 is a line editors often emend, so "at punctuation" is the weakest licence.
Synizesis once: 50.21 `vēhemēns` (two syllables).

## Line-end word, of 550 lines

| Syllables | Lines | Share |
|---|---|---|
| 1 | 7 | 1.3 % |
| 2 | 156 | 28.4 % |
| 3 | 245 | 44.5 % |
| 4 | 78 | 14.2 % |
| 5 | 43 | 7.8 % |
| 6 | 20 | 3.6 % |
| 7 | 1 | 0.2 % |

Monosyllabic endings: 5.5 `lūx`, 7.7 `nox`, 10.31 `mē`, 13.1 `mē`, 24.7 `est`, 50.20 `tē`, 55.13 `est`. The one
seven-syllable ending is 6.11. A word and its prodelided `est` count as one word (`molestum est`, three syllables).

## Decasyllables (14)

Poem 55: lines 1, 3, 5, 7, 8, 9, 13, 14, 16, 18, 20, 22. Poem 58b: lines 1, 9. They are 2.5 % of the lines, so not
rare by the 2 % rule, but they stand in these two poems only; L13 says so when a draft line is one.

## Rare features (under 2 %), with loci

| Feature | Lines | Of | Loci (up to 5) |
|---|---|---|---|
| elision at the 1st syllable | 4 | 550 | 13.11, 15.18, 55.4, 55.5 |
| elision at the 7th syllable | 8 | 550 | 6.2, 6.9, 14b.1, 24.10, 35.15 |
| three elisions in the line | 5 | 550 | 9.6, 15.7, 36.12, 45.3, 57.7 |
| line ending in prodelided est | 10 | 550 | 7.10, 10.3, 12.5, 12.16, 13.10 |
| line-end word of 1 syllable | 7 | 550 | 5.5, 7.7, 10.31, 13.1, 24.7 |
| line-end word of 7 syllables | 1 | 550 | 6.11 |
| hiatus at punctuation | 1 | 550 | 38.2 |
| hiatus beside an interjection | 1 | 550 | 3.16 |
| semihiatus of a long monosyllable | 1 | 550 | 55.4 |
| word-end after the 10th | 6 | 536 | 5.5, 7.7, 10.31, 13.1, 24.7 |

Rebuild: `.venv/bin/python scripts/build_phalaecian_profile.py`.
