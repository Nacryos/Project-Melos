"""Conservative author + fragment lookup, never a numbering concordance.

Only existing author labels / externally verified aliases and explicitly
recorded fragment numbers are used. No poem text, catalogue page number, ID,
or bibliography year is searched to guess a fragment's identity.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import re
import unicodedata


def _key(value: object) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value or "")).casefold().split())


_NUMBER = r"[0-9]{1,5}[a-zΑ-Ωα-ω]?"
_MARKER = r"(?:fr(?:ag(?:ment)?)?s?\.?|fragmenta|απ\.)"
# These are recognized query syntax, not claims of equivalence between editions.
_SCHEMES = r"(?:Edmonds|Page|Voigt|Bergk|Campbell|Lobel[ -]Page|PMG|PMGF)"
_TAIL = re.compile(
    rf"^(?:{_MARKER}\s*)?(?P<number>{_NUMBER})(?:\s+(?P<scheme>{_SCHEMES}))?$",
    re.I,
)
_FRAGMENT = re.compile(rf"(?<!\w){_MARKER}\s*(?P<number>{_NUMBER})(?!\w)", re.I)
_NAMED = re.compile(rf"(?<!\w)(?P<scheme>{_SCHEMES})\s+(?P<number>{_NUMBER})(?!\w)", re.I)
_QUALIFIED_START = re.compile(
    rf"^(?P<number>{_NUMBER})\s+(?P<scheme>{_SCHEMES})(?:\s*\(|\s*$)", re.I,
)


@dataclass(frozen=True)
class ReferenceIntent:
    author: str
    author_labels: tuple[str, ...]
    number: str
    scheme: str = ""
    filter_conflict: bool = False


def parse_reference_query(
    query: str,
    known_authors: Iterable[str],
    *,
    selected_author: str = "",
    alias_resolver: Callable[[str], Iterable[str]] | None = None,
) -> ReferenceIntent | None:
    """Recognize ``Sappho fr. 31`` or ``31`` with an author filter.

    The caller supplies corpus author labels. ``alias_resolver`` must only
    return verified author identities (e.g. ``server.author_labels``). No fuzzy
    author matching or author abbreviation expansion occurs here.
    """
    query = _key(query)
    labels = list(dict.fromkeys(str(a) for a in known_authors if a))
    if selected_author and selected_author not in labels:
        labels.append(selected_author)
    explicit_author = ""
    tail = query
    for label in sorted(labels, key=len, reverse=True):
        prefix = _key(label) + " "
        if query.startswith(prefix):
            explicit_author, tail = label, query[len(prefix):]
            break
    # Resolve only the proposed author, not every author in the corpus. The
    # audited resolver may verify large provenance files on each invocation.
    if not explicit_author and alias_resolver:
        for split in range(1, len(query.split())):
            candidate = " ".join(query.split()[:split])
            remainder = " ".join(query.split()[split:])
            if not _TAIL.fullmatch(remainder):
                continue
            aliases = list(alias_resolver(candidate))
            if {_key(a) for a in aliases} & {_key(a) for a in labels}:
                explicit_author, tail = candidate, remainder
                break
    author = explicit_author or selected_author
    if not author:
        return None
    match = _TAIL.fullmatch(tail)
    if not match:
        return None
    aliases = tuple(dict.fromkeys((author, *(alias_resolver(author) if alias_resolver else ()))))
    conflict = bool(selected_author and _key(selected_author) not in {_key(a) for a in aliases})
    return ReferenceIntent(author, aliases, match["number"].casefold(),
                           match["scheme"] or "", conflict)


def _references(record: Mapping) -> list[tuple[str, str, str]]:
    """Return (number, scheme, evidence) from citation / explicit metadata only."""
    citation = str(record.get("citation") or "")
    fragment_collection = bool(re.search(r"fragment", str(record.get("work") or ""), re.I))
    qualified_heading = _QUALIFIED_START.match(citation.strip()) if fragment_collection else None
    # A qualified primary heading may discuss other editions in parentheses.
    # Keep that source text intact in the record, but do not interpret pieces
    # of its prose as independent numbering concordances (e.g. Page within
    # the compound name "Lobel & Page").
    if qualified_heading:
        citation = citation.split('(', 1)[0].strip()
    refs = []
    for match in _FRAGMENT.finditer(citation):
        # Do not turn a fragment range into a claim for its first number.
        if re.match(r"(?:\s*[-–—]\s*|[.:])\d", citation[match.end():]):
            continue
        before, after = citation[:match.start()], citation[match.end():]
        prefix = re.search(rf"(?P<scheme>{_SCHEMES})\s*$", before, re.I)
        suffix = re.match(rf"\s+(?P<scheme>{_SCHEMES})(?!\w)", after, re.I)
        scheme = (prefix or suffix).group("scheme") if prefix or suffix else ""
        refs.append((match["number"].casefold(), _key(scheme), citation))
    for match in _NAMED.finditer(citation):
        if not re.match(r"(?:\s*[-–—]\s*|[.:])\d", citation[match.end():]):
            refs.append((match["number"].casefold(), _key(match["scheme"]), citation))
    # A plain numeric locus is a fragment only for a fragment collection.
    if fragment_collection:
        bare = _TAIL.fullmatch(_key(citation))
        if bare:
            refs.append((bare["number"].casefold(), _key(bare["scheme"]), citation))
        # An edition-qualified heading can retain a parenthetical source note.
        # Match its stated leading identity, not numbers mentioned in the note.
        qualified = _QUALIFIED_START.match(citation.strip())
        if qualified:
            refs.append((qualified["number"].casefold(), _key(qualified["scheme"]), citation))
    metadata = record.get("metadata") or {}
    if isinstance(metadata, Mapping):
        edmonds = str(metadata.get("edmonds_fragment_number") or "")
        if re.fullmatch(_NUMBER, edmonds, re.I):
            refs.append((edmonds.casefold(), "edmonds", "metadata.edmonds_fragment_number=" + edmonds))
        # Source-local heading aliases are extracted from an explicit sidebar
        # section on the same page. They do not establish a global equivalence
        # between Greek and Latin suffixes or between editions.
        aliases = metadata.get('source_citation_aliases', [])
        for alias in aliases if isinstance(aliases, list) else []:
            if not isinstance(alias, Mapping):
                continue
            heading = _key(alias.get('body_heading'))
            if (alias.get('scope') != 'fragment_heading'
                    or not alias.get('source_url')
                    or alias.get('source_url') != record.get('source_url')
                    or not alias.get('locator') or not heading
                    or heading != _key(metadata.get('source_heading'))):
                continue
            explicit = _TAIL.fullmatch(_key(alias.get('label')))
            if explicit:
                evidence = f"Source heading alias {alias['label']} at {alias['locator']} ({alias['source_url']}); body heading {alias['body_heading']}"
                refs.append((explicit['number'].casefold(), _key(explicit['scheme']), evidence))
    return refs


def rank_reference_records(
    intent: ReferenceIntent,
    records: Iterable[Mapping],
    *,
    language: str = "",
    edition: str = "",
    limit: int = 30,
    offset: int = 0,
    include_reference: bool = False,
) -> dict:
    """Return exact fragment records, including honestly labelled references.

    Callers must supply records already restricted by publication policy. This
    helper intentionally includes catalogue/reference records even when the
    general search hides those: a catalogue pointer is more honest than an
    unrelated poem. Language/edition filters remain effective. A recognized
    intent with zero matches MUST NOT fall back to broad word/form retrieval.
    """
    if limit < 0 or offset < 0:
        raise ValueError("limit and offset must be nonnegative")
    labels = {_key(label) for label in intent.author_labels}
    records = list(records)
    by_id = {record.get('id'): record for record in records if record.get('id')}
    hits = []
    if not intent.filter_conflict:
        for record in records:
            parent = by_id.get(record.get('parent_id'))
            linked_author = bool(record.get('kind') in {'translation', 'commentary'}
                                 and parent and parent.get('kind') == 'text'
                                 and parent.get('language') == 'grc'
                                 and _key(parent.get('author')) in labels
                                 and (include_reference or parent.get('quality') in {'source_text', 'machine_corrected_ocr'}))
            if _key(record.get("author")) not in labels and not linked_author:
                continue
            if language and record.get("language") != language:
                continue
            if edition and record.get("edition") != edition:
                continue
            matches = [ref for ref in _references(record) if ref[0] == intent.number
                       and (not intent.scheme or ref[1] == _key(intent.scheme))]
            if not matches:
                continue
            item = dict(record)
            if linked_author and _key(record.get('author')) not in labels:
                item['author_scope_reason'] = (
                    'Linked to the selected author by an explicit Greek parent passage; '
                    'translation/commentary authorship is retained.')
            metadata = item.get("metadata") or {}
            metadata = metadata if isinstance(metadata, Mapping) else {}
            reference_only = item.get("kind") in {"reference", "apparatus"} or metadata.get("greek_text_extracted") is False
            review = item.get("quality") in {"needs_review", "machine_ocr", "mixed_content"}
            partial = bool(metadata.get("partial_fragment_line"))
            section = bool(metadata.get('source_section')) and item.get('kind') == 'text'
            status = ("reference_only" if reference_only else "needs_review" if review
                      else "partial_text" if partial else "section_text" if section
                      else "text" if item.get("kind") == "text"
                      else "translation" if item.get("kind") == "translation" else "commentary")
            item["reference_match"] = {"number": intent.number, "scheme": intent.scheme or None,
                                       "evidence": list(dict.fromkeys(m[2] for m in matches)),
                                       "coverage": status}
            item["match_reason"] = "Exact author and explicit fragment citation; " + {
                "reference_only": "catalogue/reference only, not an available Greek reading text",
                "needs_review": "source text requires review",
                "partial_text": "partial fragment line, not a complete fragment",
                "section_text": "source-labelled section or column, not whole-fragment scope",
                "text": "source reading text; numbering remains edition-specific",
                "translation": "translation; translator authorship and output language are retained, not a Greek reading text",
                "commentary": "commentary, not the poem text",
            }[status]
            item["score"] = None
            hits.append(item)
    ranks = {"text": 0, "section_text": 1, "partial_text": 2, "translation": 3, "commentary": 4, "needs_review": 5, "reference_only": 6}
    hits.sort(key=lambda item: (ranks[item["reference_match"]["coverage"]], str(item.get("citation", "")), str(item.get("id", ""))))
    warnings = ["Fragment numbers are edition-specific. Only explicit recorded citations are matched; no numbering equivalence is inferred."]
    if intent.filter_conflict:
        warnings.append("The author in the query conflicts with the selected author filter. Clear or change the filter.")
    elif not hits:
        warnings.append("No matching fragment citation is indexed under these filters. This is a coverage limitation, not evidence that the fragment does not exist.")
    elif all(item["reference_match"]["coverage"] == "reference_only" for item in hits):
        warnings.append("Only catalogue/reference records are available for this citation; the Greek reading text is not indexed here.")
    elif not any(item["reference_match"]["coverage"] == "text" for item in hits):
        warnings.append("No whole-fragment-scope reading-text record was matched: results are source sections, partial lines, translations, commentary, references, or text requiring review.")
    return {"results": hits[offset:offset + limit], "total": len(hits), "mode": "reference",
            "method": "Exact author + fragment reference lookup", "warnings": warnings,
            "reference_query": {"author": intent.author, "number": intent.number, "scheme": intent.scheme or None}}
