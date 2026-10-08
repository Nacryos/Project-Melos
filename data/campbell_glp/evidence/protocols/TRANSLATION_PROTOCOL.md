# Public-domain English comparison translations for Campbell GLP poems

Base dir: `C:\Users\alvin\melos\.claude\worktrees\agent-a6e935236d3ca4e7c\runtime\campbell-full\`

Goal: for each Campbell poem assigned to you, find an existing PUBLIC-DOMAIN English translation of the same poem,
map Campbell's number to the translator's numbering, CHECK THE MATCH BY CONTENT, and transcribe the English exactly
as printed, verified against the scan image. These are shown on greeklyric.com as "English translation · another
edition" comparisons, labelled as not aligned to Campbell's text.

## Hard rules
- Allowed: translations PUBLISHED IN 1930 OR EARLIER (public domain in the US). Chiefly J. M. Edmonds,
  *Lyra Graeca* I (1922), II (1924), III (1927), Loeb. Others pre-1930 if needed (e.g. R. C. Jebb's *Bacchylides*
  1905 prose; J. Banks 1856 Bohn prose Theognis; H. T. Wharton's *Sappho*; B. Perrin's Plutarch 1914; F. G. Kenyon's
  Aristotle *Constitution of Athens* 1891/1920; C. D. Yonge's Athenaeus 1854; R. D. Hicks's Diogenes Laertius 1925).
- FORBIDDEN: Campbell's own Loeb *Greek Lyric* (1982-93), Edmonds' *Elegy and Iambus* (1931), West, Lattimore,
  Davenport, Svarlien, Miller, Rayor, Poochigian, any post-1930 translation, any website translation without a
  verifiable pre-1930 print source, and ANY translation you write yourself. No paraphrase, no filling gaps,
  no modernising spelling, no fixing the translator's text.
- If no PD translation of a poem can be found and verified, record it under `gaps` with the reason. Never invent.
- Match by content: compare the translator's Greek (facing page) and English with Campbell's Greek (given to you in
  `inventory.json`, field `greek_lines_pass_A`). Note extent differences (e.g. Edmonds prints extra/fewer lines,
  different supplements, or splits the fragment) in `coverage_note`. A partial overlap is acceptable if clearly noted;
  a different poem is not.
- Transcribe the English verbatim from the page image, including the translator's punctuation and spelling. Keep
  footnote reference marks as printed (¹ ² ³) but do NOT include the footnotes themselves. Keep editorial brackets the
  translator prints. Use the line breaks of the printed page (prose translations: join lines into paragraphs, removing
  end-of-line hyphenation only where a word is split by the typesetter's line break).
- Exclude the translator's introductory testimonia/context sentences (e.g. "Athenaeus, quoting ...: ") unless they are
  part of the translated poem; record the citation separately.

## Sources and tools
- Lyra Graeca page OCR (uncorrected, for searching only): `lyra-ocr\<item>.txt` (one `===== LEAF n =====` block per leaf,
  n is 0-based) for items `lyragraecabeingr01edmouoft` (vol. I, 1922), `lyragraecavol20002jmed` (vol. II, 1924),
  `lyragraecabeingr03edmouoft` (vol. III, 1927). Leaf n (0-based) = IIIF image number n+1 (`scan_leaf` = n+1).
- Download a scan image to check: `python tmp\fetch_leaf.py <IA item> <scan_leaf>` (saves `leaves\<item>\leaf-NNNN.jpg`,
  prints its sha256 and IIIF URL). Then view it with the Read tool, cropping with PIL if needed. EVERY English text you
  output must be checked word by word against such an image, not just copied from OCR.
- Other IA items: use `python tmp\ia_search.py "<query>"` to find identifiers, and the IA djvu text at
  `https://archive.org/download/<item>/<item>_djvu.txt` (fetch with Python requests) to locate pages; verify on images.
  Check the item's publication year on its title page image (must be <= 1930).
- Name your scripts with your agent prefix (given in your prompt) in `tmp\`; never overwrite others' files.

## Output
Write `translations\<PREFIX>.json` (UTF-8, ensure_ascii False, via a Python script file, never a shell heredoc):
```json
{"items": [
 {"campbell_id": "campbell-glp:sappho:1",
  "translator": "J. M. Edmonds",
  "edition": "Lyra Graeca, vol. I (1922), Loeb Classical Library 28",
  "citation": "Sappho, Edmonds fragment 1",
  "translator_number": "1",
  "source_item": "lyragraecabeingr01edmouoft",
  "source_url": "https://archive.org/details/lyragraecabeingr01edmouoft",
  "publication_year": 1922,
  "english_pages": [{"scan_leaf": 207, "printed_page": "183", "sha256": "...", "iiif_url": "..."}],
  "greek_pages": [{"scan_leaf": 206, "printed_page": "182", "sha256": "...", "iiif_url": "..."}],
  "text": "English exactly as printed ...",
  "coverage_note": "Edmonds' text and Campbell's agree in extent ... / differences ...",
  "match_evidence": "Edmonds' Greek begins ποικιλόθρον’ ἀθάνατ’ Ἀφρόδιτα ... same as Campbell line 1; ...",
  "verified_against_image": true}
 ],
 "gaps": [{"campbell_id": "...", "reason": "searched X, Y; no pre-1930 English translation found"}]}
```
Reply at the end with counts only (items, gaps) and any doubtful matches. Do not paste the translations.
