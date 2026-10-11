# Latin scanner: parameters as hypotheses

Every parameter of `backend/scansion/rules_la.yaml` and `backend/scansion/metres_la.yaml` is a named hypothesis with
a default, a rival, the share measured on the development half (written by `scripts/scansion_eval_la.py` once the
calibration pass of LA2 lands) and a Goodhart check. Last updated 2026-10-10 19:45 PDT.

| Parameter | Default (hypothesis) | Rival | Measured (dev) | Goodhart check |
|---|---|---|---|---|
| `elision` | 0.98: Catullus and Horace elide whenever the environment allows | hiatus common after strong punctuation (`elision_after_strong_punct` 0.9) | pending calibration pass | the same rate on Horace Odes 1; false-accept rate on perturbed lines |
| `elision_before_interjection` | 0.6: before o / heu both happen (Luget' o 3.1; male! o 3.16) | 0.3 (hiatus the rule) | pending | — |
| `elision_monosyllable_long` | 0.75: a long monosyllable is often kept (semi-hiatus) | 0.98 (as any word) | pending | — |
| `prodelision` | 0.98 | — | pending | — |
| `mcl_word` | 0.2: muta cum liquida mostly short in neoteric and Augustan verse | 0.5 (Greek default) | pending | Horace vs Catullus separately |
| `mcl_boundary` | 0.05 | 0.5 | pending | — |
| `s_impura` | 0.15 | 0.9 (Greek POS-INIT) | pending (few cases: reported, not tuned) | — |
| `pos_initial` | 0.9 (gn-, ps-, mn-) | 0.5 | pending (Cnidum 36.13 is short) | — |
| `final_s_drop` | 0.02 | 0 | pending | — |
| `vowel_default` | 0.5 (honest) | measured share of unknown open vowels | pending | Brier on held-out |
| `vocal_before_vowel` | 0.1 | 0.2 | pending | — |
| `vav_genitive` | 0.5: -īus often short in Catullus (illĭus 3.8, unĭus 5.3) | 0.9 (prose rule) | pending | Horace separately |
| `final_a` | 0.5 (nom./abl. ambiguity) | lexicon / parse decides | pending | — |
| `final_e_short` / `final_e_long_list` | 0.05 / 0.85 with the YAML list | lexicon decides | pending | held-out adverbs (certē, lepidē) were missed by the list |
| `final_o_long` / `final_o_short_words` / `final_o_iambic` | 0.9 / 0.2 / 0.6 | all verb -ō long | pending | Catullus vs Horace |
| `final_i_long` / `final_i_either` / `final_i_short_list` | 0.95 / 0.5 / 0.1 | — | pending | — |
| `final_as` `final_os` `final_es` `final_is` `final_us` | 0.9 / 0.9 / 0.7 / 0.25 / 0.15 | lexicon decides | pending | — |
| `synizesis` / `synizesis_list` | 0.05 / 0.85 | none | pending | — |
| `iambic_shortening` | 0.3 (flag only) | — | pending | — |
| base priors (phalaecian) | spondee 0.80, trochee 0.14, iamb 0.05, pyrrhic 0.001 | flat | pending (per poem) | out-of-author (Martial, Statius) |
| `hiatus_violation_min` | 0.9 | 0.5 | — | false-accept rate |
| L11 verbatim run | 4 words (or 3 with 15 letters), as Greek | 5 words | — | — |

Rules (nodes) are hypotheses too; the error list in `docs/latin/eval-log.md` names the ones that failed and why.
