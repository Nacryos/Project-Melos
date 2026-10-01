"""Preserve explicit grammatical disjunctions in source commentary quotes.

This expands printed grammar abbreviations only (the vocabulary used by
extract_p2_notes.py). It never supplies a missing feature, inherits features
between branches, creates a parse, or interprets ordinary lexical ``or``.
"""
from __future__ import annotations

from collections.abc import Mapping
import re


FEATURES = {
    'pres': ('tense', 'present'), 'aor': ('tense', 'aorist'),
    'imperf': ('tense', 'imperfect'), 'fut': ('tense', 'future'),
    'perf': ('tense', 'perfect'), 'act': ('voice', 'active'),
    'mid': ('voice', 'middle'), 'pass': ('voice', 'passive'),
    'ind': ('mood', 'indicative'), 'indic': ('mood', 'indicative'),
    'subj': ('mood', 'subjunctive'), 'opt': ('mood', 'optative'),
    'inf': ('mood', 'infinitive'), 'infin': ('mood', 'infinitive'),
    'imper': ('mood', 'imperative'), 'partic': ('mood', 'participle'),
    'ptc': ('mood', 'participle'), 'nom': ('case', 'nominative'),
    'gen': ('case', 'genitive'), 'dat': ('case', 'dative'),
    'acc': ('case', 'accusative'), 'voc': ('case', 'vocative'),
    'sg': ('number', 'singular'), 'pl': ('number', 'plural'),
    'masc': ('gender', 'masculine'), 'fem': ('gender', 'feminine'),
    'neut': ('gender', 'neuter'), '1st': ('person', 1),
    '2nd': ('person', 2), '3rd': ('person', 3),
}
# Full printed grammatical names express the same source annotation labels.
FEATURES.update({value: (key, value) for key, value in list(FEATURES.values())
                 if isinstance(value, str)})
TOKENS = re.compile(r'\w+|[^\w\s]', re.UNICODE)


def grammar_disjunctions(quote: str) -> list[dict]:
    """Return exact source spans of contiguous grammar-label ``or`` runs."""
    tokens = list(TOKENS.finditer(quote))
    result, index = [], 0
    while index < len(tokens):
        if tokens[index].group().casefold() not in FEATURES:
            index += 1
            continue
        start = index
        while index < len(tokens) and (tokens[index].group().casefold() in FEATURES
                or tokens[index].group().casefold() in {'or', 'a', 'an', '.', ','}):
            index += 1
        run = tokens[start:index]
        if not any(token.group().casefold() == 'or' for token in run):
            continue
        groups, current = [], []
        for token in run:
            if token.group().casefold() == 'or':
                groups.append(current)
                current = []
            else:
                current.append(token)
        groups.append(current)
        branches = []
        for group in groups:
            atoms = [token for token in group if token.group().casefold() in FEATURES]
            if not atoms:
                break
            lo, hi = atoms[0].start(), atoms[-1].end()
            if hi < len(quote) and quote[hi] == '.':
                hi += 1
            values = {}
            ambiguous_keys = set()
            for atom in atoms:
                key, value = FEATURES[atom.group().casefold()]
                if key in values and values[key] != value:
                    ambiguous_keys.add(key)
                values[key] = value
            # Conflicting labels within a branch are themselves unresolved;
            # never silently turn the last label into a feature value.
            for key in ambiguous_keys:
                values.pop(key, None)
            branches.append({'raw_label': quote[lo:hi], 'start': lo, 'end': hi,
                             'explicit_features': values,
                             'unresolved_feature_keys': sorted(ambiguous_keys)})
        if len(branches) != len(groups):
            continue
        lo, hi = branches[0]['start'], branches[-1]['end']
        result.append({'quote_start': lo, 'quote_end': hi,
                       'source_text': quote[lo:hi], 'branches': branches})
    return result


def _label_spans(raw: str, quote: str):
    if not isinstance(raw, str) or not raw.strip():
        return []
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in raw.split()) + r'(?!\w)'
    return [(match.start(), match.end()) for match in re.finditer(pattern, quote, re.I)]


def _same_evidence(left: Mapping, right: Mapping) -> bool:
    fields = ('record_id', 'source_url', 'raw_sha256', 'parent_sha256', 'quote', 'locator')
    return all(left.get(field) == right.get(field) for field in fields)


def _anchored_label_spans(obj: Mapping, quote: str):
    """An identical label elsewhere in prose is not a scope assignment."""
    spans = _label_spans(obj.get('raw_label'), quote)
    declared = obj.get('source_grammar_branch')
    if isinstance(declared, Mapping):
        start, end = declared.get('quote_start'), declared.get('quote_end')
        if type(start) is int and type(end) is int and (start, end) in spans:
            return [(start, end)]
        return []
    return spans if len(spans) == 1 else []


def _branch_represented(branch: dict, claim: Mapping, evidence: Mapping,
                        inventory: list[Mapping]) -> bool:
    for other in inventory:
        if (other.get('predicate') != 'morphology' or other.get('subject') != claim.get('subject')
                or other.get('status') != 'source_claim'
                or other.get('assertion_type') == 'model_inference'):
            continue
        obj = other.get('object')
        if not isinstance(obj, Mapping) or not isinstance(obj.get('features'), Mapping):
            continue
        if any(obj['features'].get(key) != value for key, value in branch['explicit_features'].items()):
            continue
        if branch['unresolved_feature_keys']:
            continue
        if not any(isinstance(item, Mapping) and _same_evidence(evidence, item)
                   for item in other.get('evidence') or []):
            continue
        # A short extracted prefix is not proof that omitted case/gender/etc.
        # were represented. Require the complete printed branch span.
        if (branch['start'], branch['end']) in _anchored_label_spans(obj, evidence['quote']):
            return True
    return False


def projection_qualification(claim: Mapping, inventory: list[Mapping]) -> dict:
    """Qualify an existing projection; leave accepted claims unmodified.

    Only a feature explicitly contradicted by an unrepresented source branch
    blocks selection. A shared partial label is retained as partial evidence.
    A complete, same-source candidate inventory remains available to models.
    """
    obj = claim.get('object')
    if claim.get('predicate') != 'morphology' or not isinstance(obj, Mapping):
        return {}
    features = obj.get('features')
    if not isinstance(features, Mapping) or not features or not isinstance(obj.get('raw_label'), str):
        return {}
    proofs, blocked = [], False
    for evidence_index, evidence in enumerate(claim.get('evidence') or []):
        if not isinstance(evidence, Mapping) or not isinstance(evidence.get('quote'), str):
            continue
        quote = evidence['quote']
        anchors = _anchored_label_spans(obj, quote)
        for disjunction in grammar_disjunctions(quote):
            if not any(disjunction['quote_start'] <= start < end <= disjunction['quote_end']
                       for start, end in anchors):
                continue
            complete = all(_branch_represented(branch, claim, evidence, inventory)
                           for branch in disjunction['branches'])
            conflicts = sorted({key for branch in disjunction['branches']
                                for key, value in branch['explicit_features'].items()
                                if key in features and features[key] != value})
            incomplete = bool(conflicts and not complete)
            blocked |= incomplete
            proofs.append({**disjunction, 'evidence_index': evidence_index,
                           'record_id': evidence.get('record_id'),
                           'source_url': evidence.get('source_url'),
                           'raw_sha256': evidence.get('raw_sha256'),
                           'conflicting_feature_keys': conflicts,
                           'complete_branch_inventory': complete})
    if not proofs:
        return {}
    status = ('incomplete_explicit_alternatives' if blocked else
              'explicit_alternatives_represented' if all(p['complete_branch_inventory'] for p in proofs)
              else 'partial_with_explicit_alternatives')
    return {'source_projection_status': status, 'source_grammar_alternatives': proofs,
            'source_projection_note': (
                'The source explicitly states grammatical alternatives not fully represented by this candidate inventory; a one-sided feature projection must not be selected.'
                if blocked else
                'The source explicitly states grammatical alternatives. This projection does not resolve them; missing or shared features must remain qualified.')}
