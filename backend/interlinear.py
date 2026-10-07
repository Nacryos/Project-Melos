"""Lossless interlinear presentation of existing, fallible passage analyses.

This module neither creates lexical senses nor enumerates joint sentence parses.
Feature labels follow UD (https://universaldependencies.org/u/feat/index.html);
Perseus codes use the existing documented describe_postag adapter.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import unicodedata

from .morphology import describe_postag
from .translation_languages import is_english_language

_VALUES = {
    'Case': {'Nom': ('nominative', 'nom.'), 'Acc': ('accusative', 'acc.'), 'Gen': ('genitive', 'gen.'), 'Dat': ('dative', 'dat.'), 'Voc': ('vocative', 'voc.'), 'Loc': ('locative', 'loc.')},
    'Gender': {'Fem': ('feminine', 'fem.'), 'Masc': ('masculine', 'masc.'), 'Neut': ('neuter', 'neut.')},
    'Number': {'Sing': ('singular', 'sg.'), 'Plur': ('plural', 'pl.'), 'Dual': ('dual', 'du.')},
    'Person': {'1': ('first person', '1st'), '2': ('second person', '2nd'), '3': ('third person', '3rd')},
    'Tense': {'Pres': ('present', 'pres.'), 'Past': ('past', 'past'), 'Imp': ('imperfect', 'impf.'), 'Aor': ('aorist', 'aor.'), 'Perf': ('perfect', 'perf.'), 'Pqp': ('pluperfect', 'plup.'), 'Fut': ('future', 'fut.'), 'FutPerf': ('future perfect', 'fut. perf.')},
    'Mood': {'Ind': ('indicative', 'ind.'), 'Sub': ('subjunctive', 'subj.'), 'Opt': ('optative', 'opt.'), 'Imp': ('imperative', 'imper.')},
    'Voice': {'Act': ('active', 'act.'), 'Mid': ('middle', 'mid.'), 'Pass': ('passive', 'pass.'), 'Med': ('medio-passive', 'mid./pass.')},
    'VerbForm': {'Inf': ('infinitive', 'inf.'), 'Part': ('participle', 'ptcp.'), 'Fin': ('finite', '')},
    'POS': {'NOUN': ('noun', 'n.'), 'ADJ': ('adjective', 'adj.'), 'DET': ('article', 'art.'), 'PRON': ('pronoun', 'pron.'), 'VERB': ('verb', 'v.'), 'ADV': ('adverb', 'adv.'), 'ADP': ('preposition', 'prep.'), 'CCONJ': ('conjunction', 'conj.'), 'PART': ('particle', 'part.')},
}
_KEYS = {'case': 'Case', 'gender': 'Gender', 'gend': 'Gender', 'number': 'Number', 'num': 'Number', 'person': 'Person', 'pers': 'Person', 'tense': 'Tense', 'mood': 'Mood', 'voice': 'Voice', 'verbform': 'VerbForm', 'pofs': 'POS', 'pos': 'POS', 'upos': 'POS'}


def _form(token):
    """The editor's printed reading used for lookups; brackets/underdots removed."""
    return token.get('form') or token.get('text') or ''


def _identity(value):
    return unicodedata.normalize('NFC', str(value or '')).casefold()


def candidate_identity(row):
    """Stable identity for legacy source analyses lacking an explicit ID."""
    if row.get('id'):
        return str(row['id'])
    # Preserve every source-bearing discriminator, including unfamiliar raw
    # tags. A handpicked subset can collapse distinct grammatical alternatives.
    payload = {key: value for key, value in row.items()
               if key not in {'id', 'generated_candidate_identity'}}
    return 'source-analysis:' + hashlib.sha256(json.dumps(payload, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def canonical_features(row):
    """Translate supplied labels, never infer missing morphology from spelling."""
    supplied = {}
    raw = row.get('features') or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            field = _KEYS.get(str(key).lower())
            if field:
                values = value if isinstance(value, list) else str(value).split(',')
                labels_for_field = {str(v).strip().lower() for v in values}
                # Literal Alpheios/Morpheus labels, retained unchanged in raw
                # features. UD places infinitive/participle under VerbForm.
                if field == 'Mood':
                    supplied.setdefault('VerbForm', set()).update(
                        canonical for label, canonical in (('infinitive', 'Inf'), ('participle', 'Part'))
                        if label in labels_for_field)
                if field == 'Voice' and 'mediopassive' in labels_for_field:
                    supplied.setdefault('Voice', set()).add('Med')
                if field == 'POS' and 'verb participle' in labels_for_field:
                    supplied.setdefault('POS', set()).add('VERB')
                    supplied.setdefault('VerbForm', set()).add('Part')
                # Morpheus supplies literal ordinals (pers=1st/2nd/3rd).
                # They name the same grammatical persons, not inferred roles.
                known = {canonical for canonical, (long, short) in _VALUES[field].items()
                         if any(str(v).strip().lower() in ({canonical.lower(), long, short}
                             if field == 'Person' else {canonical.lower(), long}) for v in values)}
                supplied.setdefault(field, set()).update(known)
    description = describe_postag(row.get('analysis')) if isinstance(row.get('analysis'), str) else None
    tags = row.get('source_tags') or []
    # Only whole source tags / documented expanded postag terms are mapped.
    labels = [str(tag).lower() for tag in tags] if isinstance(tags, list) else []
    labels = [{'first-person': 'first person', 'second-person': 'second person',
               'third-person': 'third person'}.get(label, label) for label in labels]
    labels += description.split(' · ') if description else []
    for field, choices in _VALUES.items():
        known = {canonical for canonical, (long, short) in choices.items()
                 if long in labels or field == 'Person' and short in labels}
        supplied.setdefault(field, set()).update(known)
    if row.get('upos') in _VALUES['POS']:
        supplied.setdefault('POS', set()).add(row['upos'])
    # Conflicting explicit values remain unresolved, including conflicts
    # across aliases and source tags. A later key must not silently win.
    blocked = {'Mood', 'VerbForm'} if supplied.get('Mood') and supplied.get('VerbForm', set()) & {'Inf', 'Part'} else set()
    return {field: next(iter(values)) for field, values in supplied.items() if len(values) == 1 and field not in blocked}


def compact_parse(features):
    # Fixed grammatical display order, independent of upstream JSON order.
    order = ('Case', 'Gender', 'Person', 'Number', 'Tense', 'Mood', 'Voice', 'VerbForm')
    labels = [_VALUES[field][features[field]][1] for field in order
              if features.get(field) in _VALUES[field] and _VALUES[field][features[field]][1]]
    return ' '.join(labels) or _VALUES['POS'].get(features.get('POS'), ('', ''))[1]


def _lemma_letters(value):
    return ''.join(c for c in unicodedata.normalize('NFD', _identity(value)) if unicodedata.category(c) != 'Mn')


_FUNCTION_WORD_POS = {'ADV', 'ADP', 'CCONJ', 'SCONJ', 'PART'}


def _feature_agrees(key, candidate_value, predicted_value):
    # UD Past is coarser than these traditional labels; compatibility is not
    # permission to infer one of them from Past. Preserve source specificity.
    # https://universaldependencies.org/u/feat/Tense.html
    if candidate_value == predicted_value:
        return True
    if key == 'POS' and {candidate_value, predicted_value} <= _FUNCTION_WORD_POS:
        # Taggers and dictionaries split adverbs, prepositions, conjunctions
        # and particles differently (ἐκτός ADP/ADV, ἀλλά CCONJ/ADV, δέ PART).
        return True
    return key == 'Tense' and predicted_value == 'Past' and candidate_value in {'Aor', 'Imp', 'Pqp'}


# Relations whose dependent agrees with its head in case, number and gender.
# Genitive modifiers (nmod) and clausal modifiers do not agree, so they are
# excluded: ἄκρα νάων must not pull νάων towards the case of ἄκρα.
_AGREEMENT_RELATIONS = {'amod', 'det', 'appos', 'nummod'}
_NOMINAL_POS = {'NOUN', 'PRON', 'PROPN', 'ADJ', 'DET', 'NUM'}


def _agreement_partners(predicted, syntax_rows):
    """Predicted words this one should agree with in case, number and gender.

    An adjective, article or apposed noun agrees with its predicted head; a
    noun agrees with its predicted modifiers. Only nominal partners count, and
    only the partner's *predicted* features are used, never another token's
    chosen parse, so the signal stays a prediction.
    """
    by_id = {(row.get('sentence_id'), row.get('id')): row for row in syntax_rows}
    sentence, identifier = predicted.get('sentence_id'), predicted.get('id')
    partners = []
    relation = str(predicted.get('deprel') or '').split(':')[0]
    head = by_id.get((sentence, predicted.get('head')))
    if relation in _AGREEMENT_RELATIONS and head and head.get('upos') in _NOMINAL_POS:
        partners.append({'text': head.get('text'), 'relation': relation, 'role': 'head',
                         'features': canonical_features(head)})
    for row in syntax_rows:
        if (row.get('sentence_id') == sentence and row.get('head') == identifier and row is not predicted
                and str(row.get('deprel') or '').split(':')[0] in _AGREEMENT_RELATIONS
                and row.get('upos') in _NOMINAL_POS):
            partners.append({'text': row.get('text'), 'relation': str(row.get('deprel')).split(':')[0], 'role': 'dependent',
                             'features': canonical_features(row)})
    # Immediate nominal neighbours in the same sentence (νᾶϊ μελαίνᾳ) count as
    # weaker, positive-only partners: the model may have mis-attached them.
    ordered = sorted((row for row in syntax_rows if row.get('sentence_id') == sentence and row.get('upos')
                      and row.get('prediction_status') != 'not_applicable'), key=lambda row: row.get('absolute_start') or 0)
    for index, row in enumerate(ordered):
        if row is predicted or row.get('id') == identifier:
            for neighbour in (ordered[index - 1] if index else None, ordered[index + 1] if index + 1 < len(ordered) else None):
                if neighbour and neighbour.get('upos') in _NOMINAL_POS and not any(p['text'] == neighbour.get('text') and p['role'] != 'neighbour' for p in partners):
                    partners.append({'text': neighbour.get('text'), 'relation': 'adjacent', 'role': 'neighbour',
                                     'features': canonical_features(neighbour)})
            break
    return [partner for partner in partners if partner['features']]


def _partner_scores(candidate, syntax):
    """(agreeing, disagreeing) counts of Case/Number/Gender against partners.

    Dependency partners count both ways. A merely adjacent nominal counts only
    when it agrees on every shared feature and at least two of them.
    """
    features = canonical_features(candidate)
    agreeing = disagreeing = 0
    for partner in (syntax or {}).get('agreement_partners') or []:
        shared = [key for key in ('Case', 'Number', 'Gender') if key in features and key in partner['features']]
        matches = [features[key] == partner['features'][key] for key in shared]
        if partner.get('role') == 'neighbour':
            if len(shared) >= 2 and all(matches):
                agreeing += len(shared)
            continue
        agreeing += sum(matches)
        disagreeing += len(matches) - sum(matches)
    return agreeing, disagreeing


def _agreements(candidate, syntax):
    """Number of grammatical features on which candidate and prediction agree.

    Agreement with a predicted head or modifier counts as well, so a parse can
    be supported by its noun even when the model mislabelled the word itself.
    """
    features, predicted = canonical_features(candidate), canonical_features(syntax or {})
    own = sum(1 for key in set(features) & set(predicted) if _feature_agrees(key, features[key], predicted[key]))
    return own + _partner_scores(candidate, syntax)[0]


def _lemma_agrees(candidate, syntax):
    if not (candidate.get('lemma') and syntax.get('lemma')):
        return None
    return _lemma_letters(candidate['lemma']) == _lemma_letters(syntax['lemma'])


def _contradicts(candidate, syntax):
    """A grammatical feature stated by both sides disagrees.

    A differing lemma alone is not a contradiction: the statistical lemmatizer
    was trained on Attic-Ionic and routinely mislemmatizes dialect spellings
    (νᾶσος → νῆσος). Lemma agreement is a ranking signal in _affinity instead.
    """
    features, predicted = canonical_features(candidate), canonical_features(syntax)
    return any(not _feature_agrees(key, features[key], predicted[key])
               for key in set(features) & set(predicted))


def _compatible(candidate, syntax):
    features = canonical_features(candidate)
    predicted = canonical_features(syntax)
    shared = set(features) & set(predicted)
    # The statistical lemmatizer can misplace accents. This deliberately loose
    # *prediction compatibility* check is never used to join dictionary senses.
    return bool(shared) and not _contradicts(candidate, syntax)


def _affinity(candidate, syntax):
    """How well a candidate parse fits the contextual prediction.

    Counts agreeing grammatical features (each worth one), lemma agreement
    (worth one) and penalises each stated disagreement. A dialect label of
    Aeolic in the parser's own output adds a small prior for Lesbian poets.
    """
    features, predicted = canonical_features(candidate), canonical_features(syntax or {})
    score = 0.0
    for key in set(features) & set(predicted):
        if features[key] == predicted[key]:
            score += 1.0
        elif _feature_agrees(key, features[key], predicted[key]):
            # Soft matches (Past~Aor, ADV~CCONJ) count, but an exact match
            # still leads: καί the conjunction over καί the adverb.
            score += 0.5
        else:
            score -= 1.5
    # A fuller parse that is not contradicted outranks a partial one of the
    # same fit (dat. masc. 1st sg. over dat. masc. sg.), so person, tense and
    # mood stated by the source are never dropped in favour of a vaguer row.
    score += 0.1 * sum(1 for key in features if key not in predicted)
    # Agreement with the predicted head noun or modifiers (ἀργαλέᾳ ... νύκτι).
    agreeing, disagreeing = _partner_scores(candidate, syntax)
    score += 0.75 * agreeing - 0.75 * disagreeing
    lemma = _lemma_agrees(candidate, syntax or {})
    if lemma is True:
        score += 1.0
    raw = candidate.get('features') or {}
    dialect = str(raw.get('dial') or raw.get('dialect') or '').lower()
    if 'aeolic' in dialect:
        score += 0.25
    if candidate.get('normalised_query'):
        # A parse reached through a spelling normalisation ranks below any
        # analysis of the exact printed form with the same fit.
        score -= 0.5
    if candidate.get('candidate_kind') == 'pattern_analysis':
        # Ending-based analyses rank below every lexicon-backed parse.
        score -= 1.0
    elif not features:
        # A bare headword match states no grammar; it is listed last.
        score -= 2.0
    elif candidate.get('basis') != 'machine_analysis' and candidate.get('candidate_kind') != 'machine_analysis':
        # An exact-form attestation recorded by a dictionary (LSJ, Wiktionary)
        # outranks a parser hypothesis of the same fit, when it states a full
        # analysis; a row giving only "pl." must not outrank "nom. masc. pl.".
        score += 0.6
    if features.get('Case') == 'Voc' and predicted.get('Case') != 'Voc':
        # Vocative forms coincide with nominatives (participles, feminines);
        # unless the prediction says vocative, the nominative reading leads.
        score -= 0.2
    return score


def candidate_basis(item):
    if item.get('normalised_query'):
        return 'machine_analysis_normalised'
    if item.get('basis') == 'machine_analysis' or item.get('candidate_kind') == 'machine_analysis':
        return 'machine_analysis'
    return 'source_alternative'


def _fuller_row_of_same_lemma(top, second):
    """True when `top` restates `second`'s lemma and parse with extra features.

    Only then may a small margin decide: dat. masc. 1st sg. over dat. masc. sg.
    A nominative against an accusative of the same lemma stays ambiguous.
    """
    if _lemma_letters(top.get('lemma')) != _lemma_letters(second.get('lemma')):
        return False
    return canonical_features(second).items() <= canonical_features(top).items()


def _fullest_reading(ranked, syntax, informative, everything=None):
    """The top row, or a same-lemma row that restates it with more features.

    A dictionary row giving only "acc. sg." may be the only one compatible with
    a prediction that guessed the gender wrong (ἄεθλον: predicted masculine, the
    lexicon's full row is neuter). The fuller row of the same headword is the
    same reading with more information, so it is shown instead, provided it
    disagrees with the prediction only on features the partial row did not
    state. Among several, the one stating most features wins.
    """
    top = ranked[0]['candidate']
    top_features = canonical_features(top)
    best, best_size = None, len(top_features)
    predicted = canonical_features(syntax) if syntax else {}
    for row in [item['candidate'] for item in ranked[1:]] + list(everything or []):
        features = canonical_features(row)
        if not _fuller_row_of_same_lemma(row, top) or features == top_features or len(features) <= best_size:
            continue
        if informative and any(key in top_features and not _feature_agrees(key, features[key], predicted[key])
                               for key in set(features) & set(predicted)):
            continue
        best, best_size = row, len(features)
    return best or top


def rank_candidates(candidates, syntax):
    """Candidates ordered by affinity to the prediction; ties keep source order.

    Returns a list of {candidate, score}. Without a prediction every score is
    the dialect prior only, so the order is essentially the source order.
    """
    scored = [(index, _affinity(row, syntax), row) for index, row in enumerate(candidates)]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [{'candidate': row, 'score': score} for _, score, row in scored]


def _exact(candidate, token, machine=False):
    if not machine and token.get('analysis_match_status') == 'spelling_suggestions_only':
        # This status describes the legacy form index, not independently
        # extracted contextual source rows. Admit only a separately proved
        # literal contextual analysis; nearby indexed spellings stay excluded.
        claims = [*(token.get('structured_evidence') or {}).get('claims', []),
                  *(token.get('contextual_supporting_claims') or [])]
        proof_ids = {claim.get('id') for claim in claims
                     if claim.get('status') == 'source_claim' and claim.get('assertion_type') == 'extracted_annotation'
                     and any(evidence.get('source_url') and evidence.get('raw_sha256') and evidence.get('locator')
                             for evidence in claim.get('evidence') or [])}
        linked = candidate.get('claim_ids') or []
        if (candidate not in (token.get('contextual_candidates') or [])
                or candidate.get('candidate_kind') not in {'grammatical_analysis', 'explicit_form_of'}
                or candidate.get('status') != 'source_claim'
                or not linked or not set(linked).issubset(proof_ids)):
            return False
    if candidate.get('edit_distance', 0) not in (None, 0):
        return False
    forms = [candidate.get('matched_form'), candidate.get('matched_object_form'), candidate.get('form'), candidate.get('attested_form')]
    forms += candidate.get('matched_form_variants') or []
    if any(forms):
        return any(unicodedata.normalize('NFC', str(form)) == unicodedata.normalize('NFC', _form(token)) for form in forms if form)
    return machine or any((token.get('claim_applications') or {}).get(cid, {}).get('scope') == 'exact_token_span'
                          for cid in candidate.get('claim_ids') or [])


def _english(row):
    language = row.get('gloss_language') or row.get('language')
    if language:
        return is_english_language(language)
    source = ' '.join(str(row.get(key) or '') for key in ('gloss_source', 'source', 'source_family', 'gloss_source_url', 'source_url')).lower()
    return any(mark in source for mark in ('lsj', 'autenrieth', 'en.wiktionary.org', 'enwiktionary', 'english wiktionary'))


def _dictionary_family(entry):
    return str(entry.get('lexicon') or entry.get('source_family') or entry.get('source') or '').casefold()


def _homograph_marked(row):
    if row.get('homograph_id') or row.get('lemma_identity'):
        return True
    if any(re.search(r'\d', str(row.get(key) or '')) for key in ('lemma_beta', 'lemma_raw', 'entry_headword')):
        return True
    lemma = row.get('lemma') or row.get('entry_headword') or ''
    raw = row.get('lemma_raw') or lemma
    return bool(re.search(r'\d', str(raw))) or _identity(raw) != _identity(lemma)


def join_machine_dictionary(token, lookup):
    """Join exact dictionary headwords to hypotheses, never to attestations.

    ``lookup`` is bounded and request-cached by the caller. Its morphological
    candidates and occurrence claims are ignored. Homographs stay unresolved.
    """
    entries = token.setdefault('lexicon_entries', [])
    known_ids = {entry.get('id') for entry in entries if entry.get('id')}
    for candidate in (token.get('machine') or {}).get('machine_candidates') or []:
        lemma = candidate.get('lemma')
        if (not isinstance(lemma, str) or not lemma or len(lemma) > 200
                or _homograph_marked(candidate) or not _exact(candidate, token, True)):
            continue
        found = lookup(lemma)
        exact = [entry for entry in found.get('lexicon_entries') or []
                 if entry.get('id') and _identity(entry.get('lemma')) == _identity(lemma)]
        for entry in exact:
            if entry['id'] not in known_ids:
                entries.append(deepcopy(entry)); known_ids.add(entry['id'])
        ids = list(dict.fromkeys(entry['id'] for entry in exact))
        candidate['lexicon_entry_ids'] = list(dict.fromkeys([
            *(candidate.get('lexicon_entry_ids') or []), *ids]))
        candidate['dictionary_join'] = {
            'status': 'available' if ids else found.get('dictionary_lookup_status', 'no_exact_headword'),
            'basis': 'machine_lemma_exact_dictionary_headword',
            'entry_ids': ids, 'occurrence_attested': False,
        }


def _unresolved_dictionary_inventory(entries, missing):
    """Keep literal meanings grouped by unresolved source-local entry identity.

    Nothing here selects a homograph or a contextual meaning. Flattened senses
    keep their original entry IDs for the optional separately labelled ranker;
    entry_alternatives preserves the unresolved lexical inventory for display.
    Only fully traced English definition spans are admitted to this new path.
    """
    # Contradictory source identities must not become a first-wins partial
    # inventory: a dropped competitor could change the contextual ranking.
    entry_payloads, sense_payloads = {}, {}
    for entry in entries:
        identifier = entry.get('id')
        if identifier:
            if identifier in entry_payloads and entry_payloads[identifier] != entry:
                return {**missing, 'selection_basis': 'conflicting_dictionary_inventory'}
            entry_payloads[identifier] = entry
        for sense in entry.get('dictionary_senses') or []:
            if not isinstance(sense, dict) or not sense.get('id'):
                continue
            payload = (identifier, sense)
            if sense['id'] in sense_payloads and sense_payloads[sense['id']] != payload:
                return {**missing, 'selection_basis': 'conflicting_dictionary_inventory'}
            sense_payloads[sense['id']] = payload
    groups, alternatives, seen_entries, seen_senses = [], [], set(), set()
    for entry in entries:
        entry_id = entry.get('id')
        if not entry_id or entry_id in seen_entries:
            continue
        seen_entries.add(entry_id)
        senses = []
        for sense in entry.get('dictionary_senses') or []:
            if (not isinstance(sense, dict) or not sense.get('id') or sense['id'] in seen_senses
                    or not any(sense.get(key) for key in ('lexicon_entry_id', 'entry_id'))
                    or ('lexicon_entry_id' in sense and sense['lexicon_entry_id'] != entry_id)
                    or ('entry_id' in sense and sense['entry_id'] != (entry.get('entry_id') or entry_id))
                    or not isinstance(sense.get('text'), str) or not sense['text'].strip()
                    or not _english(sense) or sense.get('evidence_type') != 'dictionary_sense'
                    or not sense.get('source_url') or not sense.get('source_locator')
                    or not re.fullmatch(r'[0-9a-fA-F]{64}', str(sense.get('raw_sha256') or ''))):
                continue
            seen_senses.add(sense['id'])
            senses.append(deepcopy(sense))
        groups.append({**{key: deepcopy(entry.get(key)) for key in
                          ('id', 'entry_id', 'lemma', 'lemma_raw', 'lemma_beta', 'homograph_id',
                           'lemma_identity', 'source', 'source_url', 'entry_url')},
                       'status': 'unresolved_entry_alternative', 'senses': senses,
                       'sense_inventory_status': 'available' if senses else 'no_traced_english_senses'})
        alternatives.extend(deepcopy(senses))
    if not groups:
        return missing
    return {**missing, 'status': 'alternatives' if alternatives else 'unavailable',
            'selection_basis': 'unresolved_dictionary_entries_not_contextual',
            'entry_alternatives': groups, 'alternatives': alternatives}


def _gloss(candidate, token):
    missing = {'text': None, 'full_text': None, 'status': 'unavailable', 'selection_basis': 'dictionary_preview_not_contextual_sense'}
    if not candidate:
        return missing
    entries = token.get('lexicon_entries') or []
    bound = [entry for entry in entries if entry.get('id') == candidate.get('gloss_entry_id') and entry.get('id')
             and _identity(entry.get('lemma')) == _identity(candidate.get('entry_headword') or candidate.get('lemma'))]
    if candidate.get('gloss_entry_id') and not bound:
        # A supplied pointer is authoritative only for its exact entry, not a
        # license to silently substitute another homograph or dictionary row.
        return missing
    if len(bound) == 1 and not _homograph_marked(candidate) and not _homograph_marked(bound[0]):
        # The exact source pointer remains primary. Other dictionaries can
        # supply separate alternatives only for an unnumbered, unambiguous
        # exact lemma; shared spelling never resolves numbered homographs.
        primary_family = _dictionary_family(bound[0])
        other_families = {}
        for entry in entries:
            family = _dictionary_family(entry)
            if family and family != primary_family and _identity(entry.get('lemma')) == _identity(candidate.get('lemma')):
                other_families.setdefault(family, []).append(entry)
        bound += [rows[0] for rows in other_families.values() if len(rows) == 1 and not _homograph_marked(rows[0])]
    if not bound:
        bound = [entry for entry in entries if _identity(entry.get('lemma')) == _identity(candidate.get('lemma'))]
        if _homograph_marked(candidate):
            return missing
        if any(_homograph_marked(entry) for entry in bound):
            # A lemma-only bridge cannot resolve source-local numbered
            # homographs, even if only one was returned by the lookup limit.
            return _unresolved_dictionary_inventory(bound, missing)
        # Two independent dictionaries are not two homographs. Multiple
        # matching entries *within* one dictionary remain unresolved unless
        # the morphology candidate carries an explicit entry identity.
        families = [_dictionary_family(entry) for entry in bound]
        if len(families) != len(set(families)):
            return _unresolved_dictionary_inventory(bound, missing)
    structured = [row for row in bound if 'dictionary_senses' in row or 'dictionary_senses_status' in row]
    if not structured and candidate.get('gloss_entry_id') and ('dictionary_senses' in candidate or 'dictionary_senses_status' in candidate):
        structured = [candidate]
    if structured:
        senses, seen = [], set()
        for entry in structured:
            entry_id = entry.get('gloss_entry_id') or entry.get('id')
            for sense in entry.get('dictionary_senses') or []:
                if (not isinstance(sense, dict) or not sense.get('id') or sense['id'] in seen
                        or (sense.get('lexicon_entry_id') or sense.get('entry_id')) != entry_id
                        or not isinstance(sense.get('text'), str) or not sense['text'].strip()
                        or not _english(sense) or sense.get('evidence_type') != 'dictionary_sense'):
                    continue
                seen.add(sense['id']); senses.append(deepcopy(sense))
        if not senses:
            return {**missing, 'alternatives': [], 'selection_basis': 'no_extracted_dictionary_sense'}
        # The renderer keeps complete literal definitions. The model may rank
        # these identifiers later; no dictionary wording is generated here.
        eligible = [sense for sense in senses if sense_form_compatible(sense, token, candidate=candidate)]
        if not eligible:
            return {**missing, 'alternatives': senses, 'selection_basis': 'no_form_compatible_dictionary_sense'}
        return gloss_from_sense(eligible[0], senses)
    sources = [candidate, *bound] if candidate.get('gloss') else bound
    for row in sources:
        full = row.get('gloss')
        provenance = any(row.get(key) for key in ('source', 'gloss_source', 'source_url', 'gloss_source_url', 'gloss_entry_id', 'receipt_id')) or bool(row.get('id') and not row.get('generated_candidate_identity'))
        if not provenance or not isinstance(full, str) or not full.strip() or not _english(row):
            continue
        full = full.strip()
        if any('GREEK' in unicodedata.name(char, '') for char in full):
            continue
        # A complete delimiter-bounded sense is allowed; never truncate words.
        first = full.split(';', 1)[0].strip()
        # A comma often belongs inside a gloss ('not X, but Y'), not between
        # senses. A qualifier alone is not a meaning either.
        if re.fullmatch(r'\([^)]*\)[,.:]?', first):
            first = ''
        # Prefer a complete sourced sense over an arbitrary word cap. Long
        # senses may wrap in the reader, but their meaning is never clipped.
        short = first or None
        return {**missing, 'text': short, 'full_text': full,
                'status': 'available' if short else 'long_definition',
                'source': row.get('gloss_source') or row.get('source'),
                'source_url': row.get('gloss_source_url') or row.get('source_url'),
                'entry_id': row.get('gloss_entry_id') or row.get('id'),
                'selection_basis': 'first_dictionary_sense_not_contextual_sense'}
    return missing


def gloss_from_sense(sense, alternatives, *, contextual=False):
    return {'text': sense['text'], 'full_text': sense['text'], 'status': 'available',
            'source': sense.get('source'), 'source_url': sense.get('source_url'),
            'entry_id': sense.get('lexicon_entry_id') or sense.get('entry_id'),
            'sense_id': sense['id'], 'alternatives': deepcopy(alternatives),
            'selection_basis': 'jev_contextual_sense_proposal' if contextual else 'first_dictionary_sense_not_contextual_sense',
            'source_locator': deepcopy(sense.get('source_locator')), 'qualifiers': deepcopy(sense.get('qualifiers') or []),
            'scope_text': sense.get('scope_text'), 'raw_sha256': sense.get('raw_sha256')}


def _source_tense_restrictions(sense):
    """Accept only the extractor's bounded, provenance-consistent declaration.

    The upstream extractor verifies archived XML hashes and literal scope.
    Here we check the binding again; absent/malformed proof cannot constrain
    morphology, and no English gloss text is used to infer grammatical scope.
    """
    path = sense.get('sense_path')
    restrictions = sense.get('morphology_restrictions')
    parent_locator = sense.get('source_locator')
    if (not isinstance(path, list) or not path or not isinstance(path[-1], dict)
            or not isinstance(restrictions, list) or not isinstance(parent_locator, dict)):
        return
    source_id = path[-1].get('id')
    if not isinstance(source_id, str) or not source_id:
        return
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            continue
        scope = restriction.get('scope')
        locator = restriction.get('source_locator')
        tense_locator = restriction.get('tense_source_locator')
        if not all(isinstance(value, dict) for value in (scope, locator, tense_locator)):
            continue
        target_ids = scope.get('target_source_sense_ids')
        if not isinstance(target_ids, list) or not all(isinstance(value, str) and value for value in target_ids):
            continue
        coordinates = [locator.get('rendered_start'), locator.get('rendered_end'),
                       tense_locator.get('rendered_start'), tense_locator.get('rendered_end')]
        if (restriction.get('kind') != 'source_tense_only' or restriction.get('feature') != 'Tense'
                or restriction.get('allowed_values') != ['Pres']
                or restriction.get('extraction_rule') != 'explicit_terminal_two_foregoing_present_senses_v1'
                or scope.get('kind') != 'preceding_meaning_units' or type(scope.get('count')) is not int or scope['count'] != 2
                or len(target_ids) != 2 or len(set(target_ids)) != 2 or source_id not in target_ids
                or not isinstance(restriction.get('source_text'), str) or not restriction['source_text'].strip()
                or not isinstance(sense.get('source_url'), str) or not sense['source_url']
                or restriction.get('source_url') != sense['source_url']
                or not isinstance(sense.get('raw_sha256'), str)
                or not re.fullmatch(r'[0-9a-fA-F]{64}', sense['raw_sha256'])
                or restriction.get('raw_sha256') != sense['raw_sha256']
                or not sense.get('lexicon_entry_id')
                or restriction.get('lexicon_entry_id') != sense['lexicon_entry_id']
                or ('entry_id' in restriction and restriction['entry_id'] != sense.get('entry_id'))
                or not isinstance(locator.get('node_path'), str) or not locator['node_path']
                or not isinstance(tense_locator.get('node_path'), str) or not tense_locator['node_path']
                or not all(type(value) is int for value in coordinates)
                or not 0 <= coordinates[0] <= coordinates[2] < coordinates[3] <= coordinates[1]
                or not isinstance(locator.get('offset_basis'), str) or not locator['offset_basis']
                or locator['offset_basis'] != parent_locator.get('offset_basis')
                or tense_locator.get('offset_basis') != locator['offset_basis']):
            continue
        yield restriction


def _sense_tenses(sense, token, candidate):
    # A selected candidate limits headline compatibility only. All competing
    # candidates and their literal sense inventories remain in the response
    # and ranker packet; no linguistic impossibility is inferred from ranking.
    if candidate is not None:
        return [canonical_features(candidate).get('Tense')]
    meanings = token.get('candidate_meanings') or []
    supporting = [item for item in meanings if any(
        alternative.get('id') == sense.get('id')
        for alternative in (item.get('gloss') or {}).get('alternatives') or [])]
    if token.get('candidate_id'):
        supporting = [item for item in supporting if item.get('candidate_id') == token['candidate_id']]
    if meanings:
        return [canonical_features(item).get('Tense') for item in supporting]
    if token.get('selection_basis') == 'syntax_prediction':
        return []
    return [canonical_features(token).get('Tense')]


def sense_form_compatible(sense, token, *, candidate=None):
    scope = sense.get('form_scope') or {}
    if scope.get('relation') == 'variant' and _identity(scope.get('text')) != _identity(_form(token)):
        return False
    tenses = _sense_tenses(sense, token, candidate)
    for restriction in _source_tense_restrictions(sense):
        # An unresolved/unknown alternative prevents a categorical exclusion.
        # Reject only when all supplied applicable parses explicitly conflict.
        if tenses and all(tense is not None and tense not in restriction['allowed_values'] for tense in tenses):
            return False
    return True


def _choose(token, syntax, rank):
    if syntax and not canonical_features(syntax) and not syntax.get('agreement_partners'):
        # A prediction with no grammatical content (X, INTJ, punctuation-like)
        # is no prediction: the candidates are weighed on their own.
        syntax = None
    source = [row for row in [*(token.get('source_candidates') or []), *(token.get('contextual_candidates') or [])] if _exact(row, token)]
    machine = [row for row in (token.get('machine') or {}).get('machine_candidates') or [] if _exact(row, token, True)]
    candidates = [{**row, 'id': candidate_identity(row), 'generated_candidate_identity':
                   bool(row.get('generated_candidate_identity')) or not bool(row.get('id'))} for row in source + machine]
    by_id = {}
    for row in candidates:
        signature = (_identity(row.get('lemma_raw') or row.get('lemma')), str(row.get('homograph_id') or ''),
                     str(row.get('lemma_identity') or ''), tuple(sorted(canonical_features(row).items())),
                     row.get('gloss_entry_id'), tuple(row.get('lexicon_entry_ids') or []))
        if row['id'] in by_id and by_id[row['id']] != signature:
            return None, 'ambiguous', len(candidates)
        by_id[row['id']] = signature
    # A vocative that differs from a nominative of the same lemma only in case
    # is the same form (participles, feminines); fold it so a nom./voc. pair
    # counts as one reading rather than an unresolved ambiguity.
    if not (syntax and canonical_features(syntax).get('Case') == 'Voc'):
        nominatives = {(_identity(row.get('lemma_raw') or row.get('lemma')), tuple(sorted({**canonical_features(row), 'Case': 'Nom'}.items())))
                       for row in candidates if canonical_features(row).get('Case') == 'Nom'}
        candidates = [row for row in candidates if not (canonical_features(row).get('Case') == 'Voc' and
                      (_identity(row.get('lemma_raw') or row.get('lemma')), tuple(sorted({**canonical_features(row), 'Case': 'Nom'}.items()))) in nominatives)]
    compatible = [row for row in candidates if syntax and _compatible(row, syntax)]
    # Preserve source-local homograph suffixes. Duplicate evidence for the same
    # analysis need not create duplicate presentation alternatives.
    identities = {}
    for row in compatible if syntax else candidates:
        key = (_identity(row.get('lemma_raw') or row.get('lemma')), str(row.get('homograph_id') or ''),
               str(row.get('lemma_identity') or ''), tuple(sorted(canonical_features(row).items())))
        identities.setdefault(key, row)
    # An explicit fuller source analysis can subsume a partial annotation for
    # the same lemma/homograph. Choose that existing row, never synthesize a
    # parse by combining mutually exclusive features from different rows.
    for key, row in list(identities.items()):
        features = canonical_features(row)
        # Lemma spellings with macrons or accents (ἴφθῑμος / ἴφθιμος) are the
        # same headword for this purpose.
        if any(_lemma_letters(row.get('lemma')) == _lemma_letters(other.get('lemma')) and key[1] == other_key[1]
               and features.items() < canonical_features(other).items()
               for other_key, other in identities.items() if other_key != key):
            identities.pop(key)
    decision = (rank or {}).get('decision') or {}
    if decision.get('status') in {'proposed', 'machine_proposed'}:
        chosen_id = decision.get('candidate_id')
        probabilities = decision.get('model_probabilities_uncalibrated') or {}
        packet_candidates = (decision.get('packet') or {}).get('candidates') or []
        expected = {row.get('id') for row in packet_candidates} | {'abstain'}
        complete = (None not in expected and set(probabilities) == expected
                    and all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
                            for value in probabilities.values()))
        score = probabilities.get(chosen_id)
        others = [v for k, v in probabilities.items() if k != chosen_id and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
        if complete and isinstance(score, (int, float)) and not isinstance(score, bool) and .75 <= score <= 1 and score - max(others or [0]) >= .2:
            # Select only the original server inventory, never model/packet fields.
            chosen = next((row for row in candidates if row.get('id') == chosen_id), None)
            packet_choice = next((row for row in packet_candidates if row.get('id') == chosen_id), None)
            if (chosen and packet_choice and _identity(chosen.get('lemma')) == _identity(packet_choice.get('lemma'))
                    and canonical_features(chosen) == canonical_features(packet_choice)):
                basis = 'jev_syntax_compatible' if syntax and _compatible(chosen, syntax) else 'jev_contextual_candidate'
                return chosen, basis, len(identities)
    if len(identities) == 1:
        only = next(iter(identities.values()))
        return (_fullest_reading([{'candidate': only}], syntax, bool(syntax), candidates),
                'unique_compatible_candidate' if syntax else 'unique_candidate', 1)
    if candidates:
        # Rank the full parses by their fit to the contextual prediction. When
        # nothing is compatible the prediction is contradicted on some feature;
        # the parses still rank, and the best one is shown as a ranked proposal.
        # Without a usable prediction the ranking rests on attestation and
        # completeness alone (the fuller source row of one lemma, ἔοι → εἰμί).
        # A prediction without grammatical features (X, INTJ) asserts nothing
        # that a parse could contradict; partners alone still rank below.
        informative = bool(syntax) and bool(canonical_features(syntax))
        pool = list(identities.values()) if identities else candidates
        if not informative:
            ranked = rank_candidates(pool, syntax)
            margin = ranked[0]['score'] - (ranked[1]['score'] if len(ranked) > 1 else float('-inf'))
            if canonical_features(ranked[0]['candidate']) and (len(ranked) == 1 or margin >= 0.5
                                                                or (margin > 0 and _fuller_row_of_same_lemma(ranked[0]['candidate'], ranked[1]['candidate']))):
                return _fullest_reading(ranked, syntax, False, candidates), 'morphology_ranked_without_syntax', len(pool)
            return None, 'ambiguous', len(identities) or len(candidates)
        if not identities:
            distinct = {(_identity(row.get('lemma_raw') or row.get('lemma')), str(row.get('homograph_id') or ''),
                         str(row.get('lemma_identity') or ''), tuple(sorted(canonical_features(row).items()))) for row in pool}
            if len(distinct) == 1 and canonical_features(pool[0]):
                # Only one full parse exists. A statistical prediction that
                # disagrees with it is flagged as a conflict, not obeyed.
                return pool[0], 'single_candidate_despite_syntax_conflict', 1
        ranked = rank_candidates(pool, syntax)
        # A contradicted pool is only resolved when the best parse still agrees
        # with the prediction or a predicted partner on something; lemma or
        # dialect alone never decides.
        # A margin that comes only from stating more features (0.1 each) may
        # pick the fuller row of the *same* lemma, but never resolve a homograph
        # (ἦλθον / ἔρχομαι for ἦλθες): different lemmas need a real margin.
        margin = ranked[0]['score'] - (ranked[1]['score'] if len(ranked) > 1 else float('-inf'))
        fuller = len(ranked) > 1 and _fuller_row_of_same_lemma(ranked[0]['candidate'], ranked[1]['candidate'])
        decisive = ranked[0]['score'] > 0 and (len(ranked) == 1 or margin >= 0.5 or (fuller and margin > 0))
        if decisive and (identities or _agreements(ranked[0]['candidate'], syntax) >= 1):
            basis = 'morphology_ranked_by_syntax' if identities else 'morphology_ranked_despite_syntax_conflict'
            return _fullest_reading(ranked, syntax, True, candidates), basis, len(pool)
    return None, 'ambiguous' if candidates else 'unavailable', len(identities) or len(candidates)


def _morphology_consensus(candidates, syntax):
    """A unique existing feature extension, without merging lexical identities."""
    rows = [row for row in candidates if not syntax or _compatible(row, syntax)]
    source_fallback = False
    if not rows and any(canonical_features(row) and row.get('basis') != 'machine_analysis'
                        and row.get('candidate_kind') != 'machine_analysis' for row in candidates):
        # A contradictory statistical prediction cannot erase a consistent
        # exact source analysis. Keep lexical identities unresolved and retain
        # the conflict; use only features explicitly present in a source row.
        rows = candidates
        source_fallback = True
    if not rows or len({_identity(row.get('lemma')) for row in rows}) != 1:
        return {}, []
    features = [canonical_features(row) for row in rows]
    maxima = [values for values in features if values and
              not any(values.items() < other.items() for other in features)]
    if not maxima or any(values != maxima[0] for values in maxima):
        return {}, []
    supporters = [row for row, values in zip(rows, features) if values == maxima[0]]
    if source_fallback:
        # Retain machine alternatives in the ambiguity check above, but never
        # label machine-only added features as an exact source consensus.
        supporters = [row for row in supporters if row.get('basis') != 'machine_analysis'
                      and row.get('candidate_kind') != 'machine_analysis']
        if not supporters:
            return {}, []
    return maxima[0], [candidate_identity(row) for row in supporters]


def _lexical_prediction_conflict(token, predicted):
    """Veto standalone model presentation using revalidated lexical evidence.

    A dictionary variant supplies no case/number/tense. Even a veto does not
    establish an exhaustive set of possible occurrence analyses.
    """
    if not predicted or not token.get('lexical_variants'):
        return None
    from .lexical_variants import project_variants
    rebuilt = project_variants(_form(token), token.get('lexical_variant_supporting_claims') or [])
    supplied = token.get('lexical_variants') or []
    if not rebuilt or len(rebuilt) >= 20 or len(rebuilt) != len(supplied):
        return None
    by_id = {row['id']: row for row in rebuilt}
    if len(by_id) != len(rebuilt) or {row.get('id') for row in supplied} != set(by_id):
        return None
    fields = ('id', 'matched_form', 'entry_id', 'lemma', 'entry_headword', 'claim_ids', 'method', 'scope')
    if any(any(row.get(key) != by_id[row['id']].get(key) for key in fields) for row in supplied):
        return None
    pos_map = {'adv': 'ADV', 'adj': 'ADJ', 'noun': 'NOUN', 'verb': 'VERB', 'pron': 'PRON',
               'prep': 'ADP', 'conj': 'CCONJ', 'particle': 'PART', 'article': 'DET'}
    entries = []
    for row in rebuilt:
        pos = pos_map.get(row.get('dictionary_pos'))
        if not pos or not row.get('dictionary_pos_claim_ids'):
            return None
        entries.append({'variant_id': row['id'], 'entry_id': row['entry_id'],
                        'lemma': row['lemma'], 'dictionary_pos': row['dictionary_pos'],
                        'claim_ids': deepcopy(row['dictionary_pos_claim_ids'])})
    model_pos = canonical_features(predicted).get('POS')
    model_lemma = predicted.get('lemma')
    disagrees = lambda row: (bool(model_pos and model_pos != pos_map[row['dictionary_pos']])
                            or bool(model_lemma and _lemma_letters(model_lemma) != _lemma_letters(row['lemma'])))
    if not all(disagrees(row) for row in entries):
        return None
    return {'status': 'conflict', 'variants': entries,
            'scope_note': 'Standalone syntax prediction suppressed because it disagrees with the supplied exact dictionary variants; no full occurrence parse or exhaustive lexical inventory is asserted.'}


def _shared_dictionary_sense(candidates, token):
    """One identical, sourced lexical sense across every exact alternative.

    This does not choose a parse or use a syntax prediction to discard an
    inconvenient alternative. Multiple dictionary senses still need contextual
    ranking; agreement on a first-listed gloss is not semantic agreement.
    """
    if not candidates or not any(row.get('basis') != 'machine_analysis'
                                and row.get('candidate_kind') != 'machine_analysis' for row in candidates):
        return None
    marked = {(_identity(row.get('lemma_raw') or row.get('lemma')),
               str(row.get('homograph_id') or ''), str(row.get('lemma_identity') or ''))
              for row in candidates if _homograph_marked(row)}
    if len(marked) > 1:
        return None
    sense, alternatives, supporting = None, None, []
    identities = {}
    for candidate in candidates:
        if not canonical_features(candidate):
            # A dictionary headword/suffix lookup without any morphology is
            # not a parser alternative and cannot establish shared meaning.
            return None
        identifier = candidate_identity(candidate)
        identity = (_identity(candidate.get('lemma_raw') or candidate.get('lemma')),
                    tuple(sorted(canonical_features(candidate).items())))
        if identifier in identities and identities[identifier] != identity:
            return None
        identities[identifier] = identity
        preview = _gloss(candidate, token)
        possible = [item for item in preview.get('alternatives') or [] if sense_form_compatible(item, token, candidate=candidate)]
        if (preview.get('status') != 'available' or len(possible) != 1
                or not possible[0].get('source_url') or not possible[0].get('source_locator')
                or not possible[0].get('raw_sha256') or not preview.get('entry_id')):
            return None
        current = possible[0]
        if sense is None:
            sense, alternatives = current, preview['alternatives']
        elif current != sense or preview['alternatives'] != alternatives:
            return None
        supporting.append(identifier)
    result = gloss_from_sense(sense, alternatives)
    result.update(selection_basis='shared_source_dictionary_sense_not_contextual',
                  supporting_candidate_ids=list(dict.fromkeys(supporting)),
                  scope_note='The same single available dictionary sense supports every supplied exact alternative; no contextual sense or complete parse was selected.')
    return result


def _subentry_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def catalog_machine_subentries(catalog, payload):
    """Pool a trusted, receipt-replayed resolver result without duplicating proof."""
    if not isinstance(payload, dict):
        raise ValueError('Invalid machine-subentry result')
    if (payload.get('version') != 'receipt-lemma-explicit-subentry-v1'
            or payload.get('status') not in {'available', 'partial', 'source_evidence_only', 'no_exact_subentry', 'unavailable'}
            or not isinstance(payload.get('form'), str) or not 1 <= len(payload['form']) <= 200):
        raise ValueError('Invalid machine-subentry envelope')
    inventory = payload.get('inventory_sha256')
    body = {key: value for key, value in payload.items() if key != 'inventory_sha256'}
    if not inventory or _subentry_digest(body) != inventory:
        raise ValueError('Machine-subentry inventory digest mismatch')
    dependency = payload.get('dependencies')
    if not isinstance(dependency, dict):
        raise ValueError('Missing explicit subentry dependency')
    dependency_ref = _subentry_digest(dependency)
    pools = {'dependencies': {dependency_ref: dependency}}
    fields = {'bindings': 'candidates', 'subentries': 'supporting_subentries', 'receipts': 'supporting_receipts'}
    refs = {}
    for pool, field in fields.items():
        rows = payload.get(field)
        if not isinstance(rows, list):
            raise ValueError('Missing subentry evidence collection')
        pools[pool], refs[field] = {}, []
        for row in rows:
            identifier = row.get('id') if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not identifier or identifier in pools[pool]:
                raise ValueError('Ambiguous subentry evidence identity')
            pools[pool][identifier] = row
            refs[field].append(identifier)
    envelope = {key: deepcopy(value) for key, value in body.items()
                if key not in {*fields.values(), 'dependencies'}}
    envelope.update(dependency_ref=dependency_ref, **refs)
    pools['inventories'] = {inventory: envelope}
    for pool, entries in pools.items():
        for identifier, row in entries.items():
            if identifier in catalog.get(pool, {}) and catalog[pool][identifier] != row:
                raise ValueError('Conflicting pooled subentry evidence identity')
    for pool, entries in pools.items():
        catalog.setdefault(pool, {}).update(deepcopy(entries))
    return {'status': payload['status'], 'inventory_ref': inventory,
            'candidate_refs': refs['candidates'], 'ranking_status': 'unsupported_source_type'}


def _machine_subentry_alternatives(result, token):
    """Return validated refs, not ordinary headword/Jev senses or selected glosses.

    The trusted callback verifies the actual archive and cached receipt. This
    boundary verifies their transport, exact candidate binding and ownership
    of every supplied sense. Original variant form_scope remains unchanged.
    """
    reference = token.get('machine_subentries')
    if not reference or token.get('partial_word') or token.get('editorial_fragment'):
        return {}
    try:
        catalog = result['machine_subentry_evidence']
        inventory_id = reference['inventory_ref']
        envelope = catalog['inventories'][inventory_id]
        body = {key: deepcopy(value) for key, value in envelope.items()
                if key not in {'dependency_ref', 'candidates', 'supporting_subentries', 'supporting_receipts'}}
        body['dependencies'] = catalog['dependencies'][envelope['dependency_ref']]
        if _subentry_digest(body['dependencies']) != envelope['dependency_ref']:
            return {}
        for field, pool in (('candidates', 'bindings'), ('supporting_subentries', 'subentries'), ('supporting_receipts', 'receipts')):
            ids = envelope[field]
            if not isinstance(ids, list) or len(set(ids)) != len(ids):
                return {}
            body[field] = [catalog[pool][identifier] for identifier in ids]
        if (_subentry_digest(body) != inventory_id or body['form'] != _form(token)
                or reference['candidate_refs'] != envelope['candidates']
                or body['version'] != 'receipt-lemma-explicit-subentry-v1'
                or body['status'] not in {'available', 'partial', 'source_evidence_only', 'no_exact_subentry'}):
            return {}
        from .lexicon_subentries import lookup_key
        from .machine_subentries import _preview_eligibility
        candidates = (token.get('machine') or {}).get('machine_candidates') or []
        if (token.get('machine') or {}).get('status') != 'ok' or (token.get('machine') or {}).get('form') != _form(token):
            return {}
        subentries = {row['id']: row for row in body['supporting_subentries']}
        receipts = {row['id']: row for row in body['supporting_receipts']}
        output = {}
        for binding in body['candidates']:
            if binding.get('id') != 'machine-subentry:' + _subentry_digest({key: value for key, value in binding.items() if key != 'id'}):
                return {}
            matches = [row for row in candidates if row.get('id') == binding['candidate_id']]
            if len(matches) != 1:
                return {}
            candidate = matches[0]
            raw_candidate = {key: value for key, value in candidate.items()
                             if key not in {'lexicon_entry_ids', 'dictionary_join'}}
            receipt = receipts[binding['receipt_id']]
            if (_subentry_digest(raw_candidate) != binding['machine_candidate_sha256']
                    or candidate.get('basis') != 'machine_analysis' or candidate.get('candidate_kind') != 'machine_analysis'
                    or candidate.get('receipt_id') != binding['receipt_id']
                    or candidate.get('lemma') != binding['lemma'] or binding['form'] != _form(token)
                    or binding.get('occurrence_attested') is not False or binding.get('contextually_selected') is not False
                    or binding.get('surface_equivalence_inferred') is not False
                    or binding.get('match_method') != 'exact_parser_lemma_to_explicit_subentry_orthography'
                    or lookup_key(candidate['lemma']) != binding['lookup_key']
                    or (receipt.get('source_form') or receipt.get('request_form')) != _form(token)
                    or not re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('raw_sha256') or ''))):
                return {}
            if not set(binding['english_preview_subentry_ids']).issubset(binding['subentry_ids']):
                return {}
            refs = []
            for identifier in binding['english_preview_subentry_ids']:
                evidence = subentries[identifier]
                source = evidence['source_subentry']
                if (evidence['id'] != source['id'] or source['lookup_key'] != binding['lookup_key']
                        or lookup_key(source.get('orthography')) != source['lookup_key']
                        or evidence['english_preview'] != _preview_eligibility(source)
                        or evidence['english_preview'].get('eligible') is not True):
                    return {}
                senses, seen = [], {}
                for sense in source['dictionary_senses']:
                    identity = sense.get('id')
                    form_scope = sense.get('form_scope') or {}
                    if (not identity or (identity in seen and seen[identity] != sense)
                            or not _english(sense) or sense.get('evidence_type') != 'dictionary_sense'
                            or not isinstance(sense.get('text'), str) or not sense['text'].strip()
                            or sense.get('lexicon_entry_id') != source['parent_lexicon_entry_id']
                            or sense.get('entry_id') != source['parent_entry_id']
                            or any(sense.get(key) != source.get(key) for key in ('source_url', 'raw_sha256', 'raw_path'))
                            or not re.fullmatch(r'[0-9a-f]{64}', str(sense.get('raw_sha256') or ''))
                            or not sense.get('source_locator') or form_scope.get('relation') != 'variant'
                            or form_scope.get('text') != source['orthography']
                            or form_scope.get('source_locator') != source['source_locator']):
                        return {}
                    if identity not in seen:
                        senses.append(identity)
                    seen[identity] = sense
                if senses:
                    refs.append({'binding_ref': binding['id'], 'subentry_ref': identifier, 'sense_refs': senses,
                                 'inventory_ref': inventory_id, 'ranking_status': 'unsupported_source_type',
                                 'status': 'unresolved_machine_lemma_dictionary_alternative'})
            if refs:
                output[binding['candidate_id']] = refs
        return output
    except (KeyError, TypeError, ValueError, AttributeError):
        return {}


def interlinear_reading(result):
    """Project exact tokens; links/colors are conditional, not validated syntax."""
    selection = result['selection']
    original = result.get('tokens') or []
    syntax = result.get('syntax') or {}
    syntax_rows = syntax.get('tokens') or [] if syntax.get('state', syntax.get('status')) == 'ready' else []
    by_span = {(row.get('absolute_start'), row.get('absolute_end')): row for row in syntax_rows
               if row.get('prediction_status') != 'not_applicable'}
    ranks = {row.get('token_id'): row for row in (result.get('ranking') or {}).get('items') or []}
    projected, linked, pending = [], {}, []
    for token in original:
        row = {key: deepcopy(token.get(key)) for key in ('id', 'text', 'kind', 'start', 'end', 'start_utf16', 'end_utf16')}
        row['token_id'] = token['id']
        for key in ('form', 'editorial_reconstruction', 'supplied_letters', 'supplied_whole_word', 'uncertain_letters'):
            if token.get(key) is not None and (key != 'form' or token.get('form') != token.get('text')):
                row[key] = deepcopy(token[key])
        if token.get('kind') != 'word':
            projected.append(row)
            continue
        predicted = by_span.get((token.get('start'), token.get('end')))
        if predicted is None and (token.get('text') or '').endswith(tuple("’'ʼ᾽")):
            # The syntax tokenizer may split off an elision apostrophe.
            predicted = by_span.get((token.get('start'), token.get('end') - 1))
        if predicted and predicted.get('text') not in (token.get('text'), (token.get('text') or '')[:-1]):
            predicted = None
        if predicted:
            predicted = {**predicted, 'agreement_partners': _agreement_partners(predicted, syntax_rows)}
        partial = token.get('partial_word') or token.get('editorial_fragment') or token.get('damaged_piece')
        boundary_uncertain = bool(token.get('lacuna_boundary_uncertain'))
        if token.get('damaged_piece'):
            row['damaged_piece'] = True
        chosen, basis, count = (None, 'partial_word', 0) if partial else _choose(
            token, predicted, None if boundary_uncertain else ranks.get(token['id']))
        candidates = [] if partial else [
            *[item for item in [*(token.get('source_candidates') or []), *(token.get('contextual_candidates') or [])] if _exact(item, token)],
            *[item for item in (token.get('machine') or {}).get('machine_candidates') or [] if _exact(item, token, True)]]
        # A conflict is recorded when the prediction disagrees with the chosen
        # parse (on a feature or on the lemma), or with every candidate. It
        # flags the disagreement; it does not erase a full source parse.
        disagrees = lambda item: _contradicts(item, predicted) or _lemma_agrees(item, predicted) is False
        conflict = bool(predicted and (chosen and disagrees(chosen)
                        or not chosen and candidates and all(disagrees(item) for item in candidates)))
        consensus, parse_support = _morphology_consensus(candidates, predicted) if not chosen and not partial else ({}, [])
        consensus_basis, consensus_group = 'source_morphology_consensus', None
        if not chosen and not consensus and not partial and predicted and candidates:
            # Several lemma entries can tie for the best fit while stating the
            # same full parse (ἐγώ / ἐμέ for μοι). The parse is then settled
            # even though the lemma is not; every alternative stays listed.
            ranked = rank_candidates(candidates, predicted)
            # Near-ties (within the homograph margin) form the group. If one
            # parse in the group extends all the others, it is the consensus;
            # otherwise only the features every member states.
            top = [item for item in ranked if ranked[0]['score'] - item['score'] < 0.5]
            # A vocative that differs from a nominative member only in case is
            # the same form; it stays listed but does not blur the consensus.
            nominatives = [canonical_features(item['candidate']) for item in top
                           if canonical_features(item['candidate']).get('Case') == 'Nom']
            top = [item for item in top if not (canonical_features(item['candidate']).get('Case') == 'Voc'
                   and {**canonical_features(item['candidate']), 'Case': 'Nom'} in nominatives)]
            parses = [canonical_features(item['candidate']) for item in top]
            maximal = [parse for parse in parses if parse and all(other.items() <= parse.items() for other in parses)]
            if maximal:
                shared = dict(maximal[0])
            else:
                shared = {key: value for key, value in parses[0].items()
                          if all(parse.get(key) == value for parse in parses)}
            if shared and _agreements(top[0]['candidate'], predicted) >= 1:
                consensus, parse_support = shared, [candidate_identity(item['candidate']) for item in top]
                consensus_basis = 'morphology_ranked_parse_consensus'
                consensus_group = [item['candidate'] for item in top]
        lexical_conflict = _lexical_prediction_conflict(token, predicted) if not chosen and not consensus and not partial else None
        conflict = conflict or bool(lexical_conflict)
        features = canonical_features(chosen) if chosen else consensus or (canonical_features(predicted or {}) if not partial and not conflict else {})
        if features and 'POS' not in features and predicted:
            # A source row may state case/number/gender without a part of speech;
            # the prediction's class fills it only when it fits the parse's shape.
            predicted_pos = canonical_features(predicted).get('POS')
            nominal = any(key in features for key in ('Case', 'Gender')) and not any(key in features for key in ('Tense', 'Mood', 'Person'))
            verbal = any(key in features for key in ('Tense', 'Mood', 'Person', 'VerbForm'))
            if predicted_pos and ((nominal and predicted_pos in _NOMINAL_POS) or (verbal and predicted_pos == 'VERB')):
                features = {**features, 'POS': predicted_pos}
                row['pos_from_prediction'] = True
        if (features and chosen and chosen.get('candidate_kind') == 'pattern_analysis' and 'Gender' not in features
                and 'Case' in features and predicted and canonical_features(predicted).get('Gender')):
            # An ending-only analysis of an unknown word (a name) cannot state
            # gender; the prediction's gender is taken, and labelled as such.
            features = {**features, 'Gender': canonical_features(predicted)['Gender']}
            row['gender_from_prediction'] = True
        # An unresolved candidate set must not inherit an arbitrary dictionary
        # sense; a standalone model morphology remains explicitly a prediction.
        row.update(lemma=chosen.get('lemma') if chosen else None, features=features,
                   parse_short=compact_parse(features), gloss=_gloss(chosen, token),
                   status='selected' if chosen else basis, selection_basis=basis if chosen or partial else 'syntax_prediction' if predicted else basis,
                   candidate_id=chosen.get('id') if chosen else None, agreement_group_id=None,
                   alternative_count=count, source_candidate=deepcopy(chosen) if chosen else None,
                   syntax_token_id=predicted.get('id') if predicted else None)
        if consensus:
            row['selection_basis'] = consensus_basis
            row['supporting_parse_candidate_ids'] = parse_support
        elif conflict and not chosen:
            row['selection_basis'] = 'lexical_source_syntax_conflict' if lexical_conflict else 'parser_syntax_conflict'
        if lexical_conflict:
            row['lexical_prediction_check'] = lexical_conflict
        row['syntax_conflict'] = conflict
        # Every full parse, ranked by its fit to the contextual prediction.
        # The order is a proposal; all alternatives stay visible.
        row['morphology_ranking'] = [
            {'candidate_id': candidate_identity(item['candidate']), 'lemma': item['candidate'].get('lemma'),
             'parse_short': compact_parse(canonical_features(item['candidate'])), 'score': item['score'],
             'basis': candidate_basis(item['candidate']),
             **({'normalised_query': item['candidate']['normalised_query'], 'normalisation_rule': item['candidate'].get('normalisation_rule')}
                if item['candidate'].get('normalised_query') else {})}
            for item in rank_candidates(candidates, predicted)] if candidates else []
        row['candidate_meanings'] = [
            {'candidate_id': candidate_identity(item), 'lemma': item.get('lemma'),
             'features': canonical_features(item), 'parse_short': compact_parse(canonical_features(item)),
             'gloss': _gloss(item, token),
             'basis': candidate_basis(item),
             'status': 'unresolved_alternative',
             **({'normalised_query': item['normalised_query'], 'normalisation_rule': item.get('normalisation_rule'),
                 'normalisation_note': item.get('normalisation_note')} if item.get('normalised_query') else {})}
            for item in candidates]
        machine_subentries = _machine_subentry_alternatives(result, token)
        for meaning in row['candidate_meanings']:
            refs = machine_subentries.get(meaning['candidate_id'])
            if refs and meaning['basis'] == 'machine_analysis':
                meaning['machine_subentry_alternatives'] = refs
        # Source page links form a separate inventory: never make them exact
        # printed-form candidates or let a statistical POS filter erase them.
        from .linked_dictionary import validated_candidates
        for item in validated_candidates(token) if not partial else []:
            row['candidate_meanings'].append({
                'candidate_id': item['id'], 'lemma': item['lemma'],
                'features': deepcopy(item['features']), 'parse_short': item['parse_short'],
                'basis': item['basis'], 'linked_path': deepcopy(item['linked_path']),
                'status': 'unresolved_alternative',
                'gloss': {'text': None, 'status': 'alternatives', 'entry_id': item['gloss_entry_id'],
                          'alternatives': deepcopy(item['senses']),
                          'selection_basis': 'source_linked_alternatives_not_contextual'}})
        if not chosen and not partial:
            # When the parse came from a ranked tie group, a sense shared by
            # that group (καί "and" across its dictionary rows) is enough.
            shared = _shared_dictionary_sense(consensus_group or candidates, token)
            if shared:
                row['gloss'] = shared
        if boundary_uncertain:
            # Keep every literal definition/parse visible, but a plausible
            # whole-word hypothesis cannot settle a damaged source boundary.
            row.update(lacuna_boundary_uncertain=True,
                       lacuna_boundary_evidence=deepcopy(token.get('lacuna_boundary_evidence') or []),
                       status='conditional', selection_basis='conditional_lacuna_boundary',
                       conditional_lookup_basis=basis, word_attestation=False, occurrence_verified=False,
                       analysis_scope='conditional_on_word_boundary',
                       scope_note='Word boundary uncertain beside printed dots; displayed parses and literal definitions are conditional alternatives, not a restored or verified occurrence.')
            row['gloss']['conditional_on'] = 'complete_word_boundary'
            for meaning in row['candidate_meanings']:
                meaning.update(status='conditional_alternative', word_attestation=False,
                               occurrence_verified=False, analysis_scope='conditional_on_word_boundary')
        projected.append(row)
        pending.append((row, token, predicted, partial))
        if predicted and not partial and not conflict and not boundary_uncertain:
            linked[(predicted.get('sentence_id'), predicted['id'])] = (row, predicted)
    # Second pass: a word left unresolved by the prediction can be settled by
    # the *chosen* parses of its adjacent words (θεσπεσία nom. fem. sg. settles
    # ἄχω as nominative), which are better evidence than the model's guesses.
    words_only = [entry for entry in pending if entry[0].get('kind') == 'word']
    for index, (row, token, predicted, partial) in enumerate(words_only):
        if partial or row.get('status') == 'selected' or row.get('lacuna_boundary_uncertain'):
            continue
        neighbours = []
        for offset in (-1, 1):
            if 0 <= index + offset < len(words_only):
                other = words_only[index + offset][0]
                if other.get('status') == 'selected' and other['features'].get('POS') in _NOMINAL_POS \
                        and any(key in other['features'] for key in ('Case', 'Number', 'Gender')):
                    neighbours.append({'text': other.get('text'), 'relation': 'adjacent', 'role': 'resolved_neighbour',
                                       'features': {key: other['features'][key] for key in ('Case', 'Number', 'Gender') if key in other['features']}})
        if not neighbours:
            continue
        base = predicted if predicted and canonical_features(predicted) else {'agreement_partners': []}
        augmented = {**base, 'agreement_partners': [*(base.get('agreement_partners') or []), *neighbours]}
        chosen, basis, count = _choose(token, augmented, None)
        if not chosen:
            continue
        features = canonical_features(chosen)
        row.update(lemma=chosen.get('lemma'), features=features, parse_short=compact_parse(features),
                   gloss=_gloss(chosen, token), status='selected', selection_basis='morphology_ranked_by_neighbour_parse',
                   candidate_id=chosen.get('id'), alternative_count=count, source_candidate=deepcopy(chosen),
                   neighbour_evidence=[{'text': n['text'], 'features': n['features']} for n in neighbours])
        row.pop('supporting_parse_candidate_ids', None)
    edges = []
    for row, predicted in linked.values():
        pair = linked.get((predicted.get('sentence_id'), predicted.get('head')))
        if not pair:
            continue
        head, head_prediction = pair
        relation = str(predicted.get('deprel') or '').split(':')[0]
        left, right = row['features'], head['features']
        if relation not in {'amod', 'det', 'nmod'}:
            continue
        if relation == 'nmod' and not (left.get('POS') == 'ADJ' and right.get('POS') in {'NOUN', 'PRON'}):
            continue
        if predicted.get('sentence_id') != head_prediction.get('sentence_id'):
            continue
        if not all(left.get(key) and left[key] == right.get(key) for key in ('Case', 'Number')):
            continue
        if left.get('Gender') and right.get('Gender') and left['Gender'] != right['Gender']:
            continue
        lo, hi = sorted((row['start'], head['start']))
        if any(lo <= token['start'] <= hi and (token.get('kind') == 'editorial' or token.get('partial_word') or token.get('editorial_fragment') or token.get('lacuna_boundary_uncertain')
               or token.get('text') in {'.', ';', '·', '·', '!', '?'}) for token in original):
            continue
        edges.append({'dependent': row['token_id'], 'head': head['token_id'], 'relation': relation})
    groups = []
    # Connected modifier components, not buckets of all words in one case.
    remaining = list(edges)
    while remaining:
        component = [remaining.pop(0)]
        ids = {component[0]['dependent'], component[0]['head']}
        changed = True
        while changed:
            changed = False
            for edge in remaining[:]:
                if ids & {edge['dependent'], edge['head']}:
                    component.append(edge); ids.update((edge['dependent'], edge['head']))
                    remaining.remove(edge); changed = True
        members = [row for row in projected if row['token_id'] in ids]
        # An unknown-gender head must not bridge conflicting gender groups.
        if len({row['features']['Gender'] for row in members if row['features'].get('Gender')}) > 1:
            continue
        features = {key: members[0]['features'][key] for key in ('Case', 'Gender', 'Number')
                    if members[0]['features'].get(key) and all(row['features'].get(key) == members[0]['features'][key] for row in members)}
        group_id = f'g{len(groups) + 1}'
        for row in members:
            row['agreement_group_id'] = group_id
        groups.append({'id': group_id, 'token_ids': [row['token_id'] for row in members], 'features': features,
                       'label': compact_parse(features), 'evidence_type': 'predicted_dependency_agreement', 'relations': component})
    ready = any(row.get('parse_short') or (row.get('gloss') or {}).get('text') for row in projected)
    return {'version': 1, 'status': 'proposed' if ready else 'unavailable', 'label': 'Proposed reading', 'text': selection['text'],
            'readings': [{'id': 'syntax-1', 'label': 'Proposed reading', 'status': 'proposed' if ready else 'unavailable', 'tokens': projected, 'groups': groups}],
            'warnings': ['One proposed reading, not a ranked set of joint sentence analyses. Colors indicate predicted modifier agreement, not independently verified syntax.',
                         'Dictionary previews retain source wording; a first listed sense is not a contextually adjudicated translation.']}
