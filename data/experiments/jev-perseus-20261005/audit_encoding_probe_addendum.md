# Audit: Bounded encoding probes — source availability

## Steps: 2, 6, 7 addendum
## Agent Action

Following explicit parent authorization, Team A tried three percent-encoded versions of failed occurrence URLs and retained separate probe plan, results, and raw artifacts. Query parameter values were preserved; no alternate linguistic source or invented candidates were introduced.

## Audit Checks

- [x] Three probe results all report HTTP 503 and contribute no extracted cases.
- [x] cases.json remains byte-identical to the hash approved in audit_extraction_final.md.
- [x] download_manifest.json now covers all 15 raw metadata files, including eight HTTP 503 responses and seven HTTP 200 responses.
- [x] Every manifest artifact independently checked for byte count and SHA-256 agreement.

## Verdict: PASS
## Blocking: NO

The original data-integrity approval remains valid: one previously inspected positive control, zero fresh cases. These availability probes do not increase the evidentiary sample.
