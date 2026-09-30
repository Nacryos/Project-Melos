"""Independently audit phase-two structured claims before evidence DB ingestion.

Run ``python scripts/audit_p2_claims.py`` for a read-only recheck of staged
claims (apart from audit outputs). To accept a fully inspected file, run
``python scripts/audit_p2_claims.py --accept NAME.jsonl --reason '...'``.
Acceptance is bound to exact file bytes; a later edit revokes it automatically.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "data/claims"
REPORT = ROOT / "data/reports/p2-claim-audit.json"
ACCEPTANCE = ROOT / "data/reports/p2-claim-acceptance.json"
MANIFESTS = (ROOT / "data/reports/audit-acceptance.json",
             ROOT / "data/reports/p2-text-acceptance.json")
WIKI_AUDIT = ROOT / "data/reports/wiktionary-audit.json"
PREDICATES = {"lemma", "morphology", "dialect_label", "sense_gloss",
              "equivalent_form", "variant_reading", "editorial_state", "grammar_rule",
              "author_alias", "literary_dialect", "parallel_proposal"}
ASSERTIONS = {"quoted_source", "extracted_annotation", "model_inference"}
STATUSES = {"source_claim", "machine_proposed", "needs_review"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
SPACE = re.compile(r"\s+")
MAX_ISSUES = 300
TEI_STATES = {"gap": "loss", "supplied": "restoration",
              "unclear": "uncertain_surviving_text", "add": "addition", "del": "deletion"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def root_path(value: str, area: str | None = None) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = (ROOT / value).resolve()
    if not candidate.is_relative_to(ROOT):
        return None
    if area and not candidate.is_relative_to((ROOT / area).resolve()):
        return None
    return candidate


def note(issues: list[str], message: str) -> None:
    if len(issues) < MAX_ISSUES:
        issues.append(message)


class TextHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@lru_cache(maxsize=64)
def raw_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() in {".htm", ".html"}:
        parser = TextHTML()
        parser.feed(text)
        return text + "\n" + " ".join(parser.parts)
    if path.suffix.lower() in {".xml", ".tei"}:
        try:
            return text + "\n" + " ".join(ET.fromstring(text).itertext())
        except ET.ParseError:
            return text
    return text


def source_pointer(entry: dict, locator: str):
    if not isinstance(locator, str) or not locator.startswith("/entry/"):
        raise ValueError("missing /entry JSON pointer")
    value = entry
    for component in locator.split("/")[2:]:
        key = component.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def accepted_parents(needed_files: set[str]) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    """Load only parent rows whose entire output file remains accepted."""
    accepted: dict[str, dict] = {}
    files: dict[str, str] = {}
    errors: list[str] = []
    for manifest in MANIFESTS:
        if not manifest.is_file():
            continue
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        except (KeyError, ValueError, TypeError) as exc:
            note(errors, f"Invalid parent manifest {manifest.name}: {exc}")
            continue
        for name, decision in entries.items():
            if name not in needed_files:
                continue
            if decision.get("verdict") != "PASS":
                continue
            path = root_path(f"data/processed/{name}", "data/processed")
            if not path or not path.is_file() or sha256(path) != decision.get("sha256"):
                note(errors, f"Accepted parent file hash missing/mismatched: {name}")
                continue
            files[name] = decision["sha256"]
            with path.open("rb") as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError):
                        note(errors, f"Accepted parent invalid JSON: {name}:{line_number}")
                        continue
                    record_id = row.get("id")
                    if not isinstance(record_id, str) or not record_id:
                        note(errors, f"Accepted parent missing ID: {name}:{line_number}")
                    elif record_id in accepted and accepted[record_id]["row"] != row:
                        note(errors, f"Conflicting accepted parent ID: {record_id}")
                    else:
                        accepted[record_id] = {
                            "row": row, "jsonl": name,
                            "line_sha256": hashlib.sha256(line.rstrip(b"\r\n")).hexdigest(),
                        }
    if "wiktionary-entries.jsonl" in needed_files and WIKI_AUDIT.is_file():
        try:
            wiki = json.loads(WIKI_AUDIT.read_text(encoding="utf-8"))
            wiki_path = root_path(wiki["output_path"], "data/lexica")
            if wiki.get("status") != "accepted" or not wiki_path or not wiki_path.is_file() \
                    or sha256(wiki_path) != wiki.get("output_sha256"):
                note(errors, "Wiktionary parent acceptance or hash mismatch")
            else:
                files[wiki_path.name] = wiki["output_sha256"]
                with wiki_path.open("rb") as stream:
                    for line_number, line in enumerate(stream, 1):
                        row = json.loads(line)
                        record_id = row.get("id")
                        if record_id in accepted:
                            note(errors, f"Duplicate accepted parent ID: {record_id}")
                        else:
                            accepted[record_id] = {
                                "row": row, "jsonl": wiki_path.name,
                                "line_sha256": hashlib.sha256(line.rstrip(b"\r\n")).hexdigest(),
                            }
        except (KeyError, ValueError, TypeError) as exc:
            note(errors, f"Invalid Wiktionary parent audit: {exc}")
    return accepted, files, errors


def audit_evidence(evidence: dict, claim_id: str, parents: dict[str, dict],
                   raw_hashes: dict[str, str], issues: list[str], warnings: list[str]) -> None:
    prefix = f"{claim_id}: evidence"
    if not isinstance(evidence, dict):
        note(issues, f"{prefix} is not an object")
        return
    for field in ("source_url", "raw_path", "raw_sha256", "quote"):
        if not isinstance(evidence.get(field), str) or not evidence[field]:
            note(issues, f"{prefix} missing {field}")
            return
    if not evidence["source_url"].startswith(("https://", "http://")):
        note(issues, f"{prefix} source_url is not an HTTP source URL")
    if not HASH.fullmatch(evidence["raw_sha256"]):
        note(issues, f"{prefix} raw_sha256 is invalid")
    record_id = evidence.get("record_id")
    wiki_wrapper = isinstance(record_id, str) and record_id.startswith("wiktionary:")
    path = root_path(evidence["raw_path"], "data/lexica" if wiki_wrapper else "data/raw")
    if not path or not path.is_file():
        note(issues, f"{prefix} raw_path is missing or escapes data/raw: {evidence['raw_path']}")
        return
    actual = raw_hashes.get(evidence["raw_path"])
    if actual is None:
        actual = raw_hashes[evidence["raw_path"]] = sha256(path)
    if actual != evidence["raw_sha256"]:
        note(issues, f"{prefix} raw source SHA mismatch: {evidence['raw_path']}")
    quote = evidence["quote"]
    if len(quote) < 3 and quote != "[]" and not (evidence.get("record_id") and
                                                 evidence.get("locator")):
        note(issues, f"{prefix} quote too short to locate")
    parent = parents.get(record_id) if isinstance(record_id, str) else None
    if record_id and not parent:
        note(issues, f"{prefix} unaccepted or unknown parent record: {record_id}")
    locator = evidence.get("locator")
    byte_span = isinstance(locator, dict) and isinstance(locator.get("byte_start"), int) \
        and isinstance(locator.get("byte_end"), int)
    if parent:
        row = parent["row"]
        if wiki_wrapper:
            if evidence["source_url"] != row.get("source_url") or \
                    evidence["raw_path"] != "data/lexica/wiktionary-entries.jsonl" or \
                    evidence["raw_sha256"] != raw_hashes[evidence["raw_path"]]:
                note(issues, f"{prefix} Wiktionary wrapper source attribution mismatch")
        else:
            for field in ("source_url", "raw_path", "raw_sha256"):
                if evidence[field] != row.get(field):
                    note(issues, f"{prefix} {field} differs from accepted parent {record_id}")
        if "parent_sha256" in evidence and evidence["parent_sha256"] != parent["line_sha256"]:
            note(issues, f"{prefix} accepted parent line SHA mismatch: {record_id}")
        parent_texts = [v for v in (row.get("text"),) if isinstance(v, str)]
        parent_texts.extend(v.get("text", "") for v in row.get("lines", [])
                            if isinstance(v, dict))
        if wiki_wrapper:
            try:
                value = source_pointer(row["entry"], locator)
                source_quote = json.dumps(value, ensure_ascii=False)
                if isinstance(value, list) and value and locator == "/entry/forms" and \
                        isinstance(evidence.get("metadata", {}), dict):
                    # Complete forms are checked against object.forms below;
                    # the quote need only reproduce the first source row.
                    source_quote = json.dumps(value[0], ensure_ascii=False)
                in_parent = quote == source_quote
            except (KeyError, IndexError, ValueError, TypeError):
                in_parent = False
        else:
            in_parent = any(quote in text for text in parent_texts)
        if not in_parent and not byte_span:
            note(issues, f"{prefix} quote absent from accepted parent text: {record_id}")
    elif not byte_span:
        # For standalone source claims, locate quotes in the saved artifact.
        # Large line-based source exports should supply a parent record/line.
        if path.stat().st_size > 25_000_000:
            note(issues, f"{prefix} large raw artifact requires accepted parent record")
        elif quote not in raw_text(path):
            if evidence.get("quote_normalization") == "collapse_whitespace" and \
                    SPACE.sub(" ", quote).strip() in SPACE.sub(" ", raw_text(path)).strip():
                note(warnings, f"{prefix} whitespace-normalized quote: {evidence['raw_path']}")
            else:
                note(issues, f"{prefix} quote absent from saved artifact: {evidence['raw_path']}")
    if "locator" in evidence and not isinstance(evidence["locator"], (str, dict)):
        note(issues, f"{prefix} locator must be string or object")
    if isinstance(locator, dict) and ("byte_start" in locator or "byte_end" in locator):
        start, end = locator.get("byte_start"), locator.get("byte_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            note(issues, f"{prefix} invalid byte locator")
        else:
            with path.open("rb") as stream:
                stream.seek(start)
                excerpt = stream.read(end - start)
            if excerpt != quote.encode("utf-8"):
                note(issues, f"{prefix} quote differs from exact raw byte span")


def audit_subject(subject: dict, claim_id: str, parents: dict[str, dict],
                  issues: list[str]) -> None:
    prefix = f"{claim_id}: subject"
    if not isinstance(subject, dict) or not isinstance(subject.get("type"), str):
        note(issues, f"{prefix} missing type")
        return
    passage_id = subject.get("passage_id")
    start, end = subject.get("start"), subject.get("end")
    if (start is None) != (end is None):
        note(issues, f"{prefix} offsets must occur together")
    if start is not None:
        if not passage_id or not isinstance(start, int) or isinstance(start, bool) or \
                not isinstance(end, int) or isinstance(end, bool):
            note(issues, f"{prefix} offsets require passage_id and integer codepoint bounds")
        else:
            parent = parents.get(passage_id)
            if not parent:
                note(issues, f"{prefix} offset parent unaccepted: {passage_id}")
            else:
                text = parent["row"].get("text", "")
                if start < 0 or end <= start or end > len(text):
                    note(issues, f"{prefix} offsets outside original passage text")
                elif subject.get("form") != text[start:end]:
                    note(issues, f"{prefix} form differs from exact original Unicode slice")
    elif passage_id and passage_id not in parents:
        note(issues, f"{prefix} passage_id unaccepted: {passage_id}")
    if subject.get("type") in {"token", "occurrence"} and start is None:
        note(issues, f"{prefix} token/occurrence lacks exact offsets")


def audit_wiktionary_object(row: dict, parent: dict, issues: list[str]) -> None:
    claim_id = row["id"]
    entry = parent["row"]["entry"]
    obj = row.get("object")
    subject = row.get("subject")
    if not isinstance(obj, dict) or not isinstance(subject, dict):
        return
    pred = row["predicate"]
    if obj.get("lemma") is not None and obj["lemma"] != entry.get("word"):
        note(issues, f"{claim_id}: lemma differs from source headword")
    if obj.get("pos") is not None and obj["pos"] != entry.get("pos"):
        note(issues, f"{claim_id}: POS differs from source")
    if "head_templates" in obj and obj["head_templates"] != entry.get("head_templates", []):
        note(issues, f"{claim_id}: head templates differ from source")
    if "inflection_templates" in obj and obj["inflection_templates"] != entry.get("inflection_templates", []):
        note(issues, f"{claim_id}: inflection templates differ from source")
    if "forms" in obj and obj["forms"] != entry.get("forms", []):
        note(issues, f"{claim_id}: full forms array differs from source")
    if "source_form" in obj:
        index = obj.get("form_index")
        forms = entry.get("forms", [])
        if not isinstance(index, int) or index < 0 or index >= len(forms) or \
                obj["source_form"] != forms[index] or subject.get("form") != forms[index].get("form"):
            note(issues, f"{claim_id}: dialect form/index differs from source")
    elif subject.get("form") != entry.get("word"):
        note(issues, f"{claim_id}: subject form differs from source headword")
    index = obj.get("sense_index")
    locator = row.get("evidence", [{}])[0].get("locator", "")
    if index is None and isinstance(locator, str):
        match = re.match(r"/entry/senses/(\d+)(?:/|$)", locator)
        if match:
            index = int(match.group(1))
    senses = entry.get("senses", [])
    if index is not None:
        if not isinstance(index, int) or index < 0 or index >= len(senses):
            note(issues, f"{claim_id}: sense index invalid")
            return
        sense = senses[index]
        if "source_sense" in obj and obj["source_sense"] != sense:
            note(issues, f"{claim_id}: source sense differs from parent")
        for key in ("glosses", "raw_glosses"):
            if key in obj and obj[key] != sense.get(key, []):
                note(issues, f"{claim_id}: {key} differs from source sense")
        for key, source_key in (("source_tags", "tags"), ("source_raw_tags", "raw_tags"),
                                ("sense_glosses", "glosses")):
            if key in obj and obj[key] != sense.get(source_key, []):
                note(issues, f"{claim_id}: {key} differs from source sense")
        if "targets" in obj and obj["targets"] != sense.get(obj.get("relation"), []):
            note(issues, f"{claim_id}: relationship targets differ from source sense")
    elif pred == "sense_gloss":
        note(issues, f"{claim_id}: gloss has no source sense index")
    if "source_form" in obj:
        form = obj["source_form"]
        if obj.get("source_tags") != form.get("tags", []) or \
                obj.get("source_raw_tags") != form.get("raw_tags", []):
            note(issues, f"{claim_id}: dialect form tags differ from source")
    if pred == "dialect_label":
        available = set(obj.get("source_tags", [])) | set(obj.get("source_raw_tags", []))
        if not set(obj.get("labels", [])).issubset(available):
            note(issues, f"{claim_id}: dialect label absent from source tags")


def audit_claim(row: dict, line_number: int, parents: dict[str, dict],
                raw_hashes: dict[str, str], seen: set[str], issues: list[str],
                warnings: list[str], stats: Counter) -> None:
    if not isinstance(row, dict):
        note(issues, f"line {line_number}: claim is not a JSON object")
        return
    claim_id = row.get("id")
    if not isinstance(claim_id, str) or not claim_id:
        note(issues, f"line {line_number}: missing stable claim ID")
        claim_id = f"line {line_number}"
    elif claim_id in seen:
        note(issues, f"line {line_number}: duplicate claim ID {claim_id}")
    seen.add(claim_id)
    predicate = row.get("predicate")
    if predicate not in PREDICATES:
        note(issues, f"{claim_id}: invalid predicate {predicate}")
    if "object" not in row or row["object"] is None:
        note(issues, f"{claim_id}: missing claim object")
    if row.get("assertion_type") not in ASSERTIONS:
        note(issues, f"{claim_id}: invalid assertion_type")
    if row.get("status") not in STATUSES:
        note(issues, f"{claim_id}: invalid status")
    if not isinstance(row.get("method"), str) or not row["method"]:
        note(issues, f"{claim_id}: missing extraction/mapping method")
    if not isinstance(row.get("source_family"), str) or not row["source_family"]:
        note(issues, f"{claim_id}: missing source family")
    if row.get("assertion_type") == "model_inference":
        if row.get("status") != "machine_proposed":
            note(issues, f"{claim_id}: model inference presented as source claim")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict) or not metadata.get("model_identity"):
            note(issues, f"{claim_id}: model identity missing")
    elif row.get("status") == "machine_proposed":
        note(issues, f"{claim_id}: machine proposed without model assertion type")
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        note(issues, f"{claim_id}: empty evidence")
    else:
        for item in evidence:
            audit_evidence(item, claim_id, parents, raw_hashes, issues, warnings)
    if claim_id.startswith("p2-apparatus:") and isinstance(evidence, list) and evidence:
        item = evidence[0]
        obj = row.get("object")
        if isinstance(item, dict) and isinstance(obj, dict):
            try:
                element = ET.fromstring(item["quote"])
                tag = element.tag.rsplit("}", 1)[-1]
            except (ET.ParseError, KeyError, TypeError) as exc:
                note(issues, f"{claim_id}: quoted TEI element cannot be parsed: {exc}")
            else:
                if tag == "app":
                    if predicate != "variant_reading" or obj.get("kind") != "explicit_apparatus":
                        note(issues, f"{claim_id}: app must be an explicit variant reading")
                    if not element.findall("rdg") or not obj.get("alternatives"):
                        note(issues, f"{claim_id}: app reading alternatives missing")
                else:
                    if predicate != "editorial_state" or obj.get("kind") != TEI_STATES.get(tag):
                        note(issues, f"{claim_id}: {tag} editorial state misclassified")
                    if obj.get("tei_tag") != tag or obj.get("attributes") != element.attrib:
                        note(issues, f"{claim_id}: editorial tag/attributes differ from raw TEI")
    audit_subject(row.get("subject"), claim_id, parents, issues)
    subject = row.get("subject", {})
    if isinstance(subject, dict):
        if claim_id.startswith("wiktionary:") or any(
                isinstance(e, dict) and str(e.get("record_id", "")).startswith("wiktionary:")
                for e in evidence if isinstance(evidence, list)):
            for item in evidence if isinstance(evidence, list) else []:
                if not isinstance(item, dict):
                    continue
                parent = parents.get(item.get("record_id"))
                if not parent or not isinstance(parent["row"].get("entry"), dict):
                    continue
                source_entry = parent["row"]["entry"]
                obj = row.get("object", {})
                audit_wiktionary_object(row, parent, issues)
                if isinstance(obj, dict) and "forms" in obj:
                    if obj["forms"] != source_entry.get("forms", []):
                        note(issues, f"{claim_id}: forms differ from full source entry.forms")
                    if item.get("locator") not in ("/entry/forms", "entry.forms"):
                        note(issues, f"{claim_id}: forms evidence lacks exact forms locator")
                if subject.get("passage_id") or subject.get("type") in {"token", "occurrence"}:
                    note(issues, f"{claim_id}: Wiktionary reference asserted as passage attestation")
        if predicate in {"dialect_label", "literary_dialect"} and \
                subject.get("type") in {"author", "work", "passage"}:
            note(warnings, f"{claim_id}: broad dialect subject needs explicit source scope review")
        if predicate == "variant_reading" and row.get("status") == "source_claim":
            note(warnings, f"{claim_id}: variant source claim must remain an attributed alternative")
        if predicate in {"lemma", "morphology", "sense_gloss"} and \
                subject.get("passage_id") and subject.get("start") is None:
            note(warnings, f"{claim_id}: passage claim lacks token offsets; check scope")
    stats[f"predicate:{predicate}"] += 1
    stats[f"status:{row.get('status')}"] += 1
    stats[f"assertion:{row.get('assertion_type')}"] += 1


def audit_author_profiles(raw_hashes: dict[str, str]) -> dict:
    profile_path = ROOT / "data/metadata/p2-author-profiles.json"
    claims_path = CLAIMS / "p2_authors.jsonl"
    collector_report = ROOT / "data/reports/p2_authors.json"
    issues: list[str] = []
    if not all(path.is_file() for path in (profile_path, claims_path, collector_report)):
        return {"verdict": "FAIL", "sha256": None, "records": 0,
                "blocking": True, "failures": ["Author profile/claims/report file missing"], "warnings": []}
    profiles = json.loads(profile_path.read_text(encoding="utf-8"))
    claims = {row["id"]: row for row in
              (json.loads(line) for line in claims_path.open(encoding="utf-8"))}
    reported = json.loads(collector_report.read_text(encoding="utf-8"))
    file_hash = sha256(profile_path)
    if file_hash != reported.get("output_sha256", {}).get("profiles"):
        note(issues, "Profile SHA differs from collector report")
    if sha256(claims_path) != reported.get("output_sha256", {}).get("claims"):
        note(issues, "Author claim SHA differs from collector report")
    items = profiles.get("profiles", [])
    if not isinstance(items, list) or len(items) != reported.get("profile_count"):
        note(issues, "Profile count differs from collector report")
        items = []
    qids: set[str] = set()
    alias_count = 0
    for profile in items:
        qid = profile.get("id")
        if not isinstance(qid, str) or qid in qids:
            note(issues, f"Duplicate/invalid profile identity: {qid}")
        qids.add(qid)
        urn = profile.get("cts_urn", "")
        if urn != f"urn:cts:greekLit:{profile.get('tlg_id')}":
            note(issues, f"{qid}: CTS URN/TLG identity mismatch")
        for alias in profile.get("aliases", []):
            alias_count += 1
            if not alias.get("evidence_ids"):
                note(issues, f"{qid}: alias has no claim evidence")
            for claim_id in alias.get("evidence_ids", []):
                row = claims.get(claim_id)
                if not row or row.get("predicate") != "author_alias" or \
                        row.get("subject", {}).get("id") != qid or \
                        any(alias.get(field) != row.get("object", {}).get(field)
                            for field in ("label", "source", "source_id")):
                    note(issues, f"{qid}: alias/claim mismatch {claim_id}")
        for claim_id in profile.get("literary_dialect_claim_ids", []):
            row = claims.get(claim_id)
            if not row or row.get("predicate") != "literary_dialect" or \
                    row.get("subject", {}).get("id") != qid:
                note(issues, f"{qid}: literary-dialect claim mismatch {claim_id}")
        for field in ("source_descriptions", "genre_contexts"):
            for item in profile.get(field, []):
                evidence = item.get("evidence", {})
                path = root_path(evidence.get("raw_path", ""), "data/raw")
                if not path or not path.is_file():
                    note(issues, f"{qid}: {field} source missing")
                    continue
                actual = raw_hashes.get(evidence["raw_path"])
                if actual is None:
                    actual = raw_hashes[evidence["raw_path"]] = sha256(path)
                if actual != evidence.get("raw_sha256") or \
                        evidence.get("quote", "") not in raw_text(path):
                    note(issues, f"{qid}: {field} source quote/hash mismatch")
    if alias_count != reported.get("author_alias_claims"):
        note(issues, "Profile alias count differs from author claim count")
    if len([row for row in claims.values() if row.get("predicate") == "literary_dialect"]) != \
            reported.get("literary_dialect_claims"):
        note(issues, "Literary-dialect claim count differs from collector report")
    return {"verdict": "FAIL" if issues else "PASS", "sha256": file_hash,
            "records": len(items), "aliases": alias_count, "blocking": bool(issues),
            "failures": issues, "warnings": []}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept", action="append", default=[], metavar="NAME.jsonl")
    parser.add_argument("--only", action="append", default=[], metavar="NAME.jsonl",
                        help="audit just these claim files; retain other existing decisions")
    parser.add_argument("--reason", help="specific manual review rationale for --accept")
    args = parser.parse_args()
    if args.accept and not args.reason:
        parser.error("--accept requires --reason")
    claim_paths = sorted(CLAIMS.glob("*.jsonl")) if CLAIMS.is_dir() else []
    if args.only:
        claim_paths = [path for path in claim_paths if path.name in args.only]
        if len(claim_paths) != len(set(args.only)):
            parser.error("--only named a missing claim file")
    source_to_parents = {
        "p2_notes.jsonl": {"sappho.jsonl"},
        "p2_apparatus.jsonl": {"commentary.jsonl", "perseus.jsonl"},
        "p2_grammar.jsonl": {"p2_grammar.jsonl"},
        "p2_wiktionary.jsonl": {"wiktionary-entries.jsonl"},
    }
    needed_files = set().union(*(source_to_parents.get(path.name, set()) for path in claim_paths))
    parents, parent_files, parent_errors = accepted_parents(needed_files)
    previous = {}
    if ACCEPTANCE.is_file():
        previous = json.loads(ACCEPTANCE.read_text(encoding="utf-8")).get("files", {})
    raw_hashes: dict[str, str] = {}
    reports: dict[str, dict] = {}
    acceptance: dict[str, dict] = dict(previous) if args.only else {}
    for path in claim_paths:
        issues: list[str] = []
        warnings: list[str] = []
        stats: Counter = Counter()
        seen: set[str] = set()
        file_hash = sha256(path)
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    note(issues, f"line {line_number}: invalid JSON: {exc}")
                    continue
                audit_claim(row, line_number, parents, raw_hashes, seen, issues, warnings, stats)
                stats["records"] += 1
        if not stats["records"]:
            note(issues, "Empty claim file")
        report = {"sha256": file_hash, "records": stats["records"],
                  "verdict": "FAIL" if issues else "PASS", "blocking": bool(issues),
                  "stats": dict(stats), "warnings": warnings[:MAX_ISSUES],
                  "failures": issues[:MAX_ISSUES]}
        reports[path.name] = report
        old = previous.get(path.name, {})
        if path.name in args.accept and not issues:
            reason = args.reason
        elif old.get("verdict") == "PASS" and old.get("sha256") == file_hash and not issues:
            reason = old.get("manual_reason")
        else:
            reason = None
        if reason:
            acceptance[path.name] = {"verdict": "PASS", "sha256": file_hash,
                                     "records": stats["records"],
                                     "audit_report": "data/reports/p2-claim-audit.json",
                                     "manual_reason": reason}
        else:
            acceptance[path.name] = {"verdict": "FAIL" if issues else "PENDING_MANUAL",
                                     "sha256": file_hash, "records": stats["records"],
                                     "audit_report": "data/reports/p2-claim-audit.json"}
    if any(path.name == "p2_authors.jsonl" for path in claim_paths):
        profile_report = audit_author_profiles(raw_hashes)
        reports["p2-author-profiles.json"] = profile_report
        old = previous.get("p2-author-profiles.json", {})
        if (not profile_report["blocking"] and acceptance["p2_authors.jsonl"]["verdict"] == "PASS"):
            reason = args.reason if "p2_authors.jsonl" in args.accept else old.get("manual_reason") \
                if old.get("sha256") == profile_report["sha256"] else None
        else:
            reason = None
        acceptance["p2-author-profiles.json"] = {
            "kind": "metadata", "verdict": "PASS" if reason else
            "FAIL" if profile_report["blocking"] else "PENDING_MANUAL",
            "sha256": profile_report["sha256"], "records": profile_report["records"],
            "audit_report": "data/reports/p2-claim-audit.json"}
        if reason:
            acceptance["p2-author-profiles.json"]["manual_reason"] = reason
    for requested in args.accept:
        if requested not in reports or reports[requested]["blocking"]:
            raise SystemExit(f"Cannot accept missing or failed file: {requested}")
    output = {"verdict": "FAIL" if parent_errors or any(r["blocking"] for r in reports.values())
              else "PASS" if reports else "NO_INPUT",
              "audited_files_this_run": [path.name for path in claim_paths],
              "accepted_files": {name: {"sha256": decision.get("sha256"),
                                         "records": decision.get("records"),
                                         "kind": decision.get("kind", "claims")}
                                 for name, decision in acceptance.items()
                                 if decision.get("verdict") == "PASS"},
              "accepted_parent_files": parent_files, "accepted_parent_records": len(parents),
              "parent_errors": parent_errors, "raw_files_hashed": len(raw_hashes),
              "files": reports}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ACCEPTANCE.write_text(json.dumps({"files": acceptance}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps({"verdict": output["verdict"], "files": {
        name: {"verdict": item["verdict"], "records": item["records"],
               "failures": len(item["failures"]), "warnings": len(item["warnings"])}
        for name, item in reports.items()}, "parent_errors": parent_errors}, ensure_ascii=False, indent=2))
    if output["verdict"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
