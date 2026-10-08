# Live UX audit — greeklyric.com, 2026-10-08

Goal: reading fragments, looking words up and parsing them on greeklyric.com should be at least as good as
Logeion, Perseus/Protagoras and the TLG. This audit tested the live site the way a reader would and fixed the
small frontend problems it found. Backend problems are listed for the release N work; nothing in `backend/`
was changed. The last section compares the site with Logeion, Perseus and the TLG.

## Method

- Python Playwright with headless Chromium on the live site, 1440×900 desktop and 390×844 phone (touch).
  Real mouse moves, hovers, clicks, drags and touch taps at element coordinates. Screenshots were checked by
  eye. Console errors and failed requests were logged.
- 20 Campbell GLP poems: Sappho 16, 31, 34, 96; Alcaeus 129, 347; Alcman 1, 89; Anacreon 358, 417;
  Simonides 542, 581; Ibycus 282a, 286; Stesichorus 192; Archilochus 1, 5a; Tyrtaeus 9; Bacchylides 17;
  Theognis 19–26. Campbell GLP has no Pindar.
- In each poem we clicked six kinds of word: an ordinary word, a bracketed word, an elided word, a word with an
  underdot, a proper name and a line-final word. That made 82 word lookups.
- Ten home searches: moon, σελάννα, selanna, ἔρος, eros, ερος (no accents), γλυκύπικρος, glukupikros,
  rose-fingered, ἀέλιος.
- Phrases were selected by mouse drag and by tap mode. We tested the phrase-search buttons, previous and next
  passage, browser Back and Forward, links with `?id=` or `?q=`, translations, source notes and browsing by
  poet. Every control in the reader and in the search results was hovered.

Timings on the live site, before the fixes:

| Action | Time |
|---|---|
| Home page, first poem readable | 1.1 s (3.6 s including the painting) |
| Poem opened from a link, words clickable | 0.8–1.4 s |
| Search results | 0.55–1.4 s |
| Word panel: headword and gloss shown | 1.1–1.3 s |
| Word panel fully loaded | 1.6–4.6 s |
| Phrase analysis (1 to 6 words) | 1.0–3.2 s |

## Issues found and fixed (frontend)

Deployed to production. Tests: 459 frontend tests pass (`npm run test:frontend`). Five tests were added or
updated, plus a new file, `tests/live-ux-audit.test.mjs`.

| # | Issue as a reader meets it | Fix |
|---|---|---|
| 1 | **The poem jumped on the first word click.** The selection toolbar appeared above the poem and pushed the clicked word about 166 px down, away from the cursor. This happened in every poem. | The page now scrolls by the same amount, so the word stays under the cursor. If the toolbar is stuck at the top of the screen, a word underneath it is scrolled just below it. The fix is `holdInView` in `js/passage-analysis.js`. |
| 2 | **Dragging the mouse across words selected nothing.** Chromium and Safari do not start a text selection inside a `<button>`, so a drag from one word to another did nothing or picked one stray word. Sometimes the selection jumped into the toolbar text. | A mouse drag from one word to another now selects every word in between, with a live highlight. The browser's own text selection is turned off during the drag. Touch drags still scroll the page. |
| 3 | **A misplaced click turned the next click into a long selection.** The sticky toolbar covered words near the top of the screen. Clicking one of those words pressed "Choose end word" instead. The next word click then selected about 15 lines (Sappho 16), and the word panel stopped updating. | Same fix as #1: a clicked word is kept clear of the toolbar. With a mouse the toolbar is also more compact (`@media(pointer:fine)`), so it covers fewer lines. |
| 4 | **The analysis heading was hidden.** "Selection analysis" and "Collapse analysis" scrolled under the sticky toolbar, on desktop and on phones. | The analysis panel now leaves room for the toolbar when it scrolls into view. |
| 5 | **Back and Forward skipped passages.** Every passage change replaced the current history entry, so Back left the site or jumped far back. | A passage the reader chooses now gets its own history entry. Back and Forward reopen that passage. Loading the page and Back/Forward themselves still replace the entry. |
| 6 | **Search links never finished loading.** A link such as `?q=moon` showed "Opening the reader / Loading a passage from the corpus…" forever. | The reading area now shows a heading, "The reading desk", and the message "Choose a search result to read it here, or choose a poet under 'Browse the corpus'." |
| 7 | **Search labels used technical terms.** Examples: "Ranked by reciprocal rank fusion; rank is not confidence", "lexical + forms + semantic; direct passage match", "semantic · text: Original passage embedding", "Themes: partial (116,191/116,428 eligible)" and "ranking is not certainty or influence". | New wording: "Same words, related word forms and similar meaning, found in the Greek text", "Listed by how well several kinds of match agree; the order is not a measure of certainty", "Similar meaning · …: similar in meaning to the whole passage" and "Theme search covers 116,191 of 116,428 passages". Reasons the frontend does not recognise are shown unchanged. |
| 8 | **Internal record IDs on buttons.** Occurrence buttons read "Open p2_alcaeus:elws:20686:122262:Bergk-order:23" or "Open ogc:sappho.fragmenta.jsonl:64". | They now read "Open this record →". The ID is still in the tooltip and the screen-reader label. |
| 9 | **Parse labels without spaces.** Possible analyses read "accusative,dual,feminine" or "indicative,middle,passive,singular,third-person". | Spaces are added after the commas, in the word panel and in the selection analysis. |
| 10 | **Some controls looked unclickable.** Disclosure rows (`summary`), menus (`select`), dictionary source links, "Select phrase" and the site title showed no change on hover. Some disclosure rows even showed the text cursor. | All of them now show a pointer cursor and a hover colour or underline. |
| 11 | **Gaps between verse lines on phones.** Each numbered line (5, 10, 15) was about 42 px tall instead of 25 px, because of the line number's line height. | Line numbers now sit on the verse baseline and add no height. |
| 12 | **The "Dictionary alternatives" arrow wrapped.** Its chevron dropped onto a line by itself. | The summary row is laid out as a flex row. |
| 13 | **"Look up entered form" was unclear.** What was "entered"? | Renamed "Look up searched word", with the tooltip "Look up the word typed in the search box". |

Verified live after the deploy (screenshots `live2_*.png` in the session scratchpad `ux-audit/`):

- The word stays in place on the first click (244 → 244 px).
- Dragging from μοι to ὤνηρ across two lines selects «μοι κῆνος ἴσος θέοισιν ἔμμεν’ ὤνηρ».
- The analysis heading sits below the toolbar (heading at 156 px, toolbar ending at 128 px).
- Back and Forward between Sappho 31 and 34 work.
- `?q=moon` shows "The reading desk".
- On phones the first seven lines are all 25 px tall and nothing scrolls sideways.
- No console errors.

## Issues found, not fixed (frontend, need design or backend data)

- **The word panel is long and uses technical terms.** Examples: "Normalized search: εμμεν'", "Source lemma
  inventories · 11 groups", "Nearby spelling: εἰμί · PerseusDL Greek Dependency Treebank v1.6 · 50 of 155
  forms shown", "Snapshot record hash". These need a design pass: keep headword, gloss, form and parse, then
  one dictionary block and one occurrences block, and put the rest behind a single "Sources" disclosure.
- **The word panel contradicts itself.** For ἔμμεν’ the headline says εἰμί "to be", pres. act. inf., but
  lower down it says "No exact source match" and "No sourced dictionary or morphology analysis is available
  for this form." The frontend cannot word this correctly until the backend says which source supplied the
  headline (see backend item 10).
- **"Source notes and edition details" shows raw JSON** (comparison and IIIF metadata).
- **Search result cards are cluttered.** Each card shows "Edition:", "Collection: sappho" and "Author date
  claim (birth): 630–612 BCE". The provenance panel shows raw labels: "campbell_assignment" and
  "user_supplied_edition_excerpt". Fixing this needs display labels from the API.
- **Phone tap targets are small.** Words are 25 px tall, and short words such as δ’ and ἐς are only 8–16 px
  wide (the guideline is 44 px). Verse-fit shrinks Greek to about 16 px on phones. A tap-mode magnifier or a
  larger line height on touch screens would help.
- **Some home and footer controls do not suit a reading tool.** "Adjust dither" and "Design studio" sit on the
  reader home page. "Explore usage space ↗" does not say what it does.
- **The toolbar still covers the top of the poem.** When stuck, it covers about the top 120 px on desktop and
  about 220 px on phones. Words are kept clear of it when clicked, but it still hides lines while scrolling.
  One option is to dock it to the bottom of the screen on phones.

## Backend issues (for release N; `backend/` not touched)

1. **Moon search ranking.** For "moon", Sappho fr. 34 (κάλαν σελάνναν) ranks 11th. It comes after Aristophanes
   *Clouds* (4 passages), Aeschylus *PV* 768–787 and the Homeric Hymns to Hermes and Aphrodite, none of which
   mentions the moon.
2. **Sappho fr. 96 in every search.** It is in the top 3 for moon, σελάννα, selanna, ἀέλιος, rose-fingered,
   eros and ἔρος, and 12th–14th for others. Long fragments are favoured by meaning search. Fixes: normalise
   by passage length, or split long fragments.
3. **Several editions of one fragment crowd results.** For σελάννα, Sappho 96 appears 4 times (Digital Sappho,
   DCC, OGC, OCR). For γλυκύπικρος, fr. 130 appears 3 times. "Identical copies collapsed" only catches texts
   that are exactly identical. Results should be grouped by author, fragment and citation number, with the
   editions listed inside one result.
4. **English queries bring in irrelevant Homer.** "rose-fingered" returns Iliad 1.61–80, 1.21–40, 2.61–80
   and others that lack ῥοδοδάκτυλος. The Odyssey hits with ῥοδοδάκτυλος Ἠώς are fine.
5. **Author and work names are raw labels.**
   - Slugs such as "hesiodus theogonia", "bacchylides tlg0199-tlg001", "pindarus olympia",
     "apollonius-rhodius-epic" and "agathias-scholasticus".
   - "Bergk, Theodor, 1812-1881" and "Ancient testimony quoted by Pitotto" are listed as authors.
   - The Modern Greek collection title "ΣΑΠΦΩ ΜΕΛΙΚΟΙ ΠΟΙΗΤΕΣ" is shown as the work.
   - The same author is split into several entries: "Apollonius Rhodius" (294) and "apollonius-rhodius-epic"
     (5,831).
6. **A "⊗" sign from the source markup** opens Digital Sappho and DCC texts in results (fr. 154, 168B, 112,
   130, 102).
7. **σελάννα alone finds no dictionary entry.** `/api/word?form=σελάννα` returns only spelling suggestions
   (μέλας, "black"), not σελήνη. In a poem, σελάνναν does resolve to σελήνη, so the dialect correspondence is
   applied only with passage context. As a result the search dictionary preview for σελάννα and ἀέλιος shows
   only a collapsed "alternatives" row.
8. **Intermittent server errors.**
   - HTTP 500 from `/api/word?form=δ’&passage_id=…` (Alcaeus 129 and 347, Anacreon 358, Archilochus 1).
   - HTTP 500 for καὶ in Ibycus 282a.
   - One `ERR_CONNECTION_RESET` on `/api/analyze-passage`.

   The panel recovered each time, but the requests failed (the same requests returned 200 when tried again
   later).
9. **Wrong parse or no headword in the panel headline.** Examples from this audit:
   - **Wrong parse:**
     - βλέπουσα: "1st sg. aor. ind. act." (it is a participle).
     - σοφιζομένῳ and ἐπικείσθω: "1st sg. pres. act.", with no headword.
     - περικλεὲς: lemma περικλειτός, parse "voc. pl.".
     - πορφυρῇ: no headword, parse "nom. fem. sg." (it is dative).
     - αὔτ̣[ᾳ: no headword, parse "acc. neut. pl.", although the dictionary block shows ἑαυτοῦ.
   - **No headword when letters inside the brackets complete the word:** κά[τε]σσαν, π̣[ε]λεμαίγιδος,
     ἐπ̣[ελεύσομαι, Ἱππόθω]ν̣.
   - **No headword:** οὔτ’, Θρῃκίη.
   - **No gloss:** μαλίδες (μηλίς).
10. **Weak glosses and inconsistent sources.**
    - Odd glosses: ἀλλά "otherwise" (adv.), αἰνέω "tell", θεός "God" (capital G).
    - Lowercase lemmas for proper names: κύρνος for Κύρνε, σείριος for Σείριος.
    - For σ’ the headline lemma is σύ, but the dictionary preview shows σός (the possessive adjective).
    - `/api/word` should say which source supplied the headline (parser, contextual model, recorded form), so
      the frontend can label the sections below consistently.
11. **The API sends internal labels.** Display labels are needed for collection ("campbell_assignment"),
    licence ("user_supplied_edition_excerpt"), and occurrence record IDs. Human-readable fields are needed
    instead of the JSON metadata objects shown under "Source notes and edition details".

## Gap analysis against Logeion, Perseus/Protagoras and the TLG

Status: present, partial or missing on greeklyric.com today.

| Reference feature | Status | What greeklyric.com has | Proposal |
|---|---|---|---|
| **Logeion:** several dictionaries side by side | partial | The word panel lists meanings from Middle Liddell, LSJ (via Logeion data), Autenrieth and Wiktionary, each labelled, but in one mixed list. The full LSJ entry sits behind "Full dictionary entry". | A tab or column for each dictionary, showing the full entry with sense numbers. Add Slater (Pindar) and Cunliffe where the licence allows, and keep the source labels. |
| **Logeion:** frequency | missing | — | Lemma frequency from a lemmatised GLP and lyric corpus: count, rate per 10,000 words, and rank within lyric and within all of Greek. |
| **Logeion:** word-in-context examples | partial | "Occurrence preview · 12 shown" for the exact form, "Read in context" and linked commentary. These are based on the form, not the lemma, and appear as a list of citations. | A keyword-in-context concordance by lemma: one line per hit, with the keyword centred and highlighted, sortable by author and date. |
| **Logeion:** collocations | missing | — | Words that often occur near a lemma (within ±5 words), scored by how unusual the pairing is (PMI or log-likelihood), each with example lines. This is the base for concept diachrony. |
| **Logeion:** distribution by author and genre | missing | The lexicon and authors pages exist but are not in the reader-only build. | A bar chart of a lemma's hits by author, genre and century, using `author_chronology`. Each bar links to a filtered concordance. |
| **Perseus/Protagoras:** ranked parses | partial | A headline parse, "Possible analyses" and, in phrase analysis, "Parses ranked by fit to the context". There is no single ranked list with a likelihood, and parser and treebank rows appear in different sections. | One ranked parse list combining Morpheus, the treebank and the contextual model. Show a likelihood and the reason for each entry, as Perseus's "click for probability" does. |
| **Perseus/Protagoras:** lemma search across inflected forms | partial | "Forms" search uses alternative forms recorded in the sources, not a full paradigm. "Related word forms" works from a phrase. Lemma queries are not indexed for every token. | Lemmatise every token in the GLP and lyric corpus (Morpheus receipts plus the treebank), so a lemma search finds every inflected form, with a facet listing the forms found. |
| **TLG:** lemmatised search | partial | As above: forms recorded in the sources, plus spelling normalisation. | Same token-level lemma index as above. Allow `lemma:ἔρως` in the search box. |
| **TLG:** proximity search | present | Forms mode: "Nearby, any order" with "Extra words allowed" up to 50, and "All words in passage". Matches are within one stored passage. | Allow matches across passage boundaries within N lines, and allow mixing lemma and form terms. |
| **TLG:** n-gram search | partial | Exact phrases ("Exact words", "Same wording"), but no n-gram lists or counts. | Lists of 2- to 4-word sequences per lemma or author, with counts, for formulae such as ῥοδοδάκτυλος Ἠώς. |
| **TLG:** browsing by author, work and citation | partial | Author → work → passages (20 at a time), previous/next and `?id=` links. Missing: citation jump ("Sappho 31.7"), TLG author and work numbers, and clean author names (see backend item 5). | A canonical author and work table with TLG IDs, a citation box that resolves "Sappho 31.7" or "Alc. 347.1" to a passage and line, and line-level anchors in the URL (`&line=7`). |

### Next steps for semantic search and concept diachrony

Meaning ("theme") search already covers 116,191 of 116,428 passages. Three problems hold it back:

- Long fragments dominate the results (backend item 2).
- Several editions of the same text crowd them out (item 3).
- English queries reach through translations to passages without the concept (item 4).

Suggested order of work:

1. Group results by work and citation, and split long passages into smaller pieces before the meaning search.
2. Build the token-level lemma index (this also closes the gaps in Perseus lemma search, TLG lemmatised search
   and Logeion frequency).
3. Add concordance and collocation views by lemma.
4. Draw concept diachrony as meaning-search hits and lemma collocates per author date, using the existing
   `author_chronology` date claims.

## Deployment record

- Commits on `lyric-corpus-reader`:
  - `31775c9`: reader UX audit fixes.
  - `5003aa2`: parse-label spacing in the word panel.
  - This document is committed separately.
- Cache-bust tags: `css/reader.css`, `css/touch-selection.css` and `js/passage-analysis.js` are
  `?v=ux-audit-20261008`; `js/reader.js` is `?v=ux-audit-20261008b`.
- Production before this audit: `dpl_FDqMcVTLYmNe3t6tnMa51xx9y9ik`,
  https://project-melos-ekqzb9vtm-nacryos-projects.vercel.app (created 2026-10-08 01:16 PDT).
- First deploy: `dpl_Hvi6Mkv8Tf6iP1a8SLXc3VjjXLVG` (https://project-melos-ip3yw1p08-nacryos-projects.vercel.app).
- Current production: `dpl_J6zECAQZawBs8PtzQ2wpUWRb6tWr`,
  https://project-melos-5bxvrw61c-nacryos-projects.vercel.app, served at https://greeklyric.com.
- Command used: `vercel deploy --prod --yes --build-env MELOS_READER_ONLY=1`.
- **Rollback:** `vercel promote https://project-melos-ekqzb9vtm-nacryos-projects.vercel.app --yes` (or
  `vercel rollback https://project-melos-ekqzb9vtm-nacryos-projects.vercel.app`). The backend is unaffected.
