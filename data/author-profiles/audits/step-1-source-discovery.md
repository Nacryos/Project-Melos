# Audit: Source Discovery — Melos author profiles

## Step: 1
## Agent Action

Team A proposed extracting exact English Wikipedia REST summaries for 13 authors, reusing the existing ten sourced portraits, extracting a brief exact Dickinson College Commentaries passage, and using a sourced painting for Sappho.

## Audit Checks

- [x] Source existence and accessibility: PASS for the approved endpoints below, tested with real Python urllib HTTP GET requests on 2026-10-06 at approximately 06:58–07:02 UTC.
- [x] Authority: PASS. Wikipedia is the publisher of the proposed encyclopedic excerpts (not primary historical evidence). Dickinson College Commentaries publishes the named scholarly commentary. Wikimedia Commons provides image provenance and licensing metadata.
- [x] Reuse terms: PASS for exact Wikipedia excerpts with attribution and CC BY-SA 4.0 notice/link; PASS for the identified Commons public-domain painting; PASS for DCC text with its actual stated CC BY-SA label, explicit author credit, source and terms links. Do not invent a DCC license version.
- [x] Existing portrait provenance: PASS. All ten image SHA-256 values match local-preview/portraits.json. Its licenses agree with the stored Commons imageinfo metadata. The raw metadata SHA-256 matches the download receipt.
- [x] Identity control: PASS for Alma-Tadema's explicitly identified Sappho and Alcaeus depiction. Godward's painting is excluded as a Sappho portrait because the inspected source does not identify its woman as Sappho.

## Evidence

Wikipedia base URL: https://en.wikipedia.org/api/rest_v1/page/summary/

| Endpoint suffix | HTTP | Returned title | Revision |
| --- | --- | --- | --- |
| Sappho | 200 | Sappho | 1378068123 |
| Archilochus | 200 | Archilochus | 1370189772 |
| Alcman | 200 | Alcman | 1373638100 |
| Alcaeus_of_Mytilene | 200 | Alcaeus | 1377071688 |
| Stesichorus | 200 | Stesichorus | 1377484460 |
| Ibycus | 200 | Ibycus | 1370888588 |
| Anacreon | 200 | Anacreon | 1356303389 |
| Simonides | 200 | Simonides of Ceos | 1352230113 |
| Pindar | 200 | Pindar | 1377727951 |
| Bacchylides | 200 | Bacchylides | 1352970864 |
| Homer | 200 | Homer | 1377274758 |
| Hesiod | 200 | Hesiod | 1371158424 |
| Theocritus?redirect=true | 200 | Theocritus | 1371701734 |

All successful summary responses have type `standard` and nonempty extracts. The unparameterized Theocritus URL returned HTTP 429 twice; it is not approved as presently accessible. The explicitly tested `?redirect=true` URL is approved. This is a logged endpoint selection, not a silent data fallback.

- https://en.wikipedia.org/wiki/Wikipedia:Copyrights — HTTP 200, 226843 bytes. Its reuse section requires contributor attribution, a license notice/link, and indication of modifications. Attribution through the article URL is permitted. Preserve article URL, revision permalink, retrieval time, raw artifact and receipt; exact excerpts must remain traceable to downloaded JSON.
- https://commons.wikimedia.org/wiki/File:Sir_Lawrence_Alma-Tadema,_RA,_OM_-_Sappho_and_Alcaeus_-_Walters_37159.jpg — HTTP 200, 156109 bytes. Commons identifies Sappho and Alcaeus among depicted people, describes Alcaeus playing while Sappho listens, and identifies the 1881 painting, artist and Walters collection. The artwork and Walters digital reproduction are marked public domain. A selected detail must be described as a crop of this later artistic depiction, not an authenticated likeness; exact figure selection remains a later visual audit.
- https://dcc.dickinson.edu/sappho-introduction — HTTP 200, 57790 bytes. Introduction and notes credited to Heather Waddell. Contains an extractable paragraph under Sappho's Dialect.
- https://dcc.dickinson.edu/sappho-credits — HTTP 200, 49645 bytes. Confirms author attribution and academic background.
- https://dcc.dickinson.edu/terms-use — HTTP 200, 30191 bytes. Allows reproduction with explicit credit and sharing under the same terms. Labels its license CC BY-SA but points to the generic Creative Commons licenses index; no numbered version is established by this page. Retain that exact label and terms link. The page requests notification by email; this audit does not authorize sending mail.
- https://commons.wikimedia.org/wiki/File:Godward-In_the_Days_of_Sappho-1904.jpg — HTTP 200, 156966 bytes. Public-domain image availability confirmed, but source title is Reverie (also In the Days of Sappho) and does not identify the sitter as Sappho. Excluded from identified author-portrait use. Could only be considered as an explicitly labelled period-inspired illustration under a separately approved scope.

Existing local evidence: `local-preview/portraits.json`, `local-preview/raw/portraits/commons-imageinfo.json`, and `local-preview/raw/portraits/receipt.json`. The receipt records HTTP 200 at 2026-10-06T02:51:30.817021+00:00. Its raw metadata SHA-256 is `d2d96120f3d9d0c9ea2896139d52d546000003c50b2652e02042aa65f20cc5b8`, independently verified. All ten local image hashes match their manifest entries. Image licenses differ (CC BY 2.0, CC BY-SA 2.5, CC BY-SA 2.5 it, CC BY-SA 3.0, CC BY-SA 4.0, public domain); preserve per-image attribution and license instead of applying the biography license to images.

## Verdict: PASS
## Blocking: NO for the approved sources and stated scope

Godward portrait identification and the unparameterized Theocritus endpoint remain excluded. This report approves source discovery only; download, parsing, transformation, output and integration remain subject to separate audits. No biography text or dataset records were authored during this audit.
