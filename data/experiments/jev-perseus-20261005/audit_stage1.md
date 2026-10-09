# Audit: Source Discovery — Jev versus Perseus Greek morphology pilot

## Step: 1
## Agent Action

Team A proposed a bounded, isolated research sample of the first five ambiguous occurrences from the opening Greek Odyssey and Iliad passages, within at most 40 inspected occurrences per passage. Previously inspected Odyssey ennepe is excluded before selection. Published English passages supply translation context.

## Audit Checks

- [x] Four Greek/English passage URLs independently fetched with HTTP 200 and matching Homer titles.
- [x] Each passage explicitly links CC BY-SA 3.0 US; that license URL independently returned HTTP 200.
- [x] Real morphology endpoint independently returned HTTP 200, title Greek Word Study Tool, and analysis/votes sections, using browser User-Agent plus exact Greek page Referer.
- [x] Official hopper.js independently fetched; function m appends the document identifier and occurrence number from the clicked anchor.
- [x] Personal scholarly use supported by official PerseusDL copyright statement. No blanket claim that morphology pages or voting data have the text pages' CC license.
- [x] Selection is predefined and bounded; no invented linguistic entries or padding authorized.

## Evidence

Audit performed 2026-10-05 UTC. Text identifiers: 1999.01.0135 (Odyssey Greek), 1999.01.0136 (Odyssey English), 1999.01.0133 (Iliad Greek), 1999.01.0134 (Iliad English), each at book=1:card=1.

- https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.01.0135:book=1:card=1 — 200, 124315 bytes
- https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.01.0136:book=1:card=1 — 200, 78236 bytes
- https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.01.0133:book=1:card=1 — 200, 130939 bytes
- https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.01.0134:book=1:card=1 — 200, 97573 bytes
- https://creativecommons.org/licenses/by-sa/3.0/us/ — 200
- https://www.perseus.tufts.edu/js/hopper.js — 200
- https://www.perseus.tufts.edu/hopper/morph?l=e%29%2Fnnepe&la=greek&can=e%29%2Fnnepe0&prior=moi&d=Perseus:text:1999.01.0135:book=1:card=1&i=1 — 200, 15771 bytes
- https://raw.githubusercontent.com/PerseusDL/canonical/master/README.md — 200, official copyright section permits personal use by students, scholars, and the public and explicitly distinguishes varying object copyright status.

The live site copyright help URL returned 503 during audit; the official repository statement above is the explicit documented permission source. Unheadered morphology requests were unreliable; no inference of successful extraction is made from a failed request.

## Verdict: PASS
## Blocking: NO

Scope of approval: local, bounded research experiment and sourced text excerpts. Production dictionary integration or broad republication of morphology/voting data is not approved by this audit. Stage 2 must preserve actual downloaded bytes, request URL, timestamp, and hash; stages 3–4 must remain deterministic derivations from those bytes.
