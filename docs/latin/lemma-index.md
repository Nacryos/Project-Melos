# Latin lemma index (`data/lemma_index_la.sqlite`)

Built 2026-10-11 04:34 UTC by `scripts/build_lemma_index_la.py` (not in git; licensed data). It is the Latin counterpart of the
Greek headword index (`docs/lemma-index.md`): every token of the Latin partition carries a headword, so the composer's
attestation check (L4), `forms_found`, the concordance and the agent's `la_lemma` tool answer "does Catullus use this
word, and in which forms?".

## Sources and method

- **Recorded lemmas: LASLA v1.0.1** (CIRCSE/LASLA, CC BY-NC-SA 4.0; `data/private/lasla/`; owner's licensed-data
  policy, `docs/latin/licensed-data.md`): hand-verified lemma, POS, morphology and LiLa id for every token of Catullus
  (13,129) and Horace (45,007: Odes, Epodes, Carmen Saeculare, Satires, Epistles, Ars Poetica). Each token carries its
  citation (poem / book, carmen / verse), so it is aligned to the Perseus lines of `data/corpus_la.sqlite` by verse and
  in-order form matching (u/v, i/j folded; LASLA's split enclitics -que, -ne, -ue, -cum re-attached to the host form;
  edition spelling variants matched within one or two letters; LASLA's joined forms such as *nescioquid* matched to
  two corpus words). LASLA's Catullus numbering is mapped to Merrill's (68.41-160 = 68a; 2b = 2.11-13; 14b = 14a;
  58b = 55.23-32; 78b = 78.7-10; 117 has no Perseus text).
- **Alignment:** 29,165 tokens aligned to a corpus line, 316 not (edition differences such as
  *karum / carum*, *Adriatici / Hadriatici*; counted for the author, not linked to a line), 27,284 tokens of works
  without a text here (Satires, Epistles, Ars Poetica), which still count as the author's attestation.
- **Fallback readings:** a spelling LASLA never prints takes the Morpheus lemmas of the quantity lexicon (Winge's table).
- **Lemmatiser (for texts outside LASLA and for drafts, later):** LatinCy `la_core_web_lg` 3.9.8 (MIT weights; trained on
  UD Latin treebanks and LASLA; server-side only) is installed in `.venv-nlp` and evaluated below; it is not yet called
  by the API.

## Bake-off (`scripts/latin_lemmatiser_bakeoff.py`, `docs/latin/lemma-bakeoff.json`)

Test set: LASLA's Catullus, 13,129 tokens with human lemmas. Lemmas compared after folding (u/v, i/j, case, digits).

| Candidate | Coverage | Accuracy | Note |
|---|---|---|---|
| Form lookup, most frequent LASLA lemma, trained on Horace only | 71.3 % of tokens | 95.1 % on covered (67.8 % overall) | genuinely held-out: no Catullus in training |
| LatinCy la_core_web_lg 3.9.8 | 100 % | 92.8 % | optimistic: LASLA is in its training data |
| LatinCy on the lookup's unseen words (3,766 tokens) | — | 84.9 % | the case that matters for new text |

LatinCy's commonest "errors" are lemma conventions (*nec* lemmatised *neque*, *ac* as *atque*: 126 tokens) and proper
names (61.8 % on PROPN; *Lesbia* → *lesbius*). Nouns 94 %, verbs 96 %, adjectives 87 %. Decision: the index records
LASLA's lemmas where aligned (human, 98 % of the held texts) and uses LatinCy, with the convention map, for anything
else when it is wired in; the "attested in Catullus / Horace" check therefore rests on human lemmas.

## Tables and routes

`token`, `form_lemma`, `author_lemma`, `author_form` (forms_found with one example line), `lemma`, `metadata`.
Routes (owner or agent token): `GET /api/la/lemma?q=&author=` (headword counts by author, forms the poet prints),
`GET /api/la/lemma/resolve?form=`, and `readings` on `GET /api/la/forms`. L4 in `composer_lint.check(language="la")` now
reports, per word, the headword's tokens in the poet beside the spelling's. Agent tool: `la_lemma`.
2026-10-10 21:37 PDT.
