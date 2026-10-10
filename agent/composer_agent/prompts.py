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
- Speed: the owner is waiting at the keyboard. In pool requests the checks are your scansion and form check: do \
not work out metre, forms or dialect at length in your head before proposing. Think briefly, propose 3-5 \
candidates for one slot per propose_candidates call, read what the checks say, and go on.
- Back-translations are literal: word for word where English allows, no embellishment.
- In conversation, answer from tool evidence (citations, parses, scansion), not memory alone, and be brief."""

BACKTRANSLATE_SYSTEM = """Translate the Ancient Greek you are given into literal English: keep the Greek word order \
where English allows, render every word, add nothing. Reply with the English only."""


def _greek_so_far(poem: dict) -> str:
    lines = sorted(poem.get("lines") or [], key=lambda l: l.get("position", 0))
    return "\n".join(f"{l.get('position')}: {l.get('greek', '')}" + (f"    [{l['back_translation']}]" if l.get("back_translation") else "")
                     for l in lines) or "(no lines yet)"


def _caret(poem: dict) -> str:
    caret = poem.get("caret") or {}
    return (f"Caret: line {caret.get('line_position')}, offset {caret.get('char_offset')}, "
            f"text before caret: {caret.get('prefix') or ''!r}")


def poem_context(poem: dict) -> str:
    s = poem.get("settings") or {}
    return (f"Poem: {poem.get('title') or '(untitled)'}\n"
            f"Settings: poet {s.get('author') or 'any'}, metre {s.get('metre') or 'none'}, "
            f"dialect {s.get('dialect') or 'none'}, theme {s.get('theme') or 'none'}\n\n"
            f"English source (whole):\n{poem.get('english') or '(none)'}\n\n"
            f"Greek so far (position: line [back-translation]):\n{_greek_so_far(poem)}\n\n" + _caret(poem))


def poem_update(poem: dict, english_changed: bool) -> str:
    """A later turn in the same session: only what may have changed (the history is never edited)."""
    head = "Update to the poem.\n"
    if english_changed:
        head += f"The English source changed; it now reads (whole):\n{poem.get('english') or '(none)'}\n\n"
    return head + f"Greek so far (position: line [back-translation]):\n{_greek_so_far(poem)}\n\n" + _caret(poem)


def chat_prompt(poem: dict, thread: list, message: str, first: bool = True, english_changed: bool = False) -> str:
    if first:
        convo = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in (thread or [])[-40:])
        head = poem_context(poem) + ("\n\nConversation so far:\n" + convo if convo else "")
    else:
        head = poem_update(poem, english_changed)
    return head + f"\n\nThe owner says:\n{message}\n\nIf suggestions would help, offer them with propose_candidates."


RESEARCH = """This is the first request for this poem; this conversation stays open while the owner writes it, so \
what you look up now serves every later request. Research once, briefly and to the point: the English as a whole \
(which Greek words and images carry it), how the poet uses the key lemmas (lemma_search forms_found, concordance, \
collocations, themes search), and the dialect forms you will need (dialectize). Keep these findings in mind; later \
messages will only name new slots. Before any lookup, make one propose_candidates call for the current slot from what you already know (3 \
candidates; the checks will reject what is wrong), then research, and keep alternating short lookups and small \
batches. Keep each thinking pass short: you can always propose again."""


def slots_text(slots: dict, seen: dict) -> str:
    out = []
    for key, s in slots.items():
        prior = sorted(seen.get(key) or ())
        out.append(f"- slot {key}: line {s.get('line_position')} (0-based), text already there: {s.get('prefix') or '(line start)'!r}; "
                   f"open metrical slots {s.get('remaining_template')}; want {s.get('want')} passing"
                   + (f"; already offered (do not repeat): {' | '.join(prior[:30])}" if prior else ""))
    return "\n".join(out)


def pool_prompt(poem: dict, slots: dict, seen: dict, first: bool, english_changed: bool = False) -> str:
    head = poem_context(poem) + "\n\n" + RESEARCH if first else poem_update(poem, english_changed)
    if not slots:
        return head + "\n\nTask: research only for now; reply with a two-line summary of what you found, then: done."
    return (head + "\n\nTask: fill the autocomplete pool for these slots (the current one first, then the rest of "
            "the stanza, so the owner finds options already waiting on the next lines):\n" + slots_text(slots, seen)
            + "\n\nEach candidate continues the text already in its slot (Greek only, without repeating that text) and "
              "names its slot key. Vary wording and how much English each carries: single words, phrases, the rest of "
              "the line, and phrases that run over the line end into the next line (put a newline at the line end). "
              "The owner is waiting at the keyboard: call propose_candidates early and repeatedly with small batches "
              "(3-5 candidates for one slot per call, the current slot first, then the next ones in turn) until you "
              "are told to stop. Then reply: done.")
