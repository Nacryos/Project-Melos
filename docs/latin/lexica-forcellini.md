# Forcellini, *Lexicon Totius Latinitatis* (local store)

Latin-Latin dictionary for the verse-composition checker. Built by `scripts/ingest_forcellini_la.py` into
`data/lexica/lex_forcellini.sqlite` (gitignored, local only). The committed record is
`data/open/latin/lexica/forcellini.json`.

## Source chosen, and why

The store is cut from the archive.org OCR text of the five printed volumes (Forcellini, Furlanetto, Corradini,
Perin; Padua, Typis Seminarii):

| archive.org item | volume | letters | raw text (bytes) |
|---|---|---|---|
| `forcellini2` | I | A-C | 12,545,831 |
| `forcellini3` | II | D-K | 12,748,374 |
| `forcellini4` | III | L-Q | 12,736,010 |
| `5forcellini` | IVa | R-S | 7,790,470 |
| `forcellini6` | IVb | T-Z | 4,892,717 |

Ten requests in all (five item-metadata files, five `_djvu.txt` files), each logged in
`data/raw/latin/fetch-log.jsonl`; raw files are in `data/raw/latin/lexica/forcellini/`.

Other sources looked at:

- **lexica.linguax.com (`forc2.php`)**, the corrected electronic text. Refused: `robots.txt` says
  `User-agent: *` / `Disallow: /`, and `forc2.php` answers HTTP 511 with a proof-of-work / CAPTCHA page.
  Not worked around.
- **GitHub `latin-dict/Forcellini`**: only a GoldenDict wrapper that calls linguax.com; holds no text.
- **LiLa, CLARIN, Zenodo**: no downloadable Forcellini text found.
- **Brepols Database of Latin Dictionaries**: subscription only.

So the only openly reachable text is the archive.org OCR. It is a bulk download; nothing was scraped page by page.

## Licence

archive.org item metadata, `licenseurl`: `http://creativecommons.org/publicdomain/mark/1.0/` (Public Domain
Mark 1.0). The items carry no other statement.

## What the store holds

- `entries(id, headword, folded, text)`, index on `folded`; `meta(key, value)`; and an extra table
  `source(entry_id, volume, seq, printed, repaired)` that records the headword as the OCR printed it and whether it
  was repaired.
- 46,983 entries, 45,087 distinct folded headwords, 48.3 million characters of text.
- Per volume: I 10,954; II 12,337; III 11,848; IVa 7,513; IVb 4,331.
- 6,181 headwords were repaired: the OCR's reading was unknown to Lewis & Short and to the lemma index, and exactly
  one known lemma in the right alphabetical place differed from it only by letters the OCR confuses
  (`VENUSTATOS` -> `uenustatus`, `SEPE` -> `saepe`, `PCENA` -> `poena`).
- 32,599 of Lewis & Short's 49,416 headwords have a Forcellini entry.

## Coverage of the poets' lemmas

| | lemmas | with an entry | share | share of occurrences |
|---|---|---|---|---|
| Catullus, all lemmas | 3,156 | 2,450 | 77.6% | 85.0% |
| Catullus, without proper names | 2,881 | 2,383 | 82.7% | 87.4% |
| Horace, all lemmas | 3,942 | 2,932 | 74.4% | 86.3% |
| Horace, without proper names | 3,436 | 2,813 | 81.9% | 88.1% |

Virgil could not be checked: the lemma index holds only Catullus and Horace.

`venustus` (2,490 characters), `lepidus` (2,614), `basium` (1,015) and `passer` (2,098) each have one entry.

## Known defects

1. **The text is uncorrected OCR.** Greek is garbled; letters are misread (u/n, s/a, l/i, e.g. `Catuli.` for
   `Catull.`, `sxpe` for `saepe`); citations are not marked up.
2. **Merged columns.** In 5 to 13% of each volume's characters the OCR ran the two or three columns of a page
   together, so some entries carry text from the neighbouring column.
3. **Frequent words still missing**, because their opening line is too damaged to recognise: nec, o, sui, facio,
   atque, fero, unus, neque, homo, nihil, sic, dies, modo, iucundus, dea, maestus, furor, fugio, cura, cupio, uiuo,
   ita, sidus, saeuus, quaero, urbs, laetus, aequor, aetas. Their text is in the store, attached to the end of the
   entry printed before them.
4. **Swallowed entries.** 71 entries are longer than 20,000 characters because they took in the entries that
   follow them.
5. **Short entries.** 4,692 entries are under 40 characters. Most are real cross-references (`MOENIA pro munia.
   V. MUNUS.`); some are false splits.
6. **Wrong headwords.** A minority of the 6,181 repairs picked the wrong lemma (seen: `SIVAN` -> sicani,
   `CONQUINO` -> conquiro, `ABBITO` -> abdite). `domus` currently returns the entry for DUMUS, which the OCR read as
   `DOMUS`; the real DOMUS entry is not cut out. CURA is read as `CORA`.
7. **One-letter headwords** (A, E, O) are not cut out.
8. **No proper names.** The Onomasticon is a separate work and is not in these five volumes; this accounts for most
   of the missing proper names.
9. **Homographs** are separate rows under one folded headword, in printed order, with no numbering.

## Rebuilding

```
.venv/bin/python scripts/ingest_forcellini_la.py              # fetch what is missing, cut, store; adds 0 on a second run
.venv/bin/python scripts/ingest_forcellini_la.py --rebuild    # cut the raw text again from scratch
.venv/bin/python scripts/ingest_forcellini_la.py --lemmas catullus --limit 500
```

Raw files already on disk are not fetched again. The store is rebuilt automatically when the cutting rules change
(`meta.parser`). Headword repair needs `data/lexica/lewis_short_la.sqlite` and `data/lemma_index_la.sqlite`; without
them the entries are cut but not repaired. No extra packages are needed.
