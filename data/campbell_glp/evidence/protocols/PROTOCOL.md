# Campbell GLP transcription protocol (diplomatic, image-grounded)

Source: David A. Campbell, *Greek Lyric Poetry* (1967), scanned PDF. Text section = PDF pages 33-167
(printed pages 1-135; printed page = PDF page - 32). The PDF text layer is corrupt OCR: DO NOT use it.
Work ONLY from the page images.

Base dir: `C:\Users\alvin\melos\.claude\worktrees\agent-a6e935236d3ca4e7c\runtime\campbell-full\`
- `pages\pNNN.png` - full page at scan resolution (use for layout, ordering, margin numbers).
- `halves\pNNN_top.png`, `halves\pNNN_bottom.png` - the same page upscaled 2x, top 56% and bottom 56%
  (they OVERLAP by ~12% in the middle: do not transcribe the overlap twice). Use these for every glyph.
- You may make tighter zoomed crops yourself with Python/PIL into `zoom\` (e.g. 3-4x on a single line;
  name files with your pass letter and page, e.g. `zoom\A_p050_l3.png`) whenever a diacritic, underdot or
  bracket is unclear. Do this generously.

## What to transcribe
Everything Campbell prints as the poem text, in reading order, line by line:
- Poet headings (e.g. ARCHILOCHUS) -> item type `poet_heading`.
- Fragment headings, printed as a number in parentheses, e.g. `(5A)`, `(53-68)`, `(887)`, `(1)`. Record the
  number exactly as printed without parentheses (`5A`, `53-68`). Small-caps letters as capitals (`5A`).
  Also record any title printed above a poem (e.g. a Bacchylides ode title in Greek capitals) in `title`, and
  strophic labels printed in the text column or margin (`στρ. α´`, `ἀντ.`, `ἐπ.`) in the line's `strophe_label`.
- Metrical schemes (rows of metrical signs with line references at right) -> put them in `metre_lines` only,
  roughly as printed (they are metadata; not part of the poem text; exactness not required).
- Verse lines -> `lines` with `kind: "verse"`.
- Greek or Latin prose that Campbell prints in the text column as part of the fragment (e.g. the ancient source's
  sentence introducing or interrupting the quotation) -> `kind: "prose"`.
- Lines consisting only of lacuna dots (e.g. `. . . . .`) -> `kind: "verse"` with that text.
- Printed notes such as `desunt iv versus` -> `kind: "note"`.
- Stanza/strophe gaps (extra vertical white space between groups of lines) -> do NOT insert blank lines;
  instead set `"stanza_break_before": true` on the first line after the gap.
- Indented lines: set `"indent": true` (layout metadata only).

## What NOT to transcribe
- The apparatus criticus (smaller-font notes below the text starting with a line number and sigla,
  e.g. `1 εἰμὶ δ’ ἐγὼ Ath. ...`, `52 μούναρχοι δὲ AO`, `44 suppl. Kenyon`). Skip it entirely.
- Running heads (`GREEK LYRIC POETRY`, `SCOLIA`, ...), page numbers.

## Character conventions (strict)
- Unicode NFC precomposed polytonic Greek. Final sigma ς at word end.
- Elision / apostrophe and smooth-breathing-like mark after elided word: U+2019 `’`.
  Quotation marks if printed: U+2018 `‘` opening and U+2019 `’` closing.
- Raised dot (ano teleia): U+00B7 `·`. Greek question mark: `;` (U+003B).
- Underdotted (uncertain) letter: the letter (with its accents) followed by combining U+0323. Mark exactly the
  letters that carry a dot in the image. Look hard: these dots are small.
- Square brackets `[ ]`, angle brackets as U+27E8 `⟨` / U+27E9 `⟩`, braces `{ }`, cruces `†`, as printed.
- Lacuna dots: one `.` per printed dot, separated by single spaces, e.g. `. . .` (count the dots!).
  Dots adjacent to letters/brackets as printed, e.g. `[. . .]`, `ἄ . . [`.
- A wide empty space inside brackets (lacuna of unspecified length shown as blank space): write 10 spaces.
- Iota subscript as printed (ᾳ ῃ ῳ). Diaeresis (ϊ ϋ) as printed. Breathing and accent on every word as printed;
  capitals with breathing/accent as single precomposed characters (`Ἀ`, `Ὦ`). Do NOT normalise spelling,
  dialect, or accentuation to any other edition. If Campbell prints an unusual form, keep it.
- Margin line numbers (printed at right) go into `label` of the line they stand beside, as printed
  (`5`, `10`, `35`). Otherwise `label` is "".
- Hyphenated word broken across lines: keep the hyphen and the break exactly as printed.

## Output
For each page write `out\<PASS>\pNNN.json` (UTF-8, `ensure_ascii=False`) of the form:
```json
{"pdf_page": 33, "printed_page": "1",
 "items": [
  {"type": "poet_heading", "text": "ARCHILOCHUS"},
  {"type": "fragment", "number": "1", "continued_from_previous_page": false,
   "title": null, "metre_lines": [],
   "lines": [{"label": "", "kind": "verse", "indent": false, "stanza_break_before": false, "strophe_label": "",
              "text": "εἰμὶ δ’ ἐγὼ θεράπων μὲν Ἐνυαλίοιο ἄνακτος"}],
   "continues_on_next_page": false,
   "uncertain": [{"line_index": 0, "what": "describe any glyph you could not resolve"}]}
 ]}
```
If a page begins with the continuation of a fragment from the previous page, the first item is a `fragment`
with `"number": null` and `"continued_from_previous_page": true`.
Write the files with a Python script file (json.dump, ensure_ascii=False); never through a shell heredoc
(heredocs mangle backslashes on this machine). Write the Python script with your file-writing tool into
`runtime\campbell-full\tmp\` and run it.

Before finishing each page, re-read every line against the 2x crop one more time, word by word, checking:
breathings, accents (acute/grave/circumflex), iota subscripts, diaereses, underdots, brackets, dot counts,
punctuation, margin numbers. Report in `uncertain` anything you are not sure of rather than guessing silently.
Do not consult any other edition or your memory of the text to "fix" what is printed; transcribe the image.
