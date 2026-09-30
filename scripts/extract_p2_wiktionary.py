"""Derive scoped evidence claims from the accepted Wiktionary snapshot.

Run: python -m scripts.extract_p2_wiktionary

This reads the independently accepted Kaikki/Wiktextract parent artifact. It
does not download a second copy or treat dictionary listings as attestations.
Form rows are retained in source order, including table headers and romanized
rows, so an inflection-table label is never silently assigned to a surface.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "data/lexica/wiktionary-entries.jsonl"
PARENT_AUDIT = ROOT / "data/reports/wiktionary-audit.json"
OUTPUT = ROOT / "data/claims/p2_wiktionary.jsonl"
REPORT = ROOT / "data/reports/p2_wiktionary.json"
METHOD = "accepted-kaikki-snapshot-scoped-claims-v1"
SOURCE_FAMILY = "enwiktionary-kaikki-ancient-greek-2026-09-02"

# These are source tag spellings, not inferred classifications. A tag is
# promoted only at the exact source object where it appears.
DIALECT_TAGS = {
    "Aeolic", "Arcadian", "Attic", "Boeotian", "Choral-Doric", "Cretan",
    "Cypriot", "Doric", "Epic", "Ionic", "Koine", "Lesbian", "Old-Attic",
    "Pamphylian", "West-Greek", "epic", "ionic",
}


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def accepted_parent() -> dict:
    audit = json.loads(PARENT_AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "accepted":
        raise RuntimeError("Wiktionary parent is not independently accepted")
    actual = file_sha256(PARENT)
    if actual != audit.get("output_sha256"):
        raise RuntimeError(f"Accepted Wiktionary parent hash mismatch: {actual}")
    return audit


def json_quote(value: object, source_line: str) -> str:
    """Quote exact serialized source text from the saved parent JSONL line."""
    quote = json.dumps(value, ensure_ascii=False)
    if quote not in source_line:
        raise RuntimeError(f"Source quote not found in parent record: {quote[:100]!r}")
    return quote


def evidence(wrapper: dict, parent_hash: str, locator: str, quote: str) -> list[dict]:
    return [{
        "record_id": wrapper["id"],
        "parent_sha256": wrapper["_parent_line_sha256"],
        "source_url": wrapper["source_url"],
        "raw_path": PARENT.relative_to(ROOT).as_posix(),
        "raw_sha256": parent_hash,
        "quote": quote,
        "locator": locator,
    }]


def claim(wrapper: dict, parent_hash: str, kind: str, suffix: str,
          predicate: str, subject_form: str, obj: dict, locator: str,
          quote: str, metadata: dict | None = None) -> dict:
    return {
        "id": f"{wrapper['id']}:{kind}:{suffix}",
        "subject": {"type": "form", "form": subject_form},
        "predicate": predicate,
        "object": obj,
        "evidence": evidence(wrapper, parent_hash, locator, quote),
        "assertion_type": "extracted_annotation",
        "status": "source_claim",
        "method": METHOD,
        "source_family": SOURCE_FAMILY,
        "metadata": {
            "source_record_id": wrapper["id"],
            "source_raw_path": wrapper["raw_path"],
            "source_raw_sha256": wrapper["raw_sha256"],
            "source_raw_line": wrapper["raw_line"],
            "source_raw_line_sha256": wrapper["raw_line_sha256"],
            "source_quality": wrapper["quality"],
            "license": wrapper["license"],
            "scope_note": "Dictionary annotation; not a corpus or author attestation.",
            **(metadata or {}),
        },
    }


def labels(tags: object) -> list[str]:
    return [tag for tag in tags if isinstance(tag, str) and tag in DIALECT_TAGS] if isinstance(tags, list) else []


def claims_for_wrapper(wrapper: dict, parent_hash: str, source_line: str):
    entry = wrapper["entry"]
    word = entry["word"]
    pos = entry["pos"]
    base = {"lemma": word, "pos": pos}

    yield claim(wrapper, parent_hash, "lemma", "entry", "lemma", word,
                {**base, "head_templates": entry.get("head_templates", [])},
                "/entry/word", json_quote(word, source_line))

    forms = entry.get("forms", [])
    if forms:
        # Exact parent array; retaining pseudo-rows preserves table boundaries.
        yield claim(wrapper, parent_hash, "morphology", "entry", "morphology", word,
                    {**base, "forms": forms,
                     "inflection_templates": entry.get("inflection_templates", [])},
                    "/entry/forms",
                    json_quote(forms[0], source_line),
                    {"form_count": len(forms),
                     "form_quote_scope": "first row; locator and accepted parent bind full array"})

    for form_index, form in enumerate(forms):
        if not isinstance(form, dict):
            raise RuntimeError(f"Non-object form in {wrapper['id']} at {form_index}")
        form_word = form.get("form")
        form_labels = labels(form.get("tags"))
        if form_labels and isinstance(form_word, str) and form_word:
            yield claim(wrapper, parent_hash, "dialect_form", str(form_index),
                        "dialect_label", form_word,
                        {"labels": form_labels, "source_tags": form.get("tags", []),
                         "source_raw_tags": form.get("raw_tags", []),
                         "lemma": word, "form_index": form_index,
                         "source_form": form},
                        f"/entry/forms/{form_index}", json_quote(form, source_line),
                        {"dialect_scope": "listed_form"})

    for sense_index, sense in enumerate(entry.get("senses", [])):
        if not isinstance(sense, dict):
            raise RuntimeError(f"Non-object sense in {wrapper['id']} at {sense_index}")
        loc = f"/entry/senses/{sense_index}"
        meta = {"sense_index": sense_index, "source_sense_id": sense.get("id")}
        glosses = sense.get("glosses", [])
        sense_content_key = next((key for key in ("glosses", "raw_glosses", "examples", "attestations")
                                  if sense.get(key)), None)
        if sense_content_key:
            yield claim(wrapper, parent_hash, "sense", str(sense_index),
                        "sense_gloss", word,
                        {**base, "glosses": glosses,
                         "raw_glosses": sense.get("raw_glosses", []),
                         "source_sense": sense},
                        loc + "/" + sense_content_key,
                        json_quote(sense[sense_content_key], source_line), meta)

        sense_labels = labels(sense.get("tags"))
        if sense_labels:
            yield claim(wrapper, parent_hash, "dialect_sense", str(sense_index),
                        "dialect_label", word,
                        {"labels": sense_labels, "source_tags": sense.get("tags", []),
                         "source_raw_tags": sense.get("raw_tags", []),
                         "lemma": word, "sense_index": sense_index,
                         "sense_glosses": glosses},
                        loc + "/tags", json_quote(sense["tags"], source_line),
                        {**meta, "dialect_scope": "sense"})

        for relation_key, predicate in (("form_of", "lemma"),
                                        ("alt_of", "equivalent_form")):
            relations = sense.get(relation_key, [])
            if relations:
                yield claim(wrapper, parent_hash, relation_key, str(sense_index),
                            predicate, word,
                            {"relation": relation_key, "targets": relations,
                             "source_tags": sense.get("tags", []),
                             "source_raw_tags": sense.get("raw_tags", []),
                             "sense_index": sense_index, "sense_glosses": glosses},
                            loc + "/" + relation_key,
                            json_quote(relations, source_line), meta)


def extract() -> dict:
    parent_audit = accepted_parent()
    parent_hash = parent_audit["output_sha256"]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    part = OUTPUT.with_name(OUTPUT.name + ".part")
    counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    source_entries = 0
    source_forms = 0
    source_senses = 0
    source_examples = 0
    source_attestations = 0
    template_dialect_arguments = 0
    raw_dialect_candidates: list[dict] = []
    raw_dialect_candidate_count = 0
    with PARENT.open("r", encoding="utf-8") as source, part.open("w", encoding="utf-8", newline="\n") as target:
        for line_number, line in enumerate(source, 1):
            wrapper = json.loads(line)
            wrapper["_parent_line_sha256"] = sha256(line.rstrip("\r\n").encode("utf-8")).hexdigest()
            if wrapper.get("id") != f"wiktionary:kaikki:line:{line_number}":
                raise RuntimeError(f"Unexpected source record ID at line {line_number}")
            entry = wrapper["entry"]
            if entry.get("lang_code") != "grc":
                raise RuntimeError(f"Non-Ancient-Greek entry at line {line_number}")
            source_entries += 1
            source_forms += len(entry.get("forms", []))
            source_senses += len(entry.get("senses", []))
            for template in entry.get("inflection_templates", []):
                if isinstance(template, dict) and isinstance(template.get("args"), dict):
                    if "dial" in template["args"]:
                        template_dialect_arguments += 1
            for sense_index, sense in enumerate(entry.get("senses", [])):
                source_examples += len(sense.get("examples", []))
                source_attestations += len(sense.get("attestations", []))
                if not labels(sense.get("tags")):
                    mentions = [tag for tag in sense.get("raw_tags", [])
                                if isinstance(tag, str) and any(
                                    dialect.casefold() in tag.casefold()
                                    for dialect in DIALECT_TAGS if len(dialect) > 3)]
                    if mentions:
                        raw_dialect_candidate_count += 1
                        if len(raw_dialect_candidates) < 30:
                            raw_dialect_candidates.append({"record_id": wrapper["id"],
                                                           "word": entry["word"],
                                                           "sense_index": sense_index,
                                                           "raw_tags": mentions})
            for row in claims_for_wrapper(wrapper, parent_hash, line):
                target.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts[row["predicate"]] += 1
                kind_counts[row["id"].split(":")[-2]] += 1
                if row["predicate"] == "dialect_label":
                    scope_counts[row["metadata"]["dialect_scope"]] += 1
    if source_entries != parent_audit["counts"]["output_lines"]:
        part.unlink(missing_ok=True)
        raise RuntimeError("Parent entry count changed during extraction")
    os.replace(part, OUTPUT)
    report = {
        "dataset": "Scoped claims from accepted Kaikki Ancient Greek enwiktionary snapshot",
        "status": "staged_pending_independent_audit",
        "method": METHOD,
        "source_family": SOURCE_FAMILY,
        "parent_path": PARENT.relative_to(ROOT).as_posix(),
        "parent_sha256": parent_hash,
        "parent_audit_path": PARENT_AUDIT.relative_to(ROOT).as_posix(),
        "source_entries": source_entries,
        "source_forms_retained": source_forms,
        "source_senses": source_senses,
        "source_examples": source_examples,
        "source_attestations": source_attestations,
        "inflection_template_dialect_arguments_retained": template_dialect_arguments,
        "claim_counts": dict(counts),
        "claim_kinds": dict(kind_counts),
        "dialect_claim_scopes": dict(scope_counts),
        "raw_dialect_mentions_without_controlled_tag_count": raw_dialect_candidate_count,
        "raw_dialect_mentions_without_controlled_tag_sample": raw_dialect_candidates,
        "claims": sum(counts.values()),
        "output_path": OUTPUT.relative_to(ROOT).as_posix(),
        "output_sha256": file_sha256(OUTPUT),
        "caveat": "Machine-extracted dictionary annotations only. Form listings, examples, and cited quotations do not establish Melos corpus or specific-author attestations. Source per-field rights uncertainty remains as documented by the parent audit.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    summary = extract()
    print(json.dumps({key: summary[key] for key in ("source_entries", "source_forms_retained", "claims", "output_sha256")}, ensure_ascii=False))
