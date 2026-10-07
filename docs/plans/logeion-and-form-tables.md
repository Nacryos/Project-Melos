# Logeion, and where to get inflected-form tables legitimately

Status: research only. Nothing was downloaded into `data/`, and no code was changed.
All URLs were checked on **2026-10-07** unless another date is given. Logeion was
visited read-only: robots.txt, the front-end script, and its inlined About pages.
Its API was not called.

## 1. The short answer

**Do not scrape Logeion.** Its robots.txt does not forbid crawling, but Logeion
publishes no licence, terms or open data that would let anyone *copy* its content.
Its API uses a private client key that is built into its own front end. Several of
its Greek dictionaries are copyright works that Logeion shows only by agreement
with the rights holders. Everything open on Logeion can be downloaded from the
original source, including Logeion's own corrected LSJ (CC BY-SA 4.0 on GitHub).
Logeion's morphology database, which links inflected forms to headwords, has never
been released under a licence. To get it, ask Helma Dik.

## 2. What Logeion allows

| Question | Finding | Source (checked 2026-10-07) |
|---|---|---|
| robots.txt | `User-agent: * / Disallow:` (allows all crawlers). File last modified 2017-08-03. | https://logeion.uchicago.edu/robots.txt |
| Terms of use / licence for the site | **None found.** The About page has no terms or licence. It says "Most of the reference works in our collection are older and in the public domain. We are grateful for the exceptions: DGE, LMPG, DMLBS, LaNe, GrNe…". Licences are given for each dictionary, not for the site. | https://logeion.uchicago.edu/about (text inlined in `scripts/scripts.389be11e.js`, template `views/about.logeion.html`) |
| Public API | **No public API.** The front end calls `https://anastrophe.uchicago.edu/logeion-api`, `/morpho-api/` and `/retro-api`. A `TokenInterceptor` adds a fixed `key=` parameter to every API request. The API is not documented (its root returns only "Hello, Logeion."), and anastrophe has no robots.txt (404). Using the key from another site would mean using Logeion's private client credential. | Same JS bundle; https://anastrophe.uchicago.edu/logeion-api |
| Third-party API users | `Corykidios/logeionicon_mcp` (MIT, 2026-03) calls that API. Its README says nothing about permission from Logeion. This does not show that Logeion allows such use. | https://github.com/Corykidios/logeionicon_mcp |
| Data dumps | SourceForge `logeion` has `greekInfopublic.db` (102.2 MB), `latinInfopublic.db` (104.1 MB) and `dvlg-wheel-mini.sqlite` (33 MB), all dated **2013-12-20**, with **no licence field**. They were not downloaded, so their contents are not verified. | https://sourceforge.net/projects/logeion/files/ |
| Code | `logeion/logeion-backend`, `-cgi` and `-html` were last pushed in 2015 and have **no licence**. They hold parser scripts only, with no dictionary data. `helmadik/Logeionparserexamples` (2021) also has no licence. | https://github.com/logeion/logeion-backend |
| Corrected dictionary data released by Logeion's editor | `helmadik/LSJLogeion`: **CC BY-SA 4.0** (LICENSE.md), pushed 2026-10-04, with the request "please credit Perseus Tufts *and* Helma Dik/Logeion". `helmadik/LewisShortLogeion` (Latin). `helmadik/shortdefs`: no licence file, README asks for credit to Perseus and Logeion. `helmadik/MiddleLiddell`: no licence, 2026-08-04. `helmadik/WoodhouseLogeion` (English→Greek). | https://github.com/helmadik |
| Morphology (Μορφώ) | The About-Μορφώ page says the parses come from "our morphological databases", and that "A check mark shows up for parses that we have actually, manually, applied in our database". Paradigm charts list only "forms … parsed by a person (we don't trust our databases and neither should you)". **This database has not been published under any licence.** It comes from Morpheus output plus manual corrections made at Chicago ("Perseus under PhiloLogic", `perseus.uchicago.edu`). | `views/about.morpho.html` in the JS bundle |
| Morphology connections that are open | Helma Dik contributes Morpheus stem-file fixes to `helmadik/morpheus`, a fork of `alpheios-project/morpheus` that was pushed 2026-08-19. Alpheios says stem-file pull requests "will be deployed to the Alpheios morphology service". That service is the one Melos already queries (`backend/machine_morphology.py`). So Melos already gets Chicago's stem-level corrections through Alpheios. | https://github.com/alpheios-project/morpheus (README) |
| Contact | "please contact Helma Dik (Classics Department, University of Chicago) directly if you have dictionaries that we can use or other assistance". Bug reports go through a Google Form. | About page |

## 3. Greek dictionaries on Logeion and their licences

| Dictionary | Status | Rights (as stated by Logeion or the source) | In Melos? |
|---|---|---|---|
| LSJ 1940 (Perseus; Chicago-edited) | Open | Perseus text CC BY-SA 3.0 US. Chicago edition **CC BY-SA 4.0** (`helmadik/LSJLogeion`) | **Production** (PerseusDL/lexica `56061ca`) |
| Middle Liddell 1889 | Open | Perseus Hopper CC BY-SA 3.0 US. Chicago copy has no licence | **Staged** (`data/staging/lexica`) |
| Autenrieth 1891 | Open (public-domain print) | Perseus/Homerica. The digital edition's licence is not stated | **Production** |
| Cunliffe 1924 | Open (public-domain print) | Perseus/Crane, cleaned by Dik. The digital edition's licence is not stated | **Staged** |
| Abbott-Smith 1922 (NT) | Public-domain print | Volunteer edition (`translatable-exegetical-tools/Abbott-Smith`). The repository has no licence file | No (NT only, low value) |
| Woodhouse 1910 (Eng→Gk) | Public-domain print | Bauman/Chicago digitisation | No (wrong direction) |
| Slater, *Lexicon to Pindar* 1969 | **Copyright** (De Gruyter) | Shown through Perseus and NEH funding. No open release | Blocked (see `docs/lexica-perseus-ingestion.md`) |
| Pape 1880 (Gk→De) | Public-domain print. Digital rights unclear | Digitised by P. Roelli, HTML supplied by A. Charbonnet. No licence stated | No |
| Bailly 2020 "Hugo Chávez" (Gk→Fr) | Free download. Licence not verified | Gréco team (gerardgreco.free.fr). Logeion uses it with permission. No open licence was found on the project page | No (ask first) |
| DGE (α–ἔξαυος) | **NC licence** | DGE site: CC BY-NC-SA 3.0 ES. Logeion's About page says "non-commercial, no-derivatives" | No |
| LMPG (magical papyri) | **NC licence** | DGE project licence (CC BY-NC-SA 3.0 ES) | No |
| Brill/Montanari *BrillDAG* | **Copyright** | Only the letter Λ, under an agreement with Brill (Nov 2022) | **Must not** |
| Grieks/Nederlands (GrNe) | **Copyright** | Shown by permission of the editors | **Must not** |
| Cambridge Greek Lexicon (2021) | Not shown on Logeion (0 mentions in the bundle) | © CUP | **Must not** |

## 4. Legitimate sources for form → lemma/morphology tables

Aeolic/lyric coverage was measured where possible. GLAUx figures come from its
`metadata.txt`, read 2026-10-07.

| Source | Licence | Size | Lyric / Aeolic coverage | Format | Download |
|---|---|---|---|---|---|
| **PerseusDL AGDT v1.6/2.1** (Melos already has v1.6) | CC BY-SA 3.0 US | Melos has 478,086 token rows | **No lyric.** Melos's v1.6 files are Homer, Hesiod, the tragedians, Athenaeus, Polybius, Plutarch | ALDT XML, 9-character postag | github.com/PerseusDL/treebank_data |
| **Pedalion trees: `sappho.xml`** | Repository LICENSE is MIT (code). README: "We will assign … probably CC BY-SA 4.0". GLAUx lists Pedalion as CC BY-SA 4.0 | 4,530 `<word>`s, 413 sentences (incl. punctuation) | **Sappho, manually annotated** (Y. Joosten, 2020). Also a 1.5K-token "Lyric" set (Theocritus, Mimnermus, Semonides) | ALDT 1.5, **the same postag as forms.jsonl** | github.com/perseids-publications/pedalion-trees `public/xml/sappho.xml` (commit `ee6c0112`, 2020-12-23) |
| **GLAUx** | CC BY-SA 4.0 overall. **Licence varies by text** (`SOURCE_LICENSE`: some NC/ND/"NA") | 1,421 texts, 19.5M tokens | Lyric genre 150,486 tokens: Pindar 24,857, Theognis 11,484, Bacchylides 5,549, Simonides 1,882, Anacreon 3,005, **Sappho 83, Alcaeus 0, Alcman 0**. All Aeolic texts: **185 tokens** | XML (NFD), AGDT-style; mostly automatic, with some parts manual | github.com/alekkeersmaekers/glaux, DOI 10.5281/zenodo.10948374 |
| **Morpheus** (Alpheios fork + stemlib) | Root LICENSE: Perseus CC BY-SA 3.0 US with component caveats. The perseids-tools fork is MPL-2.0 | Generates forms; stemlib 13.8 MB | Has some dialect tags (Aeolic, Doric, Epic). Aeolic coverage is partial. **Machine output, not attestation** | C engine with XML output | github.com/alpheios-project/morpheus `2f1a30d` (see `docs/morpheus-offline-feasibility-20261006.json`) |
| **Diorisis** | CC BY 4.0 (figshare). The texts come from Perseus (CC BY-SA), so keep BY-SA notices | 820 texts, 10,206,421 words, `Diorisis.zip` 194 MB | Lemmas assigned automatically with Morpheus and then disambiguated by a tagger. Includes texts from Bibliotheca Augustana; **lyric coverage not checked** (it needs the zip) | XML | doi.org/10.6084/m9.figshare.6187256 (2018-05-02) |
| **Celano, LemmatizedAncientGreekXML v1.2.5** | **CC BY-NC 4.0** | 25.5M tokens, 21.5M lemmas. Also `Morpheus/MorpheusUnicode.xml.zip` (12.5 MB) | Automatic (Mate tagger + Morpheus/"MorpheusUnderPhilologic" lemmas) | XML | github.com/gcelano/LemmatizedAncientGreekXML (2017) |
| **PROIEL** / UD-PROIEL | **CC BY-NC-SA 3.0** | Greek: NT 140,763 + Herodotus 85,080 tokens | No lyric | PROIEL XML / CoNLL-U | github.com/proiel/proiel-treebank |
| UD_Ancient_Greek-Perseus | **CC BY-NC-SA 2.5** (more restrictive than its AGDT source) | — | Same as AGDT | CoNLL-U | Use AGDT directly instead |
| Gorman trees | **CC BY-NC-SA 4.0** (`vgorman1`). The Perseids mirror is MIT for code | Prose only | None | ALDT | github.com/vgorman1/Greek-Dependency-Trees |
| **Kaikki / Wiktionary** (Melos already has it) | CC BY-SA 4.0 + GFDL | Melos has 68,196 entries (`data/wiktionary.sqlite`) | Has dialect-labelled forms in paradigm tables. These are dictionary-listed forms, not attestations | JSONL | kaikki.org/dictionary/Ancient Greek/ |
| Logeion Μορφώ database | **Unlicensed; not published** | Unknown | Some forms are manually checked (Homeric and Doric are mixed in) | — | Only by asking Helma Dik |

## 5. Recommendation (in priority order)

| # | Ingest | Why | How it feeds the parser |
|---|---|---|---|
| 1 | **Pedalion `sappho.xml`** (+ the 1.5K lyric set) | The only manual, attested Aeolic annotation found. Its postag scheme is identical to Melos's. Very small (about 4.5K tokens) | Append rows to `data/lexica/forms.jsonl` with `source: "Pedalion Trees (Sappho)"`, pinned `source_url` at the commit, `raw_sha256`, and `license: "CC-BY-SA-4.0 (stated intent; repo MIT)"`. `analysis_format: "Perseus treebank 1.5 postag"`. Because `Morphology.analyze` ranks *same-author, source-annotated* parses higher, these will disambiguate forms in Sappho passages directly. First confirm the licence with the Leuven team (Toon Van Hal or Alek Keersmaekers) by email |
| 2 | **GLAUx, only texts whose `SOURCE_LICENSE` is CC BY-SA/BY**, starting with the lyric genre (about 145K tokens) and the manual-treebank subset | Large, AGDT-compatible, and Pindar/Bacchylides/Theognis are well represented. Exclude NC, ND and "NA" rows | Add to `forms.jsonl` with a `quality` field separating `manual` (rows where `TREEBANK_ANNOTATIONS` ≠ NA) from `automatic`. Automatic rows should have the same evidence weight as machine output, not attestation. Convert NFD to NFC first |
| 3 | **`helmadik/LSJLogeion`** (CC BY-SA 4.0) in place of, or beside, PerseusDL LSJ | This is the "near perfectly formatted" Logeion LSJ the owner asked for, and it is legally downloadable. It has Unicode Greek, corrected entries, and `lang="grc"` markup | Rebuild `data/lexica/entries.jsonl` LSJ rows from a pinned commit. Keep `entry_id`s and add a column for the old Perseus ID. Credit Perseus *and* Dik/Logeion as requested. Then promote staged Middle Liddell and Cunliffe as already planned |
| 4 | **Offline Morpheus** (Alpheios stemlib, which already carries Dik's fixes) | Covers forms not in any treebank. Removes the network and quota limits of the hosted service | Keep it on the existing `machine_morphology.py` path. Produce receipts with `engine: morpheus-offline@<rev>`, kept separate from attested `forms.jsonl` and labelled with the same "machine alternatives" warning |
| 5 | **Diorisis**, after checking its lyric file list | More automatic lemmas. CC BY 4.0 | Same as the automatic tier of GLAUx: lemma only, `quality: automatic`, low weight |
| 6 | **Ask Helma Dik** for (a) the hand-checked Μορφώ parses, (b) a licence for `shortdefs` and `MiddleLiddell`, (c) any newer `greekInfopublic.db` | The hand-checked parses are the valuable part of Logeion's morphology | If permission is given in writing, add them as a separate `source` with the stated licence. Keep the manually checked parses distinct from the Morpheus-generated ones |

**Must not ingest:** anything scraped from logeion.uchicago.edu or anastrophe
(no licence, private key). Brill/Montanari, Grieks/Nederlands, Cambridge Greek
Lexicon, and Slater (copyright). DGE and LMPG (NC; greeklyric.com is public, and
NC creates risk if the site is ever funded or monetised). PROIEL, UD-Perseus,
Gorman trees and Celano's corpus (all NC). Leave them out of production unless the
owner accepts NC terms for the whole site. Keep the Wiktionary paradigm forms in
their separate reference index, as `docs/wiktionary-reference.md` already
requires. Do not merge them into `forms.jsonl`, because dictionary-listed forms
are not attestations.

## 6. Sources (all accessed 2026-10-07)

- Logeion robots.txt: https://logeion.uchicago.edu/robots.txt. About pages: https://logeion.uchicago.edu/about (the content comes from `https://logeion.uchicago.edu/scripts/scripts.389be11e.js`)
- Logeion SourceForge: https://sourceforge.net/projects/logeion/files/. Backend: https://github.com/logeion/logeion-backend. CLTK proposal (2014-10-09): https://github.com/cltk/cltk/issues/30
- Helma Dik repositories: https://github.com/helmadik/LSJLogeion, https://github.com/helmadik/shortdefs, https://github.com/helmadik/morpheus
- Alpheios Morpheus: https://github.com/alpheios-project/morpheus. Perseids Morpheus (MPL-2.0): https://github.com/perseids-tools/morpheus
- DGE licence: http://dge.cchs.csic.es/xdge/doc/licencia. Bailly 2020: http://gerardgreco.free.fr/spip.php?article52&lang=fr
- AGDT: https://github.com/PerseusDL/treebank_data. Pedalion: https://github.com/perseids-publications/pedalion-trees
- GLAUx: https://github.com/alekkeersmaekers/glaux (metadata.txt). Diorisis: https://api.figshare.com/v2/articles/6187256
- Celano: https://github.com/gcelano/LemmatizedAncientGreekXML. PROIEL: https://github.com/proiel/proiel-treebank. UD: https://github.com/UniversalDependencies/UD_Ancient_Greek-Perseus, https://github.com/UniversalDependencies/UD_Ancient_Greek-PROIEL. Gorman: https://github.com/vgorman1/Greek-Dependency-Trees
- Kaikki: https://kaikki.org/dictionary/Ancient%20Greek/
