# Adjudication of transcription disputes (Campbell GLP)

Base dir: `C:\Users\alvin\melos\.claude\worktrees\agent-a6e935236d3ca4e7c\runtime\campbell-full\`
Read `PROTOCOL.md` first: its character conventions are binding.

Two independent transcribers (A and B) transcribed every page. Your packet `adjudication\in_<NAME>.json` lists
disputes, each with `dispute_id`, `key` (POET|fragment number), `pdf_pages`, the A lines and B lines and their
margin labels, plus either their notes (`A_B_differ`) or reasons (`agreed_but_flagged`: a cross-check against another
edition found a breathing/accent/diaeresis/iota-subscript difference, or both transcribers were unsure).

For each dispute, LOOK AT THE PAGE IMAGE and decide exactly what Campbell prints:
- Locate the line on `pages\pNNN.png`; make tight crops of the words in question at 4-10x with PIL (LANCZOS) into
  `zoom\<NAME>_*.png` and view them. Compare with the same glyph elsewhere on the page (e.g. a certain rough
  breathing, a certain grave, a certain iota subscript) before deciding. Rough breathing is c-shaped (opens right),
  smooth is comma-shaped (opens left). A breathing+grave and a circumflex can look alike: compare shapes.
- Underdot vs iota subscript: an underdot is a round dot below the baseline centred under the letter; an iota
  subscript is a small vertical/hooked stroke. Mark underdots only where a dot is really printed; scan specks are
  irregular, off-centre or also appear in blank areas.
- The other edition is NOT evidence for Campbell's reading. Decide from the image only. If the image genuinely
  cannot decide (damaged/too small), choose the more probable printed reading AND set `uncertain: true` with a short
  description; that note will be stored with the poem.
- Speaker labels printed in the margin (ΧΟ., ΑΙΓ.) and part labels like (a)/(b) are NOT part of the line text: put
  them in `strophe_labels` (one entry per final line, "" if none). Digamma prints as F: encode Ϝ / ϝ.
- If A and B disagree on line segmentation (one line vs two, an indented turnover line), follow the printed layout:
  one output line per printed line.
- Margin line numbers: give the final `labels` (one per final line) as printed.

Output `adjudication\out_<NAME>.json` (UTF-8, ensure_ascii False, written by a Python script file in `tmp\` named
with your NAME prefix, never via a shell heredoc):
```json
{"decisions": [
  {"dispute_id": 12, "final_lines": ["..."], "labels": ["", "5"], "strophe_labels": ["", ""],
   "basis": "8x crop: rough breathing c-shaped on ἧδε, same as ἧς in l.3", "uncertain": false, "uncertain_note": ""}
]}
```
`final_lines` replaces the A lines in `a_range` (same count or different, as printed). Every dispute_id in your packet
must get exactly one decision. Reply with counts only (decisions, how many sided with A / B / neither, uncertain).
