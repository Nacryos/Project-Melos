"""Synthetic test-only records; never part of the collected lexicon."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.wiktionary import AuditGateError, WiktionaryLookup, build_index


class WiktionaryLookupTests(unittest.TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.source = root / "wiktionary-entries.jsonl"
        self.audit = root / "wiktionary-audit.json"
        self.index = root / "wiktionary.sqlite"
        wrappers = [
            {"id": "test:1", "source": "Synthetic Kaikki fixture",
             "source_url": "https://example.test/test-only-snapshot", "quality": "test_only",
             "raw_path": "test-only.jsonl", "raw_sha256": "test-only",
             "raw_line": 1, "raw_line_sha256": "test-only", "license": "test-only",
             "entry": {"word": "ὄρος", "lang_code": "grc", "pos": "noun",
                       "tags": ["entry tag"], "raw_tags": ["entry raw tag"],
                       "senses": [{"glosses": ["synthetic sense"], "tags": ["sense tag"],
                                   "raw_tags": ["sense raw tag"],
                                   "form_of": [{"word": "synthetic relation"}]}],
                       "forms": [{"form": "ὀρέων", "tags": ["plural", "genitive"],
                                  "raw_tags": ["form raw tag"]}]}},
            {"id": "test:2", "source": "Synthetic Kaikki fixture",
             "source_url": "https://example.test/test-only-snapshot", "quality": "test_only",
             "raw_path": "test-only.jsonl", "raw_sha256": "test-only",
             "raw_line": 2, "raw_line_sha256": "test-only", "license": "test-only",
             "entry": {"word": "ὀρός", "lang_code": "grc", "pos": "noun",
                       "senses": [{"glosses": ["different synthetic sense"]}],
                       "forms": [{"form": "ὀρέων", "tags": ["listed tag"]}]}},
        ]
        self.source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in wrappers),
                               encoding="utf-8")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.audit.write_text(json.dumps({"status": "accepted", "output_sha256": self.digest}),
                              encoding="utf-8")

    def test_build_and_lookup_preserve_tag_scope(self):
        stats = build_index(self.source, self.audit, self.index)
        self.assertEqual(stats["entries"], 2)
        service = WiktionaryLookup(self.source, self.audit, self.index)
        self.addCleanup(service.close)
        result = service.lookup("ὀρέων", limit=2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(len(service.lookup("ὀρέων", limit=1)["results"]), 1)
        item = next(row for row in result["results"] if row["id"] == "test:1")
        self.assertEqual(item["entry_tags"], ["entry tag"])
        self.assertEqual(item["senses"][0]["tags"], ["sense tag"])
        self.assertEqual(item["senses"][0]["form_of"], [{"word": "synthetic relation"}])
        self.assertEqual(item["matches"][0]["form"]["tags"], ["plural", "genitive"])
        self.assertEqual(item["matches"][0]["evidence_type"], "dictionary_listed_form")
        self.assertNotIn("attested_in_corpus", item["matches"][0])
        self.assertTrue(item["live_entry_url"].endswith("#Ancient_Greek"))
        self.assertIn("not attestations", result["warnings"][0])

    def test_audit_is_required_and_exact(self):
        self.audit.write_text(json.dumps({"status": "staged_pending_independent_audit",
                                          "output_sha256": self.digest}), encoding="utf-8")
        with self.assertRaises(AuditGateError):
            build_index(self.source, self.audit, self.index)
        self.assertFalse(self.index.exists())
        self.audit.write_text(json.dumps({"status": "accepted", "output_sha256": self.digest}),
                              encoding="utf-8")
        build_index(self.source, self.audit, self.index)
        self.source.write_text(self.source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(AuditGateError):
            WiktionaryLookup(self.source, self.audit, self.index)


if __name__ == "__main__":
    unittest.main()
