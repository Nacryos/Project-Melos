"""Extract source-stated Sappho form claims from accepted commentary records.

The input is the already downloaded and independently accepted Sappho JSONL;
this script never supplies Greek readings or grammatical analyses of its own.
Uncertain alignments remain form-level claims. Run from the repository root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from backend.source_grammar import grammar_disjunctions

INPUT = ROOT / "data/processed/sappho.jsonl"
AUDIT = ROOT / "data/reports/audit-sappho.json"
OUTPUT = ROOT / "data/claims/p2_notes.jsonl"
REPORT = ROOT / "data/reports/p2_notes.json"

GREEK = r"[\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]"
GWORD = rf"{GREEK}+(?:[’']{GREEK}+)?"
HEAD = re.compile(rf"^\s*(?:\d{{1,3}}\s+)?(?P<form>{GWORD})")
NOTE_HEAD = re.compile(rf"(?P<form>{GWORD})\s*:\s*")
EQUIV = re.compile(rf"^\s*(?P<relation>=|>|Aeol\.?\s+for)\s*(?P<form>{GWORD})(?!\s*(?:\+|{GREEK}))", re.I)
FROM = re.compile(rf"\bfrom\s+(?P<form>{GWORD})(?!\s*(?:\+|{GREEK}))", re.I)
TOKEN = re.compile(GWORD)
GRAM = re.compile(
    r"(?<!\w)(?:(?:[123](?:st|nd|rd)\s+)?(?:sg|pl)\.?\s+)?"
    r"(?:(?:pres|aor|imperf|fut|perf)\.?\s+)?"
    r"(?:(?:act|mid|pass)\.?\s+)?"
    r"(?:(?:ind|indic|subj|opt|inf|infin|imper|partic|ptc)\.?(?![A-Za-z])\s*)"
    r"|(?<!\w)(?:nom|gen|dat|acc|voc)\.?\s+(?:sg|pl)\.?"
    r"(?:\s+(?:masc|fem|neut)\.?)?",
    re.I,
)
FEATURES = {
    "pres": ("tense", "present"), "aor": ("tense", "aorist"),
    "imperf": ("tense", "imperfect"), "fut": ("tense", "future"),
    "perf": ("tense", "perfect"), "act": ("voice", "active"),
    "mid": ("voice", "middle"), "pass": ("voice", "passive"),
    "ind": ("mood", "indicative"), "indic": ("mood", "indicative"),
    "subj": ("mood", "subjunctive"), "opt": ("mood", "optative"),
    "inf": ("mood", "infinitive"), "infin": ("mood", "infinitive"),
    "imper": ("mood", "imperative"), "partic": ("mood", "participle"),
    "ptc": ("mood", "participle"), "nom": ("case", "nominative"),
    "gen": ("case", "genitive"), "dat": ("case", "dative"),
    "acc": ("case", "accusative"), "voc": ("case", "vocative"),
    "sg": ("number", "singular"), "pl": ("number", "plural"),
    "masc": ("gender", "masculine"), "fem": ("gender", "feminine"),
    "neut": ("gender", "neuter"), "1st": ("person", 1),
    "2nd": ("person", 2), "3rd": ("person", 3),
}
FEATURE_TOKEN = re.compile(r"[123](?:st|nd|rd)|[A-Za-z]+")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def features(raw: str) -> dict:
    """A documented abbreviation expansion, not a new morphological analysis."""
    result = {}
    for match in FEATURE_TOKEN.finditer(raw):
        item = FEATURES.get(match.group().lower())
        if item:
            result[item[0]] = item[1]
    return result


def fold(form: str, *, diacritics: bool = False) -> str:
    value = unicodedata.normalize("NFD", form).casefold()
    if diacritics:
        value = "".join(c for c in value if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", value)


def source_records() -> tuple[list[dict], dict[str, str]]:
    expected = json.loads(AUDIT.read_text(encoding="utf-8"))["files"][INPUT.name]
    assert expected["verdict"] == "PASS", "Source is not accepted"
    raw = INPUT.read_bytes()
    assert sha(raw) == expected["sha256"], "Accepted source hash changed"
    records, hashes = [], {}
    for line in raw.splitlines():
        record = json.loads(line)
        records.append(record)
        hashes[record["id"]] = sha(line)
    for path, raw_hash in {(r["raw_path"], r["raw_sha256"]) for r in records}:
        assert sha((ROOT / path).read_bytes()) == raw_hash, f"Raw artifact changed: {path}"
    return records, hashes


def candidates(parent: dict | None, form: str, line_label: str | None = None) -> tuple[list[dict], str]:
    if not parent or parent.get("language") != "grc":
        return [], "no_parent"
    text = parent["text"]
    spans = [(m.start(), m.end(), m.group()) for m in TOKEN.finditer(text)]
    if line_label and parent.get("lines"):
        lines = [line for line in parent["lines"] if str(line.get("label")) == str(line_label)]
        if len(lines) == 1 and lines[0]["text"]:
            positions = [m.start() for m in re.finditer(re.escape(lines[0]["text"]), text)]
            if len(positions) == 1:
                lo, hi = positions[0], positions[0] + len(lines[0]["text"])
                spans = [s for s in spans if lo <= s[0] and s[1] <= hi]
    exact = [s for s in spans if fold(s[2]) == fold(form)]
    matched, match_type = (exact, "casefold_nfd") if exact else (
        [s for s in spans if fold(s[2], diacritics=True) == fold(form, diacritics=True)],
        "diacritic_fold",
    )
    return [dict(start=a, end=b, surface=token) for a, b, token in matched], match_type


def evidence(record: dict, hashes: dict[str, str], quote: str) -> list[dict]:
    assert quote and quote in record["text"]
    return [{
        "record_id": record["id"], "source_url": record["source_url"],
        "raw_path": record["raw_path"], "raw_sha256": record["raw_sha256"],
        "parent_sha256": hashes[record["id"]], "quote": quote,
        "locator": record.get("metadata", {}).get("line_label") or record.get("citation"),
    }]


def make_claim(record: dict, parent: dict | None, hashes: dict[str, str],
               form: str, predicate: str, obj: dict, quote: str,
               method: str, line_label: str | None = None) -> dict:
    linked, match_type = candidates(parent, form, line_label)
    subject = {"type": "form", "form": form}
    if len(linked) == 1:
        subject.update(form=linked[0]["surface"], passage_id=parent["id"],
                       start=linked[0]["start"], end=linked[0]["end"])
    fingerprint = "\x1f".join([record["id"], form, predicate, json.dumps(obj, ensure_ascii=False, sort_keys=True), quote])
    claim = {
        "id": "p2-notes:" + sha(fingerprint.encode("utf-8"))[:24],
        "subject": subject, "predicate": predicate, "object": obj,
        "evidence": evidence(record, hashes, quote),
        "assertion_type": "extracted_annotation", "status": "source_claim",
        "method": method,
        "source_family": "DCC Sappho" if record["id"].startswith("dcc-") else "The Digital Sappho",
        "metadata": {"source_form": form, "match_type": match_type,
                     "match_candidates": linked if len(linked) != 1 else [],
                     "line_label": line_label or record.get("metadata", {}).get("line_label") or None},
    }
    return claim


def first_grammar(text: str) -> tuple[str, dict] | None:
    match = GRAM.search(text)
    if not match:
        return None
    end = match.end()
    # A source may state verbal and nominal participle features in sequence:
    # "aor. act. partic. acc. sg. fem." Preserve the full contiguous label.
    while True:
        next_match = GRAM.match(text, end)
        if not next_match or next_match.end() <= end:
            break
        end = next_match.end()
    raw = text[match.start():end].strip()
    mapped = features(raw)
    if not mapped:
        return None
    return raw, mapped


def grammar_objects(parsed: tuple[str, dict], quote: str, body: str,
                    body_offset: int) -> list[dict]:
    """Preserve source alternatives; split only directly attached parentheses.

    No branch inherits unprinted features. Prose discussion remains a single
    qualified projection, never a new analysis of the note's headword.
    Offsets refer to the exact retained evidence quote, not the Greek passage.
    """
    raw, mapped = parsed
    obj = {"raw_label": raw, "features": mapped}
    anchors = list(re.finditer(re.escape(raw), quote, re.I))
    alternatives = [item for item in grammar_disjunctions(quote)
                    if any(item['quote_start'] <= match.start() < match.end() <= item['quote_end']
                           for match in anchors)]
    if not alternatives:
        return [obj]
    obj['source_grammar_alternatives'] = alternatives
    # Only literal headword -> optional explicit equivalent form -> parenthesis
    # proves the note's grammatical scope without interpreting English prose.
    prefix_end = 0
    relation = EQUIV.match(body)
    if relation and explicit_equivalence(body):
        prefix_end = relation.end()
    opening = re.match(r'\s*\(\s*', body[prefix_end:])
    direct_start = body_offset + prefix_end + opening.end() if opening else None
    direct = [item for item in alternatives if item['quote_start'] == direct_start]
    if len(direct) != 1:
        obj['source_grammar_scope'] = 'unresolved_prose_scope'
        return [obj]
    item = direct[0]
    # A malformed/unclosed parenthesis does not establish a complete annotation.
    tail = quote[item['quote_end']:]
    if ')' not in tail or '(' in tail.split(')', 1)[0]:
        obj['source_grammar_scope'] = 'unresolved_annotation_boundary'
        return [obj]
    if any(branch['unresolved_feature_keys'] or not branch['explicit_features']
           for branch in item['branches']):
        obj['source_grammar_scope'] = 'unresolved_branch_features'
        return [obj]
    return [{"raw_label": branch['raw_label'], "features": branch['explicit_features'],
             "source_grammar_alternatives": alternatives,
             "source_grammar_scope": "direct_headword_parenthesis",
             "source_grammar_branch": {"index": index, "quote_start": branch['start'],
                                       "quote_end": branch['end']}}
            for index, branch in enumerate(item['branches'])]


def explicit_equivalence(body: str) -> tuple[str, str] | None:
    match = EQUIV.match(body)
    if not match:
        return None
    # Split crases and spaced OCR letters are not single equivalent forms.
    tail = body[match.end():]
    if tail.lstrip().startswith("+") or re.match(rf"\s+{GWORD}", tail):
        return None
    return match.group("relation").strip(), match.group("form")


def greek_length(form: str) -> int:
    return sum(1 for c in form if "GREEK" in unicodedata.name(c, "") and not unicodedata.combining(c))


def digital_vocabulary(record: dict, parent: dict | None, hashes: dict[str, str]) -> list[dict]:
    text = record["text"]
    head = HEAD.match(text)
    if not head:
        return []
    form = head.group("form")
    rest = text[head.end():]
    if greek_length(form) < 2 or rest.lstrip().startswith(("...", "…")):
        return []
    line_label = record.get("metadata", {}).get("line_label") or None
    claims = []
    # Explicit form equivalences only. A lemma headword is not silently equated
    # with a different inflected token in the Greek passage.
    equivalent = explicit_equivalence(rest[:110])
    if equivalent:
        relation, target = equivalent
        predicate = "lemma" if relation == ">" else "equivalent_form"
        claims.append(make_claim(record, parent, hashes, form, predicate,
                                 {"form": target, "relation_raw": relation},
                                 text, "digital_vocabulary_explicit_equivalence_v2", line_label))
    first_paren = re.match(r"^\s*\(([^)]{1,100})\)", rest)
    lemma = FROM.search(first_paren.group(1)) if first_paren else None
    if lemma and lemma.group("form") != form:
        claims.append(make_claim(record, parent, hashes, form, "lemma",
                                 {"form": lemma.group("form"), "relation_raw": "from"},
                                 text, "digital_vocabulary_explicit_from_v1", line_label))
    # A grammatical parenthesis or compact label describes the headword's
    # passage use only when that headword actually aligns with the passage.
    linked, _ = candidates(parent, form, line_label)
    grammar_scope = rest[:180]
    parsed = first_grammar(grammar_scope)
    if parsed and len(linked) == 1:
        for obj in grammar_objects(parsed, text, rest, head.end()):
            method = ("digital_vocabulary_grammar_alternatives_v2" if 'source_grammar_alternatives' in obj
                      else "digital_vocabulary_grammar_v1")
            claims.append(make_claim(record, parent, hashes, form, "morphology",
                                     obj, text, method, line_label))
    # A verb's explicit English infinitival gloss is source text, not a model
    # translation. Restrict to the first simple clause before prose commentary.
    gloss_scope = rest.lstrip()
    if first_paren:
        gloss_scope = rest[first_paren.end():].lstrip()
    aeol_prefix = re.match(rf"^Aeol\.?\s+for\s+{GWORD}\s*,?\s*", gloss_scope, re.I)
    if aeol_prefix:
        gloss_scope = gloss_scope[aeol_prefix.end():]
    gloss = re.match(r"^to\s+([a-z][A-Za-z -]{1,65})(?=[,;.(]|$)", gloss_scope[:90])
    if gloss:
        value = "to " + gloss.group(1).strip()
        claims.append(make_claim(record, parent, hashes, form, "sense_gloss",
                                 {"text": value}, text,
                                 "digital_vocabulary_explicit_to_gloss_v1", line_label))
    elif not equivalent and not re.match(r"^\s*=\s*[^,.;]{0,60}\+", rest):
        article = re.search(r"\((?:ὁ|ἡ|τό|τὸ|αἱ)\)\s+", rest[:65])
        if article:
            noun_body = rest[article.end():]
            noun_gloss = re.match(r"([A-Za-z][^().;]{0,90})(?=[.;(]|$)", noun_body)
            if noun_gloss:
                value = noun_gloss.group(1).strip().rstrip(",")
                next_entry = re.search(rf"\s+\d{{1,3}}\s+{GWORD}", value)
                if value and not next_entry and not value.lower().startswith(("aeol", "see ", "and ")):
                    claims.append(make_claim(record, parent, hashes, form, "sense_gloss",
                                             {"text": value}, text,
                                             "digital_vocabulary_article_gloss_v1", line_label))
    return claims


def dcc_notes(record: dict, parent: dict | None, hashes: dict[str, str]) -> list[dict]:
    claims = []
    line_label = None
    for line in record["text"].splitlines():
        heading = re.match(r"^\s*(\d{1,3})\s*:??\s+", line)
        if heading:
            line_label = heading.group(1)
        heads = list(NOTE_HEAD.finditer(line))
        for i, head in enumerate(heads):
            form = head.group("form")
            if greek_length(form) < 2:
                continue
            end = heads[i + 1].start() if i + 1 < len(heads) else len(line)
            segment = line[head.start():end].strip()
            body = line[head.end():end]
            eq = explicit_equivalence(body[:90])
            if eq:
                relation, target = eq
                predicate = "lemma" if relation == ">" else "equivalent_form"
                claims.append(make_claim(record, parent, hashes, form, predicate,
                                         {"form": target, "relation_raw": relation},
                                         segment, "dcc_note_colon_equivalence_v2", line_label))
            first_paren = re.match(r"^\s*\(([^)]{1,100})\)", body)
            lemma = FROM.search(first_paren.group(1)) if first_paren else None
            if lemma and lemma.group("form") != form:
                claims.append(make_claim(record, parent, hashes, form, "lemma",
                                         {"form": lemma.group("form"), "relation_raw": "from"},
                                         segment, "dcc_note_colon_lemma_v1", line_label))
            grammar_scope = body[:95]
            leading_relation = EQUIV.match(grammar_scope)
            if leading_relation and eq:
                grammar_scope = grammar_scope[leading_relation.end():]
            grammar_start = GRAM.search(grammar_scope)
            # Another Greek word before the label usually signals a discussion
            # of that other word, rather than analysis of the colon headword.
            if grammar_start and TOKEN.search(grammar_scope[:grammar_start.start()]):
                grammar_scope = ""
            parsed = first_grammar(grammar_scope)
            if parsed:
                for obj in grammar_objects(parsed, segment, body, head.end() - head.start()):
                    method = ("dcc_note_colon_grammar_alternatives_v2" if 'source_grammar_alternatives' in obj
                              else "dcc_note_colon_grammar_v1")
                    claims.append(make_claim(record, parent, hashes, form, "morphology",
                                             obj, segment, method, line_label))
    return claims


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging-dir', type=Path,
                        help='New directory below data/staging; leaves active claims/reports unchanged.')
    args = parser.parse_args(argv)
    output, report_path = OUTPUT, REPORT
    baseline_bytes = OUTPUT.read_bytes() if OUTPUT.exists() else b''
    baseline = {row['id']: row for row in map(json.loads, baseline_bytes.splitlines())}
    bindings = {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path.read_bytes())
                for path in (INPUT, AUDIT, OUTPUT, Path(__file__), ROOT / 'backend/source_grammar.py')}
    if args.staging_dir:
        staging = args.staging_dir.resolve()
        if not staging.is_relative_to((ROOT / 'data/staging').resolve()) or staging == (ROOT / 'data/staging').resolve():
            raise ValueError('Staging output must be a new child directory below data/staging')
        if staging.exists():
            raise FileExistsError(f'Staging directory already exists: {staging}')
        output, report_path = staging / 'p2_notes.jsonl', staging / 'report.json'
    records, hashes = source_records()
    by_id = {r["id"]: r for r in records}
    claims = []
    statistics = Counter()
    per_source = defaultdict(Counter)
    for record in records:
        subtype = record.get("metadata", {}).get("subtype")
        if record["id"].startswith("digital-sappho:") and subtype == "vocabulary":
            statistics["digital_vocabulary_examined"] += 1
            extracted = digital_vocabulary(record, by_id.get(record.get("parent_id")), hashes)
        elif record["id"].startswith("dcc-sappho:") and subtype == "notes":
            statistics["dcc_notes_examined"] += 1
            extracted = dcc_notes(record, by_id.get(record.get("parent_id")), hashes)
        else:
            continue
        if not extracted:
            statistics["records_without_claim"] += 1
        for claim in extracted:
            per_source[record["id"].split(":")[0]][claim["predicate"]] += 1
            statistics[claim["predicate"]] += 1
            if "passage_id" in claim["subject"]:
                statistics["unique_token_alignments"] += 1
            elif claim["metadata"]["match_candidates"]:
                statistics["ambiguous_token_alignments"] += 1
            else:
                statistics["unmatched_forms"] += 1
        claims.extend(extracted)
    ids = [c["id"] for c in claims]
    assert len(ids) == len(set(ids)), "Claim ID collision or duplicate extraction"
    grouped = defaultdict(list)
    for claim in claims:
        subject = claim["subject"]
        if "passage_id" in subject:
            key = (subject["passage_id"], subject["start"], subject["end"], claim["predicate"])
            grouped[key].append(claim)
    conflicts = []
    for key, group in grouped.items():
        values = {json.dumps(c["object"], ensure_ascii=False, sort_keys=True) for c in group}
        if len(values) > 1:
            conflicts.append({"passage_id": key[0], "start": key[1], "end": key[2],
                              "predicate": key[3], "claim_ids": [c["id"] for c in group]})
    for relative, digest in bindings.items():
        assert sha((ROOT / relative).read_bytes()) == digest, f'Input/code changed during extraction: {relative}'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in claims)
    output.write_text(payload, encoding="utf-8", newline="\n")
    new_by_id = {claim['id']: claim for claim in claims}
    removed = sorted(baseline.keys() - new_by_id.keys())
    added = sorted(new_by_id.keys() - baseline.keys())
    report = {
        "input": str(INPUT.relative_to(ROOT)).replace("\\", "/"),
        "input_sha256": sha(INPUT.read_bytes()),
        "output": str(output.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha(output.read_bytes()),
        "input_bindings": bindings,
        "staged_only": bool(args.staging_dir),
        "claim_changes": {"removed": removed, "added": added,
                          "same_id_changed": sorted(i for i in baseline.keys() & new_by_id.keys()
                                                    if baseline[i] != new_by_id[i]),
                          "replacements_by_source_record": [
                              {"removed_id": i, "source_record_id": baseline[i]['evidence'][0]['record_id'],
                               "replacement_ids": [j for j in added if new_by_id[j]['evidence'] == baseline[i]['evidence']
                                                    and new_by_id[j]['subject'] == baseline[i]['subject']]}
                              for i in removed]},
        "count": len(claims), "counts": dict(statistics),
        "coverage": {"records_examined": statistics["digital_vocabulary_examined"] + statistics["dcc_notes_examined"],
                     "records_parsed": statistics["digital_vocabulary_examined"] + statistics["dcc_notes_examined"] - statistics["records_without_claim"],
                     "records_without_supported_pattern": statistics["records_without_claim"],
                     "linked_claims": statistics["unique_token_alignments"],
                     "form_only_claims": statistics["unmatched_forms"] + statistics["ambiguous_token_alignments"]},
        "conflict_groups": len(conflicts), "conflict_examples": conflicts[:20],
        "by_source": {k: dict(v) for k, v in per_source.items()},
        "method_note": "Only explicit commentary strings are extracted. Abbreviation expansions use FEATURES in this script. Parent offsets occur only for a single matching token; ambiguous candidates remain in metadata without a passage ID. Diacritic-fold alignments are labeled and do not assert identical spelling.",
        "examples": [c for c in claims if c["metadata"]["source_form"] == "πέμπην"][:5],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(claims), "counts": dict(statistics), "output_sha256": report["output_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
