# Audit: every poem in Campbell, *Greek Lyric Poetry* (1967)

Date: 2026-10-08. Source: `C:/Users/alvin/Downloads/Campbell Greek Lyric Poetry.pdf.pdf`
(sha256 `8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f`, 493 PDF pages).
Status: **prepared, not deployed** (ship steps in `docs/deployment.md`, "Prepared: release GLP").

## Inventory

The text section is PDF pages 33–167 (printed pages 1–135; printed = PDF − 32); the notes begin
on PDF page 168. Campbell prints **237 poems/fragments** (2,562 printed text lines), each headed
by the number of the standard edition he follows (Diehl for elegy/iambus, L–P for Sappho/Alcaeus,
PMG for melic, Snell for Bacchylides, Theognis by line numbers), exactly as printed.

| Poet | Poems | Poet | Poems | Poet | Poems |
|---|---|---|---|---|---|
| Archilochus | 31 | Sappho | 24 (incl. Fr. Adesp. 976 PMG) | Theognis | 23 |
| Callinus | 2 | Alcaeus | 18 (5 already live) | Hipponax | 8 (incl. Fr. Chol. Adesp. 1) |
| Tyrtaeus | 2 | Ibycus | 5 | Simonides | 25 (9 PMG + 16 Diehl epigrams) |
| Semonides | 5 | Anacreon | 17 | Pratinas | 1 |
| Alcman | 12 | Xenophanes | 9 | Timocreon | 2 |
| Mimnermus | 5 | Phocylides | 4 | Corinna | 3 |
| Solon | 9 | Demodocus | 2 | Bacchylides | 6 (Odes 3, 5, 17, 18; frr. 4, 20B) |
| Stesichorus | 5 | Praxilla | 1 | Carmina Popularia | 3; Scolia 15 |

Already live before this work: 5 (Alcaeus 34a, 129, 130 [= `130b`], 326, 350). New: **232**.
IDs follow the existing pattern `campbell-glp:<poet>:<printed number>` (e.g. `campbell-glp:theognis:19-26`,
`campbell-glp:simonides:76d`, `campbell-glp:corinna:654-iii-12-51`). Records use the same schema,
source (`campbell_assignment`), edition string, quality (`machine_corrected_ocr`) and licence label as
the five approved rows; Alcaeus rows join the existing Alcaeus work. `source_url` is the Open Library
record of the edition (no facsimile pages were published: no edition images are committed).
Campbell's commentary and translations are not included (as before, only the five assignment poems
carry the approved commentary).

## Method (all evidence in `data/campbell_glp/evidence/`)

The PDF's text layer is corrupt OCR and was not used. Everything was read from the page images
(807×1278 px scans), following `evidence/protocols/PROTOCOL.md` (NFC polytonic; `’` elision; `·`;
combining U+0323 underdots; brackets, cruces and dot counts as printed; margin numbers as labels;
apparatus, running heads and metrical schemes excluded from the text, schemes kept as metadata).

1. **Two independent transcriptions** of every page (pass A from 2× crops; pass B from its own 3× line
   crops; B never saw A). 2,412 of 2,562 lines agreed character for character.
2. **Cross-check** against other editions already in the corpus, used only to raise flags: words whose
   letters agree but whose breathing/circumflex/iota subscript/diaeresis differ (183 flags).
3. **Image adjudication** of 444 items (134 A/B disagreements, 310 agreed-but-flagged lines), each
   decided from 4–24× crops compared with certain glyphs on the same page (`evidence/adjudication/out_J1–8`).
   77 lines changed from pass A; several readings that both transcribers shared were corrected (e.g.
   breathing+grave vs circumflex, ὢς vs ὠς, rough breathings on ἕρξαι/ἕρδουσι).
4. **Proofreading** of the whole final text, all 2,562 lines, against the images (`evidence/verify/`):
   15 proposed corrections, re-adjudicated from the image (`out_R`): 12 accepted, 3 rejected as printing
   blemishes (a stray grave over a consonant etc.), noted on the poem.
5. **Records** built deterministically (`scripts/build_campbell_glp.py`); stored rows are diffed against
   the transcription by `scripts/verify_campbell_glp.py`.

Readings the scan cannot settle (mostly breathings 3 px wide or letters at a damaged left margin) are
stored in each poem's `metadata.transcription_uncertainty`: **36 notes on 28 poems**. Calibration:
on the five already-approved poems both new passes agreed with each other where they disagreed with
the live text, and the image confirmed the new reading in the clear cases below.

## Corrections to the five live Alcaeus texts (applied on this branch, 2026-10-08)

An image check of every line where the new transcriptions differ from the live texts
(`evidence/adjudication/out_J9.json`) found transcription errors in the live, owner-approved rows.
Each was re-checked on 5–10× crops of the page; the coordinator confirmed PDF pp. 89–90; the owner asked
for faithful texts. The 11 high-confidence corrections (`data/campbell_glp/alcaeus_five_corrections.json`):

| Poem, printed line (PDF p.) | Live text | Campbell prints |
|---|---|---|
| 34a l. 10 (p. 86) | τ]ήλοθεν … πρό[τον’ ὀν]τρ[έχο]ντες | **π**]ήλοθεν … πρό̣[τον’ ὀν]τρ̣[έχο]ντες |
| 129 l. 6 (p. 88) | Αἰολήαν | **Αἰολῄαν** |
| 129 l. 14 (p. 89) | ὠς ποτ’ | **ὤς** ποτ’ |
| 129 l. 16 (p. 89) | τῶν ἐταίρων | **τὼν** ἐταίρων |
| 129 l. 18 (p. 89) | κεῖσεσθ’ … οἰ τότ’ ἔπικ | **κείσεσθ’** … **οἶ** τότ’ **ἐπικ** |
| 129 l. 22 (p. 89) | βραιδίως | **βραϊδίως** |
| 129 l. 27 (p. 89) | γεγρᾶ . [ | **γεγρά** . [ |
| 130b l. 16 (p. 89) | ἄγνοις̣ . . ς̣βιότοις̣ . . ις ὁ | **ἀγνοι̣ς̣** . . ς̣**βιότοις** . . ις **ὀ** |
| 130b l. 21 (p. 90) | πεδὰ τυνδέων | πεδὰ **τωνδέων** |
| 130b l. 23 (p. 90) | ἔγ[ων’ ἀ]πὺ | ἔγ[**ωγ**’ ἀ]πὺ |
| 130b l. 29 (p. 90) | ἔοι̣[ | **ἐοι̣**[ |

Left as approved (scan cannot decide): the underdot on νᾶ̣] and the breathing of οἳ in 34a, the
spacing `. ]` in 129 l. 15, a 1-px speck under δ of δάπτει (129 l. 23; not an underdot), and the final
raised dot after θέων· (130b l. 28). The CHS comparison edition independently prints several of the
corrected readings (ἀγνοι̣σ̣ … ὀ, τωνδέων, βραϊδίως, ὤς).

Re-anchoring (everything pinned to the old wording): corrected package
`data/campbell_glp/alcaeus_five_corrected.jsonl` (sha256 `ab2e1487…`; each record carries
`metadata.text_corrections` with "corrected to Campbell page image, PDF p.N" and `previous_text_sha256`);
re-approval entry in `docs/audits/campbell-assignment-approval.json` (`revisions`); commentary sidecar
(`parent_text_sha256`; paragraph anchors are printed line labels and lemmas, unchanged) and comparison
sidecar rebuilt by their builders (token differences reproduced against the old text, then recomputed
against the corrected one and marked `campbell_text_reanchored`); source-line English re-anchored (the six
paired lines are unchanged; only hashes moved); editorial-readings uncertainty receipt rebound (its ranges
precede the corrected line). `scripts/correct_campbell_five.py corpus` applies the same change to corpus
rows idempotently. Historical extraction scripts and saved experiment packets stay bound to the old text.

## Translations (`backend/translation_comparisons_glp_data.json`)

Owner direction 2026-10-08: show an English translation for every poem with an acknowledgement, using
only public-domain translations (published ≤ 1930), never Campbell's own Loeb versions, never
Edmonds' *Elegy and Iambus* (1931), never AI-written text. Each item was mapped from Campbell's number
to the translator's numbering, matched by content against Campbell's Greek (`match_evidence`,
extent differences in `coverage_note`), and transcribed from the scan with every English word checked
against the page image (scan leaf, IIIF URL and sha256 recorded). They use the existing
comparison-only contract (labelled as another edition, never aligned to Campbell's text, never model input).

**209 of 232** poems have one: Edmonds, *Lyra Graeca* I–III (1922/1924/1927) 125; Banks, Bohn Theognis
(1856) 24 (23 Theognis + Mimnermus 5) and Tyrtaeus (1853) 3; Linforth, *Solon the Athenian* (1919) 9; Burnet, *Early Greek
Philosophy* (1908) 9; Merivale/Bland (1813/1833) 10; Yonge's Athenaeus (1854) 7; Elton (1814) 6; Jebb's
*Bacchylides* (1905) 4; Wilson's Clement (1869) 3; Jones's Strabo (1927–29) 3; Symonds (1920) 2; Dods,
Peters, Paton, Herrick-in-Edmonds 1 each. **23 have no verifiable public-domain translation** and show none
(`data/campbell_glp/translation_gaps.json`): Alcaeus 45; Alcman 3 (papyrus published 1957);
Archilochus 55, 71, 79a, 88, 89, 92a, 103, 104, 112, 118; Semonides 2; Mimnermus 13; Hipponax 24a, 24b,
25, 29, 70, 81; Phocylides 3, 4, 8.

## Local verification (2026-10-08)

- Production-like corpus (local corpus + the five approved rows = 288,589): import adds 232 →
  **288,821**; re-running adds 0; `verify_campbell_glp.py --corpus … --expected-passages 288821`: 232/232 identical.
- Semantic manifest rebind: existing vectors retained, 232 ids pending embedding, binding matches the new corpus.
- Dev server (`tools/serve_dev.py`, port 8795): all 232 passages open with identical text; 209 show the
  translation panel and the 23 gaps show none; `/api/analyze-passage` on the first two analysable lines of
  every poem: 455 lines, 0 failures. `tests/test_campbell_glp.py`: 4 pass.
