"""Read-only, reproducible coverage audit of source-supplied assignment records.

Usage: python tests/audit_alcaeus_assignment.py --records path.jsonl --base URL
No Greek/English content is authored here. Corpus text comes from the supplied
record artifact and is compared byte-for-byte with the API. Requests and full
responses are saved for review. No model reranking or machine fetch is requested.
Coverage is not an accuracy score: fuzzy alternatives do not count as exact parses.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.passage_analysis import MAX_CHARACTERS, MAX_WORDS, tokenize_span, utf16_offset, codepoint_offset


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def greek_letter_present(value):
    return any(unicodedata.category(c).startswith("L") and "GREEK" in unicodedata.name(c, "") for c in value)


def editorial_span(text, start, end):
    selected = text[start:end]
    if any(c in "[]<>⟨⟩†‡…\u0323" for c in selected) or re.search(r"(?:\.\s*){2,}", selected):
        return True
    # A query cut at a bracket-adjacent source word is not an intact phrase.
    if (start and text[start-1] in "[]<>⟨⟩") or (end < len(text) and text[end] in "[]<>⟨⟩"):
        return True
    return any(t.get("editorial_fragment") or t.get("partial_word") for t in tokenize_span(text, start, end))


def exact_candidate(candidate):
    """Mirror the strict exactness boundary in js/dictionary-preview.js."""
    rejected = (candidate.get("quarantined") is True or candidate.get("source_consistent") is False
                or candidate.get("source_inconsistent") is True or candidate.get("assertion_type") == "model_inference"
                or any(re.search(r"quarantin|inconsisten|rejected|needs_review|machine_proposed", str(candidate.get(key, "")), re.I)
                       for key in ("status", "quality", "link_status", "lemma_link_status")))
    return (not rejected and type(candidate.get("edit_distance")) in (int, float)
            and candidate["edit_distance"] == 0 and candidate.get("match_kind") in ("indexed_form", "lexicon_headword")
            and bool(candidate.get("lemma")))


def display_dictionary_counts(directory):
    """Execute the real frontend projection on cached responses, not a gloss heuristic."""
    javascript = r"""
const fs = require('node:fs');
global.window = {};
require(process.argv[1]);
const output = [];
const responses = fs.readdirSync(process.argv[2]).map(name => JSON.parse(fs.readFileSync(require('node:path').join(process.argv[2], name), 'utf8')));
const wiki = new Map(responses.filter(r => r.request.route === '/api/wiktionary' && r.http_status === 200).map(r=>[r.request.params.form,r.body]));
for (const r of responses) {
  if (r.request.route !== '/api/word' || r.http_status !== 200) continue;
  const only = window.MelosDictionaryPreview.buildPreview(r.body);
  const view = window.MelosDictionaryPreview.buildPreview(r.body, wiki.get(r.request.params.form));
  output.push({form: r.request.params.form, passage_id:r.request.params.passage_id,
    word_only_dictionary_preview_entries:only.entries.length,
    dictionary_preview_entries:view.entries.length,
    dictionary_preview_meanings:view.entries.reduce((n,e)=>n+e.meanings.length,0)});
}
process.stdout.write(JSON.stringify(output));
"""
    completed = subprocess.run(["node", "-e", javascript, str(ROOT / "js/dictionary-preview.js"), str(directory)],
                               check=True, capture_output=True, encoding="utf-8")
    return {(row["form"], row["passage_id"]): row for row in json.loads(completed.stdout)}


class API:
    def __init__(self, base, directory, timeout=120, refresh=False):
        self.base, self.directory, self.timeout, self.refresh = base.rstrip("/"), directory, timeout, refresh
        directory.mkdir(parents=True, exist_ok=True)

    def call(self, route, params=None, payload=None, *, refresh=False):
        request = {"base": self.base, "route": route, "params": params, "payload": payload}
        key = digest(json.dumps(request, sort_keys=True, ensure_ascii=False))
        path = self.directory / f"{key}.json"
        if path.exists() and not self.refresh and not refresh:
            return json.loads(path.read_text(encoding="utf-8"))
        url = self.base + route + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "Melos-assignment-readonly-QA/1"})
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body, status = response.read(), response.status
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {"non_json_body": body.decode("utf-8", errors="replace")}
            result = {"request": request, "http_status": status, "body": parsed}
        except urllib.error.HTTPError as error:
            result = {"request": request, "http_status": error.code, "error": error.read().decode("utf-8", errors="replace")}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            result = {"request": request, "http_status": None, "error": str(error)}
        result.update({"seconds": round(time.monotonic()-start, 3), "recorded_at_unix": time.time()})
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def source_records(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        records = data if isinstance(data, list) else data.get("records", data.get("results", []))
    return [record for record in records if record.get("language") == "grc" and record.get("kind", "text") == "text"]


def source_integrity(text):
    tokens = tokenize_span(text, 0, len(text))
    words = [token for token in tokens if token["kind"] == "word"]
    assert "".join(token["text"] for token in tokens) == text
    for token in tokens:
        assert text[token["start"]:token["end"]] == token["text"]
        assert codepoint_offset(text, token["start_utf16"], "utf16") == token["start"]
        assert codepoint_offset(text, token["end_utf16"], "utf16") == token["end"]
    windows = 0
    # Every contiguous word-boundary range, including ones too large for API.
    # This proves offset/source preservation, not morphology or translation.
    for first in words:
        for last in words:
            if last["end"] <= first["start"]:
                continue
            a, b = first["start"], last["end"]
            assert codepoint_offset(text, utf16_offset(text, a), "utf16") == a
            assert codepoint_offset(text, utf16_offset(text, b), "utf16") == b
            windows += 1
    return {"tokens": len(tokens), "words": len(words), "word_boundary_ranges": windows,
            "editorial_fragments": sum(bool(w.get("editorial_fragment")) for w in words),
            "isolated_mark_tokens": sum(not greek_letter_present(w["text"]) for w in words),
            "text_sha256": digest(text), "passed": True}, words


def sampled_spans(text, words):
    spans = {}
    def add(a, b, label):
        selected = text[a:b]
        count = sum(t["kind"] == "word" for t in tokenize_span(text, a, b))
        if 1 <= count <= MAX_WORDS and len(selected) <= MAX_CHARACTERS:
            spans[(a, b)] = label
    for width in (2, 4, 8):
        for index in sorted({0, max(0, (len(words)-width)//2), max(0, len(words)-width)}):
            if index + width <= len(words):
                add(words[index]["start"], words[index+width-1]["end"], f"{width}_word_window")
    offset = 0
    lines = []
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if content.strip():
            lines.append((offset, offset+len(content)))
        offset += len(line)
    for index in sorted({0, len(lines)//2, len(lines)-1}):
        if 0 <= index < len(lines):
            add(*lines[index], "full_line")
    add(0, len(text), "full_passage")
    return [(a, b, label) for (a, b), label in spans.items()]


def machine_pilot(records, base, audit_directory, output):
    """Explicit opt-in, at most three quota-respecting exact Morpheus requests."""
    from backend.machine_morphology import validate_form
    existing = {}
    for path in (audit_directory / "responses").glob("*.json"):
        response = json.loads(path.read_text(encoding="utf-8"))
        if response["request"]["route"] == "/api/word" and response["http_status"] == 200:
            existing[response["request"]["params"]["form"]] = response["body"]
    selected = []
    seen = set()
    for record in records:
        text = record["text"]
        words = [t for t in tokenize_span(text, 0, len(text)) if t["kind"] == "word"]
        for index, token in enumerate(words):
            form = token["text"]
            if form in seen or form not in existing or token.get("editorial_fragment") or token.get("partial_word") or len(form) < 5 or form[0].isupper():
                continue
            seen.add(form)
            if any(exact_candidate(c) and c.get("analysis") for c in existing[form].get("candidates", [])):
                continue
            try:
                validate_form(form)
            except ValueError:
                continue
            selected.append((record, form, words[max(0, index-1)]["start"], words[min(len(words)-1, index+1)]["end"]))
            if len(selected) == 3:
                break
        if len(selected) == 3:
            break
    if not selected:
        raise ValueError("No source-derived complete missing forms eligible for bounded pilot")
    api = API(base, output / "responses", refresh=True)
    before_api = API(base, output / "before", refresh=True)
    after_api = API(base, output / "after", refresh=True)
    results = []
    for record, form, a, b in selected:
        text = record["text"]
        payload = {"version": 1, "passage_id": record["id"], "start": utf16_offset(text, a), "end": utf16_offset(text, b),
                   "offset_unit": "utf16", "selected_text": text[a:b], "rerank": False, "fetch_machine": False}
        before = before_api.call("/api/analyze-passage", payload=payload)
        result = api.call("/api/machine-analysis", payload={"form": form, "passage_id": record["id"]})
        after = after_api.call("/api/analyze-passage", payload=payload)
        def projection(response):
            body = response.get("body", {})
            return {"http_status": response["http_status"], "meaning": body.get("meaning"), "interlinear": body.get("interlinear"),
                    "machine": [t.get("machine") for t in body.get("tokens", []) if t.get("text") == form]}
        results.append({"form": form, "passage_id": record["id"], "start": a, "end": b, "selected_text": text[a:b],
                        "before": projection(before), "request": result, "after": projection(after)})
        print(json.dumps({"form": form, "http_status": result["http_status"], "machine_status": result.get("body", {}).get("status"),
                          "candidates": len(result.get("body", {}).get("machine_candidates", []))}, ensure_ascii=True), flush=True)
        # Do not retry or work around upstream/per-visitor limits.
        if result["http_status"] in (409, 429) or result.get("body", {}).get("status") in ("rate_limited", "busy", "upstream_error"):
            break
    (output / "pilot.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def recheck_pilot(records, base, pilot_path, output):
    """Fresh phrase projection only: consume retained cache, no parser/LLM fetch."""
    prior = json.loads(pilot_path.read_text(encoding="utf-8"))
    corpus = {r["id"]: r for r in records}
    api = API(base, output / "responses", refresh=True)
    results = []
    for row in prior:
        record = corpus[row["passage_id"]]
        text, a, b = record["text"], row["start"], row["end"]
        if text[a:b] != row["selected_text"]:
            raise ValueError("Pilot selection no longer matches final source text")
        response = api.call("/api/analyze-passage", payload={"version": 1, "passage_id": record["id"],
            "start": utf16_offset(text, a), "end": utf16_offset(text, b), "offset_unit": "utf16",
            "selected_text": text[a:b], "rerank": False, "fetch_machine": False})
        body = response.get("body", {})
        projected = [token for reading in body.get("interlinear", {}).get("readings", [])
                     for token in reading.get("tokens", []) if token.get("text") == row["form"]]
        result = {"form": row["form"], "passage_id": record["id"], "text_sha256": digest(text),
                  "http_status": response["http_status"], "source_preserved": "".join(t["text"] for t in body.get("tokens", [])) == text[a:b],
                  "projected_tokens": projected, "meaning": body.get("meaning"),
                  "machine": [t.get("machine") for t in body.get("tokens", []) if t.get("text") == row["form"]]}
        results.append(result)
        print(json.dumps({"form": row["form"], "http_status": response["http_status"],
            "projected_tokens": [{"lemma": t.get("lemma"), "status": t.get("status"),
                "selection_basis": t.get("selection_basis"), "gloss": t.get("gloss", {}).get("text"),
                "alternatives": len(t.get("candidate_meanings", []))} for t in projected]}, ensure_ascii=True), flush=True)
    (output / "pilot-recheck.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--base", default="https://greeklyric.com")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/alcaeus-assignment-qa")
    parser.add_argument("--offline", action="store_true", help="Only exact-text span integrity; no API calls")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-catalogue", action="store_true", help="Refresh passage/ref navigation after a metadata-only correction; reuse lexical/span receipts")
    parser.add_argument("--refresh-phrases", action="store_true", help="Refresh all sampled analysis and phrase-search receipts")
    parser.add_argument("--lexical-reuse-provenance", type=Path, help="Integrator evidence that word/Wiktionary modules and lexical data are unchanged")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--word-limit", type=int, default=0, help="Diagnostic partial run only; zero means all unique forms")
    parser.add_argument("--no-phrases", action="store_true")
    parser.add_argument("--machine-pilot-from", type=Path, help="Explicitly run at most3 source-parser fetches for missing forms from an existing audit; no LLM calls")
    parser.add_argument("--recheck-pilot", type=Path, help="Recheck prior pilot phrase projections without any parser or LLM fetch")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    api = API(args.base, args.output / "responses", args.timeout, args.refresh)
    records = source_records(args.records)
    if not records:
        raise ValueError("No Greek text records in supplied artifact; refusing an empty audit.")
    if args.machine_pilot_from:
        machine_pilot(records, args.base, args.machine_pilot_from, args.output)
        return
    if args.recheck_pilot:
        recheck_pilot(records, args.base, args.recheck_pilot, args.output)
        return
    report = {"base": args.base, "source_artifact": str(args.records.resolve()), "source_artifact_sha256": hashlib.sha256(args.records.read_bytes()).hexdigest(),
              "accuracy_claim": False, "paid_model_calls": 0, "records": [], "word_lookups": [], "phrase_checks": []}
    if args.lexical_reuse_provenance:
        proof = args.lexical_reuse_provenance.read_bytes()
        report["lexical_cache_reuse_provenance"] = {"path": str(args.lexical_reuse_provenance.resolve()),
            "sha256": hashlib.sha256(proof).hexdigest(), "evidence": json.loads(proof)}
    record_by_id = {record["id"]: record for record in records}
    forms = {}
    available = []
    for record in records:
        text, identifier = record["text"], record["id"]
        integrity, words = source_integrity(text)
        item = {"id": identifier, "citation": record.get("citation"), "source_integrity": integrity}
        if not args.offline:
            response = api.call("/api/passage", {"id": identifier}, refresh=args.refresh_catalogue)
            item["http_status"] = response["http_status"]
            item["api_exact_text"] = response.get("body", {}).get("text") == text
            if item["http_status"] == 200 and item["api_exact_text"]:
                fragment = record.get("metadata", {}).get("assignment_fragment") or identifier.rsplit(":", 1)[-1]
                reference = api.call("/api/search", {"q": f"Alcaeus {fragment}", "mode": "words", "limit": 100}, refresh=args.refresh_catalogue)
                reference_body = reference.get("body", {})
                item["reference_search"] = {"http_status": reference["http_status"], "query": f"Alcaeus {fragment}",
                    "target_in_results": any(r.get("id") == identifier for r in reference_body.get("results", [])),
                    "returned_ids": [r.get("id") for r in reference_body.get("results", [])]}
                available.append((record, words))
                for word in words:
                    if not word.get("editorial_fragment") and not word.get("partial_word") and greek_letter_present(word["text"]):
                        forms.setdefault(word["text"], identifier)
        report["records"].append(item)
    for index, (form, identifier) in enumerate(forms.items()):
        if args.word_limit and index >= args.word_limit:
            break
        response = api.call("/api/word", {"form": form, "passage_id": identifier})
        wiki_response = api.call("/api/wiktionary", {"form": form, "limit": 8})
        body = response.get("body", {})
        candidates = body.get("candidates", [])
        exact = [c for c in candidates if exact_candidate(c)]
        context_text = (body.get("context") or {}).get("text")
        report["word_lookups"].append({"form": form, "passage_id": identifier, "http_status": response["http_status"],
            "context_text_sha256": digest(context_text) if isinstance(context_text, str) else None,
            "context_text_matches_source": context_text == record_by_id[identifier]["text"],
            "lookup_scope": "uncertain_printed_letters" if "\u0323" in form else "printed_lookup_segment",
            "wiktionary_http_status": wiki_response["http_status"], "wiktionary_ready": wiki_response.get("body", {}).get("ready"),
            "analysis_match_status": body.get("analysis_match_status"), "match_status": body.get("match_status"),
            "candidate_count": len(candidates), "exact_candidate_count": len(exact),
            "exact_parse_count": sum(bool(c.get("analysis")) for c in exact),
            "lexicon_entry_count": len(body.get("lexicon_entries", [])),
            "exact_lemmas": list(dict.fromkeys(c.get("lemma") for c in exact)), "warnings": body.get("warnings", []), "seconds": response["seconds"]})
        print(f"word {index+1}/{len(forms)} status={response['http_status']}", flush=True)
    if not args.offline and not args.no_phrases:
        for record, words in available:
            text, identifier = record["text"], record["id"]
            for a, b, label in sampled_spans(text, words):
                selected = text[a:b]
                payload = {"version": 1, "passage_id": identifier, "start": utf16_offset(text, a), "end": utf16_offset(text, b),
                           "offset_unit": "utf16", "selected_text": selected, "rerank": False, "fetch_machine": False}
                response = api.call("/api/analyze-passage", payload=payload, refresh=args.refresh_phrases)
                body = response.get("body", {})
                returned = body.get("tokens", [])
                result = {"passage_id": identifier, "label": label, "start": a, "end": b, "selected_text": selected,
                          "editorial_span": editorial_span(text, a, b),
                          "http_status": response["http_status"], "source_preserved": "".join(t["text"] for t in returned) == selected,
                          "selection_preserved": body.get("selection", {}).get("text") == selected,
                          "word_count": sum(t["kind"] == "word" for t in returned), "syntax_status": body.get("syntax", {}).get("status"),
                          "meaning_status": body.get("meaning", {}).get("status"), "seconds": response["seconds"]}
                # Search a small bounded sample rather than every exponential combination.
                if label in ("4_word_window", "full_line"):
                    result["search"] = {}
                    for mode in ("words", "forms"):
                        search = api.call("/api/search", {"q": selected, "mode": mode, "match": "exact", "author": record["author"], "limit": 100}, refresh=args.refresh_phrases)
                        search_body = search.get("body", {})
                        results = search_body.get("results", [])
                        result["search"][mode] = {"http_status": search["http_status"], "total": search_body.get("total"),
                            "target_in_results": any(r.get("id") == identifier for r in results),
                            "same_exact_text_in_results": any(r.get("text") == text for r in results),
                            "returned_ids": [r.get("id") for r in results]}
                report["phrase_checks"].append(result)
                print(f"phrase {identifier} {label} status={response['http_status']}", flush=True)
    words_report, phrases = report["word_lookups"], report["phrase_checks"]
    if words_report:
        previews = display_dictionary_counts(api.directory)
        for row in words_report:
            row.update(previews.get((row["form"], row["passage_id"]), {"dictionary_preview_entries": 0, "dictionary_preview_meanings": 0}))
    report["summary"] = {"records": len(records), "available_exact": len(available), "unique_lookup_forms": len(forms),
        "unique_nonunderdotted_lookup_segments": sum("\u0323" not in f for f in forms),
        "word_forms_tested": len(words_report), "word_http_success": sum(w["http_status"] == 200 for w in words_report),
        "forms_with_exact_parse": sum(w["exact_parse_count"] > 0 for w in words_report),
        "word_contexts_bound_to_exact_source": sum(w["context_text_matches_source"] for w in words_report),
        "forms_with_displayable_dictionary": sum(w["dictionary_preview_entries"] > 0 for w in words_report),
        "word_statuses": dict(Counter(w["analysis_match_status"] for w in words_report)),
        "phrase_requests": len(phrases), "phrase_http_success": sum(p["http_status"] == 200 for p in phrases),
        "phrase_lossless": sum(p["source_preserved"] and p["selection_preserved"] for p in phrases)}
    report["summary"]["all_unique_forms_tested"] = len(words_report) == len(forms) and bool(available)
    report["summary"]["all_reference_queries_match"] = all(r.get("reference_search", {}).get("target_in_results") for r in report["records"])
    tested_searches = [p for p in phrases if p.get("search")]
    report["summary"]["literal_phrase_queries"] = len(tested_searches)
    report["summary"]["literal_phrase_target_hits"] = sum(p["search"]["words"]["target_in_results"] for p in tested_searches)
    report["summary"]["intact_forms_queries"] = sum(not p["editorial_span"] for p in tested_searches)
    report["summary"]["intact_forms_target_hits"] = sum(not p["editorial_span"] and p["search"]["forms"]["target_in_results"] for p in tested_searches)
    report["summary"]["editorial_forms_queries"] = sum(p["editorial_span"] for p in tested_searches)
    report["summary"]["infrastructure_pass"] = bool(args.offline or (
        len(available) == len(records) and report["summary"]["all_reference_queries_match"]
        and report["summary"]["literal_phrase_target_hits"] == report["summary"]["literal_phrase_queries"]
        and report["summary"]["intact_forms_target_hits"] == report["summary"]["intact_forms_queries"]
        and all(w["http_status"] == 200 and w["context_text_matches_source"] for w in words_report)
        and all(p["http_status"] == 200 and p["source_preserved"] and p["selection_preserved"] for p in phrases)))
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
