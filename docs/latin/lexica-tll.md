# Thesaurus Linguae Latinae: local lookup store

`data/lexica/lex_tll.sqlite` holds the text of the open-access TLL PDFs, page by page and article by article.
It is built by `scripts/ingest_tll_la.py` from PDFs kept in `data/raw/latin/lexica/tll/`. Both directories are
gitignored: the PDFs and the store stay on this machine. Only `data/open/latin/lexica/tll.json` (sources, licence,
checksums, counts) is committed.

## Source and licence

- Index of the PDFs: <https://thesaurus.badw.de/en/tll-digital/tll-open-access.html>. Files are served from
  `publikationen.badw.de` (record: <https://publikationen.badw.de/en/thesaurus>).
- The index page says: "In consultation with the publisher De Gruyter, we offer here an Open Access PDF version
  (organized by volumes and lemmas) of the previously published volumes A - M and O - P, as well as parts of N and R.
  Access is free of charge."
- The record page says: "Lizenz License : CC BY-NC-ND".
- The first page of each PDF says: "This work is offered to you under a Creative Commons
  Attribution-NonCommercial-NoDerivs CC BY-NC-ND license (explanation here). In addition, you are not allowed to print
  or modify (parts of) this file or to upload it to a public website (no file-sharing). We kindly ask you to respect
  these restrictions. Instead, please refer fellow researchers to our website. Continued access to this version of the
  ThLL depends on your acceptance of these conditions. Please also leave this page and the watermark in the file."

So: private lookup only. The PDFs are kept unmodified; neither they nor the store may be published, and no TLL
text should be shown on the public site. Cite the TLL and send readers to the Thesaurus website.

Robots: `thesaurus.badw.de/robots.txt` disallows nothing; `publikationen.badw.de` has no robots file. No login wall or
CAPTCHA. Fetched 2026-11-16, one request at a time, at least one second apart; every request is in
`data/raw/latin/fetch-log.jsonl`.

## What is in

60 PDFs, 6.38 GB, 16,163 pages.

| Letters | Volumes | State |
|---|---|---|
| A-M | I-VIII | complete |
| N | IX 1, fascicles 1-4 | to *netura* |
| O | IX 2 | complete |
| P | X 1, X 2 | complete |
| R | XI 2, fascicles 1-10 | to *resurgo* |
| Names C, D | Onomasticon II, III | complete |

Not in, because not published or not offered: N after *netura*, Q, R after *resurgo*, S-Z, Onomasticon after D.
So *venustus*, *nox*, *nugae*, *sal*, *tener* and the like are misses.

## Tables

```
pages(id, volume, pdf_page, col_from, col_to, head_from, head_to, text, file)
pages_fts                       -- FTS5 over pages.text, rowid = pages.id
entries(id, headword, folded, text, volume, col_from, col_to, page_from, page_to,
        level, located, n_chars, variant_of)      -- index on folded
meta(key, value)
```

- `pages.pdf_page` counts from 1 inside `pages.file`; `col_from`/`col_to` are the two printed column numbers of the
  page. `head_from`/`head_to` are the running heads as the OCR read them (folded; often misread, use for orientation
  only).
- `entries.folded` is the headword folded as `backend/latin_dictionary.py` folds (lowercase, no diacritics, j to i,
  v to u). `entries.page_from`/`page_to` are `pages.id` values.
- `entries.level`: 1 a headword, 2 a sub-lemma inside an article (*puella* under *puellus*, *lepide* under
  *lepidus*), 3 a pointer to the corrigenda page of the volume (headword ends in `[addenda]`; text is that page).
- `entries.located`: 1 when the headword's own line was found, so `text` starts at the article; 0 when it was not, in
  which case `text` starts at the previous headword on the same page (or the top of the page) and the article is
  somewhere below.
- `entries.text` is cut at 30,000 characters; `n_chars` is the full length (1,409 articles are longer). Read on
  through `pages` from `page_from` to `page_to`.
- `entries.variant_of`: a bookmark with two spellings ("abaeto, abito") gives one row per spelling; the extra rows
  point at the main row and repeat its text.
- `meta` keys: name, title, language, direction, source_url, licence, licence_record, access_note, retrieved,
  text_layer, n_entries, n_entry_rows, n_addenda, n_located, n_pages, letters, ranges, fts_table, built,
  max_entry_chars.

## Looking a word up

```
.venv/bin/python scripts/ingest_tll_la.py --check basium lepidus
```

or in SQL:

```sql
SELECT headword, volume, col_from, col_to, located, n_chars, text
FROM entries WHERE folded = 'lepidus'
ORDER BY volume LIKE 'onom%', level = 3, located DESC, n_chars DESC;

-- no row: the article that precedes the word in the alphabet (deliciae is under "2. delicia")
SELECT e.headword, p.file, p.pdf_page FROM entries e JOIN pages p ON p.id = e.page_from
WHERE e.folded <= 'deliciae' AND e.level = 1 AND e.variant_of IS NULL AND e.volume NOT LIKE 'onom%'
ORDER BY e.folded DESC LIMIT 1;

-- full text
SELECT p.volume, p.col_from, p.file, p.pdf_page FROM pages_fts f JOIN pages p ON p.id = f.rowid
WHERE pages_fts MATCH '"passer deliciae"';
```

The second query must be limited to words inside the published ranges (`meta.ranges` lists each file's first and
last lemma); `lookup()` in the script does this, so *nox* is a miss and not "the last word before it".

Several rows per word are normal: homonyms ("1. dico", "2. dico"), a cross-reference stub beside the real article,
a name in the Onomasticon, an addenda pointer.

## Text layer

Installed for this: `pymupdf` 2.1 (`uv pip install --python .venv/bin/python pymupdf`; it pulled in `pymupdf-layout`,
`pymupdf4llm` and `tabulate`). No OCR was run here.

- Volumes I-VIII, IX 2, X and the Onomasticon are scans. Their text layer is the publisher's own OCR (ABBYY
  FineReader), which the PDF cover page calls uncorrected. Latin running text is readable and searchable; expect
  wrong letters (`foonus` for *bonus*, `-avl` for *-āvī*, `CATVXLO` for *CATVLLO*). Greek is garbage. Vowel length
  marks are lost or misread. Small capitals in author names are often wrong. The sign printed before a major lemma
  comes out as a stray `*`, `«`, `^` or `a` in front of the headword (`alibellus`).
- The fascicles of N (IX 1) and R (XI 2) are born digital: Latin is clean and macrons survive; Greek is still
  garbage (a private font).
- 36 of the 16,163 pages have no text (covers, blanks). No volume lacks a text layer.
- Column numbers were read or filled in from neighbours on 15,933 pages; a running head was read on 15,946.
- Marginal line numbers (5, 10, 15 ...) are removed; a few survive inside lines. Words hyphenated at a line end are
  joined.

## Segmentation

Every PDF but one carries a bookmark for each headword, giving the page. The script finds the headword's line on
that page by matching the bookmark against the OCR text (exact first, then with tolerance for misread letters).
The last R fascicle (`resilio`-`resurgo`) has no bookmarks; its headwords are taken from bold type (147, all placed).

| | headwords | placed on their line |
|---|---|---|
| lexicon, level 1 | 69,674 | 62,586 (90 %) |
| lexicon, sub-lemmata (level 2) | 7,683 | 4,489 (58 %) |
| Onomasticon C, D | 14,393 | 11,566 (80 %) |
| all | 91,750 | 78,641 (86 %) |

Plus 1,748 addenda pointers and 3,119 variant-spelling rows: 96,617 rows in `entries`.

Of the placed level-1 lexicon headwords, 74 % open with the headword letter for letter; the rest were matched
through OCR errors (14 of 14 drawn at random were the right line).

Check on 30 lemmata (`--check` with no words):

- 3 are outside what is published and miss, as they should: *venustus* (V), *nugae* and *nox* (N stops at *netura*).
- Of the other 27, 26 have a row under their folded headword. *deliciae* has none, because the TLL files it under
  "2. delicia"; the alphabetical fallback lands on that article.
- 25 of the 27 start on the headword's line, and all 25 are the right article (read by eye): *lepidus, basium,
  bellus, libellus, passer, ineptus, amo, aqua, bonus, cano, dico, domus, emo, facio, fero, gratia, homo, iocus,
  ludo, mare, mollis, otium, puella, pius, res*.
- *caput* has its row and the right page, but its line was not found (`located = 0`).

## Defects

- 14 % of headwords are not placed on their line; they are mostly names, sub-lemmata printed inside an article and
  one-line cross-references. Their rows still give the right page.
- An article ends where the next placed headword begins. If the next headword was not placed, the text runs to the
  end of that headword's page, so some entries carry the start of their neighbour.
- A sub-lemma's text is also inside its parent's text.
- The bookmark list is the publisher's and, by its own note, may be incomplete; a headword without a bookmark has no
  row and its text sits inside the preceding article.
- 30 files were listed on the index page under a wrong address ("vol. 06.2" for "vol. 06,2"), which returns a record
  page instead of the PDF. The script takes the working link from that record page; the record pages are kept as
  `*.record.html` and both requests are in the fetch log.
- The index page lists XI 2 fascicle 9 with the columns of fascicle 8, so the local file is named
  `tll_11.2.9_col1121-1280_...` although it holds col. 1281-1464. The column numbers in the store come from the
  pages and are right.

## Rebuilding, and other dictionaries

```
.venv/bin/python scripts/ingest_tll_la.py            # fetch what is missing, then build (about a minute for the build)
.venv/bin/python scripts/ingest_tll_la.py --fetch    # resumable; existing files are skipped
.venv/bin/python scripts/ingest_tll_la.py --build
```

A dictionary PDF the owner supplies goes into its own store with the same tables:

```
.venv/bin/python scripts/ingest_tll_la.py --pdf /path/to/file.pdf --name old --title "Oxford Latin Dictionary"
```

This writes `data/lexica/lex_old.sqlite`. `pages` and `pages_fts` are always filled, provided the PDF has a text
layer (the script reports how many pages have none; it does not OCR). `entries` is filled from bookmarks when there
is about one per page or more, otherwise from lines opening in bold type, and only if at least 50 are found and 85 %
run in alphabetical order; otherwise it is left empty. This mode has been tried only on TLL fascicles, not on any
other dictionary. The script fetches nothing in this mode.
