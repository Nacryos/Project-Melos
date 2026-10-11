# Open sources for Latin verse, survey pass B (2026-10-10): texts, translations, commentaries

Status: survey only; nothing ingested. Rows: `rows-b.jsonl` in this folder (64 rows, 57 with a licence or terms
statement verified verbatim against the fetched bytes; the rest carry an empty quote and say why). Method as in
`docs/open-sources-survey-2026-10-09.md`: User-Agent `Melos/1.0 (+https://greeklyric.com)` on every request, robots.txt
read and obeyed per host, no logins, paywalls or CAPTCHAs, no pirate uploads relied on (Digital Library of India copies
are listed but not used), nothing over 50 MB downloaded (the Hypotactic data zip, 29 MB, was only HEAD-checked). Every
fetched page is saved under the session scratchpad `survey-b/raw/` with its sha256 in `survey-b/fetchlog.jsonl`
(274 fetches). Policy per `docs/decisions.md`: licences are recorded, not a gate; `reuse_verdict` says `no` only
for sources whose own terms forbid copying or capture (PHI, MQDQ) or that are in copyright and were not fetched.

### Texts

| Resource | Edition / year | Format | Licence (short) | Coverage | Verdict |
|---|---|---|---|---|---|
| PerseusDL canonical-latinLit: Catullus, Carmina (phi0472.phi001.perseus-lat2.xml) | E. T. Merrill, Catullus (Boston: Ginn and Company, 1893), per the TEI sourceDesc | tei | CC BY-SA 4.0 (file header) | 116 poems (div subtype=poem), 2,318 <l> lines; cRefPattern poem/line | use: edition and file licence both stated in the header; repo licence CC BY-SA 4.0 |
| PerseusDL canonical-latinLit: Horace, Carmina (phi0893.phi001.perseus-lat2.xml) | Paul Shorey and Gordon J. Laing, Horace, Odes and Epodes (Chicago: Benj. H. Sanborn, 1919), per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md) | Odes I-IV, 3,034 <l> lines | use: repo licence CC BY-SA 4.0; header has no <availability> element |
| PerseusDL canonical-latinLit: Horace, Carmen Saeculare (phi0893.phi002.perseus-lat2.xml) | Shorey and Laing 1919 (as above) | tei | CC BY-SA 4.0 (repo license.md) | Carmen Saeculare, 76 lines | use: repo licence |
| PerseusDL canonical-latinLit: Horace, Epodes (phi0893.phi003.perseus-lat2.xml) | Friedrich Vollmer, Q. Horati Flacci Carmina (Leipzig: Teubner, 1912); keyboarded for the Latin Library by Konrad Schroder, per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md) | Epodes 1-17, 625 lines | use: repo licence |
| PerseusDL canonical-latinLit: Horace, Satires / Epistles / Ars Poetica (phi0893.phi004-006 perseus-lat2) | Satires: Latin from C. Smart, The Works of Horace (Philadelphia: Whetham, 1836); Epistles: H. R. Fairclough, Loeb 1929; Ars Poetica: Smart 1836 (per the TEI sou | tei | CC BY-SA 4.0 (repo license.md) | Satires 2,116 lines; Epistles 1,492 lines; Ars Poetica 476 lines | use: repo licence (lower priority: hexameters) |
| PerseusDL canonical-latinLit: Martial, Epigrammata (phi1294.phi002.perseus-lat2.xml) | W. Heraeus, rev. J. Borovskij, M. Valerii Martialis Epigrammaton libri (Leipzig: Teubner, 1925 / 1976), per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md); edition 1976 in copyright | Epigrammata, 9,462 lines (959 KB) | use: file is CC BY-SA 4.0 in the repo; underlying edition (1976 revision) is in copyright, recorded not gating |
| PerseusDL canonical-latinLit: Statius, Silvae (phi1020.phi002.perseus-lat2.xml) | J. H. Mozley, Statius, vol. 1 (Loeb, London: Heinemann, 1928), per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md) | Silvae I-V, 3,901 lines (hendecasyllables at 1.6, 2.7, 4.3, 4.9); Thebaid phi001 (9,742 lines) and Achilleid phi003 (1,127) also present | use: repo licence; Mozley 1928 is PD in the US since 2024 |
| PerseusDL canonical-latinLit: Tibullus, Elegiae (phi0660.phi001.perseus-lat2.xml) | J. P. Postgate, Tibulli aliorumque carminum libri tres (OCT, Oxford 1915), from the Latin Library transcription by Konrad Schroder, per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md) | Books I-III, 1,933 lines | use: repo licence |
| PerseusDL canonical-latinLit: Sulpicia, Carmina Omnia + Six Poems (phi0660.phi003 perseus-lat2 / perseus-eng2) | Anne Mahoney, Sulpicia: Text, translation, and commentary (2000), electronic text, per the TEI sourceDesc | tei | CC BY-SA 4.0 (repo license.md) | Six poems, 40 lines Latin; English translation (eng2) 40 lines | use: repo licence; modern open text and translation |
| PerseusDL canonical-latinLit: Seneca, Tragoediae (phi1017.phi001-phi010 perseus-lat2) | R. Peiper and G. Richter, L. Annaei Senecae Tragoediae (Leipzig: Teubner, 1921), per the TEI sourceDesc of phi001 | tei | CC BY-SA 4.0 (repo license.md) | Ten plays: Hercules Furens (1,389 lines), Troades, Phoenissae, Medea, Phaedra, Oedipus, Agamemnon, Thyestes, Hercules Oetaeus, Octavia (one file each; only phi001 header fetched) | use: repo licence; choral lyrics inside |
| PerseusDL canonical-latinLit: Ausonius (stoa0045: De Bissula, Caesares) | not fetched (only __cts__.xml read) | tei | CC BY-SA 4.0 (repo license.md) | De Bissula (stoa001) and Caesares (stoa002) only | record_only: only two short works; headers not read |
| Latin Wikisource: Carmina (Catullus, ed. Merrill) | Page states: 'editio: Catullus, Cambridge, Massachusetts, Harvard University Press, 1893; Elmer Truesdell Merrill recensuit; fons: Google Books' (Merrill's 1893 | html | CC BY-SA (page footer) | Index to poems 1-116 (no 18-20, as in Merrill) as subpages '/Carmen I' etc.; subpages use <poem> with {{versus\|5}} line numbers and metre categories (e.g. Categoria:Hendecasyllabi); wikitext via ?act | use: CC BY-SA footer; same edition as the PerseusDL file, a second witness for diffing |
| Latin Wikisource: Carmina (Catullus, ed. Cornish) | Page states: 'editio: The poems of Gaius Valerius Catullus, Cambridge, Cambridge University Press, 1904; Franciscus Warre Cornish recensuit', from the djvu scan | html | CC BY-SA (page footer) | Index to poems 1-116 as subpages '/1', '/2', '/2a' ... | use: CC BY-SA footer; Cornish's Latin text (1904) |
| Latin Wikisource: Carmina (Horatius), Epodi, Carmen Saeculare | Carmina page states: 'editio: Horace, Odes and Epodes, Paul Shorey and Gordon J. Laing, Chicago, Benj. H. Sanborn & Co, 1919; fons: Perseus'. Epodi and Carmen_S | html | CC BY-SA (page footer) | Odes I-IV as subpages 'Carmina (Horatius)/Liber I/Carmen I' ...; Epodi 1-17 as subpages; Carmen Saeculare in one <poem> | use: CC BY-SA footer; Odes are a copy of the Perseus text (prefer PerseusDL TEI) |
| Latin Wikisource: Epigrammata (Martialis) | Page states 'editio: incognita fons: incognitus' | html | CC BY-SA (footer); edition unknown | Books I-XII as subpages; Xenia, Apophoreta and Liber spectaculorum as separate pages | record_only: edition unknown; PerseusDL Martial is better documented |
| Latin Wikisource: Silvae (Statius) | Page states 'editio: incognita fons: incognitus' | html | CC BY-SA (footer); edition unknown | Books I-V | record_only: edition unknown; PerseusDL Silvae (Mozley 1928) preferred |
| Latin Wikisource: Priapea | Page states 'editio: incognita fons: incognitus' | html | CC BY-SA (footer); edition unknown | Priapea 1-80 on one page (sections 1-19 numbered, then 20-29 etc.) | use: only open copy with a licence; edition unknown (record) |
| Latin Wikisource: Pervigilium Veneris | Page states 'editio: 1848 fons: librum vide' (edition of 1848, not named) | html | CC BY-SA (footer); 1848 edition | Complete poem on one page (93 lines) | use: licensed copy; 1848 text with old orthography (jam, nunquam); the Loeb 1913 Latin (Mackail) is the better text but scan only |
| Latin Wikisource: Carmina (Cinna) [Carminum fragmenta] | Page states 'editio: incognita'; wikitext gives Fons = http://www.thelatinlibrary.com/cinna.html | html | CC BY-SA (footer); edition unknown | Fragments 1-4, 6-7 ... (numbered as in FPL) | record_only: copied from the Latin Library, edition unknown; the Teubner Mueller scans give a sourced text |
| Hypotactic (David Chamberlain): Latin scansion, Catullus | edition not stated on the fetched pages | html | 'use the source code of the pages as data' (no licence named); CC BY 4.0 per Greek survey, unverified here | JS app shell (3,851 bytes); scansion is loaded by metre.js; data archive https://hypotactic.com/hypotactic_data_6_17_2025.zip (HEAD: 29,084,693 bytes, last-modified 17 Jun 2025) not downloaded | use: for alignment of scanned text (pass A covers format); licence name not on the fetched pages |
| Catullus Online (Daniel Kiss), poems with full repertory of conjectures | Kiss's own critical text; 'A full repertory of conjectures on Catullus is presented here in a critical apparatus alongside his poems' (About the repertory page) | html | No terms stated (only image copyright); modern apparatus | All poems on the home page (740,849 bytes, line-numbered 61.32 etc.); ?dir=poems&w_apparatus=1&showall=1 for the apparatus; testimonia; images of T, O, G, R; list of ~120 manuscripts; bibliography (43 | record_only: no terms or licence for the text or apparatus on any fetched page; the apparatus is a modern copyrighted scholarly work; ask the editor before reuse |
| Teubner: Catulli Tibulli Propertii carmina, accedunt Laevii Calvi Cinnae aliorum reliquiae (ed. L. Mueller), scans | Lucian Mueller, Teubner 1892 printing (also 1870: catvllitibvllip00priagoog, 1880 microform catvllitibvllipr01cat, 1885 catvllitibvllipr0000catu) | scan | archive.org possible-copyright-status NOT_IN_COPYRIGHT | Appendix of fragments of Laevius, Calvus, Cinna and others; djvu OCR text available | use: PD scan with OCR; the only open edition of the Catullan-circle fragments found with a sourced text |
| Baehrens, Fragmenta poetarum Romanorum (Teubner 1886), scans | E. Baehrens 1886 | scan | archive.org licenseurl: CC Public Domain Mark 1.0 | Complete FPR; Google scan with CC public-domain mark (also fragmentapoetaru00baehuoft, Toronto, no rights field; fragmentapoetar00baehgoog NOT_IN_COPYRIGHT) | use: PD scan |
| Morel, Fragmenta poetarum Latinorum epicorum et lyricorum (Teubner 1927), scans | W. Morel 1927 (revision of Baehrens) | scan | No rights field on item; PD-US by date (1927) | Complete FPL 1927; University of Illinois scan (no rights field); also fragmentapoetaru0000more (Trent / internetarchivebooks, no rights field) | use: PD in the US (published 1927); the item metadata carries no rights field, so unverified from the item; non-US rights may subsist |

### Translations

| Resource | Edition / year | Format | Licence (short) | Coverage | Verdict |
|---|---|---|---|---|---|
| Project Gutenberg #20732: The Carmina of Caius Valerius Catullus, tr. Burton (verse) and Smithers (prose), 1894 | Sir Richard F. Burton (verse) and Leonard C. Smithers (prose, introduction, notes), London 1894 | txt | PG licence; 'Public domain in the USA' | All poems, verse and literal prose side by side, with notes; clean e-text (430,463 bytes) | use: clean PD e-text; Smithers' prose is the literal translation the PRD names |
| PerseusDL canonical-latinLit: Catullus, Smithers prose (phi0472.phi001.perseus-eng4.xml) | Leonard C. Smithers, The Carmina of Gaius Valerius Catullus (London, 1894), per the TEI sourceDesc | tei | CC BY-SA 4.0 (file header); text PD 1894 | 117 poem divs of prose (545 <l>), aligned to the Latin by poem number | use: poem-aligned TEI of the PD prose, no OCR work needed |
| PerseusDL canonical-latinLit: Catullus, Burton verse (phi0472.phi001.perseus-eng3.xml) | Sir Richard Francis Burton 1894, per the TEI sourceDesc | tei | CC BY-SA 4.0 (file header); text PD 1894 | 118 divs, 2,360 lines of verse | use: poem-aligned verse (not literal) |
| Cornish 1904 (CUP): The poems of Gaius Valerius Catullus with an English translation, scan + en.wikisource transcription | F. W. Cornish, Cambridge University Press 1904 (the text later reused in the 1913 Loeb) | scan | archive.org NOT_IN_COPYRIGHT; en.wikisource CC BY-SA | Latin and prose English for all poems; en.wikisource 'The poems of Gaius Valerius Catullus (Cornish)' is a Proofread-Page transcription ('116 Latin Carmina (poems) and fragments, side by side with the | use: PD scan; the Wikisource transcription is the clean e-text route (CC BY-SA, PD content) |
| Cornish 1913 Loeb: Catullus, Tibullus and Pervigilium Veneris (Cornish, Postgate, Mackail), scan of the 1918 printing | F. W. Cornish (Catullus), J. P. Postgate (Tibullus), J. W. Mackail (Pervigilium Veneris), Loeb 1913; this scan is the 1918 printing (Toronto, PIMS) | scan | No rights field on item; PD-US by date | Complete volume: Latin with facing prose English; djvu OCR present | use: PD in the US by date (1913/1918); item metadata has no rights, licenseurl or possible-copyright-status field, so unverified from the item |
| Mackail 1913: Pervigilium Veneris, Latin and prose English (in the Cornish Loeb) | J. W. Mackail, in Loeb Catullus Tibullus Pervigilium Veneris 1913 | scan | No rights field on item; PD-US by date | Pervigilium Veneris text and translation at the end of the volume | use: PD-US by date; scan only |
| Kelly 1854 (Bohn): Erotica. The poems of Catullus and Tibullus, and the Vigil of Venus, literal prose | Walter K. Kelly, Bohn's Classical Library 1854 (literal prose plus Lamb's and Grainger's metrical versions) | scan | archive.org: LoC 'unaware of any copyright restrictions' | All poems; Library of Congress scan; also poemsofcatullu00catu (Toronto, no rights field) | use: PD scan; the oldest literal prose Catullus |
| Lamb 1821: The poems of Caius Valerius Catullus (verse) | George Lamb, London: J. Murray 1821 | scan | archive.org NOT_IN_COPYRIGHT | Verse translation, two volumes (vol. 1 item) | use: PD scan; verse, not literal |
| Martin 1861: The Poems of Catullus translated into English verse | Theodore Martin, London: Parker 1861 | scan | archive.org NOT_IN_COPYRIGHT | Verse translation | use: PD scan; verse |
| Ellis 1871: The Poems and Fragments of Catullus translated in the metres of the original (Gutenberg #18867 + scan) | Robinson Ellis, London: J. Murray 1871 | txt | PG licence; 'Public domain in the USA' | All poems and fragments in the original metres; clean e-text https://www.gutenberg.org/cache/epub/18867/pg18867.txt; scan poemsfragmentsof00catuiala (NOT_IN_COPYRIGHT) | use: clean PD e-text; metrical, useful for the composer's metre side rather than as a literal gloss |
| Project Gutenberg #14020: The Works of Horace translated literally into English prose by C. Smart, rev. Buckley | Christopher Smart 1756, 'A new edition revised by Theodore Alois Buckley' (Bohn / Harper 1863 family; Gutenberg text, 485,296 bytes) | txt | PG licence; 'Public domain in the USA' | Odes I-IV, Carmen Saeculare, Epodes, Satires, Epistles, Ars Poetica: complete literal prose | use: clean PD e-text; the literal prose Horace |
| Conington: The Odes and Carmen Saeculare of Horace (verse): Gutenberg #5432 and PerseusDL phi0893.phi001.perseus-eng2.xml | John Conington, 1863 (Gutenberg text; PerseusDL TEI from the 1882 Bell edition, 2,955 lines) | txt | PG licence; 'Public domain in the USA' | Odes I-IV and Carmen Saeculare, verse; TEI copy poem-aligned in PerseusDL (CC BY-SA 4.0 repo licence) | use: clean PD e-text; verse, not literal |
| Conington: The Satires, Epistles, and Art of Poetry of Horace (verse), Gutenberg #5419 | John Conington 1870 | txt | 'Public domain in the USA' (landing page) | Satires, Epistles, Ars Poetica in verse | use: clean PD e-text; verse |
| Bennett 1914 Loeb: Horace, Odes and Epodes (prose) | C. E. Bennett, Loeb 1914 (revised 1927) | scan | archive.org NOT_IN_COPYRIGHT on a 1968 reprint; unverified for 1914 | No free scan of the 1914 or 1927 printing found: archive.org searches return the 1901 Allyn & Bacon school edition (Latin with notes: horaceodesandep00unkngoog, NOT_IN_COPYRIGHT), lending-only 1930s-6 | record_only: the 1914 text is PD-US but the only free scan is a 1968 reprint whose NOT_IN_COPYRIGHT flag refers to a Google digitisation; use Smart (Gutenberg) or Wickham 1903 instead until a 1914-1927 scan is found |
| Wickham 1903: Horace for English Readers, prose translation of the whole of Horace | E. C. Wickham, Oxford: Clarendon 1903 | scan | archive.org NOT_IN_COPYRIGHT | Odes, Epodes, Carmen Saeculare, Satires, Epistles, Ars Poetica in prose; djvu OCR present (also horaceforenglis00wickgoog etc.) | use: PD scan with OCR; the best literal prose Odes after Smart |
| Ker 1919-1920 Loeb: Martial, Epigrams, 2 vols (prose) | Walter C. A. Ker, Loeb 1919 (vol. 1) and 1920 (vol. 2) | scan | archive.org NOT_IN_COPYRIGHT | Both volumes: vol. 1 martialepigrams01martiala, vol. 2 martialepigrams02martiala (both 'date 1919-1920', NOT_IN_COPYRIGHT); also epigramswithengl02martuoft (1920, Toronto, no rights field) | use: PD-US scans with OCR; Ker bowdlerises obscene epigrams into Italian |
| Bohn 1860/1865: The Epigrams of Martial translated into English prose | Henry G. Bohn (ed.), Bohn's Classical Library 1860; LoC scan of the 1865 printing; also epigramsmartial00bohngoog (1897, NOT_IN_COPYRIGHT) | scan | archive.org: LoC 'unaware of any copyright restrictions' | All epigrams in prose with metrical versions | use: PD scan |
| Slater 1908: The Silvae of Statius translated with introduction and notes | D. A. Slater, Oxford: Clarendon 1908 | scan | archive.org NOT_IN_COPYRIGHT | Silvae I-V in prose, with notes | use: PD scan with OCR |
| Mozley 1928 Loeb: Statius vol. 1 (Silvae, Thebaid I-IV) | J. H. Mozley, Loeb 1928 | scan | archive.org 'Permission Granted to Digitize Item'; PD-US since 2024 | Silvae complete with facing Latin; item flagged 'Permission Granted to Digitize Item' (Toronto PIMS); also statius01stat (Princeton, no rights field) | use: PD in the US since 1 Jan 2024 (published 1928); the Latin of this volume is the PerseusDL Silvae text |
| Miller: Seneca's Tragedies, 1907 verse (Chicago) and 1917 Loeb prose | Frank Justus Miller, Loeb 1917 vol. 1 (tragedieswitheng01seneuoft, NOT_IN_COPYRIGHT); verse 1907 tragediesseneca00senegoog (NOT_IN_COPYRIGHT) | scan | archive.org NOT_IN_COPYRIGHT | All ten tragedies; choral odes included | use: PD scans |
| Evelyn-White 1919-1921 Loeb: Ausonius, 2 vols | Hugh G. Evelyn-White, Loeb 1919 (vol. 1) and 1921 (vol. 2: ausoniuswithengl02ausouoft, NOT_IN_COPYRIGHT) | scan | archive.org NOT_IN_COPYRIGHT | Complete Ausonius with facing Latin | use: PD scans; also the only open Latin of most of Ausonius with a stated edition |
| Mahoney 2000: Sulpicia, Six Poems (PerseusDL phi0660.phi003.perseus-eng2.xml) | Anne Mahoney 2000 | tei | CC BY-SA 4.0 (repo license.md) | Six poems, 40 lines | use: CC BY-SA 4.0 repo licence |
| A. S. Kline, Poetry in Translation: Catullus, The Poems (and Horace) | A. S. Kline 2001 (Catullus), 2003-2005 (Horace) | html | Copyright Kline; free for non-commercial purposes, conditions apply | All poems of Catullus; all of Horace | record_only: not public domain; permission covers non-commercial reproduction only and 'Conditions and Exceptions apply'; owner decision needed before any use |

### Commentaries and apparatus

| Resource | Edition / year | Format | Licence (short) | Coverage | Verdict |
|---|---|---|---|---|---|
| Dickinson College Commentaries (DCC) | DCC editions with notes and vocabulary | html | CC BY-SA (terms-use page) | Latin texts linked from /home-page-latin: Cicero (de Imperio, Philippics, Verrines), Eutropius, Jerome Vita Malchi, Nepos Hannibal, Ovid Amores 1, Pliny Letters, Seneca Hercules Furens, Seneca Natural | record_only: licence is clear (CC BY-SA) but none of the Latin lyric poets is there; Seneca HF notes may help with the choral lyrics |
| Perseus Hopper (perseus.tufts.edu): Merrill commentary 1999.04.0006, Catullus Latin 1999.02.0003, Horace texts and commentaries | Merrill 1893 (commentary); Shorey-Laing 1919 | html | robots.txt disallows all; licence unverifiable here | not fetched | record_only: robots.txt disallows every path for generic agents, so no Hopper page was fetched; the Merrill commentary is not in any PerseusDL GitHub repo (canonical-pdlrefwk holds only William Smith's dictionaries) |
| Merrill 1893: Catullus, edited with commentary (Ginn), PD scan | E. T. Merrill, Boston: Ginn 1893 | scan | archive.org NOT_IN_COPYRIGHT | Text and commentary on all poems; djvu OCR present (also catullus00catugoog, NOT_IN_COPYRIGHT) | use: PD scan of the commentary that Perseus serves; the Perseus HTML copy is robots-blocked |
| Ellis 1889: A Commentary on Catullus, 2nd ed. (Clarendon), PD scans | Robinson Ellis 1889 (2nd ed.); also commentaryoncatu00elliiala, acommentaryonca00elligoog (NOT_IN_COPYRIGHT); 1st ed. 1876 cu31924026493118 | scan | archive.org NOT_IN_COPYRIGHT | Full commentary; djvu OCR present | use: PD scan |
| Fordyce 1961: Catullus, a commentary (OUP) | C. J. Fordyce 1961 |  | In copyright | not sought | no: in copyright; note only |
| Wickham: The Odes, Carmen Seculare and Epodes with a commentary (Clarendon 1881 / 1891 / 1912), PD scans | E. C. Wickham, Opera omnia vol. 1, 1881 (operaomniawithco01horauoft), 2nd ed. 1891 (odescarmensecula00horauoft), 3rd ed. 1912 (horacevol1odesca00horauoft), all  | scan | archive.org NOT_IN_COPYRIGHT | Odes, Carmen Saeculare, Epodes with commentary | use: PD scans |
| Page: Horace, Opera with notes by T. E. Page, A. Palmer and A. S. Wilkins (Macmillan 1896), PD scan | T. E. Page et al. 1896; Page's Carminum libri (1883-1895: carminumlibmacm00horauoft etc.) | scan | archive.org NOT_IN_COPYRIGHT | Complete Horace with school commentary | use: PD scan |
| Nisbet and Hubbard, A Commentary on Horace Odes I (1970), II (1978); Nisbet and Rudd III (2004) | 1970-2004 |  | In copyright | not sought | no: in copyright; note only |
| Catullus Online: critical apparatus and repertory of conjectures (Kiss) | D. Kiss, 2013- (all conjectures since 1472) | html | No terms stated; modern apparatus | Apparatus to every line; testimonia; manuscript images | record_only: no reuse terms stated; modern scholarly work; ask the editor (kiss [apud] ub.edu) |

### Aggregators

| Resource | Edition / year | Format | Licence (short) | Coverage | Verdict |
|---|---|---|---|---|---|
| PHI Latin Texts (Packard Humanities Institute) | various (not consulted) | html | Personal study only, no copies (click-through) | Full classical Latin corpus behind a click-through licence | no: personal study only, no copies |
| The Latin Library: Catullus (catullus.shtml) and other poets | Credits page: Catullus 'posted from the Whitman College Classics Department from a revised version of Mynors' Oxford text of 1958'; Horace Sermones and Epodes f | html | No licence stated (provenance note only) | catullus.shtml carries all poems on one page (117,375 bytes; list 1-116 with 2b, 14b, 58b, 78b) | record_only: no licence or terms stated anywhere (about.html, cred.html, home); Catullus follows Mynors 1958 (in copyright) |
| Musisque Deoque (MQDQ), Latin poetry archive with apparatus | various critical editions (site) | html | All rights reserved; no mirroring or automatic capture | Full Latin poetry with metrical and critical apparatus; indices by metre (/indici/metri) | no: all rights reserved, no commercial use, mirroring and automatic capture of texts forbidden without agreement |
| PerseusDL canonical-latinLit (GitHub repository) | see per-file rows | tei | CC BY-SA 4.0 (license.md) | Repo tree listed (not truncated); data/ has 46 phi + 14 stoa groups; license.md at repo root | use: CC BY-SA 4.0 |
| Latin Wikisource (la.wikisource.org) | per page; many 'editio: incognita' | html | CC BY-SA (footer) | Scriptor pages fetched for Catullus, Horace, Martial, Statius, Seneca, Tibullus, Ausonius, Cinna, Laevius (no works), Calvus (404) | use: CC BY-SA; edition quality varies by page |
| Project Gutenberg | various | txt | Each landing page: 'Public domain in the USA' | Author pages fetched for Horace (author/1790) and Catullus (author/8308, author/898 = Burton) | use: PD-US e-texts |
| Internet Archive (archive.org): scans used in this pass | various | scan | per item | Searches run through the advancedsearch JSON API (robots.txt disallows only /control/ and /report/); rights read from https://archive.org/metadata/<id> (fields rights, licenseurl, possible-copyright-s | use: per item; items in the 'internetarchivebooks' lending collection and Digital Library of India uploads were recorded but not relied on |
| HathiTrust |  | scan | unverified (HTTP 403) | Not used | record_only: robots.txt requests to babel.hathitrust.org and www.hathitrust.org both returned HTTP 403 to this User-Agent, so nothing was fetched and no full-text search was run |

## Notes

### Best open Catullus text

- **PerseusDL `phi0472.phi001.perseus-lat2.xml`** (Merrill, Ginn 1893): 116 poems, 2,318 lines, TEI with
  `cRefPattern` poem/line. Header: `Available under a Creative Commons Attribution-ShareAlike 4.0 International License`.
  URL `https://raw.githubusercontent.com/PerseusDL/canonical-latinLit/master/data/phi0472/phi001/phi0472.phi001.perseus-lat2.xml`, sha256 `2a52b461b1114b9a7e0a8166e0248044594890a50313b905b8c7d7639145baa1`.
  Repo `license.md` (CC BY-SA 4.0): sha256 `ccf0e8ce183761bf82700126cc45a4e907b2cede024e65e3fef5c2338b9b7063`.
- The same edition on **Latin Wikisource**, `https://la.wikisource.org/wiki/Carmina_(Catullus,_ed._Merrill)` (index page
  sha256 `010d1be9f0014f55e935d2161acf14cf20470fb3108f2546a01131e23bdf3cce`; subpages `/Carmen I` ... with `{{versus|5}}` line markers and metre
  categories such as `Categoria:Hendecasyllabi`), and Cornish's 1904 Latin at
  `https://la.wikisource.org/wiki/Carmina_(Catullus,_ed._Cornish)` (sha256 `a0d3f01f8156709ef984e247e5949fd50eba33a2c30f2d1deaef44247b2b5cc4`), both
  under the footer `Nonobstantibus ceteris condicionibus hunc textum tractare licet secundum "Creative Commons Attribution-ShareAlike License"`. Two independent witnesses for diffing against Perseus.
- Catullus Online holds Kiss's own text plus the full conjecture repertory, testimonia and manuscript images (home page
  740,849 bytes carries every poem); no terms for text or apparatus are stated anywhere on the site, so it is recorded
  only. The Latin Library Catullus follows "a revised version of Mynors' Oxford text of 1958" (credits page) and states no
  licence. Hypotactic's Catullus page is a JS shell; pass A covers the data format.

### Best open Horace text

- **PerseusDL**: Odes `phi0893/phi001/phi0893.phi001.perseus-lat2.xml` (Shorey and Laing 1919; 3,034 lines; sha256
  `ddac1805d6120b78db476ac94c4d88b066b1fcd7676cd520e6abd927360655dc`), Carmen Saeculare `phi0893/phi002/...perseus-lat2.xml` (76 lines;
  sha256 `70f8e13e5ef8d51a49b2a3f087e6a8c85eb961e6d78e8cd4b5e42001214c832f`), Epodes `phi0893/phi003/...perseus-lat2.xml` (Vollmer, Teubner
  1912; 625 lines; sha256 `e94d55384e838e8e0e5bf36a9636e155b924fb329f375d80edd53554a0193f4b`); Satires (phi004, 2,116 lines), Epistles
  (phi005, Fairclough 1929, 1,492 lines), Ars Poetica (phi006, 476 lines). None of the Horace files has an
  `<availability>` element; the repo `license.md` (CC BY-SA 4.0) is the licence.
- Latin Wikisource's `Carmina_(Horatius)` is a copy of the Perseus Shorey-Laing text ("fons: Perseus"); `Epodi` and
  `Carmen_Saeculare` state no edition. Prefer the TEI.

### Minor poets (machine-readable, open)

- Martial: PerseusDL `phi1294.phi002.perseus-lat2.xml` (Heraeus-Borovskij Teubner 1925/1976, 9,462 lines, CC BY-SA 4.0
  file; the 1976 revision is itself in copyright, recorded not gating). Statius Silvae: PerseusDL `phi1020.phi002`
  (Mozley 1928, 3,901 lines). Sulpicia: PerseusDL `phi0660.phi003` Latin and English (Anne Mahoney 2000) and inside
  Tibullus `phi0660.phi001` (Postgate 1915). Seneca tragedies: PerseusDL `phi1017.phi001-phi010` (Peiper-Richter 1921),
  choral odes not separately tagged. Ausonius: PerseusDL has only De Bissula and Caesares; Wikisource has 40+ works with
  no edition named. Priapea: Latin Wikisource (editio incognita) and Latin Library (Baehrens PLM 1879, no licence); not in
  PerseusDL. Pervigilium Veneris: Latin Wikisource (editio 1848), Latin Library (no licence), Mackail's Loeb text as scan.
- Calvus, Cinna, Laevius: no PerseusDL text; Wikisource has only a Cinna page copied from the Latin Library (Calvus page
  404, Laevius page empty). Open editions with a sourced text are PD scans: Mueller's Teubner *Catulli Tibulli Propertii
  carmina, accedunt Laevii Calvi Cinnae aliorum reliquiae* (1892 printing `catvllitibvllip00catugoog`,
  NOT_IN_COPYRIGHT), Baehrens FPR 1886 (`bub_gb_qhE_ZFDini8C`, CC Public Domain Mark), Morel FPL 1927
  (`fragmentapoetaru00baeh`, no rights field, PD-US by date). Courtney 1993 is in copyright and was not sought.
- DCC has none of these poets (the PRD's "Sulpicia (DCC)" is wrong: DCC's only Sulpic* text is Sulpicius Severus); its
  licence is `Dickinson College Commentaries by Dickinson College is licensed under a Creative Commons Attribution-ShareAlike License`.

### PD literal translations: clean e-text versus scan only

| Translation | Clean e-text | Scan |
|---|---|---|
| Catullus, Smithers 1894 prose (+ Burton verse) | Gutenberg #20732 `https://www.gutenberg.org/cache/epub/20732/pg20732.txt` (sha256 `5a0b450ec685b4dea15f7565c429f833c149582b8143176c040e7b467e4b0659`); PerseusDL TEI `phi0472.phi001.perseus-eng4.xml` (Smithers, poem-aligned, sha256 `dac151949ace81ee4f85f53d7858106be6646781daa6e3870ce7aff7c46d1cf4`) and `perseus-eng3.xml` (Burton) | - |
| Catullus, Cornish 1904/1913 prose | en.wikisource `The_poems_of_Gaius_Valerius_Catullus_(Cornish)` (Proofread-Page transcription of the 1904 CUP book, sha256 `aa88c9fd4671ec138e6387de46a6f316e58739ab2e5a667ac3fdcada7a4b48c9`) | `poemsofcaiusvale00catuuoft` (1904, NOT_IN_COPYRIGHT); Loeb 1913 as the 1918 printing `catullustibullus00catu` (no rights field on the item) with Postgate's Tibullus and Mackail's Pervigilium |
| Catullus, Kelly 1854 Bohn prose | - | `eroticapoemsofca00catu` (LoC: "unaware of any copyright restrictions") |
| Catullus, Lamb 1821 / Martin 1861 verse | - | `poemscaiusvaler01catugoog`, `poemscatu00catuuoft` (NOT_IN_COPYRIGHT) |
| Catullus, Ellis 1871 metrical | Gutenberg #18867 (sha256 `f776fa5db95177d3885a3f74f4244fdb447d94f5487879a76da9bce0be416724`) | `poemsfragmentsof00catuiala` |
| Horace, Smart 1836 prose (Buckley rev.) | Gutenberg #14020 `https://www.gutenberg.org/cache/epub/14020/pg14020.txt` (sha256 `7917f40af30d993d95456c27350864eee8398a78d0319c00a704c9eb8562b863`); PerseusDL eng2 for Satires and Ars Poetica only | - |
| Horace, Conington verse | Gutenberg #5432 Odes/CS (sha256 `b78f660001a270019ce085c4e4072118dab1501493774fe381d8ef342d0a1a63`), #5419 Satires/Epistles/AP; PerseusDL `phi0893.phi001.perseus-eng2.xml` (1882 Bell, poem-aligned) | `odesandcarmensa00horagoog` |
| Horace, Wickham 1903 prose | - | `horaceforenglish00horaiala` (NOT_IN_COPYRIGHT) |
| Horace, Bennett 1914 Loeb prose | - | not found: only the 1901 Allyn & Bacon school text, lending-only reprints, and a 1968 reprint (`odesandepodes01horagoog`); record only |
| Martial, Ker 1919-20 Loeb | - | `martialepigrams01martiala`, `martialepigrams02martiala` (NOT_IN_COPYRIGHT) |
| Martial, Bohn 1860 prose | - | `epigramsofmarti00mart` (LoC) |
| Statius Silvae, Slater 1908 / Mozley 1928 | - | `silvaetranslated00statuoft` (NOT_IN_COPYRIGHT); `statiusstat01statuoft` ("Permission Granted to Digitize Item"; PD-US since 2024) |
| Seneca tragedies, Miller 1907 / 1917 | - | `tragediesseneca00senegoog`, `tragedieswitheng01seneuoft` (NOT_IN_COPYRIGHT) |
| Ausonius, Evelyn-White 1919-21 | - | `ausonius00auso`, `ausoniuswithengl02ausouoft` (NOT_IN_COPYRIGHT) |
| Kline (not PD) | poetryintranslation.com | - |

Archive.org rights were read from `https://archive.org/metadata/<id>`; items whose metadata lacks `rights`,
`licenseurl` and `possible-copyright-status` are marked unverified in the rows even where the date makes them PD-US.
Every scan listed has a `_djvu.txt` OCR file.

### Exact terms

- **PHI Latin Texts** (`https://latin.packhum.org/`, sha256 `c7c4874147aac1d4615c236e4e6c114f05b65521754017bc6652cd5112576ff0`): "I agree to use this web site only for personal study and not to make copies except for my personal use under “Fair Use” principles of Copyright law. Click here if you agree to this License" Verdict: no.
- **The Latin Library** (`https://www.thelatinlibrary.com/about.html`, sha256 `33dc194899239301ecb63f0b36dd251edd4455a7b0214b61e83fa6ccbf533b39`): no licence or terms anywhere; the only
  rights statement is "These texts have been drawn from different sources. Many were originally scanned and formatted from texts in the Public ..." Verdict: record only (Catullus follows Mynors 1958).
- **Catullus Online** (`http://www.catullusonline.org/CatullusOnline/?dir=edited_pages&pageID=5`, sha256 `d310e367164a8b06e99ded4e1c93de413f659bf256c241b79c9608e397065bcf`): the only rights statement is
  "The copyright © of these images is asserted on behalf of the respective libraries, as of 2013 and 2017." No terms for text or apparatus; contact "kiss [apud] ub.edu". Verdict: record only.
- **Musisque Deoque** (`https://www.mqdq.it/`, sha256 `520fb0db694c4c3159f326275f3b64022029c063b608c40d7b7b815635c4bd6a`): "Tutti i diritti dei testi con apparato contenuti in www.mqdq.it sono riservati alle unità del Progetto Ricerca di Interesse Nazionale Musisque Deoque, ai curatori editoriali dell'opera e agli autori originari dei documenti. Non ne è consentito alcun uso a scopi commerciali se non previo accordo. Sono consentite la riproduzione e la circolazione in formato cartaceo o su supporto elettronico portatile (off-line) ad esclusivo uso scientifico, didattico o documentario, purché i documenti non vengano alterati in alcun modo sostanziale, ed in particolare mantengano le corrette indicazioni di data, paternità e fonte originale (citazione). Link da altri siti web sono graditi, soprattutto se ne verrà data comunicazione alla redazione (mqdq-galaxy@unive.it), per facilitare la tempestiva comunicazione di eventuali successive variazioni. È vietato ogni genere di mirroring (duplicazione) su altri siti, o di cattura automatica dei testi, a meno di specifici accordi con la redazione." Verdict: no.
- **A. S. Kline** (`https://www.poetryintranslation.com/PITBR/Latin/Catullus.php`, sha256 `1a4c4d48981ee408fb5eb301ce8687b7b249035da1171fb658c9adbd7e35bcb2`): "© Copyright 2001 All Rights Reserved This work may be freely reproduced, stored and transmitted, electronically or otherwise, for any non-commercial purpose. Conditions and Exceptions apply." Verdict: record only.
- **DCC** (`https://dcc.dickinson.edu/terms-use`, sha256 `c7d6aa7c7041da8b4d753ff6a86c6968edc05bfbefdb3b9be406c5f4ff84275f`): "Dickinson College Commentaries by Dickinson College is licensed under a Creative Commons Attribution-ShareAlike License".
- **PerseusDL** `license.md`: "Attribution-ShareAlike 4.0 International" (sha256 `ccf0e8ce183761bf82700126cc45a4e907b2cede024e65e3fef5c2338b9b7063`); the
  Catullus files add "Available under a Creative Commons Attribution-ShareAlike 4.0 International License".
- **Latin Wikisource** footer on every page read: "Nonobstantibus ceteris condicionibus hunc textum tractare licet secundum "Creative Commons Attribution-ShareAlike License"".
- **Hypotactic** (`https://hypotactic.com/use-the-source/`, sha256 `3b67098e9176e352d8d3a87cddf5b958424e3428cf2581268e003e605ab8df74`): "If you’re interested in the scansion of the texts, you can use the source code of the pages as data. Each syllable is tagged as a span, with classes short/long, foot#, word#, wordend, hemi1/hemi2 (before or after main caesura), footend." No licence name appears on the fetched pages; the CC BY 4.0 statement the Greek survey quotes from the Urdatorn/hypotactic repo was not re-verified (GitHub API HTTP 403, rate limit).

### Blocked or unverified

- **Perseus Hopper**: `https://www.perseus.tufts.edu/robots.txt` (sha256 `802ee28567641161a619fb16bf8cf1739599caf9bbac8abe4f845b678a59a295`) puts `User-agent: *` in one group
  with `user-agent: stress-agent` / `Disallow: /` (only comment lines between them), so every Hopper URL, including
  Merrill's commentary `Perseus:text:1999.04.0006` and `/hopper/opensource/download`, was left unfetched. The commentary
  is not in any PerseusDL repository (`canonical-pdlrefwk` holds William Smith's dictionaries only); use the PD scan of
  Merrill's 1893 Ginn edition (`catulluseditedby00catuuoft`, NOT_IN_COPYRIGHT) instead.
- **HathiTrust**: `babel.hathitrust.org/robots.txt` and `www.hathitrust.org/robots.txt` both answered HTTP 403 to this
  User-Agent; nothing was fetched and no full-text search was run.
- **Project Gutenberg** search is disallowed (`Disallow: /ebooks/search`); author pages were used instead.
- **GitHub API** rate limit (HTTP 403) stopped the `canonical-pdlrefwk` tree and `Urdatorn/hypotactic` listings; the
  pdlrefwk contents were read from the GitHub HTML tree page instead.
- Fordyce 1961 and Nisbet-Hubbard 1970/1978 (Nisbet-Rudd 2004) are in copyright and were not sought.
