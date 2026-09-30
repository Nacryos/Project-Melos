# Reader API (implementation contract)

Python FastAPI server at port 8791 serves static root and JSON APIs. SQLite index
is rebuilt from collector JSONL; raw/processed files remain authoritative.

- `GET /api/status`: `{passages, authors, author_labels, works, sources, languages, embeddings, evidence, classifier, warnings}`; the statistics `authors` count folds Unicode/case-equivalent labels, while `author_labels` counts raw distinct labels. The author chooser may merge further verified identities.
- `GET /api/authors`: `{authors:[{author,count,labels:[],identity_id?}]}`; independently accepted identity profiles merge only source-backed aliases and preserve their exact labels.
- `GET /api/works?author=...`: `{works:[{id,author,work,edition,language,count}]}`
- `GET /api/passage?id=...`: full passage plus `previous_id`, `next_id`, `related`.
- `GET /api/passages?work_id=...&offset=0&limit=20`: `{results:[],total}`
- `GET /api/search?q=...&mode=words|forms|themes|hybrid&author=&language=&include_reference=false&offset=0&limit=30`: `{results:[passage + score + match_reason],total,mode,method,warnings}`. Lexical totals count all distinct filtered matches; theme totals count a fixed first-1,000 ranked-candidate pool. Hybrid uses bounded lexical/form/dense candidate pools and exposes `matched_evidence`; its total is not every potentially relevant corpus passage. `commentary_assisted=false` restricts hybrid to direct Greek-text evidence.
- `GET /api/word?form=...&passage_id=...`: generic lexical candidates and occurrences plus `structured_evidence`, `contextual_candidates:[]`, `context_analysis_status` and `author_profile`. Source-linked claims and model judgements are separate; missing morphology or senses are not filled from memory.
- `GET /api/evidence?form=&passage_id=&claim_id=&limit=20`: source claims at their declared scope, with exact quotations and locators. Large paradigms are compacted for lookup; `GET /api/claim?id=...` returns the full source claim.
- `POST /api/classify-context`: JSON `{form,passage_id}` returns `status=proposed|abstained`, an existing `candidate_id` if selected, source evidence IDs, inspectable packet and raw uncalibrated provider signals. Jev is server-side; this endpoint is local-only and never changes corpus evidence. Public deployments must set `MELOS_PUBLIC_DEPLOYMENT=1`, disabling paid classification pending an authenticated gateway.
- `GET /api/wiktionary?form=...`: independently gated `{ready,query,results,total,warnings}` reference lookup. Entry, sense, and listed-form tags retain their separate scopes; listed forms do not assert corpus attestation or unattestation.
- `GET /api/usage-space?q=...&author=&limit=80`: `{points:[{id,x,y,z,text,author,work,citation,source_url,date_start,date_end,match_reason}],method,retrieval_method,warnings}`. Coordinates derive from actual passage features and are not historical facts. Any thematic fallback is disclosed and need not contain the queried word.
- `GET /api/sources`: collection reports and counts.

All query values URL-encoded. Passage IDs opaque. `work_id` is a stable hash of
source, author, work, edition, language. Text stays original; HTML is escaped in
reader. Theme search may use translations/commentary as retrieval bridges but
must disclose which text was indexed and must not label that as Greek semantic
understanding. Return missing capability plainly, never fake successful results.
An author filter matches case/Unicode-equivalent labels and independently
accepted source-backed identity aliases, plus
commentary explicitly linked to that author's text by `parent_id` or by a
page-scoped note sharing a source URL within the same collection. A linked
commentary result retains its modern `author` and adds `author_scope_reason`.

Reader developer owns `reader.html`, `js/reader.js`, `css/reader.css`; visualization
developer owns `js/usage-space.js` and exposes `window.MelosUsageSpace.open(query,
author)` plus `close()`. Main owns server, database and integration. Morphology
developer owns `backend/morphology.py` and communicates callable contract. Encoder
developer owns `backend/semantic.py` and `scripts/build_embeddings.py`; coordinate
input schema and index paths with main before launching encoding.
