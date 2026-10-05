# Passage-analysis model and prediction audit

Independent audit, 2026-10-05. Scope: new syntax model assets and their use as machine predictions, not certification of philological correctness.

## Step 1: Source discovery

Agent action: selected OdyCy `grc_odycy_joint_trf` 0.7.0 as a practical CPU-installable candidate, not a demonstrated universal best parser.

Checks:

- PASS: the official [model API](https://huggingface.co/api/models/chcaa/grc_odycy_joint_trf?blobs=true) returned model identity `chcaa/grc_odycy_joint_trf` and revision `83046e93fa6b5dee122c3ca7cff1377512928143`.
- PASS: independently fetched the [revision-pinned model card](https://huggingface.co/chcaa/grc_odycy_joint_trf/raw/83046e93fa6b5dee122c3ca7cff1377512928143/README.md), HTTP 200. It declares MIT and version 0.7.0.
- PASS: the [official code license](https://raw.githubusercontent.com/centre-for-humanities-computing/odyCy/main/LICENSE) is MIT. This records upstream declarations; it does not independently relicense training texts.
- PASS: upstream wheel metadata specifies `grc_odycy_joint_trf-0.7.0-py3-none-any.whl`, 497,296,758 bytes, SHA-256 `8a828bb5d105e0f2d85d22479ab487fd9b5bacb9fdfb7098245e5e5aaefecd5e`.
- WARNING: model card specifies spaCy `>=3.7.4,<3.8.0`; local installed spaCy is reported as 3.8.7. Successful inference must be checked and this compatibility difference retained in provenance.
- WARNING: the planned adapter excludes `frequency_lemmatizer`. Published full-pipeline lemmatization metrics must not be attributed to this reduced pipeline.

Verdict: PASS for source discovery and permission to obtain assets. No accuracy or production-readiness certification.

## Steps 2–4: Download, extraction, transformation

Agent action: explicit setup script downloaded the pinned wheel and raw metadata; extracted model data without executing the wheel's custom Python factory.

Checks:

- PASS: independently hashed the actual downloaded wheel; size and SHA-256 match upstream. ZIP CRC test is clean.
- PASS: all four raw-artifact receipt entries have matching byte lengths and SHA-256 hashes. The receipt records verification UTC and the exact source URLs for model API metadata, model card, wheel, and separately fetched official code license.
- PASS: all 24 extracted model files were compared byte-for-byte against their wheel members; every comparison and per-file hash passed. No linguistic transformation or authored linguistic data was involved.
- PASS: the wheel contains no license file. The separate code-license download is explicitly distinguished from the model card's license declaration.
- BLOCKER FOUND: upstream `meta.json` has an empty license string. The initial generated provenance copied that blank value, which also made the adapter reject its own receipt. Required correction: obtain the model's declared MIT value from saved model card/API metadata, record that source, and retain the upstream blank field rather than pretending the wheel supplied a license.

Correction verified: model license now comes from saved pinned API `cardData.license` (`mit`); `license_basis` explicitly distinguishes the empty wheel field and separate code license. Receipt blocker resolved.

Verdict: PASS for acquisition and byte-preserving extraction.

## Steps 5–7: Real inference, integration, and cross-validation

Agent action: `scripts/verify_syntax_provider.py` reads two actual corpus records using SQLite `mode=ro`, disables socket connections before loading the model, and writes results only under ignored `runtime/models/odycy/`.

Checks:

- PASS: independently compared the saved inputs to corpus records `dcc-sappho:brothers-poem` and `dcc-sappho:frag-103:103Β`; exact equality and input SHA-256 checks pass.
- PASS: checked every emitted token, rather than a sample: all original-text slices and source hashes pass. Repeated words and all ten bracket tokens retain their proper source offsets; no letters were restored. The current normalized model view emits 130 tokens; its identity-input ablation emits 153.
- PASS: outputs are `contextual_prediction`, with exact model revision and runtime package versions. No source annotation promotion or corpus-write path is present in the setup/provider/verification code inspected.
- PASS: actual offline CPU inference completed with both normalized and identity model inputs. The current normalized run has 106 tokens for the Brothers Poem and 24 for the fragment. Observed timings are approximately 22.58 seconds for the first passage including cold loading and 0.19 seconds for the second passage. These are two observed timings, not a throughput or accuracy benchmark.
- PASS: runtime records spaCy 3.8.7, spaCy Transformers 1.3.9, Transformers 4.49.0, and Torch 2.6.0+cu124; adapter explicitly selects CPU. The unsupported-upstream spaCy version combination ran locally, but this is not a compatibility guarantee for other environments.
- RESOLVED INTEGRATION BLOCKER: the initial raw model treated some newline tokens as dependency roots and gave brackets ordinary word classes, including `[` with predicted lemma `[τε`. The adapter now preserves those raw predictions, marks nonlexical whitespace/editorial characters, suppresses their linguistic fields in the ordinary view, and marks attachments to them unresolved rather than silently repairing Greek text.

### Final model-view correction and ablation

Only CR, LF, and TAB are replaced by one U+0020 space each in the model input. The stored source is unchanged. This is a deterministic, same-codepoint-length analysis view, not a linguistic normalization. The adapter returns original source slices; optional `model_text` records differing token text. `parser_input_preprocessing` records the transform, changed-character count, and model-input hash; `model_input_identical` explicitly distinguishes model input from original source.

Independent checks passed: equal string lengths, exact transform whitelist, unchanged letters and editorial signs, model-input hashes, replacement counts, original-source token slices for both runs, and preservation of nonlexical raw predictions. No accent, letter, punctuation, editorial sign, or non-ASCII whitespace is normalized by this transform.

| Existing source | Replaced whitespace characters | Current tokens | Unresolved nonlexical heads, identity → normalized |
| --- | ---: | ---: | ---: |
| Brothers Poem | 19 | 106 | 17 → 0 |
| Fragment 103Β | 4 | 24 | 3 → 1 |

The current normalized fragment retains ten editorial tokens, all explicitly inapplicable as ordinary lexical predictions, with raw predictions preserved. Its remaining attachment to a nonlexical head is explicitly unresolved, not a root. Independently ran all 14 adapter unit tests, including original CR/LF/TAB span preservation: passing.

This ablation removes a demonstrated formatting artifact; fewer unresolved heads is not measured syntactic accuracy. A held-out lyric evaluation remains necessary. Preserving offsets and executing inference are not linguistic certification.

Verdict: PASS for model/source integrity and the adapter's explicit prediction contract. No remaining acquisition/integrity blocker. Browser presentation is a separate UI check. This audit does not certify the correctness of any Greek parse or justify importing predictions as gold annotations.
