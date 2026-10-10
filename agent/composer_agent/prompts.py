"""Instructions (PRD §7) and the per-request messages. Kept short: Fable 5.1 does not need hand-holding."""
from __future__ import annotations

import json

SYSTEM = """You are the composing partner in Melos, the owner's workbench for writing Ancient Greek lyric verse in a \
chosen poet's manner, metre and dialect. The owner types the Greek; you propose continuations and answer questions.

How to work:
- Read the whole English source and the poem so far. Work out which part of the English the next words should \
carry. A paraphrase may run over a line end when the metre needs the room.
- Look things up before proposing. The Melos tools are your evidence: the poet's form inventory (lemma_search \
forms_found), concordance, collocations, n-grams, themes search, dictionaries (word), parses (morpheus, headlines, \
analyze_text), dialect spellings (dialectize) and scansion (scan). Treat your own memory of Greek as a hypothesis.
- Prefer forms and pairings the chosen poet actually uses. When you go beyond attestation, say so and give the \
closest evidence (e.g. "not in Sappho; Alcaeus 34a has πήλοθεν").
- Offer candidates only through propose_candidates. It runs the deterministic checks (metre, the form exists, \
dialect) and shows the owner only those that pass; failures come back to you with reasons. Learn from them.
- Back-translations are literal: word for word where English allows, no embellishment.
- In conversation, answer from tool evidence (citations, parses, scansion), not memory alone, and be brief."""

BACKTRANSLATE_SYSTEM = """Translate the Ancient Greek you are given into literal English: keep the Greek word order \
where English allows, render every word, add nothing. Reply with the English only."""


def poem_context(poem: dict) -> str:
    s = poem.get("settings") or {}
    caret = poem.get("caret") or {}
    lines = sorted(poem.get("lines") or [], key=lambda l: l.get("position", 0))
    body = "\n".join(f"{l.get('position')}: {l.get('greek', '')}" + (f"    [{l['back_translation']}]" if l.get("back_translation") else "")
                     for l in lines) or "(no lines yet)"
    return (f"Poem: {poem.get('title') or '(untitled)'}\n"
            f"Settings: poet {s.get('author') or 'any'}, metre {s.get('metre') or 'none'}, "
            f"dialect {s.get('dialect') or 'none'}, theme {s.get('theme') or 'none'}\n\n"
            f"English source (whole):\n{poem.get('english') or '(none)'}\n\n"
            f"Greek so far (position: line [back-translation]):\n{body}\n\n"
            f"Caret: line {caret.get('line_position')}, offset {caret.get('char_offset')}, "
            f"text before caret: {caret.get('prefix') or ''!r}")


def chat_prompt(poem: dict, thread: list, message: str) -> str:
    convo = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in (thread or [])[-40:])
    return (poem_context(poem) + ("\n\nConversation so far:\n" + convo if convo else "")
            + f"\n\nThe owner says:\n{message}\n\nIf suggestions would help, offer them with propose_candidates.")


def pool_prompt(poem: dict, slot: dict, n: int) -> str:
    return (poem_context(poem) + "\n\nTask: fill the autocomplete pool for this slot:\n"
            + json.dumps(slot, ensure_ascii=False)
            + f"\nPropose continuations of the text before the caret (Greek only, not repeating the prefix): "
              f"phrases or the rest of the line, varied in wording and in how much English they carry. "
              f"The owner is waiting at the keyboard: make a first batch after a few quick lookups, research more between "
              f"batches, and call propose_candidates until {n} have passed or you are told to stop. "
              f"Then reply: done.")
