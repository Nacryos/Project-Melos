(() => {
  'use strict';
  const sourceTexts = new WeakMap();
  const keyOf = body => JSON.stringify([body.passage_id, body.start, body.end, body.selected_text, sourceTexts.get(body) || '']);
  function selectionFor({ passage, form, start, end, joined = false, fragment = false }) {
    if (joined || fragment || !passage?.id || typeof passage.text !== 'string'
      || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > passage.text.length
      || passage.text.slice(start, end) !== form || !/^[\p{L}][\p{L}\p{M}’'᾽ʼ]*$/u.test(form)
      || form.includes('\u0323')) return null;
    const body = { version: 1, passage_id: passage.id, start, end, selected_text: form,
      offset_unit: 'utf16', fetch_machine: true, rerank: true };
    sourceTexts.set(body, passage.text);
    return body;
  }
  const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
  const equal = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
  const sourceSenseEqual = (a, b) => ['id', 'text', 'entry_id', 'lexicon_entry_id', 'evidence_type',
    'source', 'source_url', 'raw_sha256', 'source_locator', 'language', 'linked_path', 'qualifiers', 'scope_text',
    'form_scope', 'citations', 'citation_scope', 'qualifier_scope', 'sense_path', 'scope_locator', 'definition_kind', 'extraction_method']
    .every(key => equal(a[key], b[key]));
  function checkedOccurrence(data, body) {
    if (data?.passage?.id !== body.passage_id || data.selection?.text !== body.selected_text
      || data.selection?.start_utf16 !== body.start || data.selection?.end_utf16 !== body.end) {
      throw new Error('The returned selection differs from this word.');
    }
    const words = (data.tokens || []).filter(token => token.kind === 'word');
    if (words.length !== 1 || words[0].text !== body.selected_text || words[0].start_utf16 !== body.start
      || words[0].end_utf16 !== body.end || words[0].partial_word || words[0].editorial_fragment) {
      throw new Error('This response is not an intact, single-word selection.');
    }
    const token = words[0];
    const readings = data.interlinear?.readings || [];
    if (readings.length !== 1) return null;
    const rows = (readings[0].tokens || []).filter(row => row.kind === 'word');
    if (rows.length !== 1) return null;
    const row = rows[0];
    if (row.token_id !== token.id || row.text !== token.text || row.start_utf16 !== body.start || row.end_utf16 !== body.end
      ) return null;
    const decisions = (data.sense_ranking?.items || []).filter(item => item.token_id === token.id);
    if (decisions.length !== 1) return null;
    return { token, row, decision: decisions[0] };
  }
  function checkedProposal(data, body) {
    const occurrence = checkedOccurrence(data, body);
    if (!occurrence) return null;
    const { token, row, decision } = occurrence, gloss = row.gloss || {};
    if (gloss.status !== 'available' || gloss.selection_basis !== 'jev_contextual_sense_proposal') return null;
    if (decision?.status !== 'proposed' || decision.selected_sense_id !== gloss.sense_id) return null;
    const sense = (gloss.alternatives || []).find(item => item.id === gloss.sense_id
      && (item.lexicon_entry_id || item.entry_id) === gloss.entry_id && item.text === gloss.text);
    if (!sense || sense.evidence_type !== 'dictionary_sense' || !/^(en|eng|english)$/i.test(sense.language || sense.gloss_language || '')
      || !sense.source_url || !sense.source || !sense.text?.trim()) return null;
    const linkedCandidates = window.MelosDictionaryPreview?.linkedDictionaryCandidates?.(token.form || token.text, token.linked_dictionary) || [];
    const linkedSenseMatches = item => item.id === sense.id && item.text === sense.text
      && (item.lexicon_entry_id || item.entry_id) === gloss.entry_id
      && ['source', 'source_url', 'raw_sha256', 'source_locator', 'language', 'linked_path', 'qualifiers', 'scope_text']
        .every(key => JSON.stringify(stable(item[key])) === JSON.stringify(stable(sense[key])));
    const candidates = [...(token.source_candidates || []), ...(token.contextual_candidates || []), ...(token.machine?.machine_candidates || []), ...linkedCandidates];
    const supports = gloss.supporting_candidate_ids || decision.supporting_candidate_ids || [];
    const supported = candidates.filter(candidate => supports.includes(candidate.id)
      && (!linkedCandidates.includes(candidate) || candidate.senses.some(linkedSenseMatches))
      && (candidate.gloss_entry_id === gloss.entry_id || candidate.lexicon_entry_ids?.includes(gloss.entry_id)
        || row.candidate_meanings?.some(item => item.candidate_id === candidate.id
          && item.gloss?.alternatives?.some(alternative => alternative.id === sense.id
            && (alternative.lexicon_entry_id || alternative.entry_id) === gloss.entry_id && alternative.text === sense.text))));
    if (!supported.length) return null;
    const selected = row.status === 'selected' && row.candidate_id && row.source_candidate?.id === row.candidate_id && supports.includes(row.candidate_id)
      ? supported.find(candidate => candidate.id === row.candidate_id && (!linkedCandidates.includes(candidate)
        || candidate.linked_path.literal_pos_agreement === true)) : null;
    // A parse-only agreement is distinct from choosing a lexical homograph.
    // Every contributing row must carry the complete same recorded feature set
    // and also support this sense; never union partial candidate features here.
    const parseIds = row.supporting_parse_candidate_ids;
    const featureKey = features => features && typeof features === 'object' && !Array.isArray(features)
      ? JSON.stringify(Object.keys(features).sort().map(key => [key, features[key]])) : '';
    const rowFeatures = featureKey(row.features);
    const sourceCandidates = [...(token.source_candidates || []), ...(token.contextual_candidates || [])];
    const consensusRows = !selected && !row.candidate_id && !row.source_candidate
      && row.selection_basis === 'source_morphology_consensus' && !row.syntax_conflict
      && Array.isArray(parseIds) && parseIds.length && rowFeatures && rowFeatures !== '[]'
      ? parseIds.map(id => {
        const raw = sourceCandidates.find(candidate => candidate.id === id && supported.includes(candidate));
        const evidence = (row.candidate_meanings || []).find(item => item.candidate_id === id);
        return raw && evidence?.basis === 'source_alternative' && typeof raw.lemma === 'string' && raw.lemma
          && evidence.lemma?.normalize('NFC') === raw.lemma.normalize('NFC')
          && featureKey(evidence.features) === rowFeatures && evidence.parse_short === row.parse_short ? evidence : null;
      }) : [];
    const consensus = consensusRows.length > 0 && consensusRows.every(Boolean)
      && new Set(consensusRows.map(item => item.lemma.normalize('NFC'))).size === 1;
    return { text: sense.text, source: sense.source, source_url: sense.source_url,
      parse: selected || consensus ? row.parse_short || '' : '', lemma: selected ? selected.lemma || '' : '',
      parse_basis: selected ? row.selection_basis : consensus ? 'source_morphology_consensus' : null,
      alternatives: (gloss.alternatives || []).filter(item => item.evidence_type === 'dictionary_sense'
        && /^(en|eng|english)$/i.test(item.language || item.gloss_language || '') && item.text && item.source_url),
      sense_id: sense.id, entry_id: gloss.entry_id, basis: gloss.selection_basis };
  }
  function checkedRankedAlternatives(data, body) {
    const occurrence = checkedOccurrence(data, body);
    if (!occurrence) return null;
    const { token, row, decision } = occurrence;
    if (decision.status !== 'uncertain' || decision.selected_sense_id !== null
      || row.sense_ranking_status !== 'uncertain'
      || !/^[a-f0-9]{64}$/i.test(decision.inventory_sha256 || '')
      || row.sense_ranking_inventory_sha256 !== decision.inventory_sha256) return null;
    const linked = window.MelosDictionaryPreview?.linkedDictionaryCandidates?.(token.form || token.text, token.linked_dictionary) || [];
    const raw = [...(token.source_candidates || []), ...(token.contextual_candidates || []), ...(token.machine?.machine_candidates || []), ...linked];
    const inventory = new Map(), candidateIds = new Set();
    for (const candidate of row.candidate_meanings || []) {
      const senses = candidate.gloss?.alternatives || [];
      if (!senses.length) continue;
      const matches = raw.filter(item => item.id === candidate.candidate_id);
      if (matches.length !== 1 || candidateIds.has(candidate.candidate_id)) return null;
      candidateIds.add(candidate.candidate_id);
      const sourceCandidate = matches[0];
      for (const sense of senses) {
        let url;
        try { url = new URL(sense.source_url); } catch { return null; }
        const entry = sense.lexicon_entry_id || sense.entry_id;
        if (!sense.id || !sense.text?.trim() || sense.evidence_type !== 'dictionary_sense'
          || !/^(en|eng|english)$/i.test(sense.language || '') || !sense.source || !sense.source_locator
          || !/^[a-f0-9]{64}$/i.test(sense.raw_sha256 || '') || !['https:', 'http:'].includes(url.protocol)
          || url.username || url.password || !entry) return null;
        if (linked.includes(sourceCandidate)) {
          if (!sourceCandidate.senses.some(item => sourceSenseEqual(item, sense))) return null;
        } else if (sourceCandidate.gloss_entry_id !== entry && !sourceCandidate.lexicon_entry_ids?.includes(entry)) {
          // The backend can join another dictionary's same-lemma entry.
          // Require that actual entry and its literal sense, not a loose
          // candidate_meanings assertion or an accent-folded headword.
          const entries = (token.lexicon_entries || []).filter(item => item.id === entry);
          const exact = value => typeof value === 'string' ? value.normalize('NFC') : '';
          if (entries.length !== 1 || !exact(sourceCandidate.lemma)
            || exact(candidate.lemma) !== exact(sourceCandidate.lemma)
            || exact(entries[0].lemma) !== exact(sourceCandidate.lemma)
            || !entries[0].dictionary_senses?.some(item => sourceSenseEqual(item, sense))) return null;
        }
        const existing = inventory.get(sense.id);
        if (existing && !sourceSenseEqual(existing.sense, sense)) return null;
        if (!existing) inventory.set(sense.id, { sense, support: [], lemmas: [] });
        const item = inventory.get(sense.id);
        item.support.push(candidate.candidate_id);
        if (sourceCandidate.lemma && !item.lemmas.includes(sourceCandidate.lemma)) item.lemmas.push(sourceCandidate.lemma);
      }
    }
    if (!inventory.size) return null;
    const scores = decision.model_probabilities_uncalibrated, ranked = row.ranked_sense_alternatives;
    const keys = [...inventory.keys()], sameIds = ids => ids.length === keys.length && new Set(ids).size === keys.length && ids.every(id => inventory.has(id));
    if (!scores || !sameIds(Object.keys(scores).filter(id => id !== 'abstain'))
      || !Object.hasOwn(scores, 'abstain') || !Object.values(scores).every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1)
      || !Array.isArray(ranked) || !sameIds(ranked.map(item => item.id))
      || !Array.isArray(decision.ranked_senses) || !sameIds(decision.ranked_senses.map(item => item.sense_id))
      || decision.ranked_senses.some(item => item.score_uncalibrated !== scores[item.sense_id])) return null;
    const alternatives = [];
    for (const sense of ranked) {
      const original = inventory.get(sense.id);
      if (!sourceSenseEqual(original.sense, sense) || sense.score_uncalibrated !== scores[sense.id]
        || !Array.isArray(sense.supporting_candidate_ids)
        || !equal([...sense.supporting_candidate_ids].sort(), [...original.support].sort())) return null;
      alternatives.push({ ...original.sense, supporting_candidate_ids: original.support, lemmas: original.lemmas, score_uncalibrated: sense.score_uncalibrated });
    }
    alternatives.sort((a, b) => b.score_uncalibrated - a.score_uncalibrated);
    return { kind: 'ranked_alternatives', alternatives, abstain_score_uncalibrated: scores.abstain,
      parse: '', selected_sense_id: null, inventory_sha256: decision.inventory_sha256 };
  }
  function createSession({ post, limit = 32, ttl = 600000, now = Date.now }) {
    const cache = new Map(), flights = new Map();
    let selected = null;
    function select(body) {
      selected = body ? keyOf(body) : null;
      for (const [key, item] of flights) if (key !== selected) { item.controller.abort(); flights.delete(key); }
    }
    async function run(body) {
      const key = keyOf(body);
      if (selected !== key) throw new Error('The selected word has changed.');
      const saved = cache.get(key);
      if (saved && now() - saved.time < ttl) return saved.value;
      if (flights.has(key)) return flights.get(key).promise;
      const controller = new AbortController();
      const item = { controller, promise: null };
      item.promise = (async () => {
        if (!globalThis.crypto?.subtle || typeof TextEncoder !== 'function' || !sourceTexts.has(body)) {
          const error = new Error('This browser cannot verify the displayed passage.');
          error.code = 'context_verification_unavailable'; throw error;
        }
        const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(sourceTexts.get(body)));
        const expectedHash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
        if (controller.signal.aborted || selected !== key) throw new Error('The selected word has changed.');
        const data = await post('/api/analyze-passage', body, { signal: controller.signal });
        if (controller.signal.aborted || selected !== key) throw new Error('The selected word has changed.');
        if (data?.passage?.text_sha256 !== expectedHash) {
          const error = new Error('The passage has changed. Reopen it before reading this word in context.');
          error.code = 'context_hash_mismatch'; throw error;
        }
        const value = checkedProposal(data, body) || checkedRankedAlternatives(data, body);
        cache.delete(key);
        if (value) cache.set(key, { value, time: now() });
        while (cache.size > limit) cache.delete(cache.keys().next().value);
        return value;
      })().finally(() => { if (flights.get(key) === item) flights.delete(key); });
      flights.set(key, item);
      return item.promise;
    }
    return { select, run, clear() { select(null); cache.clear(); } };
  }
  function mount({ host, body, session, current, classifierReady, node, safeLink }) {
    session.select(body);
    if (!body || !classifierReady()) return;
    const section = node('section', 'inspector-section word-context');
    const heading = node('h3', '', 'In this passage');
    const action = node('button', 'context-action classifier-action', 'Read in context'); action.type = 'button';
    const output = node('div', 'word-context-result'); output.setAttribute('aria-live', 'polite');
    section.append(heading, action, output); host.append(section);
    action.addEventListener('click', async () => {
      if (!current() || action.disabled) return;
      action.disabled = true; action.textContent = 'Reading context…';
      try {
        const proposal = await session.run(body);
        if (!current()) return;
        output.replaceChildren();
        if (!proposal) { output.append(node('p', 'candidate-reason', 'No preferred meaning was selected. Dictionary alternatives remain below.')); return; }
        if (proposal.kind === 'ranked_alternatives') {
          heading.textContent = 'Possible meanings in this passage';
          output.append(node('p', 'candidate-reason', 'Ranked contextual alternatives · Jev. No single meaning was selected.'));
          const details = node('details', 'entry-details');
          details.append(node('summary', '', 'More meanings and evidence'));
          proposal.alternatives.forEach((sense, index) => {
            const item = node('div', 'dictionary-glimpse-entry');
            item.append(node('p', 'candidate-gloss', `${index + 1}. ${sense.text}`));
            if (sense.lemmas.length) item.append(node('p', 'candidate-reason', sense.lemmas.join(' / ')));
            const source = safeLink(sense.source_url, sense.source); if (source) item.append(source);
            (index < 3 ? output : details).append(item);
            details.append(node('p', 'candidate-reason', `${index + 1}. Model score ${sense.score_uncalibrated}`));
            if (Array.isArray(sense.scope_text) && sense.scope_text.length > 1)
              details.append(node('p', 'candidate-reason', `Source sense context: ${sense.scope_text.join(' → ')}`));
          });
          details.append(node('p', 'candidate-reason', `Abstention score: ${proposal.abstain_score_uncalibrated}. These uncalibrated model scores are not measured accuracy or verified probabilities of a reading. No morphological reading is selected by this list.`));
          output.append(details); return;
        }
        heading.textContent = 'In this passage';
        output.append(node('p', 'candidate-gloss', proposal.text), node('small', 'candidate-meta-label', 'Contextual proposal · Jev'));
        if (proposal.parse) output.append(node('p', 'candidate-analysis', [proposal.lemma, proposal.parse].filter(Boolean).join(' · ')));
        const link = safeLink(proposal.source_url, proposal.source); if (link) output.append(link);
        const details = node('details', 'entry-details'); details.append(node('summary', '', 'Evidence and dictionary alternatives'));
        details.append(node('p', 'candidate-reason', 'Jev selected this existing English dictionary sense; it is a proposal, not a verified passage annotation.'));
        if (proposal.parse_basis === 'source_morphology_consensus') details.append(node('p', 'candidate-reason',
          'The supporting recorded analyses agree on this parse. No individual lexical alternative has been selected.'));
        const seen = new Set();
        for (const sense of proposal.alternatives) {
          if (seen.has(sense.id)) continue; seen.add(sense.id);
          const line = node('p', 'candidate-reason', sense.text), source = safeLink(sense.source_url, sense.source || 'Dictionary source');
          if (source) line.append(node('span', '', ' · '), source); details.append(line);
        }
        output.append(details);
      } catch (error) {
        if (current() && error.name !== 'AbortError') {
          const explanation = error.code === 'context_verification_unavailable'
            ? 'This browser cannot verify the displayed passage. Use a secure HTTPS connection or an updated browser. Dictionary entries remain below.'
            : error.code === 'context_hash_mismatch' ? 'The passage has changed. Reopen it before reading this word in context. Dictionary entries remain below.'
              : 'Contextual reading is unavailable. The sourced dictionary entries remain below.';
          output.replaceChildren(node('p', 'candidate-reason', explanation));
        }
      } finally {
        if (current()) { action.disabled = false; action.textContent = 'Read in context'; }
      }
    });
  }
  window.MelosWordContext = { selectionFor, checkedProposal, checkedRankedAlternatives, createSession, mount };
})();
