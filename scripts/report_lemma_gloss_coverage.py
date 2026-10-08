"""Lemma -> dictionary entry -> short English gloss coverage, before/after the supplement.

  python -I scripts/report_lemma_gloss_coverage.py \
      --machine-cache runtime/dev/machine_morphology.sqlite \
      --audit runtime/dev/audit-lexica-after/occurrences.json \
      --output runtime/dev/lemma-gloss-coverage.json

Lemmas come from (a) every parser (Morpheus) candidate in the cached receipts
and (b) optionally every display lemma and candidate lemma of a saved
scripts/audit_alcaeus_occurrences.py run. Each lemma is looked up as a printed
headword (backend.morphology.Morphology.headword_entries) twice: core files
only (production LSJ + Autenrieth) and core + data/lexica/supplement-entries.jsonl.
A lemma is covered when backend.lemma_glosses.choose finds one entry with an
extracted English definition and backend.short_gloss.short_head yields a
short gloss. Misses are reported with the reason. Read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.lemma_glosses import headword_key, resolve  # noqa: E402
from backend.machine_morphology import MachineMorphologyService  # noqa: E402
from backend.morphology import Morphology  # noqa: E402
from backend.short_gloss import short_head  # noqa: E402

NO_FORMS = ROOT / "data" / "lexica" / "__no_forms__.jsonl"


def machine_lemmas(path: Path) -> Counter:
    import sqlite3
    service = MachineMorphologyService(path)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        receipts = [(rid, json.loads(meta).get("request_form")) for rid, meta in
                    db.execute("SELECT id, metadata FROM receipts")]
    lemmas = Counter()
    for receipt_id, form in receipts:
        try:
            result = service.load_receipt(receipt_id, form=form)
        except Exception:
            continue
        for candidate in result.get("machine_candidates") or []:
            if candidate.get("lemma"):
                lemmas[unicodedata.normalize("NFC", candidate["lemma"])] += 1
    return lemmas


def audit_lemmas(path: Path) -> Counter:
    rows = json.loads(path.read_text(encoding="utf-8"))
    lemmas = Counter()
    for row in rows:
        if row.get("editorial_fragment") or row.get("partial_word") or row.get("damaged_piece"):
            continue
        display = row.get("display") or {}
        if display.get("lemma"):
            lemmas[unicodedata.normalize("NFC", display["lemma"])] += 1
        for candidate in [*row.get("candidates", []), *row.get("cached_machine_candidates", [])]:
            if candidate.get("lemma"):
                lemmas[unicodedata.normalize("NFC", candidate["lemma"])] += 1
    return lemmas


def check(morphology: Morphology, lemma: str) -> dict:
    entry, senses, info = resolve(lemma, {"text": lemma, "features": {}}, morphology.headword_entries)
    short = short_head(senses[0]["text"]) if entry else None
    if short:
        return {"status": "covered", "entries": len(info["entry_ids"]), "dictionary": entry["source"],
                "short_gloss": short["text"], "definition": senses[0]["text"], "match": info.get("headword_match"),
                "via_cross_reference": info.get("cross_reference", {}).get("target_headword")}
    capital = headword_key(lemma)[:1].isupper()
    if not info["entry_ids"]:
        reason = "proper_name_no_headword" if capital else "no_headword_in_any_dictionary"
    elif any(item["reason"] == "homograph_entries_unresolved" for item in info["skipped"]):
        reason = "homograph_entries_unresolved"
    else:
        reason = ("proper_name_entry_without_english_definition" if capital
                  else "entry_without_extracted_english_definition")
    return {"status": "miss", "reason": reason, "entries": len(info["entry_ids"]),
            "entry_ids": info["entry_ids"][:8], "skipped": info["skipped"],
            "cross_reference": info.get("cross_reference")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--machine-cache", type=Path, action="append", default=[])
    parser.add_argument("--audit", type=Path, action="append", default=[])
    parser.add_argument("--supplement", type=Path, default=ROOT / "data/lexica/supplement-entries.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    lemmas: Counter = Counter()
    for path in args.machine_cache:
        lemmas.update(machine_lemmas(path))
    for path in args.audit:
        lemmas.update(audit_lemmas(path))
    # Ending-pattern stubs ("-τος", backend/pattern_morphology.py) are not lemmas.
    lemmas = Counter({k: v for k, v in lemmas.items()
                      if re.search(r"[Ͱ-Ͽἀ-῿]", k) and not k.startswith("-")})
    core = Morphology(ROOT / "data/lexica/entries.jsonl", NO_FORMS)
    full = Morphology(ROOT / "data/lexica/entries.jsonl", NO_FORMS, supplement_paths=[args.supplement])
    rows = {}
    for lemma in sorted(lemmas):
        rows[lemma] = {"occurrences": lemmas[lemma], "before": check(core, lemma), "after": check(full, lemma)}
    summary = {}
    for phase in ("before", "after"):
        statuses = [row[phase] for row in rows.values()]
        summary[phase] = {"lemmas": len(statuses),
                          "covered": sum(s["status"] == "covered" for s in statuses),
                          "with_any_entry": sum(s["entries"] > 0 for s in statuses),
                          "miss_reasons": dict(Counter(s.get("reason") for s in statuses if s["status"] == "miss")),
                          "gloss_dictionaries": dict(Counter(s.get("dictionary") for s in statuses
                                                             if s["status"] == "covered"))}
    report = {"summary": summary, "inputs": {"machine_cache": [str(p) for p in args.machine_cache],
                                             "audit": [str(p) for p in args.audit],
                                             "supplement": str(args.supplement)},
              "lemmas": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for lemma, row in rows.items():
        if row["after"]["status"] == "miss":
            print("MISS", lemma, row["after"]["reason"], row["after"]["entries"])


if __name__ == "__main__":
    main()
