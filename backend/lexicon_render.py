"""Display renderer for source TEI lexicon entries.

Audited JSONL and raw TEI remain untouched. Only explicit Greek TEI spans are
converted from Perseus Beta Code; English and Latin prose is copied verbatim.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import zlib
from collections import OrderedDict

from functools import lru_cache
from html import unescape
from html.entities import html5 as HTML5_ENTITIES
import hashlib
import mmap
from pathlib import Path
import re
from typing import Any

from betacode import beta_to_uni
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = (ROOT / "data/raw/lexica").resolve()
# Middle Liddell and Cunliffe were staged under data/raw/perseus-lexica
# (docs/lexica-perseus-ingestion.md); both directories are local XML archives.
EXTRA_RAW_ROOTS = ((ROOT / "data/raw/perseus-lexica").resolve(),)
SPACE = re.compile(r"\s+")
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

# Source TEI layouts. ``tag`` is the entry element; ``beta`` says whether
# lang="greek" spans are Perseus Beta Code (Unicode sources must never pass
# through the Beta Code converter: it would turn parentheses into breathings).
# ``located`` sources are read from the byte range recorded in the audited
# entries row (locator.byte_start/byte_end) and the fragment's own identity
# attribute is checked against entry_id; nothing is matched by headword.
# ``definition_tags`` are the TEI elements that mark English definitions.
SOURCE_FORMATS: dict[str, dict[str, Any]] = {
    "PerseusDL LSJ TEI": {"tag": "entryFree", "beta": True, "located": False,
                          "definition_tags": ("tr", "gloss", "def", "title")},
    "Perseus Autenrieth TEI via Homerica": {"tag": "entryFree", "beta": True, "located": False,
                                            "definition_tags": ("tr", "gloss", "def", "title")},
    "Perseus Middle Liddell TEI (Hopper open-source texts)": {
        "tag": "entry", "beta": True, "located": True, "id_attr": "id",
        "definition_tags": ("tr", "gloss", "def", "title"),
        # ML puts every definition inside <sense>; an example translation
        # follows a Greek <foreign> in the same sense.
        "example_rule": "sense_scoped", "reference_lead": True},
    # Cunliffe's <gloss> marks only the lexicographer's own sense heads; it
    # never translates the quoted Homeric examples, so no example rule.
    "Perseus Cunliffe TEI via Homerica": {
        "tag": "div", "beta": False, "located": True, "id_attr": XML_NS + "id",
        "definition_tags": ("gloss",), "example_rule": None, "capitalised_glosses": True,
        # Each numbered sense is a nested <div>: citations/qualifiers are scoped to it.
        "sense_tags": ("div",)},
    # Logeion's LSJ marks English definitions as italics (<i>); other
    # languages in italics carry an explicit lang attribute (README, Nov. 2024).
    "LSJ (Logeion edition, H. Dik) TEI": {
        "tag": "div2", "beta": False, "located": True, "id_attr": "id", "headword": "head",
        "definition_tags": ("i",), "reference_lead": True},
    # Dodson: <def role="brief"> and <def role="full"> are the only content.
    "Dodson Greek Lexicon (NT; public domain)": {
        "tag": "entry", "beta": False, "located": True, "id_attr": "n", "id_suffix": True,
        "definition_tags": ("def",), "example_rule": None, "merge_adjacent": False},
}
DEFAULT_FORMAT = SOURCE_FORMATS["PerseusDL LSJ TEI"]


def source_format(record: dict[str, Any] | None) -> dict[str, Any]:
    return SOURCE_FORMATS.get((record or {}).get("source"), DEFAULT_FORMAT)
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
    if (not any(candidate.is_relative_to(root) for root in (RAW_ROOT, *EXTRA_RAW_ROOTS))
            or candidate.suffix.lower() != ".xml"):
        raise ValueError(f"Lexicon source path outside local XML archive: {raw_path}")
    return candidate


def _render_text(value: str, greek: bool, entities: dict[str, str], beta: bool = True) -> str:
    """Keep decoded source entities outside the Beta Code conversion span."""
    convert = greek and beta
    result: list[str] = []
    previous = 0
    for marker in ENTITY_MARKER.finditer(value):
        if marker.group() not in entities:
            continue
        chunk = value[previous:marker.start()]
        result.append(beta_to_uni(chunk) if convert else chunk)
        result.append(entities[marker.group()])
        previous = marker.end()
    chunk = value[previous:]
    result.append(beta_to_uni(chunk) if convert else chunk)
    return "".join(result)


def _render_node(node: etree._Element, entities: dict[str, str],
                 inherited_greek: bool = False, beta: bool = True) -> str:
    if isinstance(node, etree._Entity):
        name = node.name
        return HTML5_ENTITIES.get(name + ";", f"&{name};")
    if not isinstance(node.tag, str):
        # Comments and processing instructions are not source text.
        return ""
    language = node.get("lang") or node.get("{http://www.w3.org/XML/1998/namespace}lang")
    if language:
        greek = language.strip().lower() in GREEK_LANGS
    else:
        greek = inherited_greek or node.tag == "orth"
    pieces: list[str] = []
    if node.text:
        pieces.append(_render_text(node.text, greek, entities, beta))
    for child in node:
        pieces.append(_render_node(child, entities, greek, beta))
        if child.tail:
            pieces.append(_render_text(child.tail, greek, entities, beta))
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


# Release U: 8 files thrashed (a lookup touches dozens of dictionary files); offsets are small.
@lru_cache(maxsize=512)
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


def _identity_matches(entry: etree._Element, fmt: dict[str, Any], entry_id: str,
                      entities: dict[str, str] | None = None) -> bool:
    value = entry.get(fmt.get("id_attr", "id"))
    if value is None:
        return False
    # Character references in the attribute (Logeion ids such as
    # "crossa)ke/llea&lt;n&gt;") were swapped for placeholders before parsing.
    value = "".join((entities or {}).get(char, char) for char in value)
    if fmt.get("id_suffix"):
        # Dodson: n="<lemma> | <number>"; entry_id is the number.
        return value.rpartition("|")[2].strip() == entry_id
    return value == entry_id


def _read_located(source: Path, entry_id: str, fmt: dict[str, Any],
                  locator: dict[str, Any] | None) -> tuple[etree._Element, dict[str, str]]:
    start = (locator or {}).get("byte_start")
    end = (locator or {}).get("byte_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise KeyError(f"Entry {entry_id!r} has no byte locator in {source}")
    with source.open("rb") as handle:
        handle.seek(start)
        fragment = handle.read(end - start)
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False,
                             huge_tree=True, recover=False)
    safe_fragment, entities = _safe_entities(fragment)
    entry = etree.fromstring(safe_fragment, parser=parser)
    if entry.tag != fmt["tag"] or not _identity_matches(entry, fmt, entry_id, entities):
        raise ValueError(f"Malformed entry fragment {entry_id!r} in {source}")
    return entry, entities


def read_entry(raw_path: str | Path, entry_id: str,
               record: dict[str, Any] | None = None) -> tuple[etree._Element, dict[str, str]]:
    """Read one source entry without flattening its sense/citation hierarchy.

    Missing files/IDs raise; callers may surface that failure as a warning.
    The first lookup indexes byte offsets in that source file. Only the chosen
    entry fragment is parsed; cached offsets avoid a large XML parse for each
    word. External DTDs and network entity resolution are off.

    Sources marked ``located`` in SOURCE_FORMATS are read from the byte range
    in the audited record's locator instead, and the fragment's own identity
    attribute must equal ``entry_id``.
    """
    fmt = source_format(record)
    if fmt.get("located"):
        return _read_located(_source_path(raw_path), entry_id, fmt, (record or {}).get("locator"))
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


def render_entry_text(raw_path: str | Path, entry_id: str,
                      record: dict[str, Any] | None = None) -> str:
    """Render one entry; only explicitly Greek spans undergo Beta conversion."""
    entry, entities = read_entry(raw_path, entry_id, record)
    return SPACE.sub(" ", _render_node(entry, entities, beta=source_format(record)["beta"])).strip()


def _render_spans(entry: etree._Element, entities: dict[str, str], beta: bool = True):
    """Render the existing source text while retaining exact node offsets."""
    pieces, spans, length = [], {}, 0
    def append(text):
        nonlocal length
        pieces.append(text)
        length += len(text)
    def visit(node, inherited=False):
        start = length
        if isinstance(node, etree._Entity):
            append(_render_node(node, entities, inherited, beta))
        elif not isinstance(node.tag, str):
            pass  # comments / processing instructions carry no source text
        else:
            language = node.get('lang') or node.get('{http://www.w3.org/XML/1998/namespace}lang')
            greek = language.strip().lower() in GREEK_LANGS if language else inherited or node.tag == 'orth'
            if node.text:
                append(_render_text(node.text, greek, entities, beta))
            for child in node:
                visit(child, greek)
                if child.tail:
                    append(_render_text(child.tail, greek, entities, beta))
        spans[node] = (start, length)
    visit(entry)
    return ''.join(pieces), spans


def _comparative_definition(entry: etree._Element, entities: dict[str, str]) -> dict | None:
    """A narrow source-layout correction, not a general LSJ sense classifier.

    LSJ can open its first <sense> inside a comparative morphology note and
    uses <tr> for Sanskrit forms too. Only the explicitly marked ``cf. Skt.``
    parenthetical-preamble layout is supported here. Other layouts abstain.
    Greek Beta Code is rendered first, so breathing signs are not parentheses.
    """
    text, spans = _render_spans(entry, entities)
    trs = list(entry.iter('tr'))
    for ordinal, boundary in enumerate(re.finditer(r':\s*\u2014', text), 1):
        stack, parentheses, invalid = [], [], False
        for index, char in enumerate(text[:boundary.start()]):
            if char == '(':
                stack.append(index)
            elif char == ')':
                if not stack:
                    invalid = True
                    break
                parentheses.append((stack.pop(), index + 1))
        if invalid or stack:
            continue
        previous = [node for node in trs if spans[node][0] < boundary.start()]
        if not previous:
            continue
        # A mere parenthetical translation is not proof of an etymology. Its
        # containing source note must explicitly identify the comparison.
        if not all(any(start < spans[node][0] and spans[node][1] <= end
                       and re.search(r'\bcf\.\s*Skt\.', text[start:spans[node][0]], re.I)
                       for start, end in parentheses) for node in previous):
            continue
        senses = [node for node in entry.iter('sense')
                  if spans[node][0] <= boundary.start() and spans[node][1] >= boundary.end()]
        if not senses:
            continue
        sense = min(senses, key=lambda node: spans[node][1] - spans[node][0])
        start, end = boundary.end(), spans[sense][1]
        stops = [spans[node][0] for node in sense.iter()
                 if node.tag in {'bibl', 'cit', 'sense'} and spans[node][0] >= start]
        if stops:
            end = min(end, *stops)
        if not any(start <= spans[node][0] < spans[node][1] <= end for node in trs):
            continue
        # Keep all surrounding source words (not a bag of isolated <tr>s),
        # especially contrasts such as "man, opp. woman" and their qualifiers.
        excerpt = SPACE.sub(' ', text[start:end]).strip()
        if not excerpt or len(excerpt) > 700 or re.search(r'\bcf\.\s*Skt\.', excerpt, re.I):
            continue
        depth, balanced = 0, True
        for char in excerpt:
            depth += (char == '(') - (char == ')')
            if depth < 0:
                balanced = False
                break
        if not balanced or depth:
            # A citation can occur inside a meaning qualifier. Do not expose
            # an excerpt that ends halfway through that parenthetical scope.
            continue
        if re.search(r'\b(?:esp|opp|viz|e\.g|i\.e)\.\s*$', excerpt, re.I):
            # Some source <sense> starts divide a running clause immediately
            # after a qualification marker. Do not publish that dangling lead-in.
            continue
        return {'definition_excerpt': excerpt,
                'source_locator': {'sense_id': sense.get('id'), 'boundary_ordinal': ordinal,
                                   'rendered_start': start, 'rendered_end': end,
                                   'offset_basis': 'uncompacted Greek-span-rendered TEI entry'}}
    return None


@lru_cache(maxsize=160)  # LSJ (27) + Logeion LSJ (86) + other lexicon files
def _raw_digest(path: Path, mtime_ns: int, size: int) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def definition_excerpt(record: dict[str, Any]) -> dict[str, Any]:
    """Return an optional hash-bound LSJ display excerpt, never replace gloss."""
    if (record.get('source') != 'PerseusDL LSJ TEI' or not record.get('raw_sha256')
            or not record.get('source_url')):
        return {}
    path = _source_path(record['raw_path'])
    signature = path.stat()
    if _raw_digest(path, signature.st_mtime_ns, signature.st_size) != record['raw_sha256']:
        return {}
    entry, entities = read_entry(record['raw_path'], record['entry_id'])
    after = path.stat()
    if (after.st_mtime_ns, after.st_size) != (signature.st_mtime_ns, signature.st_size):
        return {}
    found = _comparative_definition(entry, entities)
    if not found:
        return {}
    return {'definition_excerpt': found['definition_excerpt'],
            'definition_excerpt_provenance': {
                'source_url': record.get('source_url'), 'entry_id': record['entry_id'],
                'raw_sha256': record['raw_sha256'],
                'method': 'Source definition clause after an explicit balanced Sanskrit comparative preamble; no contextual sense adjudication.',
                'source_locator': found['source_locator']}}


_RENDERED: "OrderedDict[str, str]" = OrderedDict()
_RENDERED_LOCK = threading.Lock()
_RENDERED_MAX = 4096
_STORE = threading.local()


def _render_key(record: dict[str, Any]) -> str | None:
    parts = (record.get("raw_path"), record.get("entry_id"), record.get("raw_sha256"), record.get("id"))
    if all(part is None for part in parts):
        return None
    return json.dumps([str(p) if p is not None else None for p in parts], ensure_ascii=False)


def _render_store():
    """Release U: optional precomputed renderings (scripts/build_render_cache.py), env MELOS_RENDER_CACHE."""
    path = os.environ.get("MELOS_RENDER_CACHE", "")
    if not path:
        return None
    con = getattr(_STORE, "con", None)
    if con is None:
        try:
            con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, check_same_thread=False)
            con.execute("SELECT 1 FROM rendered LIMIT 1")
        except sqlite3.Error:
            con = False
        _STORE.con = con
    return con or None


def render_source_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add a rendered display field and explicit method/warning metadata.

    Release U: memoised per source record (path, entry id, raw SHA-256, record id); the archived entries never
    change while the server runs (a changed file has another hash, so a stale rendering cannot match). The
    memo holds JSON text and every call decodes a fresh copy, so callers may edit theirs. A precomputed store
    (MELOS_RENDER_CACHE, built by scripts/build_render_cache.py with this same function) answers first
    lookups; big entries (LSJ ὁ, σύ) took 10-40 ms to render and were rendered again on every word lookup."""
    key = _render_key(record)
    if key is None:
        return _render_source_record(record)
    with _RENDERED_LOCK:
        text = _RENDERED.get(key)
        if text is not None:
            _RENDERED.move_to_end(key)
    if text is None:
        store = _render_store()
        if store is not None:
            try:
                row = store.execute("SELECT value FROM rendered WHERE key=?", (key,)).fetchone()
            except sqlite3.Error:
                row = None
            if row:
                text = zlib.decompress(row[0]).decode("utf-8")
        if text is None:
            text = json.dumps(_render_source_record(record), ensure_ascii=False)
        with _RENDERED_LOCK:
            _RENDERED[key] = text
            while len(_RENDERED) > _RENDERED_MAX:
                _RENDERED.popitem(last=False)
    return json.loads(text)


def _render_source_record(record: dict[str, Any]) -> dict[str, Any]:
    from .lexicon_senses import dictionary_senses
    try:
        rendered = render_entry_text(record["raw_path"], record["entry_id"], record)
    except (KeyError, ValueError, FileNotFoundError, etree.XMLSyntaxError) as exc:
        return {"rendered_entry_text": None, "rendering_method": METHOD,
                "rendering_warning": str(exc), **dictionary_senses(record)}
    result = {"rendered_entry_text": rendered, "rendering_method": METHOD,
              "rendering_warning": None}
    try:
        result.update(definition_excerpt(record))
    except (KeyError, ValueError, OSError, etree.XMLSyntaxError):
        # Optional compact display correction fails closed; the diplomatic
        # stored gloss and full source rendering are still available.
        pass
    # Import locally to keep the source reader independent of its optional
    # structured-definition projection.
    result.update(dictionary_senses(record))
    return result


__all__ = ["read_entry", "render_entry_text", "render_source_record", "source_format",
           "SOURCE_FORMATS", "METHOD"]
