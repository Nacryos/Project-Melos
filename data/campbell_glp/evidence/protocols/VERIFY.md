# Final proofreading pass (character-by-character verification)

Base dir: `C:\Users\alvin\melos\.claude\worktrees\agent-a6e935236d3ca4e7c\runtime\campbell-full\`
Conventions: read `PROTOCOL.md` (character conventions) and `ADJUDICATION.md` (how to tell rough/smooth breathing,
breathing+grave vs circumflex, underdot vs iota subscript, specks) first. Those rules are binding.

For each of your pages, `proof\pNNN.json` lists every final transcribed line on that page (poem id, line index,
margin label, kind, text). Your job is to PROOFREAD it against the page image `pages\pNNN.png`, character by
character: every letter, breathing, accent, iota subscript, diaeresis, underdot, bracket, lacuna dot (count them),
punctuation mark, elision mark, margin number, and that no printed text line is missing or extra (apparatus,
running heads and page numbers are intentionally excluded; metrical schemes are excluded).

Work line by line: crop each printed line at 3-4x (PIL LANCZOS) into `zoom\<NAME>_*.png`, view it, and compare it with
the proof text word by word. Zoom to 8x+ on any diacritic you are not certain of. Assume nothing is right.

Output `verify\<NAME>.json` (via a Python script file in `tmp\` prefixed with your NAME; never a shell heredoc):
```json
{"pages": [33, 34], "lines_checked": 57,
 "corrections": [{"poem_id": "...", "line_index": 3, "pdf_page": 34, "current": "...", "corrected": "...",
                  "what": "ἧ -> ἣ: compact arch = breathing+grave", "confidence": "high|medium"}],
 "missing_or_extra": [{"pdf_page": 34, "what": "..."}],
 "label_fixes": [{"poem_id": "...", "line_index": 3, "current": "", "corrected": "5"}]}
```
Only report a correction when the image clearly shows something different (confidence high) or probably different
(medium). Do not report differences from other editions or "expected" Greek. Reply with counts only.
