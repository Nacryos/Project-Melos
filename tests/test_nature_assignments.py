import json
import sqlite3

import pytest

from backend.visual_themes import source_identity, text_sha256
from scripts.build_visual_annotations import validate_decision
from tools.build_nature_assignments import collect_assignments, compact_json, ordered_themes, public_config


def fixture_source(record_id="test:greek", text="waves and sea", kind="text", language="grc"):
    return {"id": record_id, "text": text, "source": "test-fixture", "author": "Pindar",
            "work_id": "test-work", "citation": "1.1", "kind": kind, "language": language,
            "quality": "source_text"}


def fixture_label(record):
    return validate_decision({"id": record["id"], "status": "label", "reason": "Test fixture.",
        "labels": [{"theme": "sea_coast", "kind": "scene", "strength": "strong",
                    "evidence": [{"id": record["id"], "quote": "waves"}]}]}, {record["id"]: record})


def fixture_files(tmp_path, sources, annotations):
    database, sidecar = tmp_path / "corpus.sqlite", tmp_path / "validated.json"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE passages (id,text,source,author_canonical,work_id,citation,language,kind,quality,data)")
        for record in sources:
            con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(record[key] for key in
                ("id", "text", "source", "author", "work_id", "citation", "language", "kind", "quality"))
                + (json.dumps(record),))
    sidecar.write_text(json.dumps({"schema_version": 1, "manifest": {}, "records": annotations}), "utf-8")
    return database, sidecar


def test_only_current_positive_annotations_export_and_output_is_minimal(tmp_path):
    positive, abstained, unreviewed = fixture_source(), fixture_source("test:abstain"), fixture_source("test:unreviewed")
    abstention = validate_decision({"id": abstained["id"], "status": "abstain", "reason": "Test abstention.",
                                   "labels": []}, {abstained["id"]: abstained})
    database, sidecar = fixture_files(tmp_path, [positive, abstained, unreviewed], [fixture_label(positive), abstention])
    result, counts = collect_assignments(database, sidecar)
    assert result == {positive["id"]: {"theme": "sea_coast", "hash": text_sha256(positive["text"]), "themes": ["sea_coast"]}}
    assert counts == {"nonpositive": 1, "greek": 1, "exported": 1}
    assert compact_json(result) == compact_json(collect_assignments(database, sidecar)[0])
    assert all(term not in compact_json(result) for term in ("waves", "evidence", "reason", "source_identity"))
    # Mutate only indexed text, leaving JSON payload unchanged: must still fail closed.
    with sqlite3.connect(database) as con:
        con.execute("UPDATE passages SET text='changed' WHERE id=?", (positive["id"],))
    assert collect_assignments(database, sidecar)[0] == {}


def test_translation_assignment_requires_current_actual_parent(tmp_path):
    greek = fixture_source()
    translation = fixture_source("test:translation", "English waves", "translation", "en") | {"parent_id": greek["id"]}
    annotation = fixture_label(greek)
    inherited = annotation | {"id": translation["id"], "source_text_sha256": text_sha256(translation["text"]),
        "source_identity": source_identity(translation), "parent_id": greek["id"],
        "parent_text_sha256": text_sha256(greek["text"]), "parent_source_identity": source_identity(greek)}
    database, sidecar = fixture_files(tmp_path, [greek, translation], [annotation, inherited])
    assert set(collect_assignments(database, sidecar)[0]) == {greek["id"], translation["id"]}
    with sqlite3.connect(database) as con:
        con.execute("UPDATE passages SET text='changed' WHERE id=?", (greek["id"],))
    result, counts = collect_assignments(database, sidecar)
    assert result == {}
    assert counts["missing_or_stale"] == 2


def test_order_is_deterministic_and_uses_only_existing_labels():
    span = {"id": "test", "start": 0, "end": 3}
    labels = [{"theme": theme, "strength": "strong", "kind": kind, "evidence": [span]}
              for theme, kind in (("sea_coast", "simile"), ("garden_grove", "scene"), ("river_spring", "scene"))]
    assert ordered_themes(labels) == ordered_themes(list(reversed(labels))) == ["garden_grove", "river_spring", "sea_coast"]
    labels[2]["evidence"].append({"id": "other-test", "start": 4, "end": 8})
    assert ordered_themes(labels)[0] == "river_spring"
    labels[0]["strength"] = "guessed"
    with pytest.raises(ValueError, match="Unsupported"):
        ordered_themes(labels)


def test_runtime_manifest_strips_provenance_and_checks_urls(tmp_path):
    from tools.build_nature_assignments import ROOT, MANIFEST
    manifest = json.loads((ROOT / MANIFEST).read_text("utf-8"))
    result = public_config(manifest, "/assets/nature-presets/assignments.123456789abc.json", ROOT)
    assert result["defaultPresetId"] == "garden_grove"
    assert all(set(preset) == {"title", "url", "smallUrl"} for preset in result["presets"].values())
    assert "source_path" not in compact_json(result)
    assert "output/imagegen" not in compact_json(result)
    manifest["presets"][0]["url"] = "https://example.test/image.webp"
    with pytest.raises(ValueError, match="Unsafe"):
        public_config(manifest, "/assets/nature-presets/assignments.123456789abc.json", tmp_path)
