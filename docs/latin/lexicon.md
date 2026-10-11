# Latin quantity lexicon (`data/scansion/quantities_la.sqlite`)

Built 2026-10-11 02:56 UTC by `scripts/scansion_build_lexicon_la.py` from the raw files under `data/raw/latin/` (sha256 and
fetch times in `data/raw/latin/fetch-log.jsonl`; the sqlite is not in git, its manifest `data/scansion/quantities_la.manifest.json`
is). Same table as the Greek lexicon (`q(key, akey, source, marks, lemmas)`); the key is `latin.key` (lower case, u for v,
i for j, no marks). Read by `backend/scansion/lexicon_la.py`.

| Source | Rows | What | Codes | Licence (survey rows A) | Upstream |
|---|---|---|---|---|---|
| `winge` | 812,588 | Johan Winge's `macrons.txt`: form, tag, lemma, macronised form | `_` long → L, `^` short → S, `_^` → A (either), unmarked → s (short by the file's convention) | code GPL-3.0; the data is Perseus Morpheus Latin output (CC BY-SA 3.0 US) plus Winge's overrides; server-side use now, redistribution of a derived table only after asking the author | Morpheus Latin, Lewis & Short |
| `wiktionary` | 1,988,775 (892,320 entries) | English Wiktionary's Latin headwords and inflection tables (Kaikki extraction) | macron → L, breve → S, both → A, unmarked → s | CC BY-SA 4.0 + GFDL | editors citing Lewis & Short, Gaffiot, OLD |
| `lewis_short` | 58,160 | Perseus Lewis & Short `<orth>` headwords with breves / macrons | explicit marks only; unmarked → u | CC BY-SA 4.0 | — |

Distinct keys: 1,069,819; sqlite 226 MB. Winge and Wiktionary share an upstream (Morpheus / Lewis & Short), so
agreement between them is not two pieces of evidence; the lookup merges codes per letter and reports one of: `L`, `S`
(explicit), `S` by convention only (`LEX-S-CONV`), `conflict` (readings of both lengths across or within sources,
including the sources' own "either"), `unmarked`, `unknown_word`. Enclitics (-que, -ne, -ue) are split for the lookup
and their own vowel is short. Hypotactic data is never a source (it is the gold).

Coverage and accuracy on Catullus's hendecasyllables: `docs/latin/eval-log.md` (LA2). Audit of 100 random rows per
source against the raw files: pending (LA2 check list).
