"""Download Wikidata author chronology claims without dating any poems.

The name-to-entity mapping is a disambiguation configuration. Each QID is cited by
its entity URL, and all output claims are extracted from saved API responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/metadata/raw/wikidata_entities.json"
OUTPUT = ROOT / "data/metadata/chronology.json"
API = "https://www.wikidata.org/w/api.php"
ENTITIES = {
    # Entity selections cite https://www.wikidata.org/wiki/{QID}.
    "Archilochus": "Q201323",
    "Alcman": "Q298850",
    "Sappho": "Q17892",
    "Alcaeus": "Q212872",
    "Stesichorus": "Q332797",
    "Ibycus": "Q332802",
    "Anacreon": "Q213484",
    "Simonides": "Q273003",
    "Pindar": "Q134929",
    "Bacchylides": "Q310681",
    # Release O (2026-10-09): the other poets and authors in the corpus, selected by
    # wbsearchentities label + description (an ancient Greek poet/author of that name).
    "Homer": "Q6691", "Hesiod": "Q44233", "Theognis": "Q336115", "Solon": "Q133337",
    "Tyrtaeus": "Q316094", "Mimnermus": "Q316129", "Callinus": "Q334235", "Semonides": "Q381049",
    "Hipponax": "Q367377", "Xenophanes": "Q131671", "Corinna": "Q241132", "Aeschylus": "Q40939",
    "Sophocles": "Q7235", "Euripides": "Q48305", "Aristophanes": "Q43353", "Callimachus": "Q192417",
    "Theocritus": "Q219484", "Apollonius Rhodius": "Q192638", "Aratus": "Q180671", "Lycophron": "Q432737",
    "Nicander": "Q363818", "Moschus": "Q957548", "Bion": "Q463364", "Oppian": "Q116508",
    "Quintus Smyrnaeus": "Q352702", "Nonnus": "Q312916", "Musaeus": "Q1954009",
    "Agathias Scholasticus": "Q233136", "Phocylides": "Q972799", "Timocreon": "Q3555985",
    "Praxilla": "Q278711", "Pratinas": "Q1362371", "Posidippus": "Q1392801",
    "Dionysius Periegetes": "Q1226993", "Hephaestion": "Q549010", "Telesilla": "Q287216",
    "Timotheus": "Q669691", "Erinna": "Q256241", "Terpander": "Q113417", "Lasus": "Q1128200",
    "Philoxenus": "Q138664", "Ananius": "Q3615044", "Telestes": "Q2364741", "Porphyry": "Q203445",
    "Demodocus": "Q3558606",
}
PROPERTIES = {"P569": "birth", "P570": "death", "P1317": "floruit", "P2031": "work_period_start", "P2032": "work_period_end"}


def fetch() -> bytes:
    """All entities, 50 per request (the API limit), merged into one saved payload."""
    ids = list(ENTITIES.values())
    merged = {"entities": {}}
    for start in range(0, len(ids), 50):
        payload = json.loads(_fetch(ids[start:start + 50]))
        merged["entities"].update(payload["entities"])
    return json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _fetch(ids) -> bytes:
    session = requests.Session()
    session.headers.update({"User-Agent": "MelosCorpus/0.1 (research corpus; https://github.com/PerseusDL)"})
    params = {
        "action": "wbgetentities", "ids": "|".join(ids),
        "format": "json", "props": "labels|aliases|descriptions|claims",
        "languages": "en|el|grc", "languagefallback": "0",
    }
    error = None
    for attempt in range(5):
        try:
            response = session.get(API, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if set(ids) - set(payload.get("entities", {})):
                raise ValueError("Wikidata omitted requested entities")
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Wikidata download failed: {error}")


def time_value(snak: dict) -> dict | None:
    if snak.get("snaktype") != "value":
        return None
    value = snak.get("datavalue", {}).get("value")
    if not isinstance(value, dict) or "time" not in value:
        return None
    result = {key: value.get(key) for key in ("time", "precision", "before", "after", "calendarmodel")}
    year_match = re.match(r"([+-])(\d+)-", value["time"])
    if year_match:
        year = int(year_match[2]) * (1 if year_match[1] == "+" else -1)
        precision = value.get("precision")
        if precision == 9:
            result["year_interval"] = [year, year]
        elif precision == 7 and year < 0:
            century = (abs(year) + 99) // 100
            result["year_interval"] = [-century * 100, -(century - 1) * 100 - 1]
        elif precision == 8 and year < 0:
            decade = (abs(year) + 9) // 10
            result["year_interval"] = [-decade * 10, -(decade - 1) * 10 - 1]
    return result


def snak_summary(snak: dict) -> dict:
    result = {"snaktype": snak.get("snaktype"), "datatype": snak.get("datatype")}
    if snak.get("snaktype") == "value":
        result["value"] = snak.get("datavalue", {}).get("value")
    return result


def snaks_summary(snaks: dict) -> dict:
    return {prop: [snak_summary(s) for s in values] for prop, values in snaks.items()}


def label(entity: dict, lang: str) -> str | None:
    return entity.get("labels", {}).get(lang, {}).get("value")


def reference_type(reference: dict) -> str:
    """Classify Wikidata reference mechanics, never its historical reliability."""
    properties = set(reference["snaks"])
    if "P248" in properties:
        return "stated_in_item"
    if "P854" in properties:
        return "reference_url"
    if "P143" in properties:
        return "imported_project_only"
    if "P268" in properties:
        return "authority_identifier"
    return "other_reference"


REFERENCE_NOTES = {
    "stated_in_item": "Wikidata supplies a 'stated in' item; its scholarship and date claim have not been independently validated here.",
    "reference_url": "Wikidata supplies a reference URL; its date claim has not been independently validated here.",
    "imported_project_only": "The cited reference only identifies a Wikimedia project import, not independent historical evidence for the date.",
    "authority_identifier": "The cited reference is an authority identifier, possibly with retrieval time; it does not itself explain the historical date evidence.",
    "other_reference": "Wikidata supplies reference fields whose evidentiary type is not classified by this collector.",
}


def qualified_interval(time: dict | None, claim: dict) -> list[int] | None:
    """Use explicit earliest/latest qualifiers when present, retaining raw snaks."""
    if not time or "year_interval" not in time:
        return None
    start, end = time["year_interval"]
    for qualifier in claim.get("qualifiers", {}).get("P1319", []):
        qtime = time_value(qualifier)
        if qtime and qtime.get("year_interval"):
            start = qtime["year_interval"][0]
    for qualifier in claim.get("qualifiers", {}).get("P1326", []):
        qtime = time_value(qualifier)
        if qtime and qtime.get("year_interval"):
            end = qtime["year_interval"][1]
    return [start, end] if start <= end else None


def chronology_for_author(claims: list[dict], entity_url: str) -> dict:
    """Select one explicit author-date claim as a transparent sorting proxy."""
    def eligible(kind: str) -> list[dict]:
        return [c for c in claims if c["kind"] == kind and c["rank"] != "deprecated"
                and c["references"] and c.get("effective_year_interval")]

    births, floruits = eligible("birth"), eligible("floruit")
    if births:
        candidates = births
    elif floruits:
        candidates = floruits
    else:
        return {"type": "unknown", "source_url": entity_url,
                "sort_start": None, "sort_end": None, "sort_year": None,
                "source_statement_ids": [], "method": "No referenced birth or floruit claim with a usable year or century interval"}

    def selection_key(claim: dict) -> tuple:
        qualifiers = claim["qualifiers"]
        explicit_bounds = bool(qualifiers.get("P1319") and qualifiers.get("P1326"))
        interval = claim["effective_year_interval"]
        return (not explicit_bounds, claim["rank"] != "preferred",
                interval[1] - interval[0], -len(claim["references"]), claim["statement_id"] or "")

    selected = min(candidates, key=selection_key)
    selected_interval = selected["effective_year_interval"]
    uncertainty = []
    if len({tuple(c["effective_year_interval"]) for c in candidates}) > 1:
        uncertainty.append("competing_non_deprecated_claims")
    if selected["qualifiers"].get("P1319") or selected["qualifiers"].get("P1326"):
        uncertainty.append("explicit_earliest_latest_qualifier")
    if selected["qualifiers"].get("P1480"):
        uncertainty.append("sourcing_circumstances_qualifier")
    if selected["time"]["precision"] < 9:
        uncertainty.append("coarse_wikidata_time_precision")
    reference_types = sorted({reference_type(r) for r in selected["references"]})
    if "imported_project_only" in reference_types:
        uncertainty.append("reference_is_wikimedia_import_only")
    if "authority_identifier" in reference_types:
        uncertainty.append("reference_is_authority_identifier_only")
    return {
        "type": "biographical_claim_envelope",
        "claim_kind": selected["kind"],
        "sort_start": selected_interval[0],
        "sort_end": selected_interval[1],
        "sort_year": sum(selected_interval) / 2,
        "source_url": entity_url,
        "source_statement_ids": [selected["statement_id"]],
        "reference_types": reference_types,
        "reference_notes": [REFERENCE_NOTES[t] for t in reference_types],
        "selected_claim": {
            "statement_id": selected["statement_id"],
            "statement_url": selected["statement_url"],
            "kind": selected["kind"], "rank": selected["rank"],
            "time": selected["time"],
            "effective_year_interval": selected_interval,
            "qualifiers": selected["qualifiers"],
            "references": selected["references"],
            "reference_types": reference_types,
        },
        "uncertainty": uncertainty,
        "alternative_claim_count": len(candidates) - 1,
        "method": "Select a referenced non-deprecated birth claim, otherwise floruit. Explicit earliest/latest qualifiers outrank preferred rank, then preferred rank, narrower interval, reference count, and statement ID. Sort-year is the selected interval midpoint, only an author-period proxy; it is never a poem date.",
    }


def transform(raw_bytes: bytes) -> dict:
    payload = json.loads(raw_bytes)
    result = []
    for site_name, qid in ENTITIES.items():
        entity = payload["entities"][qid]
        claims = []
        for prop, kind in PROPERTIES.items():
            for claim in entity.get("claims", {}).get(prop, []):
                references = []
                for ref in claim.get("references", []):
                    refs = snaks_summary(ref.get("snaks", {}))
                    urls = [v.get("value") for v in refs.get("P854", []) if isinstance(v.get("value"), str)]
                    urls.extend(
                        "https://www.wikidata.org/wiki/" + v["value"]["id"]
                        for v in refs.get("P248", [])
                        if isinstance(v.get("value"), dict) and v["value"].get("id")
                    )
                    reference = {"snaks": refs, "source_urls": urls}
                    reference["reference_type"] = reference_type(reference)
                    references.append(reference)
                qualifiers = snaks_summary(claim.get("qualifiers", {}))
                claims.append({
                    "statement_id": claim.get("id"), "property": prop, "kind": kind,
                    "rank": claim.get("rank"), "snak": snak_summary(claim["mainsnak"]),
                    "time": time_value(claim["mainsnak"]),
                    "effective_year_interval": qualified_interval(time_value(claim["mainsnak"]), claim),
                    "qualifiers": qualifiers, "references": references,
                    "statement_url": f"https://www.wikidata.org/wiki/{qid}#{prop}",
                })
        bounds = [c["effective_year_interval"] for c in claims
                  if c["rank"] != "deprecated" and c["kind"] in ("birth", "death", "floruit")
                  and c["effective_year_interval"]]
        entity_url = f"https://www.wikidata.org/wiki/{qid}"
        result.append({
            "site_author": site_name, "source_author": label(entity, "en"),
            "source_native_label": label(entity, "el") or label(entity, "grc"),
            "source_aliases_en": [a["value"] for a in entity.get("aliases", {}).get("en", [])],
            "entity_id": qid, "entity_url": entity_url,
            "claim_source": API, "claims": claims,
            "biographical_claim_envelope": [min(x[0] for x in bounds), max(x[1] for x in bounds)] if bounds else None,
            "author_chronology": chronology_for_author(claims, entity_url),
            "poem_date": None,
        })
    return {
        "source": "Wikidata wbgetentities", "source_url": API,
        "raw_path": RAW.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Biographical claims can conflict. The envelope is only the broad range of non-deprecated sourced biographical statements, never a composition date. Wikidata time precision and qualifiers remain attached to each claim.",
        "reference_classification": REFERENCE_NOTES,
        "authors": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached", action="store_true", help="Reparse saved raw API response")
    args = parser.parse_args()
    if args.cached:
        raw_bytes = RAW.read_bytes()
    else:
        raw_bytes = fetch()
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_bytes(raw_bytes)
    output = transform(raw_bytes)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(output['authors'])} author records and {sum(len(a['claims']) for a in output['authors'])} chronology claims to {OUTPUT}")


if __name__ == "__main__":
    main()
