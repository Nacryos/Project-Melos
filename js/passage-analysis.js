// Selection is local state. Only an explicit action contacts the analysis API.
(() => {
  'use strict';
  const MAX_CHARACTERS = 2000, MAX_WORDS = 80;
  function rankingCandidateLabel(candidate) {
    if (!candidate) return '';
    const labels = { pofs: 'part of speech', gend: 'gender', num: 'number', pers: 'person', dial: 'dialect', decl: 'declension', stemtype: 'stem type' };
    const literal = value => typeof value === 'string' || typeof value === 'number' ? String(value)
      : Array.isArray(value) ? value.map(literal).filter(Boolean).join(', ')
      : value && typeof value === 'object' && Object.hasOwn(value, '$') ? literal(value.$) : '';
    const fields = value => Object.entries(value || {}).filter(([, raw]) => literal(raw)).map(([key, raw]) => `${labels[key] || key}: ${literal(raw)}`);
    const parts = [candidate.lemma || candidate.matched_form || 'Unlabelled candidate'];
    const analysis = candidate.analysis_text || candidate.analysis;
    if (analysis) parts.push(typeof analysis === 'string' ? analysis : JSON.stringify(analysis));
    const inflection = fields({ ...candidate.inflection, ...candidate.features });
    if (inflection.length) parts.push(inflection.join(' · '));
    const dictionary = Object.fromEntries(Object.entries(candidate.dictionary_fields || {}).filter(([key]) => !['hdwd', 'lang'].includes(key)));
    const dictionaryText = fields(dictionary);
    if (dictionaryText.length) parts.push(`Dictionary fields: ${dictionaryText.join(' · ')}`);
    if (candidate.equivalent_form) parts.push(`Source equivalent form: ${candidate.equivalent_form}`);
    if (parts.length === 1) parts.push('Grammatical analysis not supplied');
    return parts.join(' · ');
  }
  function lexicalPrediction(token) {
    return token?.prediction_status !== 'not_applicable' && !['whitespace', 'editorial', 'punctuation'].includes(token?.token_kind)
      && /[\p{L}\p{N}]/u.test(String(token?.text || ''));
  }
  function sourceCandidateGroups(token) {
    const groups = { exact: [], nearby: [], other: [] };
    for (const item of token.source_candidates || []) {
      const form = item.matched_form || item.attested_form;
      if (token.analysis_match_status === 'spelling_suggestions_only' || Number(item.edit_distance) > 0) groups.nearby.push(item);
      else if (form && form.normalize('NFC') === token.text.normalize('NFC')) groups.exact.push(item);
      else groups.other.push(item);
    }
    return groups;
  }
  function selectionIssue(span) {
    if (!span?.selected_text?.trim()) return 'Select source text to analyze.';
    if ([...span.selected_text].length > MAX_CHARACTERS) return 'Analyze up to 2,000 characters at a time. The selection has not been shortened.';
    if ((span.selected_text.match(/[\p{L}\p{M}]+(?:['’᾽ʼ᾿][\p{L}\p{M}]+)*/gu) || []).length > MAX_WORDS) return 'Analyze up to 80 words at a time. The selection has not been shortened.';
    return '';
  }
  function sourceMap(root, source) {
    const map = new WeakMap();
    const blocks = [...root.querySelectorAll('.line-content, p')];
    let cursor = 0;
    for (const block of blocks) {
      const text = block.textContent;
      const start = source.indexOf(text, cursor);
      if (start < 0 || source.slice(cursor, start).trim()) return null;
      const walker = root.ownerDocument.createTreeWalker(block, 4);
      let offset = start;
      while (walker.nextNode()) {
        const leaf = walker.currentNode;
        map.set(leaf, { start: offset, end: offset + leaf.data.length });
        offset += leaf.data.length;
      }
      cursor = start + text.length;
    }
    return blocks.length && !source.slice(cursor).trim() ? map : null;
  }
  function selectedSpan(selection, root, map, source) {
    if (!map || selection?.rangeCount !== 1) return null;
    const range = selection.getRangeAt(0);
    if (range.collapsed || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
    const walker = root.ownerDocument.createTreeWalker(root, 4);
    let start = null, end = null;
    while (walker.nextNode()) {
      const leaf = walker.currentNode, mapped = map.get(leaf);
      if (!mapped || !range.intersectsNode(leaf)) continue;
      const low = leaf === range.startContainer ? range.startOffset : 0;
      const high = leaf === range.endContainer ? range.endOffset : leaf.data.length;
      if (low >= high) continue;
      if (start === null) start = mapped.start + low;
      end = mapped.start + high;
    }
    return start === null ? null : { start, end, offset_unit: 'utf16', selected_text: source.slice(start, end) };
  }
  function createRequester({ post, current, onResult, onError, onBusy }) {
    let generation = 0, controller = null;
    function cancel() { ++generation; controller?.abort(); controller = null; onBusy(false); }
    async function run(body) {
      cancel();
      const ticket = generation, requestController = new AbortController();
      controller = requestController; onBusy(true);
      try {
        const data = await post('/api/analyze-passage', body, { signal: requestController.signal });
        if (ticket !== generation || !current(body)) return;
        if (data.passage?.id !== body.passage_id || data.selection?.text !== body.selected_text
          || data.selection?.start_utf16 !== body.start || data.selection?.end_utf16 !== body.end) {
          throw new Error('The service returned a different passage or selection. Select the text again.');
        }
        onResult(data);
      } catch (error) {
        if (ticket === generation && current(body) && error.name !== 'AbortError') onError(error);
      } finally {
        if (ticket === generation) { controller = null; onBusy(false); }
      }
    }
    return { cancel, run };
  }
  function mount({ root, toolbar, getPassage, post, node, safeLink, inspectWord }) {
    const analyze = node('button', 'selection-analyze', 'Analyze selection'); analyze.type = 'button';
    toolbar.prepend(analyze);
    const extend = node('button', 'selection-extend', 'Choose end word'); extend.type = 'button';
    extend.title = 'Select a start word, activate this control, then tap or focus and activate the last word.';
    extend.setAttribute('aria-pressed', 'false'); toolbar.append(extend);
    const selectionNote = node('small', 'selection-analysis-note'); selectionNote.setAttribute('role', 'status'); toolbar.append(selectionNote);
    const panel = node('section', 'passage-analysis'); panel.hidden = true;
    panel.setAttribute('aria-label', 'Selected passage analysis');
    toolbar.after(panel);
    const heading = node('div', 'passage-analysis-heading');
    const title = node('h3', '', 'Selection analysis');
    const close = node('button', 'passage-analysis-close', 'Collapse analysis'); close.type = 'button';
    heading.append(title, close);
    const quote = node('blockquote', 'passage-analysis-selection');
    const controls = node('div', 'passage-analysis-controls');
    const machine = node('button', '', 'Fetch computational alternatives'); machine.type = 'button';
    const rerank = node('button', '', 'Ask Jev to rank alternatives'); rerank.type = 'button';
    const cancel = node('button', '', 'Cancel request'); cancel.type = 'button'; cancel.hidden = true;
    controls.append(machine, rerank, cancel);
    const status = node('p', 'candidate-reason'); status.setAttribute('role', 'status');
    const output = node('div', 'passage-analysis-output');
    panel.append(heading, quote, controls, status, output);
    let map = null, source = '', span = null, wordMode = false, busy = false, passageId = '', extending = false, includeMachine = false;
    const key = value => value ? `${value.start}:${value.end}:${value.selected_text}` : '';
    const requester = createRequester({ post,
      current: body => getPassage()?.id === body.passage_id && key(body) === key(span),
      onBusy(value) { busy = value; cancel.hidden = !value; panel.setAttribute('aria-busy', String(value)); refreshAction(); machine.disabled = value; rerank.disabled = value; },
      onError(error) { status.textContent = `Analysis unavailable: ${error.message || error}. Word lookup remains available.`; },
      onResult(data) { status.textContent = 'Source records and computational proposals are labeled separately.'; render(data); }
    });
    function say(host, text, cls = 'candidate-reason') { if (text) host.append(node('p', cls, text)); }
    function details(host, label, data) {
      const box = node('details', 'entry-details');
      box.append(node('summary', '', label), node('pre', 'passage-analysis-receipt', JSON.stringify(data, null, 2))); host.append(box);
    }
    function link(host, url, label) { const item = safeLink(url, label); if (item) host.append(item); }
    function section(label) { const part = node('section', 'passage-analysis-section'); part.append(node('h4', '', label)); output.append(part); return part; }
    function featureText(value) {
      if (!value) return '';
      return typeof value === 'string' ? value : Object.entries(value).map(([name, field]) => `${name}: ${typeof field === 'string' ? field : JSON.stringify(field)}`).join(' · ');
    }
    function candidate(host, value, label, index) {
      const card = node('div', 'candidate');
      say(card, `${label} · alternative ${index + 1}`, 'candidate-meta-label');
      say(card, value.lemma || 'Headword not supplied', 'candidate-lemma');
      say(card, value.analysis_text || featureText(value.features) || value.analysis || 'Inflection not supplied.', 'candidate-analysis');
      say(card, value.gloss, 'candidate-gloss');
      if (value.matched_form || value.attested_form) say(card, `Recorded source spelling: ${value.matched_form || value.attested_form}`);
      say(card, value.reason);
      say(card, value.source ? `Source: ${value.source}` : 'Source identity is recorded below.');
      link(card, value.source_url, 'Open analysis source');
      link(card, value.gloss_source_url, 'Open meaning source');
      details(card, 'Candidate identity and provenance', value); host.append(card);
    }
    function render(data) {
      output.replaceChildren();
      for (const warning of data.warnings || []) say(output, warning, 'warning');
      const tokenHost = section('Words and morphological alternatives');
      const syntaxTokens = data.syntax?.tokens || [];
      const words = (data.tokens || []).filter(token => token.kind === 'word');
      if (!words.length) say(tokenHost, 'No analyzable words in this literal selection. Editorial signs remain preserved above.');
      for (const token of words) {
        const box = node('details', 'passage-analysis-token'); box.open = words.length <= 3;
        const recorded = sourceCandidateGroups(token), contextual = token.contextual_candidates || [], computed = token.machine?.machine_candidates || [];
        box.append(node('summary', '', `${token.text} · ${recorded.exact.length} exact source matches · ${recorded.nearby.length} nearby spellings${recorded.other.length ? ` · ${recorded.other.length} other source matches` : ''}${contextual.length ? ` · ${contextual.length} contextual alternatives` : ''}${computed.length ? ` · ${computed.length} computational alternatives` : ''}`));
        const lookup = node('button', 'occurrence-search', 'Open word dictionary'); lookup.type = 'button';
        lookup.addEventListener('click', () => inspectWord(token.text)); box.append(lookup);
        say(box, `Original spelling · UTF-16 offsets ${token.start_utf16}–${token.end_utf16}`);
        say(box, token.candidate_scope || 'These are general form alternatives. Source ordering does not resolve this occurrence or express a probability.');
        recorded.exact.forEach((item, i) => candidate(box, item, item.analysis || item.analysis_text ? 'Source-recorded morphology · exact spelling' : 'Source dictionary match · exact spelling', i));
        contextual.forEach((item, i) => candidate(box, item, 'Source-linked contextual candidate', i));
        computed.forEach((item, i) => candidate(box, item, 'Computational morphology · proposal', i));
        if (!recorded.exact.length) say(box, 'No exact-spelling source analysis returned for this word.');
        for (const predicted of syntaxTokens.filter(item => lexicalPrediction(item) && item.start_utf16 === token.start_utf16 && item.end_utf16 === token.end_utf16 && item.text === token.text)) {
          const model = node('div', 'candidate passage-model-prediction');
          say(model, 'Contextual model prediction · exact token span', 'candidate-meta-label');
          say(model, predicted.lemma || 'Model headword unavailable', 'candidate-lemma');
          say(model, [predicted.upos, predicted.xpos, featureText(predicted.features)].filter(Boolean).join(' · '), 'candidate-analysis');
          say(model, 'One contextual parser prediction, not a verified source parse.');
          say(model, [data.syntax.provider, data.syntax.model, data.syntax.model_version].filter(Boolean).join(' · '));
          details(model, 'Model token and provenance', { token: predicted, provenance: data.syntax.provenance }); box.append(model);
        }
        for (const [items, title, label] of [
          [recorded.other, 'Other source-form matches', 'Other source spelling · not an exact match'],
          [recorded.nearby, 'Nearby spellings · not parses of this word', 'Nearby spelling—not a parse of this word']
        ]) if (items.length) {
          const suggestions = node('details', 'entry-details passage-spelling-suggestions');
          suggestions.append(node('summary', '', `${title} · ${items.length}`));
          say(suggestions, 'The analyses below belong to the displayed source spellings. They must not be read as parses of the selected word.');
          items.forEach((item, i) => candidate(suggestions, item, label, i)); box.append(suggestions);
        }
        say(box, `Computational morphology: ${String(token.machine?.status || 'unavailable').replaceAll('_', ' ')}.`);
        for (const warning of token.warnings || []) say(box, warning, 'warning');
        if (token.machine?.receipt) details(box, 'Computational provider receipt', token.machine.receipt);
        if (token.structured_evidence?.claims?.length) details(box, 'Recorded evidence and exact application scope', { evidence: token.structured_evidence, claim_applications: token.claim_applications });
        else say(box, 'No structured source annotation supplied for this word.');
        if (token.contextual_supporting_claims?.length) details(box, 'Contextual claims and application scope', { claims: token.contextual_supporting_claims, claim_applications: token.claim_applications });
        tokenHost.append(box);
      }
      const syntax = section('Syntax relationships · one model prediction');
      say(syntax, `Contextual parser: ${String(data.syntax?.status || 'unavailable').replaceAll('_', ' ')}. Proposed attachments are model output, not source annotations.`);
      say(syntax, data.syntax?.scope === 'whole_passage' ? 'The parser reads the containing passage; relationships below concern the selected words. Heads may lie outside the selection.' : 'The parser reads the selected span; relationships outside this context may be missing.');
      const relationships = syntaxTokens.filter(token => token.selected !== false && lexicalPrediction(token)).map(token => {
        const head = syntaxTokens.find(item => item.id === token.head && item.sentence_id === token.sentence_id);
        const unresolved = token.attachment_status === 'unresolved_nonlexical_head' || (head && !lexicalPrediction(head));
        return { dependent_text: token.text, head_text: unresolved ? 'unresolved attachment to nonlexical material'
          : token.head == null ? 'root' : head?.text || `unresolved head ${token.head}`, relation: unresolved ? 'uncertain' : token.deprel };
      });
      for (const relation of relationships) say(syntax, `${relation.dependent_text || relation.dependent || relation.token_id || '?'} → ${relation.head_text || relation.head || 'root'} · ${relation.relation || relation.deprel || 'unspecified relationship'}`, 'passage-syntax-link');
      if (data.syntax) details(syntax, 'Parser relationships and provenance', data.syntax);
      for (const warning of data.lint?.warnings || []) say(syntax, typeof warning === 'string' ? warning : warning.message || JSON.stringify(warning), 'warning');
      const ranking = section('Contextual ranking');
      say(ranking, `Jev: ${String(data.ranking?.status || 'not_requested').replaceAll('_', ' ')}. Probabilities are model estimates, not verified correctness rates. All original alternatives remain available above.`);
      for (const item of data.ranking?.items || []) {
        say(ranking, `${item.form || item.token_id} · ${String(item.status || 'unavailable').replaceAll('_', ' ')}`, 'candidate-meta-label');
        const candidates = item.decision?.packet?.candidates || [];
        for (const [index, ranked] of (item.ranked_candidates || []).entries()) {
          const identified = candidates.find(candidate => (candidate.id || candidate.candidate_id) === ranked.candidate_id);
          const score = typeof ranked.score_uncalibrated === 'number' && Number.isFinite(ranked.score_uncalibrated) && ranked.score_uncalibrated >= 0 && ranked.score_uncalibrated <= 1
            ? ` · ${(ranked.score_uncalibrated * 100).toFixed(1)}% model estimate` : '';
          const rankedRow = node('p', 'candidate-analysis passage-ranking-candidate', `${index + 1}. ${rankingCandidateLabel(identified) || ranked.candidate_id}${score}`);
          rankedRow.title = `Candidate ID: ${ranked.candidate_id}`; ranking.append(rankedRow);
        }
        const abstain = item.decision?.model_probabilities_uncalibrated?.abstain;
        if (typeof abstain === 'number' && Number.isFinite(abstain) && abstain >= 0 && abstain <= 1) say(ranking, `Abstain · ${(abstain * 100).toFixed(1)}% model estimate`, 'candidate-analysis passage-ranking-abstain');
        say(ranking, item.decision?.reason);
      }
      for (const warning of data.ranking?.warnings || []) say(ranking, warning, 'warning');
      if (data.ranking && data.ranking.status !== 'not_requested') details(ranking, 'Ranking estimates and provenance', data.ranking);
      const context = data.context || {}, translations = section('Published translation context');
      say(translations, 'Whole containing passage unless explicit selection alignment is supplied. This is not an exact translation of the selected phrase.');
      if (!context.published_translations?.length) say(translations, 'No published translation linked to this passage.');
      for (const item of context.published_translations || []) {
        say(translations, [item.author || item.translator, item.work, item.citation, item.source].filter(Boolean).join(' · ') || 'Linked published translation', 'translation-credit');
        say(translations, item.text || item.preview_text || item.excerpt, 'translation-text');
        link(translations, item.source_url, 'Open published translation source');
        details(translations, 'Translation scope and provenance', item);
      }
      const evidence = section('Commentary and dialect evidence');
      say(evidence, 'Authorial dialect is a contextual prior; it does not establish that every form is exclusive to that dialect.');
      if (!context.commentary?.length) say(evidence, 'No linked commentary supplied.');
      for (const item of context.commentary || []) {
        say(evidence, [item.author, item.work, item.citation].filter(Boolean).join(' · '), 'translation-credit');
        say(evidence, item.text || item.excerpt || item.preview_text, 'commentary-excerpt');
        link(evidence, item.source_url, 'Open commentary source'); details(evidence, 'Commentary scope and provenance', item);
      }
      if (context.author_profile) details(evidence, 'Authorial dialect prior and source', context.author_profile);
      if (context.structured_evidence?.claims?.length) details(evidence, 'Recorded passage evidence', context.structured_evidence);
      else say(evidence, 'No structured passage annotation supplied.');
    }
    function refreshAction() {
      const issue = !map ? 'This displayed text cannot be mapped exactly to the original passage.' : selectionIssue(span);
      analyze.disabled = busy || Boolean(issue); analyze.title = issue || 'Analyze this exact source span; Jev ranking requires a separate action.';
      extend.disabled = !span || !map;
      selectionNote.textContent = issue; selectionNote.hidden = !issue;
    }
    function change(next, word = false) {
      wordMode = word;
      if (key(next) !== key(span)) { requester.cancel(); includeMachine = false; panel.hidden = true; output.replaceChildren(); }
      span = next; refreshAction();
    }
    function request(options = {}) {
      if (!span || selectionIssue(span) || !map || !getPassage()?.id) return;
      panel.hidden = false; quote.textContent = span.selected_text;
      if (options.fetch_machine) includeMachine = true;
      status.textContent = options.rerank ? 'Requesting Jev model estimates…' : 'Looking up this exact selection…';
      requester.run({ version: 1, passage_id: getPassage().id, ...span, fetch_machine: includeMachine, rerank: false, ...options });
    }
    analyze.addEventListener('click', () => request());
    extend.addEventListener('click', () => {
      extending = !extending; extend.setAttribute('aria-pressed', String(extending));
      extend.textContent = extending ? 'Now choose the last word' : 'Choose end word';
    });
    machine.addEventListener('click', () => request({ fetch_machine: true }));
    rerank.addEventListener('click', () => request({ rerank: true }));
    cancel.addEventListener('click', () => { requester.cancel(); status.textContent = 'Request cancelled. A request already received by the service may still finish.'; });
    close.addEventListener('click', () => { requester.cancel(); panel.hidden = true; analyze.focus(); });
    return {
      refreshAction,
      wordSelection: () => wordMode ? span : null,
      hasSelection: () => Boolean(span),
      reset() { requester.cancel(); span = null; map = null; wordMode = false; passageId = ''; extending = false; includeMachine = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word'; panel.hidden = true; output.replaceChildren(); refreshAction(); },
      bind(passage) { source = String(passage.text || ''); passageId = passage.id; map = sourceMap(root, source); refreshAction(); },
      selectionChanged(selection) {
        if (!getPassage() || getPassage().id !== passageId) return;
        if ((wordMode || extending) && (!selection || !selection.rangeCount || selection.isCollapsed || selection.getRangeAt?.(0)?.collapsed)) return;
        change(selectedSpan(selection, root, map, source));
      },
      chooseWord(button) {
        const walker = root.ownerDocument.createTreeWalker(button, 4); let first = null, last = null;
        while (walker.nextNode()) { const item = map?.get(walker.currentNode); if (item) { first ??= item.start; last = item.end; } }
        if (extending && span && first !== null) { first = Math.min(first, span.start); last = Math.max(last, span.end); }
        extending = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word';
        change(first === null ? null : { start: first, end: last, offset_unit: 'utf16', selected_text: source.slice(first, last) }, true);
        if (span) { toolbar.hidden = false; const selected = toolbar.querySelector('#selected-phrase'); if (selected) selected.textContent = `“${span.selected_text}”`; }
      }
    };
  }
  window.MelosPassageAnalysis = { mount, sourceMap, selectedSpan, selectionIssue, createRequester, lexicalPrediction, sourceCandidateGroups, rankingCandidateLabel };
})();
