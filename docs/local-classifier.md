# Local contextual classifier probe

The local language model is an **experimental evidence reranker**, not a source
of Greek text or scholarly claims. It may select an existing candidate ID or
abstain. Its outputs live in `data/reports/local-classifier.json`, separate from
`data/claims/` and `data/processed/`. Model scores, if exposed later, would not
be calibrated probabilities of philological truth.

## Runtime and model choice

This Windows machine has a laptop RTX 3070 (8,192 MiB), Python 3.13, CUDA
PyTorch 2.6.0, and Transformers. No Ollama or llama.cpp command or local service
listener was available. BGE-M3 is the existing passage encoder. The local
classifier adapter in `backend/local_classifier.py` imports no model library or
weights when its status is queried; it loads only on an explicit `decide()`
call. The user-facing classifier remains disabled by default because the pilot
cannot validate Ancient Greek accuracy.

The tested models are pinned under the ignored project cache:

| Model | Revision | Weight bytes | License | Purpose |
| --- | --- | ---: | --- | --- |
| [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | `c1899de289a04d12100db370d81485cdf75e47ca` | 1,503,300,328 | Apache 2.0 | Small baseline, failed pilot |
| [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` | 4,063,515,592 | Apache 2.0 | Larger bounded diagnostic and explicit provider |

The [Qwen3 model cards](https://huggingface.co/Qwen/Qwen3-1.7B) claim support
for 100+ languages and document a non-thinking chat mode. They provide no
Ancient Greek benchmark. [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
is another Apache 2.0 option with a smaller, 29+ language claim; no Ancient
Greek result justifies treating it as better. Google's
[Gemma 3 1B](https://huggingface.co/google/gemma-3-1b-it) is gated behind
license acceptance, so it was not downloaded. The choice to test Qwen3 reflects
transparent licensing, local Transformers support, and the hardware budget;
recency alone is not evidence of philological quality.

## Reproduce the diagnostics

From the Melos project directory:

```powershell
py -3.13 scripts/probe_local_classifier.py --model 0.6b --download-only
py -3.13 scripts/probe_local_classifier.py --model 0.6b --dcc-fixtures
py -3.13 scripts/probe_local_classifier.py --model 1.7b --download-only
py -3.13 scripts/probe_local_classifier.py --model 1.7b --dcc-fixtures --append
py -3.13 scripts/probe_local_classifier.py --model 1.7b --context-fixtures
```

The first fixture set uses the accepted saved DCC Sappho fragment 1 Greek and
notes, verifies the raw HTML SHA-256, and asks which of eight note lines
directly addresses three source-appearing forms and one absent form. Expected
answers are derived by exact substring match; these are **synthetic evaluation
queries**, not historical data entries. The second set builds the classifier's
real evidence packet from staged `p2_notes` source claims: source-supported
`πέμπην` morphology, competing attributed interpretations of `ἔλθην`, and
two unresolved `ἔχη` token locations. The latter two expect abstention.
Those staged claims are diagnostic inputs pending independent audit, not
accepted model output or new corpus evidence.

## Measured results and limits

| Diagnostic | Schema-valid | Fixture matches | Latency | GPU peak |
| --- | ---: | ---: | --- | ---: |
| Qwen3-0.6B, DCC 4 cases | 2/4 | 1/4 | 5.95–7.26 s/case; 4.51 s load | 2,129 MiB PyTorch allocated |
| Qwen3-1.7B, same DCC cases | 2/4 strict; 4/4 after stripping an exact JSON code fence | 4/4 after that formatting normalization | 8.59–19.42 s/case; 19.49 s load | 4,582 MiB PyTorch allocated |
| Qwen3-1.7B, staged claim-context cases | 3/3 bounded choice schema | **1/3**: 1 explicit morphology correct, 0/2 abstentions correct | 44.67 s first call including load, then 1.91 and 1.40 s | same model; about 5.6 GB total device use in DCC run |

The 0.6B model chose a note for the absent form and returned invalid evidence
IDs in two cases. The 1.7B model handled that simple absent-form case and all
three positive note matches, but twice wrapped valid JSON in a code fence
despite the prompt. The provider accepts only a complete fenced JSON block
and still rejects unknown candidate IDs.

The more relevant claim-context test exposed a substantive weakness: 1.7B
selected the directly sourced `πέμπην` morphology, then chose one of three
competing editorial interpretations of `ἔλθην` and one of two unresolved `ἔχη`
token offsets. Both latter choices should have abstained. The exact model
strings, evidence IDs, source URLs, timings, and expected labels are preserved
in the report. These are a few synthetic evaluation decisions over saved
sources, not a held-out Ancient Greek benchmark. They support leaving local
classification disabled in the user interface. `local_model_status()` reports
`validated: false` and `recommended: false`; the larger model remains an
explicit research adapter only.

The 1.7B model used about 5.6 GB of device memory overall during the DCC run.
Its adapter checks for at least 5 GB free GPU memory before loading, so it may
refuse a request while the BGE-M3 encoder occupies the same 8 GB GPU. No CPU
latency was measured. The model process exited after the benchmark; there is
no installed service or paid API dependency.
