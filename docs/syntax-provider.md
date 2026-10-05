# Local syntax provider

Melos uses the open-source **OdyCy transformer 0.7.0** as a replaceable local
dependency-parser baseline. Its output is a `contextual_prediction`, never a
source annotation, restored text, or a calibrated correctness probability. The
adapter returns one predicted parse and preserves every source spelling and
Python Unicode-codepoint offset. A selected fragment can lack the context needed
for a reliable attachment. Lyric, editorial supplements, gaps and ellipsis remain
particularly uncertain. The parser does not fill gaps or write into the corpus.
Whitespace and pure editorial-marker tokens retain exact spans but their model
grammar is marked inapplicable; audit-only `raw_prediction` retains the original
output. A word attached by the model to such a boundary has an explicitly unresolved
head rather than being presented as a root. Normal punctuation remains in the parse.

The parser sees a position-preserving analysis view in which CR, LF and tab each
become one ASCII space. Greek letters, combining marks and editorial signs are
untouched. Every returned token's `text` comes from the original source slice;
`model_text` is retained where it differs. `parser_input_preprocessing` records the
transform, replacement count and model-input hash, and `model_input_identical`
distinguishes unchanged model input from unchanged source storage. This avoids
treating line breaks as words while keeping original character positions.

## Selection and limits of the evidence

The [official OdyCy repository](https://github.com/centre-for-humanities-computing/odyCy)
and [model card](https://huggingface.co/chcaa/grc_odycy_joint_trf) provide a packaged
spaCy transformer pipeline trained on joint UD Ancient Greek data. The pinned
497,296,758-byte wheel makes CPU deployment feasible within this integration's
download budget. This is a viable baseline, not a finding that OdyCy is universally
best or that its benchmark scores measure correctness on Melos fragments.

[Celano 2025](https://aclanthology.org/2025.lm4dh-1.5/) found Trankit best for syntax
among the six model architectures in that AGDT-scheme experiment. Its released
[OGA parser](https://git.informatik.uni-leipzig.de/celano/morphosyntactic_parser_for_oga)
uses a customized Trankit distribution, pretokenized CoNLL input and an
XLM-RoBERTa backbone; it remains a strong candidate for a separate deployment and
comparative evaluation. Its AGDT scores cannot directly rank a UD parser on a
different test set. [greCy](https://github.com/jmyerston/greCy) also releases
transformer pipelines and reports competitive UD benchmarks, with the project's
own caveat about generalizing beyond its evaluation texts.

The current [Dilemma repository](https://github.com/open-greek/dilemma) was also
examined. It documents approximately 1.5 GB of tagger weights within a roughly
4.3 GB full installation, and a lemma lookup partly generated from paradigms.
Its documentation is not an independent benchmark establishing superiority for
fragmentary lyric. This integration imports none of its generated lookup forms
as attestations.

No new comparative accuracy evaluation has been performed. Local checks below
establish successful execution, source-offset fidelity and offline operation.

## Exact artifact and license

- Repository: `chcaa/grc_odycy_joint_trf`
- Revision: `83046e93fa6b5dee122c3ca7cff1377512928143`
- Wheel: `grc_odycy_joint_trf-0.7.0-py3-none-any.whl`
- SHA-256: `8a828bb5d105e0f2d85d22479ab487fd9b5bacb9fdfb7098245e5e5aaefecd5e`
- License: MIT, declared by the pinned Hugging Face model card/API. The wheel's
  `meta.json` license field is empty and it does not bundle a license file.
  The upstream **code** MIT license is separately retained, explicitly labelled.

The setup command saves the raw wheel, model card, API response and code license
under ignored `runtime/models/odycy/raw/`, including retrieval URLs, sizes and
SHA-256 receipts. It extracts unchanged model data and writes a per-file manifest
at `pipeline/melos-provenance.json`. It does not install or execute upstream
custom Python code. The custom `frequency_lemmatizer` component is excluded;
the trainable lemmatizer remains. Published full-pipeline lemma scores do not
apply unchanged to this configuration.

## Provisioning

Provision separately from public requests. Use an isolated environment and
install the optional requirements. On Linux, install a CPU PyTorch wheel from the
official PyTorch index before the requirements to avoid unnecessary CUDA packages.
Allow approximately 1.1 GB disk for retained wheel plus expanded model, plus the
Python runtime; measure RAM and latency on the intended host. The model alone is
too large for a small serverless function bundle. Run a persistent backend and
mount the preinstalled pipeline read-only when possible.

```powershell
py -3.13 -m venv runtime/venv-syntax
runtime/venv-syntax/Scripts/python -m pip install -r requirements.txt -r requirements-syntax.txt
runtime/venv-syntax/Scripts/python scripts/setup_syntax_provider.py --download
# Review the acquisition receipt before integration.
runtime/venv-syntax/Scripts/python scripts/setup_syntax_provider.py --extract
runtime/venv-syntax/Scripts/python scripts/verify_syntax_provider.py
runtime/venv-syntax/Scripts/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

The local validation environment was created with `--system-site-packages` to
reuse the already installed spaCy 3.8.7 and PyTorch 2.6.0+cu124 without modifying
global packages. Only optional transformer dependencies were installed inside
`runtime/venv-syntax`; it is a task environment, not a replacement for unrelated
OCR or other tools. Clean deployments should use a fully isolated environment.
CPU execution is explicitly selected even if the PyTorch build supports CUDA.

`MELOS_SYNTAX_MODEL_PATH` can point at another installed pipeline directory with
a valid Melos provenance receipt. Restart after changing this setting or repairing
a failed runtime. Default is `runtime/models/odycy/pipeline` relative to the repo.

Upstream specifies spaCy `>=3.7.4,<3.8.0`; local Python 3.13 validation used 3.8.7
and emitted spaCy's compatibility warning. This is an explicit compatibility
exception verified by actual inference, not proof of unchanged benchmark quality.
Exact spaCy, transformer plugin, Transformers and PyTorch versions are returned
with every prediction. Validate the same artifact in the deployment environment
before advertising that host as ready.

## Runtime and validation

`backend.syntax_provider.status()` performs no model load or download. It reports
`available` when artifacts/dependencies are present, `ready` only after successful
inference in that process, and visible unavailable/error states otherwise. Model
files are hash checked during first load. A process handles one prediction at a
time and immediately reports busy for additional concurrent calls. Inputs are
bounded to 4,096 Unicode codepoints and 256 model tokens. Runtime never downloads
models; loader flags require local transformer files.

The reproducible smoke check reads two existing source passages through a read-only
SQLite connection and blocks network connections before loading the parser. It
saves exact inputs, source IDs, hashes, prediction tokens and dependency heads at
`runtime/models/odycy/inference-verification.json`. It processes Sappho's Brothers
Poem (`dcc-sappho:brothers-poem`) and a bracketed Sappho fragment
(`dcc-sappho:frag-103:103Β`). It also runs the same model on identity-whitespace
input and reports unresolved boundary-head counts for both views. This is an
operational ablation, not a gold-standard accuracy evaluation; the first normalized
run includes cold load, so raw timings are not directly comparable. On the local
Windows host cold loading takes tens of seconds and warm short passages take
fractions of a second; the artifact records the actual timings for each run.

Unit checks in `tests/test_syntax_provider.py` cover non-BMP and combining Unicode,
repeated forms, punctuation, editorial brackets, unchanged source slices, bounds,
busy state, visible failure and absence of eager loading. Fake tokens in unit
tests are labelled test fixtures; readiness evidence comes from the separate real
model run. Deployment readiness and actual live deployment are separate checks.
