# Latin scansion and corpus: prior art and open sources

Date: 2026-10-10 (Pacific). Branch `latin-composer`. Survey rows: `data/open/latin/survey-2026-10-10/rows-{a,b,c}.jsonl`
(22 + 64 + 38 = 124 rows) with `summary-{a,b,c}.md`. Companion to the Greek survey `docs/open-sources-survey-2026-10-09.md`
and to the Greek scanner's prior-art table in `docs/scansion.md` §2. PRD: `docs/prd/latin-composer.md` §4.2, §4.4, §5.

## 1. Summary

Hypotactic Latin (David Chamberlain) is the gold set. Its licence is on `hypotactic.com/latin/about.html` itself: "All the
data on this site is/are licensed as CC-BY 4.0". It is ingested on this branch (`scripts/ingest_open_hypotactic_latin.py`
into `data/open/latin/hypotactic/`): `catullus.html` (2,287 lines, 118 poems, 552 hendecasyllable lines in 43 poems) and
`odes1.html` (876 lines, 38 odes). Pedecerto is dactylic-only, non-commercial and forbids mirroring; not used. Quantity
lexicon: the clean route is Wiktionary via Kaikki (CC BY-SA + GFDL, 842,381 forms) plus Collatinus (GPL-2.0-or-later in
every data file; 81,981 lemma lines with quantities) plus Lewis & Short headwords (CC BY-SA 4.0); Winge's `macrons.txt`
(283,023 forms, the richest table) has no data licence and stays a comparator until its author answers. Texts: PerseusDL
`canonical-latinLit` (CC BY-SA 4.0) covers Catullus (Merrill 1893), Horace, Martial, Statius, Tibullus/Sulpicia, Seneca;
Latin Wikisource (CC BY-SA) adds Priapea, Pervigilium and a second Catullus; Calvus, Cinna, Laevius exist only as PD scans.
Translations: Smithers, Burton, Conington (Odes) and Smart (Satires, Ars) are poem-aligned TEI; Smart's Odes and Ellis are
clean Gutenberg texts; Cornish 1904 is transcribed on en.wikisource; the rest are scans needing OCR. Lemmatiser: LatinCy
`la_core_web_lg` first (MIT weights, lookup table off), then the Stanza models; Morpheus Latin (CC BY-SA 3.0 US) and
Whitaker's WORDS (permissive) answer "does this form exist". LASLA (CIRCSE/LASLA v1.0.1) gives hand-verified lemmas for every
token of Catullus and Horace, under CC BY-NC-SA 4.0. Blocked or needing the owner: the NC licences (LASLA and EvaLatin, the
LatinCy lookup table, the ITTB/PROIEL/Perseus treebanks and models trained on them), Winge's data terms, Pedecerto, Kline's
translations (non-commercial only), Catullus Online (no terms stated).

## 2. Method

Three passes on 2026-10-10 (fetch times 2026-10-11 UTC): A scansion tools and quantity resources; B texts, translations,
commentaries; C lemmatisers, morphology, dictionaries, lemma gold. Every request used `User-Agent: Melos/1.0
(+https://greeklyric.com)`; robots.txt obeyed per host (Zenodo `/api/`, LiLa `/data/`, the ULiège Dataverse and every
Perseus Hopper path were disallowed and not fetched); no logins, paywalls or pirate uploads; nothing over 50 MB downloaded
(Lewis & Short XML, the Kaikki dump, the LatinCy `trf` wheel and the 29 MB Hypotactic zip were sized, not fetched). Licences
were quoted verbatim from the fetched page or file and hashed (sha256 in the rows); rows without such a quote say
"unverified". Blocked: HathiTrust answered HTTP 403 even for robots.txt; the GitHub API rate limit stopped some tree
listings; Project Gutenberg's search is disallowed, so author pages were used. Raw fetches are in the session scratchpad.

## 3. Scansion tools and quantity resources

| Resource | What | Licence (as quoted in rows-a) | Accuracy claimed | Verdict | What we take |
|---|---|---|---|---|---|
| **Hypotactic Latin** (Chamberlain) | hand scansion as HTML: `span.syll.{long,short,elided}` plus classes hiatus, synizesis, lengthening, diastole, systole, resolved, hypermetric | "All the data on this site is/are licensed as CC-BY 4.0" (about.html) | none (hand-made) | use, gold only | Catullus and Odes 1 ingested; 29 MB site zip later (Odes 2-4, Epodes, Sermones, Epistulae, Ars; no Carmen Saeculare in the menu) |
| **Pedecerto / MQDQ** | machine scansion of MQDQ; hexameter and pentameter lines only; `allpedecertoscans.zip` 12.0 MB | "Tutti i diritti riservati"; "Non ne è consentito alcun uso a scopi commerciali se non previo accordo"; mirroring and automatic capture forbidden | none | ask_author (mqdq-galaxy@unive.it); not used | nothing: dactylic only, so no hendecasyllables |
| **Winge, latin-macronizer `macrons.txt`** | RFTagger + Morpheus-generated lexicon; 812,588 rows, 283,023 forms, TSV with `_`/`^` | repo GPL-3.0 (code); no data statement; content is Morpheus output (CC BY-SA 3.0 US) plus overrides | site "about 98% to 99%"; thesis "about 98% of the vowel lengths" | ask_author (johan.winge@gmail.com); evaluate_only now | coverage comparator; not in the lexicon until answered |
| **CLTK `prosody.lat`** (v1.5.0; pin `cltk==1.5.1`) + `lat_models_cltk` `macrons.txt` | deterministic hexameter, pentameter, hendecasyllable fit (CLTK 2.x has no prosody module); `macrons.txt` is a 2016 snapshot of Winge's file, 755,557 rows, 257,615 forms | MIT (code and models repos); the data is Morpheus-derived | none | evaluate_only (scanners); superseded (data) | baseline score on the gold; its hendecasyllable template |
| **Collatinus lexicon** | `lemmes.la` 24,072 + `lem_ext.la` 57,909 lemma lines with ā/ă; `modeles.la` paradigms with ending quantities | every data file: "GNU General Public License ... either version 2 of the License, or (at your option) any later version" | none | use | lemma + paradigm quantities; forms must be generated; derived table stays GPL-compatible and separate from app code |
| **Perseus Morpheus Latin stemlib** | upstream of every Latin macron list; `ls.nom` 136,212 stems from Lewis & Short | "Creative Commons Attribution-ShareAlike 3.0 United States License" | none | use | regenerate a form table if Winge declines; needs a new container (image is Greek-only) |
| **Wiktionary Latin (Kaikki)** | 842,381 forms; macrons in headwords and inflection tables; JSONL 1.1 GB | "both CC-BY-SA and GFDL" | crowd-sourced | use | per-form marks, same pipeline as Greek; fetch on the laptop (box disk at 97-98 %) |
| **Lewis & Short** (PerseusDL/lexica) | TEI 77.4 MB; `<orth>` carries macrons/breves (252 of 319 in a 400 KB sample) | "CC BY-SA 4.0 ... You credit Perseus" | - | use | lemma-level marks; glosses |
| Gaffiot 2016 (Gréco) | headwords with quantities; 21.6 MB JS blob "Tous droits réservés" | "Attribution-NonCommercial-NoDerivatives 4.0" on a Wayback copy of Gréco's page; live pages state nothing (pass C: unverified) | - | no | its lemmas reach us only through Collatinus `lem_ext.la` |
| Whitaker's Words | dictionary + morphology; "does not currently support vowel length" | "Permission is hereby freely given for any and all use of program and data" | none | no (quantities); use (analyser) | L1 fallback analyser |
| Anceps (Fedchin) | metre as constraint over Winge + MQDQ frequency dicts (`MqDqMacrons.json` 18.9 MB) | no licence file (unverified) | "around 10%" of trimeters need a human | ask_author | the method is already ours |
| latin_scansion (CUNY-CL) | Pynini FST hexameter grammars | Apache-2.0 | none | evaluate_only | hexameter baseline only |
| Scandroid; student scanners; Ycreak NN (Nolden 2022); Signatrix; LASY; latin-scanner (npm); two Winge forks | Scandroid "scans metrical English verse"; the rest are hexameter toys or an NN trained on Pedecerto data | GPL (Scandroid); mostly none / unverified | none | no | - |
| Macronised texts (Nova Vulgata by hand; Latin Library auto; KaanGoker HF); Logeion | texts, not scansions; aggregated dictionary site | none; HF "license: mit" on Latin Library text; Logeion none published | - | no (Logeion off limits) | Nova Vulgata as an eval text only if its author grants a licence |

No open Latin scanner found publishes a measured accuracy on a hand-scanned gold set. Compare `docs/scansion.md` §2: the
Greek side had the same gap, and Hypotactic filled it there too.

**Does the owner's doubt hold?** Partly. Latin vowel length is lexical plus position: position is a rule, a vowel's own
length must come from a lexicon. Macronised resources exist: Winge 283,023 forms, Collatinus 81,981 lemma lines with
quantities, Wiktionary 842,381 forms, Lewis & Short headwords, Latin WordNet 74,795 lemmas with prosody. But their upstreams
are mostly Morpheus Latin and Lewis & Short (Winge, CLTK, Anceps and Morpheus are one lineage; Collatinus and Wiktionary draw
on Lewis & Short and Gaffiot), so agreement between them is not independent evidence (PRD §4.2). Coverage on Catullus and
Horace, hapax forms separately, is still to be measured (LA2). Until then the doubt is a measurement to make, not a verdict.

## 4. Texts

| Poet | File or page | Edition | Licence (as quoted in rows-b) | Verdict |
|---|---|---|---|---|
| Catullus | PerseusDL `data/phi0472/phi001/phi0472.phi001.perseus-lat2.xml` (116 poems, 2,318 `<l>`) | Merrill, Ginn 1893 | file header "Available under a Creative Commons Attribution-ShareAlike 4.0 International License" | use (primary) |
| Catullus, 2nd witness | la.wikisource `Carmina_(Catullus,_ed._Merrill)`; `Carmina_(Catullus,_ed._Cornish)` | Merrill 1893; Cornish, CUP 1904 | footer: "hunc textum tractare licet secundum "Creative Commons Attribution-ShareAlike License"" | use for diffing |
| Catullus, apparatus | catullusonline.org (Kiss) | Kiss's text + repertory of conjectures | no terms stated; only "The copyright © of these images is asserted on behalf of the respective libraries" | record_only; ask kiss [apud] ub.edu |
| Horace Odes | PerseusDL `phi0893.phi001.perseus-lat2.xml` (3,034 lines) | Shorey and Laing 1919 | repo `license.md` "Attribution-ShareAlike 4.0 International"; file has no `<availability>` | use |
| Horace Carmen Saeculare; Epodes | `phi0893.phi002` (76 lines); `phi0893.phi003` (625 lines) | Shorey and Laing 1919; Vollmer, Teubner 1912 | repo | use |
| Horace Sat., Ep., Ars | `phi0893.phi004-006` (2,116 / 1,492 / 476 lines) | Smart 1836 Latin; Fairclough 1929; Smart 1836 | repo | use, lower priority (hexameters) |
| Martial | `phi1294.phi002` (9,462 lines) | Heraeus rev. Borovskij, Teubner 1925/1976 | repo; the 1976 revision is in copyright (recorded, not gating) | use; la.wikisource copy "editio: incognita" record_only |
| Statius Silvae | `phi1020.phi002` (3,901 lines; Phalaecians 1.6, 2.7, 4.3, 4.9) | Mozley, Loeb 1928 (PD-US since 2024) | repo | use |
| Tibullus / Sulpicia | `phi0660.phi001` (1,933 lines; Sulpicia at 3.13-18); `phi0660.phi003` lat2 + eng2 (40 lines) | Postgate OCT 1915; Mahoney 2000 | repo | use |
| Seneca tragedies | `phi1017.phi001-phi010` (ten plays) | Peiper and Richter, Teubner 1921 | repo | use; choral odes not tagged, locate by line range |
| Ausonius | PerseusDL stoa0045 (De Bissula, Caesares only); la.wikisource 40+ works with no edition; Evelyn-White Loeb scans (§5) | - | repo / footer / IA NOT_IN_COPYRIGHT | record_only (Perseus); scans for the rest |
| Priapea | la.wikisource `Priapea` (1-80 on one page) | "editio: incognita fons: incognitus" | footer CC BY-SA | use; edition unknown (record); not in PerseusDL |
| Pervigilium Veneris | la.wikisource `Pervigilium_Veneris` (93 lines) | "editio: 1848" (old orthography) | footer CC BY-SA | use; Mackail's Loeb Latin is scan-only |
| Calvus, Cinna, Laevius | IA scans: Mueller, Teubner 1892 `catvllitibvllip00catugoog`; Baehrens FPR 1886 `bub_gb_qhE_ZFDini8C`; Morel FPL 1927 `fragmentapoetaru00baeh` | Teubner editions | "NOT_IN_COPYRIGHT"; "licenseurl ... publicdomain/mark/1.0/"; no rights field (PD-US by date, unverified) | use after OCR; la.wikisource Cinna is a Latin Library copy (record_only); Calvus 404; Laevius empty |
| Not sources | PHI ("only for personal study and not to make copies"); Latin Library (no licence; Catullus follows Mynors 1958); MQDQ (all rights reserved, no mirroring or capture); Perseus Hopper (robots.txt disallows all) | - | - | no / record_only |

PRD §5.1 assumptions the survey overturns:

- DCC has none of these poets. Its only "Sulpic*" text is Sulpicius Severus. Its CC BY-SA licence is real but useless here.
- Bennett 1914 Loeb: no free scan of the 1914 or 1927 printing exists on archive.org; the only free item is a 1968 reprint. Record only.
- Cornish 1913 Loeb: the free scan is the 1918 printing with no rights field (PD-US by date, unverified). Cornish's 1904 CUP text is on Wikisource: Latin on la.wikisource, English as an en.wikisource Proofread-Page transcription.
- The PRD says the Perseus Merrill text is CC BY-SA 3.0. The file header says 4.0.
- Catullus Online states no terms at all, so "if its terms allow" cannot be answered without writing to the editor.
- Hypotactic's Horace menu has no Carmen Saeculare.

## 5. Translations

| Translator | Year | Work | Clean e-text or scan | URL or id | Rights as stated | Verdict |
|---|---|---|---|---|---|---|
| Smithers (literal prose) | 1894 | Catullus | clean; poem-aligned TEI | Gutenberg #20732; PerseusDL `phi0472.phi001.perseus-eng4.xml` (117 divs) | PG "Public domain in the USA"; TEI header CC BY-SA 4.0 | use first |
| Burton (verse) | 1894 | Catullus | clean; poem-aligned TEI | same Gutenberg; `phi0472.phi001.perseus-eng3.xml` (118 divs, 2,360 lines) | same | use (verse, not literal) |
| Cornish (prose) | 1904 (CUP) | Catullus | clean transcription + scan | en.wikisource `The_poems_of_Gaius_Valerius_Catullus_(Cornish)`; IA `poemsofcaiusvale00catuuoft` | "NOT_IN_COPYRIGHT"; wikisource CC BY-SA | use |
| Cornish, Postgate, Mackail (prose) | Loeb 1913, scan of 1918 printing | Catullus, Tibullus, Pervigilium | scan (djvu OCR) | IA `catullustibullus00catu` | no rights field: unverified; PD-US by date | use after OCR |
| Kelly (literal prose) | 1854 (Bohn) | Catullus, Tibullus, Pervigilium | scan | IA `eroticapoemsofca00catu` | LoC "unaware of any copyright restrictions" | use after OCR |
| Lamb; Martin (verse) | 1821; 1861 | Catullus | scans | IA `poemscaiusvaler01catugoog`; `poemscatu00catuuoft` | "NOT_IN_COPYRIGHT" | low priority |
| Ellis (original metres) | 1871 | Catullus | clean | Gutenberg #18867 | "Public domain in the USA" | use (metre side, not gloss) |
| Smart rev. Buckley (literal prose) | 1756 / 1863 | all Horace | clean; TEI for Satires and Ars only | Gutenberg #14020; PerseusDL `phi0893.phi004/phi006 perseus-eng2.xml` | PG "Public domain in the USA" | use first for Horace |
| Conington (verse) | 1863; 1870 | Odes + CS; Sat., Ep., Ars | clean; poem-aligned TEI for the Odes | Gutenberg #5432, #5419; PerseusDL `phi0893.phi001.perseus-eng2.xml` (2,955 lines) | PG "Public domain in the USA"; repo CC BY-SA 4.0 | use (verse) |
| Bennett (prose) | Loeb 1914 | Odes, Epodes | no free scan of 1914/1927; 1968 reprint only | IA `odesandepodes01horagoog` | "NOT_IN_COPYRIGHT" on the reprint; unverified for 1914 | record_only |
| Wickham (prose) | 1903 | all Horace | scan | IA `horaceforenglish00horaiala` | "NOT_IN_COPYRIGHT" | use after OCR (best prose Odes after Smart) |
| Ker (prose); Bohn (prose) | Loeb 1919-20; 1860 / 1865 | Martial | scans | IA `martialepigrams01martiala`, `02martiala`; `epigramsofmarti00mart` | "NOT_IN_COPYRIGHT"; LoC "unaware of any copyright restrictions" | use after OCR; Ker renders obscene epigrams in Italian |
| Slater (prose); Mozley (prose) | 1908; Loeb 1928 | Silvae | scans | IA `silvaetranslated00statuoft`; `statiusstat01statuoft` | "NOT_IN_COPYRIGHT"; "Permission Granted to Digitize Item" (PD-US since 2024) | use after OCR |
| Miller (verse; prose) | 1907; Loeb 1917 | Seneca tragedies | scans | IA `tragediesseneca00senegoog`; `tragedieswitheng01seneuoft` | "NOT_IN_COPYRIGHT" | use after OCR |
| Evelyn-White (prose) | Loeb 1919-21 | Ausonius | scans | IA `ausonius00auso`; `ausoniuswithengl02ausouoft` | "NOT_IN_COPYRIGHT" | use after OCR |
| Mahoney | 2000 | Sulpicia | TEI | PerseusDL `phi0660.phi003.perseus-eng2.xml` | repo CC BY-SA 4.0 | use |
| Kline | 2001-05 | Catullus; Horace | html | poetryintranslation.com | "for any non-commercial purpose. Conditions and Exceptions apply." | record_only; owner decision |

Poem-aligned TEI, no OCR or alignment work: Smithers 1894, Burton 1894, Conington Odes, Smart Satires and Ars, Mahoney. Clean
text needing poem alignment: Smart Odes, Ellis, Conington Sat./Ep./Ars, en.wikisource Cornish. The rest are scans; each has a `_djvu.txt`, so OCR exists but line boundaries must be rebuilt.

## 6. Lemmatisers, morphology, dictionaries, lemma gold

| Resource | What | Licence (as quoted in rows-c) | Accuracy claimed | Verdict |
|---|---|---|---|---|
| **LatinCy `la_core_web_sm/md/lg` 3.9.8** (Burns); `trf` (1.7 GB) | spaCy: enclitic splitter, tagger, morphologizer, edit-tree + lookup lemmatiser | "license: mit" (weights); trained on six UD treebanks + LASLA | LEMMA_ACC 94.98 / 95.19 / 95.26 (README); sm meta.json 0.9378; trf 95.48 | use, lookup component off; trf evaluate_only |
| `la-latincy-lookups` 1.0.0 | lemma_lookup 909,669 entries from Kaikki + UD; a hard install dependency | "CC BY-NC-SA 4.0 ... This package is a dataset" | - | no: disable `lookup_lemmatizer`; never copy the table |
| `latincy-preprocess` 0.5.1 | u/v normalisation, macron stripping | MIT | - | use (linter normalisation) |
| `la_stanza_latincy`; `la_udpipe_latincy` | Burns retrains on UD + LASLA | "license: mit"; NC training data | lemma 97.87; F1 92.99 | evaluate_only |
| Stanza `stanza-la` | per-treebank models; default ITTB | "license: apache-2.0"; trained on NC treebanks | lemmas ITTB 99.09 ... Perseus 83.57 | evaluate_only |
| UDPipe 2 Latin (UD 2.17); LatinPipe (ÚFAL) | per-treebank models; PhilBerta joint tagger/lemmatiser/parser | "distributed under the CC BY-NC-SA licence"; LatinPipe code MPL-2.0, model "CC BY-NC-SA 4.0" | lemmas perseus 87.99; EvaLatin 2024 parsing winner, no lemma figure | no; evaluate_only (comparison systems) |
| CLTK backoff lemmatiser (cltk<=1.x) | NLTK backoff chain; removed in CLTK 2.x | MIT code; data "CC BY-SA 3.0" (AGLDT); Collatinus part GPL | none ("BETA") | evaluate_only |
| Collatinus 12 | lemmatiser + analyser from a lemma lexicon | "GNU GPL v3" (data files GPL-2.0-or-later) | none | evaluate_only, separate process |
| Whitaker's WORDS | Ada analyser; DICTLINE 39,335 entries; INFLECTS 3,228 rules | "Permission is hereby freely given for any and all use of program and data" | none | use (L1 fallback) |
| Morpheus Latin stemlib | stems + endings; analyses carry Lewis & Short lemma keys | "Creative Commons Attribution-ShareAlike 3.0 United States License" | none | use (L1 parser; new container) |
| LatMor (Springmann, Schmid) | SFST morphology with vowel length | "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License. Before using LatMor for commercial purposes, you must purchase a license" | none | no |
| LEMLAT 3.0 | analyser with MySQL lexical db; types, not tokens | "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License" | none | evaluate_only |
| Latin BERT; LaBerta / PhilBerta | encoders only | MIT; "apache-2.0" | POS figures only | evaluate_only |
| pie-extended `lasla` | PIE tagger-lemmatiser trained on LASLA | code "Mozilla Public License Version 2.0"; model unverified | none | ask_author (Thibault Clérice) |
| UD_Latin-ITTB / Perseus / PROIEL | treebanks (medieval prose; classical mixed, no Catullus/Horace; prose) | CC BY-NC-SA 3.0 / 2.5 / 4.0 (each LICENSE.txt; PROIEL's README says 3.0) | - | evaluate_only |
| UD_Latin-LLCT; UD_Latin-CIRCSE | charters; Seneca tragedies + Tacitus with LASLA-derived lemmas | "Creative Commons License Attribution-ShareAlike 4.0 International" | - | use (CIRCSE: the only BY-SA verse treebank) |
| UD_Latin-UDante | Dante's Latin, some verse | LICENSE.txt CC BY-SA 4.0 vs README CC BY-NC-SA 3.0 | - | ask_author |
| Perseus AGLDT Latin 2.1 | source of UD_Latin-Perseus | "Creative Commons Attribution-ShareAlike 3.0 United States License" (vs NC 2.5 in UD) | - | evaluate_only |
| **LASLA** (CIRCSE/LASLA v1.0.1) | hand-verified lemma, POS, morphology; all Catullus (13,129 words, 3,161 lemma strings) and all Horace (45,007 words); LiLa ids | "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License" | "full manual verification" | evaluate_only |
| EvaLatin 2020 (LT4HALA) | Horace Odes gold, 13,290 tokens, lemma + UPOS | "Creative Commons Attribution-NonCommercial-ShareAlike (CC BY-NC-SA) 4.0 International" (2024 parsing set: CC BY-SA 4.0) | - | evaluate_only |
| LiLa Lemma Bank | 168,789 lemmas; SPARQL endpoint; 11 MB SQL dump | "Creative Commons Attribution-ShareAlike 4.0 International License" | - | use (lemma id space) |
| Lewis & Short; Lewis, Elementary Latin Dictionary (PerseusDL/lexica) | TEI 77.4 MB, full senses, macronised headwords; TEI 14.5 MB, short glosses | "CC BY-SA 4.0 ... You credit Perseus"; "Creative Commons Attribution-ShareAlike 4.0 International License" | - | use (full glosses; pop-up glosses) |
| Latin WordNet 2.0 (Exeter); DCC Latin Core Vocabulary | 74,795 lemmas with prosody, principal parts, synsets; about 1,000 headwords with definitions and frequency rank | "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)"; "Creative Commons Attribution-ShareAlike 3.0 Unported License" | - | use (synonyms, LiLa alignment; common-word glosses, frequency prior) |
| Wiktionary Latin (Kaikki) | inflection tables, principal parts, headwords; 1.2 GB JSONL | "both CC-BY-SA and GFDL" | - | use (forms, not glosses) |
| Tesserae | 744 `.tess` texts incl. Catullus and Horace; `la.lexicon.csv` 1,220,933 form-lemma rows | no licence file (unverified) | - | ask_author |
| Gaffiot 2016; HF Latin datasets; LatinISE; Logeion | - | unverified, conflicting with sources, or none | - | no / ask |

**Evaluation order** (PRD §5.2: 300 hand-checked Catullus tokens, winner's held-out score to `docs/latin/lemma-index.md`):

1. LatinCy `la_core_web_lg` 3.9.8, run twice: as shipped, and with `lookup_lemmatizer` disabled. If the second run holds,
   the NC table never touches Melos data. Control for its tokenizer: only `-que` is split, macrons are stripped, `norm_` is
   u/i-folded while lemma spellings mix LASLA u-only and UD v; the index must fold u/v and i/j before matching headwords.
2. `la_stanza_latincy` (97.87 claimed) and Stanza `stanza-la` (Perseus 83.57), one harness for both; also the candidates for the rescoring role OdyCy plays in the Greek index.
3. Morpheus Latin as the parser in the Greek sense (analyses with Lewis & Short keys, as `build_lemma_index.py` expects), from a new container built on `stemlib/Latin`; Whitaker's WORDS as the fallback analyser.
4. Not for production: UDPipe, LatinPipe, LatMor, LEMLAT (NC); Collatinus only as a separate GPL process; CLTK backoff is legacy.

**L1 ("does this form exist")** is not the lemmatiser's job (PRD §2, §5.2): a statistical lemmatiser returns a lemma for any
string, so it cannot say no. L1 is answered by closed-vocabulary analysers (Morpheus Latin, CC BY-SA 3.0 US; Whitaker, permissive;
Collatinus, GPL as a separate process) plus the attested-form inventory. The statistical lemmatiser serves context disambiguation, the L4 "attested in Catullus/Horace" linter and the concordance.

**LASLA.** CIRCSE/LASLA v1.0.1 on GitHub holds the Liège corpus as CoNLL-UP, every token linked to a LiLa lemma id: all of
Catullus and all of Horace. It is the held-out gold for every candidate except LatinCy and `la_stanza_latincy`, which were
trained on it. Orthography is u-only and j-less (`nouum`, `iuuat`), no punctuation; enclitic compounds are split under a
multiword token. Licence CC BY-NC-SA 4.0: evaluation use is one question, storing its lemmas in the product index another
(§8). EvaLatin 2020's Horace Odes gold is the same annotation as a test set; UD_Latin-CIRCSE (CC BY-SA 4.0) is a BY-SA
sample of the same conventions for Seneca.

**Glosses, legally:** Lewis & Short (full senses) and the Elementary Lewis (short pop-ups), both CC BY-SA 4.0 with the
Perseus credit line; DCC core vocabulary (CC BY-SA 3.0) for the commonest words; Latin WordNet 2.0 (CC BY-SA 4.0) for
synonyms. Wiktionary for inflection, not glosses. Not Gaffiot (NC-ND or unverified), not Logeion (off limits).

## 7. Licence summary

| Resource | Code | Data | Training data | Derived tables redistributable? | Action |
|---|---|---|---|---|---|
| Hypotactic Latin | - | CC BY 4.0 (about.html) | - | yes, with attribution "David Chamberlain, hypotactic.com" | use (gold only; never in the lexicon) |
| Winge `macrons.txt` | GPL-3.0 | none stated; Morpheus-derived | - | unknown | ask author (johan.winge@gmail.com); evaluate_only meanwhile |
| CLTK `macrons.txt` (2016) | MIT | MIT claimed; Morpheus-derived | - | only with Perseus attribution and share-alike | record only (superseded) |
| Collatinus lexicon | GPL-3.0 | GPL-2.0-or-later (file headers) | - | yes under GPL-compatible terms, attributed, separate from app code | use |
| Morpheus Latin stemlib | - | CC BY-SA 3.0 US | - | yes, share-alike, "offer Perseus any modifications" | use |
| Wiktionary (Kaikki) | - | CC BY-SA + GFDL | - | yes, share-alike | use |
| Lewis & Short; Elementary Lewis | - | CC BY-SA 4.0 + Perseus credit line | - | yes, share-alike | use |
| Latin WordNet 2.0; LiLa Lemma Bank; DCC core vocabulary | - | CC BY-SA 4.0; 4.0; 3.0 | - | yes | use |
| Whitaker's WORDS | permissive notice | same | - | yes | use |
| CLTK `prosody.lat` 1.5.x; latin_scansion | MIT; Apache-2.0 | - | - | n/a | evaluate_only |
| LatinCy sm/md/lg, trf | MIT | - | UD (3 NC treebanks) + LASLA (NC) | n/a (weights, not tables) | use with lookup off; owner decision on NC-trained models |
| `la-latincy-lookups` | - | CC BY-NC-SA 4.0 | Kaikki + UD | no | do not copy; disable component |
| `la_stanza_latincy`; Stanza `stanza-la` | MIT; Apache-2.0 | - | NC treebanks (+ LASLA) | n/a | evaluate_only; same owner decision |
| UDPipe 2; LatinPipe model; LatMor; LEMLAT 3 | MPL-2.0 (LatinPipe) | CC BY-NC-SA | NC | no | comparison systems only / no |
| LASLA v1.0.1; EvaLatin 2020 | - | CC BY-NC-SA 4.0 | - | no (NC) | evaluate_only; owner decision for recorded lemmas; request to LASLA/CIRCSE |
| UD_Latin-ITTB / Perseus / PROIEL | - | CC BY-NC-SA 3.0 / 2.5 / 4.0 | - | no | evaluate_only |
| UD_Latin-LLCT / CIRCSE; UD_Latin-UDante | - | CC BY-SA 4.0; UDante conflict: BY-SA 4.0 vs BY-NC-SA 3.0 | - | yes; unclear | use; ask author (UDante) |
| pie-extended `lasla` model; Tesserae; Anceps | MPL-2.0; unverified; none (unverified) | unverified (LASLA-trained); unverified; MQDQ-derived | NC; -; - | unclear / unclear / no | ask author (Thibault Clérice for pie-extended); nothing needed from Anceps |
| Pedecerto / MQDQ | - | all rights reserved; NC; no mirroring | - | no | not used; ask mqdq-galaxy@unive.it only if dactylic gold is ever wanted |
| Gaffiot 2016 | - | CC BY-NC-ND 4.0 (Wayback) / unverified | - | no (ND) | no; lemmas only via Collatinus |
| PerseusDL canonical-latinLit (texts, TEI translations) | - | CC BY-SA 4.0 | - | yes | use |
| Latin Wikisource; en.wikisource | - | CC BY-SA | - | yes | use (edition recorded per page) |
| Project Gutenberg texts; Internet Archive scans | - | "Public domain in the USA"; per item: NOT_IN_COPYRIGHT / PD Mark / LoC / none | - | yes (US); yes where stated, unverified where no field | use; use per item and mark unverified |
| Kline; Catullus Online | - | NC only, "Conditions and Exceptions apply"; no terms stated | - | no; unclear | owner decision (Kline); ask kiss [apud] ub.edu; both record only |
| PHI; Latin Library; Logeion; Perseus Hopper | - | click-through personal use; none; none; robots-blocked | - | no | not sources |

## 8. Open decisions for the owner

1. NC lemma gold (LASLA, EvaLatin 2020): allow evaluation-only use now, and write to LASLA/CIRCSE about recorded lemmas?
2. LatinCy and the Stanza models: run with the NC lookup table disabled (or ask Burns), and may models trained on NC treebanks run server-side for greeklyric.com?
3. Winge's `macrons.txt`: send the one email (johan.winge@gmail.com) asking for CC BY-SA redistribution of a derived table?
4. Pedecerto: drop entirely (recommended; dactylic only) or write to mqdq-galaxy@unive.it for a Catullus 62-116 check?
5. Kline's translations: non-commercial only; leave out (recommended; PD prose exists for every poet)?
6. Collatinus-derived quantity table: ship as a separate GPL data file with attribution, or keep it build-side only?
7. Catullus Online apparatus: ask the editor (kiss [apud] ub.edu), or leave out?
8. Martial: accept the Perseus file (CC BY-SA 4.0) whose underlying 1976 Teubner revision is in copyright (record, not gate)?
9. Large fetches: the Kaikki Latin dump (1.2 GB), Lewis & Short XML (77 MB), Winge's table, the Collatinus data, the Perseus Catullus TEI and the LASLA files were fetched on this box on 2026-10-10 (11 GB free afterwards; `data/raw/latin/fetch-log.jsonl`); the 29 MB Hypotactic zip was not (the per-work pages were enough).
10. Full Hypotactic ingest for an out-of-author held-out set: confirm whether its menu has Martial or Statius Phalaecians before relying on PRD §4.4's split.
11. Bennett 1914: keep searching (HathiTrust was unreachable) or settle on Smart + Wickham for prose Horace?

## 9. Appendix: rows used

One line per row: name | licence_url | sha256 (first 12 hex) | fetched_at (all 2026-10-11 UTC; time shown) | licence_verified. "-" = none recorded.

### Pass A (rows-a.jsonl, 22)

- CLTK cltk.prosody.lat scanners | raw.githubusercontent.com/cltk/cltk/v1.5.0/LICENSE | 2dbcd9be0771 | 02:23:54Z | True
- CLTK macronizer + lat_models_cltk macrons.txt | raw.githubusercontent.com/cltk/lat_models_cltk/master/LICENSE | 4125babcce0c | 02:25:25Z | True
- Johan Winge latin-macronizer macrons.txt | raw.githubusercontent.com/Alatius/latin-macronizer/master/LICENSE | d62f065830aa | 02:15:08Z | True
- Perseus Morpheus Latin stemlib | raw.githubusercontent.com/PerseusDL/morpheus/master/README.md | 5c5342e0a67e | 02:26:31Z | True
- Collatinus lexicon (lemmes.la, lem_ext.la, modeles.la, irregs.la) | raw.githubusercontent.com/biblissima/collatinus/master/bin/data/lemmes.la | 0b926602f943 | 02:17:58Z | True
- Hypotactic Latin (hypotactic.com/latin) | hypotactic.com/latin/about.html | f7bcb3f2271d | 02:17:52Z | True
- Pedecerto / Musisque Deoque scansions | www.pedecerto.eu/pagine/autori | 7d5fad217651 | 02:18:04Z | True
- Anceps (dargones/anceps) | - | - | 02:16:25Z | False
- latin_scansion (CUNY-CL) | raw.githubusercontent.com/CUNY-CL/latin_scansion/master/LICENSE.txt | 217366db9396 | 02:22:04Z | True
- Scandroid (jproft mirror) | raw.githubusercontent.com/jproft/Scandroid/master/README.md | 8d11de6efc02 | 02:20:03Z | True
- Latin_scansion_with_neural_networks (Ycreak; Nolden 2022) | - | - | 02:18:05Z | False
- Signatrix | - | - | 02:23:55Z | False
- latin-scanner (npm) and latin-scan.com | registry.npmjs.org/latin-scanner | bc98e6604e03 | 02:16:27Z | True
- LASY (sunwoo-j/LASY) | raw.githubusercontent.com/sunwoo-j/LASY/main/LICENSE | 157deebf647a | 02:27:27Z | True
- Other GitHub scanners found by search (12 repos) | - | - | 02:15:14Z | False
- Wiktionary Latin via Kaikki | kaikki.org/dictionary/ | f0ec65c992c2 | 02:15:12Z | True
- Lewis & Short via PerseusDL/lexica | raw.githubusercontent.com/PerseusDL/lexica/master/CTS_XML_TEI/perseus/pdllex/lat/ls/README.md | 5ce62020d4cb | 02:18:00Z | True
- Gaffiot 2016 (Gréco) | web.archive.org/web/2023id_/http://gerardgreco.free.fr/spip.php?article47 | 1830d1e946f7 | 02:23:58Z | True
- Whitaker's Words | raw.githubusercontent.com/mk270/whitakers-words/master/README.md | 7383c8ef30f3 | 02:13:24Z | True
- Logeion | - | - | 02:13:29Z | False
- KaanGoker/dactylic-hexameter-latin-poetry-corpus (HF) | huggingface.co/datasets/KaanGoker/dactylic-hexameter-latin-poetry-corpus/raw/main/README.md | 543727435fce | 02:23:56Z | True
- Macronised Latin text corpora on GitHub (4 repos) | - | - | 02:16:34Z | False

### Pass B (rows-b.jsonl, 64)

- PerseusDL Catullus Carmina (phi0472.phi001.perseus-lat2.xml) | raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/data/phi0472/phi001/phi0472.phi001.perseus-lat2.xml | 2a52b461b111 | 02:17:13Z | True
- PerseusDL Horace Carmina (phi0893.phi001) | raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/license.md | ccf0e8ce1837 | 02:21:25Z | True
- PerseusDL Horace Carmen Saeculare (phi0893.phi002) | same license.md | ccf0e8ce1837 | 02:21:26Z | True
- PerseusDL Horace Epodes (phi0893.phi003) | same license.md | ccf0e8ce1837 | 02:21:26Z | True
- PerseusDL Horace Satires / Epistles / Ars (phi0893.phi004-006) | same license.md | ccf0e8ce1837 | 02:21:26Z | True
- PerseusDL Martial Epigrammata (phi1294.phi002) | same license.md | ccf0e8ce1837 | 02:21:25Z | True
- PerseusDL Statius Silvae (phi1020.phi002) | same license.md | ccf0e8ce1837 | 02:21:26Z | True
- PerseusDL Tibullus Elegiae (phi0660.phi001) | same license.md | ccf0e8ce1837 | 02:21:27Z | True
- PerseusDL Sulpicia (phi0660.phi003 lat2 / eng2) | same license.md | ccf0e8ce1837 | 02:21:27Z | True
- PerseusDL Seneca Tragoediae (phi1017.phi001-phi010) | same license.md | ccf0e8ce1837 | 02:21:28Z | True
- PerseusDL Ausonius (stoa0045) | same license.md | ccf0e8ce1837 | 02:17:30Z | True
- Latin Wikisource: Carmina (Catullus, ed. Merrill) | la.wikisource.org/wiki/Liber_Catulli_(ed._Merrill) | 010d1be9f001 | 02:17:13Z | True
- Latin Wikisource: Carmina (Catullus, ed. Cornish) | la.wikisource.org/wiki/Liber_Catulli_(ed._Cornish) | a0d3f01f8156 | 02:17:13Z | True
- Latin Wikisource: Carmina (Horatius), Epodi, Carmen Saeculare | la.wikisource.org/wiki/Carmina_(Horatius) | 9ec3f62e4caa | 02:15:17Z | True
- Latin Wikisource: Epigrammata (Martialis) | la.wikisource.org/wiki/Epigrammata_(Martialis) | 00134bfff899 | 02:26:13Z | True
- Latin Wikisource: Silvae (Statius) | la.wikisource.org/wiki/Silvae | 8e4b9d48c863 | 02:26:13Z | True
- Latin Wikisource: Priapea | la.wikisource.org/wiki/Priapea | 9f6b983b8395 | 02:21:33Z | True
- Latin Wikisource: Pervigilium Veneris | la.wikisource.org/wiki/Pervigilium_Veneris | fd6609809f75 | 02:21:33Z | True
- Latin Wikisource: Carmina (Cinna) | la.wikisource.org/wiki/Carmina_(Cinna) | fe976db4e15c | 02:26:13Z | True
- Hypotactic: Latin scansion, Catullus (use-the-source page) | hypotactic.com/use-the-source/ | 3b67098e9176 | 02:24:16Z | True (page names no licence; CC BY 4.0 verified in pass A)
- Catullus Online (Kiss), poems | catullusonline.org/CatullusOnline/?dir=edited_pages&pageID=5 | d310e367164a | 02:19:00Z | True
- PHI Latin Texts | latin.packhum.org/ | c7c4874147aa | 02:15:18Z | True
- The Latin Library | www.thelatinlibrary.com/about.html | 33dc19489923 | 02:15:19Z | True
- Dickinson College Commentaries | dcc.dickinson.edu/terms-use | c7d6aa7c7041 | 02:19:01Z | True
- Musisque Deoque (MQDQ) | www.mqdq.it/ | 520fb0db694c | 02:15:24Z | True
- Perseus Hopper (Merrill commentary etc.) | www.perseus.tufts.edu/robots.txt | 802ee2856764 | 02:15:21Z | True
- Teubner Mueller 1892: Catulli Tibulli Propertii carmina (scans) | archive.org/metadata/catvllitibvllip00catugoog | 5eb0a6adc6b0 | 02:26:31Z | True
- Baehrens FPR 1886 (scans) | archive.org/metadata/bub_gb_qhE_ZFDini8C | 520594e097e3 | 02:22:51Z | True
- Morel FPL 1927 (scans) | archive.org/metadata/fragmentapoetaru00baeh | 3ecd000a298f | 02:22:48Z | False
- Gutenberg #20732 Burton / Smithers 1894 | www.gutenberg.org/cache/epub/20732/pg20732.txt | 5a0b450ec685 | 02:15:21Z | True
- PerseusDL Catullus, Smithers prose (perseus-eng4) | raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/data/phi0472/phi001/phi0472.phi001.perseus-eng4.xml | dac151949ace | 02:17:13Z | True
- PerseusDL Catullus, Burton verse (perseus-eng3) | .../phi0472.phi001.perseus-eng3.xml | 6b99889817fa | 02:17:13Z | True
- Cornish 1904 (CUP), scan + en.wikisource | archive.org/metadata/poemsofcaiusvale00catuuoft | b2d521b7885b | 02:26:15Z | True
- Cornish 1913 Loeb (1918 printing) | archive.org/metadata/catullustibullus00catu | 4cc27ada7b29 | 02:21:25Z | False
- Mackail 1913 Pervigilium (same item) | archive.org/metadata/catullustibullus00catu | 4cc27ada7b29 | 02:21:25Z | False
- Kelly 1854 (Bohn) | archive.org/metadata/eroticapoemsofca00catu | 5f3b2e7b8605 | 02:22:29Z | True
- Lamb 1821 | archive.org/metadata/poemscaiusvaler01catugoog | 7ec95c116b64 | 02:26:14Z | True
- Martin 1861 | archive.org/metadata/poemscatu00catuuoft | 375a2b19a822 | 02:22:30Z | True
- Ellis 1871 (Gutenberg #18867 + scan) | www.gutenberg.org/cache/epub/18867/pg18867.txt | f776fa5db951 | 02:29:43Z | True
- Gutenberg #14020 Smart / Buckley, Horace | www.gutenberg.org/cache/epub/14020/pg14020.txt | 7917f40af30d | 02:15:21Z | True
- Conington Odes + CS (Gutenberg #5432; PerseusDL eng2) | www.gutenberg.org/cache/epub/5432/pg5432.txt | b78f660001a2 | 02:29:43Z | True
- Conington Satires, Epistles, Ars (Gutenberg #5419) | www.gutenberg.org/ebooks/5419 | bfa4b5f6ac0a | 02:29:44Z | True
- Bennett 1914 Loeb (1968 reprint item) | archive.org/metadata/odesandepodes01horagoog | f38261c5f678 | 02:22:55Z | True
- Wickham 1903 Horace for English Readers | archive.org/metadata/horaceforenglish00horaiala | bd0d373d3ea0 | 02:26:15Z | True
- Ker 1919-20 Loeb Martial | archive.org/metadata/martialepigrams01martiala | 57c3de86d89e | 02:22:03Z | True
- Bohn 1860/1865 Martial | archive.org/metadata/epigramsofmarti00mart | b05b94768465 | 02:22:09Z | True
- Slater 1908 Silvae | archive.org/metadata/silvaetranslated00statuoft | e4aa8633aa04 | 02:22:16Z | True
- Mozley 1928 Loeb Statius I | archive.org/metadata/statiusstat01statuoft | 520750967db6 | 02:22:18Z | True
- Miller 1907 / 1917 Seneca | archive.org/metadata/tragedieswitheng01seneuoft | db02a8508872 | 02:29:43Z | True
- Evelyn-White 1919-21 Ausonius | archive.org/metadata/ausonius00auso | fe63244494e9 | 02:26:44Z | True
- Mahoney 2000 Sulpicia (PerseusDL eng2) | same license.md | ccf0e8ce1837 | 02:21:27Z | True
- A. S. Kline, Poetry in Translation | www.poetryintranslation.com/PITBR/Latin/Catullus.php | 1a4c4d48981e | 02:15:24Z | True
- Merrill 1893 commentary (scan) | archive.org/metadata/catulluseditedby00catuuoft | 7fea1bdccf88 | 02:22:40Z | True
- Ellis 1889 commentary (scans) | archive.org/metadata/commentaryoncatu00elliuoft | 45aae026e003 | 02:22:34Z | True
- Fordyce 1961 | - | - | - | False (in copyright, not fetched)
- Wickham commentary 1881 / 1891 / 1912 (scans) | archive.org/metadata/odescarmensecula00horauoft | 5d4aeb24fbc5 | 02:29:46Z | True
- Page 1896 Horace Opera (scan) | archive.org/metadata/operawithnotesby00horauoft | 4fafc7511b5a | 02:29:44Z | True
- Nisbet and Hubbard / Nisbet and Rudd | - | - | - | False (in copyright, not fetched)
- Catullus Online apparatus (Kiss) | catullusonline.org/CatullusOnline/?dir=edited_pages&pageID=9 | 9548700c6ef2 | 02:19:00Z | True
- PerseusDL canonical-latinLit (repository) | raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/license.md | ccf0e8ce1837 | 02:17:12Z | True
- Latin Wikisource (site) | la.wikisource.org/wiki/Scriptor:Gaius_Valerius_Catullus | 0aafb9218782 | 02:15:17Z | True
- Project Gutenberg (site) | www.gutenberg.org/ebooks/14020 | 31ca9e206eaa | 02:15:21Z | True
- Internet Archive (scans used) | - (per item) | - | - | False (per-item rights above)
- HathiTrust | - | - | - | False (HTTP 403)

### Pass C (rows-c.jsonl, 38)

- LatinCy la_core_web_sm/md/lg 3.9.8 | huggingface.co/latincy/la_core_web_lg/raw/main/README.md | 710fcff9da7b | 02:14:14Z | True
- LatinCy la_core_web_trf 3.9.8 | huggingface.co/latincy/la_core_web_trf/raw/main/README.md | 3d3a327c20c3 | 02:14:14Z | True
- la-latincy-lookups 1.0.0 | raw.githubusercontent.com/latincy/la-latincy-lookups/main/README.md | b923548d561a | 02:23:20Z | True
- latincy-preprocess 0.5.1 | raw.githubusercontent.com/latincy/latincy-preprocess/main/LICENSE | 85c67b90da79 | 02:23:20Z | True
- CLTK Latin backoff lemmatiser | raw.githubusercontent.com/cltk/lat_models_cltk/master/lemmata/backoff/README.md | 7e851feae0ad | 02:26:09Z | True
- Collatinus 12 | raw.githubusercontent.com/biblissima/collatinus/master/README.md | 647814cc71c3 | 02:15:36Z | True
- Whitaker's WORDS | raw.githubusercontent.com/mk270/whitakers-words/master/README.md | 7383c8ef30f3 | 02:15:36Z | True
- Morpheus Latin stem library | raw.githubusercontent.com/PerseusDL/morpheus/master/README.md | 5c5342e0a67e | 02:15:37Z | True
- LatMor | www.cis.uni-muenchen.de/~schmid/tools/LatMor/ | 087ac7e338e0 | 02:15:38Z | True
- LEMLAT 3.0 | raw.githubusercontent.com/CIRCSE/LEMLAT3/master/README.md | 7052954755a1 | 02:15:38Z | True
- LatinPipe | lindat.mff.cuni.cz/repository/xmlui/handle/11234/1-5671 | 72228019e45c | 02:23:20Z | True
- Stanza Latin models (stanza-la) | huggingface.co/stanfordnlp/stanza-la/raw/main/README.md | 6f3edd28c677 | 02:15:38Z | True
- UDPipe 2 Latin models (UD 2.17) | ufal.mff.cuni.cz/udpipe/2/models | 83b166cd1cb7 | 02:15:38Z | True
- LatinCy retrains (la_udpipe_latincy, la_stanza_latincy) | huggingface.co/latincy/la_stanza_latincy/raw/main/README.md | abe6a81fdb21 | 02:23:20Z | True
- Latin BERT | raw.githubusercontent.com/dbamman/latin-bert/master/LICENSE | 632744030a58 | 02:15:39Z | True
- LaBerta / PhilBerta | huggingface.co/bowphs/LaBerta/raw/main/README.md | b9fdec538986 | 02:28:53Z | True
- pie-extended lasla model | raw.githubusercontent.com/hipster-philology/nlp-pie-taggers/master/LICENSE | 1f256ecad192 | 02:31:12Z | True (code only; model unverified)
- UD_Latin-ITTB | raw.githubusercontent.com/UniversalDependencies/UD_Latin-ITTB/master/LICENSE.txt | 3e07ac7ee7b0 | 02:14:14Z | True
- UD_Latin-Perseus | .../UD_Latin-Perseus/master/LICENSE.txt | 1e610c18edec | 02:14:15Z | True
- UD_Latin-PROIEL | .../UD_Latin-PROIEL/master/LICENSE.txt | 33af57b85f3e | 02:14:15Z | True
- UD_Latin-LLCT | .../UD_Latin-LLCT/master/LICENSE.txt | 899b1804a12e | 02:14:15Z | True
- UD_Latin-UDante | .../UD_Latin-UDante/master/LICENSE.txt | 899b1804a12e | 02:14:15Z | True
- UD_Latin-CIRCSE | .../UD_Latin-CIRCSE/master/LICENSE.txt | 899b1804a12e | 02:14:15Z | True
- Perseus AGLDT Latin v2.1 | raw.githubusercontent.com/PerseusDL/treebank_data/master/README.md | e394f5978d66 | 02:14:16Z | True
- LASLA corpus (CIRCSE/LASLA v1.0.1) | raw.githubusercontent.com/CIRCSE/LASLA/master/README.md | 047b2b3228d1 | 02:17:11Z | True
- EvaLatin 2020/2022/2024 (CIRCSE/LT4HALA) | github.com/CIRCSE/LT4HALA/blob/master/2020/data_and_doc/LICENSE.txt (commit 2ac2af22127c) | 3a2feffbb90c | 02:28:52Z | True
- Tesserae | - | - | 02:17:11Z | False
- Perseus-derived and other Latin corpora on Hugging Face | - | - | 02:17:14Z | False
- LatinISE | - | - | 02:26:11Z | False
- LiLa Lemma Bank | github.com/CIRCSE/LiLa_Lemma-Bank/blob/master/README.md (commit 1716c7961f9f) | 9acee46c3a7d | 02:28:52Z | True
- Lewis & Short (PerseusDL/lexica) | raw.githubusercontent.com/PerseusDL/lexica/master/CTS_XML_TEI/perseus/pdllex/lat/ls/README.md | 5ce62020d4cb | 02:23:22Z | True
- Lewis, Elementary Latin Dictionary | raw.githubusercontent.com/PerseusDL/lexica/master/README.md | f75ece374961 | 02:17:12Z | True
- Gaffiot 2016 | - | - | 02:17:13Z | False
- Wiktionary Latin via Kaikki | kaikki.org/dictionary/ | f0ec65c992c2 | 02:17:13Z | True
- Latin WordNet 2.0 | raw.githubusercontent.com/ThomasK81/latinwordnet2/master/README.md | 7dd899382fcb | 02:23:19Z | True
- DCC Latin Core Vocabulary | dcc.dickinson.edu/vocab/core-vocabulary | 443e6d439253 | 02:26:14Z | True
- Logeion | - | - | 02:19:44Z | False
- Latin macronizer (Alatius) | raw.githubusercontent.com/Alatius/latin-macronizer/master/LICENSE | d62f065830aa | 02:17:14Z | True
