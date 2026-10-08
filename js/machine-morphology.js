// Explicit computational analysis only. No corpus evidence or dictionary sense inference.
(() => {
  'use strict';
  const stable = value => Array.isArray(value) ? value.map(stable)
    : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
  function displayGroups(candidates) {
    const groups = new Map();
    for (const item of candidates) {
      // Display identity only. Raw inflections, IDs and pointers remain in the
      // original inventory and never become one classifier choice.
      const key = JSON.stringify(stable({ lemma: item.lemma, features: item.features, dictionary_fields: item.dictionary_fields }));
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    return [...groups.values()];
  }
  // The engine that produced a result, read from its receipt: our local Morpheus
  // build (named by commit) or the remote Alpheios service. Nothing is assumed.
  const LOCAL_PARSER = 'morpheus-local-v1';
  function engineOf(receipt) {
    if (!receipt || typeof receipt !== 'object') return null;
    if (receipt.parser_version === LOCAL_PARSER) {
      const commits = {};
      for (const match of String(receipt.engine_revision || '').matchAll(/alpheios-project\/(morpheus|morphsvc)@([0-9a-f]{40})/g)) commits[match[1]] = match[2];
      const repo = name => `https://github.com/alpheios-project/${name}${commits[name] ? `/tree/${commits[name]}` : ''}`;
      return { local: true, label: `Morpheus, local build${commits.morpheus ? ` at commit ${commits.morpheus.slice(0, 7)}` : ''}`,
        url: repo('morpheus'), service: commits.morphsvc ? { label: `morphsvc ${commits.morphsvc.slice(0, 7)}`, url: repo('morphsvc') } : null };
    }
    return { local: false, label: 'Morpheus via Alpheios', url: 'https://alpheios.net/pages/tools/', terms: 'https://alpheios.net/pages/apiterms/' };
  }
  function mount({ host, form, passageId, current, post, node, safeLink, classifierReady }) {
    const section = node('section', 'inspector-section machine-analysis');
    section.append(node('h3', '', 'More possible parses'));
    const about = node('details', 'entry-details notice-details');
    about.append(node('summary', '', 'About these analyses'), node('p', 'candidate-reason',
      'Ask the morphology service for possible headwords and inflections. These are computational alternatives, not attestations or a reading selected for this author. No meaning is inferred from a matching headword.'));
    const analyze = node('button', 'classifier-action', 'Analyze this form'); analyze.type = 'button';
    const cancel = node('button', 'machine-cancel', 'Cancel request'); cancel.type = 'button'; cancel.hidden = true;
    const attribution = node('p', 'candidate-reason machine-attribution');
    const attribute = engine => {
      attribution.replaceChildren();
      if (!engine) { attribution.append(node('span', '', 'Parser: the engine is named on each result (local Morpheus build or the Alpheios service).')); return; }
      attribution.append(node('span', '', 'Parser: '));
      const provider = safeLink(engine.url, engine.label);
      attribution.append(provider || node('span', '', engine.label));
      const service = engine.service && safeLink(engine.service.url, engine.service.label);
      if (service) attribution.append(node('span', '', ' · service '), service);
      const terms = engine.terms && safeLink(engine.terms, 'API terms');
      if (terms) attribution.append(node('span', '', ' · '), terms);
    };
    attribute(null);
    const output = node('div', 'machine-output'); output.setAttribute('aria-live', 'polite');
    about.append(attribution);
    section.append(analyze, cancel, output, about); host.append(section);
    let generation = 0, controller = null, busy = false;
    const clear = target => target.replaceChildren();
    const say = (target, text, cls = 'candidate-reason') => target.append(node('p', cls, text));
    const warnings = (target, values) => {
      const notes = (Array.isArray(values) ? values : []).filter(Boolean);
      if (!notes.length) return;
      const details = node('details', 'entry-details notice-details');
      details.append(node('summary', '', 'Details'));
      for (const value of notes) say(details, String(value));
      target.append(details);
    };
    const valid = ticket => current() && generation === ticket;
    const stop = () => {
      ++generation; controller?.abort(); controller = null; busy = false;
      analyze.disabled = false; cancel.hidden = true;
    };
    cancel.addEventListener('click', () => { stop(); if (current()) { clear(output); say(output, 'Request cancelled. A request already received by the service may still finish.'); } });
    const provenance = (target, label, payload, url) => {
      const details = node('details', 'entry-details machine-provenance');
      details.append(node('summary', '', label), node('pre', '', JSON.stringify(payload, null, 2)));
      const link = safeLink(url, 'Source API request'); if (link) details.append(link);
      target.append(details);
    };
    const candidate = (target, item, members = [item]) => {
      const card = node('div', 'candidate machine-candidate');
      say(card, 'Computational candidate', 'candidate-meta-label');
      say(card, item.lemma || 'Headword not supplied', 'candidate-lemma');
      const labels = { pofs: 'Part of speech', case: 'Case', gend: 'Gender', num: 'Number',
        tense: 'Tense', voice: 'Voice', mood: 'Mood', pers: 'Person', person: 'Person',
        decl: 'Declension', declension: 'Declension', stemtype: 'Stem type', dial: 'Engine dialect' };
      const fields = Object.entries(item.features || {}).map(([key, value]) =>
        `${Object.hasOwn(labels, key) ? labels[key] : key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`);
      if (fields.length) say(card, fields.join(' · '), 'candidate-analysis');
      if (!Object.keys(item.features || {}).length) say(card, 'No inflection fields supplied.');
      if (item.features?.dial) warnings(card, ['Dialect tags are literal engine labels, not exclusive attribution to this author.']);
      if (members.length > 1) say(card, `${members.length} engine alternatives with the same displayed features.`);
      provenance(card, members.length > 1 ? 'All engine alternatives and identities' : 'Engine fields and candidate identity',
        members.map(member => ({ id: member.id, dictionary_fields: member.dictionary_fields, inflection: member.inflection,
          entry_pointer: member.entry_pointer, inflection_pointer: member.inflection_pointer, receipt_id: member.receipt_id })));
      target.append(card);
    };
    const compare = (target, result, ticket) => {
      if (!passageId || !result.receipt?.id || !result.machine_candidates.length) return;
      if (!classifierReady()) return;
      const button = node('button', 'classifier-action', 'Compare these analyses with Jev'); button.type = 'button';
      const answer = node('div', 'machine-comparison'); target.append(button, answer);
      button.addEventListener('click', async () => {
        if (!valid(ticket) || busy || button.disabled) return;
        busy = true; button.disabled = true; analyze.disabled = true; cancel.hidden = false;
        controller = new AbortController(); clear(answer); say(answer, 'Comparing computational alternatives…');
        try {
          const decision = await post('/api/classify-context', { form, passage_id: passageId,
            candidate_basis: 'machine', machine_receipt_id: result.receipt.id }, { signal: controller.signal });
          if (!valid(ticket)) return;
          clear(answer);
          const chosen = result.machine_candidates.find(item => item.id === decision.candidate_id);
          if (decision.status === 'machine_proposed' && decision.candidate_basis === 'machine' && chosen) {
            say(answer, 'Suggested reading · Jev', 'candidate-meta-label');
            candidate(answer, chosen);
            warnings(answer, ['Jev proposal among computational alternatives · interpretive only. This selects neither an attested sense nor an authoritative textual reading. All alternatives remain above.']);
          } else warnings(answer, [decision.decision_stage === 'preflight'
            ? 'Comparison not run; no model call was made.'
            : 'No computational alternative was selected.']);
          warnings(answer, [decision.reason, decision.model ? `Model: ${decision.model}.` : '', decision.cache_hit != null
            ? decision.cache_hit ? 'Cached comparison; no new Jev call.' : 'New Jev comparison.' : '']);
          if (decision.model_confidence_uncalibrated != null || decision.model_probabilities_uncalibrated != null) {
            provenance(answer, 'Raw uncalibrated model signals', {
              note: 'Raw model signals are uncalibrated, not probabilities of philological truth.',
              confidence: decision.model_confidence_uncalibrated,
              candidate_preferences: decision.model_probabilities_uncalibrated,
            });
          }
          warnings(answer, decision.warnings);
          provenance(answer, 'Comparison provenance', { status: decision.status, candidate_id: decision.candidate_id,
            candidate_basis: decision.candidate_basis, decision_stage: decision.decision_stage,
            model: decision.model, cache_hit: decision.cache_hit, machine_evidence: decision.machine_evidence });
        } catch (error) {
          if (valid(ticket)) {
            clear(answer); say(answer, 'Could not compare these readings. Try again.', 'error-message');
            warnings(answer, [error.message || String(error), ...(error.response?.warnings || [])]);
          }
        } finally {
          if (valid(ticket)) { busy = false; button.disabled = false; analyze.disabled = false; cancel.hidden = true; controller = null; }
        }
      });
    };
    analyze.addEventListener('click', async () => {
      if (!current() || busy || analyze.disabled) return;
      const ticket = ++generation; busy = true; analyze.disabled = true; cancel.hidden = false;
      controller = new AbortController(); clear(output); say(output, 'Requesting computational analyses…');
      try {
        const result = await post('/api/machine-analysis', { form, ...(passageId ? { passage_id: passageId } : {}) }, { signal: controller.signal });
        if (!valid(ticket)) return;
        clear(output);
        const engine = engineOf(result.receipt);
        if (engine) attribute(engine);
        if (result.status === 'ok' && Array.isArray(result.machine_candidates) && result.machine_candidates.length) {
          say(output, `${result.machine_candidates.length} possible parses`, 'candidate-meta-label');
          if (engine) say(output, `Parsed by ${engine.label}.`, 'candidate-reason machine-engine');
          for (const members of displayGroups(result.machine_candidates)) candidate(output, members[0], members);
          compare(output, result, ticket);
        } else if (result.status === 'no_analyses') say(output, 'No additional parses found.');
        else say(output, result.status === 'rate_limited' || result.status === 'busy'
          ? 'The morphology service is busy or rate-limited. Please try again later.'
          : 'Could not load additional parses. Try again.', 'error-message');
        warnings(output, result.warnings);
        // A local receipt's URL is the service's internal address, not a public link.
        if (result.receipt) provenance(output, engine?.local ? 'Request receipt' : 'Request receipt and source API', result.receipt, engine?.local ? null : result.receipt.url);
        if (Array.isArray(result.machine_entries) && result.machine_entries.length) provenance(output, 'Raw engine entries', result.machine_entries);
      } catch (error) {
        if (valid(ticket)) {
          clear(output); say(output, error.status === 429 || error.status === 409
            ? 'The morphology service is busy or rate-limited. Please try again later.'
            : 'Could not load additional parses. Try again.', 'error-message');
          warnings(output, [error.message || String(error), ...(error.response?.warnings || [])]);
          if (error.response?.receipt) provenance(output, 'Failed request receipt', error.response.receipt, error.response.receipt.url);
        }
      } finally {
        if (valid(ticket)) { busy = false; analyze.disabled = false; cancel.hidden = true; controller = null; }
      }
    });
    return stop;
  }
  globalThis.MelosMachineMorphology = { mount, displayGroups, engineOf };
})();
