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
# Release P: anonymous collections are dated only by a referenced claim on the work's own item
# (inception); the label is the site author label used for the collection.
WORK_ENTITIES = {"Homeric Hymns": "Q329342", "Orphica": "Q1313790", "Anacreontea": "Q145973"}
# Release P: poets named as the author of an epigram in the Greek Anthology records
# (metadata.attributed_author, Perseus tlg7000), by token share. Each was selected with
# wbsearchentities (2026-10-09) on the poet's usual English name; a Perseus label is mapped only
# when the hit is described as an ancient poet, epigrammatist or the known author of the epigrams,
# and the label does not also name another ancient epigrammatist. Ambiguous labels stay undated:
# Antipater (Sidon / Thessalonica), Philippus, Leonidas (Tarentum / Alexandria), Archias, Diodorus,
# Alcaeus (Messene / Mytilene), Julianus (the prefect / the emperor), Asclepiades, Erycius,
# Theaetetus, Gaetulicus, Plato, Cometas; and labels without a matching item (Straton, Dioscorides,
# Rufinus, Nicarchus, Apollonides, Bianor, Ammianus, Automedon ...). The date is the attributed
# poet's, never the epigram's; "Anonymi Epigrammatici" stays undated.
ATTRIBUTED = {
    "Gregorius Nazianzenus": "Q44011", "Agathias Scholasticus": "Q233136", "Meleager": "Q441460",
    "Palladas": "Q939680", "Lucillius": "Q654760", "Paulus Silentiarius": "Q518544", "Antiphilus": "Q3558592",
    "Crinagoras": "Q2908699", "Macedonius II": "Q1453173", "Philodemus": "Q451550",
    "Marcus Argentarius": "Q1165512", "Diogenes Laertius": "Q59138", "Anyte": "Q241120", "Nossis": "Q559151",
    "Leontius Minotaurus": "Q11931346", "Simias": "Q770394", "Julius Leonidas": "Q16332896",
    "Theodoridas": "Q3526540", "Mnasalces": "Q19053390", "Alpheus": "Q2840067", "Damagetus": "Q12875833",
    "Leo Philosophus": "Q681601", "Diodorus Zonas": "Q11917225", "Rhianus": "Q2319055",
    "Tullius Geminus": "Q11953382", "Marianus": "Q98083959", "Lollius Bassus": "Q6668972",
    "Statyllius Flaccus": "Q1300185", "Quintus Maecius": "Q1243832", "Pseudo-lucianus": "Q19558843",
    # Epigrams the records attribute to poets already catalogued above (same items).
    "Callimachus": "Q192417", "Theocritus": "Q219484", "Posidippus": "Q1392801", "Anacreon": "Q213484",
    "Moschus": "Q957548", "Simonides": "Q273003",
}
PROPERTIES = {"P569": "birth", "P570": "death", "P1317": "floruit", "P2031": "work_period_start", "P2032": "work_period_end",
              "P571": "inception"}


def fetch() -> bytes:
    """All entities, 50 per request (the API limit), merged into one saved payload."""
    ids = list(dict.fromkeys([*ENTITIES.values(), *WORK_ENTITIES.values(), *ATTRIBUTED.values()]))
    merged = {"entities": {}}
    for start in range(0, len(ids), 50):
        payload = json.loads(_fetch(ids[start:start + 50]))
        merged["entities"].update(payload["entities"])
    # Labels of the genre items named by P136 claims (for the sourced genre labels).
    genres = sorted({snak["mainsnak"]["datavalue"]["value"]["id"] for e in merged["entities"].values()
                     for snak in e.get("claims", {}).get("P136", [])
                     if snak.get("mainsnak", {}).get("snaktype") == "value"})
    merged["genre_items"] = {}
    for start in range(0, len(genres), 50):
        payload = json.loads(_fetch(genres[start:start + 50], props="labels"))
        merged["genre_items"].update(payload["entities"])
    return json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _fetch(ids, props="labels|aliases|descriptions|claims") -> bytes:
    session = requests.Session()
    session.headers.update({"User-Agent": "MelosCorpus/0.1 (research corpus; https://github.com/PerseusDL)"})
    params = {
        "action": "wbgetentities", "ids": "|".join(ids),
        "format": "json", "props": props,
        "languages": "en|el|grc", "languagefallback": "0",
    }
    error = None
    for attempt in range(8):
        try:
            response = session.get(API, params=params, timeout=45)
            if response.status_code == 429:  # Wikimedia rate limit: back off, do not hammer
                time.sleep(int(response.headers.get("Retry-After") or 0) or 30 * (attempt + 1))
                error = RuntimeError("HTTP 429")
                continue
            response.raise_for_status()
            payload = response.json()
            if set(ids) - set(payload.get("entities", {})):
                raise ValueError("Wikidata omitted requested entities")
            return response.content
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 7:
                time.sleep(3 * (attempt + 1))
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
        # Release P: CE centuries and decades (release O read only BCE ones, so every
        # late-antique author with a century claim, e.g. Nonnus "5th century", was undated).
        # Wikidata displays +0500 and +0450 at century precision as "5th century" (401-500).
        elif precision == 7 and year > 0:
            century = (year + 99) // 100
            result["year_interval"] = [(century - 1) * 100 + 1, century * 100]
        elif precision == 8 and year > 0:
            result["year_interval"] = [year // 10 * 10, year // 10 * 10 + 9]
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

    # Release P: after birth and floruit, a referenced work-period, death or (for an anonymous
    # collection's work item) inception claim; the kind is kept on the claim.
    candidates = next((found for kind in ("birth", "floruit", "work_period_start", "death", "inception")
                       for found in [eligible(kind)] if found), [])
    if not candidates:
        return {"type": "unknown", "source_url": entity_url,
                "sort_start": None, "sort_end": None, "sort_year": None,
                "source_statement_ids": [], "method": "No referenced birth, floruit, work-period, death or inception claim with a usable year, decade or century interval"}

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
        "method": "Select a referenced non-deprecated birth claim, otherwise floruit, work-period start, death, inception (in that order). Explicit earliest/latest qualifiers outrank preferred rank, then preferred rank, narrower interval, reference count, and statement ID. Sort-year is the selected interval midpoint, only an author-period proxy; it is never a poem date.",
    }


def transform(raw_bytes: bytes) -> dict:
    payload = json.loads(raw_bytes)
    result = []
    genre_items = payload.get("genre_items", {})
    selections = ([(name, qid, "author") for name, qid in ENTITIES.items()]
                  + [(name, qid, "work") for name, qid in WORK_ENTITIES.items()]
                  + [(name, qid, "attributed_author") for name, qid in ATTRIBUTED.items()])
    for site_name, qid, scope in selections:
        if qid not in payload["entities"]:
            continue
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
        genre_claims = []
        for claim in entity.get("claims", {}).get("P136", []):
            snak = claim.get("mainsnak", {})
            if snak.get("snaktype") != "value" or claim.get("rank") == "deprecated":
                continue
            value = snak["datavalue"]["value"]["id"]
            genre_claims.append({"statement_id": claim.get("id"), "value": value,
                                 "label": label(genre_items.get(value, {}), "en"), "rank": claim.get("rank"),
                                 "referenced": bool(claim.get("references")),
                                 "statement_url": f"https://www.wikidata.org/wiki/{qid}#P136"})
        result.append({
            "site_author": site_name, "scope": scope, "source_author": label(entity, "en"),
            "source_description": entity.get("descriptions", {}).get("en", {}).get("value"),
            "source_native_label": label(entity, "el") or label(entity, "grc"),
            "source_aliases_en": [a["value"] for a in entity.get("aliases", {}).get("en", [])],
            "entity_id": qid, "entity_url": entity_url,
            "claim_source": API, "claims": claims,
            "biographical_claim_envelope": [min(x[0] for x in bounds), max(x[1] for x in bounds)] if bounds else None,
            "author_chronology": chronology_for_author(claims, entity_url),
            "genre_claims": genre_claims,
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


ATTRIBUTIONS = ROOT / "data/metadata/attributions.json"
# CTS textgroups whose records are filed under a generic author label ("Anonymous") but belong to
# a dated collection item above. tlg0013 is the Homeric Hymns textgroup in the Perseus
# canonical-greekLit catalogue (data/tlg0013/__cts__.xml, groupname "Homeric Hymns").
TEXTGROUP_COLLECTIONS = {"tlg0013": "Homeric Hymns"}


def build_attributions(corpus: str) -> dict:
    """Passage id -> the poet its record names (metadata.attributed_author) or its collection.

    Used only to date a passage whose own author label has no claim (Greek Anthology epigrams,
    anonymous hymns); author labels, filters and counts are unchanged."""
    import sqlite3
    con = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    passages, by_kind = {}, {"attributed_author": 0, "textgroup_collection": 0}
    for pid, data in con.execute("SELECT id, data FROM passages WHERE language IN ('grc','mul')"):
        metadata = (json.loads(data or "{}").get("metadata") or {})
        named = metadata.get("attributed_author")
        if isinstance(named, str) and named.strip():
            passages[pid] = named.strip()
            by_kind["attributed_author"] += 1
            continue
        match = re.search(r"\b(tlg\d{4})\.tlg\d{3}", pid + " " + str(metadata.get("cts_urn") or ""))
        if match and match[1] in TEXTGROUP_COLLECTIONS:
            passages[pid] = "collection:" + TEXTGROUP_COLLECTIONS[match[1]]
            by_kind["textgroup_collection"] += 1
    return {"version": 1, "corpus": corpus, "counts": by_kind,
            "basis": {"attributed_author": "record metadata attributed_author (Perseus Greek Anthology TEI <head> attribution)",
                      "textgroup_collection": "CTS textgroup of the record id / cts_urn: " + json.dumps(TEXTGROUP_COLLECTIONS)},
            "passages": passages}


GENRE_SOURCES = ROOT / "data/metadata/genre_sources.json"
# Source editions whose own collection or work labels name a genre (release P). The label is
# stored verbatim with its record count; backend/author_catalogue.py maps it to a genre name.
GENRE_LABEL_SOURCES = {
    "p2_cgl_anthology": "Ανθολογία Αρχαϊκής Λυρικής Ποίησης (Centre for the Greek Language): section heading",
    "lyric_web": "Greek Wikisource collection page title",
    "p2_elegy": "Greek Wikisource work title",
}


def build_genre_sources(corpus: str) -> dict:
    """Per canonical author, the genre-bearing collection/work labels of its source editions."""
    import sqlite3
    import sys
    sys.path.insert(0, str(ROOT))
    from backend.author_aliases import canonical
    con = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    authors: dict = {}
    sql = (f"SELECT source, author, work FROM passages WHERE kind='text' AND language IN ('grc','mul') "
           f"AND source IN ({','.join('?' * len(GENRE_LABEL_SOURCES))})")
    for source, author, work in con.execute(sql, list(GENRE_LABEL_SOURCES)):
        name = canonical(author or "") or author
        label = str(work or "").strip()
        if not label:
            continue
        row = authors.setdefault(name, {})
        row.setdefault(label, {"count": 0, "source": source, "source_description": GENRE_LABEL_SOURCES[source]})
        row[label]["count"] += 1
    return {"version": 1, "corpus": corpus, "sources": GENRE_LABEL_SOURCES, "authors": authors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached", action="store_true", help="Reparse saved raw API response")
    parser.add_argument("--attributions", metavar="CORPUS", help="Also write data/metadata/attributions.json from this corpus")
    args = parser.parse_args()
    if args.attributions:
        ATTRIBUTIONS.parent.mkdir(parents=True, exist_ok=True)
        data = build_attributions(args.attributions)
        ATTRIBUTIONS.write_text(json.dumps(data, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        print("attributions", data["counts"])
        genres = build_genre_sources(args.attributions)
        GENRE_SOURCES.write_text(json.dumps(genres, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("genre sources", len(genres["authors"]), "authors")
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
