"""Reproduce the author gallery from licensed, saved source responses.

Stages: fetch (raw receipts), extract (deterministic staging), write (publish).
Run independent data-extraction audits between stages. No generated biographies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/author-profiles"
RAW = DATA / "raw"
OUT = ROOT / "assets/authors"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
UA = "MelosAuthorProfiles/1.0 (https://greeklyric.com; educational source attribution)"
# Source-selection configuration; extracted author data lives only in responses.
TITLES = {"Alcaeus": "Alcaeus_of_Mytilene"}
EXTRA = ("Homer", "Hesiod", "Theocritus")
DCC = "https://dcc.dickinson.edu/sappho-introduction"
COPYRIGHT = "https://en.wikipedia.org/wiki/Wikipedia:Copyrights"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def old_portraits():
    return read(ROOT / "local-preview/portraits.json")["portraits"]


def fetch_one(session, url, path, **kwargs):
    for attempt in range(5):
        response = session.get(url, timeout=60, **kwargs)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            print(f"RETRY {response.status_code}: {url}", flush=True)
            time.sleep(min(2 ** (attempt + 1), 16))
            continue
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        dump(path.with_suffix(path.suffix + ".receipt.json"), {
            "url": response.url, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": response.status_code, "sha256": digest(response.content),
        })
        return response
    raise RuntimeError(f"Download failed: {url}")


def fetch():
    session = requests.Session()
    session.headers["User-Agent"] = UA
    authors = [p["author"] for p in old_portraits()] + list(EXTRA)
    for author in authors:
        title = TITLES.get(author, author)
        url = SUMMARY + quote(title) + ("?redirect=true" if author == "Theocritus" else "")
        fetch_one(session, url, RAW / f"{author.lower()}.json")
        print(f"Downloaded summary: {author}", flush=True)
        time.sleep(0.5)
    fetch_one(session, COPYRIGHT, RAW / "wikipedia-copyrights.html")
    fetch_one(session, DCC, RAW / "dcc-sappho-introduction.html")
    fetch_one(session, "https://dcc.dickinson.edu/terms-use", RAW / "dcc-terms.html")


def source_receipt(path):
    receipt = read(path.with_suffix(path.suffix + ".receipt.json"))
    assert digest(path.read_bytes()) == receipt["sha256"], path
    return {**receipt, "raw_file": path.relative_to(ROOT).as_posix()}


def excerpt(text, max_words=150):
    # Preserve the exact source prefix; truncate only at a sentence boundary.
    if len(text.split()) <= max_words:
        return text
    ends = list(re.finditer(r"[.!?](?=\s|$)", text))
    allowed = [m.end() for m in ends if len(text[:m.end()].split()) <= max_words]
    if not allowed:
        raise ValueError("No sentence boundary within excerpt length")
    return text[:allowed[-1]]


def extract():
    legacy = old_portraits()
    portraits = {p["author"]: p for p in legacy}
    js = (ROOT / "js/app.js").read_text(encoding="utf-8")
    greek = dict(re.findall(r"en: '([^']+)', gr: '([^']+)'", js))
    copyright_soup = BeautifulSoup((RAW / "wikipedia-copyrights.html").read_bytes(), "html.parser")
    license_link = copyright_soup.find("a", href=re.compile(r"creativecommons.org/licenses/by-sa/4\.0"))
    if not license_link:
        raise ValueError("Wikipedia CC BY-SA 4.0 license link missing")
    wp_license_url = license_link["href"]
    dcc_path = RAW / "dcc-sappho-introduction.html"
    dcc = BeautifulSoup(dcc_path.read_bytes(), "html.parser")
    dcc_terms = BeautifulSoup((RAW / "dcc-terms.html").read_bytes(), "html.parser")
    dcc_license = dcc_terms.find("a", href=re.compile(r"creativecommons.org/licenses"))
    if not dcc_license or "CC BY-SA" not in dcc_terms.get_text():
        raise ValueError("DCC reusable license statement missing")
    dcc_paragraph = next(p.get_text("", strip=False).strip() for p in dcc.find_all("p")
                         if p.get_text().startswith("The Aeolic dialect was spoken"))
    dcc_byline = next(p.get_text(" ", strip=True) for p in dcc.find_all("p")
                     if "Introduction and notes by" in p.get_text())
    records = []
    for author in list(portraits) + list(EXTRA):
        path = RAW / f"{author.lower()}.json"
        payload = read(path)
        if payload.get("type") != "standard" or not payload.get("extract"):
            raise ValueError(f"Missing or ambiguous biography: {author}")
        page_url = payload["content_urls"]["desktop"]["page"]
        record = {
            "author": author, "slug": author.lower(), "greek": greek.get(author, ""),
            "biography": {
                "text": excerpt(payload["extract"]), "source_url": page_url,
                "source_title": payload["title"] + " — Wikipedia",
                "revision_url": "https://en.wikipedia.org/w/index.php?oldid=" + payload["revision"],
                "license": "CC BY-SA 4.0", "license_url": wp_license_url,
                "attribution": "Wikipedia contributors", "extraction": "Exact opening excerpt; sentence-boundary truncation only",
                **source_receipt(path),
            },
            "portrait": None, "reading": [],
        }
        if author in portraits:
            original = portraits["Alcaeus"] if author == "Sappho" else portraits[author]
            source_image = ROOT / "local-preview" / original["image"]
            assert digest(source_image.read_bytes()) == original["sha256"], source_image
            image = "/assets/authors/" + ("sappho-alcaeus" if author in ("Sappho", "Alcaeus") else author.lower()) + source_image.suffix
            record["portrait"] = {
                **original, "author": author, "image": image,
                "source_image": source_image.relative_to(ROOT).as_posix(),
                "raw_metadata": "local-preview/" + original["raw_metadata"],
                "object_position": "21% 40%" if author == "Sappho" else "90% 45%" if author == "Alcaeus" else "50% 35%",
                "focus": {"x": 0.217, "y": 0.388, "width": 0.21, "height": 0.39} if author == "Sappho" else
                         {"x": 0.88, "y": 0.44, "width": 0.21, "height": 0.39} if author == "Alcaeus" else None,
            }
            # Display labels classify explicit source metadata, not new historical claims.
            if "?" in original["description"]:
                record["portrait"]["caption"] = "Attributed portrait · identity uncertain"
            elif "Papyrus" in original["title"]:
                record["portrait"]["caption"] = "Dithyrambs manuscript · not a portrait"
            elif author in ("Sappho", "Alcaeus"):
                record["portrait"]["caption"] = original["title"] + " · later artistic depiction"
        if author in ("Sappho", "Alcaeus"):
            record["reading"].append({
                "text": dcc_paragraph, "title": dcc.title.get_text(" ", strip=True),
                "source_url": DCC, "author": dcc_byline,
                "license": "CC BY-SA", "license_url": "https://dcc.dickinson.edu/terms-use",
                "extraction": "Exact paragraph beginning 'The Aeolic dialect was spoken'",
                **source_receipt(dcc_path),
            })
        records.append(record)
    dump(DATA / "staged.json", {"schema_version": 1, "authors": records})
    print(f"Staged {len(records)} source biographies; {sum(bool(p['portrait']) for p in records)} portraits")


def write():
    catalog = read(DATA / "staged.json")
    assert len({p["author"] for p in catalog["authors"]}) == len(catalog["authors"])
    for profile in catalog["authors"]:
        biography = profile["biography"]
        raw = ROOT / biography["raw_file"]
        assert source_receipt(raw)["sha256"] == biography["sha256"]
        assert read(raw)["extract"].startswith(biography["text"])
        portrait = profile["portrait"]
        if portrait:
            src = ROOT / portrait["source_image"]
            dest = ROOT / portrait["image"].lstrip("/")
            assert digest(src.read_bytes()) == portrait["sha256"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    dump(OUT / "catalog.json", catalog)
    print(f"Published {len(catalog['authors'])} profiles to {OUT / 'catalog.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fetch", "extract", "write"))
    args = parser.parse_args()
    try:
        globals()[args.stage]()
    except Exception as exc:
        print(f"AUTHOR PROFILE EXTRACTION FAILED: {exc}", flush=True)
        raise
