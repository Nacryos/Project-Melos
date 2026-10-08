"""Conservative, source-bound definition spans from the archived Perseus TEI.

TEI ``tr``/``gloss`` are candidate markers, not proof of an English meaning:
the same tags enclose Sanskrit cognates, antonyms and example translations.
This display projection retains node identities, scopes and source offsets;
it neither changes the archive nor supplies missing meanings from a model.
"""
from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
import re
from typing import Any

from lxml import etree

from .short_gloss import meaningful

from .lexicon_render import (GREEK_LANGS, SOURCE_FORMATS, SPACE, _raw_digest, _render_spans,
                             _source_path, read_entry, source_format)

VERSION = "tei-definition-spans-v4"
# Every TEI dictionary whose layout lexicon_render.SOURCE_FORMATS describes.
SOURCES = frozenset(SOURCE_FORMATS)
BLOCKED = {"bibl", "cit", "quote", "etym", "xr", "foreign", "orth",
           "itype", "pron", "gram", "gramGrp"}
NON_ENGLISH = re.compile(r"\b(?:Skt\.|Sanskrit|Lat\.|Latin|Germ\.|Goth\.|I\.-\s*E\.|Lith\.|Zend|root\b)", re.I)
OPPOSITION = re.compile(r"\b(?:opp\.|opposed to|as opposed to)(?:\s+to)?\s*$", re.I)
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
GRAMMATICAL_LEAD = re.compile(r"\b(?:gen\.|dat\.|acc\.|nom\.|voc\.|dual|Adv\.|strengthd\.)", re.I)
OFFSET_BASIS = "uncompacted Greek-span-rendered TEI entry"
# This is a source typography delimiter, not a linguistic inference: LSJ
# separates inflectional preambles from English definitions with colon-dash.
DEFINITION_BOUNDARY = re.compile(r":\s*[\u2014\u2013]")
# Source-typography markers that introduce a referenced Greek word rather than
# a usage example ("poet. for", "Adv. of", "= ", "cf."). Used only for sources
# whose SOURCE_FORMATS entry sets reference_lead (Middle Liddell, Logeion LSJ).
REFERENCE_LEAD = re.compile(r"(?:\b(?:for|of|from|than)|=|\bcf\.|\bi\.\s*e\.|\bv\.)\s*,?\s*$", re.I)
PREAMBLE = {"etym", "form", "note", "xr"}


def _is_greek(node):
    language = node.get("lang") or node.get("{http://www.w3.org/XML/1998/namespace}lang")
    return bool(language) and language.strip().lower() in GREEK_LANGS


def _plain(value: str) -> str:
    return SPACE.sub(" ", value).strip()


def _parentheses(text: str) -> list[tuple[int, int]]:
    stack, result = [], []
    for i, char in enumerate(text):
        if char in "([":
            stack.append((char, i))
        elif char in ")]" and stack:
            opening, start = stack[-1]
            if (opening, char) in {("(", ")"), ("[", "]")}:
                stack.pop()
                result.append((start, i + 1))
    # Unclosed source notes cannot establish a return to English definition.
    result.extend((start, len(text)) for _, start in stack)
    return result


def _locator(node, start, end):
    return {"node_path": node.getroottree().getpath(node),
            "rendered_start": start, "rendered_end": end,
            "offset_basis": OFFSET_BASIS}


# Element(s) that delimit one source sense. Cunliffe nests sense <div>s
# instead of <sense>; set per parse from SOURCE_FORMATS (thread-local context).
_SENSE_TAGS: ContextVar[tuple[str, ...]] = ContextVar("sense_tags", default=("sense",))


def _scope(node, entry):
    tags = _SENSE_TAGS.get()
    return next((a for a in node.iterancestors() if a.tag in tags), entry)


def _path(scope):
    ancestors = list(scope.iterancestors())[::-1] + [scope]
    return [{"id": a.get("id"), "n": a.get("n"), "level": a.get("level")}
            for a in ancestors if a.tag == "sense"]


def _backward_tense_restrictions(entry, text, spans, rows):
    """Resolve one explicit, bounded LSJ backward-reference layout.

    Source: archived Perseus LSJ, erchomai n42827.2. Its terminal declaration
    names exactly "the two foreg. rare signfs." and marks ``pres.`` in <tns>.
    Require adjacent numbered I/2 meaning units, extracted definitions, the
    same explicit headword, and the source-sense boundary. Other backward
    references abstain. ``Pres`` follows the existing UD Tense convention:
    https://universaldependencies.org/u/feat/Tense.html .
    """
    headword = next(iter(entry.iter("orth")), None)
    if headword is None:
        return
    identity = _plain(text[slice(*spans[headword])]).rstrip("., ")
    for tense in entry.iter("tns"):
        if _plain(text[slice(*spans[tense])]) != "pres.":
            continue
        scope = tense.getparent()
        if scope is None or scope.tag != "sense" or scope.getparent() is not entry:
            continue
        if scope.get("n") != "2" or scope.get("level") != "3":
            continue
        previous = scope.getprevious()
        if (previous is None or previous.tag != "sense" or previous.get("n") != "I"
                or previous.get("level") != "2"):
            continue
        form = tense.getnext()
        if form is None or form.tag != "foreign" or form.getnext() is not None:
            continue
        if not re.fullmatch(r"\s*", tense.tail or ""):
            continue
        if _plain(text[slice(*spans[form])]).rstrip("., ") != identity:
            continue
        if not re.fullmatch(r"[\s.]*", form.tail or ""):
            continue
        # Inspect only the immediately preceding source text node. This
        # deliberately rejects negations, unbounded counts and quoted notes.
        predecessor = tense.getprevious()
        if predecessor is None or predecessor.tag != "bibl":
            continue
        match = re.fullmatch(r"\s*:\s*(the two foreg\. rare signfs\. belong only to the)\s*",
                             predecessor.tail or "")
        if not match:
            continue
        target_ids = [previous.get("id"), scope.get("id")]
        if not all(target_ids):
            continue
        targets = {source_id: [row for row in rows if row.get("sense_path")
                              and row["sense_path"][-1].get("id") == source_id]
                   for source_id in target_ids}
        if not all(targets.values()):
            continue
        start = spans[predecessor][1] + match.start(1)
        end = spans[form][1]
        restriction = {"kind": "source_tense_only", "feature": "Tense",
                       "allowed_values": ["Pres"],
                       "source_text": _plain(text[start:end]),
                       "source_locator": _locator(scope, start, end),
                       "tense_source_locator": _locator(tense, *spans[tense]),
                       "scope": {"kind": "preceding_meaning_units", "count": 2,
                                 "target_source_sense_ids": target_ids},
                       "extraction_rule": "explicit_terminal_two_foregoing_present_senses_v1"}
        for group in targets.values():
            for row in group:
                bound = deepcopy(restriction)
                bound.update(source_url=row["source_url"], raw_sha256=row["raw_sha256"],
                             lexicon_entry_id=row["lexicon_entry_id"], entry_id=row["entry_id"],
                             raw_path=row["raw_path"], source=row["source"])
                row.setdefault("morphology_restrictions", []).append(bound)


def _parse(entry, entities, record):
    fmt = source_format(record)
    token = _SENSE_TAGS.set(tuple(fmt.get("sense_tags", ("sense",))))
    try:
        return _parse_entry(entry, entities, record, fmt)
    finally:
        _SENSE_TAGS.reset(token)


def _parse_entry(entry, entities, record, fmt):
    text, spans = _render_spans(entry, entities, fmt["beta"])
    parentheses = _parentheses(text)
    nodes = [n for n in entry.iter() if isinstance(n.tag, str)]
    order = {node: i for i, node in enumerate(nodes)}
    definition_tags = set(fmt["definition_tags"])
    # Elements that mark an English rendering for example/continuation checks.
    # Unchanged {"tr", "gloss"} for the original LSJ/Autenrieth layout.
    marked = {"tr", "gloss"} | (definition_tags - {"def", "title"})
    example_rule = fmt.get("example_rule", "lsj")
    headword_tag = fmt.get("headword", "orth")
    first_orth = (entry.find(headword_tag) if headword_tag != "orth"
                  else next(iter(entry.iter("orth")), None))
    accepted, excluded = [], []

    def make(node, start, end, kind, scope=None):
        scope = scope if scope is not None else _scope(node, entry)
        while start < end and text[start].isspace():
            start += 1
        while end > start and (text[end - 1].isspace() or text[end - 1] in ",;"):
            end -= 1
        locator = _locator(node, start, end)
        # A local source window is evidence, not an inferred restriction. Full
        # entry and containing-sense citations remain independently available.
        scope_start, scope_end = spans[scope]
        context_start = max(0, min(scope_start, start - 260))
        context_start = max(context_start, start - 480)
        context_end = min(scope_end, end + 240)
        citations = [{"text": _plain(text[spans[c][0]:spans[c][1]]),
                      "reference": c.get("n"),
                      "source_locator": _locator(c, *spans[c])}
                     for c in scope.iter("bibl") if _scope(c, entry) is scope]
        qualifiers = [{"text": _plain(text[spans[q][0]:spans[q][1]]),
                       "type": q.get("type") or q.tag,
                       "source_locator": _locator(q, *spans[q])}
                      for q in scope.iter() if q.tag in {"usg", "lbl", "gram"}
                      and _scope(q, entry) is scope]
        row = {"id": f"{record['id']}:{VERSION}:{locator['node_path']}:{start}:{end}",
               "entry_id": record["entry_id"], "lexicon_entry_id": record["id"],
               "text": _plain(text[start:end]), "language": "en",
               "source": record["source"], "source_url": record["source_url"],
               "raw_sha256": record["raw_sha256"], "raw_path": record["raw_path"],
               "evidence_type": "dictionary_sense", "definition_kind": kind,
               "sense_path": _path(scope), "scope_text": _plain(text[context_start:context_end]),
               "scope_locator": {"rendered_start": context_start, "rendered_end": context_end,
                                 "offset_basis": OFFSET_BASIS},
               "qualifiers": qualifiers, "citations": citations,
               "qualifier_scope": "containing_source_sense_not_individual_definition",
               "citation_scope": "containing_source_sense_not_individual_definition",
               "source_locator": locator, "extraction_method": VERSION}
        orths = [o for o in entry.iter("orth") if spans[o][1] <= start
                 and not any(a.tag in {"cit", "bibl", "quote"} for a in o.iterancestors())]
        if orths:
            orth = orths[-1]
            # A variant in a parenthetical preamble does not govern all
            # subsequent senses. Only an immediately adjacent orthography
            # declaration can restrict this definition; otherwise retain the
            # entry headword identity (not the latest spelling mentioned).
            if orth is not first_orth and not re.fullmatch(r"[\s,]*", text[spans[orth][1]:start]):
                orth = first_orth
            row["form_scope"] = {"text": _plain(text[slice(*spans[orth])]),
                                 "relation": "headword" if orth is first_orth else "variant",
                                 "source_locator": _locator(orth, *spans[orth])}
        # Explicit morphology-labelled subforms (not all adjacent examples)
        # can introduce their own definition without an <orth> wrapper.
        foreign_forms = [o for o in entry.iter("foreign") if spans[o][1] <= start
                         and not any(a.tag in {"cit", "bibl", "quote"} for a in o.iterancestors())]
        if foreign_forms:
            form = foreign_forms[-1]
            gap = _plain(text[spans[form][1]:start])
            lead = _plain(text[max(0, spans[form][0] - 75):spans[form][0]])
            if len(gap) < 8 and re.search(r"\b(?:Adv\.|strengthd\.)\s*$", lead):
                row["form_scope"] = {"text": _plain(text[slice(*spans[form])]),
                                     "relation": "variant",
                                     "source_locator": _locator(form, *spans[form])}
        return row

    for node in nodes:
        if node.tag not in definition_tags:
            continue
        # LSJ sometimes marks an English entry-head definition as <title>,
        # e.g. ego. Bibliographical titles are never definition candidates.
        if node.tag == "title":
            previous = node.getprevious()
            if (node.getparent() is not entry or previous is not first_orth
                    or not re.fullmatch(r"\s*,?\s*", previous.tail or "")
                    or not re.match(r"\s*:", node.tail or "")):
                continue
        a, b = spans[node]
        value = _plain(text[a:b])
        reason = None
        ancestors = list(node.iterancestors())
        language = next((n.get("lang") or n.get("{http://www.w3.org/XML/1998/namespace}lang")
                         for n in [node] + ancestors
                         if n.get("lang") or n.get("{http://www.w3.org/XML/1998/namespace}lang")), None)
        if any(n.tag in BLOCKED for n in ancestors):
            reason = "citation_form_or_nondefinition_container"
        elif language and language.lower() not in {"en", "eng", "english"}:
            reason = "explicit_non_english_language"
        elif not re.search(r"[A-Za-z]", value) or GREEK.search(value):
            reason = "no_english_definition_text"
        elif not meaningful(value):
            # A bare article or one letter ("a," in LSJ Dionysos) is a
            # typographic fragment of a phrase, not a definition.
            reason = "no_english_definition_text"
        elif re.fullmatch(r"[A-Z][\w-]+\.", value) and not (
                # Cunliffe prints one-word sense heads capitalised with a full
                # stop ("Thoughtlessness."); short ones stay excluded.
                fmt.get("capitalised_glosses") and len(value) > 6):
            reason = "abbreviation_not_safe_definition"
        elif re.fullmatch(r"[A-Z]{2,}[,.;]?", value):
            reason = "citation_acronym_not_safe_definition"
        elif (node.getprevious() is not None and node.getprevious().tag in {"bibl", "cit"}
              and node.getnext() is not None and node.getnext().tag == "bibl"
              and node.getnext().find("biblScope") is not None
              and not (node.getprevious().tail or "").strip()
              and not (node.tail or "").strip()):
            reason = "bibliographic_fragment_between_citation_nodes"
        elif any(start <= a < end and NON_ENGLISH.search(text[start:a])
                 for start, end in parentheses):
            reason = "comparative_or_etymological_note"
        else:
            prefix = _plain(text[max(0, a - 180):a])
            if NON_ENGLISH.search(re.split(r"[:;\u2014)]", prefix)[-1]):
                reason = "explicit_non_english_comparison"
            elif OPPOSITION.search(prefix):
                reason = "opposed_meaning_not_headword_definition"
            elif any(start <= a < end and GREEK.search(text[start:a])
                     and re.search(r"\b(?:being|means|opp\.)", text[start:a])
                     for start, end in parentheses):
                reason = "definition_of_compared_word"
        # Distinguish bare lexical glosses from a translation of a Greek
        # example immediately before them. Morphology-labelled variants are
        # retained with their literal context, not generalized to the lemma.
        if reason is None and example_rule is not None:
            node_scope = _scope(node, entry)
            preceding = [n for n in nodes[:order[node]] if n.tag in
                         ({"foreign", "quote", "orth", "itype", "bibl", "cit", "sense"} | marked)
                         and spans[n][1] <= a
                         # Middle Liddell: only a Greek example inside the same
                         # <sense> can own a following translation; Latin
                         # cognates and etymology/form preambles cannot.
                         and not (example_rule == "sense_scoped" and n.tag in {"foreign", "quote"}
                                  and (_scope(n, entry) is not node_scope or not _is_greek(n)
                                       or any(x.tag in PREAMBLE for x in n.iterancestors())))
                         # Some flattened TEI senses start immediately after
                         # an example belonging to that sense, so a scope
                         # change alone is NOT a definition boundary. Only
                         # explicitly marked preamble morphology is skipped.
                         and not (_scope(n, entry) is not node_scope
                                  and n.tag == "foreign"
                                  and any(child.tag in {"itype", "gen", "gram", "gramGrp"}
                                          for child in n.iterdescendants()))]
            previous = max(preceding, key=lambda n: spans[n][1], default=None)
            if (previous is not None and previous.tag == "itype"
                    and _scope(previous, entry) is _scope(node, entry)
                    and _scope(node, entry) is not entry
                    and any(spans[n][1] <= spans[previous][0] for n in _scope(node, entry).iter("bibl"))):
                reason = "usage_complement_not_headword_definition"
            if previous is not None and previous.tag in {"foreign", "quote"}:
                gap = _plain(text[spans[previous][1]:a])
                lead = _plain(text[max(spans[_scope(node, entry)][0], spans[previous][0] - 100):spans[previous][0]])
                closed_comparison = any(start <= spans[previous][0] < end <= a
                                        and re.search(r"\bcf\.", text[start:spans[previous][0]], re.I)
                                        for start, end in parentheses)
                # A Greek variant in a completed editorial parenthesis is
                # not an immediately preceding example for a new definition.
                closed_note = any(start <= spans[previous][0] < spans[previous][1] <= end <= a
                                  and text[start] == "("
                                  and re.search(r"\b(?:marg\.|v\.l\.|var\.\s*lect\.)", text[start:end])
                                  and re.fullmatch(r"[\s,;:.\u2014\u2013]*", text[end:a])
                                  for start, end in parentheses)
                example_marker = re.search(r"\be\.?\s*g\.", lead, re.I)
                # An entry preamble may name the singular/plural counterpart
                # before the FIRST lexical sense (e.g. LSJ deute: "as pl. of
                # deuro, <sense><tr>come hither!</tr>"). That is an explicit
                # grammatical relation, not a Greek usage example. Require
                # both the source label and the structural entry boundary;
                # a new <sense> alone is not sufficient.
                grammatical_counterpart = (
                    previous.tag == "foreign" and _scope(previous, entry) is entry
                    and previous.getparent() is entry and node_scope is not entry
                    and not re.search(r"\be\.?\s*g\.",
                                      _plain(text[max(0, spans[previous][0] - 100):spans[previous][0]]), re.I)
                    and re.search(r"\b(?:as\s+)?(?:sg|pl|dual)\.\s+of\s*$",
                                  _plain(text[max(0, spans[previous][0] - 100):spans[previous][0]]), re.I)
                    and re.fullmatch(r"[\s,]*", gap)
                    and not any(n.tag in ({"bibl", "cit", "sense"} | marked)
                                for n in nodes[:order[previous]])
                )
                # "poet. for X, wild", "Adv. of X, with admiration": a Greek
                # word introduced by a reference marker is not an example.
                referenced = bool(fmt.get("reference_lead") and REFERENCE_LEAD.search(lead))
                if (not closed_comparison and not closed_note and not grammatical_counterpart
                        and not referenced and not DEFINITION_BOUNDARY.search(gap) and len(gap) < 60 and (example_marker or
                        (not GRAMMATICAL_LEAD.search(lead) and not re.search(r"\b(?:means|meaning|of)\s*$", gap)))):
                    reason = "translation_of_preceding_greek_example"
            # A translation split over multiple <tr>s is still an example.
            if previous is not None and previous.tag in marked:
                previous_exclusion = next((x for x in reversed(excluded)
                                           if x["source_locator"]["node_path"] == previous.getroottree().getpath(previous)), None)
                gap = _plain(text[spans[previous][1]:a])
                if (previous_exclusion and previous_exclusion["reason"] == "translation_of_preceding_greek_example"
                        and len(gap) < 45 and not DEFINITION_BOUNDARY.search(gap)):
                    reason = "translation_of_preceding_greek_example"
        if reason:
            excluded.append({"reason": reason, "source_locator": _locator(node, a, b)})
        else:
            # An English word continuing immediately after the emphasized
            # span is part of its phrase (e.g. <tr>free</tr> men), not a new
            # independent sense. Preserve that literal contiguous clause.
            continuation = re.match(r"\s+([A-Za-z][A-Za-z '\u2019-]*)(?=[,;:])", node.tail or "")
            if continuation and not re.match(r"(?:in|as|of|or|and|with|for|is|was|are|means|opp|esp|etc)\b", continuation.group(1), re.I):
                b += continuation.end(1)
            accepted.append(make(node, a, b, "explicit_definition_markup"))

    # A small explicit prose layout: interjection/exclamation descriptions
    # immediately after a headword. Stop before usage qualifiers or examples,
    # never mine arbitrary unmarked English prose as a definition.
    if first_orth is not None:
        start = spans[first_orth][1]
        next_node = next((n for n in entry if spans[n][0] >= start and n is not first_orth), None)
        end = spans[next_node][0] if next_node is not None else spans[entry][1]
        segment = text[start:end]
        match = re.match(r"\s*[:,]?\s*((?:interjection|exclamation)\s+(?:expressive\s+of|expressing)\s+.+?)(?=,\s*(?:freq\.|in\s)|$)", segment, re.I | re.S)
        if match:
            a, b = start + match.start(1), start + match.end(1)
            accepted.append(make(first_orth, a, b, "explicit_headword_prose_description", entry))
    accepted.sort(key=lambda r: r["source_locator"]["rendered_start"])
    # Typography often emphasizes separate parts of ONE definition, e.g.
    # <tr>turn</tr> one <tr>from</tr> his <tr>opinion, change</tr> his
    # <tr>mind</tr>. Join adjacent definition spans across plain English
    # connective text, retaining a single contiguous, reproducible source span.
    merged = []
    for row in accepted:
        if merged and fmt.get("merge_adjacent", True):
            prior = merged[-1]
            left, right = prior["source_locator"], row["source_locator"]
            gap = text[left["rendered_end"]:right["rendered_start"]]
            prior_node = entry.getroottree().xpath(left["node_path"])[0]
            current_node = entry.getroottree().xpath(right["node_path"])[0]
            if (prior_node.getparent() is current_node.getparent()
                    and prior["sense_path"] == row["sense_path"]
                    and 0 <= len(gap) < 100
                    and re.fullmatch(r"[\s,A-Za-z'\u2019-]*", gap)
                    and not re.search(r"\b(?:opp|except|not|rather)\b", gap, re.I)):
                prior["source_locator"]["rendered_end"] = right["rendered_end"]
                prior["text"] = _plain(text[left["rendered_start"]:right["rendered_end"]])
                prior.setdefault("component_node_paths", [left["node_path"]]).append(right["node_path"])
                prior["id"] = f"{record['id']}:{VERSION}:{left['node_path']}:{left['rendered_start']}:{right['rendered_end']}"
                scope_end = row["scope_locator"]["rendered_end"]
                prior["scope_locator"]["rendered_end"] = scope_end
                prior["scope_text"] = _plain(text[prior["scope_locator"]["rendered_start"]:scope_end])
                continue
        merged.append(row)
    accepted = merged
    _backward_tense_restrictions(entry, text, spans, accepted)
    # Crossreferences are evidence of a source relation, not definitions.
    # Do not follow targets here: equal Greek spellings can name separate
    # homographs (e.g. LSJ pa=s1 versus pa=s2). A lookup resolver must retain
    # this edge and independently resolve the exact dictionary target.
    crossreferences = []
    for xr in entry.iter("xr"):
        if any(a.tag in {"bibl", "cit", "quote", "etym"} for a in xr.iterancestors()):
            continue
        for ref in xr.iter("ref"):
            a, b = spans[ref]
            language = ref.get("lang") or ref.get("{http://www.w3.org/XML/1998/namespace}lang")
            if language not in {"greek", "grc"} or not GREEK.search(text[a:b]):
                continue
            scope = _scope(xr, entry)
            crossreferences.append({
                "lexicon_entry_id": record["id"], "entry_id": record["entry_id"],
                "target_text": _plain(text[a:b]),
                "target_key": _plain("".join(ref.itertext())),
                "target_key_encoding": "Perseus Beta Code",
                "relation_text": _plain(text[slice(*spans[xr])]),
                "source_locator": _locator(ref, a, b),
                "relation_locator": _locator(xr, *spans[xr]),
                "sense_path": _path(scope), "resolution_status": "unresolved",
                "source": record["source"], "source_url": record["source_url"],
                "raw_path": record["raw_path"], "raw_sha256": record["raw_sha256"],
                "extraction_method": VERSION,
            })
    return {"dictionary_senses": accepted,
            "dictionary_crossreferences": crossreferences,
            "dictionary_senses_status": "source_structured" if accepted else "no_safe_definition_spans",
            "dictionary_senses_excluded": excluded,
            "dictionary_senses_warning": None,
            "dictionary_senses_method": VERSION}


def _byte_range(record):
    if not source_format(record).get("located"):
        return (None, None)
    locator = record.get("locator") or {}
    return (locator.get("byte_start"), locator.get("byte_end"))


@lru_cache(maxsize=2048)
def _cached(raw_path, entry_id, record_id, source, source_url, digest, mtime_ns, size,
            byte_start=None, byte_end=None):
    path = _source_path(raw_path)
    if _raw_digest(path, mtime_ns, size) != digest:
        return {"dictionary_senses": [], "dictionary_senses_status": "source_hash_mismatch",
                "dictionary_senses_warning": "Archived dictionary source does not match its recorded SHA-256."}
    entry, entities = read_entry(raw_path, entry_id, {
        "source": source, "locator": {"byte_start": byte_start, "byte_end": byte_end}})
    after = path.stat()
    if (after.st_mtime_ns, after.st_size) != (mtime_ns, size):
        return {"dictionary_senses": [], "dictionary_senses_status": "source_changed_during_read",
                "dictionary_senses_warning": "Archived dictionary changed during extraction."}
    return _parse(entry, entities, {"raw_path": raw_path, "entry_id": entry_id,
                  "id": record_id, "source": source, "source_url": source_url,
                  "raw_sha256": digest})


def dictionary_senses(record: dict[str, Any]) -> dict[str, Any]:
    """Return literal safe spans or an explicit fail-closed status.

    This field is authoritative over the old flattened gloss for supported
    TEI dictionaries. Unsupported dictionaries keep their own source parser.
    """
    if record.get("source") not in SOURCES:
        return {}
    required = ("raw_path", "entry_id", "id", "source_url", "raw_sha256")
    if not all(record.get(k) for k in required):
        return {"dictionary_senses": [], "dictionary_senses_status": "missing_source_provenance",
                "dictionary_senses_warning": "Cannot verify dictionary definition source."}
    try:
        path = _source_path(record["raw_path"])
        stat = path.stat()
        return deepcopy(_cached(record["raw_path"], record["entry_id"], record["id"],
                                record["source"], record["source_url"], record["raw_sha256"],
                                stat.st_mtime_ns, stat.st_size,
                                *_byte_range(record)))
    except (OSError, KeyError, ValueError, etree.XMLSyntaxError) as exc:
        return {"dictionary_senses": [], "dictionary_senses_status": "source_unavailable",
                "dictionary_senses_warning": str(exc)}


__all__ = ["dictionary_senses", "VERSION"]
