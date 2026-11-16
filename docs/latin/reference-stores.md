# Latin reference stores: commentary and grammar

Two public-domain books the Catullan composer can consult: what a commentator says of a word or a line, and what
the grammar says of a rule. Built 2026-11-15. Reader: `backend/latin_reference.py`; command line: `scripts/la_ref.py`.

```
.venv/bin/python -I scripts/ingest_open_merrill_commentary.py     # -> data/open/latin/merrill-commentary/
.venv/bin/python -I scripts/ingest_open_allen_greenough.py        # -> data/open/latin/allen-greenough/
.venv/bin/python scripts/build_reference_la.py                    # -> data/reference_la.sqlite (gitignored, 7.6 MB)
.venv/bin/python scripts/la_ref.py commentary 5 7 | grammar 603 | search "long by position" | word bellus | intro Metres
.venv/bin/python -m pytest tests/test_reference_la.py -q           # 18 tests
```

## What was ingested

| Store | Source | Rows | File |
|---|---|---|---|
| Merrill, commentary | E. T. Merrill, *Catullus* (1893), Perseus TEI `Perseus:text:1999.02.0004`, one `dltext` request | 2,530 line notes + 118 poem headnotes | `merrill-commentary/notes.jsonl` (1.1 MB) |
| Merrill, Introduction | same file, `<text n="intro">` | 86 numbered sections under 13 headings | `merrill-commentary/intro.jsonl` (0.1 MB) |
| Allen and Greenough | *New Latin Grammar* (1903), Perseus TEI `Perseus:text:1999.04.0001`, one `dltext` request | 1,603 rows = 642 sections + 961 lettered subsections | `allen-greenough/sections.jsonl` (1.4 MB) |

| Allen and Greenough, subject map | the book's own Index of Words and Subjects (OCR of the archive.org scan `allengreenoughsn00alleiala`, same 1903 printing) + the headings of the TEI | 4,328 index references from 2,045 entries (3,526 confirmed) + 333 headings | `allen-greenough/subjects.jsonl` (0.9 MB) |

The three stores of text come from the Perseus TEI, not from OCR: the archive.org scan of Merrill (`catulluseditedby00catuuoft`) was not
needed, because the Perseus file holds the Introduction as well. Raw files and a per-source `fetch-log.jsonl` are in
`data/raw/latin/merrill-commentary/` and `data/raw/latin/allen-greenough/`.

**Merrill, notes.** Row: `id`, `poem`, `line` (as printed: `7`, `1-3`, `23b`), `line_start`, `line_end`, `kind`
(`note` / `headnote`), `lemma` (the phrase the note hangs on), `text`, `latin` (the Latin phrases Merrill prints in
the note, parallels quoted from other authors left out), `source_url`. 118 poem divisions (1-116 with 14b, 58b, 68a,
68b, 78b, and one division `18-20`). 193 notes have no lemma phrase (the note hangs on the line or the range).

Notes per poem (poem:notes): 1:24 2:24 3:28 4:38 5:15 6:16 7:20 8:20 9:14 10:40 11:26 12:19 13:19 14:33 14b:3 15:15
16:7 17:38 18-20:0 21:11 22:35 23:25 24:10 25:26 26:6 27:13 28:21 29:42 30:16 31:17 32:4 33:7 34:13 35:25 36:31 37:25
38:10 39:18 40:13 41:6 42:19 43:7 44:21 45:31 46:15 47:13 48:6 49:8 50:25 51:14 52:7 53:5 54:9 55:26 56:4 57:11 58:6
58b:13 59:6 60:6 61:165 62:85 63:138 64:420 65:30 66:107 67:39 68a:40 68b:127 69:10 70:4 71:9 72:8 73:8 74:4 75:5
76:26 77:7 78:6 78b:5 79:11 80:9 81:5 82:4 83:9 84:9 85:2 86:4 87:3 88:7 89:3 90:5 91:6 92:4 93:4 94:1 95:20 96:7
97:5 98:4 99:18 100:9 101:14 102:7 103:4 104:6 105:3 106:2 107:5 108:9 109:5 110:13 111:6 112:4 113:5 114:9 115:10
116:11.

Poems with no line notes: only `18-20` (three pieces the earlier editors inserted and the manuscripts do not have;
the division holds Merrill's headnote saying so).
The 42 hendecasyllabic poems (Merrill's list in Intr. 81, with 14b and 58b) carry 657 line notes. Merrill does not divide poem 2 (no 2b).

**Merrill, Introduction.** Row: `section` (Merrill's own number, 1-86), `heading_n`, `heading`, `text`. Headings:
1 Early Lyric Poetry at Rome (§§ 1-2), 2 Catullus (3-5), 3 Date of birth and of death (6-8), 4 Family and
circumstances (9-11), 5 Education (12-15), 6 Lesbia (16-28), 7 Journey to Bithynia (29-36), 8 Later years (37-43),
9 Poems (44-52), 10 Manuscripts (53-54), 11 Friends and foes (55-75), **12 Metres (76-85)**, **13 Prosody (86)**.
§ 81 is the Phalaecean; § 86 a-g is elision, diaeresis, synaeresis, hiatus, systole, diastole and final *s* (the
commentary cites it as "Intr. 86d"); the sub-letters stand inside the text of the one row (`subsections` lists them).

**Allen and Greenough.** Row: `section`, `sub` (empty for the section's opening text, else the letter), `heading_path`
(part > chapter > subsection > sub-subsection), `text`. Sections 1-642 are all present, none duplicated, none empty:
Part First (words and forms) 1-267, Part Second (syntax) 268-601 (334 sections), Prosody 602-642 (41 sections:
Quantity 602-606, Rhythm 607-611, Versification 612, Forms of Verse 613-629, Miscellaneous 630-638, Glossary 639-642). Mute and liquid is 603 f; elision, ecthlipsis and hiatus 612 e-g; the Phalaecean
is item 11 of 625.

Check made: the letters of every row, joined in order, equal the letters of the TEI body in order (724,334 letters;
only the 185 letters of the title lines before § 1 and the division headings, kept as `heading_path`, stand outside
the rows). Twelve sections were then read against the raw TEI by eye (11, 43, 113, 280, 341, 419, 486, 604, 608,
612, 625, 642): each opens and closes where the source does.

## Searching the grammar and the Introduction

`grammar_search` asks the book's own subject map before the text. **The index is not in the Perseus TEI** (the file
has no front or back matter), so it is read from the Internet Archive's OCR text of a scan of the same 1903 printing
(pages headed INDEX OF WORDS AND SUBJECTS; item rights fields: `possible-copyright-status: NOT_IN_COPYRIGHT`, no
`licenseurl`, no `rights`). The OCR is unaudited, so each reference is checked against the clean TEI: it is
`confirmed` when a word of its subject stands in the section it points to (for a range, every word in one section of
the range), and the lookups use confirmed references only (3,526 of 4,328). Subsection letters the OCR read as
digits (`603. 7` for 603. f) land on the whole section. Entries the OCR ran together are lost as subjects ("Sequence
of tenses" is one; the entry "tenses: sequence of, 482-485" survives). The 333 headings of the TEI are in the same
map and stand before the index at equal match. No alias is added by hand.

Order of results: subjects that hold the query (`match` `heading` or `index`, six places in ten at most); the phrase
in the text; subjects made only of words of the query, then index entries that hold it with their detail (three
each); the other text matches (all content words, any of them, then words that open alike: `stem`). Words such as
"and", "of", "by" are dropped outside the phrase; a word in the heading counts four times one in the text.

| Query | `grammar_search` lands on |
|---|---|
| common syllables | 11 c, 603 f (index: "Common syllables, 11. c, 603. f.") |
| position | 429 b, 11 b, 603 (index: "Position in Prosody"), then 603 f from the text |
| elision / hiatus / synizesis | 612 e / 612 g / 603 c and 642 (index) |
| diminutives | 243, 263 (index: "Diminutive endings") |
| cum clauses | 544, 323 g, 549 b (index entry *cum*), 540 d, 492, 493 |
| sequence of tenses | 485 d, 465, 518 a (index), then 485, 481, 484, 483 (phrase) |
| Phalaecean | 625 (text; the OCR spells the index entry "Phalecian") |
| **hendecasyllable** | **nothing**: the word is not in the book, which calls the verse Phalaecean (625. 11) |
| **mute and liquid** | **4 (the index entry Mutes), not 603 f**: the book gives the rule as "a mute followed by l or r" and indexes it under "Common syllables" and "Position in Prosody"; 603 f is 22nd for this query |

`intro_search` (Merrill's Introduction has no index; headings and text only): hendecasyllable -> 81, 61 (by stem:
he writes "hendecasyllabic"); Phalaecean -> 81; elision -> 82, 86; hiatus -> 76, 86, 82; diminutives -> 46 only (he
treats diminutives under the Poems; the word does not occur in 76-86).

## Licences (verbatim)

- Merrill TEI header: "This text may be freely distributed, subject to the following restrictions: You credit
  Perseus, as follows, whenever you use the document: Text provided by Perseus Digital Library, with funding from
  The National Endowment for the Humanities. Original version available for viewing and download at
  http://www.perseus.tufts.edu/hopper/. You leave this availability statement intact. You use it for non-commercial
  purposes only. You offer Perseus any modifications you make."
- Perseus page of the Merrill text (fetched 2026-11-15): "This work is licensed under a Creative Commons
  Attribution-ShareAlike 3.0 United States License."
- Allen and Greenough: the TEI header of the downloaded file has **no availability statement**. The Alpheios copy of
  the same Perseus digitisation (github.com/alpheios-project/grammar-allen-greenough, README) says: "This work is
  licensed under a Creative Commons Attribution-Noncommercial-Share Alike 3.0 United States License". The Perseus
  page of the text answered HTTP 403 ("Please allow cookies") and is not quoted.
- Each manifest carries these statements verbatim under `licence`, with a plain line (`licence.plain`): the
  underlying book is in the public domain and the encoding carries the quoted terms. The index OCR comes from an
  archive.org item marked `NOT_IN_COPYRIGHT` with no licence field.
- Both books are public domain (1893, 1903, United States). The two Perseus statements for Merrill disagree on
  commercial use; until that is settled, treat both stores as credit-Perseus, non-commercial, share-alike.

## Known faults

- These are Perseus's keyed transcriptions, so faults are few but real, and none is corrected here: `4O-43` for
  40-43 (Intr. 81); "a mute followed by 1 or r" for *l* (A&G 603 f, so the phrase "mute and liquid" does not occur
  in that row: search `common syllables` or `long by position`, or go to `603f`); 33 `<*>` gaps in A&G where the keyer could not read the page.
- A&G's metrical schemes are images in the edition: 54 are replaced by `[scheme]`, so the grammar's hendecasyllable
  (625.11) has its example line and its prose but not the diagram. Merrill's schemes are text (`oo -uu- u- u--`).
- Tie marks and some special signs are lost in the TEI: "deinde (for deinde)" at 603 c. 288 full-width `）` remain.
- A&G 43 and 49: the row for the section opens with "a." because the file puts the section mark on its first
  lettered paragraph.
- Merrill's Greek is beta code in the file, converted with the `betacode` package (153 notes; the beta code is kept
  in `greek_betacode`). Greek that the file tags as Latin is caught by its shape; one note (62.4) keeps a stretch of
  untagged beta code.
- Five remarks by the Perseus editors inside Merrill's Introduction are marked `[Note in the Perseus file: ...]`.
- Keying slips stand as found: `SYSYOLE` (Intr. 86 e), `flo[wacute]erets` and `Rā´ ui dī` (A&G 625).
- `notes_for_words` matches the lemma phrase and the Latin Merrill prints, not the English prose; lemmas come from
  the LASLA index, so a word outside Catullus and Horace matches by printed form only. Common words return many
  notes (the lemma-phrase matches come first).
- Perseus began answering 403 ("Please allow cookies") after four requests; the ingest scripts read the raw files
  already downloaded and fetch only what is missing. No TEI of either book was found in the PerseusDL GitHub
  repositories (one path guessed, 404; GitHub code search needs a login), so that route is unverified.

## Further sources (checked 2026-11-15)

Checked through `https://archive.org/metadata/<id>` (HTTP 200 each) and the Gutenberg pages; "pcs" is the item's
`possible-copyright-status` field, quoted. The item pages themselves were not opened.

**Commentaries on Catullus**

| Work | Open? | Where | Rights as stated | Note |
|---|---|---|---|---|
| Ellis, *A Commentary on Catullus*, 2nd ed. 1889 | yes | archive.org `commentaryoncatu00elliuoft`, `commentaryoncatu00elliiala`; 1st ed. 1876 `cu31924026493118` | pcs "NOT_IN_COPYRIGHT" (1876 item: no rights field) | English; OCR text exists (2.1 MB), fair, Greek and Roman numerals garbled in places. Not on Perseus. Its Prolegomena open the volume |
| Baehrens, *Catulli Veronensis liber* (1876-85) | yes | `catulliveronensi00catuuoft` (both volumes); vol. 2 alone `ldpd_8627272_002` | pcs "NOT_IN_COPYRIGHT"; second item no rights field | Latin; OCR good in the sample |
| Friedrich, *Catulli Veronensis liber* (1908) | yes | `catulliveronens01catugoog`, `catulliveronens00baehgoog` | pcs "NOT_IN_COPYRIGHT" | German; umlauts mangled in the OCR |
| Kroll, *C. Valerius Catullus* (1923) | no open scan found | `cvaleriuscatullu0000wilh` (1959 reprint) | "access-restricted-item = true" | lending only |
| Fordyce, *Catullus: A Commentary* (1961) | no | `catullus0000cjfo` | "access-restricted-item = true" | in copyright |
| Quinn, *Catullus: The Poems* (1970) | no | `catulluspoems0000catu` | "access-restricted-item = true" | in copyright |
| Garrison, *The Student's Catullus* | not confirmed | none found on archive.org | | modern textbook; assume in copyright |
| Thomson, *Catullus* (1997) | no | not on archive.org | | in copyright |

**Grammars**

| Work | Open? | Where | Rights as stated | Note |
|---|---|---|---|---|
| Gildersleeve and Lodge, *Latin Grammar* (3rd ed. 1895) | yes | `latingrammar00gild`, `gildersleeveslat00gilduoft` | pcs "NOT_IN_COPYRIGHT" | scan + OCR only; not on Gutenberg |
| Bennett, *New Latin Grammar* | yes | Project Gutenberg #15665 | "Public domain in the USA." | keyed text, not OCR |
| Lane, *A Latin Grammar for Schools and Colleges* | yes | Project Gutenberg #44653; scan `latingrammarfors00laneuoft` | "Public domain in the USA."; pcs "NOT_IN_COPYRIGHT" | keyed text, not OCR |
| Hale and Buck, *A Latin Grammar* (1903) | yes | `alatingrammar02buckgoog` | pcs "NOT_IN_COPYRIGHT" | OCR only |
| Kühner-Holzweissig, vol. 1 (2nd ed.) | yes | `ausfhrlichegra01khuoft` | pcs "NOT_IN_COPYRIGHT" | German; OCR |
| Kühner-Stegmann, Satzlehre 1 (1912), 2 (1914) | partly | `ausfuhrliche-grammatik-der-lateinischen-sprache-satzlehre-erster-teil`, `...-zweiter-teil` | part 1 no rights field; part 2 licenseurl "https://creativecommons.org/publicdomain/mark/1.0/" | user uploads; the text download of part 1 answered 404. Not on Perseus |

**On Catullus's language and metre (public domain, OCR text on archive.org)**

| Work | Where | Rights as stated |
|---|---|---|
| Munro, *Criticisms and Elucidations of Catullus* (1878), English | `criticismselucid00munriala` | pcs "NOT_IN_COPYRIGHT" |
| Riese, *Die Gedichte des Catullus* (1884), German commentary | `diegedichtedesc00catugoog` | pcs "NOT_IN_COPYRIGHT" |
| Heussner, *Observationes grammaticae in Catulli Veronensis librum* (1869), Latin | `observationesgra00heusuoft` | pcs "NOT_IN_COPYRIGHT" |
| Baumann, *De arte metrica Catulli* (1881), Latin | `bub_gb_HEg8AQAAMAAJ` | licenseurl "http://creativecommons.org/publicdomain/mark/1.0/"; OCR poor |
| Palmer's edition (1896) | `catulliveronen00catu` | no rights field |

Not confirmed as separate items: Ellis's Prolegomena (they open the commentary volume above), Bonnet, Hermes,
Postgate. Merrill's own Introduction §§ 76-86, already ingested, is the short treatment of Catullus's metres and prosody.

## Ellis's commentary: OCR, unaudited, not in the lookups

`scripts/ingest_open_ellis_commentary.py` -> `data/open/latin/ellis-commentary/notes.jsonl` (2.4 MB) + `manifest.json`,
from the archive.org OCR text of `commentaryoncatu00elliuoft` (2nd ed. 1889; item metadata: possible-copyright-status
"NOT_IN_COPYRIGHT", no `licenseurl` or `rights` field). It is **not** loaded into `data/reference_la.sqlite` and no
lookup returns it: the rows are too rough to stand beside Merrill's without an audit.

- 2,035 notes on 107 poems. No notes were recovered for 18-20, 85, 90, 91, 92, 108, 113, and none for some lines of
  other poems (51.1 for one): where the OCR broke a note's opening line number, that note's text sits at the end of
  the note before it. Ellis's poem introductions and excursuses are not separate rows; the Prolegomena are left out.
- The OCR keeps few poem headings (24 read, with 124 odd-page running heads), so the poem of a note is worked out:
  a fall in the line numbers opens a new run of notes, and each run is placed on the poem whose lines (Merrill's
  text, u/v folded) hold the words its notes open with. `poem_check` per note: `text-match` 1,198 (one of the note's
  first three words stands in that line of that poem), `segment-match` 604 (placed by other notes of its run),
  `unverified` 233 (no match: poem from the headings and the count of runs alone; expect errors).
- A spot check of 20 poem-and-line lookups found the expected note in 17; the other three (51.1, 85.1, 76.1 as a
  word match) were missing or opened with prose. No lemma phrase (the heavy type is lost), Greek often garbled,
  italics misread ("Zantum dat tibt Roma").
