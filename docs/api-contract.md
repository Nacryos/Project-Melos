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
- `POST /api/classify-context`: JSON `{form,passage_id}` returns `status=proposed|abstained`, `decision_stage`, an existing `candidate_id` if selected, source evidence IDs, inspectable packet and raw uncalibrated provider signals. Jev is server-side and never changes corpus evidence. Public deployments require the explicit `MELOS_PUBLIC_CLASSIFIER=1` opt-in and use the durable quota/cache gateway described in `docs/deployment.md`; preflight rejection makes no provider request.
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

### Printed word boundaries

Derived occurrence tokens retain combining marks and a single attached terminal
apostrophe. The recognized apostrophe glyphs `'`, `’`, `᾽`, and `ʼ` share a folded
lookup key; the original glyph remains in the source and displayed token. No
missing ending is supplied. Internal apostrophes do not split a word, whereas
repeated signs form a boundary after the first attached sign.

Greek exact-word searches and contextual occurrence checks distinguish a form
with a terminal apostrophe from the same letters without it. Greek paired
single quotes are consequently conservative/literal: bare `α` does not exactly
match `'α'`, while `α'` does. The system cannot infer whether an attached mark is
quotation punctuation or elision. English/Latin description searches retain
their previous ordinary quotation-boundary behavior.

Reader commentary previews compare literal complete Greek tokens with folded
accents, sigma and the four apostrophe glyphs. They preserve the source excerpt
and do not join words over gaps or infer a parse. Explicit printed line-end
divisions are joined only for passage-word lookup, with source text unchanged.

Spacing psili (`᾿`, U+1FBF) is a separate retained printed sign. It is not folded
to an ordinary apostrophe: copying `κἄμμ᾿` from Sappho 27 preserves that spelling
in word lookup, contextual checks, commentary matching and exact search. This
does not identify the editorial function of every spacing breathing sign.

Latin-letter queries retain apostrophes in both romanization and Beta Code
paths. A Greek-block punctuation character alone does not make a query Greek
script. Unsupported punctuation/digits separate query words instead of silently
joining their letters. The partial Beta decoder strips the supported accent,
breathing, case, iota-subscript, diaeresis and underdot syntax only; it is not a
full Beta Code document importer. Character handling was checked against the
[TLG Quick Reference, pp. 3–4](https://stephanus.tlg.uci.edu/encoding/quickbeta.pdf).

Persistent evidence and Wiktionary indexes declare a lookup-normalization
version. A version mismatch fails closed until their derivative lookup keys
are rebuilt or repaired against unchanged, independently accepted source data.
Corpus-token, evidence-key, and dictionary-key repairs must be deployed as a
coordinated snapshot with the corresponding backend code.

Word lookup exposes `observed_form_groups`, not a pooled paradigm for every
spelling suggestion. Inventories retain source lemma identity, homograph
markers, source references, query-match relationship, and explicit truncation
counts. They are source annotations across the index, not attestations in the
selected author or an adjudication of that occurrence. The reader does not
fall back to an unscoped `attested_forms` list from an older backend.

Reader developer owns `reader.html`, `js/reader.js`, `css/reader.css`; visualization
developer owns `js/usage-space.js` and exposes `window.MelosUsageSpace.open(query,
author)` plus `close()`. Main owns server, database and integration. Morphology
developer owns `backend/morphology.py` and communicates callable contract. Encoder
developer owns `backend/semantic.py` and `scripts/build_embeddings.py`; coordinate
input schema and index paths with main before launching encoding.
