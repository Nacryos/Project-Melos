"""Replay approved source occurrences against a new context-window backend.

This checks context/offset contracts and reports model changes, not Greek
accuracy. Baseline requests and responses are actual saved production probes.
No Jev ranking, morphology fetch, authored gloss or reconstructed source text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_alcaeus_occurrences import Receipts


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def reading(result):
    rows = result["interlinear"]["readings"]
    assert len(rows) == 1, "This comparison expects one default reading"
    words = [t for t in rows[0]["tokens"] if t.get("kind") == "word"]
    assert len(words) == 1, "Expected one selected source word"
    return words[0]


def verify_comparisons(result, expected):
    """Verify the complete approved reader-only projection, including credits."""
    actual = (result.get("context") or {}).get("translation_comparisons")
    assert expected and expected.get("status") == "available", "Approved comparison unavailable locally"
    assert actual == expected, "Reader comparison differs from approved source projection"
    assert actual["scope"] == "whole_poem_other_edition"
    for field in ("selection_aligned", "exact_edition_alignment", "word_attestation", "line_attestation", "model_eligible"):
        assert actual[field] is False
    return actual["comparison_count"]


def verify(result, request, record, *, require_commentary=False, expected_comparisons=None):
    text = record["text"]
    a, b = request["start"], request["end"]
    assert text[a:b] == request["selected_text"] == result["selection"]["text"]
    assert result["passage"]["id"] == record["id"]
    assert result["passage"]["text_sha256"] == sha(text)
    assert result.get("ranking", {}).get("status") == "not_requested"
    assert result.get("sense_ranking", {}).get("status") == "not_requested"
    assert result.get("limits", {}).get("machine_fetches") == 0
    syntax = result["syntax"]
    assert syntax.get("state", syntax.get("status")) == "ready", "Actual syntax model did not run"
    x, y = syntax["context_start"], syntax["context_end"]
    assert type(x) is int and type(y) is int and 0 <= x <= a < b <= y <= len(text)
    assert y-x <= 2000 and syntax["scope"] in {"whole_passage", "bounded_context_window"}
    assert y-x > b-a, "A single word was still parsed without neighbors"
    if syntax["scope"] == "whole_passage":
        assert x == 0 and y == len(text)
    else:
        assert syntax.get("warnings"), "Partial context must disclose its boundary"
    selected_predictions = []
    for token in syntax.get("tokens", []):
        begin, end = token["start"], token["end"]
        assert type(begin) is int and type(end) is int and 0 <= begin < end <= y-x
        assert token["absolute_start"] == x+begin and token["absolute_end"] == x+end
        assert text[x+begin:x+end] == token["text"]
        assert token["selected"] == (x+begin < b and x+end > a)
        if token["selected"]:
            selected_predictions.append({key: token.get(key) for key in
                                         ("text", "lemma", "upos", "features", "head", "deprel")})
    assert selected_predictions, "No syntax token maps to the selected occurrence"
    # The projected context is interpretive only; it is not a translation or
    # an exact word annotation, even when a printed note mentions that word.
    commentary = (result.get("context") or {}).get("published_commentary")
    if require_commentary:
        assert commentary and commentary["status"] == "available"
        assert commentary["parent_id"] == record["id"]
        assert commentary["scope"] == "whole_poem_commentary"
        assert commentary["selection_aligned"] is False
        assert commentary["word_attestation"] is False
    comparison_count = verify_comparisons(result, expected_comparisons) if expected_comparisons is not None else None
    return {"context_scope": syntax["scope"], "context_characters": y-x,
            "context_start": x, "context_end": y, "context_sha256": sha(text[x:y]),
            "syntax_token_count": len(syntax.get("tokens", [])),
            "selected_predictions": selected_predictions,
            "commentary_status": commentary.get("status") if commentary else "absent",
            "commentary_paragraph_count": commentary.get("paragraph_count") if commentary else 0,
            "approved_translation_comparison_count": comparison_count}


def run(origin, baseline, output, *, require_commentary=False, require_comparisons=False):
    source_path = ROOT / "runtime/campbell-assignment/campbell_assignment.jsonl"
    records = {row["id"]: row for row in map(json.loads, source_path.read_text(encoding="utf-8").splitlines())}
    baseline_report = load(baseline / "report.json")
    baseline_hashes = {row["response_sha256"] for row in baseline_report["results"]}
    receipts = Receipts(origin, output / "receipts", timeout=180)
    results = []
    requests = sorted(baseline.glob("*.request.json"))
    assert len(requests) == 5, "Expected the five previously approved probes"
    for path in requests:
        request = load(path)
        assert request["rerank"] is False and request["fetch_machine"] is False
        prior_path = path.with_name(path.name.replace(".request.json", ".response.json"))
        assert hashlib.sha256(prior_path.read_bytes()).hexdigest() in baseline_hashes
        prior = load(prior_path)
        result, receipt = receipts.call("/api/analyze-passage", payload=request)
        record = records[request["passage_id"]]
        expected = None
        if require_comparisons:
            from backend.translation_comparisons import for_passage
            expected = for_passage(record)
            assert expected and expected.get("status") == "available"
        detail = verify(result, request, record, require_commentary=require_commentary, expected_comparisons=expected)
        old_word, new_word = reading(prior), reading(result)
        results.append({"form": request["selected_text"], "passage_id": request["passage_id"],
                        "receipt": receipt, "before_parse": old_word.get("parse_short"),
                        "after_parse": new_word.get("parse_short"),
                        "before_selection_basis": old_word.get("selection_basis"),
                        "after_selection_basis": new_word.get("selection_basis"),
                        "after_gloss": new_word.get("gloss"), **detail})
    report = {"scope": "Source-offset and neighboring-context contract; linguistic accuracy not established",
              "origin": origin, "baseline_origin": baseline_report["origin"],
              "request_count": len(results), "paid_ranking_requested": False, "results": results}
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output / "report.json"), "results": [
        {k: row[k] for k in ("form", "before_parse", "after_parse", "context_scope", "syntax_token_count",
                             "commentary_status")} for row in results]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--baseline", type=Path, default=ROOT / "runtime/lexical-release-d/live-root")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-commentary", action="store_true")
    parser.add_argument("--require-comparisons", action="store_true")
    args = parser.parse_args()
    run(args.origin, args.baseline, args.output, require_commentary=args.require_commentary,
        require_comparisons=args.require_comparisons)
