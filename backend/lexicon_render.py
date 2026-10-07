"""Display renderer for source TEI lexicon entries.

Audited JSONL and raw TEI remain untouched. Only explicit Greek TEI spans are
converted from Perseus Beta Code; English and Latin prose is copied verbatim.
"""

from __future__ import annotations

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


def _render_spans(entry: etree._Element, entities: dict[str, str]):
    """Render the existing source text while retaining exact node offsets."""
    pieces, spans, length = [], {}, 0
    def append(text):
        nonlocal length
        pieces.append(text)
        length += len(text)
    def visit(node, inherited=False):
        start = length
        if isinstance(node, etree._Entity):
            append(_render_node(node, entities, inherited))
        else:
            language = node.get('lang') or node.get('{http://www.w3.org/XML/1998/namespace}lang')
            greek = language.strip().lower() in GREEK_LANGS if language else inherited or node.tag == 'orth'
            if node.text:
                append(_render_text(node.text, greek, entities))
            for child in node:
                visit(child, greek)
                if child.tail:
                    append(_render_text(child.tail, greek, entities))
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


@lru_cache(maxsize=32)
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


def render_source_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add a rendered display field and explicit method/warning metadata."""
    from .lexicon_senses import dictionary_senses
    try:
        rendered = render_entry_text(record["raw_path"], record["entry_id"])
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


__all__ = ["read_entry", "render_entry_text", "render_source_record", "METHOD"]
