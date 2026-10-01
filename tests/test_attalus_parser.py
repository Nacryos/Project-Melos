"""Narrow parser regression from captured Attalus HTML, not authored corpus text.

Recreate the bounded fixture with ``python tests/test_attalus_parser.py --capture``.
The download is cached outside the corpus in data/raw/attalus_parser_regression;
only three source sections are retained here. Tests run offline. This does not
run the collector, create passage records, or authorize corpus admission.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ingest_p2_attalus_anthology import decode, fetch, parse_page  # noqa: E402

URL = "https://www.attalus.org/poetry/meleager.html"
REFERENCES = ("5.179", "5.182", "5.184")
FIXTURE = Path(__file__).parent / "fixtures" / "attalus_meleager_excerpt.html"
MANIFEST = FIXTURE.with_suffix(".json")


def section(source: str, reference: str) -> str:
    marker = re.search(r'<A CLASS="ref" NAME="' + re.escape(reference) + r'">', source)
    assert marker, reference
    following = re.search(r'<A CLASS="ref" NAME="', source[marker.end():])
    end = marker.end() + following.start() if following else len(source)
    return source[marker.start():end]


def fixture_source() -> str:
    raw = FIXTURE.read_bytes()
    # Git may check text fixtures out as CRLF on Windows. Verify the recorded
    # LF-normalized excerpt, while the manifest separately fingerprints raw HTTP bytes.
    source = raw.decode("utf-8").replace("\r\n", "\n")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == manifest["fixture_sha256"]
    assert manifest["source_url"] == URL
    return source


def visible(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def test_g_initial_translation_is_preserved_in_full():
    source = fixture_source()
    raw_body = re.split(r"<P>", section(source, "5.182"), flags=re.I)[1:]
    expected = "\n".join(filter(None, (visible(part) for part in raw_body)))
    assert expected.startswith("Give her this message, Dorcas")
    rows = {row["reference"]: row for row in parse_page(source)["epigrams"]}
    assert rows["5.182"]["text"] == expected


def test_header_navigation_and_translator_notes_stay_separate():
    source = fixture_source()
    rows = {row["reference"]: row for row in parse_page(source)["epigrams"]}
    assert set(rows) == set(REFERENCES)
    for row in rows.values():
        assert row["perseus_url"].startswith("http://www.perseus.tufts.edu/")
        assert all(paragraph != "G" for paragraph in row["text"].splitlines())
    greens = [visible(value) for value in re.findall(
        r'<FONT CLASS="green">(.*?)</FONT>', section(source, "5.179"), re.I | re.S)]
    assert rows["5.179"]["notes"]
    assert all(note in greens and note not in rows["5.179"]["text"]
               for note in rows["5.179"]["notes"])


def test_non_g_translation_is_unchanged():
    source = fixture_source()
    raw_body = re.split(r"<P>", section(source, "5.184"), flags=re.I)[1:]
    expected = list(filter(None, (visible(part) for part in raw_body)))
    assert expected
    row = next(row for row in parse_page(source)["epigrams"] if row["reference"] == "5.184")
    assert row["text"].splitlines() == expected


def capture() -> None:
    """Actual HTTP download and deterministic source slicing; no text supplied."""
    raw_path = ROOT / "data/raw/attalus_parser_regression/meleager.html"
    raw = fetch(URL, raw_path, refresh=True, delay=0)
    source = decode(raw)
    title = re.search(r"<TITLE>.*?</TITLE>", source, re.I | re.S)
    assert title
    excerpt = title.group(0) + "\n" + "".join(section(source, ref) for ref in REFERENCES)
    encoded = excerpt.replace("\r\n", "\n").encode("utf-8")
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(encoded)
    manifest = {
        "source_url": URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_path": raw_path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "fixture_sha256": hashlib.sha256(encoded).hexdigest(),
        "references": list(REFERENCES),
        "transform": "Declared-encoding decode; literal title and three reference sections; CRLF to LF; UTF-8 encode.",
        "terms_url": "https://www.attalus.org/info/comments.html",
        "scope": "Non-commercial parser regression only; no corpus admission.",
        "regenerate": "python tests/test_attalus_parser.py --capture",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] != ["--capture"]:
        raise SystemExit("Use --capture to download the source fixture, or run with pytest.")
    capture()
