"""Bounded, source-derived alternatives for strict multiword retrieval.

No paradigms or senses are generated. Operational ceilings reject a request;
they never silently remove alternatives from an otherwise successful query.
"""
from contextlib import closing
import json
from .morphology import query_variants, normalize as morphology_key
from .textutils import normalize

MAX_GROUP_KEYS = 2000
MAX_TOTAL_KEYS = 20000
MAX_PROVENANCE_REFS = 8


class SequenceLimit(ValueError):
    pass


def build_groups(words, morphology, evidence):
    groups, cache = [], {}
    morphology._load()
    for index, word in enumerate(words):
        if word not in cache:
            choices = {}
            abbreviated = set()

            def add(form, ref):
                key = normalize(form)
                if not key or any(char.isspace() for char in key):
                    return
                refs = choices.setdefault(key, [])
                if ref not in refs and len(refs) < MAX_PROVENANCE_REFS:
                    refs.append(ref)
                elif ref not in refs:
                    abbreviated.add(key)
                if len(choices) > MAX_GROUP_KEYS:
                    raise SequenceLimit('A query word has too many indexed alternatives; use Exact words or a more specific form. No partial expansion was searched.')

            keys = query_variants(word)
            for key in dict.fromkeys([normalize(word), *keys]):
                add(key, {'kind': 'literal_query', 'form': word})
            lemmas = set(morphology.expansion_lemmas_for_form(word))
            lemma_refs = {}
            for key in keys:
                for row in [*morphology._forms.get(key, ()), *morphology._entries.get(key, ())]:
                    lemma = row.get('lemma')
                    if lemma not in lemmas:
                        continue
                    ref = {name: row[name] for name in ('source', 'source_url', 'document_id', 'sentence_id', 'token_id') if row.get(name)}
                    ref.update(kind='source_lemma_link', lemma=lemma, form=word)
                    lemma_refs.setdefault(lemma, []).append(ref)
            # The public source-candidate projection has a hard 100-row ceiling.
            # A saturated response cannot establish a complete choice set.
            found = evidence.candidate_analyses(word, limit=100)
            candidates = found.get('candidates', [])
            if len(candidates) >= 100:
                raise SequenceLimit('A query word exceeds the source-analysis limit; use Exact words or a more specific form. No incomplete candidate inventory was searched.')
            for candidate in candidates:
                if candidate.get('status') != 'source_claim' or candidate.get('assertion_type') == 'model_inference':
                    continue
                if candidate.get('source_projection_status') == 'incomplete_explicit_alternatives':
                    # Do not promote an explicitly incomplete projection to a
                    # complete morphological expansion contract.
                    raise SequenceLimit('A source analysis has unindexed grammatical alternatives. Use Exact words; strict form expansion is not complete for this query.')
                targets = [candidate.get('lemma'), *[target.get('word') for target in candidate.get('lemma_targets') or [] if isinstance(target, dict)]]
                for lemma in targets:
                    if not isinstance(lemma, str) or not lemma:
                        continue
                    lemmas.add(lemma)
                    for claim_id in candidate.get('claim_ids') or []:
                        lemma_refs.setdefault(lemma, []).append({'kind': 'source_lemma_link', 'claim_id': claim_id, 'lemma': lemma, 'form': word})
            # Explicit source equivalent forms are separate retrieval links,
            # never a model-selected grammatical identity.
            raw_claims = evidence.lookup(word, limit=None).get('claims', [])
            for claim in raw_claims:
                if claim.get('predicate') != 'equivalent_form' or claim.get('status') != 'source_claim' or claim.get('assertion_type') == 'model_inference':
                    continue
                obj = claim.get('object') or {}
                values = [obj.get('form'), *[target.get('word') for target in obj.get('targets') or [] if isinstance(target, dict)]]
                for value in values:
                    if isinstance(value, str):
                        for key in query_variants(value):
                            add(key, {'kind': 'equivalent_form', 'claim_id': claim['id'], 'form': value})
            for lemma in sorted(lemmas):
                for form in morphology.expansion_forms_for_lemma(lemma):
                    for row in morphology._forms.get(morphology_key(form), ()):
                        if row.get('form') != form or morphology_key(row.get('lemma', '')) != morphology_key(lemma):
                            continue
                        ref = {name: row[name] for name in ('source', 'source_url', 'document_id', 'sentence_id', 'token_id') if row.get(name)}
                        ref.update(kind='source_indexed_form', form=form, lemma=lemma)
                        add(form, ref)
                        for link in lemma_refs.get(lemma, []):
                            add(form, link)
            # Full accepted table query, not forms_for_lemma's silent 500 cap.
            for lemma in sorted({word, *lemmas}):
                lemma_keys = query_variants(lemma)
                if not lemma_keys:
                    continue
                with closing(evidence._connect()) as con:
                    rows = con.execute(
                        "SELECT DISTINCT e.form,c.id,c.evidence_json FROM claims c INDEXED BY claims_form_idx JOIN form_edges e ON e.claim_id=c.id "
                        "WHERE c.normalized_form IN (SELECT value FROM json_each(?)) AND c.passage_id IS NULL "
                        "AND c.predicate='morphology' AND c.status='source_claim' AND c.assertion_type!='model_inference'",
                        (json.dumps(lemma_keys),))
                    for row in rows:
                        ref = {'kind': 'dictionary_listed_form', 'claim_id': row['id'], 'form': row['form'], 'lemma': lemma}
                        sources = json.loads(row['evidence_json'])
                        if sources and sources[0].get('source_url'):
                            ref['source_url'] = sources[0]['source_url']
                        add(row['form'], ref)
                        for link in lemma_refs.get(lemma, []):
                            add(row['form'], link)
            cache[word] = (choices, abbreviated)
        groups.append({'query_index': index, 'query_term': word, 'alternatives': cache[word][0],
                       'abbreviated_provenance_keys': cache[word][1]})
        if sum(len(group['alternatives']) for group in groups) > MAX_TOTAL_KEYS:
            raise SequenceLimit('The complete query has too many indexed form alternatives; shorten it or use Exact words. No partial query was searched.')
    return groups
