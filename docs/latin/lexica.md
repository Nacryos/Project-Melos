# The further Latin dictionaries (2026-11-16)

Seven dictionaries beside Lewis & Short, each taken as ready-made structured text, each a local store read by one
reader. Owner's ruling: private use; the built stores stay local (`data/lexica/` is gitignored); only the small
manifests under `data/open/latin/lexica/` are committed. Forcellini and the Thesaurus Linguae Latinae are built by
two sibling scripts to the same contract and are read by the same reader; the Oxford Latin Dictionary is in
copyright and was not fetched.

## What was built

| file | what |
|---|---|
| `scripts/ingest_lexica_la.py` | download (once; raw files are kept) and build: `ingest_lexica_la.py [names]` |
| `data/lexica/lex_<name>.sqlite` | one store per dictionary (local) |
| `data/open/latin/lexica/<name>.json` | manifest: source, licence verbatim, counts, sha256 of the raw file |
| `backend/latin_lexica.py` | `available()`, `lookup(word, dicts=None, limit=3)`, `english(q, limit=20)`, `search(q, dicts=None, limit=10)`, `pages(q, ...)`, `gloss(word)`, `query(...)`; nothing raises, a missing file is an empty answer |
| `scripts/la_lex.py` | `la_lex.py` (the stores), `la_lex.py <word>`, `--en "<english>"`, `--search "<words>"`, `--dict a,b`, `--full`, `--json` |
| `GET /api/la/lexica?q= \| en= \| search= &dict=&limit=&full=` | the same, for the owner and the agent; agent tool `la_lexica` |
| `tests/test_lexica_la.py` | 11 tests; those on the real stores skip when a store is absent |

No Python package was installed: StarDict archives (`.ifo`, `.idx`, `.dict.dz`, `.syn`) are read with the standard
library.

## The dictionaries

| store | work | direction | entries | text | source | licence found |
|---|---|---|---|---|---|---|
| `smith_hall` | W. Smith and T. D. Hall, *A Copious and Critical English-Latin Dictionary* (1871) | en-la | 30,247 | 10.3 M characters | github.com/latin-dict/SmithHall1871, release v0.2 | "Creative Commons Legal Code CC0 1.0 Universal" (repository LICENSE) |
| `riddle_arnold` | J. E. Riddle and T. K. Arnold, *A Copious and Critical English-Latin Lexicon* (1864) | en-la | 32,432 | 8.5 M | github.com/latin-dict/Riddle1864, v1.0 | none stated in the keeper's repository; the book is of 1864 |
| `lewis_elementary` | C. T. Lewis, *An Elementary Latin Dictionary* (1890) | la-en | 17,582 | 4.7 M | github.com/latin-dict/Lewis1890, v1.1 (from Perseus) | "Creative Commons Legal Code Attribution-ShareAlike 3.0 Unported" |
| `doederlein` | L. Döderlein, *Hand-book of Latin Synonymes*, tr. H. H. Arnold (1874) | la-en | 556 groups, 2,894 further headwords | 0.4 M | github.com/latin-dict/Doederlein1874, v1.1 | "Creative Commons Legal Code CC0 1.0 Universal" |
| `georges_de_la` | K. E. Georges, *Kleines deutsch-lateinisches Handwörterbuch* (1910) | de-la | 27,043 | 8.0 M | github.com/latin-dict/Georges1910, v1.0 | "This is free and unencumbered software released into the public domain." (Unlicense) |
| `georges` | K. E. Georges, *Ausführliches lateinisch-deutsches Handwörterbuch*, 8th ed. (1913-1918) | la-de | 54,782 | 20.9 M | tovotu.de/data/stardict/georges_lat-de.zip, linked from tuxor1337.frama.io/firedict/dictionaries.html | the keeper's list: "Public Domain (copyright expired, published 1913)"; the text was converted from zeno.org, which states its own terms for its edition |
| `gaffiot` | F. Gaffiot, *Dictionnaire latin-français* (1934), revised as Gaffiot 2016 (Gréco, De Wilde, Maréchal, Okubo) | la-fr | 72,163 | 11.9 M | github.com/Gaffiot/digital-gaffiot-json (`gaffiot.json`) | "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International"; the README excludes Wikimedia projects |

The whole licence statement of each is in its manifest and in the store's `meta` table. Two need care: Gaffiot 2016
is NC-ND, so the store is for private local use and nothing derived from it may be published; Riddle-Arnold carries
no statement at all from its keeper. Raw files: `data/raw/latin/lexica/<name>/`, 56 MiB together, each fetch logged
in `data/raw/latin/fetch-log.jsonl` (User-Agent `Melos/1.0 (+https://greeklyric.com)`, 1.1 s between requests).

Built by the sibling scripts and read here:

- `forcellini` (la-la; `scripts/ingest_forcellini_la.py`, `docs/latin/lexica-forcellini.md`): 46,983 entries cut
  from the archive.org OCR of the five volumes; noisy text, about 27 very common words missing, 82.7 % of Catullus's
  lemmas (proper names aside) covered.
- `tll` (la-la; `scripts/ingest_tll_la.py`, `docs/latin/lexica-tll.md`): the open-access Thesaurus, 60 PDFs, 16,163
  pages; A-M, O, P whole, N to *netura*, R to *resurgo*, Onomasticon C-D; 91,750 headwords from the PDFs' bookmarks
  (86 % placed on their line), every page in full text. CC BY-NC-ND and no upload to a public site: local only.
  The same script takes a dictionary PDF the owner supplies (`--pdf FILE --name old`).

## The store contract

`entries(id, headword, folded, text)` with an index on `folded`; `meta(key, value)` with name, title, language,
direction, source_url, licence, retrieved, n_entries. Latin headwords fold as `backend/latin_dictionary.fold`
(lowercase, no quantities, j -> i, v -> u); English and German headwords fold to lowercase. Mine add
`forms(folded, entry_id)` for the alternative headwords of an entry (each member of a Döderlein group; StarDict
synonyms) and `entries_fts` (FTS5 over headword and text, diacritics removed). A store may instead hold
`pages(volume, col | col_from, text)`; the reader takes what it finds. The key of a store everywhere is its file
name (`lex_tll_partial.sqlite` is `tll_partial`); any `lex_*.sqlite` in the directory is listed, a builder's scratch
file included.

## How a lookup runs

- **A Latin word** (`lookup`, `la_lex.py <word>`, `q=`): tried as spelled, then under the lemmas the lemma index
  gives the form, then under the headwords Lewis & Short resolves it to; the first key that finds an entry wins and
  is named in `how` (`basia` -> "form of basium"). Unasked, only the Latin-headword stores answer; `--dict
  smith_hall` asks an English-Latin store for its sense fragments (below). 320 characters of each entry unless
  `--full`.
- **English** (`english`, `--en`, `en=`): the article under the English headword in Smith & Hall and Riddle-Arnold
  (as typed, without "to", unpluralised), then articles that mention the word. Smith & Hall prints quantities on its
  Latin answers and on nothing else, so `latin` lists the answers by their marks, with the clause each stands in.
- **Full text** (`search`, `--search`): every word of the query, any order, FTS5 `bm25` order; `pages` does the same
  over stores that keep pages.
- **`gloss(word)`**: one line each from Georges and Gaffiot.

## Wiring

- `latin_dictionary.reverse()` has a third source. Each row's `sources` names those that found it: `lewis-short`,
  `catullus-interlinear`, `smith-hall` (`LS`, `Cat`, `SH` in `la_dict.py --en`), and `smith_hall` gives the word as
  printed and its clause. Words two or three sources give come first; then Catullus's own; then Smith & Hall's other
  answers in its order; then Lewis & Short's. A Catullan co-occurrence too weak to stand alone is admitted when
  Smith & Hall gives the same word (*suavium*, *salsus*). A form that is no headword goes to its lemma (*amores* ->
  *amor*). Without the store, `reverse()` is as before.
- L14 is unchanged in verdict and detail. A row that warns or has no entry gains `gloss` (Georges, Gaffiot) in the
  evidence; a test holds verdict, detail and every other field equal with and without it.
- Route `/api/la/lexica`, agent tool `la_lexica`, and a paragraph each in `critic-brief.md`,
  `composing-hendecasyllables.md` and the skill.

## Samples (2026-11-16)

| query | answer |
|---|---|
| `venustus` | Georges "anmutig, reizend, lieblich"; Gaffiot "plein de charme, de grâce, d'élégance : Cic. Br. 203 ... Catul. 89, 2 ; 31, 12"; Lewis "charming, pleasing, winning, agreeable, beautiful"; Döderlein's group *formosus, pulcher, venustus* |
| `lepidus` | Georges "niedlich, zierlich, allerliebst"; Gaffiot "plaisant, agréable, charmant, élégant : Pl. Capt. 956"; Lewis "pleasant, agreeable, charming, fine, elegant, neat" |
| `basium` | Georges "ein zärtlicher Kuß"; Gaffiot "baiser : Catul. 5, 7"; Lewis "a kiss: da mi basia mille, Ct."; Döderlein "Osculum is a friendly; suavium, a tender; basium, an ardent kiss." |
| en `charming` | Smith & Hall (adj.): *amoenus* (esp. to the eye), *bellus*, *dulcis*, *suavis*, *lepidus*, *venustus*, *gratus*; Riddle-Arnold: *venustus* (properly of persons), *gratus*, *amoenus*, *lepidus*, *suavissimus* |
| en `darling` | Smith & Hall: *suavis*, *mellitus*, *mellitulus*, *deliciae* ("my mistress's d. (a sparrow), deliciae meae puellae, Cat."), *deliciolae*; Riddle-Arnold: *deliciae; amores* |
| en `sweetheart` | Smith & Hall: *amores* ("suos amores tenens in gremio, Cat. 45, 1"), *deliciae*, *animus* (Plaut.); Riddle-Arnold: *dilecta*, *amica* (in a dishonorable sense) |

`reverse("charming")` now opens *venustus* (LS+Cat+SH, Catullus 6), *lepidus* (LS+Cat+SH, 4), *lepor* (LS+Cat),
*bellus* (LS+SH, 14); `reverse("kiss")`: *basium*, *basio* (all three), *suavium* (Cat+SH), *suavior*, *osculor*,
*osculum* (LS+SH).

## Limits and what failed

- **Smith & Hall's sense fragments.** The StarDict conversion makes 2,531 "entries" out of numbered senses
  ("2. venustus", "3. lepidus"), each the fragment of a larger article. They do no harm to English lookups and give
  a rough reverse index (`la_lex.py venustus --dict smith_hall`), but they are not articles.
- **Latin answers by quantity marks.** A Latin word Smith & Hall prints without a mark (*mappa*, *bellus*) is taken
  only when it follows a sense number and is a Lewis & Short headword; a marked word inside an example phrase
  (*bonum*, *res*) can be listed as if it were an answer. Riddle-Arnold prints no quantities, so its Latin is not
  picked out: read the article.
- **Gaffiot's homographs** keep the number in the headword ("1 vĕnustus"); 6,884 entries. The text is the komarov
  TeX with the macros stripped; citations are broken over lines.
- **Georges 1913** comes through a third party's conversion of zeno.org's text; its licence rests on the keeper's
  statement. The index gave 64 alternative forms only, so sub-headwords inside an
  article are found by `--search`, not by lookup.
- **Döderlein** is 556 synonym groups, not a dictionary: a word outside a group has no entry.
- **Logeion**: one web search (2026-11-16) found no published bulk data, only the reading interface; nothing was
  taken from it. It shows Lewis & Short and Gaffiot 2016 among others, which are here already.
- **Not ingested**: Du Cange and other medieval dictionaries (out of scope); the Oxford Latin Dictionary (in
  copyright; the owner will supply it); Georges's larger German-Latin dictionary (the latin-dict releases hold the *Kleines* only; no other
  source was looked for).
- German and French glosses are not translated; the critic reads them as they stand.
