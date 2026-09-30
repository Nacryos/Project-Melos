# Structured evidence index

`data/claims/*.jsonl` contains the source-specific claims defined in
`augmentation-contract.md`. `data/evidence.sqlite` is a derived, disposable
index. It is built only from files marked `PASS` in
`data/reports/p2-claim-acceptance.json` whose current SHA-256 and record count
match the independent audit manifest.

Run `python scripts/build_evidence.py` after claim audit. The builder validates
the required fields, allowed predicates/statuses, evidence references, and
unique claim IDs. It writes to a temporary SQLite file and replaces the old
index only after every accepted file passes. Unaccepted files are excluded;
an absent manifest or no accepted files is an error. The builder reports the
input file hashes and counts, also recorded in the database `input_files`
table. It never fetches or generates a historical claim.
The same manifest may contain `p2-author-profiles.json` with
`kind: "metadata"`; its hash is checked, but it is not loaded as a claim.
Other accepted non-JSONL inputs are rejected.

## Reader API

```python
from backend.evidence import EvidenceIndex

evidence = EvidenceIndex()
word = evidence.lookup("λόγος", passage_id="source:passage", limit=20)
views = evidence.candidate_analyses("λόγος", passage_id="source:passage")
listed_forms = evidence.forms_for_lemma("λόγος", limit=500)
passage = evidence.get_passage_claims("source:passage", limit=50)
neighbors = evidence.related_claims("source-specific:claim-id", limit=20)
full_claim = evidence.get_claim("source-specific:claim-id")
inputs = evidence.provenance()
```

`lookup` returns `claims`, `total`, and a method statement. Each claim exposes
its original `subject`, `predicate`, `object`, `evidence`, `assertion_type`,
`status`, `method`, `source_family`, and source file. The `strength` label says
what link supports this result:

| Strength | Meaning |
| --- | --- |
| `explicit_passage_span` | Claim explicitly names this passage and source-supplied token offsets. |
| `explicit_passage_link` | Claim explicitly names this passage, without offsets. |
| `general_form_claim` | Claim names the queried form, without a passage link. |
| `listed_entry_form` | A source entry lists the queried form among its forms. No passage occurrence is asserted. |

Accent and case folding is a search operation; `match_reason` says when the
original spellings differ. Scope and status are independent: a source claim
may be general, while a review-needed claim may be passage-linked. Ordering
favors explicit passage links, then review status and morphology/lemma claims.
It is an inspection order, not a confidence score. The index preserves
contradictory claims rather than reconciling them.

For entries carrying large paradigms in `object.forms`, `lookup` returns only
the matching source rows in `matched_object_forms`. The returned object records
`listed_form_count` and `object_omitted_fields: ["forms"]`; `get_claim(id)`
returns the complete, unprojected claim. `candidate_analyses` projects only
explicitly present lemma, raw analysis/tags, and features from lemma,
morphology, or equivalent-form claims. Null fields remain null. Candidate IDs
are claim IDs or claim IDs with source form ordinals. Equivalent forms retain
their source relation labels. `evidence_refs` are source record IDs or stable claim-local
evidence references. These rows can be shown before approximate lexicon
suggestions, but they do not merge different sources into a single parse.
For Wiktionary `form_of` claims, a single explicit target word can appear as
the candidate lemma; multiple targets stay in `lemma_targets` with no chosen
lemma. Raw source tags stay separate from normalized features.
`forms_for_lemma` returns source-listed spellings only. A caller can search
actual corpus tokens with those spellings; listing alone is not attestation.
The reverse index includes only listed values containing Greek letters.
English table headings and placeholders remain in the complete claim, but
cannot become Greek search expansions.

`get_passage_claims` returns only explicit `subject.passage_id` links.
`related_claims` traverses shared source-specific subject, passage, or folded
form. A shared form is a discovery edge, not agreement or influence. The
database stores subject, predicate, object, and source evidence without a
separate graph service.

Missing `data/evidence.sqlite` raises `FileNotFoundError`. The reader/server
should present that as unavailable evidence, rather than a successful empty
result. The SQLite file can be regenerated from accepted JSONL and the audit
manifest at any time.
