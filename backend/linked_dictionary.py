"""Compact, locally revalidated source-linked dictionary candidate paths.

Printed spelling links are not orthographic normalization or attestations.
Source-anchor tags and separately proved same-entry noun metadata supply
candidate morphology; target entries supply meanings, never source gender.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import sqlite3
from pathlib import Path

from .dictionary_crossrefs import lookup_crossreference_meanings
from .source_link_aliases import lookup_form_link_aliases
from .evidence import EvidenceIndex, DEFAULT_DB
from .noun_entry_features import lookup_noun_inherent_features, project_noun_inherent_features

VERSION = 'source-linked-dictionary-inventory-v2'
SOURCE_DB = Path(__file__).resolve().parents[1] / 'data/wiktionary.sqlite'
POS = {'noun': 'NOUN', 'adj': 'ADJ', 'adv': 'ADV', 'verb': 'VERB',
       'pron': 'PRON', 'prep': 'ADP', 'conj': 'CCONJ', 'particle': 'PART', 'article': 'DET'}
# Output-schema labels only; source gender strings/proofs remain unmodified.
NOUN_GENDER = {'masculine': 'Masc', 'feminine': 'Fem', 'neuter': 'Neut'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def compact_inventory(form, crossrefs, aliases, noun_metadata=None):
    """Project already verified helper results; not a public proof validator."""
    from .interlinear import canonical_features, compact_parse
    claims = {c['id']: c for block in (crossrefs, aliases) for c in block['supporting_claims']}
    alias_by_id = {r['id']: r for r in aliases['aliases']}
    relations = {r['id']: r for block in (crossrefs, aliases) for r in block['relations']}
    verified_metadata = {}
    for entry_id, supplied in (noun_metadata or {}).items():
        if not isinstance(supplied, dict) or supplied.get('entry_id') != entry_id:
            continue
        replayed = project_noun_inherent_features(entry_id, supplied.get('supporting_claims', []),
                                                 supplied.get('supporting_source_records', []))
        if replayed == supplied and replayed.get('dictionary_pos') == 'noun':
            verified_metadata[entry_id] = replayed
    paths = []
    for raw in [*crossrefs['candidates'], *aliases['meaning_candidates']]:
        alias = alias_by_id.get(raw.get('alias_id'))
        anchors = ([{'source_form': alias['matched_object_form'], 'claim_id': alias['claim_ids'][1],
                     'source_locator': alias['source_locator']}] if alias else raw['query_anchors'])
        for anchor in anchors:
            source_pos = alias['dictionary_pos'] if alias else raw['source_dictionary_pos']
            source_lemma = alias['entry_headword'] if alias else raw['source_headword']
            target_head = claims.get(raw['target_entry_id'] + ':lemma:entry') or {}
            target_pos = (target_head.get('object') or {}).get('pos')
            relation = relations.get(raw.get('relation_id')) or {}
            relation_context = {k: deepcopy(v) for k, v in relation.items() if k in {
                'relation', 'relation_text', 'source_display', 'source_link', 'target_link',
                'target_identity_status', 'target_entry_ids', 'resolution_status', 'target_headword'}}
            grammar = {'source_tags': deepcopy(anchor['source_form'].get('tags') or []),
                       'upos': POS.get(source_pos)}
            features = canonical_features(grammar)
            noun = verified_metadata.get(raw['source_entry_id']) if source_pos == 'noun' else None
            metadata_view = None
            if noun and noun.get('entry_headword') == source_lemma:
                explicit_gender = features.get('Gender')
                entry_gender = noun.get('unambiguous_entry_gender')
                applied = not explicit_gender and noun.get('gender_status') == 'single_source_gender' and entry_gender in NOUN_GENDER
                if applied:
                    features = {**features, 'Gender': NOUN_GENDER[entry_gender]}
                source_head = next((c for c in noun['supporting_claims']
                                    if c['id'] == raw['source_entry_id'] + ':lemma:entry'), None)
                metadata_view = {k: deepcopy(noun.get(k)) for k in (
                    'entry_id', 'entry_headword', 'dictionary_pos', 'source_etymology_number', 'method',
                    'gender_status', 'dictionary_gender_options', 'unambiguous_entry_gender', 'evidence_groups',
                    'paradigm_gender_conflicts', 'gender_covered_sense_indices', 'source_sense_count', 'scope')}
                metadata_view.update(applied_to_candidate=bool(applied),
                    explicit_form_gender=explicit_gender,
                    application_basis='same_anchor_noun_metadata' if applied else
                                      'explicit_form_gender_preserved' if explicit_gender else 'metadata_not_unique_or_complete',
                    supporting_claim_ids=[c['id'] for c in noun['supporting_claims']],
                    source_record_proof=deepcopy(source_head['evidence'][0]) if source_head else None,
                    contextually_selected=False)
            path = {'source_entry_id': raw['source_entry_id'], 'source_headword': source_lemma,
                    'target_entry_id': raw['target_entry_id'], 'target_headword': raw['target_headword'],
                    'target_etymology_number': raw.get('target_etymology_number'),
                    'relation_id': raw.get('relation_id'),
                    'query_anchor': deepcopy(anchor), 'source_dictionary_pos': source_pos,
                    'target_dictionary_pos': target_pos, 'literal_pos_agreement': source_pos == target_pos,
                    'relation_context': relation_context,
                    'match_method': 'literal_source_form_link' if alias else 'exact_source_form_crossreference',
                    'claim_ids': [c for c in raw['claim_ids'] if c != raw['sense']['claim_id']]}
            if metadata_view is not None:
                path['source_noun_metadata'] = metadata_view
            if alias:
                path.update(alias_id=alias['id'], source_link=deepcopy(alias['source_link']),
                            printed_form=alias['printed_form'])
            identifier = 'linked-path:' + _digest(path)
            claim = claims[raw['sense']['claim_id']]
            proof = claim['evidence'][0]
            senses = []
            lexical_path = {key: path[key] for key in ('source_entry_id', 'source_headword', 'target_entry_id',
                           'target_headword', 'target_etymology_number', 'relation_id',
                           'source_dictionary_pos', 'target_dictionary_pos', 'literal_pos_agreement', 'relation_context')}
            lexical_path['sense_claim_id'] = raw['sense']['claim_id']
            # Kaikki stores the hierarchical gloss chain on each sense; the
            # final literal string is its leaf, not a generated paraphrase.
            # Every distinct source sense remains a choice, and its entire
            # chain remains scope_text for contextual interpretation.
            for ordinal, text in enumerate(raw['sense']['glosses'][-1:]):
                if not isinstance(text, str) or not text.strip():
                    continue
                senses.append({'id': 'linked-sense:' + _digest(lexical_path), 'entry_id': raw['target_entry_id'],
                    'lexicon_entry_id': raw['target_entry_id'], 'text': text, 'language': 'eng',
                    'evidence_type': 'dictionary_sense', 'source': claim['source_family'],
                    'source_url': proof['source_url'], 'source_locator': raw['sense']['locator'],
                    'raw_sha256': proof['raw_sha256'], 'qualifiers': deepcopy(raw['sense'].get('tags') or []),
                    'scope_text': deepcopy(raw['sense']['glosses']), 'linked_path': lexical_path})
            existing = next((r for r in paths if r['id'] == identifier), None)
            if existing:
                existing['senses'].extend(s for s in senses if s not in existing['senses'])
                continue
            paths.append({'id': identifier, 'candidate_id': identifier, 'lemma': source_lemma,
                          'features': features, 'parse_short': compact_parse(features),
                          'basis': 'source_linked_dictionary_path', 'linked_path': path,
                          'gloss_entry_id': raw['target_entry_id'], 'senses': senses})
    payload = {'form': form, 'method': VERSION, 'candidates': paths,
               'retrieval_scope': crossrefs.get('source_retrieval_scope'),
               'scope': 'source_linked_candidates_not_exact_surface_or_contextual_attestation'}
    payload['inventory_sha256'] = _digest(payload)
    return payload


def _stamp(path):
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (str(p), None, None)
                 for p in (Path(path), Path(str(path) + '-wal')))


@lru_cache(maxsize=4096)  # release U: 128 forms were evicted by a 600-word warm-up
def _lookup(form, evidence_path, source_path, stamps):
    index = EvidenceIndex(evidence_path)
    crossrefs = lookup_crossreference_meanings(form, index, source_path)
    aliases = lookup_form_link_aliases(form, index, source_path)
    source_entries = {r['source_entry_id'] for r in crossrefs['candidates'] if r['source_dictionary_pos'] == 'noun'}
    source_entries.update(r['entry_id'] for r in aliases['aliases'] if r['dictionary_pos'] == 'noun')
    metadata = {entry_id: lookup_noun_inherent_features(entry_id, index, source_path)
                for entry_id in sorted(source_entries)}
    return compact_inventory(form, crossrefs, aliases, metadata)


def lookup_linked_dictionary(form, evidence_index=None, source_index_path=None):
    evidence_path = str((evidence_index.db_path if evidence_index else DEFAULT_DB).resolve())
    source_path = str(Path(source_index_path or SOURCE_DB).resolve())
    return deepcopy(_lookup(form, evidence_path, source_path, (_stamp(evidence_path), _stamp(source_path), VERSION)))


def validated_candidates(token):
    """A caller-supplied digest is never authority: rebuild from local sources."""
    supplied = token.get('linked_dictionary')
    if not supplied or token.get('partial_word') or token.get('editorial_fragment'):
        return []
    try:
        expected = lookup_linked_dictionary(token.get('form') or token['text'])
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        return []
    return expected['candidates'] if supplied == expected else []
