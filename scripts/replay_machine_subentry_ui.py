"""Snapshot an actual local source/receipt replay for frontend contract tests."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'runtime/alcaeus-morpheus-maintenance/subentry-integration-response.json'
target = root / 'tests/fixtures/machine-subentry-actual.json'
target.write_text(json.dumps(json.loads(source.read_text(encoding='utf-8')), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(target)
word_source = root / 'runtime/alcaeus-morpheus-maintenance/subentry-word-full-route-response.json'
word_target = root / 'tests/fixtures/machine-subentry-word-actual.json'
word_target.write_text(json.dumps(json.loads(word_source.read_text(encoding='utf-8')), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(word_target)
