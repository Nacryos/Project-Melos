# Licensed data used behind the scenes (register)

Owner's addendum (2026-10-10, `~/work/latin-composer-brief.md`): licensed data may be used where it improves the Latin
scansion and parser elements (quantity lexica, annotated scansions, treebanks, lemmatiser training data) under the
standing Melos licensed-data policy: behind-the-scenes use only (signals, training, calibration), stored under
`data/private/`, licence and source recorded per item, at most 30-word cited excerpts in any UI, full display only
with permission; no pirate or shadow-library sources. Coordinator rulings 2026-10-11: LASLA yes (lemma gold and recorded
lemmas, server-side, no redistribution); Winge's macron table yes (server-side now; an author email prepared, not sent).

| Item | Where | Licence | Source and hash | Use | UI exposure |
|---|---|---|---|---|---|
| LASLA v1.0.1, Catullus and Horace (12 CoNLL-UP files, 17.4 MB) | `data/private/lasla/` (manifest.json with sha256 per file) | CC BY-NC-SA 4.0 | github.com/CIRCSE/LASLA via survey C fetch | lemma gold for the lemmatiser bake-off; recorded lemmas in the Latin lemma index | none (counts and lemma ids only) |
| Johan Winge, `macrons.txt` (812,588 rows; 325,380 distinct after dedupe) | `data/raw/latin/winge/` (gitignored); rows in `data/scansion/quantities_la.sqlite` source `winge` | code GPL-3.0; data from Perseus Morpheus Latin (CC BY-SA 3.0 US) plus the author's overrides, no data licence stated | github.com/Alatius/latin-macronizer, sha256 b22950c26ad2… | per-form vowel quantities (scanner signal) | none (the scanner shows p_long and a rule, never the table) |
| Hypotactic Latin (Chamberlain) | `data/open/latin/hypotactic/` | CC BY 4.0 (open; listed for completeness) | hypotactic.com/latin, sha256 in its manifest | evaluation gold only | none |

Draft of the author email for Winge (not sent; the owner decides): `docs/latin/drafts/winge-email.md`.
Last updated 2026-10-10 20:21 PDT.
