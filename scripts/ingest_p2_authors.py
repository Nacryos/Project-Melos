"""Extract source-identified author aliases and literary-dialect context claims.

Run from the repository root: ``py -3.13 scripts/ingest_p2_authors.py``.
The collector keeps downloaded source bytes and never assigns a dialect to a
token or dates an individual poem. OGC identifiers are only joined to
Wikidata entities when the source gives an explicit QID or a CTS identifier.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/p2_authors"
CLAIMS = ROOT / "data/claims/p2_authors.jsonl"
PROFILES = ROOT / "data/metadata/p2-author-profiles.json"
REPORT = ROOT / "data/reports/p2_authors.json"
OGC_COMMIT = "f4062a5013e56d2727e3e88e7a8d8e13d207a06d"
PERSEUS_COMMIT = "bcc5df0602f3b3fe6fefe1e1d575602a25ab1db6"
OGC_BASE = f"https://raw.githubusercontent.com/open-greek/open-greek-corpus/{OGC_COMMIT}/data"
PERSEUS_BASE = f"https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/{PERSEUS_COMMIT}/data"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "MelosCorpus/0.1 (author metadata research; cached source fetches)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    error = None
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                data = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(data)
            temp.replace(path)
            return data
        except (HTTPError, URLError, TimeoutError) as exc:
            error = exc
            if isinstance(exc, HTTPError) and exc.code in (400, 401, 403, 404):
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Download failed: {url}: {error}")


def raw_ref(path: Path, url: str, data: bytes) -> dict:
    return {"source_url": url, "raw_path": path.relative_to(ROOT).as_posix(),
            "raw_sha256": sha256(data), "bytes": len(data)}


def download_sources() -> dict[str, dict]:
    sources = {}
    for name in ("author_ids.json", "author_authority.json", "corpus_catalog.tsv"):
        url = f"{OGC_BASE}/{name}"
        path = RAW / "ogc" / name
        sources[name] = raw_ref(path, url, fetch(url, path))
    for group in ("tlg0012", "tlg0033", "tlg0199"):
        url = f"{PERSEUS_BASE}/{group}/__cts__.xml"
        path = RAW / "perseus" / f"{group}.xml"
        sources[group] = raw_ref(path, url, fetch(url, path))
    # Existing local chronology provides the source-backed QID selection for
    # ten lyric authors. OGC's pinned author authority names Homer as Q6691;
    # the identity is still admitted only if downloaded P12869 matches tlg0012.
    chronology = json.loads((ROOT / "data/metadata/chronology.json").read_text(encoding="utf-8"))
    qids = [entry["entity_id"] for entry in chronology["authors"]]
    authority = json.loads((RAW / "ogc/author_authority.json").read_text(encoding="utf-8"))
    qids.append(authority["tlg0012"]["wikidata"])
    params = {"action": "wbgetentities", "ids": "|".join(qids), "format": "json",
              "props": "labels|aliases|descriptions|claims|sitelinks",
              "languages": "en|el|grc", "languagefallback": "0"}
    url = WIKIDATA_API + "?" + urlencode(params)
    path = RAW / "wikidata_entities_v2.json"
    data = fetch(url, path)
    entities = json.loads(data).get("entities", {})
    if set(qids) - set(entities):
        raise ValueError(f"Missing Wikidata entities: {sorted(set(qids) - set(entities))}")
    sources["wikidata"] = raw_ref(path, url, data)
    return sources


def source_text(source: dict) -> str:
    return (ROOT / source["raw_path"]).read_text(encoding="utf-8")


def evidence(source: dict, quote: str, locator: str) -> dict:
    if quote not in source_text(source):
        raise ValueError(f"Evidence quote missing at {source['raw_path']}: {quote[:80]!r}")
    return {key: source[key] for key in ("source_url", "raw_path", "raw_sha256")} | {
        "quote": quote, "locator": locator}


def json_field_quote(raw: str, field: str, value: str) -> str:
    # JSON string escapes are retained exactly as downloaded. Wikidata's API
    # currently emits compact JSON; OGC emits spaced pretty JSON.
    encoded = json.dumps(value, ensure_ascii=True)
    for candidate in (f'"{field}":{encoded}', f'"{field}": {encoded}'):
        if candidate in raw:
            return candidate
    raise ValueError(f"JSON field not found in raw source: {field}={value!r}")


def make_claim(qid: str, predicate: str, value: dict, evidences: list[dict],
               method: str, source_family: str, key: str, caveat: str = "") -> dict:
    stable = hashlib.sha256(f"{qid}|{predicate}|{source_family}|{key}".encode()).hexdigest()[:16]
    return {
        "id": f"p2-authors:{stable}", "subject": {"type": "author", "id": qid},
        "predicate": predicate, "object": value, "evidence": evidences,
        "assertion_type": "extracted_annotation", "status": "source_claim",
        "method": method, "source_family": source_family,
        "metadata": {"caveat": caveat} if caveat else {},
    }


def parse_identity(sources: dict[str, dict]) -> tuple[list[dict], list[dict], dict]:
    wd_raw = source_text(sources["wikidata"])
    wd = json.loads(wd_raw)["entities"]
    authority = json.loads(source_text(sources["author_authority.json"]))
    registry = json.loads(source_text(sources["author_ids.json"]))["authors"]
    catalog_raw = source_text(sources["corpus_catalog.tsv"])
    catalog = list(csv.DictReader(catalog_raw.splitlines(), delimiter="\t"))
    cts_ns = "{http://chs.harvard.edu/xmlns/cts}"
    groups = {}
    for key in ("tlg0012", "tlg0033", "tlg0199"):
        element = ET.fromstring(source_text(sources[key]))
        groups[key] = (element.attrib["urn"], element.findtext(cts_ns + "groupname"))
    claims: list[dict] = []
    profiles: list[dict] = []
    matches = {"wikidata_cts": 0, "ogc_catalog_rows": 0, "perseus_cts": 0,
               "wikidata_sitelinks": 0}
    for qid, entity in wd.items():
        expected_groups = [group for group, entry in authority.items()
                           if entry.get("wikidata") == qid]
        wd_urns = {statement["mainsnak"]["datavalue"]["value"]
                   for statement in entity.get("claims", {}).get("P12869", [])
                   if statement.get("rank") != "deprecated"
                   and statement.get("mainsnak", {}).get("snaktype") == "value"}
        verified = [group for group in expected_groups
                    if f"urn:cts:greekLit:{group}" in wd_urns]
        if len(verified) != 1:
            raise ValueError(f"No unique OGC ↔ Wikidata CTS identity for {qid}: {verified}")
        group = verified[0]
        urn = f"urn:cts:greekLit:{group}"
        id_evidence = [
            evidence(sources["wikidata"], json_field_quote(wd_raw, "value", urn),
                     f"entities.{qid}.claims.P12869"),
            evidence(sources["author_authority.json"],
                     json_field_quote(source_text(sources["author_authority.json"]), "wikidata", qid),
                     f"{group}.wikidata"),
        ]
        matches["wikidata_cts"] += 1
        if group in groups:
            if groups[group][0] != urn:
                raise ValueError(f"Perseus CTS mismatch for {group}")
            matches["perseus_cts"] += 1
        profile = {"id": qid, "cts_urn": urn, "tlg_id": group,
                   "display_name": entity["labels"]["en"]["value"],
                   "aliases": [], "literary_dialect_claim_ids": [],
                   "source_descriptions": [], "genre_contexts": [],
                   "scope_note": "Author identity and literary context only; no token dialect, form validity, authorship adjudication, or poem date follows."}
        for lang, obj in entity.get("descriptions", {}).items():
            description = obj["value"]
            profile["source_descriptions"].append({
                "text": description, "source": "Wikidata", "language": lang,
                "evidence": evidence(sources["wikidata"],
                                     json_field_quote(wd_raw, "value", description),
                                     f"entities.{qid}.descriptions.{lang}"),
                "usage": "Source description is broad context, not a fixed genre taxonomy or passage classification",
            })
            if re.search(r"\blyric poet\b", description, re.I):
                profile["genre_contexts"].append({
                    "source_label": "lyric poet", "source": "Wikidata English description",
                    "evidence": evidence(sources["wikidata"],
                                         json_field_quote(wd_raw, "value", description),
                                         f"entities.{qid}.descriptions.{lang}"),
                    "scope": "Broad author description; no passage-level genre classification",
                })
        seen_aliases = set()

        def add_alias(label: str, source: str, source_id: str, ev: list[dict],
                      key: str, caveat: str = "") -> None:
            if not label or (source, source_id, label) in seen_aliases:
                return
            seen_aliases.add((source, source_id, label))
            claim = make_claim(qid, "author_alias",
                               {"label": label, "source": source, "source_id": source_id},
                               ev + id_evidence, "cts-author-id-crosswalk-v1", source,
                               key, caveat)
            claims.append(claim)
            profile["aliases"].append({"label": label, "source": source,
                                       "source_id": source_id, "evidence_ids": [claim["id"]]})

        for lang, obj in entity.get("labels", {}).items():
            label = obj["value"]
            add_alias(label, "Wikidata", qid,
                      [evidence(sources["wikidata"], json_field_quote(wd_raw, "value", label),
                                f"entities.{qid}.labels.{lang}")],
                      f"label:{lang}:{label}")
        for lang, aliases in entity.get("aliases", {}).items():
            for obj in aliases:
                label = obj["value"]
                add_alias(label, "Wikidata", qid,
                          [evidence(sources["wikidata"], json_field_quote(wd_raw, "value", label),
                                    f"entities.{qid}.aliases.{lang}")],
                          f"alias:{lang}:{label}")
        wiki = entity.get("sitelinks", {}).get("elwikisource")
        if wiki:
            title = wiki["title"]
            add_alias(title, "Greek Wikisource sitelink", "elwikisource:" + title,
                      [evidence(sources["wikidata"], json_field_quote(wd_raw, "title", title),
                                f"entities.{qid}.sitelinks.elwikisource.title")],
                      f"elwikisource:{title}")
            if ":" in title:
                add_alias(title.split(":", 1)[1], "Greek Wikisource sitelink",
                          "elwikisource:" + title,
                          [evidence(sources["wikidata"], json_field_quote(wd_raw, "title", title),
                                    f"entities.{qid}.sitelinks.elwikisource.title")],
                          f"elwikisource-local:{title}")
            matches["wikidata_sitelinks"] += 1
        if group in groups:
            perseus_name = groups[group][1]
            xml_raw = source_text(sources[group])
            match = re.search(r"<ti:groupname\b[^>]*>" + re.escape(perseus_name) + r"</ti:groupname>", xml_raw)
            if not match:
                raise ValueError(f"No Perseus groupname evidence for {group}")
            add_alias(perseus_name, "Perseus CTS", urn,
                      [evidence(sources[group], match.group(), f"{group}/__cts__.xml groupname")],
                      f"perseus:{group}:{perseus_name}")
        # The catalog's CTS group and OGC's own authority table provide the
        # bridge. The OGA ID then links source slugs across catalog rows.
        identified_rows = [row for row in catalog if row.get("cts_urn", "").startswith(urn + ".")]
        author_ids = {row["author_id"] for row in identified_rows if row["author_id"]}
        for oga_id in sorted(author_ids):
            registered = registry.get(oga_id)
            if not registered:
                raise ValueError(f"Missing OGC author registry ID {oga_id}")
            slug = registered["slug"]
            matching_rows = [row for row in catalog if row["author_id"] == oga_id]
            for row in matching_rows:
                raw_line = next((line for line in catalog_raw.splitlines()
                                 if line.startswith(row["slug"] + "\t")
                                 and ("\t" + row["work_id"] + "\t") in line), None)
                if raw_line is None:
                    raise ValueError(f"No exact catalog row for {row['slug']}")
                ev = [evidence(sources["corpus_catalog.tsv"], raw_line,
                               f"slug={row['slug']};work_id={row['work_id']}")]
                add_alias(row["author"], "OGC corpus catalog", oga_id, ev,
                          f"ogc-author:{oga_id}:{row['author']}")
                matches["ogc_catalog_rows"] += 1
            slug_ev = [evidence(sources["author_ids.json"],
                                json_field_quote(source_text(sources["author_ids.json"]), "slug", slug),
                                f"authors.{oga_id}.slug")]
            add_alias(slug, "OGC author slug", oga_id, slug_ev,
                      f"ogc-slug:{oga_id}:{slug}")
        profiles.append(profile)
    return claims, profiles, matches


def parse_literary_dialect(sources: dict[str, dict], claims: list[dict],
                           profiles: list[dict]) -> int:
    pages = [
        ("dcc_sappho", "https://dcc.dickinson.edu/sappho-introduction",
         ROOT / "data/raw/p2_grammar/dcc.dickinson.edu__sappho-introduction.html"),
        ("goodell", "https://dcc.dickinson.edu/grammar/goodell/introduction",
         ROOT / "data/raw/p2_grammar/dcc.dickinson.edu__grammar__goodell__introduction.html"),
    ]
    dialect_sources = {}
    for key, url, path in pages:
        if not path.exists():
            raise FileNotFoundError(f"Grammar collector has not staged {path}")
        dialect_sources[key] = raw_ref(path, url, path.read_bytes())
        sources[key] = dialect_sources[key]
    dcc_raw = source_text(dialect_sources["dcc_sappho"])
    dcc_match = re.search(r"<p>(The Aeolic dialect was spoken on Lesbos,.*?borrowed many Aeolisms\.)</p>",
                          dcc_raw, re.S)
    if not dcc_match:
        raise ValueError("DCC Aeolic author paragraph missing")
    dcc_quote = dcc_match.group(1)
    dialect_match = re.search(r"The (\w+) dialect was spoken.*?([A-Z]\w+) and the poet ([A-Z]\w+).*?primary literary representatives", dcc_quote)
    if not dialect_match:
        raise ValueError("DCC author/dialect relation missing")
    dcc_dialect, *dcc_authors = dialect_match.groups()
    goodell_raw = source_text(dialect_sources["goodell"])
    goodell_match = re.search(r"<p>.*?(In the literature the dialects were somewhat mingled;.*?the Ionic\.)</p>",
                              goodell_raw, re.S)
    if not goodell_match:
        raise ValueError("Goodell literary dialect paragraph missing")
    goodell_quote = goodell_match.group(1)
    goodell_relations = re.findall(r"(Sappho|Pindar|Homer) \([^)]*\)(?: represents fairly)? the (Aiolic|Doric|Ionic)", goodell_quote)
    # Pindar/Homer clauses include another author before the dialect label,
    # so extract their named clauses explicitly from the same quoted paragraph.
    goodell_relations = []
    for pattern in (r"(Sappho) \([^)]*\) represents fairly the (Aiolic)",
                    r"(Pindar) \([^)]*\) and Theokritos \([^)]*\) the (Doric)",
                    r"(Homer) \([^)]*\) and Herodotos \([^)]*\) the (Ionic)"):
        match = re.search(pattern, goodell_quote)
        if not match:
            raise ValueError(f"Goodell literary-dialect relation missing: {pattern}")
        goodell_relations.append(match.groups())
    by_name = {p["display_name"]: p for p in profiles}
    # Alcaeus's Wikidata display label includes a geographic qualifier.
    by_name["Alcaeus"] = next(p for p in profiles if p["id"] == "Q212872")
    song_match = re.search(r"<p>(The Alexandrian library had nine books \(scrolls\) of songs attributed to Sappho\..*?)</p>",
                           dcc_raw, re.S)
    if not song_match:
        raise ValueError("DCC Sappho song-context paragraph missing")
    by_name["Sappho"]["genre_contexts"].append({
        "source_label": "songs attributed to Sappho", "source": "DCC Sappho Introduction",
        "evidence": evidence(dialect_sources["dcc_sappho"], song_match.group(1),
                             "Sappho's Poems, Alexandrian books paragraph"),
        "scope": "Historical collection description; attribution and genre of a specific fragment require separate evidence",
    })
    by_name["Homer"]["genre_contexts"].append({
        "source_label": "Homeric epic", "source": "DCC Sappho Introduction",
        "evidence": evidence(dialect_sources["dcc_sappho"], "Homeric epic",
                             "Sappho's Dialect, author paragraph"),
        "scope": "Tradition/genre phrase, not proof of authorship for every corpus row",
    })
    count = 0
    for name in dcc_authors:
        profile = by_name[name]
        claim = make_claim(profile["id"], "literary_dialect",
                           {"source_label": dcc_dialect,
                            "scope": "DCC names the poet as a primary literary representative of the Aeolic dialect; not an exclusive or token-level label"},
                           [evidence(dialect_sources["dcc_sappho"], dcc_quote,
                                     "Sappho's Dialect, author paragraph")],
                           "dcc-literary-dialect-paragraph-v1", "dcc-sappho-heather-waddell",
                           f"{name}:{dcc_dialect}",
                           "A literary-context prior only; a particular form may belong to another register or be editorially supplied.")
        claims.append(claim)
        profile["literary_dialect_claim_ids"].append(claim["id"])
        count += 1
    for name, label in goodell_relations:
        profile = by_name[name]
        claim = make_claim(profile["id"], "literary_dialect",
                           {"source_label": label,
                            "scope": "Goodell's broad literary classification; the same paragraph explicitly says literary dialects were somewhat mingled"},
                           [evidence(dialect_sources["goodell"], goodell_quote,
                                     "Goodell, Introduction, literary dialect paragraph")],
                           "goodell-literary-dialect-paragraph-v1", "dcc-goodell-ayer-2018",
                           f"{name}:{label}",
                           "Dated grammar overview, not a form-validity rule or current poem chronology.")
        claims.append(claim)
        profile["literary_dialect_claim_ids"].append(claim["id"])
        count += 1
    return count


def write_outputs(claims: list[dict], profiles: list[dict], sources: dict,
                  matches: dict, dialect_count: int) -> None:
    labels = {alias["label"]: set() for p in profiles for alias in p["aliases"]}
    for profile in profiles:
        for alias in profile["aliases"]:
            labels[alias["label"]].add(profile["id"])
    ambiguous = sorted(label for label, owners in labels.items() if len(owners) > 1)
    corpus = json.loads((ROOT / "data/reports/coverage.json").read_text(encoding="utf-8"))
    corpus_labels = [entry["author_label"] for entry in corpus["authors"]]
    unresolved = [label for label in corpus_labels if label not in labels or label in ambiguous]
    payload = {
        "status": "collected_pending_independent_audit",
        "purpose": "Exact source-linked author identity and qualified literary context priors",
        "profiles": sorted(profiles, key=lambda p: p["display_name"]),
        "unresolved_corpus_labels": unresolved,
        "ambiguous_aliases": ambiguous,
        "lookup_policy": "Exact Unicode/casefold match of source-attested labels; reject cross-profile collisions and mixed-author strings. No similarity or substring match.",
        "dialect_policy": "Literary dialect claims are contextual priors; never assign a token dialect, validate a form, or infer a poem date from this file.",
    }
    CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    PROFILES.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    CLAIMS.write_text("".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in claims), encoding="utf-8")
    PROFILES.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "status": "collected_pending_independent_audit",
        "sources": sources, "profile_count": len(profiles), "claim_count": len(claims),
        "author_alias_claims": len(claims) - dialect_count,
        "literary_dialect_claims": dialect_count,
        "identity_matches": matches,
        "matched_existing_corpus_labels": len(corpus_labels) - len(unresolved),
        "unresolved_corpus_labels": len(unresolved),
        "ambiguous_aliases": ambiguous,
        "new_passages": 0,
        "source_failures": [],
        "source_rights": {"OGC metadata": "repository CC BY-SA 4.0; reused pinned audited source",
                          "Perseus CTS": "repository CC BY-SA 4.0; reused pinned audited source",
                          "Wikidata entity data": "CC0 structured data; source gate PASS",
                          "DCC/Goodell introductions": "CC BY-SA, version unspecified; source gate PASS for bounded quotations"},
        "output_sha256": {"claims": sha256(CLAIMS.read_bytes()),
                          "profiles": sha256(PROFILES.read_bytes())},
        "limitations": ["OGC author catalog and Wikidata CTS linkage are source assertions, not independent proof of every passage's attribution.",
                        "Mixed and uncertain corpus author labels remain unresolved.",
                        "Goodell's dates are excluded; existing chronology remains the sole author-period metadata."]}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    sources = download_sources()
    if args.download_only:
        print(json.dumps(sources, ensure_ascii=False, indent=2))
        return
    claims, profiles, matches = parse_identity(sources)
    dialect_count = parse_literary_dialect(sources, claims, profiles)
    write_outputs(claims, profiles, sources, matches, dialect_count)
    print(f"Wrote {len(profiles)} profiles and {len(claims)} source claims to {PROFILES} / {CLAIMS}")


if __name__ == "__main__":
    main()
