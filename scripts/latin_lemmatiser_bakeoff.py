#!/usr/bin/env python3
"""Lemmatiser bake-off on LASLA's hand-verified lemmas (data/private/lasla; CC BY-NC-SA, evaluation use only).

Candidates: (a) a form-lookup baseline trained on LASLA's Horace tokens (most frequent lemma per normalised form),
tested on Catullus: a genuinely held-out test; (b) LatinCy la_core_web_lg (spaCy) on the same sentences: LatinCy was
trained on LASLA among other data, so its score here is optimistic and is reported as such; (c) LatinCy on the tokens
whose form never occurs in Horace (out-of-vocabulary for the baseline). Lemmas are compared after normalisation
(lower case, u for v, i for j, trailing digits dropped). Tokens are compared one to one on LASLA's own tokenisation:
LatinCy runs on the sentence text with its enclitic splitter, and the comparison walks both token lists, matching on
the normalised form (a mismatch skips to the next match). Usage: .venv-nlp/bin/python scripts/latin_lemmatiser_bakeoff.py
-> docs/latin/lemma-bakeoff.json and a table on stdout."""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_lemma_index_la import read_conllup, LASLA  # noqa: E402


def norm(s: str) -> str:
    s = (s or "").lower().replace("v", "u").replace("j", "i")
    return re.sub(r"\d+$", "", s)


def sentences(files):
    out = []
    for f in files:
        for sent in read_conllup(LASLA / f):
            toks = []
            for t in sent:
                # LASLA splits enclitics into separate tokens (que, ne, ue); keep them, LatinCy splits them too
                toks.append((norm(t["form"]), norm(t["lemma"]), t["upos"]))
            out.append(toks)
    return out


def main():
    horace = [f for f in ("Horatius_Carmina_HorCarm1.conllup", "Horatius_Carmina_HorCarm2.conllup", "Horatius_Carmina_HorCarm3.conllup",
                          "Horatius_Carmina_HorCarm4.conllup", "Horatius_Epodi_HorEpodi.conllup", "Horatius_CarmenSaeculare_HorSaecu.conllup",
                          "Horatius_HorSermones_HorSerm1.conllup", "Horatius_HorSermones_HorSerm2.conllup",
                          "Horatius_HorEpistulae_HorEpis1.conllup", "Horatius_HorEpistulae_HorEpis2.conllup", "Horatius_ArsPoetica_HorArsPo.conllup")]
    train = sentences(horace)
    test = sentences(["Catullus_Catullus_Catul.conllup"])
    table: dict = defaultdict(Counter)
    for sent in train:
        for f, l, _ in sent:
            table[f][l] += 1
    lookup = {f: c.most_common(1)[0][0] for f, c in table.items()}
    n = right_lookup = covered = 0
    oov_tokens = []
    for sent in test:
        for f, l, _ in sent:
            n += 1
            if f in lookup:
                covered += 1
                right_lookup += lookup[f] == l
            else:
                oov_tokens.append((f, l))
    res = {"test": "LASLA Catullus (13,129 tokens, enclitics split)", "baseline": {
        "name": "form lookup, most frequent LASLA lemma, trained on LASLA Horace (45,007 tokens)",
        "coverage": round(covered / n, 4), "accuracy_on_covered": round(right_lookup / max(covered, 1), 4),
        "accuracy_overall_unknown_counted_wrong": round(right_lookup / n, 4), "oov_tokens": len(oov_tokens)}}
    try:
        import spacy
        t0 = time.time()
        nlp = spacy.load("la_core_web_lg")
        res["latincy"] = {"model": "la_core_web_lg " + str(nlp.meta.get("version")), "load_s": round(time.time() - t0, 1)}
        matched = right = 0
        oov_set = {f for f, _ in oov_tokens}
        oov_matched = oov_right = 0
        by_upos = defaultdict(lambda: [0, 0])
        errors = Counter()
        t1 = time.time()
        for sent in test:
            text = " ".join(f for f, _, _ in sent)
            doc = nlp(text)
            pred = [(norm(t.text), norm(t.lemma_)) for t in doc if not t.is_punct]
            i = 0
            for f, l, upos in sent:
                # walk to the next LatinCy token with this form
                j = i
                while j < len(pred) and pred[j][0] != f:
                    j += 1
                if j >= len(pred):
                    continue
                matched += 1
                ok = pred[j][1] == l
                right += ok
                by_upos[upos][0] += 1
                by_upos[upos][1] += ok
                if f in oov_set:
                    oov_matched += 1
                    oov_right += ok
                if not ok:
                    errors[(f, l, pred[j][1])] += 1
                i = j + 1
        res["latincy"].update({"tokens_matched": matched, "of": n, "accuracy": round(right / max(matched, 1), 4),
                               "accuracy_on_baseline_oov": round(oov_right / max(oov_matched, 1), 4), "oov_matched": oov_matched,
                               "seconds": round(time.time() - t1, 1),
                               "by_upos": {u: {"n": a, "acc": round(b / a, 3)} for u, (a, b) in sorted(by_upos.items(), key=lambda x: -x[1][0])[:10]},
                               "top_errors": [{"form": f, "gold": g, "pred": p, "n": c} for (f, g, p), c in errors.most_common(15)],
                               "caveat": "LatinCy's training data include LASLA, so this is not a held-out score; the baseline's is."})
    except Exception as exc:  # noqa: BLE001
        res["latincy"] = {"error": f"{type(exc).__name__}: {exc}"}
    out = ROOT / "docs" / "latin" / "lemma-bakeoff.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: (v if k != "latincy" else {x: y for x, y in v.items() if x not in ("top_errors", "by_upos")}) for k, v in res.items()}, indent=1))
    if "top_errors" in res.get("latincy", {}):
        print("top errors:", res["latincy"]["top_errors"][:8])
        print("by upos:", res["latincy"]["by_upos"])


if __name__ == "__main__":
    main()
