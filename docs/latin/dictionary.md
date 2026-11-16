# Latin dictionary store and check L14 (2026-11-15)

Lewis & Short, whole, as a local store with a forward lookup, an English -> Latin lookup and the composer check
L14 "period and register" (PRD `docs/prd/catullan-hendecasyllable-checks.md`).

## What was built

| file | what |
|---|---|
| `scripts/build_dictionary_la.py` | Perseus TEI -> `data/lexica/lewis_short_la.sqlite` (123 MiB, gitignored; 8 s to build), plus the two committed files below |
| `data/open/latin/lewis-short/manifest.json` | source, licence, sha256 of the XML, counts |
| `data/open/latin/lewis-short/authors.json` | L&S author abbreviation -> name, obiit / floruit year, `before_ad14` |
| `backend/latin_dictionary.py` | `lookup(word)`, `reverse(english, limit=20)`, `check(text, *, metre_name, author)` (L14), `word_report`, `status` |
| `scripts/la_dict.py` | `la_dict.py <word>`, `la_dict.py --en "<english>"`, `la_dict.py --check "<draft>"` (`--json`, `--full`) |
| `tests/test_dictionary_la.py` | 11 tests (parser, labels, author table, authors on each side of A.D. 14, missing store, lookup, reverse and its sources, stems and G2, L14) |

Source: `data/raw/latin/lewis-short/lat.ls.perseus-eng2.xml` (Perseus Digital Library; sha256 `a21c3799...1836c`).
Licence, from the file's header: "Available under a Creative Commons Attribution-ShareAlike 4.0 International
License". The store is a derived work under the same licence; it is rebuilt, not committed.

Store tables: `entries` (headword as printed with macrons, folded key, type, part of speech, gender, inflection,
opening line, labels, authors with counts, whole entry as plain text), `senses` (order, level, number, labels,
English glosses, quote translations, text), `citations` (author, work, locus, CTS URN, quote, sense), `forms`
(every `<orth>` of an entry, folded: sub-headwords and variant spellings resolve to their entry), `authors`,
`sense_fts` (FTS5 over headword, glosses, translations).

### Measured

| | |
|---|---|
| entries | 51,645 |
| senses | 101,982 (80,411 with an English gloss; 14,289 with a quote translation) |
| citations (tagged `<bibl>`, author resolved) | 379,558; 1,098 dropped (no author, modern scholars) |
| Catullus citations | 1,701 in 1,242 entries |
| entries with no tagged citation | 10,606 (cross-references, names) |
| folded headword forms | 70,255 |
| authors in the table | 231 abbreviations, 10 undated collections |
| Catullus interlinear pairs (table `interlinear`) | 8,268 English stem / Latin lemma pairs from 2,308 lines; 2,739 stand in two lines or more |
| entries by label | class. 2,822; post-class. 2,636; post-Aug. 2,044; late Lat. 1,643; poet. 1,333; rare 1,075; ante-class. 995; very rare 940; eccl. Lat. 705; jurid. Lat. 113 |
| Catullus vocabulary with an entry | 3,057 of 3,161 lemmas of the lemma index (96.7 %; 98.9 % of his 13,129 tokens) |

The 104 lemmas without an entry are mostly names (Acme, Allius, Aufilena, Cybele, Ipsithilla), substantivised
plurals the index lemmatises apart (boni, ceteri, caelestes), spellings L&S prints otherwise (langor / languor,
brachiolum / bracchiolum, laserpitifer / laserpicifer) and a few obscenities and nonce words L&S omits (defutuo,
diffutuo, insapiens).

Citations are those Perseus tagged. A locus printed bare after a tagged one ("16, 12; 99, 16" in *basium*) is in
the entry text but not in `citations`; `id.` and an authorless `<bibl>` inherit the preceding author.

Labels are read from the entry's opening (from the first English gloss to the first citation after it, 300
characters at most) and, per sense, from the sense's opening. L&S prints them as running text ("rare and mostly
poet.", "ante- and post-class."), not as tags, so this is a pattern match. Known weakness: "late Lat.; class.
servator" (*salvator*) also yields `class.`, which names the classical synonym; `class.` is never used to decide.

### The author table

L&S's own "Abbreviations used in referring to ancient authors and their works" (dates "on the authority of
Teuffel") is not in the Perseus XML. It was taken from the Wikisource transcription
(https://en.wikisource.org/wiki/A_Latin_Dictionary#ABBREVIATIONS, Wikisource text CC BY-SA 4.0, the dictionary
itself public domain), fetched 2026-11-15 and kept at `data/raw/latin/lewis-short/abbreviations.wikisource.txt`.
`before_ad14` is true for a floruit by A.D. 14 or a death by A.D. 34 (Livy and Ovid died in 17). Eleven rows are
editorial and say so in their `source` field: the Vulgate (405), the legal codes, Notae Tironianae, and three
corrections of the list as transcribed (below). Plin. and Sen. each cover two authors, all after A.D. 14.

Audit of every row for era and date (second pass, 2026-11-15). All 231 rows were read against the list. Found:

| error | effect | fix |
|---|---|---|
| Prisc.: the list as transcribed prints "fl. B.C. 500" | Priscian counted as an author before A.D. 14: 1,156 citations in 946 entries, and for 247 entries he was the only "early" witness; the report printed `earliest=Prisc. (fl. B.C. 500)` | editorial row, fl. A.D. 500 |
| Lampr. printed "ob. B.C. 300"; Ampel. "fl. (?) 200" with no era | caught in the first pass | editorial rows, A.D. 300 and 200 |
| a floruit of exactly A.D. 14 (Monum. Ancyr., At. Cap.) fell outside `year < 14` | the Res Gestae counted as later than Augustus | floruit by A.D. 14 counts |
| list against practice: the list's "August." is Augustus and "Pomp." is L. Pomponius (comic, B.C. 90), but L&S's citations under them are Augustine (Conf., C. D., Serm.; 103) and mostly Pompeius on Donatus (12) | either would vouch for a late word as early | both resolve to rows after A.D. 14 (`ALIASES`) |
| "Nov." is both Novius (B.C. 90) and the Novellae / Novatian | ambiguous | a shared abbreviation is early only if every namesake is |

The other 65 B.C. rows are republican or Augustan authors and stand. Four aliases that the table made redundant
were dropped. Not done: collation of the transcription against a scan of the printed list, and a check of every
abbreviation's use in the XML against its row (only the collisions above were found by reading works cited).

## L14 period and register

For each distinct word: readings (`backend.latin_lemma.readings`, at most three) -> L&S entries; a form with no
reading is tried as a headword, then with -que / -ne / -ue removed. Per entry:

- **warn**: the entry cites dated authors and none before A.D. 14; or it is labelled post-class. / post-Aug. /
  late Lat. / eccl. Lat. and cites no classical-period author (dated from B.C. 85 on and before A.D. 14), which
  catches "ante- and post-class." words known only from Plautus and Apuleius.
- **note**: a late label on an entry that does cite classical authors (the label then qualifies a form, a sense or
  a construction); poet., ante-class., rare, jurid. labels; the loci and sense L&S cites from the target author;
  only undated sources; no author at all.
- never a warning: a word L&S cites the target author for; a lemma the target author's own text holds (lemma
  index); a capitalised word that is not line-initial (a name); a form with another reading that is unobjectionable.
- **no entry** is listed, not warned.

`ok` is false when a word warns; `blocking` is always false; a missing store returns `ok: True` and a detail
beginning `unavailable:`.

### False alarms on Catullus (every warning is one by construction)

All 5,815 distinct forms (13,129 tokens) of Catullus in the lemma index, with the corpus rule switched off so that
only the dictionary rule is measured:

| rule | forms warned | tokens |
|---|---|---|
| first version: any late label in the opening warns | 72 (1.24 %) | 83 (0.63 %) |
| final rule, dictionary only | 6 (0.10 %) | 6 (0.05 %) |
| final rule as shipped (lemma in Catullus never warns) | 0 | 0 |
| held out, Horace: 16,079 forms / 45,007 tokens, dictionary only | 11 (0.07 %) | 14 (0.03 %) |
| held out, Horace, as shipped with `author="Horace"` | 0 | 0 |

These are the figures after the author-table audit. Catullus is unchanged (6 forms, 6 tokens; statuses ok 2,827,
note 2,882, no entry 100). Horace gained one, *auerrere*: L&S's *averro* cites Licinius Macer through Priscian
only, and Priscian no longer counts as early.

First version, the top 30 of 72 (form, entry, label) and the cause, which was the rule's: the label belongs to one
form, sense or construction of a word that L&S cites from Cicero, Lucretius or Virgil in the same entry.
pelagi x4 (pelagus, post-Aug.), perhibent x2 (post-Aug.), oportet x2 (late Lat.), nefando x2 / nefanda (post-Aug.),
ineptiarum x2 (post-class.), immiti x2 (post-Aug.), extremo x2 / extremis x2 (exter, post-class.), aspicite x2
(eccl. Lat.), uicem (post-Aug.), udo (post-Aug.), tutamen (post-class.), tinnitus (post-Aug.), tegmina (post-Aug.),
susurrat (post-class.), socii (post-Aug.), sessores (post-Aug.), scorti (post-class.), scabra (post-Aug.),
rediuiuis (late Lat.), reclude (post-Aug.), properante / properans (post-Aug.), praecerpens (post-Aug.), perenne
(post-Aug.), penetrabit (post-class.), paenitet / paeniteat (late Lat.), oscula (post-Aug.), obiurgare
(post-class.), nautis / nauita (late Lat.). Fix: a late label warns only when the entry cites no classical-period
author. Two more causes were the rule's and are fixed: *Marce* read as *marcus* "a hammer" (Isidore) and *Rauide*
as *ravidus* (Columella), now treated as names.

Final rule, the 6 that remain, all gaps in L&S or in the lemma, none in the author table:

| form | entry | cause |
|---|---|---|
| uirentium (and Horace's uirentis, uirenti, uirentem) | virens | L&S's participle stub cites Columella only; the verb is *vireo* |
| exarsit | ex-ardeo (eccl. Lat., Vulgate) | the form belongs to *exardesco*; the reading offered is *exardeo* |
| suppernata | sup-pernatus | L&S cites it through Festus; the Catullus locus is not tagged |
| pipiabat | pipio | L&S cites Tertullian; it reads Catullus 3.10 under another verb |
| fellat | fello | L&S cites Martial only |
| omentum | omentum (post-Aug.) | L&S cites Celsus, Persius, Pliny; Catullus 90.6 is missing |

Horace's other seven: porrum / porri, siser (Columella), germinat, mangonum (post-Aug. in L&S), promissor (L&S
cites Quintilian; Horace A.P. 138 untagged), ciniflones (Tertullian), auerrere (Priscian only; S. 2.4.37 untagged).

### It warns on late words

`check("salvator incarnatus beatificans trinitas baptizo resurrectio sanctificare glorificare spiritualis salvare
mundialis confortare carnalis possibilitas essentialiter")` warns on 14 of 15, e.g. "salvator: labelled late Lat.;
no author before A.D. 14 (earliest Tert. (ob. A.D. 220))". *spiritualis* is a note: L&S labels it post-Aug. but
cites Vitruvius. Not measured: a recall figure on a labelled set of late words; 15 hand-picked words is a
demonstration, not a rate.

## Reverse lookup

`reverse(english, limit)` reads two sources of its own and, when `data/lexica/lex_smith_hall.sqlite` is built, a
third, Smith & Hall's English-Latin dictionary (`smith-hall`; `docs/latin/lexica.md`, Wiring). Every row says
which found it in `sources`:

1. `lewis-short`: L&S's glosses through FTS5. Three tiers: a gloss equal to the query in the entry's first glossed
   sense; an equal gloss in a later sense or a containing gloss in the first; the rest by score. Inside the first
   two tiers Catullus's count orders, then Horace's.
2. `catullus-interlinear`: the audited literal English of Catullus (`data/open/latin/interlinear-catullus/`,
   2,308 lines, one English line per Latin line). The builder stems the English content words lightly (kisses,
   kissed, kissing -> kiss), lemmatises the Latin line with `backend/latin_lemma.py`, and scores each English stem
   against each lemma of the same line with Dunning's log-likelihood (G2), lines as events. Kept: pairs in two
   lines or more with G2 >= 6.63 and above chance, and one-line pairs whose English word stands in two lines at
   most and whose lemma in five at most. Each row keeps its loci, its first line in Latin and English, and the
   rank of the English word among the lemma's own.

Merge: words both sources give come first (strongest Catullan association first); then Catullus's own words that
L&S glosses otherwise, if they stand with the English word in two lines or more, the English word is the lemma's
strongest, and G2 >= 10.83 (five at most); then L&S's other headwords. A row's `interlinear` field gives count,
G2, loci, and the first line in both languages.

Checked by hand (top 5; LS = lewis-short, Cat = catullus-interlinear, with loci; last figure = Catullus's count):

| query | top 5 |
|---|---|
| witty | dicax (LS+Cat 22.2; 1), urbanus (LS+Cat 22.2; 5), perurbanus (LS; 0), Bion (LS; 0), salio = salsus (LS; 1) |
| charming | venustus (LS+Cat 3.2, 22.2, 31.12, 89.2, 97.9; 6), lepidus (LS+Cat 1.1, 6.17, 78.1, 78.2; 4), lepor (LS+Cat 16.7, 32.2, 50.7; 4), bellus (LS; 14), amoenus (LS; 0) |
| darling | deliciolae (LS; 0), monnula (LS; 0), gratus (LS; 5), pullus (LS; 0), mellitulus (LS; 0) |
| kiss | basium (LS+Cat 5.7, 5.13, 7.9, 16.12, 99.16; 5), basio (LS+Cat 7.9, 8.18, 48.2, 48.3; 4), suavium (Cat 78.8, 79.4; 2), savio (Cat 99.2, 99.14), suavior (LS; 1) |
| trifles | nugae (LS+Cat 1.4; 1), ineptio (LS; 1), tricae (LS; 0), gerrae (LS; 0), butubatta (LS; 0) |
| tasteless | insulsus (LS+Cat 10.33; 3), ineptus (LS; 5), inelegans (LS; 1), bliteus (LS; 0), insipidus (LS; 0) |
| sweetheart | amatrix (LS; 0), puella (LS; 42), suus (LS; 28), domina (LS; 9), mellilla (LS; 0) |
| to joke | iocor (LS+Cat 2.6, 21.5; 2), iocus (LS+Cat 42.3, 50.6; 3), alludo (LS; 1), irrideo (LS; 0), ioculus (LS; 0) |
| napkin | linteum (Cat 12.3, 12.11; 5), orarium (LS; 0), sabanum (LS; 0), mappa (LS; 0), involucrum (LS; 0) |

What this shows. The interlinear fixes the cases where it uses the English word: *venustus*, *lepidus*, *lepor*
for "charming" (L&S alone put *bellus* first and *lepidus* nowhere near), *insulsus* for "tasteless", *linteum*
for "napkin" (L&S glosses it "a linen cloth" and never found it). Its limits, all visible above:

- It answers only in the translator's words. The literal English renders *deliciae* "delight" and *mellitus*
  "honeyed", so "darling" and "sweetheart" get nothing from Catullus and fall back on L&S, where *deliciae* sits
  ninth and fifth. "Witty" stands in two lines only (12.4, 22.2): *facetus* and *lepidus* are rendered otherwise.
- The association is co-occurrence in a line, not word alignment. Without L&S's agreement a neighbour can come
  through; the two-line and strongest-word conditions removed *puella*, *deliciae*, *meus* from "sparrow" and
  *mordeo* from "kiss", at the price of dropping one-line words that L&S does not gloss with the query.
- The lemma is the lemma index's, the headword is L&S's: *salsus* is found under L&S's *salio*, and the two
  spellings *savium* / *suavium* come out as two rows.

Better than either: a synonym step (query -> L&S's glosses for Catullus's own words) or a real English-Latin
dictionary; see below.

## Larger lexica: survey (checked on the web 2026-11-15)

None ingested in this pass. Items that could not be verified today are marked.

| lexicon | open copy | licence as stated | form |
|---|---|---|---|
| Thesaurus Linguae Latinae | https://thesaurus.badw.de/en/tll-digital/tll-open-access.html (60 PDFs on publikationen.badw.de): A-M, O-P, N to *netura*, R to *resurgo*; later R fascicles scheduled 2027-2029; no Q, S-Z | "License: CC BY-NC-ND" (https://publikationen.badw.de/en/thesaurus; no version number) | PDF. One recent fascicle tested (XI 2,5 *refodio-regnum*, 65 pp.): born-digital text layer, Greek garbled, margin line numbers interleaved. Older volumes not tested (probably scans). |
| Oxford Latin Dictionary, 2nd ed. 2012 | none | in copyright (OUP). Not re-verified today: the OUP page returned nothing | the owner's own scan would be private-use only, never redistributed |
| Georges, Ausführliches lateinisch-deutsches Handwörterbuch (1913-18) | http://www.zeno.org/Georges-1913, HTML plus facsimiles, "mehr als 62.000 Hauptstichwörtern" | labelled "Gemeinfrei", but Zeno's terms allow use "ausschließlich zu privaten, nicht kommerziellen oder gewerblichen Zwecken" and forbid taking substantial parts into another database | a GitHub JSON copy (`Poliorcetes/Georges-Lateinisch-Deutsch`) has no licence or provenance; no TEI found |
| Forcellini, Lexicon Totius Latinitatis | `latin-dict/Forcellini` on GitHub; scans on archive.org | repository CC0-1.0, "distributed as Public Domain" | HTML / GoldenDict; lexica.linguax.com could not be read (bot check) |
| Gaffiot 2016 (Gréco) | http://gerardgreco.free.fr/spip.php?article12 | "© Gérard Gréco 2013-2014-2015-2016 --- Tous droits réservés." A CC BY-NC-ND claim seen elsewhere was not confirmed | PDF; StarDict builds by third parties; TeX source on request "for non-commercial use"; 72,165 entries with a frequency index |
| Döderlein, Hand-book of Latin Synonymes | https://www.gutenberg.org/ebooks/33197 | "Public domain in the USA" | plain text, 550 kB (1875 Andover edition); the German original only as archive.org scans |
| Smith & Hall, Copious and Critical English-Latin Dictionary (1871) | archive.org `copiouscriticale00smit` (OCR); `nikita-moor/latin-dictionary/SmithHall1871/dict.xdxf` | archive.org "NOT_IN_COPYRIGHT"; the XDXF carries the Public Domain Mark | XDXF, 16.5 MB, about 27,000 articles, marked abandoned, about 65 % unformatted, OCR errors. Latinitium's clean edition states no licence: do not scrape |

### What to ingest next, in order

1. **Smith & Hall** as the English -> Latin index: ingest the XDXF, repair against the archive.org OCR, and resolve
   every Latin candidate to its L&S entry so the reverse lookup returns period labels and Catullus counts with it.
   It replaces the gloss matching above, which is the weakest part of this pass.
2. **Döderlein** from Gutenberg: small, clean, free; it answers "which of these near-synonyms" (L&S already cites
   "Doed. Syn." by volume and page).
3. **Tag the untagged L&S citations** (bare loci after a tagged one, "ap. Fest."): it would remove most of the six
   residual false alarms and costs no new source.
4. **TLL as lookup only**, per lemma, for hard cases: the NoDerivatives term and the missing letters (Q, S-Z) rule
   out a bulk store; a private text index for search is a question for the owner, not a default.
5. **OLD** (the owner's scan) and **Georges**: private, never redistributed. The OLD is the one that would change
   L14 itself, since its coverage stops at about A.D. 200 and its citations are dated; Georges adds little for an
   English-speaking pipeline. **Gaffiot 2016** needs Gréco's permission.
