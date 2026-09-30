"""Download Perseus LSJ, Autenrieth, and Greek treebank XML, then extract JSONL.

Requires: lxml, betacode. Run: python scripts/ingest_lexica.py

LSJ headword conversion uses the open-source ``betacode`` Python package,
following the Perseus Beta Code convention documented at
https://www.perseus.tufts.edu/hopper/help/greek.
No glosses or morphological analyses are authored by this program.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from betacode import beta_to_uni
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "lexica"
OUT = ROOT / "data" / "lexica"
REPORTS = ROOT / "data" / "reports"
API = "https://api.github.com/repos/{repo}"
REPOS = {
    "lsj": "PerseusDL/lexica",
    "autenrieth": "gregorycrane/Homerica",
    "treebank": "PerseusDL/treebank_data",
}
NOTICE_PATHS = {
    "lsj": ["README.md", "license.md", "CTS_XML_TEI/perseus/pdllex/grc/lsj/README.md"],
    "autenrieth": ["README.md", "LICENSE", "LICENSE.md"],
    "treebank": ["README.md", "v1.6/README.md"],
}
USER_AGENT = "melos-source-ingestion/1.0 (research corpus)"
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
HOMOGRAPH_NUMBER = re.compile(r"\d+$")
SPACE = re.compile(r"\s+")


def request_bytes(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def get_json(url: str) -> dict:
    return json.loads(request_bytes(url))


def repo_snapshot(repo: str) -> tuple[str, list[dict]]:
    info = get_json(API.format(repo=repo))
    branch = info["default_branch"]
    commit = get_json(API.format(repo=repo) + f"/commits/{branch}")["sha"]
    tree = get_json(API.format(repo=repo) + f"/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError(f"Truncated GitHub tree: {repo}@{commit}")
    return commit, tree["tree"]


def selected_files(group: str, tree: list[dict]) -> list[dict]:
    if group == "lsj":
        prefix = "CTS_XML_TEI/perseus/pdllex/grc/lsj/"
        suffix = ".xml"
    elif group == "autenrieth":
        prefix = ""
        suffix = "autenrieth.xml"
    else:
        prefix = "v1.6/greek/data/"
        suffix = ".tb.xml"
    return sorted(
        [node for node in tree if node["type"] == "blob"
         and node["path"].startswith(prefix) and node["path"].endswith(suffix)
         and (group != "autenrieth" or node["path"] == "autenrieth.xml")],
        key=lambda node: node["path"],
    )


def raw_url(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(path, safe='/')}"


def download_file(group: str, repo: str, commit: str, node: dict) -> dict:
    relative = Path("data") / "raw" / "lexica" / group / node["path"]
    target = ROOT / relative
    url = raw_url(repo, commit, node["path"])
    # A matching raw file is an already downloaded, hash-verified cache.
    if target.exists() and target.stat().st_size == node.get("size"):
        body = target.read_bytes()
    else:
        body = request_bytes(url)
        if len(body) != node.get("size"):
            raise RuntimeError(f"Byte size mismatch: {url}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    blob_sha = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    if blob_sha != node["sha"]:
        raise RuntimeError(f"Git blob checksum mismatch: {target}")
    return {
        "path": node["path"], "raw_path": relative.as_posix(),
        "source_url": url, "raw_sha256": hashlib.sha256(body).hexdigest(),
        "git_blob_sha": blob_sha, "bytes": len(body),
    }


def compact(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def plain_text(element: etree._Element) -> str:
    return compact("".join(element.itertext()))


def header_metadata(raw_file: dict, *, recover: bool = False) -> dict:
    context = etree.iterparse(str(ROOT / raw_file["raw_path"]), events=("end",),
                              tag="fileDesc", load_dtd=False, no_network=True,
                              resolve_entities=False, huge_tree=True, recover=recover)
    try:
        header = next(context)[1]
    except StopIteration:
        return {}
    field_names = ("title", "author", "publisher", "pubPlace", "date", "sourceDesc")
    return {name: [plain_text(element) for element in header.iter(name)
                   if plain_text(element)] for name in field_names}


def parse_lsj(raw_file: dict, output: io.TextIOBase, counters: dict) -> None:
    file_number = re.search(r"perseus-eng(\d+)\.xml$", raw_file["path"])
    if file_number is None:
        raise ValueError(raw_file["path"])
    path = ROOT / raw_file["raw_path"]
    # The original TEI P4 references remote DTDs. Its entry content is parsed
    # without fetching those DTDs or expanding external entities.
    context = etree.iterparse(str(path), events=("end",), tag="entryFree",
                              load_dtd=False, no_network=True, resolve_entities=False,
                              huge_tree=True, recover=False)
    for _, entry in context:
        counters["lsj_entries_seen"] += 1
        key = entry.get("key")
        entry_id = entry.get("id")
        translations = []
        seen = set()
        for tr in entry.iter("tr"):
            value = plain_text(tr)
            if value and value not in seen:
                translations.append(value)
                seen.add(value)
            if len(translations) >= 4:
                break
        if key and entry_id:
            key_without_number = HOMOGRAPH_NUMBER.sub("", key)
            lemma = compact(beta_to_uni(key_without_number))
            if GREEK.search(lemma):
                # The complete diplomatic plain-text entry is retained for an
                # expandable traditional dictionary view. Greek in this field
                # remains in the source's Beta Code; lemma is converted above.
                entry_text = plain_text(entry)
                record = {
                    "id": f"lsj:{file_number.group(1)}:{entry_id}",
                    "lemma": lemma,
                    "lemma_beta": key,
                    "gloss": "; ".join(translations),
                    "entry_text": entry_text,
                    "entry_text_encoding": "Perseus Beta Code for Greek spans",
                    "source": "PerseusDL LSJ TEI",
                    "source_url": raw_file["source_url"],
                    "entry_url": "https://www.perseus.tufts.edu/hopper/text?doc="
                    + quote(f"Perseus:text:1999.04.0057:entry={key}", safe=""),
                    "raw_path": raw_file["raw_path"],
                    "raw_sha256": raw_file["raw_sha256"],
                    "license": "CC-BY-SA-4.0",
                    "entry_id": entry_id,
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                counters["lsj_entries_written"] += 1
                if not translations:
                    counters["lsj_entries_without_marked_translation"] += 1
            else:
                counters["lsj_non_greek_headword"] += 1
        else:
            counters["lsj_missing_key_or_id"] += 1
        entry.clear()
        while entry.getprevious() is not None:
            del entry.getparent()[0]


def parse_treebank(raw_file: dict, output: io.TextIOBase, counters: dict,
                   license_name: str) -> None:
    path = ROOT / raw_file["raw_path"]
    context = etree.iterparse(str(path), events=("end",), tag="sentence",
                              load_dtd=False, no_network=True, resolve_entities=False,
                              huge_tree=True, recover=False)
    for _, sentence in context:
        document_id = sentence.get("document_id", "")
        sentence_id = sentence.get("id", "")
        for word in sentence.iter("word"):
            counters["treebank_tokens_seen"] += 1
            form = word.get("form", "")
            lemma_raw = word.get("lemma", "")
            analysis = word.get("postag", "")
            if not GREEK.search(form):
                counters["treebank_tokens_skipped"] += 1
                counters["treebank_non_greek_tokens"] += 1
                continue
            if not GREEK.search(lemma_raw) or not analysis:
                counters["treebank_tokens_skipped"] += 1
                counters["treebank_missing_lemma_or_analysis"] += 1
                continue
            record = {
                "form": form,
                "lemma": HOMOGRAPH_NUMBER.sub("", lemma_raw),
                "lemma_raw": lemma_raw,
                "analysis": analysis,
                "analysis_format": "Perseus treebank 1.6 postag",
                "source": "PerseusDL Greek Dependency Treebank v1.6",
                "source_url": raw_file["source_url"],
                "raw_path": raw_file["raw_path"],
                "raw_sha256": raw_file["raw_sha256"],
                "license": license_name,
                "citation": word.get("cite", ""),
                "document_id": document_id,
                "sentence_id": sentence_id,
                "token_id": word.get("id", ""),
                "quality": "annotated_treebank_token",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            counters["treebank_tokens_written"] += 1
        sentence.clear()
        while sentence.getprevious() is not None:
            del sentence.getparent()[0]


def parse_autenrieth(raw_file: dict, output: io.TextIOBase, counters: dict,
                     skipped: list[dict]) -> None:
    path = ROOT / raw_file["raw_path"]
    # This older TEI contains named external entities not defined in the raw
    # file. Keep their literal references in entry_text; never fetch the DTD.
    context = etree.iterparse(str(path), events=("end",), tag="entryFree",
                              load_dtd=False, no_network=True, resolve_entities=False,
                              huge_tree=True, recover=True)
    for _, entry in context:
        counters["autenrieth_entries_seen"] += 1
        entry_id = entry.get("id")
        key = entry.get("key", "")
        orth = next(entry.iter("orth"), None)
        orth_beta = plain_text(orth) if orth is not None else ""
        first_orth = orth_beta.split(",", 1)[0].replace("-", "")
        first_orth = re.sub(r"[\s_^]", "", first_orth)
        candidates = [first_orth, HOMOGRAPH_NUMBER.sub("", key)]
        lemma = ""
        lemma_beta = ""
        for candidate in candidates:
            converted = compact(beta_to_uni(candidate))
            if converted and all(GREEK.fullmatch(char) or
                                 ("\u0300" <= char <= "\u036f") for char in converted):
                lemma, lemma_beta = converted, candidate
                break
        if entry_id and lemma:
            glosses = []
            seen = set()
            for gloss in entry.iter("gloss"):
                value = plain_text(gloss)
                if value and value not in seen:
                    glosses.append(value)
                    seen.add(value)
                if len(glosses) >= 4:
                    break
            record = {
                "id": f"autenrieth:{entry_id}",
                "lemma": lemma,
                "lemma_beta": lemma_beta,
                "gloss": "; ".join(glosses),
                "entry_text": plain_text(entry),
                "entry_text_encoding": "Perseus Beta Code for Greek spans",
                "source": "Perseus Autenrieth TEI via Homerica",
                "source_url": raw_file["source_url"],
                "entry_url": "https://www.perseus.tufts.edu/hopper/text?doc="
                + quote(f"Perseus:text:1999.04.0073:entry={key}", safe=""),
                "raw_path": raw_file["raw_path"],
                "raw_sha256": raw_file["raw_sha256"],
                "license": "unknown",
                "edition_year": 1891,
                "entry_id": entry_id,
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            counters["autenrieth_entries_written"] += 1
            if not glosses:
                counters["autenrieth_entries_without_marked_gloss"] += 1
        else:
            counters["autenrieth_entries_skipped"] += 1
            skipped.append({"entry_id": entry_id, "key": key, "orth": orth_beta})
        entry.clear()
        while entry.getprevious() is not None:
            del entry.getparent()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "lsj", "autenrieth", "treebank"), default="all")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--treebank-license", default="unknown",
                        help="Use only a verified, source-specific license label")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    groups = ["lsj", "autenrieth", "treebank"] if args.group == "all" else [args.group]
    snapshots = {}
    downloaded = {}
    notices = {}
    for group in groups:
        repo = REPOS[group]
        commit, tree = repo_snapshot(repo)
        nodes = selected_files(group, tree)
        if not nodes:
            raise RuntimeError(f"No source files found: {repo}@{commit}")
        snapshots[group] = {"repository": repo, "commit": commit, "files": len(nodes)}
        files = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(download_file, group, repo, commit, node) for node in nodes]
            for future in as_completed(futures):
                files.append(future.result())
        downloaded[group] = sorted(files, key=lambda item: item["path"])
        notice_nodes = [node for node in tree if node["type"] == "blob"
                        and node["path"] in NOTICE_PATHS[group]]
        notices[group] = []
        for node in notice_nodes:
            notice_file = download_file(group, repo, commit, node)
            notice_file["text"] = (ROOT / notice_file["raw_path"]).read_text(encoding="utf-8")
            notices[group].append(notice_file)
    counters = {
        "lsj_entries_seen": 0, "lsj_entries_written": 0,
        "lsj_missing_key_or_id": 0, "lsj_entries_without_marked_translation": 0,
        "lsj_non_greek_headword": 0,
        "autenrieth_entries_seen": 0, "autenrieth_entries_written": 0,
        "autenrieth_entries_skipped": 0,
        "autenrieth_entries_without_marked_gloss": 0,
        "treebank_tokens_seen": 0, "treebank_tokens_written": 0,
        "treebank_tokens_skipped": 0, "treebank_non_greek_tokens": 0,
        "treebank_missing_lemma_or_analysis": 0,
    }
    skipped_autenrieth = []
    if "lsj" in groups or "autenrieth" in groups:
        with (OUT / "entries.jsonl").open("w", encoding="utf-8", newline="\n") as output:
            for raw_file in downloaded.get("lsj", []):
                parse_lsj(raw_file, output, counters)
            for raw_file in downloaded.get("autenrieth", []):
                parse_autenrieth(raw_file, output, counters, skipped_autenrieth)
    if "treebank" in groups:
        with (OUT / "forms.jsonl").open("w", encoding="utf-8", newline="\n") as output:
            for raw_file in downloaded["treebank"]:
                parse_treebank(raw_file, output, counters, args.treebank_license)
    bibliographies = {
        group: header_metadata(downloaded[group][0], recover=(group == "autenrieth"))
        for group in ("lsj", "autenrieth") if group in downloaded
    }
    report = {"accessed_at_utc": datetime.now(timezone.utc).isoformat(),
              "snapshots": snapshots, "counts": counters,
              "skipped_autenrieth_entries": skipped_autenrieth,
              "bibliographies": bibliographies, "license_notices": notices,
              "raw_files": {group: downloaded[group] for group in groups}}
    report_name = "lexica_ingest.json" if args.group == "all" else f"lexica_{args.group}_ingest.json"
    (REPORTS / report_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshots": snapshots, "counts": counters}, indent=2))


if __name__ == "__main__":
    main()
