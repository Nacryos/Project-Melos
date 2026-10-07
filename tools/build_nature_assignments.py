"""Export existing source-bound aesthetic annotations for the static reader.

Run ``python tools/build_nature_assignments.py`` after building the paintings;
``--check`` verifies the deterministic export without writing files. This does
not classify text. Unreviewed, abstained, stale, and missing records have no
assignment; the garden default is only a presentation fallback.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.visual_themes import THEMES, annotation_for, load_annotations

ASSETS = Path("assets/nature-presets")
RUNTIME = Path("js/nature-preset-data.js")
ANNOTATIONS = Path("data/annotations/visual-themes/validated.json")
DATABASE = Path("data/corpus.sqlite")
MANIFEST = Path("data/nature-presets.json")


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def ordered_themes(labels: list[dict]) -> list[str]:
    """Choose an aesthetic display order, never a scientific confidence score.

    The current validated schema admits only strong labels. Scene labels take
    precedence over similes, then more distinct validated evidence spans, then
    the fixed vocabulary order. No additional text interpretation occurs.
    """
    if any(label.get("theme") not in THEMES or label.get("strength") != "strong"
           or label.get("kind") not in ("scene", "simile") for label in labels):
        raise ValueError("Unsupported validated visual-theme label")
    if len({label["theme"] for label in labels}) != len(labels):
        raise ValueError("Duplicate visual-theme label")

    def order(label):
        spans = {(span["id"], span["start"], span["end"])
                 for span in label["evidence"]}
        return (label["kind"] != "scene", -len(spans), THEMES.index(label["theme"]))

    return [label["theme"] for label in sorted(labels, key=order)]


def collect_assignments(database: Path, annotations: Path) -> tuple[dict, dict]:
    """Read current indexed records; annotation_for checks source and parents."""
    if not annotations.is_file():
        raise FileNotFoundError(annotations)
    saved, _ = load_annotations(annotations)
    assignments, counts = {}, Counter()
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row

        @lru_cache(maxsize=None)
        def lookup(record_id):
            row = con.execute(
                "SELECT id,text,source,author_canonical,work_id,citation,language,kind,quality,data "
                "FROM passages WHERE id=?", (record_id,)).fetchone()
            if row is None:
                return None
            record = json.loads(row["data"])
            # Current indexed source fields override any stale payload copies.
            record.update({key: row[key] for key in row.keys() if key not in ("data", "author_canonical")})
            record["author"] = row["author_canonical"]
            return record

        for record_id in sorted(saved):
            if saved[record_id].get("status") != "label":
                counts["nonpositive"] += 1
                continue
            record = lookup(record_id)
            annotation = annotation_for(record, lookup, annotations) if record else None
            if not annotation or annotation["status"] != "label" or not annotation["labels"]:
                counts["missing_or_stale"] += 1
                continue
            themes = ordered_themes(annotation["labels"])
            assignments[record_id] = {"theme": themes[0], "hash": annotation["source_text_sha256"], "themes": themes}
            counts["translation" if record["kind"] == "translation" else "greek"] += 1
    counts["exported"] = len(assignments)
    return assignments, dict(counts)


def public_config(manifest: dict, assignments_url: str, root: Path) -> dict:
    """Allowlist public metadata; private provenance never reaches JavaScript."""
    presets = manifest["presets"]
    if manifest.get("version") != 1 or manifest.get("default_preset_id") != "garden_grove":
        raise ValueError("Unexpected nature-preset manifest")
    if len(presets) != len(THEMES) or {p["id"] for p in presets} != set(THEMES):
        raise ValueError("Expected exactly the five nature presets")
    public = {}
    for preset in presets:
        title = preset["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Missing preset title")
        small = next(v for v in preset["variants"] if v["width"] == 480)
        for variant in (preset, small):
            url = variant["url"]
            pattern = rf"/assets/nature-presets/{re.escape(preset['id'])}-(480|960)\.[0-9a-f]{{12}}\.webp"
            if not isinstance(url, str) or re.fullmatch(pattern, url) is None:
                raise ValueError("Unsafe nature-preset URL")
            payload = (root / url.lstrip("/")).read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != variant["sha256"] or digest[:12] not in url:
                raise ValueError("Nature-preset content hash mismatch")
        public[preset["id"]] = {"title": title, "url": preset["url"], "smallUrl": small["url"]}
    return {"defaultPresetId": "garden_grove", "presets": public, "assignmentsUrl": assignments_url}


def build(root: Path = ROOT, check: bool = False) -> dict:
    assignments, counts = collect_assignments(root / DATABASE, root / ANNOTATIONS)
    payload = (compact_json(assignments) + "\n").encode("utf-8")
    filename = "assignments." + hashlib.sha256(payload).hexdigest()[:12] + ".json"
    assignment_path = ASSETS / filename
    manifest = json.loads((root / MANIFEST).read_text("utf-8"))
    config = public_config(manifest, "/" + assignment_path.as_posix(), root)
    runtime = ("// Generated by tools/build_nature_assignments.py; do not edit.\n"
               "// Aesthetic defaults are presentation choices, not literary classifications.\n"
               "window.MelosNaturePresetData=" + compact_json(config) + ";\n").encode("utf-8")
    outputs = {assignment_path: payload, RUNTIME: runtime}
    for relative, content in outputs.items():
        destination = root / relative
        if check:
            if not destination.is_file() or destination.read_bytes() != content:
                raise ValueError(f"Nature-preset export is stale: {relative}")
        else:
            if relative == assignment_path and destination.exists() and destination.read_bytes() != content:
                raise ValueError("Content-addressed assignment collision")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    return {"assignments_url": config["assignmentsUrl"], **counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify generated outputs without writing")
    args = parser.parse_args()
    print(json.dumps(build(check=args.check), sort_keys=True))
