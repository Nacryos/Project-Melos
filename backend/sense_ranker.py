"""Optional, occurrence-bound selection of literal dictionary senses.

This is a distinct interpretive operation from morphological classification.
Only server-extracted sense identifiers are choices; definitions are never
generated. The injected provider is the existing durable, budgeted Jev gateway.
"""
from copy import deepcopy
import hashlib
import json
import math
import os

from .interlinear import gloss_from_sense, interlinear_reading, sense_form_compatible
from .jev_gateway import GatewayLimit, GatewayUnavailable
from .passage_ranker import _syntax_context, _translations
from .translation_languages import is_english_language
from .edition_commentary import (DATA_SHA256 as CAMPBELL_COMMENTARY_SHA256,
                                 compact_model_context, for_passage as edition_commentary_for_passage)

SCHEMA = 'melos-contextual-dictionary-sense-v2'
MAX_TOKEN_OCCURRENCES = 3
MAX_SENSE_CHOICES = 254  # Jev has 255 choice slots including abstain.
MAX_MORPHOLOGY_ALTERNATIVES = 32  # Distinct from the sense-choice ceiling.
SHORT_CHOICE_THRESHOLD = 10
# These are conservative *character* ceilings for our complete JSON request,
# not Jev token counts. Jev applies its own 32k state+question / 64k total token
# limits; without its tokenizer we must not claim a local token guarantee.
MAX_SENSE_STATE_CHARS = 64000
MAX_SENSE_STATE_QUESTION_PROXY_CHARS = 96000
MAX_SENSE_REQUEST_PROXY_CHARS = 128000


class CommentaryContextUnavailable(ValueError):
    """A requested Campbell poem no longer matches the approved sidecar."""


def _inventory(token):
    """Union literal senses across exact alternatives without selecting a parse."""
    senses, support, candidate_payloads = {}, {}, {}
    for candidate in token.get('candidate_meanings') or []:
        identifier = candidate.get('candidate_id')
        if not identifier:
            continue
        if identifier in candidate_payloads and candidate_payloads[identifier] != candidate:
            raise ValueError('Conflicting morphology payloads share a candidate ID.')
        candidate_payloads[identifier] = candidate
        for sense in (candidate.get('gloss') or {}).get('alternatives') or []:
            if not _valid_sense(sense):
                raise ValueError('Incomplete sourced sense payload.')
            key = sense['id']
            if key in senses and senses[key] != sense:
                raise ValueError('Conflicting source payloads share a sense ID.')
            senses[key] = deepcopy(sense)
            support.setdefault(key, [])
            if identifier not in support[key]:
                support[key].append(identifier)
    return [{**sense, 'supporting_candidate_ids': support[key]} for key, sense in senses.items()]


def _inventory_digest(result, token, senses):
    return hashlib.sha256(json.dumps({'passage': result.get('passage'),
        'selection': result.get('selection'), 'token_id': token.get('token_id'),
        'start': token.get('start'), 'end': token.get('end'), 'senses': senses,
        'morphology_inventory': token.get('candidate_meanings'),
        'selected_morphology': token.get('source_candidate')},
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _valid_sense(sense):
    return (isinstance(sense, dict) and isinstance(sense.get('id'), str)
            and sense['id'] and isinstance(sense.get('text'), str) and sense['text'].strip()
            and sense.get('entry_id') and sense.get('evidence_type') == 'dictionary_sense'
            and is_english_language(sense.get('language'))
            and sense.get('source_url') and sense.get('source_locator')
            and isinstance(sense.get('raw_sha256'), str) and len(sense['raw_sha256']) == 64)


def _bounded_syntax(result, token):
    syntax = _syntax_context(result)
    rows = syntax.get('tokens') or []
    targets = [row for row in rows if row.get('absolute_start') == token.get('start')
               and row.get('absolute_end') == token.get('end')]
    ids = {(row.get('sentence_id'), row.get('id')) for row in targets}
    heads = {(row.get('sentence_id'), row.get('head')) for row in targets}
    neighbours = [row for row in rows if (row.get('sentence_id'), row.get('id')) in ids | heads
                  or (row.get('sentence_id'), row.get('head')) in ids]
    kept = neighbours[:12]
    return {**syntax, 'tokens': kept, 'scope': 'target_dependency_neighbourhood',
            'original_scope': syntax.get('scope'), 'omitted_token_predictions': len(rows) - len(kept),
            'scope_note': 'Fallible target/head/direct-dependent predictions only, capped at twelve rows; the full source Greek remains in passage.text. Not source annotations.'}


def _compact_evidence(packet):
    """Share semantic evidence; full extraction coordinates stay server-side."""
    catalog = {}
    source_contexts = {}
    context_keys, evidence_keys = {}, {}
    candidate_bindings = {}
    candidates = packet['candidates']
    for candidate in candidates:
        # Extraction file paths/coordinate encodings do not help classify a
        # meaning. The original inventory digest binds all of them server-side.
        for key in ('raw_path', 'scope_locator', 'source_locator', 'extraction_method'):
            candidate.pop(key, None)
        if isinstance(candidate.get('citations'), list):
            candidate['citations'] = [{key: deepcopy(value) for key, value in citation.items()
                                      if key != 'source_locator'} if isinstance(citation, dict) else deepcopy(citation)
                                     for citation in candidate['citations']]
        candidate.pop('gloss', None)  # exact duplicate of the literal text field
        support = candidate.pop('supporting_candidate_ids')
        binding = next((key for key, value in candidate_bindings.items() if value == support), None)
        if binding is None:
            binding = 'binding-' + str(len(candidate_bindings) + 1)
            candidate_bindings[binding] = support
        candidate['supporting_candidates_ref'] = binding
        context = {key: candidate.pop(key) for key in ('source', 'source_url', 'raw_sha256', 'language', 'evidence_type',
                   'definition_kind', 'form_scope', 'qualifier_scope', 'citation_scope') if key in candidate}
        encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        reference = context_keys.setdefault(encoded, 'ctx-' + str(len(context_keys) + 1))
        source_contexts[reference] = context
        candidate['source_context_ref'] = reference
    for candidate in candidates:
        for key in ('citations', 'qualifiers', 'scope_text', 'sense_path'):
            value = candidate.get(key)
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if len(encoded) <= 160 or sum(other.get(key) == value for other in candidates) < 2:
                continue
            reference = evidence_keys.setdefault(encoded, 'ev-' + str(len(evidence_keys) + 1))
            catalog[reference] = deepcopy(value)
            candidate.pop(key)
            candidate[key + '_ref'] = reference
    # Linked sense IDs differ while their source→target relation is often
    # identical. Share that literal context, never drop competing anchors or
    # source restrictions. Full paths remain in the server-bound inventory.
    for row in [*candidates, *packet.get('morphology_alternatives', [])]:
        path = row.get('linked_path')
        if not isinstance(path, dict):
            continue
        noun_metadata = path.pop('source_noun_metadata', None)
        if noun_metadata is not None:
            encoded = json.dumps(noun_metadata, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            reference = evidence_keys.setdefault(encoded, 'ev-' + str(len(evidence_keys) + 1))
            catalog[reference] = deepcopy(noun_metadata)
            path['source_noun_metadata_ref'] = reference
        common = {key: path.pop(key) for key in (
            'source_entry_id', 'source_headword', 'target_entry_id', 'target_headword',
            'target_etymology_number', 'relation_id', 'source_dictionary_pos',
            'target_dictionary_pos', 'literal_pos_agreement', 'relation_context') if key in path}
        encoded = json.dumps(common, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        reference = evidence_keys.setdefault(encoded, 'ev-' + str(len(evidence_keys) + 1))
        catalog[reference] = common
        path['context_ref'] = reference
    packet['shared_source_evidence'] = catalog
    packet['source_contexts'] = source_contexts
    packet['candidate_bindings'] = candidate_bindings
    packet['constraints'].append('supporting_candidates_ref resolves in candidate_bindings; source_context_ref resolves in source_contexts; other _ref fields resolve in shared_source_evidence. All sense choices, source restrictions and citation texts/references are retained. Extraction coordinates remain server-side bound by inventory_sha256.')
    if any(row.get('linked_path') for row in candidates):
        packet['constraints'].append('linked_path.context_ref supplies shared source/target/relation fields from shared_source_evidence; merge them with the remaining path fields. Source grammar never inherits target POS or gender.')


def _hoist_common_commentary_candidate_fields(packet):
    """Factor identical sense metadata only in the Campbell-enriched packet.

    Every choice retains its ID, literal sense text, restrictions, and unique
    scope. The hoisted fields apply to *each* choice and can be reconstructed
    exactly; no candidate or supporting proof is removed.
    """
    candidates = packet['candidates']
    if len(candidates) < 2:
        return
    common = {}
    for field in ('candidate_kind', 'entry_id', 'lexicon_entry_id', 'source_context_ref'):
        if all(field in row and row[field] == candidates[0][field] for row in candidates):
            common[field] = deepcopy(candidates[0][field])
    if common:
        for row in candidates:
            for field in common:
                del row[field]
        packet['candidate_common_fields'] = common
        packet['constraints'].append('candidate_common_fields applies unchanged to every listed candidate.')


def add_context_relevance(packet, passage, target, *, commentary=None):
    """Add source retrieval guidance without changing any candidate inventory.

    This also supports frozen-packet experiments: the only changed fields are
    preview metadata, source retrieval cues and explicit interpretation rules.
    """
    occurrence = packet.get('target_occurrence') or {}
    source_passage = packet.get('passage') or {}
    if (any(source_passage.get(key) != passage.get(key) for key in ('id', 'text'))
            or any(occurrence.get(key) != target.get(key) for key in ('text', 'start', 'end'))):
        raise ValueError('Context relevance target differs from the source packet occurrence.')
    cues = None
    if commentary is not None:
        # A frozen experiment cannot attach cues from another source view.
        source_view = compact_model_context(commentary)
        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if canonical(packet.get('published_commentary_context')) != canonical(source_view):
            raise ValueError('Commentary view differs from the supplied source context.')
        from .commentary_retrieval import retrieval_cues
        cues = retrieval_cues(passage, target, commentary=commentary)
        if not cues or cues.get('status') != 'available':
            raise CommentaryContextUnavailable('Approved commentary retrieval source or occurrence is unavailable.')
    preview = packet.get('selected_morphology')
    if preview is not None:
        preview.update(presentation_role='current_heuristic_preview',
                       selection_is_source_adjudication=False,
                       constrains_sense_candidates=False)
    packet['constraints'].append(
        'selected_morphology is the current heuristic preview, not independent source adjudication or a constraint on sense choices. Do not prefer a candidate merely because this preview selected it; consider every supplied source path and its evidence.')
    if commentary is not None:
        packet['commentary_retrieval_cues'] = cues
        packet['constraints'].append(
            'commentary_retrieval_cues identifies literal printed headings matching the target or nearby words. Consult the referenced paragraph ordinals in published_commentary_context. Neighbor headings concern those other words, not automatically the target; contiguous printed note groups preserve continuations but do not establish occurrence alignment, attestation, or a selected sense. Keep all source alternatives and the complete commentary.')


def _shorten_choice_ids(packet):
    """Use small wire choices while retaining every source sense ID once.

    The immutable server-side inventory hash still binds the full originals.
    The mapping is model-visible so short IDs never conflate source records.
    """
    if len(packet['candidates']) < SHORT_CHOICE_THRESHOLD:
        return
    mapping = {}
    for index, candidate in enumerate(packet['candidates'], 1):
        wire_id = f's{index}'
        mapping[wire_id] = candidate['id']
        candidate['id'] = wire_id
    packet['source_choice_ids'] = mapping
    packet['constraints'].append('Choose a short candidate ID from candidates; source_choice_ids maps each one to its exact original source sense ID. No source senses were merged or removed.')


def _request_size_proxy(packet):
    """Upper-envelope JSON character estimate including Jev's choice question.

    A Jev choice description projects fields from each full candidate; using
    the entire candidate here safely overcounts that projection. The per-choice
    allowance covers the candidate ID, evidence instruction and JSON keys;
    the fixed allowance covers model, question instructions and abstention.
    An offline test compares this envelope with the actual intercepted body.
    """
    encoded = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str))
    state = encoded(packet)
    question = sum(encoded(candidate) + 256 for candidate in packet['candidates']) + 4096
    return state, state + question, state + question + 256


def sense_packet(passage, result, token):
    """Validate all identity boundaries before any paid work; never trim options."""
    text = passage.get('text')
    metadata = result.get('passage') or {}
    selection = result.get('selection') or {}
    start, end = token.get('start'), token.get('end')
    a, b = selection.get('start'), selection.get('end')
    if (not isinstance(text, str) or passage.get('id') != metadata.get('id')
            or hashlib.sha256(text.encode()).hexdigest() != metadata.get('text_sha256')
            or any(type(value) is not int for value in (start, end, a, b))
            or not 0 <= a <= start < end <= b <= len(text)
            or text[start:end] != token.get('text') or text[a:b] != selection.get('text')):
        raise ValueError('Source occurrence identity changed.')
    # Rebuild from the server's original occurrence inventory. The interlinear
    # payload is a view, not authority for adding senses or swapping entries.
    trusted = next((row for row in interlinear_reading(result)['readings'][0]['tokens']
                    if row.get('token_id') == token.get('token_id')), None)
    if trusted is None or any(trusted.get(key) != token.get(key) for key in (
            'text', 'start', 'end', 'source_candidate', 'candidate_id', 'lemma', 'features', 'selection_basis',
            'gloss', 'candidate_meanings')):
        raise ValueError('Selected morphology differs from the original occurrence inventory.')
    senses = _inventory(trusted)
    if (not senses or len(senses) > MAX_SENSE_CHOICES
            or len(trusted.get('candidate_meanings') or []) > MAX_MORPHOLOGY_ALTERNATIVES
            or not all(_valid_sense(sense) for sense in senses)
            or len({sense['id'] for sense in senses}) != len(senses)):
        raise ValueError('Complete sourced sense inventory is unavailable or exceeds safe bounds.')
    packet = {'task_schema': SCHEMA, 'task': 'contextual_dictionary_sense',
        'passage': {key: deepcopy(passage.get(key)) for key in ('id', 'text', 'language', 'author', 'work', 'citation', 'source_url')},
        'target_occurrence': {key: deepcopy(token.get(key)) for key in ('token_id', 'text', 'start', 'end')},
        'selected_span': deepcopy(selection),
        'selected_morphology': ({key: deepcopy(token.get(key)) for key in ('candidate_id', 'lemma', 'features', 'parse_short', 'selection_basis')}
                                if token.get('candidate_id') else None),
        'morphology_alternatives': [{key: deepcopy(row.get(key)) for key in ('candidate_id', 'lemma', 'features', 'basis', 'linked_path') if row.get(key) is not None}
                                    for row in trusted.get('candidate_meanings') or []],
        'inventory_sha256': _inventory_digest(result, trusted, senses),
        'candidates': [{**deepcopy(sense), 'candidate_kind': 'dictionary_sense', 'gloss': sense['text']} for sense in senses],
        'published_translation_context': _translations(passage),
        'predicted_syntax_context': _bounded_syntax(result, token),
        'constraints': [
            'Choose only a supplied literal dictionary sense ID or abstain. Never generate, rewrite, inflect, or complete a definition.',
            'Classify this exact token occurrence using only supplied exact-entry senses and supporting morphology candidate IDs. Morphology may remain unresolved. A sense selection does not select a case, number, tense, or complete parse. If the inventory is inadequate, abstain.',
            'Dictionary scope, qualifications, examples, and explicit variant forms restrict meanings; an example translation need not be a general headword definition.',
            'Respect qualifier_scope and citation_scope: containing-source-sense notes and citations are not necessarily attached to each individual definition, and do not establish dialect exclusivity.',
            'Author, translation, and predicted syntax are defeasible context, never independent proof of a sense. Do not infer dialect exclusivity from author identity.',
            'When several near-synonymous source senses fit equally well, abstain rather than overstate confidence. The listed order is not a contextual ranking.'
        ]}
    if any(row.get('linked_path') for row in trusted.get('candidate_meanings') or []):
        packet['constraints'].append('Source-linked dictionary paths are explicit page/form links, not exact printed-spelling matches or occurrence attestations. Source-anchor grammar is separate from target-entry meanings; target homonyms and source/target POS disagreements remain alternatives. A predicted or currently selected morphology must not veto a competing sourced path. Selecting a linked sense does not select its full parse.')
    commentary = edition_commentary_for_passage(passage, for_model=True)
    if commentary is not None:
        if commentary.get('status') != 'available':
            raise CommentaryContextUnavailable('Approved Campbell commentary is unavailable or source identity changed.')
        packet['published_commentary_context'] = compact_model_context(commentary)
        packet['commentary_data_sha256'] = CAMPBELL_COMMENTARY_SHA256
        packet['commentary_context_sha256'] = hashlib.sha256(json.dumps(
            commentary, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        packet['constraints'].append(
            'Use these notes as fallible whole-poem context. Do not assert exact occurrence alignment from their placement. Choose a supplied sense when the combined evidence supports it; otherwise abstain.')
    if os.environ.get('MELOS_COMMENTARY_RELEVANCE') == '1':
        # Experimental retrieval cues (tested 2026-10-07 without improvement);
        # off by default so production packets stay within the model bound.
        add_context_relevance(packet, passage, token, commentary=commentary)
    _compact_evidence(packet)
    if commentary is not None:
        _hoist_common_commentary_candidate_fields(packet)
    _shorten_choice_ids(packet)
    state_chars, combined_chars, request_chars = _request_size_proxy(packet)
    if (state_chars > MAX_SENSE_STATE_CHARS
            or combined_chars > MAX_SENSE_STATE_QUESTION_PROXY_CHARS
            or request_chars > MAX_SENSE_REQUEST_PROXY_CHARS):
        raise ValueError('Complete sense evidence exceeds safe bounds; no options were dropped.')
    return packet


class PassageSenseRanker:
    def __init__(self, passage_lookup, provider_factory):
        self.passage_lookup = passage_lookup
        self.provider_factory = provider_factory

    def __call__(self, result, *, visitor_id=None):
        output = {'status': 'not_available', 'provider': 'TypeSafe Jev',
                  'max_token_occurrences': MAX_TOKEN_OCCURRENCES, 'attempted_occurrences': 0, 'items': [],
                  'warnings': ['Dictionary sense ranking is conditional on supplied exact morphology alternatives, not necessarily one resolved parse. Model probabilities are uncalibrated; literal source alternatives remain available.']}
        readings = (result.get('interlinear') or {}).get('readings') or []
        # Do not imply that we have scored distinct joint constructions.
        if len(readings) != 1:
            return output
        try:
            passage = self.passage_lookup((result.get('passage') or {}).get('id'))
        except Exception:
            return output
        pending = []
        for token in readings[0].get('tokens') or []:
            if token.get('kind') != 'word':
                continue
            item = {'token_id': token.get('token_id'), 'status': 'not_available', 'selected_sense_id': None, 'ranked_senses': []}
            output['items'].append(item)
            try:
                packet = sense_packet(passage, result, token)
            except CommentaryContextUnavailable:
                item['reason'] = 'Approved whole-poem commentary is unavailable or changed; no sense model request was made.'
                continue
            except (ValueError, TypeError, KeyError) as exc:
                item['reason'] = ('Complete sense and commentary evidence exceeds the safe packet bound; no model request was made.'
                                  if 'exceeds safe bounds' in str(exc) else
                                  'No complete, exact-lemma sourced sense inventory is available for this occurrence.')
                continue
            item['inventory_sha256'] = packet['inventory_sha256']
            if len(packet['candidates']) == 1:
                item.update(status='single_dictionary_sense', reason='Only one extracted source sense is available; no contextual model comparison was made.')
                continue
            pending.append((token, item, packet))
        if not pending:
            return output
        try:
            provider = self.provider_factory(visitor_id)
            if provider is None:
                raise GatewayUnavailable('Jev not configured.')
        except Exception:
            output['status'] = 'unavailable'
            return output
        blocked = None
        for token, item, packet in pending:
            if blocked:
                item.update(status=blocked, reason='Further sense comparisons stopped after a gateway failure or limit.')
                continue
            if output['attempted_occurrences'] >= MAX_TOKEN_OCCURRENCES:
                item.update(status='request_limit', reason='At most three word-sense comparisons run per explicit selection.')
                continue
            output['attempted_occurrences'] += 1
            try:
                answer = provider.decide(packet)
                if not isinstance(answer, dict) or not answer.get('model'):
                    raise GatewayUnavailable('Invalid answer.')
                choices = {sense['id']: sense for sense in _inventory(token)}
                wire_to_source = packet.get('source_choice_ids') or {identifier: identifier for identifier in choices}
                wire_choice = answer.get('choice')
                if wire_choice not in {*wire_to_source, 'abstain'}:
                    raise GatewayUnavailable('Invalid choice.')
                choice = 'abstain' if wire_choice == 'abstain' else wire_to_source[wire_choice]
                raw = answer.get('model_probabilities')
                probabilities = {('abstain' if identifier == 'abstain' else wire_to_source[identifier]): score
                                 for identifier, score in (raw.items() if isinstance(raw, dict) else [])
                                 if identifier in {*wire_to_source, 'abstain'} and type(score) in (int, float)
                                 and math.isfinite(score) and 0 <= score <= 1}
                item.update(status='abstained' if choice == 'abstain' else 'uncertain', model=answer['model'],
                            model_probabilities_uncalibrated=probabilities, cache_hit=bool(answer.get('cache_hit')),
                            usage=deepcopy(answer.get('usage')), proposed_sense_id=None if choice == 'abstain' else choice,
                            ranked_senses=sorted([{'sense_id': identifier, 'score_uncalibrated': probabilities.get(identifier)} for identifier in choices],
                                                 key=lambda row: (row['score_uncalibrated'] is None, -(row['score_uncalibrated'] or 0))))
                # Require the complete score vector, including abstention, so
                # an omitted competitor cannot produce a false margin.
                complete = (isinstance(raw, dict) and set(raw) == {*wire_to_source, 'abstain'}
                            and set(probabilities) == {*choices, 'abstain'})
                score = probabilities.get(choice, 0)
                margin = score - max([value for key, value in probabilities.items() if key != choice] or [0])
                if choice != 'abstain' and complete and score >= .75 and margin >= .2 and sense_form_compatible(choices[choice], token):
                    item.update(status='proposed', selected_sense_id=choice,
                                supporting_candidate_ids=deepcopy(choices[choice]['supporting_candidate_ids']))
                else:
                    item['reason'] = 'No decisive contextual sense proposal; the dictionary-order preview is unchanged.'
            except GatewayLimit as exc:
                blocked = 'rate_limited'; item.update(status=blocked, retry_after=exc.retry_after)
            except Exception:
                blocked = 'unavailable'; item.update(status=blocked, reason='Sense comparison could not complete; source definitions are unchanged.')
        output['status'] = 'complete' if all(row.get('model') for _, row, _ in pending) else 'partial' if any(row.get('model') for _, row, _ in pending) else blocked or 'not_available'
        return output


def apply_sense_ranking(interlinear, ranking, *, source_result=None):
    """Select source payload by exact ID, never use model-provided wording."""
    if source_result is None:
        return
    trusted_tokens = {row.get('token_id'): row for reading in interlinear_reading(source_result).get('readings') or []
                      for row in reading.get('tokens') or []}
    by_token = {row.get('token_id'): row for row in ranking.get('items') or []}
    for reading in interlinear.get('readings') or []:
        for token in reading.get('tokens') or []:
            for field in ('ranked_sense_alternatives', 'sense_ranking_status', 'sense_ranking_inventory_sha256'):
                token.pop(field, None)
            decision = by_token.get(token.get('token_id')) or {}
            if decision.get('status') not in {'proposed', 'uncertain', 'abstained'}:
                continue
            trusted = trusted_tokens.get(token.get('token_id'))
            if not trusted or any(token.get(key) != trusted.get(key) for key in ('text', 'start', 'end', 'candidate_id', 'source_candidate', 'candidate_meanings')):
                continue
            try:
                alternatives = _inventory(trusted)
            except ValueError:
                continue
            if decision.get('inventory_sha256') != _inventory_digest(source_result, trusted, alternatives):
                continue
            chosen = next((sense for sense in alternatives if sense.get('id') == decision.get('selected_sense_id')), None)
            probabilities = decision.get('model_probabilities_uncalibrated') or {}
            expected = {sense['id'] for sense in alternatives} | {'abstain'}
            if (set(probabilities) != expected or not all(type(value) in (int, float) and math.isfinite(value)
                    and 0 <= value <= 1 for value in probabilities.values())):
                continue
            # A non-decisive ranking can be useful without becoming a selected
            # meaning. Rebuild every label/proof from the original inventory,
            # never from the model or the lightweight ranked_senses response.
            token['ranked_sense_alternatives'] = sorted(
                [{**deepcopy(sense), 'score_uncalibrated': probabilities[sense['id']]}
                 for sense in alternatives], key=lambda row: -row['score_uncalibrated'])
            token['sense_ranking_status'] = 'uncertain' if decision['status'] == 'proposed' else decision['status']
            token['sense_ranking_inventory_sha256'] = decision['inventory_sha256']
            if decision['status'] != 'proposed':
                continue
            score = probabilities.get(decision.get('selected_sense_id'), 0)
            margin = score - max([value for key, value in probabilities.items() if key != decision.get('selected_sense_id')] or [0])
            if (chosen and score >= .75 and margin >= .2 and sense_form_compatible(chosen, token)
                    and decision.get('supporting_candidate_ids') == chosen['supporting_candidate_ids']):
                if token.get('candidate_id') not in chosen['supporting_candidate_ids'] and (
                        token.get('candidate_id') or chosen.get('linked_path')):
                    # Do not display one lemma's meaning underneath another
                    # lemma's selected parse. Keep the proposal in ranking.
                    if not chosen.get('linked_path'):
                        continue
                    # A sourced linked meaning can challenge a statistical
                    # parse, but cannot make its own full parse true. Remove
                    # the incompatible presentation, not the raw alternatives.
                    token.update(candidate_id=None, source_candidate=None, lemma=None,
                                 features={}, parse_short='', agreement_group_id=None,
                                 selection_basis='linked_sense_morphology_unresolved', status='ambiguous')
                    token.pop('supporting_parse_candidate_ids', None)
                    affected = {group['id'] for group in reading.get('groups') or []
                                if token['token_id'] in group.get('token_ids', [])}
                    reading['groups'] = [group for group in reading.get('groups') or [] if group['id'] not in affected]
                    for other in reading.get('tokens') or []:
                        if other.get('agreement_group_id') in affected:
                            other['agreement_group_id'] = None
                token['gloss'] = gloss_from_sense(chosen, alternatives, contextual=True)
                token['gloss']['supporting_candidate_ids'] = deepcopy(chosen['supporting_candidate_ids'])
                token['sense_ranking_status'] = 'proposed'
