"""Synthetic source-association fixtures, not historical lexical evidence."""

from copy import deepcopy
import json

import pytest

from backend.candidate_senses import project_entry_senses


def fixtures(number=1, gloss="SYNTHETIC meaning A"):
    entry = f"wiktionary:kaikki:line:{number}"
    metadata = {"source_record_id": entry, "source_raw_sha256": "a" * 64,
                "source_raw_line_sha256": str(number) * 64,
                "source_quality": "machine_extracted_unreviewed", "license": "SYNTHETIC license"}
    evidence = {"record_id": entry, "parent_sha256": str(number) * 64,
                "raw_sha256": "c" * 64,
                "raw_path": "data/raw/synthetic-fixture.jsonl",
                "source_url": "https://example.test/synthetic-dictionary",
                "quote": "SYNTHETIC morphology", "locator": "/entry/forms"}
    morphology = {
        "id": entry + ":morphology:entry", "predicate": "morphology",
        "subject": {"type": "form", "form": "\u03b1"},
        "object": {"lemma": "\u03b1", "pos": "adj",
                   "forms": [{"form": "\u03b2", "tags": ["neuter", "plural"]}]},
        "metadata": metadata, "evidence": [evidence],
        "status": "source_claim", "assertion_type": "extracted_annotation",
        "method": "accepted-kaikki-snapshot-scoped-claims-v1",
        "source_family": "enwiktionary-kaikki-synthetic-test",
    }
    candidate = {
        "id": morphology["id"] + "#form:0", "candidate_kind": "grammatical_analysis",
        "lemma": "\u03b1", "entry_headword": "\u03b1", "matched_form": "\u03b2",
        "claim_ids": [morphology["id"]], "source_family": morphology["source_family"],
        "matched_object_form": deepcopy(morphology["object"]["forms"][0]),
        "source_tags": ["neuter", "plural"], "analysis": ["neuter", "plural"],
    }
    sense = {
        **deepcopy(morphology), "id": entry + ":sense:0", "predicate": "sense_gloss",
        "object": {"lemma": "\u03b1", "pos": "adj", "glosses": [gloss],
                   "raw_glosses": ["(SYNTHETIC qualifier) " + gloss],
                   "source_sense": {"id": "synthetic-sense", "tags": ["synthetic-tag"],
                                    "raw_tags": ["SYNTHETIC scope"]}},
        "metadata": {**metadata, "sense_index": 0, "source_sense_id": "synthetic-sense"},
        "evidence": [{**evidence, "quote": json.dumps([gloss]),
                      "locator": "/entry/senses/0/glosses"}],
    }
    return candidate, morphology, sense


def test_exact_entry_identity_not_headword_selects_literal_senses():
    candidate, morphology, sense = fixtures()
    other_candidate, other_morphology, other_sense = fixtures(2, "SYNTHETIC meaning B")
    before = deepcopy((candidate, morphology, sense))
    result = project_entry_senses(candidate, morphology, [sense, other_sense])
    assert len(result) == 1
    assert result[0]["glosses"] == ["SYNTHETIC meaning A"]
    assert result[0]["raw_glosses"] == sense["object"]["raw_glosses"]
    assert result[0]["tags"] == ["synthetic-tag"]
    assert result[0]["raw_tags"] == ["SYNTHETIC scope"]
    assert result[0]["claim_id"] == sense["id"]
    assert result[0]["entry_id"] == "wiktionary:kaikki:line:1"
    assert result[0]["locator"] == "/entry/senses/0/glosses"
    assert result[0]["scope"] == "general_dictionary_entry"
    assert result[0]["license"] == "SYNTHETIC license"
    assert (candidate, morphology, sense) == before
    other = project_entry_senses(other_candidate, other_morphology, [sense, other_sense])
    assert other[0]["glosses"] == ["SYNTHETIC meaning B"]


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(status="needs_review"),
    lambda s: s.update(assertion_type="model_inference"),
    lambda s: s.update(source_family="another-family"),
    lambda s: s.update(predicate="lemma"),
    lambda s: s["subject"].update(passage_id="synthetic-passage"),
    lambda s: s["subject"].update(form="\u03b3"),
    lambda s: s["object"].update(lemma="\u03b3"),
    lambda s: s["object"].update(pos="noun"),
    lambda s: s["metadata"].update(source_record_id="wiktionary:kaikki:line:2"),
    lambda s: s["metadata"].update(source_raw_sha256="b" * 64),
    lambda s: s["metadata"].update(source_raw_line_sha256="b" * 64),
    lambda s: s["metadata"].update(source_quality="quarantined"),
    lambda s: s["metadata"].update(sense_index=1),
    lambda s: s["metadata"].pop("sense_index"),
    lambda s: s["metadata"].pop("source_record_id"),
    lambda s: s["evidence"][0].update(record_id="wiktionary:kaikki:line:2"),
    lambda s: s["evidence"][0].update(parent_sha256="b" * 64),
    lambda s: s["evidence"][0].update(raw_sha256="b" * 64),
    lambda s: s["evidence"][0].update(source_url="https://example.test/other"),
    lambda s: s["evidence"][0].update(locator="/entry/senses/1/glosses"),
    lambda s: s["evidence"][0].update(quote='["Different literal words"]'),
    lambda s: s["object"]["source_sense"].update(form_of=[{"word": "\u03b3"}]),
    lambda s: s["object"].update(raw_glosses="not an array"),
    lambda s: s["object"]["source_sense"].update(raw_glosses=["WRONG qualifier"]),
    lambda s: s["object"]["source_sense"].update(glosses=["WRONG definition"]),
    lambda s: s["object"]["source_sense"].update(id="wrong-sense-id"),
])
def test_wrong_scope_or_identity_is_not_joined(mutation):
    candidate, morphology, sense = fixtures()
    mutation(sense)
    assert project_entry_senses(candidate, morphology, [sense]) == []


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(candidate_kind="explicit_form_of"),
    lambda c: c.update(lemma_targets=[{"word": "\u03b1"}]),
    lambda c: c.update(lemma="\u03b3"),
    lambda c: c.update(entry_headword="\u03b3"),
    lambda c: c.update(claim_ids=["wiktionary:kaikki:line:2:morphology:entry"]),
    lambda c: c.update(source_family="other-family"),
    lambda c: c["claim_ids"].append("wiktionary:kaikki:line:2:morphology:entry"),
    lambda c: c.update(id=c["id"].removesuffix("0") + "9999"),
    lambda c: c.update(matched_form="\u03b3"),
    lambda c: c["matched_object_form"].update(form="\u03b3"),
    lambda c: c.update(analysis=["dative"]),
])
def test_unresolved_form_of_target_cannot_inherit_homograph(mutation):
    candidate, morphology, sense = fixtures()
    mutation(candidate)
    assert project_entry_senses(candidate, morphology, [sense]) == []


def test_all_entry_senses_retained_without_contextual_selection():
    candidate, morphology, sense = fixtures()
    second = deepcopy(sense)
    second["id"] = second["id"].removesuffix("0") + "1"
    second["metadata"]["sense_index"] = 1
    second["evidence"][0]["locator"] = "/entry/senses/1/glosses"
    second["object"]["glosses"].append("SYNTHETIC narrower meaning")
    second["evidence"][0]["quote"] = json.dumps(second["object"]["glosses"])
    result = project_entry_senses(candidate, morphology, [second, sense])
    assert [row["sense_index"] for row in result] == [0, 1]
    assert result[1]["glosses"] == second["object"]["glosses"]
    assert all("contextual" not in row for row in result)


def test_duplicated_source_sense_ordinal_is_not_silently_chosen():
    candidate, morphology, sense = fixtures()
    assert project_entry_senses(candidate, morphology, [sense, deepcopy(sense)]) == []


def test_compacted_morphology_binds_original_ordinal_not_preview_index():
    candidate, morphology, sense = fixtures()
    row = morphology["object"].pop("forms")[0]
    morphology["matched_object_forms"] = [row]
    morphology["matched_object_form_ordinals"] = [29]
    candidate["id"] = candidate["id"].removesuffix("0") + "29"
    assert len(project_entry_senses(candidate, morphology, [sense])) == 1
    candidate["id"] = candidate["id"].removesuffix("29") + "0"
    assert project_entry_senses(candidate, morphology, [sense]) == []
