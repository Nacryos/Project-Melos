# Handover: the box session to the Mac coordinator (2026-10-10)

Written on the always-on Linux box ("basecamp") by the Claude session that
has worked in `~/work/Nacryos/Project-Melos` since 2026-09-30. Facts below
were re-verified on 2026-10-09 at 23:46 UTC (16:46 Pacific). Where I describe
something other sessions created, I say so; treat those lines as observations,
not ownership.

## 1. Goal of this build

Project Melos is a source-backed research reader and lexicon for Ancient
Greek lyric (https://greeklyric.com). The box session's job, under the owner's
decisions of 2026-09-30 (`docs/decisions.md`), has been to raise usable
coverage of the fragmentary poets and to make English-language search reach
Greek passages, without weakening provenance:

- admit modern editions and machine-corrected OCR; merge author spellings;
  group identical copies in search; keep verse lines unwrapped on every screen;
- collect new sources (modern-edition texts and, above all, English
  translations linked to Greek passages);
- measure search quality with a judged query set and change ranking only on
  measured gains;
- prepare the next structural step: fine-tuning the bi-encoder on the
  English-to-Greek pairs now in the corpus (the owner's "option 2").

## 2. Current state

**Live site.** Vercel project `nacryos-projects/project-melos` deploys
production on every push to `main`; `/api/*` is rewritten to the Funnel URL
`https://basecamp.taila44c41.ts.net:8443`, which proxies `127.0.0.1:8791` on
this box. Public status at the time of writing: 288,584 passages, 108 merged
authors, mirror grouping on, 116,428 embeddings.

**Repository.** `origin/main` tip `fde4d1c` (2026-10-05). The box checkout is
at that commit, clean. `origin/lyric-corpus-reader` exists and is `main` plus
4 commits (tip `74ee93f`: source-bound passage analysis with morphology syntax
and Jev ranking, plus two docs commits). All of the box session's Sep 30
commits (`65241c5`, `d670d57`, `0d497df`, `e678422`, `e1a99b7`, `70450fe`,
`58cb5cf`, `5629753`) are ancestors of both branches, so the Sep 30 main line
is fully contained in `lyric-corpus-reader`. The owner reports the Mac clone
`~/Projects/melos` is on `lyric-corpus-reader`, 85 commits ahead and unpushed,
carried over from the Windows laptop; only 4 of those are on the remote. The
container currently serving production was built from
`~/melos-u/u-src-fab37bf.tar.gz`; commit `fab37bf` is not on any remote branch,
so **production runs code that is not pushed**, and the pushed `main` is behind
the deployed code. A push to `main` only redeploys the static front end; it
does not change the API.

**Index.** The live `corpus.sqlite` (owned by root, mtime 2026-09-30 16:33
Pacific) was built on the Windows laptop (its manifest paths use backslashes)
with the schema-2 columns (`author_canonical`, `text_key`, `passage_authors`),
so merging and grouping are native. It includes the laptop's own CGL anthology
collection (`p2_cgl_anthology`, 1,032 rows) but none of the box session's
collector outputs (see 4).

## 3. Done, open, pending decisions

### Done on main (2026-09-30)

| Commit | What |
| --- | --- |
| `65241c5` | Author merging (`backend/author_aliases.json`), mirror grouping, `machine_corrected_ocr` quality, modern editions admitted, owner-acceptance helper, in-place schema migration (`scripts/migrate_corpus_schema.py`), verse-fit script (`js/verse-fit.js`), collectors for the Centre for the Greek Language anthology and Eulogikon |
| `d670d57` | Alias table shipped inside the backend package (the data dir is mounted over the image) |
| `0d497df` | Retrieval lab (`scripts/lab_build_eval.py`, `scripts/lab_eval.py`), weighted/extra fusion signals in `backend/retrieval.py`, Edmonds *Elegy and Iambus* collector (`scripts/ingest_p2_perseus_elegy.py`), Wikisource collector parameters |
| `e678422` | Paton Greek Anthology translations from attalus.org (`scripts/ingest_p2_attalus_anthology.py`) |
| `70450fe`, `5629753` | English queries fuse a BM25 bridge over linked English records (`backend/bridges.py`); transliterations stay on the Greek path. Measured: Recall@5 +2, Recall@10 +1, MRR unchanged |
| `58cb5cf` | `docs/retrieval.md` section on the lab findings |

Lab findings (195 judged queries, fixed snapshot, four rounds): Greek-vector
similarity for an English query Recall@10 0.11; hybrid 0.38; hybrid plus BM25
bridge 0.39-0.42; pseudo-relevance feedback adds recall but lowers MRR; small
and large cross-encoder rerankers both lower recall, the large one at 1.3 s
per pair on CPU. Greek phrase, accentless and transliterated fixtures score
1.0. The Sappho commentary is mostly glosses and metre (7 of 57 read as
descriptions). Details: `docs/retrieval.md`, reports in
`~/work/Nacryos/melos-lab/report-*.json`.

### Collected on the box, not yet indexed

Outputs sit in `~/work/Nacryos/Project-Melos/data/processed/` (git-ignored)
with raw artifacts under `data/raw/`. The laptop/Mac builds the index, and the
collectors are on `main`, so the simplest route is to run them there.

| File | Records | Notes |
| --- | ---: | --- |
| `p2_perseus_elegy.jsonl` | 3,460 | Edmonds 1931: 696 Greek fragments, 1,031 testimonia, 1,733 English (1,722 linked). Archive cached at `data/raw/p2_perseus_elegy/hopper-texts-GreekRoman.tar.gz` (125 MB) |
| `p2_attalus_anthology.jsonl` | 2,049 | Paton translations, 2,047 linked to Perseus `tlg7000` rows |
| `p2_eulogikon.jsonl` | 20,950 | 34 poets; edition unspecified by the source; scholia typed commentary |
| `p2_cgl_anthology.jsonl` | 774 | superseded by the laptop's own CGL collection already in the index |
| `p2_wikisource_lyric.jsonl` | 8 | thin |

### Open

- Index the Edmonds and Paton collections (English translations are the
  main lever for English search).
- Fine-tune the bi-encoder (option 2). The training set is being prepared by
  the box session; see `data/training/` on the box and section 6.
- Re-measure the bridge on the current index (the lab snapshot is the Sep 30
  index; the live index has grown by about 1,000 rows).
- The lab's `prf_hits` (feedback) and English-only fusion remain lab-only.

### Owner decisions pending

1. Whether to generate machine English paraphrases for lyric fragments that
   have no translation (most of Sappho, all of Ibycus and Stesichorus),
   labelled as machine text. Cost is small; it is a policy call.
2. Where collectors run from now on (box vs laptop/Mac) and who owns
   acceptance (`scripts/accept_owner_outputs.py` exists for the owner path).
3. Disk: the box is at 97 % (13 GB free). Candidates I would not delete
   without a word: `~/work/Nacryos/melos-lab/data-snapshot` (2.5 GB, Sep 30
   snapshot), the hopper archive (125 MB), 233 exited `melos-api-*`
   containers and 60 images (docker reports 0.9 GB reclaimable containers and
   1.3 GB build cache), the five `corpus-before-*` backups in the data dir
   (about 7.5 GB, root-owned, made by the laptop pipeline).

## 4. Box-only resources

**Checkout.** `~/work/Nacryos/Project-Melos` (clone of `Nacryos/Project-Melos`,
on `main`). Python venv `.venv` (no torch; tests run here). Node 22. `gh` is
authenticated as `Nacryos`. Git identity used for commits: Alvin.

**Production service directory** `/home/alvin/services/melos/` (mounted into
containers):

| Path | Role |
| --- | --- |
| `data/` | the live indexes: `corpus.sqlite`, `evidence.sqlite`, `wiktionary.sqlite`, `embeddings/`, `lexica/`, `claims/`, `metadata/`, `reports/`, `processed/` (only `p2_cgl_anthology.jsonl` and `sappho.jsonl`). Mounted read-only at `/app/data`. Root-owned files arrive from the laptop pipeline. |
| `models/` | HF cache with `BAAI/bge-m3`, mounted read-only at `/models` (`HF_HOME`). |
| `secrets/jev.env` | the TypeSafe/Jev key, mounted at `/run/secrets/jev.env`. Never copy it. |
| `runtime/` | writable classifier state (`classifier.sqlite`). |
| `releases/`, `qa*-code.tar.gz`, `lab/` (root-owned, Oct 6) | artifacts of the laptop/Mac deployment and evaluation pipelines; not mine. |
| `deploy/start_backend.sh` in the repo | the sanctioned way to start the container (`MELOS_IMAGE=... sh deploy/start_backend.sh`; refuses if `melos-api` exists). |

**Containers and ports** (as of writing; names ending in `-before-*`,
`-canary-*`, `-lexical-*`, `-offline-eval-*` are exited history):

| Container | Image | Port | Note |
| --- | --- | --- | --- |
| `melos-api` | `melos-api:20261009u` | 127.0.0.1:8791 | production, behind the Funnel |
| `melos-api-canary-v` | `melos-api:20261009v` | 127.0.0.1:8792 | canary of the next release (other session) |
| `melos-morpheus` | `melos-morpheus:2f1a30d` | 127.0.0.1:8793 | morphology service (other session) |
| `melos-api-lab-w`, `melos-api-dev-w` | `melos-api:20261009u` | 8795, 8796 | other session's lab/dev instances |
| `melos-lab` | `melos-api:20260930-merge2` | none | **my** sidecar for retrieval experiments, idle (`sleep infinity`), 8 CPUs/16 GB caps |

Images `melos-api:20260930-merge1..4` are the box session's builds; the
`2026100x*` series are the laptop/Mac pipeline's.

**Retrieval lab** `~/work/Nacryos/melos-lab/`: `data-snapshot/` (Sep 30
`corpus.sqlite` copied with `cp -p` plus `embeddings/`), `hub/` (HF cache with
a symlink to bge-m3 plus the two rerankers), `eval-queries*.jsonl`,
`report-*.json`, `*.log`, `hopper/` (extracted Edmonds TEI). Recipe in
`docs/retrieval.md` and in the box session's memory. To re-create the
container: `docker run -d --name melos-lab --cpus=8 --memory=16g --user=1000:1000`
with the live data dir at `/app/data:ro`, the snapshot's `corpus.sqlite` and
`embeddings` mounted over `/app/data/...`, `/models:ro`, the repo's `backend`
and `scripts` over `/app/backend` and `/app/scripts`, the lab dir at `/lab`,
and **`-e MELOS_PUBLIC_DEPLOYMENT=1 -e MELOS_PUBLICATION_POLICY=source-labels`**
(without the policy variable the API hides Wikisource rows and lexical numbers
are wrong; this cost the first run).

**`~/melos-u` and `~/melos-q`** (not mine; observed): staging directories of
the laptop/Mac release pipeline for releases "u" (Oct 9) and "q" (Oct 8):
`src/` (unpacked tarball of the deployed tree, e.g. `u-src-fab37bf.tar.gz`),
`base-image.txt` (`melos-api:20261009t` was the base for u), `build/` (lemma
and n-gram index builds), `data/` (`lemma_index.sqlite`, `ngrams.sqlite`,
`citation_index.sqlite`, `render_cache.sqlite`, calibration JSON),
`canary-checks/` and `prod-checks/` (`cite-eval`, `compare-101`,
`compare-heldout`, `endpoints.txt`, `smoke.txt`, `release-u.json`), `eval/`
(`lyric-dump-*.json` and `lyric-score-*` results), `work/` (debug scripts).
Treat as the coordinator's; nothing of mine reads or writes them.

**Unrelated load.** `~/work/pc-t0..t5` are another project (periclymenus);
their sessions drive the box's load average near 30. Expect slow runs.

## 5. How to check progress

```
# repository and deploy state
cd ~/work/Nacryos/Project-Melos && git fetch && git log --oneline -5 origin/main && git status --short
gh api repos/Nacryos/Project-Melos/deployments?per_page=1 --jq '.[0] | "\(.created_at) \(.sha[0:7])"'
docker ps --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}' | grep -v Exited
curl -s http://127.0.0.1:8791/api/status | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["passages"],d["authors"],d.get("mirror_grouping"),d["embeddings"].get("count"))'
curl -s 'http://127.0.0.1:8791/api/search?q=the+sweet+apple+reddens+on+the+topmost+bough&mode=hybrid&limit=3' | python3 -c 'import json,sys;d=json.load(sys.stdin);print([(r["author"],r["citation"],sorted(r.get("retrieval_ranks",{}))) for r in d["results"]])'

# tests (box venv; 8 tests read collector outputs that exist only where the index is built)
.venv/bin/python -m pytest tests -q --deselect tests/test_apparatus_claims.py --deselect tests/test_notes_extraction.py
npm run test:frontend

# retrieval lab
tail -3 ~/work/Nacryos/melos-lab/*.log
docker exec melos-lab python /app/scripts/lab_eval.py --queries /lab/eval-queries-keep.jsonl --out /lab/report-x.json --every 2 --methods hybrid_current hybrid_prod

# training set (option 2)
ls -la ~/work/Nacryos/Project-Melos/data/training/ && cat ~/work/Nacryos/Project-Melos/data/training/*/stats.json
```

## 6. Pitfalls

- **Two code lines.** Production is built from the Mac/laptop tree (unpushed,
  85 commits ahead on `lyric-corpus-reader`), while the box session merges to
  `main`. Anything the box pushes to `main` reaches the API only when the
  coordinator's tree pulls `main` and rebuilds. Before changing `backend/`
  from the box, pull the coordinator's branch or expect conflicts on
  `backend/server.py`, `backend/retrieval.py`, `scripts/build_corpus.py`,
  `js/reader.js`, `css/reader.css`.
- **The API tolerates an old-schema index** (`legacy_schema()`), but a
  `corpus.sqlite` dropped in without `author_canonical` silently turns mirror
  grouping off; `/api/status` reports `mirror_grouping`.
- **`.dockerignore` is a whitelist** (`backend/*.py`, `backend/*.json`, css,
  js, paintings, two HTML files). A new backend data file must be whitelisted
  or it never reaches the image.
- **Sidecars need the publication policy env** (see section 4) or they run
  the restricted view.
- **The embeddings manifest is bound to `corpus.sqlite` mtime and size**;
  copy with `cp -p` or the semantic index reports not ready.
- **Root-owned files** in `services/melos/data` can be replaced (directory is
  owner-writable) but not edited in place.
- **Disk at 97 %.** Builds, snapshots and `docker build` can fail abruptly.
- **Long-running checks in this session used background tasks and
  Monitors**; a fresh session must re-arm anything it wants watched.
- **Collector outputs on the box are not accepted anywhere.** Acceptance
  manifests live with the index builder; `scripts/accept_owner_outputs.py`
  writes hash-bound PASS entries where the data lives.
- **`/api/classify-context` costs money** when `MELOS_PUBLIC_CLASSIFIER=1`
  (the production container sets a daily limit of 500). Do not loop on it.

## 7. Handover prompt for the Mac coordinator

Copy from the line below.

---

You are coordinating Project Melos (https://greeklyric.com, repo
Nacryos/Project-Melos) from the owner's Mac. A Claude session on the owner's
always-on Linux box ("basecamp") keeps doing the hands-on work over ssh+tmux
(socket `basecamp`, session `melos`, cwd `~/work/Nacryos/Project-Melos`); you
direct it, review its output, and own the deploy pipeline that builds
`melos-api` containers from your tree.

Read first: `docs/handoff-2026-10-10-box-to-mac-coordinator.md` (this file),
`docs/decisions.md` (owner policy: modern editions admitted, corrected OCR
searchable, authors merged, copies grouped), `docs/retrieval.md` (search
measurements and the English bridge), `docs/deployment.md`.

Facts you must hold:
- Production API is the Docker container `melos-api` on the box, port
  127.0.0.1:8791, data mounted read-only from `/home/alvin/services/melos/data`,
  reached publicly through the Tailscale Funnel; Vercel serves the static site
  from `main` and proxies `/api/*` to it. Start containers only with
  `MELOS_IMAGE=<tag> sh deploy/start_backend.sh`.
- Your Mac clone is on `lyric-corpus-reader`, ahead and unpushed; the box
  works on `main`. Everything the box pushed on Sep 30 is already in your
  branch. Decide and say explicitly whether the box should commit to `main`
  or to your branch, and pull before you build.
- The live index was built on the laptop; the box holds collector outputs
  that are not indexed: Edmonds Elegy and Iambus (1,722 linked English
  renderings), Paton Greek Anthology (2,049), Eulogikon (20,950). English
  translations linked to Greek passages are the main lever for English search.
- Measured on 195 judged queries: Greek-vector similarity alone finds a
  passage for an English query one time in ten; the deployed hybrid plus BM25
  bridge reaches about 0.4 Recall@10; rerankers lowered recall and are too
  slow on CPU. Do not re-propose rerankers on the box.
- The box is at 97 % disk and load average about 30 from unrelated sessions.
  No GPU. Any fine-tune runs on a GPU elsewhere; the box only prepares data.
- The box session's retrieval lab is the container `melos-lab` and
  `~/work/Nacryos/melos-lab/`; a sidecar must set
  `MELOS_PUBLIC_DEPLOYMENT=1 MELOS_PUBLICATION_POLICY=source-labels`.
- `~/melos-u` and `~/melos-q` are your pipeline's staging directories; the
  box session does not touch them.

Immediate agenda:
1. Check the bi-encoder training set the box prepared under
   `data/training/` (train/dev JSONL with hard negatives, `stats.json`,
   `README.md` with the fine-tune recipe); decide where the GPU job runs.
2. Decide on indexing the Edmonds and Paton collections and on the pending
   owner questions (machine paraphrases for untranslated fragments; disk
   clean-up; who runs collectors).
3. Keep the box's changes measured: any ranking change goes through
   `scripts/lab_eval.py` on a fixed snapshot before deployment.

When you message the box session, give one task at a time with the target
branch, and ask it to reply with commit hashes and the verification it ran.

---
