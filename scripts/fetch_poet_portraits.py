"""Reproducible Commons assets for the LOCAL poet-timeline experiment.

Run `python scripts/fetch_poet_portraits.py fetch`, audit raw/extracted records,
then `python scripts/fetch_poet_portraits.py write` to publish the local manifest.
No image transformations: Commons' own thumbnail is downloaded byte-for-byte.
Candidate filenames are discovery configuration, not authored source metadata.
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
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "local-preview"
RAW = OUT / "raw" / "portraits"
ASSETS = OUT / "assets" / "portraits"
API = "https://commons.wikimedia.org/w/api.php"
UA = "Melos/1.0 (https://greeklyric.com; educational research)"
# Discovered on Wikipedia author pages and Commons Nine lyric poets.jpg credits.
SOURCES = {
    "Archilochus": "Archilochus 01 pushkin.jpg",
    "Alcman": "Mosaic Portrait of the Poet Alcman (cropped).jpg",
    "Sappho": "Malarz Safony - Kalpis wykonana techniką Six.jpg",
    "Alcaeus": "Sir Lawrence Alma-Tadema, RA, OM - Sappho and Alcaeus - Walters 37159.jpg",
    "Stesichorus": "Stesichorus.jpg",
    "Ibycus": "Reggio calabria monumento ibico.jpg",
    "Anacreon": "Anacreon Louvre.jpg",
    "Simonides": "Nuremberg chronicles f 60r 3.png",
    "Pindar": "Bust of Pindar.jpg",
    "Bacchylides": "Bacchylides, Dithyrambs, Papyrus 733.jpg",
}


def get(session, url, **kwargs):
    for attempt in range(4):
        response = session.get(url, timeout=50, **kwargs)
        if response.status_code in (429, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** (attempt + 1))
            continue
        response.raise_for_status()
        return response
    raise RuntimeError(f"Download failed: {url}")


def plain(value):
    # HTML -> visible plain text, using the source markup (no paraphrasing).
    if "<" not in (value or ""):
        return value or ""
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA
    response = get(session, API, params={
        "action": "query", "format": "json", "redirects": 1,
        "prop": "imageinfo", "iiprop": "url|extmetadata|sha1|mime|size",
        "iiurlwidth": 640, "titles": "|".join("File:" + f for f in SOURCES.values()),
    })
    (RAW / "commons-imageinfo.json").write_bytes(response.content)
    (RAW / "receipt.json").write_text(json.dumps({
        "url": response.url, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": response.status_code,
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = json.loads((RAW / "commons-imageinfo.json").read_text(encoding="utf-8"))
    if "error" in payload:
        raise RuntimeError(payload["error"])
    pages = {p["title"].replace("_", " "): p for p in payload["query"]["pages"].values()}
    redirects = {r["from"]: r["to"] for r in payload["query"].get("redirects", [])}
    records = []
    for author, filename in SOURCES.items():
        title = "File:" + filename
        page = pages[redirects.get(title, title).replace("_", " ")]
        info = page["imageinfo"][0]
        meta = info["extmetadata"]
        value = lambda key: plain(meta.get(key, {}).get("value", ""))
        license_name = value("LicenseShortName")
        if not license_name or not (license_name.startswith("CC") or "public domain" in license_name.lower()):
            raise RuntimeError(f"No approved reusable license for {author}: {license_name!r}")
        url = info.get("thumburl", info["url"])
        image_response = get(session, url)
        suffix = ".png" if "png" in image_response.headers.get("Content-Type", "") else ".jpg"
        destination = ASSETS / (author.lower() + suffix)
        destination.write_bytes(image_response.content)
        record = {
            "author": author,
            "image": destination.relative_to(OUT).as_posix(),
            "source_url": info["descriptionurl"],
            "title": value("ObjectName") or page["title"],
            "description": value("ImageDescription"),
            "source_categories": value("Categories").split("|"),
            "artist": value("Artist"),
            "license": license_name,
            "license_url": value("LicenseUrl"),
            "credit": value("Credit"),
            "download_url": url,
            "sha256": hashlib.sha256(image_response.content).hexdigest(),
            "source_file": page["title"],
            "raw_metadata": "raw/portraits/commons-imageinfo.json",
            "image_transform": "None; downloaded Commons thumbnail bytes unchanged",
        }
        records.append(record)
        print(f"Downloaded {author}: {license_name}, {len(image_response.content):,} bytes")
        time.sleep(0.35)
    (RAW / "extracted.json").write_text(json.dumps({"portraits": records}, ensure_ascii=False, indent=2), encoding="utf-8")


def write():
    data = json.loads((RAW / "extracted.json").read_text(encoding="utf-8"))
    authors = re.findall(r"en: '([^']+)'", (ROOT / "js" / "app.js").read_text(encoding="utf-8").split("const POETS = [", 1)[1].split("];", 1)[0])
    assert len({p["author"] for p in data["portraits"]}) == len(data["portraits"])
    for record in data["portraits"]:
        assert record["author"] in authors
        path = OUT / record["image"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    (OUT / "portraits.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(data['portraits'])} audited-source image records to local-preview/portraits.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("fetch", "write"))
    args = parser.parse_args()
    try:
        globals()[args.stage]()
    except Exception as exc:
        print(f"PORTRAIT EXTRACTION FAILED: {exc}")
        raise
