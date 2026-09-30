"""Trace every staged apparatus claim to its saved, hash-checked TEI."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter

from scripts import extract_p2_apparatus as apparatus


def test_exact_quotes_and_reading_structure():
    claims = list(apparatus.read_jsonl(apparatus.OUT))
    assert claims
    assert len({claim["id"] for claim in claims}) == len(claims)
    raw_cache = {}
    count = Counter()
    for claim in claims:
        evidence = claim["evidence"][0]
        path = evidence["raw_path"]
        if path not in raw_cache:
            raw = (apparatus.ROOT / path).read_bytes()
            assert apparatus.sha256(raw) == evidence["raw_sha256"]
            raw_cache[path] = raw
        raw = raw_cache[path]
        loc = evidence["locator"]
        assert raw[loc["byte_start"]:loc["byte_end"]].decode("utf-8") == evidence["quote"]
        node = ET.fromstring(evidence["quote"])
        kind = claim["object"]["kind"]
        if kind == "explicit_apparatus":
            assert claim["predicate"] == "variant_reading"
            assert apparatus.local(node.tag) == "app"
            lemma = next((child for child in node if apparatus.local(child.tag) == "lem"), None)
            readings = [child for child in node if apparatus.local(child.tag) == "rdg"]
            assert lemma is not None and readings
            assert claim["object"]["lemma"] == apparatus.reading(lemma)
            assert claim["object"]["alternatives"] == [apparatus.reading(r) for r in readings]
        else:
            assert claim["predicate"] == "editorial_state"
            assert claim["object"]["tei_tag"] == apparatus.local(node.tag)
            if apparatus.local(node.tag) == "gap":
                assert claim["object"]["text"] is None
            else:
                assert claim["object"]["text"] == apparatus.content(node)
        assert claim["source_family"].startswith(("dclp:", "perseus:"))
        assert claim["subject"].get("passage_id") is None
        count[kind] += 1
    assert count["explicit_apparatus"] > 0
    assert count["restoration"] > 0
    assert count["uncertain_surviving_text"] > 0


def test_dclp_apparatus_links_are_exact_records():
    parent_apps = {
        r["id"]: r
        for r in apparatus.read_jsonl(apparatus.ROOT / "data/processed/commentary.jsonl")
        if r["kind"] == "apparatus"
    }
    claims = [c for c in apparatus.read_jsonl(apparatus.OUT)
              if c["object"]["kind"] == "explicit_apparatus"]
    assert len(claims) == len(parent_apps)
    seen = set()
    for claim in claims:
        evidence = claim["evidence"][0]
        parent = parent_apps[evidence["record_id"]]
        assert evidence["raw_path"] == parent["raw_path"]
        assert evidence["source_url"] == parent["source_url"]
        assert apparatus.content(ET.fromstring(evidence["quote"])) == apparatus.content(ET.fromstring(parent["text"]))
        seen.add(evidence["record_id"])
    assert seen == parent_apps.keys()


def test_report_hash_and_counts():
    report = json.loads(apparatus.REPORT.read_text(encoding="utf-8"))
    claims = list(apparatus.read_jsonl(apparatus.OUT))
    assert report["claim_count"] == len(claims)
    assert report["output_sha256"] == apparatus.sha256(apparatus.OUT.read_bytes())
    expected = Counter((c["source_family"].split(":", 1)[0],
                        "app" if c["object"]["kind"] == "explicit_apparatus"
                        else c["object"]["tei_tag"])
                       for c in claims)
    for source, by_tag in report["by_source_and_tag"].items():
        for tag, count in by_tag.items():
            assert expected[source, tag] == count
