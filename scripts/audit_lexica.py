"""Independent, reproducible audit of the Perseus lexicon JSONL artifacts.

Run after ingestion: python scripts/audit_lexica.py
The twenty seeded traces reparse saved XML, rather than calling the collector.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
from urllib.parse import quote

from betacode import beta_to_uni
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/reports/audit-lexica.json"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
HOMOGRAPH = re.compile(r"\d+$")
SPACE = re.compile(r"\s+")
ENTRY_FIELDS = {"id", "lemma", "lemma_beta", "gloss", "entry_text", "entry_text_encoding",
                "source", "source_url", "entry_url", "raw_path", "raw_sha256",
                "license", "entry_id"}
FORM_FIELDS = {"form", "lemma", "lemma_raw", "analysis", "analysis_format",
               "source", "source_url", "raw_path", "raw_sha256", "license",
               "citation", "document_id", "sentence_id", "token_id", "quality"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha(path: Path) -> str:
    digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def plain_text(element: etree._Element) -> str:
    return compact("".join(element.itertext()))


def fail(errors: list[str], message: str) -> None:
    if len(errors) < 100:
        errors.append(message)


def manifests(errors: list[str]) -> tuple[dict, dict]:
    raw_by_path = {}
    snapshots = {}
    path = ROOT / "data/reports/lexica_ingest.json"
    if not path.is_file():
        fail(errors, f"Missing ingestion manifest: {path.relative_to(ROOT)}")
        return raw_by_path, snapshots
    data = json.loads(path.read_text(encoding="utf-8"))
    for group in ("lsj", "autenrieth", "treebank"):
        snapshot = data.get("snapshots", {}).get(group, {})
        snapshots[group] = {"manifest": path.relative_to(ROOT).as_posix(),
                            "snapshot": snapshot, "reported_counts": data.get("counts", {})}
        files = data.get("raw_files", {}).get(group, [])
        if len(files) != snapshot.get("files"):
            fail(errors, f"{group}: manifest file count differs from snapshot")
        repo = {"lsj": "PerseusDL/lexica", "autenrieth": "gregorycrane/Homerica",
                "treebank": "PerseusDL/treebank_data"}[group]
        if snapshot.get("repository") != repo or not re.fullmatch(r"[0-9a-f]{40}", snapshot.get("commit", "")):
            fail(errors, f"{group}: repository or pinned commit invalid")
        for meta in files:
            rel = meta["raw_path"]
            path = (ROOT / rel).resolve()
            if not path.is_relative_to((ROOT / "data/raw/lexica" / group).resolve()):
                fail(errors, f"{group}: raw path escapes source directory: {rel}")
                continue
            if not path.is_file():
                fail(errors, f"Missing raw source: {rel}")
                continue
            actual_hash = sha256(path)
            if actual_hash != meta.get("raw_sha256") or path.stat().st_size != meta.get("bytes"):
                fail(errors, f"Raw source hash or size mismatch: {rel}")
            if git_blob_sha(path) != meta.get("git_blob_sha"):
                fail(errors, f"Raw source Git blob SHA mismatch: {rel}")
            expected_url = (f"https://raw.githubusercontent.com/{repo}/{snapshot.get('commit')}/"
                            + quote(meta["path"], safe="/"))
            if meta.get("source_url") != expected_url:
                fail(errors, f"Source URL does not match pinned commit: {rel}")
            raw_by_path[rel] = meta
        notices = data.get("license_notices", [])
        if isinstance(notices, dict):
            notices = notices.get(group, [])
        if not notices:
            fail(errors, f"{group}: no saved license/source notices")
        else:
            for notice in notices:
                notice_path = ROOT / notice["raw_path"]
                if not notice_path.is_file() or sha256(notice_path) != notice.get("raw_sha256"):
                    fail(errors, f"{group}: notice missing or hash mismatch: {notice['raw_path']}")
        if group == "lsj" and not any("CC BY-SA 4.0" in n.get("text", "") for n in notices):
            fail(errors, "LSJ: saved notices do not substantiate CC BY-SA 4.0")
        if group == "treebank" and not any("Attribution-ShareAlike 3.0" in n.get("text", "") for n in notices):
            fail(errors, "Treebank: saved notices do not substantiate CC BY-SA 3.0 US")
    return raw_by_path, snapshots


def scan_jsonl(group: str, raw_by_path: dict, errors: list[str]) -> dict:
    path = ROOT / ("data/lexica/entries.jsonl" if group == "lsj" else "data/lexica/forms.jsonl")
    stats = Counter()
    samples = {"lsj": [], "autenrieth": []} if group == "lsj" else {"treebank": []}
    rng = {name: random.Random(seed) for name, seed in
           (("lsj", 20260930), ("autenrieth", 20260932), ("treebank", 20260931))}
    sample_counts = Counter()
    seen_ids = set()
    form_analyses = defaultdict(set)
    if not path.is_file():
        fail(errors, f"Missing output: {path.relative_to(ROOT)}")
        return {"path": path.relative_to(ROOT).as_posix(), "count": 0, "sha256": None, "samples": []}
    before = sha256(path)
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeError) as error:
                fail(errors, f"{group} line {line_number}: invalid JSON: {error}")
                continue
            stats["rows"] += 1
            source_group = row.get("id", "").split(":", 1)[0] if group == "lsj" else "treebank"
            if source_group not in samples:
                fail(errors, f"{group} line {line_number}: unknown dictionary source ID")
                continue
            fields = (ENTRY_FIELDS | ({"edition_year"} if source_group == "autenrieth" else set())) if group == "lsj" else FORM_FIELDS
            if set(row) != fields:
                fail(errors, f"{group} line {line_number}: schema fields differ")
            meta = raw_by_path.get(row.get("raw_path"))
            if not meta:
                fail(errors, f"{group} line {line_number}: unmanifested raw path")
            elif row.get("raw_sha256") != meta["raw_sha256"] or row.get("source_url") != meta["source_url"]:
                fail(errors, f"{group} line {line_number}: source attribution/hash mismatch")
            if f"/lexica/{source_group}/" not in row.get("raw_path", ""):
                fail(errors, f"{group} line {line_number}: record source group differs from raw path")
            if group == "lsj":
                stats[f"{source_group}_rows"] += 1
                if not all(isinstance(row.get(key), str) and row[key] for key in
                           ("id", "lemma", "lemma_beta", "entry_text", "entry_id")):
                    fail(errors, f"lsj line {line_number}: empty required content")
                if row.get("id") in seen_ids:
                    fail(errors, f"lsj line {line_number}: duplicate entry ID {row.get('id')}")
                seen_ids.add(row.get("id"))
                try:
                    expected_lemma = compact(beta_to_uni(HOMOGRAPH.sub("", row["lemma_beta"])))
                    if row.get("lemma") != expected_lemma or not GREEK.search(expected_lemma):
                        fail(errors, f"lsj line {line_number}: Beta Code conversion mismatch")
                except Exception as error:
                    fail(errors, f"lsj line {line_number}: conversion error: {error}")
                if not row.get("gloss"):
                    stats["empty_marked_gloss"] += 1
                if HOMOGRAPH.search(row.get("lemma_beta", "")):
                    stats["homograph_number_in_source_key"] += 1
                if row.get("entry_text_encoding") != "Perseus Beta Code for Greek spans":
                    fail(errors, f"lsj line {line_number}: entry text encoding label changed")
                if source_group == "lsj":
                    if row.get("license") != "CC-BY-SA-4.0" or row.get("source") != "PerseusDL LSJ TEI":
                        fail(errors, f"lsj line {line_number}: source/license label differs")
                elif (row.get("license") != "unknown" or row.get("edition_year") != 1891 or
                      row.get("source") != "Perseus Autenrieth TEI via Homerica"):
                    fail(errors, f"autenrieth line {line_number}: source/license/year label differs")
            else:
                if not all(isinstance(row.get(key), str) and row[key] for key in
                           ("form", "lemma", "lemma_raw", "analysis", "token_id")):
                    fail(errors, f"treebank line {line_number}: empty required content")
                if row.get("lemma") != HOMOGRAPH.sub("", row.get("lemma_raw", "")):
                    fail(errors, f"treebank line {line_number}: lemma normalization mismatch")
                if not GREEK.search(row.get("form", "")) or not GREEK.search(row.get("lemma_raw", "")):
                    fail(errors, f"treebank line {line_number}: non-Greek form/lemma")
                if row.get("analysis_format") != "Perseus treebank 1.6 postag" or row.get("quality") != "annotated_treebank_token":
                    fail(errors, f"treebank line {line_number}: analysis/quality label changed")
                if row.get("license") != "CC-BY-SA-3.0-US":
                    fail(errors, f"treebank line {line_number}: license label differs from source notice")
                if HOMOGRAPH.search(row.get("lemma_raw", "")):
                    stats["homograph_number_in_source_lemma"] += 1
                form_analyses[row.get("form")].add((row.get("lemma_raw"), row.get("analysis")))
            sample_counts[source_group] += 1
            reservoir = samples[source_group]
            target = 5 if group == "lsj" else 10
            if len(reservoir) < target:
                reservoir.append({"line": line_number, "record": row})
            else:
                slot = rng[source_group].randrange(sample_counts[source_group])
                if slot < target:
                    reservoir[slot] = {"line": line_number, "record": row}
    after = sha256(path)
    if before != after:
        fail(errors, f"Output changed during audit: {path.relative_to(ROOT)}")
    if group == "treebank":
        stats["forms_with_multiple_lemma_postag_analyses"] = sum(len(x) > 1 for x in form_analyses.values())
    return {"path": path.relative_to(ROOT).as_posix(), "count": stats["rows"],
            "sha256": after, "stats": dict(stats), "samples": samples}


def trace_entry(item: dict, errors: list[str]) -> dict:
    row = item["record"]
    path = ROOT / row["raw_path"]
    found = None
    source_group = row["id"].split(":", 1)[0]
    context = etree.iterparse(str(path), events=("end",), tag="entryFree", load_dtd=False,
                              no_network=True, resolve_entities=False, huge_tree=True,
                              recover=source_group == "autenrieth")
    for _, entry in context:
        if entry.get("id") == row["entry_id"] and (source_group == "autenrieth" or entry.get("key") == row["lemma_beta"]):
            found = entry
            break
        entry.clear()
        while entry.getprevious() is not None:
            del entry.getparent()[0]
    issues = []
    if found is None:
        issues.append("raw XML entry not found")
    else:
        source_text = plain_text(found)
        translations = []
        for tr in found.iter("tr" if source_group == "lsj" else "gloss"):
            text = plain_text(tr)
            if text and text not in translations:
                translations.append(text)
            if len(translations) >= 4:
                break
        expected_gloss = "; ".join(translations)
        if row["entry_text"] != source_text:
            issues.append("entry_text differs from complete entryFree text")
        if row["gloss"] != expected_gloss:
            issues.append("short gloss differs from first four unique marked translations")
        if source_group == "lsj":
            file_number = re.search(r"perseus-eng(\d+)\.xml$", row["raw_path"])
            if not file_number or row["id"] != f"lsj:{file_number.group(1)}:{row['entry_id']}":
                issues.append("entry ID is not tied to XML file and entry id")
            source_key = row["lemma_beta"]
            work_id = "1999.04.0057"
        else:
            if row["id"] != f"autenrieth:{row['entry_id']}":
                issues.append("entry ID is not tied to XML entry id")
            key = found.get("key", "")
            orth = next(found.iter("orth"), None)
            orth_beta = plain_text(orth) if orth is not None else ""
            first_orth = re.sub(r"[\s_^]", "", orth_beta.split(",", 1)[0].replace("-", ""))
            candidates = [first_orth, HOMOGRAPH.sub("", key)]
            accepted = []
            for candidate in candidates:
                converted = compact(beta_to_uni(candidate))
                if converted and all(GREEK.fullmatch(char) or "\u0300" <= char <= "\u036f" for char in converted):
                    accepted.append((candidate, converted))
                    break
            if not accepted or (row["lemma_beta"], row["lemma"]) != accepted[0]:
                issues.append("lemma does not derive from XML orth/key")
            source_key = key
            work_id = "1999.04.0073"
        expected_url = "https://www.perseus.tufts.edu/hopper/text?doc=" + quote(
            f"Perseus:text:{work_id}:entry={source_key}", safe="")
        if row["entry_url"] != expected_url:
            issues.append("entry URL does not encode source key")
    for issue in issues:
        fail(errors, f"LSJ sample line {item['line']}: {issue}")
    return {"line": item["line"], "id": row["id"], "raw_path": row["raw_path"],
            "raw_sha256": row["raw_sha256"], "source_url": row["source_url"],
            "lemma_beta": row["lemma_beta"], "lemma": row["lemma"],
            "gloss_empty": not bool(row["gloss"]), "result": "PASS" if not issues else "FAIL",
            "issues": issues}


def trace_form(item: dict, errors: list[str]) -> dict:
    row = item["record"]
    path = ROOT / row["raw_path"]
    found = None
    context = etree.iterparse(str(path), events=("end",), tag="sentence", load_dtd=False,
                              no_network=True, resolve_entities=False, huge_tree=True)
    for _, sentence in context:
        if (sentence.get("id", "") == row["sentence_id"] and
                sentence.get("document_id", "") == row["document_id"]):
            for word in sentence.iter("word"):
                if (word.get("id", "") == row["token_id"] and
                        word.get("form", "") == row["form"] and
                        word.get("lemma", "") == row["lemma_raw"] and
                        word.get("postag", "") == row["analysis"]):
                    found = word
                    break
        if found is not None:
            break
        sentence.clear()
        while sentence.getprevious() is not None:
            del sentence.getparent()[0]
    issues = []
    if found is None:
        issues.append("exact XML token/form/lemma/postag not found")
    elif row["citation"] != found.get("cite", ""):
        issues.append("citation differs from XML token")
    for issue in issues:
        fail(errors, f"Treebank sample line {item['line']}: {issue}")
    return {"line": item["line"], "token_id": row["token_id"],
            "sentence_id": row["sentence_id"], "raw_path": row["raw_path"],
            "raw_sha256": row["raw_sha256"], "source_url": row["source_url"],
            "form": row["form"], "lemma_raw": row["lemma_raw"],
            "postag": row["analysis"], "result": "PASS" if not issues else "FAIL",
            "issues": issues}


def inspect_autenrieth_parser(raw_by_path: dict, errors: list[str]) -> dict:
    candidates = [ROOT / rel for rel in raw_by_path if rel.endswith("/autenrieth/autenrieth.xml")]
    if len(candidates) != 1:
        fail(errors, "Autenrieth raw XML is missing or not unique")
        return {}
    context = etree.iterparse(str(candidates[0]), events=("end",), tag="entryFree",
                              load_dtd=False, no_network=True, resolve_entities=False,
                              huge_tree=True, recover=True)
    count = 0
    unresolved_literal = False
    for _, entry in context:
        count += 1
        if not unresolved_literal and re.search(r"&[A-Za-z][\w.]*;", "".join(entry.itertext())):
            unresolved_literal = True
        entry.clear()
        while entry.getprevious() is not None:
            del entry.getparent()[0]
    error_types = dict(Counter(item.type_name for item in context.error_log))
    unexpected = set(error_types) - {"WAR_UNDECLARED_ENTITY"}
    if unexpected:
        fail(errors, f"Autenrieth recover parser encountered non-entity errors: {sorted(unexpected)}")
    if not unresolved_literal:
        fail(errors, "Autenrieth unresolved entity references were not retained as literal text")
    return {"raw_entryFree_count": count, "parser_error_log_types": error_types,
            "error_log_is_capped": len(context.error_log) == 100,
            "unresolved_entity_literals_retained": unresolved_literal}


def main() -> None:
    errors = []
    raw_by_path, snapshots = manifests(errors)
    entries = scan_jsonl("lsj", raw_by_path, errors)
    forms = scan_jsonl("treebank", raw_by_path, errors)
    for group, artifact, counter in (("lsj", entries, "lsj_entries_written"),
                                      ("autenrieth", entries, "autenrieth_entries_written"),
                                      ("treebank", forms, "treebank_tokens_written")):
        reported = snapshots.get(group, {}).get("reported_counts", {}).get(counter)
        actual = artifact["stats"].get(f"{group}_rows", 0) if group != "treebank" else artifact["count"]
        if actual != reported:
            fail(errors, f"{group}: output count {actual} differs from reported {reported}")
    traces = {"entries": [trace_entry(item, errors) for source in ("lsj", "autenrieth")
                           for item in entries["samples"][source]],
              "forms": [trace_form(item, errors) for item in forms["samples"]["treebank"]]}
    aut_parser = inspect_autenrieth_parser(raw_by_path, errors)
    reported_aut_seen = snapshots.get("autenrieth", {}).get("reported_counts", {}).get("autenrieth_entries_seen")
    if aut_parser.get("raw_entryFree_count") != reported_aut_seen:
        fail(errors, "Autenrieth raw entryFree count differs from ingestion report")
    for artifact in (entries, forms):
        del artifact["samples"]
    warnings = []
    if entries.get("stats", {}).get("homograph_number_in_source_key", 0):
        warnings.append("LSJ display lemma strips terminal source-key digits; lemma_beta and entry ID preserve them. Keep keyed senses distinct in lookup.")
    if forms.get("stats", {}).get("homograph_number_in_source_lemma", 0):
        warnings.append("Treebank normalized lemma strips terminal homograph digits; lemma_raw preserves them. Do not claim a unique homograph from normalized lemma.")
    warnings.append("Autenrieth source repository did not provide a verified license notice; its records are labeled unknown and require a reuse decision.")
    warnings.append("Autenrieth XML needs recover=True with unresolved external entity references; source text may omit content represented only by those entities.")
    warnings.append("Treebank postag is a contextual annotated-token analysis, not proof that every identical surface form has that analysis.")
    warnings.append("LSJ gloss is at most four distinct <tr> values, not a complete dictionary definition; empty gloss can be a valid cross-reference entry.")
    report = {"verdict": "FAIL" if errors else "PASS",
              "blocking": bool(errors), "sample_seed": {"lsj": 20260930, "autenrieth": 20260932,
                                                   "treebank": 20260931},
              "raw_file_count": len(raw_by_path), "snapshots": snapshots,
              "autenrieth_parser": aut_parser,
              "outputs": {"entries": entries, "forms": forms}, "traces": traces,
              "files": {"entries.jsonl": {"verdict": "FAIL" if errors else "PASS",
                                           "sha256": entries["sha256"], "count": entries["count"]},
                        "forms.jsonl": {"verdict": "FAIL" if errors else "PASS",
                                         "sha256": forms["sha256"], "count": forms["count"]}},
              "warnings": warnings, "errors": errors}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "blocking": report["blocking"],
                      "entries": entries["count"], "forms": forms["count"],
                      "raw_files": len(raw_by_path), "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
