# Audit: Download, parsing and transformation — Melos author profiles

## Step: 2–4
## Agent Action

Team A implemented `scripts/build_author_profiles.py` with separate fetch, extract and write commands, then fetched raw sources and generated `data/author-profiles/staged.json`. Publishing is not part of this approval.

## Audit Checks

- [x] Step 2 actual HTTP downloads: PASS. `fetch_one` executes `requests.Session.get`, raises on unsuccessful responses, saves response bytes, and writes response URL/status/time/SHA-256 receipts. Retryable errors are printed; exceptions propagate and are reported. Thirteen JSON summaries and three HTML sources exist with independent byte hashes matching all sixteen HTTP-200 receipts.
- [x] Step 3 source-only parsing: PASS. JSON biographies come from saved summary files, DCC text/title/byline from saved HTML parsed with BeautifulSoup, image descriptions/credits/licenses from the pre-existing source-backed portrait manifest. All thirteen biography values independently matched their raw sources; there are no manually authored biography rows.
- [x] Step 4 deterministic transformation: PASS. All thirteen excerpts are exact nonempty prefixes, at most 150 whitespace-separated words. Independent boundary selection reproduces every result, including the sole shortened excerpt, Bacchylides. Existing Greek names are read from repository application data; no transliteration or phonological mapping is introduced.
- [x] Attribution/provenance: PASS. Every biography's source URL, source title, revision URL and receipt fields match raw JSON/receipt inputs. The Wikipedia copyright HTML supports the extracted CC BY-SA 4.0 license link. DCC retains the unversioned CC BY-SA label and terms URL rather than assigning an unsupported version.
- [x] Portrait integrity: PASS. All ten selected image source hashes match. Artist, source, description, title, category, license, credit and download fields match the existing manifest. Sappho deliberately selects the same documented Alma-Tadema image as Alcaeus. Homer, Hesiod and Theocritus remain null rather than gaining invented portraits.
- [x] DCC exactness: PASS. Both Sappho and Alcaeus use the identical paragraph found in downloaded DCC HTML; the paragraph discusses both poets. Byline and page title are also present in that source. No paraphrase is inserted.

## Evidence

Independent read-only verification: `python data/author-profiles/audits/verify_staging.py`, exit 0. This checks every profile, exceeding the required ten-entry sample.

| Author | Source words | Excerpt words | Image | DCC passages |
| --- | --- | --- | --- | --- |
| Archilochus | 46 | 46 | Yes | 0 |
| Alcman | 92 | 92 | Yes | 0 |
| Sappho | 113 | 113 | Yes | 1 |
| Alcaeus | 75 | 75 | Yes | 1 |
| Stesichorus | 59 | 59 | Yes | 0 |
| Ibycus | 102 | 102 | Yes | 0 |
| Anacreon | 80 | 80 | Yes | 0 |
| Simonides | 80 | 80 | Yes | 0 |
| Pindar | 106 | 106 | Yes | 0 |
| Bacchylides | 189 | 110 | Yes | 0 |
| Homer | 75 | 75 | No | 0 |
| Hesiod | 23 | 23 | No | 0 |
| Theocritus | 17 | 17 | No | 0 |

The high unchanged-text ratio is intentional exact excerpt reuse, not an attempted linguistic conversion, so phonological transformation-reference requirements do not apply. The only content transformation is deterministic sentence-boundary truncation of one source prefix. Attribution labels, destination paths, excerpt descriptions and CSS focus coordinates are implementation metadata, not authored historical claims.

The prior source audit independently fetched the same summary sources and confirmed their titles/revisions. Download receipts and saved bytes support those real HTTP results. Existing portrait source metadata and its receipt were independently verified in step 1.

## Verdict: PASS
## Blocking: NO

Approval covers download, parsing and deterministic extraction only. Step 5 must verify published catalog/image bytes, and integration must verify visible attribution, rendering, accurate labels and the Sappho/Alcaeus figure selection. The `image_transform` field describes byte handling; CSS focus is separate presentation metadata and must not be represented as a newly downloaded cropped image.
