/* Source-backed display projection only. No generated senses or parsing. */
(() => {
  'use strict';
  const MAX_MEANINGS = 3;
  const MAX_ANALYSES = 4;
  const MAX_EXCERPT = 200;
  const list = (value) => Array.isArray(value) ? value : [];
  const text = (value) => typeof value === 'string' ? value.trim() : '';
  const identity = (value) => text(value).normalize('NFC'); // Never fold distinct accented lemmas.
  const SOURCE_NAMES = new Map([
    ['Kaikki Ancient Greek postprocessed enwiktionary extraction', 'Wiktionary'],
    ['Wiktionary / Kaikki', 'Wiktionary'], ['Wiktionary', 'Wiktionary'], ['Kaikki', 'Wiktionary'],
    ['PerseusDL LSJ TEI', 'LSJ'], ['LSJ', 'LSJ'],
    ['Perseus Autenrieth TEI via Homerica', 'Autenrieth'], ['Autenrieth', 'Autenrieth'],
    ['Perseus Middle Liddell TEI (Hopper open-source texts)', 'Middle Liddell'],
    ['LSJ (Logeion edition, H. Dik) TEI', 'LSJ (Logeion)'],
    ['Perseus Cunliffe TEI via Homerica', 'Cunliffe'],
    ['Dodson Greek Lexicon (NT; public domain)', 'Dodson (NT)'],
    ['PerseusDL Greek Dependency Treebank v1.6', 'Perseus treebank'], ['Perseus treebank', 'Perseus treebank']
  ]);
  const friendlySourceName = (source) => SOURCE_NAMES.get(text(source)) || text(source);
  const rejected = (row) => !row || row.quarantined === true || row.source_consistent === false ||
    row.source_inconsistent === true || row.assertion_type === 'model_inference' ||
    [row.status, row.quality, row.link_status, row.lemma_link_status].some(value =>
      /(?:quarantin|inconsisten|rejected|needs_review|machine_proposed)/i.test(text(value)));
  function sourceUrl(value) {
    try {
      const url = new URL(text(value));
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
    } catch { return ''; }
  }
  function greekFormKey(value) {
    // Fold accents, breathing/quantity marks, case and final sigma only.
    // In particular, a suffix's hyphen and an elision mark are significant.
    return text(value).normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
      .replace(/ς/g, 'σ').replace(/[’ʼ᾽᾿]/g, "'").normalize('NFC');
  }
  function eligibleWikiMatch(match, row, query) {
    const matched = match?.kind === 'headword' ? text(match.word) || text(row.headword) :
      match?.kind === 'listed_form' ? text(match.form?.form) : '';
    // No local transliteration guesses: /api/word remains responsible for
    // transliterated lookup. Wiki previews require comparable Greek forms.
    return /\p{Script=Greek}/u.test(query) && !!matched && greekFormKey(matched) === greekFormKey(query);
  }
  function exactWikiMatch(match, row, query) {
    return match?.kind === 'headword'
      ? identity(row.headword) === identity(query) && identity(match.word || row.headword) === identity(query)
      : match?.kind === 'listed_form' && identity(match.form?.form) === identity(query);
  }
  function formOfSense(sense) {
    return list(sense?.form_of).length > 0 || list(sense?.tags).some(tag =>
      typeof tag === 'string' && tag.toLowerCase() === 'form-of');
  }
  function grammaticalTags(tags) {
    const metadata = new Set(['canonical', 'alternative', 'romanization', 'transliteration', 'form-of', 'alt-of']);
    return list(tags).filter(tag => typeof tag === 'string' && !metadata.has(tag.toLowerCase()));
  }
  function excerpt(value) {
    const original = text(value);
    if (!original) return null;
    if (original.length <= MAX_EXCERPT) return { text: original, truncated: false };
    let end = MAX_EXCERPT;
    // A literal prefix with explicit ellipsis, not a rewritten definition.
    const space = original.slice(0, end).search(/\s+\S*$/u);
    if (space > MAX_EXCERPT / 2) end = space;
    if (/[\uD800-\uDBFF]/u.test(original[end - 1])) end--;
    return { text: original.slice(0, end).trimEnd() + '…', truncated: true };
  }
  function isCandidateQuery(query) {
    const value = text(query);
    // Phrases/descriptions need an explicitly indexed multiword entry; do not
    // infer one by decomposing a query. Beta Code punctuation is accepted.
    return value.length > 0 && value.length <= 80 && /\p{L}/u.test(value) &&
      !/\s/u.test(value) && /^[\p{L}\p{M}\d*()\/\\=+|'’ʼ᾽᾿.,-]+$/u.test(value);
  }
  function entryId(entry) {
    return text(entry.id) || `${text(entry.source_url)}#${text(entry.entry_id)}`;
  }
  function exactCandidate(candidate) {
    return !rejected(candidate) && candidate.edit_distance === 0 &&
      ['indexed_form', 'lexicon_headword'].includes(candidate.match_kind) && !!identity(candidate.lemma);
  }
  function readableAnalysis(candidate) {
    const description = text(candidate.analysis_text);
    if (description) return description;
    const raw = text(candidate.analysis);
    // Compact source postags stay in the full inspector. A missing decoder
    // does not turn an opaque code into another human-readable parse choice.
    if (/\bpostag\b|\bpos[- ]?tag\b/i.test(text(candidate.analysis_format)) ||
        /^(?:[a-z-][123-][spd-]|[a-z][0-9])[a-z0-9-]{4,}$/i.test(raw)) return '';
    return raw;
  }
  function meaning(value, source, url, extra = {}) {
    const shortened = excerpt(value);
    return shortened && url ? { ...shortened, source, source_url: url, ...extra } : null;
  }
  function sourcedDefinitionExcerpt(entry, url) {
    // The API supplies this only after checking the accepted LSJ raw hash and
    // extracting a bounded source clause. Keep the full gloss as fallback if
    // the display projection cannot bind that clause to this exact entry.
    const provenance = entry.definition_excerpt_provenance;
    const locator = provenance?.source_locator;
    if (!url || text(entry.source) !== 'PerseusDL LSJ TEI' || !text(entry.definition_excerpt) ||
        !text(entry.entry_id) || text(provenance?.entry_id) !== text(entry.entry_id) ||
        sourceUrl(provenance?.source_url) !== url ||
        !/^[a-f0-9]{64}$/i.test(text(provenance?.raw_sha256)) ||
        !text(provenance?.method) ||
        locator?.offset_basis !== 'uncompacted Greek-span-rendered TEI entry' ||
        !Number.isInteger(locator?.boundary_ordinal) || locator.boundary_ordinal < 1 ||
        !Number.isInteger(locator?.rendered_start) ||
        !Number.isInteger(locator?.rendered_end) ||
        locator.rendered_start < 0 || locator.rendered_end <= locator.rendered_start) return null;
    return { text: entry.definition_excerpt, provenance };
  }
  function definitionExcerpt(entry) {
    if (!entry || typeof entry !== 'object' || rejected(entry)) return null;
    if (structuredSensesPresent(entry)) {
      const sense = structuredSenses(entry)[0];
      return sense ? { text: sense.text, provenance: sense } : null;
    }
    return sourcedDefinitionExcerpt(entry, sourceUrl(entry.source_url));
  }
  function structuredSensesPresent(entry) {
    return Object.hasOwn(entry, 'dictionary_senses') || Object.hasOwn(entry, 'dictionary_senses_status');
  }
  function structuredSenses(entry) {
    const id = entryId(entry);
    return list(entry.dictionary_senses).filter(sense => !rejected(sense) && text(sense.id) &&
      text(sense.lexicon_entry_id || sense.entry_id) === id && sense.evidence_type === 'dictionary_sense' &&
      /^(?:en|eng)(?:-[a-z0-9]{2,8})*$/i.test(text(sense.language)) && text(sense.text) &&
      sourceUrl(sense.source_url));
  }
  function unique(rows, key) {
    const seen = new Set();
    return rows.filter(row => { const value = key(row); if (seen.has(value)) return false; seen.add(value); return true; });
  }
  function sourceTense(candidate, query) {
    if (!exactCandidate(candidate) || !sourceUrl(candidate.source_url)
      || candidate.candidate_kind === 'machine_analysis' || candidate.basis === 'machine_analysis'
      || identity(candidate.matched_form) !== identity(query)) return null;
    const names = {pres:'Pres',present:'Pres',aor:'Aor',aorist:'Aor',imp:'Imp',imperfect:'Imp',
      perf:'Perf',perfect:'Perf',pqp:'Pqp',pluperfect:'Pqp',fut:'Fut',future:'Fut',futperf:'FutPerf','future perfect':'FutPerf',past:'Past'};
    const values = [];
    const feature = candidate.features?.Tense ?? candidate.features?.tense;
    const featureValues = Array.isArray(feature) ? feature : typeof feature === 'string' ? feature.split(',') : [];
    if (feature != null && (!featureValues.length || featureValues.some(value => !names[text(value).toLowerCase()]))) return null;
    for (const value of featureValues)
      if (names[text(value).toLowerCase()]) values.push(names[text(value).toLowerCase()]);
    // Whole source tags and backend-expanded Perseus labels only. Never
    // derive tense from an ending, English meaning or model prediction.
    const labels = {present:'Pres',aorist:'Aor',imperfect:'Imp',perfect:'Perf',pluperfect:'Pqp',
      future:'Fut','future perfect':'FutPerf',past:'Past'};
    for (const value of [...list(candidate.source_tags), ...text(candidate.analysis_text).split(' · ')])
      if (labels[text(value).toLowerCase()]) values.push(labels[text(value).toLowerCase()]);
    const known = new Set(values);
    return known.size === 1 ? [...known][0] : null;
  }
  function sourcePresentRestriction(sense, entry) {
    const sourceSense = list(sense.sense_path).at(-1)?.id;
    if (!sourceSense || sense.extraction_method !== 'tei-definition-spans-v4'
      || sense.source !== 'PerseusDL LSJ TEI' || typeof entry.rendered_entry_text !== 'string') return null;
    const basis = 'uncompacted Greek-span-rendered TEI entry';
    return list(sense.morphology_restrictions).find(restriction => {
      const scope = restriction?.scope, locator = restriction?.source_locator, tense = restriction?.tense_source_locator;
      const targets = scope?.target_source_sense_ids, points = [locator?.rendered_start,locator?.rendered_end,tense?.rendered_start,tense?.rendered_end];
      return restriction?.kind === 'source_tense_only' && restriction.feature === 'Tense'
        && Array.isArray(restriction.allowed_values) && restriction.allowed_values.length === 1 && restriction.allowed_values[0] === 'Pres'
        && restriction.extraction_rule === 'explicit_terminal_two_foregoing_present_senses_v1'
        && scope?.kind === 'preceding_meaning_units' && scope.count === 2 && Array.isArray(targets)
        && targets.length === 2 && new Set(targets).size === 2 && targets.includes(sourceSense)
        && targets.every(id => list(entry.dictionary_senses).some(item => list(item.sense_path).at(-1)?.id === id))
        && restriction.lexicon_entry_id === entryId(entry) && restriction.lexicon_entry_id === sense.lexicon_entry_id
        && restriction.entry_id === sense.entry_id && restriction.source === sense.source
        && restriction.source_url === sense.source_url && sourceUrl(sense.source_url) === sourceUrl(entry.source_url)
        && /^[a-f0-9]{64}$/i.test(text(sense.raw_sha256)) && restriction.raw_sha256 === sense.raw_sha256
        && restriction.raw_path === sense.raw_path && typeof restriction.raw_path === 'string'
        && locator?.node_path && tense?.node_path && points.every(Number.isInteger)
        && 0 <= points[0] && points[0] <= points[2] && points[2] < points[3] && points[3] <= points[1]
        && locator.offset_basis === basis && tense.offset_basis === basis && sense.source_locator?.offset_basis === basis
        // Display text is whitespace-compacted, while the audited locators
        // address the uncompacted TEI rendering. Do not misapply those offsets.
        && text(restriction.source_text) && entry.rendered_entry_text.includes(restriction.source_text);
    }) || null;
  }
  function formRestrictedSenseIds(entry, candidates, query, unresolvedEntry = false) {
    const tenses = candidates.map(candidate => sourceTense(candidate, query));
    return new Set(!unresolvedEntry && tenses.length && tenses.every(tense => tense && tense !== 'Pres')
      ? structuredSenses(entry).filter(sense => sourcePresentRestriction(sense, entry)).map(sense => sense.id) : []);
  }
  function candidateDefinitionExcerpt(entry, candidate, query) {
    if (!entry || rejected(entry) || !structuredSensesPresent(entry)) return definitionExcerpt(entry);
    const id = entryId(entry);
    // Candidate-specific display, never the tense of some other candidate in
    // the word response. An unresolved or nonexact link cannot exclude senses.
    const bound = exactCandidate(candidate) && identity(candidate.lemma) === identity(entry.lemma)
      && (candidate.gloss_entry_id === id || list(candidate.lexicon_entry_ids).includes(id))
      && candidate.lemma_link_status !== 'ambiguous_source_lemmas';
    const incompatible = bound ? formRestrictedSenseIds(entry, [candidate], query) : new Set();
    const sense = structuredSenses(entry).find(item => !incompatible.has(item.id));
    return sense ? { text: sense.text, provenance: sense } : null;
  }
  function lexicalVariantPreview(form, variants, supportingClaims) {
    const claims = list(supportingClaims), ids = new Map();
    for (const claim of claims) {
      if (ids.has(claim?.id)) ids.set(claim.id, null); else if (claim?.id) ids.set(claim.id, claim);
    }
    return list(variants).flatMap(variant => {
      if (rejected(variant) || variant?.candidate_kind !== 'dictionary_variant' || variant.status !== 'source_claim'
        || variant.assertion_type !== 'extracted_annotation' || !text(variant.id) || !text(variant.entry_id)
        || variant.scope !== 'exact_source_listed_lexical_variant_not_morphological_parse'
        || !/^enwiktionary-kaikki-ancient-greek-/.test(text(variant.source_family))
        || identity(variant.matched_form) !== identity(form) || identity(variant.matched_object_form?.form) !== identity(form)
        || !identity(variant.lemma) || identity(variant.entry_headword) !== identity(variant.lemma)
        || variant.analysis || variant.features || !list(variant.claim_ids).length
        || !list(variant.claim_ids).every(id => ids.get(id) && !rejected(ids.get(id)))) return [];
      const head = ids.get(`${variant.entry_id}:lemma:entry`), morphology = ids.get(`${variant.entry_id}:morphology:entry`);
      const relation = list(variant.claim_ids).map(id => ids.get(id)).find(claim => claim?.predicate === 'dialect_label');
      if (head?.predicate !== 'lemma' || morphology?.predicate !== 'morphology'
        || identity(head.object?.lemma) !== identity(variant.lemma) || identity(head.subject?.form) !== identity(variant.lemma)
        || identity(morphology.object?.lemma) !== identity(variant.lemma)
        || identity(relation?.subject?.form) !== identity(form) || identity(relation?.object?.source_form?.form) !== identity(form)
        || identity(relation?.object?.lemma) !== identity(variant.lemma)) return [];
      const meanings = list(variant.entry_senses).flatMap(sense => {
        const claim = ids.get(sense?.claim_id), proof = list(claim?.evidence).find(item => item?.locator === sense.locator);
        if (!sense || sense.scope !== 'general_dictionary_entry_not_contextually_adjudicated'
          || sense.entry_id !== variant.entry_id || !list(variant.entry_sense_claim_ids).includes(sense.claim_id)
          || !claim || rejected(claim) || claim.predicate !== 'sense_gloss'
          || !text(sense.source_sense_id).startsWith('en-') || claim.source_family !== variant.source_family
          || identity(claim.object?.lemma) !== identity(variant.lemma) || identity(claim.subject?.form) !== identity(variant.lemma)
          || list(sense.glosses).length !== 1 || !text(sense.glosses[0]) || /[\p{Script=Greek}\r\n]/u.test(sense.glosses[0])
          || list(sense.tags).includes('form-of') || !sourceUrl(sense.source_url)
          || sourceUrl(proof?.source_url) !== sourceUrl(sense.source_url) || proof?.quote !== sense.quote) return [];
        try {
          if (JSON.stringify(JSON.parse(sense.quote)) !== JSON.stringify(sense.glosses)
            || JSON.stringify(claim.object?.glosses) !== JSON.stringify(sense.glosses)) return [];
        } catch { return []; }
        return [{ text: sense.glosses[0], source_url: sourceUrl(sense.source_url), claim_id: sense.claim_id,
          entry_id: sense.entry_id, locator: sense.locator, source_quality: sense.source_quality }];
      });
      if (!meanings.length) return [];
      return [{ id: variant.id, form: variant.matched_form, lemma: variant.lemma,
        source_tags: list(variant.source_tags), meanings, evidence: variant }];
    });
  }
  function linkedDictionaryCandidates(form, inventory) {
    if (!inventory || identity(inventory.form) !== identity(form)
      || !['source-linked-dictionary-inventory-v1', 'source-linked-dictionary-inventory-v2'].includes(inventory.method)
      || inventory.scope !== 'source_linked_candidates_not_exact_surface_or_contextual_attestation'
      || !/^[a-f0-9]{64}$/i.test(text(inventory.inventory_sha256))) return [];
    const counts = new Map();
    for (const candidate of list(inventory.candidates)) counts.set(candidate?.id, (counts.get(candidate?.id) || 0) + 1);
    return list(inventory.candidates).filter(candidate => {
      const path = candidate?.linked_path;
      if (!candidate || counts.get(candidate.id) !== 1 || candidate.basis !== 'source_linked_dictionary_path'
        || !/^linked-path:[a-f0-9]{64}$/i.test(text(candidate.id)) || candidate.candidate_id !== candidate.id
        || !path || !text(path.source_entry_id) || !text(path.target_entry_id)
        || identity(candidate.lemma) !== identity(path.source_headword) || !identity(path.target_headword)
        || candidate.gloss_entry_id !== path.target_entry_id || !list(path.claim_ids).length
        || (path.source_entry_id !== path.target_entry_id && !text(path.relation_id))) return false;
      if (path.match_method === 'exact_source_form_crossreference') {
        if (identity(path.query_anchor?.source_form?.form) !== identity(form)) return false;
      } else if (path.match_method === 'literal_source_form_link') {
        const link = path.source_link;
        if (!text(path.alias_id) || !Array.isArray(link) || link.length !== 2 || typeof link[1] !== 'string'
          || !link[1].endsWith('#Ancient_Greek') || identity(link[1].slice(0, -'#Ancient_Greek'.length)) !== identity(form)
          || identity(link[0]) !== identity(path.printed_form)
          || identity(path.query_anchor?.source_form?.form) !== identity(path.printed_form)) return false;
      } else return false;
      const noun = path.source_noun_metadata;
      const anchorGenders = list(path.query_anchor?.source_form?.tags).filter(tag =>
        ['masculine', 'feminine', 'neuter'].includes(tag));
      if (noun) {
        const proof = noun.source_record_proof, genders = { masculine: 'Masc', feminine: 'Fem', neuter: 'Neut' };
        if (inventory.method !== 'source-linked-dictionary-inventory-v2'
          || noun.method !== 'same-entry-noun-gender-v1'
          || noun.scope !== 'same_source_noun_entry_metadata_not_occurrence_disambiguation'
          || noun.entry_id !== path.source_entry_id || noun.entry_headword !== path.source_headword
          || noun.dictionary_pos !== 'noun' || path.source_dictionary_pos !== 'noun'
          || noun.contextually_selected !== false || proof?.record_id !== path.source_entry_id
          || !/^[a-f0-9]{64}$/i.test(proof?.raw_sha256 || '') || !/^[a-f0-9]{64}$/i.test(proof?.parent_sha256 || '')
          || !sourceUrl(proof?.source_url) || !list(noun.supporting_claim_ids).length
          || !noun.supporting_claim_ids.every(id => typeof id === 'string' && id.startsWith(`${path.source_entry_id}:`))
          || !list(noun.evidence_groups).length || !noun.evidence_groups.every(group =>
            noun.supporting_claim_ids.includes(group.claim_id) && typeof group.source_locator === 'string'
              && group.source_locator.startsWith('/entry/'))) return false;
        if (noun.applied_to_candidate === true) {
          const gender = genders[noun.unambiguous_entry_gender];
          if (!gender || noun.gender_status !== 'single_source_gender' || noun.explicit_form_gender !== null || anchorGenders.length
            || noun.application_basis !== 'same_anchor_noun_metadata' || candidate.features?.Gender !== gender
            || !Array.isArray(noun.dictionary_gender_options) || noun.dictionary_gender_options.length !== 1
            || noun.dictionary_gender_options[0] !== noun.unambiguous_entry_gender) return false;
        } else if (noun.applied_to_candidate !== false || (candidate.features?.Gender
          && !list(path.query_anchor?.source_form?.tags).some(tag => genders[tag] === candidate.features.Gender))) return false;
      }
      if (inventory.method === 'source-linked-dictionary-inventory-v2' && candidate.features?.Gender
        && noun?.applied_to_candidate !== true && !anchorGenders.some(tag =>
          ({ masculine: 'Masc', feminine: 'Fem', neuter: 'Neut' })[tag] === candidate.features.Gender)) return false;
      if (!list(candidate.senses).length) return false;
      return candidate.senses.every(sense => {
        const link = sense?.linked_path;
        return sense?.evidence_type === 'dictionary_sense' && /^en(?:g)?$/i.test(text(sense.language))
          && /^linked-sense:[a-f0-9]{64}$/i.test(text(sense.id)) && text(sense.text)
          && (sense.lexicon_entry_id || sense.entry_id) === path.target_entry_id && sourceUrl(sense.source_url)
          && text(sense.source) && text(sense.source_locator) && /^[a-f0-9]{64}$/i.test(text(sense.raw_sha256))
          && link && ['source_entry_id', 'source_headword', 'target_entry_id', 'target_headword', 'target_etymology_number', 'relation_id']
            .every(key => link[key] === path[key])
          && typeof link.sense_claim_id === 'string' && link.sense_claim_id.startsWith(`${path.target_entry_id}:sense:`);
      });
    });
  }
  function linkedDictionaryGroups(form, inventory) {
    const groups = new Map();
    for (const candidate of linkedDictionaryCandidates(form, inventory)) {
      const path = candidate.linked_path;
      const features = Object.entries(candidate.features || {}).sort(([a], [b]) => a.localeCompare(b));
      // Repeated paradigms may record one analysis several times. Preserve
      // their proof paths, but never merge target homonyms or distinct parses.
      const key = JSON.stringify([path.source_entry_id, path.target_entry_id,
        path.target_etymology_number, path.source_dictionary_pos, path.target_dictionary_pos, features]);
      if (!groups.has(key)) groups.set(key, { lemma: candidate.lemma, target_lemma: path.target_headword,
        target_entry_id: path.target_entry_id, etymology: path.target_etymology_number,
        source_pos: path.source_dictionary_pos, target_pos: path.target_dictionary_pos,
        parse_short: candidate.parse_short, candidates: [], meanings: [] });
      const group = groups.get(key);
      group.candidates.push(candidate);
      for (const sense of candidate.senses) {
        let meaning = group.meanings.find(item => item.id === sense.id);
        if (!meaning) { meaning = { ...sense, supporting_candidate_ids: [] }; group.meanings.push(meaning); }
        meaning.supporting_candidate_ids.push(candidate.id);
      }
    }
    return [...groups.values()];
  }
  function compactView(entries, ambiguous) {
    const byLemma = new Map();
    for (const entry of entries) {
      const key = identity(entry.lemma);
      if (!byLemma.has(key)) byLemma.set(key, []);
      byLemma.get(key).push(entry);
    }
    const eligible = [];
    for (const alternatives of byLemma.values()) {
      const sourceCounts = new Map();
      for (const entry of alternatives) sourceCounts.set(entry.source, (sourceCounts.get(entry.source) || 0) + 1);
      // Same-spelling homographs cannot be identified across dictionaries by
      // spelling alone. Keep their entry identities; don't collapse their parses.
      if ([...sourceCounts.values()].some(count => count > 1)) eligible.push(...alternatives);
      else eligible.push(alternatives.find(entry => entry.meaning_kind === 'structured_dictionary_gloss') || alternatives[0]);
    }
    const selections = new Map();
    let selectedCount = 0;
    // Give separate entries a first excerpt before adding a second/third sense.
    for (let round = 0; round < MAX_MEANINGS && selectedCount < MAX_MEANINGS; round++) {
      for (const entry of eligible) {
        if (selectedCount >= MAX_MEANINGS) break;
        const available = entry.compact_meanings || entry.meanings;
        if (!available[round]) continue;
        if (!selections.has(entry)) selections.set(entry, []);
        selections.get(entry).push(available[round]);
        selectedCount++;
      }
    }
    const selected = [...selections].map(([entry, meanings]) => ({ ...entry, meanings }));
    const omitted = entries.filter(entry => !selections.has(entry)).map(entry => ({ id: entry.id, lemma: entry.lemma, source: entry.source }));
    const totalMeanings = entries.reduce((sum, entry) => sum + entry.meanings.length + (entry.omitted_meaning_count || 0), 0);
    return { entries: selected, ambiguous, omitted_entries: omitted, omitted_entry_count: omitted.length,
      omitted_meaning_count: Math.max(0, totalMeanings - selectedCount),
      truncated: totalMeanings > selectedCount || selected.some(entry => entry.truncated),
      label: ambiguous ? 'Dictionary alternatives; no contextual sense selected' : 'Short dictionary preview' };
  }
  function buildPreview(data, wiktionary = null) {
    const query = text(data?.form) || text(wiktionary?.query);
    const empty = { query, entries: [], normalized_alternatives: [], compact: compactView([], false), ambiguous: false, truncated: false, label: 'Dictionary preview' };
    if (!data || data.ready === false) return empty;
    const candidates = list(data.candidates).filter(exactCandidate);
    const dictionary = list(data.lexicon_entries).filter(row => !rejected(row) && identity(row.lemma));
    const entries = [];
    for (const entry of dictionary) {
      const id = entryId(entry), lemma = text(entry.lemma), source = text(entry.source);
      const url = sourceUrl(entry.source_url);
      const matches = candidates.filter(candidate => identity(candidate.lemma) === identity(lemma) &&
        (list(candidate.lexicon_entry_ids).includes(id) || candidate.gloss_entry_id === id));
      if (!url || !matches.length) continue;
      // A prose LSJ/Autenrieth gloss is one excerpt. Never split commas or
      // semicolons into supposed senses that the source did not distinguish.
      const structured = structuredSensesPresent(entry), clause = structured ? null : definitionExcerpt(entry);
      const meanings = structured ? structuredSenses(entry).map(sense => meaning(sense.text, text(sense.source) || source,
        sourceUrl(sense.source_url), { sense_id: sense.id, qualifiers: sense.qualifiers || [], scope_text: sense.scope_text,
          provenance: [sense] })).filter(Boolean) : [meaning(clause?.text || entry.gloss, source, url, {
        provenance: [{ entry_id: id, source, source_url: url }],
        ...(clause ? { definition_excerpt_provenance: clause.provenance } : {})
      })].filter(Boolean);
      if (!meanings.length) continue;
      const unresolvedEntry = matches.some(candidate => {
        const alternatives = dictionary.filter(other => identity(other.lemma) === identity(lemma) &&
          text(other.source) === source && list(candidate.lexicon_entry_ids).includes(entryId(other)));
        return alternatives.length > 1;
      });
      const analyses = unresolvedEntry ? [] : unique(matches.flatMap(candidate => {
        const parse = readableAnalysis(candidate);
        const parseUrl = sourceUrl(candidate.source_url);
        return parse && parseUrl ? [{ text: parse, matched_form: text(candidate.matched_form),
          source: text(candidate.source), source_url: parseUrl,
          label: 'Indexed form analysis (not a resolved passage parse)' }] : [];
      }), row => `${row.text}\0${row.source_url}\0${row.matched_form}`);
      const ambiguous = unresolvedEntry || matches.some(candidate =>
        candidate.lemma_link_status === 'ambiguous_source_lemmas') ||
        new Set(analyses.map(row => row.text)).size > 1;
      const incompatible = formRestrictedSenseIds(entry, matches, query, unresolvedEntry);
      entries.push({ id, lemma, source, source_url: url,
        entry_url: sourceUrl(entry.entry_url) || url, meanings,
        compact_meanings: meanings.filter(item => !incompatible.has(item.sense_id)),
        form_restricted_sense_ids: [...incompatible],
        meaning_kind: structured ? 'structured_dictionary_gloss' : 'dictionary_excerpt',
        analyses: analyses.slice(0, MAX_ANALYSES), ambiguous,
        label: unresolvedEntry ? 'Dictionary entry alternative; form-to-entry link unresolved' :
          ambiguous ? 'Dictionary entry; parsing alternatives remain' : 'Dictionary entry excerpt',
        truncated: meanings.some(row => row.truncated) || analyses.length > MAX_ANALYSES });
    }
    if (wiktionary?.ready === true && identity(wiktionary.query) === identity(query) && !rejected(wiktionary)) {
      for (const row of list(wiktionary.results)) {
        if (rejected(row) || !text(row.id) || !identity(row.headword)) continue;
        const url = sourceUrl(row.source_url), source = text(row.source) || 'Wiktionary / Kaikki';
        const matches = list(row.matches).filter(match => eligibleWikiMatch(match, row, query));
        if (!url || !matches.length) continue;
        const exactMatches = matches.filter(match => exactWikiMatch(match, row, query));
        const normalizedOnly = exactMatches.length === 0;
        const headwordMatched = exactMatches.some(match => match.kind === 'headword');
        // A form-of page can embed its target's full declension table. A hit
        // on that table does not make the page-headword's form-of gloss a
        // meaning of the listed row. Ordinary lexical senses still apply.
        const sourceSenses = list(row.senses).filter(sense =>
          !rejected(sense) && (headwordMatched || normalizedOnly || (!formOfSense(sense)
            && !list(row.entry_form_of).length && list(sense.glosses).length <= 1)));
        const meanings = new Map();
        for (const sense of sourceSenses) {
          for (const gloss of list(sense.glosses)) {
            // Compare the complete literal gloss, before excerpt truncation.
            // Identical text in two source senses remains one display excerpt
            // with both references, not an invented collapse of the senses.
            const key = identity(gloss);
            const reference = { entry_id: row.id, source, source_url: url, sense_index: sense.sense_index };
            if (meanings.has(key)) {
              const existing = meanings.get(key);
              if (!existing.sense_indices.includes(sense.sense_index)) {
                existing.sense_indices.push(sense.sense_index);
                existing.provenance.push(reference);
              }
            } else {
              const item = meaning(gloss, source, url, { sense_index: sense.sense_index,
                sense_indices: [sense.sense_index], provenance: [reference] });
              if (item) meanings.set(key, item);
            }
          }
        }
        const distinctMeanings = [...meanings.values()];
        if (!distinctMeanings.length) continue;
        const listedAnalyses = exactMatches.flatMap(match => {
          if (match.kind !== 'listed_form' || rejected(match.form)) return [];
          // Canonical rows can contain noun gender, which describes the
          // lexeme, not a competing inflectional analysis of this form.
          if (list(match.form.tags).some(tag => typeof tag === 'string' &&
            ['canonical', 'romanization', 'transliteration'].includes(tag.toLowerCase()))) return [];
          const tags = grammaticalTags(match.form.tags);
          return tags.length ? [{ text: tags.join(', '), matched_form: text(match.form.form),
            source, source_url: url, label: 'Dictionary-listed form tags (not a corpus attestation)' }] : [];
        });
        const normalizedAnalyses = matches.filter(match => !exactWikiMatch(match, row, query)).flatMap(match => {
          if (match.kind !== 'listed_form' || rejected(match.form)) return [];
          const tags = grammaticalTags(match.form.tags);
          return tags.length ? [{ text: tags.join(', '), matched_form: text(match.form.form), source, source_url: url,
            label: 'Spelling-normalized dictionary match; not an exact parse of the selected form' }] : [];
        });
        // On a direct inflected-headword lookup, form-of sense tags describe
        // that headword. Do not distribute them over a different table form,
        // or across a mixed entry's unrelated lexical senses.
        const formOfOnly = sourceSenses.length > 0 && sourceSenses.every(formOfSense);
        const senseAnalyses = headwordMatched && formOfOnly ? sourceSenses.flatMap(sense => {
          const tags = grammaticalTags(sense.tags);
          return tags.length ? [{ text: tags.join(', '), matched_form: text(row.headword),
            source, source_url: url, label: 'Source form-of sense tags (not a corpus attestation)' }] : [];
        }) : [];
        const analyses = unique([...senseAnalyses, ...listedAnalyses],
          item => `${item.text}\0${item.matched_form}`);
        entries.push({ id: row.id, lemma: text(row.headword), source, source_url: url,
          entry_url: sourceUrl(row.live_entry_url) || url, meanings: distinctMeanings.slice(0, MAX_MEANINGS),
          meaning_kind: 'structured_dictionary_gloss', omitted_meaning_count: Math.max(0, distinctMeanings.length - MAX_MEANINGS),
          normalized_only: normalizedOnly, normalized_analyses: normalizedAnalyses,
          analyses: analyses.slice(0, MAX_ANALYSES), ambiguous: new Set(analyses.map(item => item.text)).size > 1,
          label: 'Wiktionary snapshot excerpts; live entry may differ',
          truncated: distinctMeanings.length > MAX_MEANINGS || analyses.length > MAX_ANALYSES ||
            distinctMeanings.some(item => item.truncated) || Number(row.total_senses) > list(row.senses).length });
      }
    }
    const allEntries = unique(entries, entry => `${entry.source}\0${entry.id}`);
    const normalizedAlternatives = allEntries.filter(entry => entry.normalized_only);
    const distinct = allEntries.filter(entry => !entry.normalized_only);
    const sourceLemmas = new Map();
    for (const entry of distinct) {
      const key = `${entry.source}\0${identity(entry.lemma)}`;
      sourceLemmas.set(key, (sourceLemmas.get(key) || 0) + 1);
    }
    const ambiguous = new Set(distinct.map(entry => identity(entry.lemma))).size > 1 ||
      [...sourceLemmas.values()].some(count => count > 1) || distinct.some(entry => entry.ambiguous);
    return { query, entries: distinct, normalized_alternatives: normalizedAlternatives, compact: compactView(distinct, ambiguous), ambiguous,
      truncated: distinct.some(entry => entry.truncated),
      label: ambiguous ? 'Dictionary alternatives — no contextual sense selected' : 'Dictionary preview — source excerpts' };
  }
  window.MelosDictionaryPreview = Object.freeze({ isCandidateQuery, buildPreview, friendlySourceName,
    definitionExcerpt, candidateDefinitionExcerpt, lexicalVariantPreview, linkedDictionaryCandidates, linkedDictionaryGroups });
})();
