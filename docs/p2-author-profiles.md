# Author identity and literary context profiles

`scripts/ingest_p2_authors.py` regenerates `data/claims/p2_authors.jsonl`,
`data/metadata/p2-author-profiles.json`, and `data/reports/p2_authors.json` from
saved, source-hashed metadata. It creates no corpus passages or poem dates.

Profiles are keyed by Wikidata QID and include a CTS author URN, the source's
display label, exact alias records (`label`, `source`, `source_id`,
`evidence_ids`), source descriptions and broad genre contexts, and IDs of
author-level `literary_dialect` claims. The alias evidence joins Wikidata's
P12869 CTS identifier with the pinned OGC author authority and catalog. For
the Perseus authors, the pinned CTS group metadata provides another direct
identifier check. Greek Wikisource names come from Wikidata's exact
`elwikisource` sitelinks. A shared spelling alone never establishes a match.

`backend.authors.lookup_author(label)` and `equivalent_labels(label)` accept
only exact, case-insensitive Unicode-equivalent labels in an independently
accepted profile. They abstain on mixed-author labels, collisions, and any
profile or claim file whose current hash lacks a matching `PASS` entry in
`data/reports/p2-claim-acceptance.json`. Each function accepts optional file
paths for isolated integration or testing.

The dialect claims preserve the source's literary language labels. DCC's
Sappho introduction names Sappho and Alcaeus as Aeolic literary
representatives; Goodell's historical overview calls literary dialects mixed
while broadly associating Sappho with Aiolic, Pindar with Doric, and Homer
with Ionic. These are author-level context priors. They do not classify any
token, validate an inflection, determine the dialect of a whole poem, or date
a composition. The Goodell dates are not imported into chronology.

Unresolved source labels remain in `unresolved_corpus_labels`. In particular,
compound attributions, scholia, hymns, pseudonymous collections, and a few
names without an explicit identity bridge are not merged into individual
poet profiles. Existing author labels in the corpus remain unchanged.
