"""Display renderer for source TEI lexicon entries.

Audited JSONL and raw TEI remain untouched. Only explicit Greek TEI spans are
converted from Perseus Beta Code; English and Latin prose is copied verbatim.
"""

from __future__ import annotations

from functools import lru_cache
from html import unescape
from html.entities import html5 as HTML5_ENTITIES
import mmap
from pathlib import Path
import re
from typing import Any

from betacode import beta_to_uni
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = (ROOT / "data/raw/lexica").resolve()
SPACE = re.compile(r"\s+")
GREEK_LANGS = {"greek", "grc", "el", "ancient greek"}
# Standard-library copy of the HTML named character reference table:
# https://html.spec.whatwg.org/multipage/named-characters.html . Only explicit
# semicolon-terminated names are resolved; source-specific names stay visible.
METHOD = "Greek TEI spans rendered from Perseus Beta Code; source text retained"
ENTRY_START = re.compile(rb'<entryFree\b[^>]*\bid="([^"]+)"[^>]*>')
ENTRY_END = b"</entryFree>"
NAMED_ENTITY = re.compile(rb"&(#x[0-9A-Fa-f]+|#[0-9]+|[A-Za-z][A-Za-z0-9_.:-]*);")
ENTITY_MARKER = re.compile(r"[\ue000-\uf8ff]")


def _source_path(raw_path: str | Path) -> Path:
    candidate = (ROOT / raw_path).resolve()
    if not candidate.is_relative_to(RAW_ROOT) or candidate.suffix.lower() != ".xml":
        raise ValueError(f"Lexicon source path outside local XML archive: {raw_path}")
    return candidate


def _render_text(value: str, greek: bool, entities: dict[str, str]) -> str:
    """Keep decoded source entities outside the Beta Code conversion span."""
    result: list[str] = []
    previous = 0
    for marker in ENTITY_MARKER.finditer(value):
        if marker.group() not in entities:
            continue
        chunk = value[previous:marker.start()]
        result.append(beta_to_uni(chunk) if greek else chunk)
        result.append(entities[marker.group()])
        previous = marker.end()
    chunk = value[previous:]
    result.append(beta_to_uni(chunk) if greek else chunk)
    return "".join(result)


def _render_node(node: etree._Element, entities: dict[str, str],
                 inherited_greek: bool = False) -> str:
    if isinstance(node, etree._Entity):
        name = node.name
        return HTML5_ENTITIES.get(name + ";", f"&{name};")
    language = node.get("lang") or node.get("{http://www.w3.org/XML/1998/namespace}lang")
    if language:
        greek = language.strip().lower() in GREEK_LANGS
    else:
        greek = inherited_greek or node.tag == "orth"
    pieces: list[str] = []
    if node.text:
        pieces.append(_render_text(node.text, greek, entities))
    for child in node:
        pieces.append(_render_node(child, entities, greek))
        if child.tail:
            pieces.append(_render_text(child.tail, greek, entities))
    return "".join(pieces)


def _safe_entities(fragment: bytes) -> tuple[bytes, dict[str, str]]:
    entities: dict[str, str] = {}
    used_markers = set(ENTITY_MARKER.findall(fragment.decode("utf-8")))
    available_markers = (chr(value) for value in range(0xE000, 0xF900)
                         if chr(value) not in used_markers)
    by_name: dict[str, str] = {}

    def replace(match: re.Match[bytes]) -> bytes:
        name = match.group(1).decode("ascii")
        marker = by_name.get(name)
        if marker is None:
            marker = next(available_markers, None)
            if marker is None:
                raise ValueError("Too many distinct source entities in one entry")
            by_name[name] = marker
            entities[marker] = (unescape("&" + name + ";") if name.startswith("#") else
                                HTML5_ENTITIES.get(name + ";", f"&{name};"))
        return marker.encode("utf-8")
    return NAMED_ENTITY.sub(replace, fragment), entities


@lru_cache(maxsize=8)
def _entry_offsets(path: Path, mtime_ns: int | None = None,
                   size: int | None = None) -> dict[str, tuple[int, int]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    result: dict[str, tuple[int, int]] = {}
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as source:
            for match in ENTRY_START.finditer(source):
                entry_id = match.group(1).decode("utf-8")
                ending = source.find(ENTRY_END, match.end())
                if ending < 0:
                    raise ValueError(f"Unclosed TEI entry {entry_id!r} in {path}")
                result[entry_id] = (match.start(), ending + len(ENTRY_END))
    return result


def read_entry(raw_path: str | Path, entry_id: str) -> tuple[etree._Element, dict[str, str]]:
    """Read one source entry without flattening its sense/citation hierarchy.

    Missing files/IDs raise; callers may surface that failure as a warning.
    The first lookup indexes byte offsets in that source file. Only the chosen
    entry fragment is parsed; cached offsets avoid a large XML parse for each
    word. External DTDs and network entity resolution are off.
    """
    source = _source_path(raw_path)
    signature = source.stat()
    try:
        start, end = _entry_offsets(source, signature.st_mtime_ns, signature.st_size)[entry_id]
    except KeyError as exc:
        raise KeyError(f"Entry {entry_id!r} missing in {source}") from exc
    with source.open("rb") as handle:
        handle.seek(start)
        fragment = handle.read(end - start)
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False,
                             huge_tree=True, recover=False)
    safe_fragment, entities = _safe_entities(fragment)
    entry = etree.fromstring(safe_fragment, parser=parser)
    if entry.tag != "entryFree" or entry.get("id") != entry_id:
        raise ValueError(f"Malformed entry fragment {entry_id!r} in {source}")
    return entry, entities


def render_entry_text(raw_path: str | Path, entry_id: str) -> str:
    """Render one entry; only explicitly Greek spans undergo Beta conversion."""
    entry, entities = read_entry(raw_path, entry_id)
    return SPACE.sub(" ", _render_node(entry, entities)).strip()


def render_source_record(record: dict[str, Any]) -> dict[str, str | None]:
    """Add a rendered display field and explicit method/warning metadata."""
    try:
        rendered = render_entry_text(record["raw_path"], record["entry_id"])
    except (KeyError, ValueError, FileNotFoundError, etree.XMLSyntaxError) as exc:
        return {"rendered_entry_text": None, "rendering_method": METHOD,
                "rendering_warning": str(exc)}
    return {"rendered_entry_text": rendered, "rendering_method": METHOD,
            "rendering_warning": None}


__all__ = ["read_entry", "render_entry_text", "render_source_record", "METHOD"]
