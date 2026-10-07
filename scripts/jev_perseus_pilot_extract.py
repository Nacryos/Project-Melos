"""Bounded, reproducible live Perseus pilot. Never calls Jev or edits the corpus.

Only externally downloaded HTML supplies linguistic data. Transformations are
HTML entity decoding by BeautifulSoup and whitespace normalization (Python str);
no transliteration, linguistic normalization, or generated translation is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/jev-perseus-20261005"
BASE = "https://www.perseus.tufts.edu/hopper/"
SOURCES = [
    ("odyssey", "Perseus:text:1999.01.0135:book=1:card=1", "1999.01.0136"),
    ("iliad", "Perseus:text:1999.01.0133:book=1:card=1", "1999.01.0134"),
]
SELECTION = {
    "rule": "First 5 ambiguous successful occurrences in document order per source; maximum first 40 occurrences",
    "ambiguous": "At least two distinct (source lemma id, morphology) rows",
    "max_per_source": 5,
    "max_occurrences_per_source": 40,
    "exclude_prior_inspected_query_l": "e)/nnepe",
    "errors": "Save failed HTTP responses and stop; do not substitute data",
    "source_order": [s[0] for s in SOURCES],
    "purpose": "Experimental comparison only; no corpus integration",
}
AMENDMENT = {
    "reason": "Original strict sampling halted on inaccessible live morphology; parent authorized availability sampling",
    "authorization": "Parent instruction 2026-10-05; independent auditor accepted",
    "timeout_seconds": 15,
    "max_consecutive_morph_failures_per_passage": 3,
    "failure_policy": "Log and omit unavailable occurrence; never supply invented candidates",
    "positive_control": "Previously inspected Odyssey query l=e)/nnepe fetched separately, flagged non-fresh",
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(node):
    return " ".join(node.get_text(" ", strip=True).split())


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0"
        self.manifest = []
        self.last = 0.0

    def get(self, name, url, referer=None, timeout=15):
        path = OUT / "raw" / (name + ".html")
        meta_path = path.with_suffix(".meta.json")
        if path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = path.read_bytes()
            assert meta["requested_url"] == url
            assert hashlib.sha256(content).hexdigest() == meta["sha256"]
            if meta["status"] != 200:
                raise RuntimeError(f"Saved failure requires explicit resolution: {meta_path}")
        else:
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last)))
            headers = {"Referer": referer} if referer else {}
            started = datetime.now(timezone.utc).isoformat()
            try:
                response = self.session.get(url, headers=headers, timeout=timeout)
            except requests.RequestException as exc:
                error_suffix = datetime.now(timezone.utc).strftime("%H%M%S%f")
                dump(OUT / "errors" / (name + "_" + error_suffix + ".json"), {"url": url, "time": started, "error": str(exc)})
                raise
            self.last = time.monotonic()
            content = response.content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            meta = {"requested_url": url, "effective_url": response.url,
                    "status": response.status_code, "downloaded_at": started,
                    "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                    "raw_path": str(path.relative_to(ROOT)), "request_headers": dict(self.session.headers) | headers,
                    "response_headers": dict(response.headers)}
            dump(meta_path, meta)
            response.raise_for_status()
        self.manifest.append(meta)
        dump(OUT / "download_manifest.json", self.manifest)
        return BeautifulSoup(path.read_bytes(), "html.parser"), meta


def text_record(soup, meta):
    text = soup.select_one(".text_container > .text")
    if not text:
        raise ValueError("Missing source text container")
    citation_links = [a["href"] for a in soup.select("a[href]") if "/citations/urn:cts:" in a["href"]]
    if len(citation_links) != 1:
        raise ValueError("Missing unique CTS citation")
    return {
        "text": norm(text), "source_url": meta["requested_url"],
        "edition": norm(soup.select_one("#text_desc")),
        "citation_uri": citation_links[0], "title": norm(soup.title),
        "raw_path": meta["raw_path"], "sha256": meta["sha256"],
        "license_urls": sorted({a["href"] for a in soup.select("a[href]") if "creativecommons.org/licenses" in a["href"]}),
    }


def candidates(soup):
    parsed = []
    for lemma in soup.select(".analysis > .lemma"):
        name = lemma.select_one(".lemma_header h4")
        gloss = lemma.select_one(".lemma_definition")
        table = lemma.find("table", recursive=False)
        if name is None or table is None:
            raise ValueError("Unexpected lemma structure")
        for row_index, row in enumerate(table.find_all("tr", recursive=False)):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 4:
                raise ValueError(f"Expected 4 candidate cells, found {len(cells)}")
            form, morphology, votes, percent = map(norm, cells)
            if not re.fullmatch(r"[\d,.]+%", percent):
                raise ValueError(f"Invalid displayed percent: {percent}")
            if votes == "no user votes":
                count = 0
            elif re.fullmatch(r"[\d,]+ user votes?", votes):
                count = int(votes.split()[0].replace(",", ""))
            else:
                raise ValueError(f"Unknown vote display: {votes}")
            parsed.append({
                "id": f"p{len(parsed) + 1}", "lemma": norm(name),
                "morphology": morphology, "gloss": norm(gloss) if gloss else None,
                "perseus_percent": float(percent[:-1].replace(",", "")),
                "user_votes": count, "perseus_percent_display": percent,
                "user_votes_display": votes, "perseus_selected": "winner" in row.get("class", []),
                "source_lemma_id": lemma.get("id"), "source_row_index": row_index,
                "form_display": form,
            })
    if not parsed:
        raise ValueError("No live morphology candidates in successful response")
    return parsed


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    freeze_path = OUT / "selection_plan.json"
    if freeze_path.exists():
        old = json.loads(freeze_path.read_text(encoding="utf-8"))
        assert old["plan"] == SELECTION, "Selection plan changed after freeze"
    else:
        dump(freeze_path, {"frozen_at": datetime.now(timezone.utc).isoformat(), "plan": SELECTION})
    amendment_path = OUT / "selection_amendment_v2.json"
    if amendment_path.exists():
        assert json.loads(amendment_path.read_text(encoding="utf-8"))["plan"] == AMENDMENT
    else:
        dump(amendment_path, {"frozen_at": datetime.now(timezone.utc).isoformat(), "plan": AMENDMENT})
        previous_attempts = OUT / "attempts.json"
        if previous_attempts.exists():
            dump(OUT / "original_strict_attempts.json", json.loads(previous_attempts.read_text(encoding="utf-8")))
    fetch = Fetcher()
    fetch.get("hopper_js", "https://www.perseus.tufts.edu/js/hopper.js")
    fetch.get("perseus_official_copyright", "https://raw.githubusercontent.com/PerseusDL/canonical/master/README.md")
    cases, attempts, passages = [], [], []
    for key, doc, translation_id in SOURCES:
        source_url = BASE + "text?doc=" + doc
        source, source_meta = fetch.get(key + "_greek", source_url)
        greek = text_record(source, source_meta)
        translation_links = [a for a in source.select("a[href]") if a.get_text(strip=True) == "focus" and translation_id in a["href"]]
        if len(translation_links) != 1:
            raise ValueError("No unique linked English edition")
        english_url = urljoin(source_url, translation_links[0]["href"])
        english_soup, english_meta = fetch.get(key + "_english", english_url, source_url)
        english = text_record(english_soup, english_meta)
        greek_range = greek["citation_uri"].rsplit(":", 1)[-1]
        english_range = english["citation_uri"].rsplit(":", 1)[-1]
        if greek_range != english_range:
            raise ValueError(f"Unaligned card ranges: {greek_range} vs {english_range}")
        english["edition_alignment_status"] = "Perseus-linked parallel translation; identical CTS passage range; edition descriptions retained separately"
        english["context_scope"] = greek_range
        passages.append({"id": key, "greek": greek, "translation": english})
        dump(OUT / "passages.json", passages)
        text = source.select_one(".text_container > .text")
        links = text.select('a[href^="morph?"]')
        documents = re.findall(r"addDocument\('([^']+)'\)", str(source))
        selected = 0
        consecutive_failures = 0
        ordered_links = list(enumerate(links[:SELECTION["max_occurrences_per_source"]]))
        # Capture the declared known control first, independent of availability sample.
        controls = [(i, a) for i, a in ordered_links if parse_qs(urlsplit(a["href"]).query)["l"][0] == SELECTION["exclude_prior_inspected_query_l"]]
        ordered_links = controls + [(i, a) for i, a in ordered_links if (i, a) not in controls]
        for index, link in ordered_links:
            href = link["href"]
            query = parse_qs(urlsplit(href).query)
            match = re.search(r"m\(this,(-?\d+),(\d+)\)", link.get("onclick", ""))
            if not match:
                raise ValueError("Unexpected word onclick")
            which, document_index = map(int, match.groups())
            morph_url = urljoin(source_url, href) + "&d=" + documents[document_index] + "&i=" + str(which)
            attempt = {"passage_id": key, "word_index_zero_based": index, "target": norm(link),
                       "source_href": href, "source_onclick": link["onclick"], "morph_url": morph_url}
            is_control = query["l"][0] == SELECTION["exclude_prior_inspected_query_l"]
            attempt["sample_role"] = "previously_inspected_positive_control" if is_control else "availability_sample"
            attempt["result"] = "pending"
            attempts.append(attempt)
            dump(OUT / "attempts.json", attempts)
            try:
                morph, morph_meta = fetch.get(f"{key}_morph_{index:03d}", morph_url, source_url)
            except (requests.RequestException, RuntimeError) as exc:
                attempt.update({"result": "unavailable_omitted", "error": str(exc)})
                dump(OUT / "attempts.json", attempts)
                print(f"Unavailable {key}-{index:03d}: {type(exc).__name__}", flush=True)
                consecutive_failures += 1
                if consecutive_failures >= AMENDMENT["max_consecutive_morph_failures_per_passage"]:
                    break
                continue
            consecutive_failures = 0
            parsed = candidates(morph)
            distinct = {(p["source_lemma_id"], p["morphology"]) for p in parsed}
            attempt.update({"result": "selected" if len(distinct) >= 2 else "unambiguous",
                            "candidate_count": len(parsed), "raw_path": morph_meta["raw_path"]})
            dump(OUT / "attempts.json", attempts)
            if len(distinct) < 2:
                continue
            title_parts = greek["title"].split(",")
            # Exact source line is discovered through DOM <br> boundaries, not generated.
            before, after = [], []
            for sibling in link.previous_siblings:
                if getattr(sibling, "name", None) == "br":
                    break
                before.append(str(sibling) if isinstance(sibling, NavigableString) else sibling.get_text(" "))
            for sibling in link.next_siblings:
                if getattr(sibling, "name", None) == "br":
                    break
                after.append(str(sibling) if isinstance(sibling, NavigableString) else sibling.get_text(" "))
            case = {
                "id": f"{key}-{index:03d}", "target": norm(link),
                "sample_role": attempt["sample_role"],
                "author": title_parts[0].strip(), "work": title_parts[1].strip(),
                "citation": greek["citation_uri"], "greek_context": greek["text"],
                "target_line_before": " ".join("".join(reversed(before)).split()),
                "target_line_after": " ".join("".join(after).split()),
                "word_index_zero_based": index, "word_occurrence_i": which,
                "source_href": href, "source_onclick": link["onclick"],
                "source_doc": documents[document_index], "prior": query.get("prior", [None])[0],
                "translation": english, "greek_edition": greek["edition"],
                "candidates": parsed, "morph_url": morph_url,
                "source_urls": [source_url, english_url, morph_url],
                "raw_refs": [source_meta, english_meta, morph_meta],
                "perseus_evaluator_table": [[norm(cell) for cell in row.select("th, td")]
                                            for row in morph.select("#votes table tr")],
                "perseus_explanation": norm(morph.select_one("#votes")) if morph.select_one("#votes") else None,
            }
            cases.append(case)
            dump(OUT / "cases.json", cases)
            if not is_control:
                selected += 1
            print(f"Selected {case['id']} with {len(parsed)} candidate rows", flush=True)
            if selected >= SELECTION["max_per_source"]:
                break
    dump(OUT / "extraction_summary.json", {"case_count": len(cases), "attempt_count": len(attempts),
         "completed_at": datetime.now(timezone.utc).isoformat(), "cases_sha256": hashlib.sha256((OUT / "cases.json").read_bytes()).hexdigest() if cases else None,
         "unavailable_occurrences": [a for a in attempts if a["result"] == "unavailable_omitted"],
         "fresh_case_count": sum(c["sample_role"] == "availability_sample" for c in cases),
         "known_control_count": sum(c["sample_role"] == "previously_inspected_positive_control" for c in cases),
         "limitations": ["Convenience sample from first card of two Homer texts; not representative accuracy", "Perseus combined scores are not calibrated probabilities or ground truth", "Historical user voting is not independent gold", "English full-card context retains linked edition provenance; Greek/English edition identity is not assumed"]})
    print(json.dumps({"cases": len(cases), "attempts": len(attempts), "output": str(OUT)}))


def probe_encoded():
    """Three parent-authorized equivalent-parameter probes, separate from sample."""
    attempts = json.loads((OUT / "attempts.json").read_text(encoding="utf-8"))
    targets = [a for a in attempts if a["result"] == "unavailable_omitted"][:3]
    dump(OUT / "encoding_probe_plan.json", {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "authorization": "Parent requested one bounded alternative encoding cohort before Jev",
        "rule": "First three unavailable occurrences; query encoded with urllib.parse.urlencode preserving ordered parameter pairs",
        "max_calls": 3, "timeout_seconds": 10, "targets": targets,
    })
    fetch, results = Fetcher(), []
    for attempt in targets:
        parts = urlsplit(attempt["morph_url"])
        encoded = urlunsplit(parts._replace(query=urlencode(parse_qsl(parts.query))))
        assert parse_qsl(urlsplit(encoded).query) == parse_qsl(parts.query)
        doc = parse_qs(parts.query)["d"][0]
        name = f"encoding_probe_{attempt['passage_id']}_{attempt['word_index_zero_based']:03d}"
        result = {"original_attempt": attempt, "encoded_url": encoded}
        try:
            soup, meta = fetch.get(name, encoded, BASE + "text?doc=" + doc, timeout=10)
            result.update({"result": "success", "candidates": candidates(soup), "raw_ref": meta})
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            result.update({"result": "failed", "error": str(exc)})
        results.append(result)
        dump(OUT / "encoding_probe_results.json", results)
        print(f"Encoding probe {name}: {result['result']}", flush=True)
    # Preserve the complete manifest, including prior and failed raw responses.
    dump(OUT / "download_manifest.json", [json.loads(p.read_text(encoding="utf-8"))
         for p in sorted((OUT / "raw").glob("*.meta.json"))])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-encoded", action="store_true")
    args = parser.parse_args()
    probe_encoded() if args.probe_encoded else run()
