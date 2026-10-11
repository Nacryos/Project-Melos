# Latin composer: end-to-end runs (deliverable 5)

Local dev stack (`scripts/latin_dev_stack.sh`: this worktree's melos-api on 127.0.0.1:8797 and the composer agent service
on 127.0.0.1:8801, scratch secrets and state under `data/private/dev-stack/`; the live containers are never touched).
Driver: `scripts/latin_e2e.py`: sign in as the owner, create a poem with settings language la / Catullus / phalaecian and
the English source "Come, friends, tonight we drink the dark Falernian; tomorrow the rain can keep the whole city to itself.", ask the pool for line 1 (whole-line mode, open slots
`xx-uu-u-u-F`), read the streamed candidates (each linted by `POST /api/composer/check` with `language=la` before it
leaves the agent service), save the first candidate that fills the whole template as the line's version, and read the
saved version's checks back. Model: Fable 5.1, research turn at xhigh, pool fill at medium (release W defaults).

| Run | First passing candidate | Passing (whole lines) | Rejected by the lint | Whole fill | Cost | Accepted line | Saved version's checks |
|---|---|---|---|---|---|---|---|
| 20261010-203337 | 36.5 s | 5 (? whole lines) | 0 | 37.6 s | $0.227 | nunc, o | L7 fail, L1 ok, L2 ok, L4 ok, L11 ok |
| 20261010-203604 | 24.5 s | 4 (3 whole lines) | 4 | 62.7 s | $0.273 | nigrum nocte bibamus hac Falernum | L7 ok, L1 ok, L2 ok, L4 ok, L11 ok |

The first run's driver saved the first candidate of the stream, a two-syllable opening ("nunc, o") that fits the open
slots but is not a whole line, and the saved version's whole-line metre check rightly failed; the driver now takes the
first candidate whose fit leaves no open slot. The second run's accepted line scans –––⏑⏑–⏑–⏑–⏑ (nigrum nocte bibamus
hac Falernum: spondee base, the elision-free Catullan shape), every word is printed in the Latin corpus, and no run of
it is copied from Catullus (L11 clean). The lint rejected four candidates of the second batch on the metre (L7). The
agent used only `propose_candidates` (no research lookups) in these fills: the Latin research tools exist
(`la_concordance`, `la_forms`) but the research turn did not call them for this short poem; measured next with a
longer source and the `words` mode.

Costs are the agent's own per-turn figures (`data/private/dev-stack/agent-state/usage.jsonl`). 2026-10-10 20:37 PDT.
