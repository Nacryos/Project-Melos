# PRD: Composer with an agent (release W)

Owner: Alvin. Written 2026-10-09 (Pacific). Branch base: `composer-v` (release V work in progress).
Status: approved direction from the owner on 2026-10-09; open points in §9.

## 1. Goal

A web composer at greeklyric.com, visible only to the signed-in owner. You type Greek on a TypeGreek board.
The agent proposes whole phrases and lines that already scan, already parse and are in the right dialect. It
works like code autocomplete: options pop up under the cursor and you choose with the keyboard. A chat panel
lets you ask the same agent questions ("how would these two words combine in a Sapphic stanza, even if Sappho
never has them together?"). All work is saved on the server.

The model behind it is **Claude Fable 5.1 (`claude-fable-5-1`) at effort `xhigh`**, always (owner's ruling).
It runs on the Basecamp box next to the Melos backend so it can call every deterministic tool directly.

## 2. What exists (from `composer-v`)

| Piece | State |
|---|---|
| Owner sign-in (release T) | Live in the API; argon2id hash in `services/melos/secrets/owner_auth.env` (set 2026-10-09). `owner_login_check` 0 failures. |
| TypeGreek input (`js/typegreek.js`) | Done; matches typegreek.com's rules, tested. |
| Composer page (`composer.html`, `js/composer.js`) | Canvas with live syllable shading (`/api/scan`), word hover (`/api/analyze-text`), "suggest next line". Public; no storage. |
| `/api/compose/suggest` | Corpus proposer only, lint checks L1, L2, L4, L7, L11; no model. Not owner-gated. |
| Deterministic tools | Search, word/dictionary, Morpheus, analyze-text, dialectize, scan, lemma search/frequency/concordance/collocations/n-grams, concept diachrony, cite, commentary. |
| Grammar checks | Not built: agreement (L3), accent (L9), particles (L10). |

## 3. User experience

Layout, top to bottom:

1. **English panel** (left or top, collapsible). The English you are working from, as free text. It is not
   split into lines; the agent reads it as a whole and tracks roughly where you are in it.
2. **TypeGreek board.** The poem being written, line by line, with live scansion shading. The current line is
   editable; finished lines can be reopened.
3. **Autocomplete pop-up** under the caret, opened on Tab or after a pause. It lists 3–8 continuations that
   already pass scansion and the form/dialect checks. Each shows the Greek, its metrical pattern, a gloss, and
   which part of the English it covers. Up/down to choose, Enter to accept, Esc to close. Options can run past
   the end of the line into the next one when a paraphrase needs the room.
4. **Back-translation** under each Greek line: the agent's English for what you actually wrote, so you can see
   the poem's direction drift from or match the source.
5. **Versions row** under each line: every saved version of that line, side by side, scrolling horizontally.
   Click one to make it current; versions are never deleted, only archived.
6. **Chat panel** (right side). Talk to the agent. It sees the poem, the English, the current line and the
   caret. It answers with tool-backed evidence (citations, parses, scansion) and can push suggestions into the
   pop-up or the versions row.

Toolbar (kept from release V): poet style, metre, dialect, theme.

## 4. Speed: how it feels instant with a slow model

A Fable 5.1 call at `xhigh` takes from several seconds to minutes. The deterministic checks take milliseconds.
So the model never runs on a keystroke. Instead:

- **Candidate pool, filled ahead of time.** After every accepted word, line or edit to the English, the agent
  produces a large batch of continuations for the next stretch of verse in one call. Each streams back as soon
  as it is written and goes through the checks; only those that pass enter the pool.
- **The pop-up reads the pool.** As you type, the client filters the pool by the letters already typed and by
  position in the metre (string match plus a pattern match; no network round trip). If the pool has nothing
  fitting, the pop-up says "thinking" and shows the pool's next arrivals.
- **Cheap fillers while the model works.** The release V corpus proposer and a metre-aware n-gram proposer run
  at once (tens of ms) and fill the pop-up, labelled as corpus, until model candidates arrive.
- **Cache.** Pools are keyed by (poem, line, caret context, settings) and reused when you move back and forth.

Target latencies: pop-up open from pool < 50 ms; first model candidate for a new slot < 15 s; scansion of a
typed line < 150 ms (existing scanner budget).

## 5. The checks (generate, then discard)

Every candidate from the model goes through the lint bank before you can see it. Failing ones are dropped and
their failure is fed back to the agent so the next batch avoids it.

| Check | Tool | Blocks |
|---|---|---|
| L7 metre: the candidate fits the remaining metrical slots (and responsion if set) | `/api/scan` | yes |
| L1 every form exists (lexicon or Morpheus) | `/api/words/headlines`, Morpheus | yes |
| L2 dialect: forms are right for the chosen dialect (attested or rule-derived) | `/api/dialectize`, `backend/dialect_rules.py` | yes |
| L4 attestation: how each form and pairing is attested, by author | lemma search, n-grams, collocations | no (shown) |
| L11 verbatim quotation: runs of 4+ words copied from the corpus | n-grams | shown as homage |
| L3 agreement, L9 accent, L10 particles | to build (§8) | L3 yes once built |

## 6. Architecture

```
browser (greeklyric.com/composer, owner cookie)
   │  HTTPS via Vercel rewrite → Tailscale Funnel
   ▼
melos-api (FastAPI, existing)            box, read-only container
   ├─ /api/composer/*   owner-only: poems, lines, versions, English, pool, chat (SSE)
   ├─ composer.sqlite   in /app/runtime (only writable mount)
   └─ proxies agent calls ─────────────► melos-composer-agent (new container, box)
                                          Claude Agent SDK, model claude-fable-5-1, effort xhigh
                                          tools = Melos MCP server (in-process), each tool an HTTP
                                          call back to melos-api on the box's internal network
                                          no Bash, no file writes, no web except Melos
```

- **Agent harness:** the Claude Agent SDK (the Claude Code harness as a library), Python. Built-in tools are
  turned off except read-only ones that are useful (none touch the filesystem outside a scratch dir). The
  Melos tools are exposed as one in-process MCP server: `search`, `word`, `morpheus`, `analyze_text`,
  `dialectize`, `scan`, `lemma_search`, `lemma_frequency`, `concordance`, `collocations`, `ngrams`,
  `concept_diachrony`, `cite`, `commentary`, `check_candidate` (runs the whole lint bank on a candidate).
- **Why a separate container:** the API container is read-only and hardened; the agent needs Node (the SDK
  runs the Claude Code CLI) and an outbound connection to Anthropic. Keeping it apart means a fault in the
  agent cannot touch the live API.
- **Key:** the owner's Anthropic API key on the box (`~/.config/basecamp/keys/anthropic-api.key`), mounted
  read-only as a secret into the agent container only. Never sent to the browser.
- **Access:** every `/api/composer/*` route and the `composer.html` page require the owner session; signed-out
  requests get 404, as with `/api/private/*`. The agent container listens only on the box's internal Docker
  network and accepts calls only from melos-api with a shared internal token.
- **Storage (`composer.sqlite`):** `poems` (title, settings, English text), `lines` (poem, position, current
  version), `versions` (line, Greek, back-translation, scansion, checks, created_at, source = owner/agent/corpus,
  archived), `pool` (poem, slot key, candidate, checks, created_at), `chat` (poem, role, content, tool trace).
  Append-only for versions and chat.
- **Streaming:** chat and pool fill use server-sent events from melos-api to the browser.

## 7. Agent instructions (summary)

- Read the whole English, the poem so far and the caret. Work out which part of the English the next words
  should carry, allowing paraphrase to spill over line ends.
- Look things up before proposing: dictionaries, corpus usage by the chosen poet, collocations, Morpheus parses,
  dialect forms. Prefer forms attested in the poet; when going beyond attestation, say so and give the closest
  evidence (e.g. "not in Sappho; Alcaeus fr. 130b has …").
- Propose many short candidates in a fixed JSON shape (Greek, the English span it covers, the metrical slots it
  fills, the evidence used). Never present a candidate that failed a blocking check.
- Back-translate whatever the owner settles on, literally.
- In chat: answer with evidence from the tools (citations, parses, scansion), not from memory alone.

## 8. Phases

| Phase | Deliverable | Check |
|---|---|---|
| W0 | Owner gate on `composer.html` and all compose routes; `composer.sqlite` with poems/lines/versions; save/load in the page | signed-out 404 tests; reload keeps work |
| W1 | Agent container with the Melos MCP tools and the API key; `/api/composer/chat` SSE | a chat question answered with tool calls |
| W2 | Candidate pool: model batch → lint bank → pool; pop-up reading the pool; corpus filler | p95 pop-up < 50 ms from pool; zero shown candidates failing L1/L2/L7 |
| W3 | English panel, back-translation, spill-over across lines; versions row | owner check |
| W4 | L3 agreement check; accent and particle checks as warnings | gold examples |
| W5 | Release W build, canary, promote, rollback script; frontend deploy | canary checks, owner sign-off |

## 9. Open points

1. Whether "Sapphic" mode may use Homeric forms (proposed: allowed, labelled) and whether runs of 4+ words
   copied from the corpus are allowed (proposed: allowed, labelled as homage).
2. Accent convention for Lesbian (proposed: follow the chosen edition; Campbell by default).
3. Cost guard: Fable 5.1 at `xhigh` costs about $10 / $50 per million input/output tokens. Proposed: a daily
   spend counter shown in the page, no hard cap unless the owner sets one.
4. `main` auto-deploys the Sep 30 frontend to production on every push (incident 2026-10-09); deploy
   automatic builds from `main` should be switched off before this work merges.
