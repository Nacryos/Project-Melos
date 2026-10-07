/* Source-backed browsing. Display projections never infer senses or resolve parses. */
(() => {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
  const text = value => typeof value === 'string' ? value.trim() : '';
  const alphabet = 'αβγδεζηθικλμνξοπρστυφχψω'.split('');
  const accepted = row => row && row.quarantined !== true && row.source_consistent !== false &&
    row.source_inconsistent !== true && row.assertion_type !== 'model_inference' &&
    ![row.status, row.quality, row.link_status, row.lemma_link_status].some(value => /quarantin|inconsisten|rejected|needs_review|machine_proposed/i.test(text(value)));
  function sourceUrl(value) {
    try { const url = new URL(text(value)); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
    catch { return ''; }
  }
  function readState(value) {
    const params = new URL(value).searchParams;
    const offset = Number(params.get('offset'));
    return { q: text(params.get('q')).slice(0, 100), lemma: text(params.get('lemma')).slice(0, 100),
      prefix: alphabet.includes(params.get('prefix')) ? params.get('prefix') : '',
      mode: ['auto', 'greek', 'english'].includes(params.get('mode')) ? params.get('mode') : 'auto',
      author: text(params.get('author')).slice(0, 160), offset: Number.isSafeInteger(offset) && offset > 0 ? Math.min(offset, 100000) : 0 };
  }
  function writeState(value, state) {
    const url = new URL(value);
    for (const key of ['q', 'lemma', 'prefix', 'mode', 'author', 'offset']) {
      const item = state[key];
      if (!item || key === 'mode' && item === 'auto') url.searchParams.delete(key);
      else url.searchParams.set(key, String(item));
    }
    return url;
  }
  function readerUrl(query, mode = 'exact', author = '') {
    const params = new URLSearchParams({ q: query, mode });
    if (author) params.set('author', author);
    return `/?${params}`;
  }
  function splitCandidates(data) {
    const rows = list(data?.candidates).filter(accepted);
    return { exact: rows.filter(row => row.edit_distance === 0 && ['indexed_form', 'lexicon_headword'].includes(row.match_kind)),
      nearby: rows.filter(row => Number(row.edit_distance) > 0) };
  }
  window.MelosLexiconPage = Object.freeze({ sourceUrl, readState, writeState, readerUrl, splitCandidates });
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  if (!$('lexicon-search')) return;
  const preview = window.MelosDictionaryPreview;
  const state = readState(location.href);
  let browseController, entryController, browseSequence = 0, entrySequence = 0, debounce;
  let authors = [], activeForm = '', currentData = null, latestRows = [], selectedEntryId = '';
  const node = (tag, className = '', value = '') => {
    const element = document.createElement(tag); element.className = className; element.textContent = value; return element;
  };
  function arrow(direction = 'right') {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5',
      'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false', class: 'lexicon-icon' })) svg.setAttribute(key, value);
    const path = document.createElementNS(namespace, 'path');
    path.setAttribute('d', direction === 'external' ? 'M6 18 18 6M6 6h12v12' : direction === 'left' ? 'M19 12H5m6-6-6 6 6 6' : 'M5 12h14m-6-6 6 6-6 6');
    svg.append(path); return svg;
  }
  for (const host of document.querySelectorAll('[data-lexicon-arrow]')) host.append(arrow(host.dataset.lexiconArrow));
  function link(url, label) {
    const safe = sourceUrl(url); if (!safe) return null;
    const anchor = node('a', 'source-link', label); anchor.href = safe; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; anchor.append(arrow('external')); return anchor;
  }
  function addLink(host, url, label) { const anchor = link(url, label); if (anchor) host.append(anchor); }
  function save(push = false) { history[push ? 'pushState' : 'replaceState'](null, '', writeState(location.href, state)); }
  function api(path, params, signal) {
    const suffix = new URLSearchParams(params);
    return window.melosApiFetch(`${path}?${suffix}`, { signal }).then(async response => {
      if (!response.ok) throw new Error(`The corpus service returned ${response.status}.`);
      const data = await response.json();
      if (data.ready === false) throw new Error(text(data.message) || 'The source index is not ready.');
      return data;
    });
  }
  function warnings(host, rows) { for (const value of list(rows)) if (text(value)) host.append(node('p', 'warning', value)); }
  function error(host, message, retry) {
    const box = node('div', 'lookup-error'); box.append(node('p', 'warning', message));
    const button = node('button', '', 'Try again'); button.type = 'button'; button.addEventListener('click', retry); box.append(button); host.append(box);
  }
  function syncControls() {
    $('lexicon-query').value = state.q; $('lexicon-mode').value = state.mode;
    for (const button of $('lexicon-alphabet').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.letter === state.prefix));
  }
  function markSelection() {
    let marked = false;
    for (const button of $('headword-list').querySelectorAll('button')) {
      const current = !marked && button.dataset.lemma === state.lemma && (!selectedEntryId || button.dataset.entry === selectedEntryId);
      button.setAttribute('aria-current', String(current)); if (current) marked = true;
    }
  }
  function selectEnglishResult() {
    if (state.mode !== 'auto' || !state.q || activeForm !== state.q || !currentData || !latestRows.length || splitCandidates(currentData).exact.length) return;
    const first = latestRows[0]; selectEntry(text(first.headword) || text(first.lemma), false, text(first.id));
  }
  async function browse() {
    browseController?.abort(); browseController = new AbortController(); const sequence = ++browseSequence;
    $('headword-list').replaceChildren(); $('headword-prev').disabled = true; $('headword-next').disabled = true;
    $('browse-status').textContent = 'Loading source headwords…'; $('headword-count').textContent = ''; $('headword-page').textContent = ''; $('browse-note').textContent = '';
    $('headword-list').setAttribute('aria-busy', 'true');
    try {
      const data = await api('/api/lexicon', { q: state.q, prefix: state.prefix, mode: state.mode, limit: 30, offset: state.offset }, browseController.signal);
      if (sequence !== browseSequence) return;
      const rows = list(data.results).filter(accepted); latestRows = rows;
      $('headword-count').textContent = Number.isFinite(data.total) ? Number(data.total).toLocaleString() : '';
      $('browse-status').textContent = rows.length ? state.q ? `Matches for “${state.q}”` : state.prefix ? `Beginning with ${state.prefix}` : 'Alphabetical headwords' : 'No matching headwords. Try another spelling or meaning.';
      for (const row of rows) {
        const lemma = text(row.headword) || text(row.lemma); if (!lemma) continue;
        const item = node('li'); const button = node('button'); button.type = 'button'; button.dataset.lemma = lemma; button.dataset.entry = text(row.id);
        const greek = node('span', 'headword-greek', lemma); greek.lang = 'grc'; button.append(greek);
        if (text(row.meaning)) button.append(node('span', 'headword-gloss', row.meaning));
        if (text(row.source)) button.append(node('span', 'headword-gloss', preview?.friendlySourceName(row.source) || row.source));
        button.addEventListener('click', () => selectEntry(lemma, true, text(row.id))); item.append(button); $('headword-list').append(item);
      }
      markSelection();
      $('headword-prev').disabled = state.offset === 0; $('headword-next').disabled = !data.has_more;
      $('headword-page').textContent = rows.length ? `${state.offset + 1}–${state.offset + rows.length}` : '';
      $('browse-note').textContent = list(data.warnings).map(text).filter(Boolean).join(' ');
      if (!state.lemma && rows.length) selectEntry(text(rows[0].headword) || text(rows[0].lemma), false, text(rows[0].id));
      else selectEnglishResult();
    } catch (err) {
      if (sequence !== browseSequence || err.name === 'AbortError') return;
      $('browse-status').textContent = 'Headword browser unavailable.';
      const item = node('li'); error(item, err.message, browse); $('headword-list').append(item);
    } finally { if (sequence === browseSequence) $('headword-list').setAttribute('aria-busy', 'false'); }
  }
  function renderDictionary(host, data) {
    const view = preview?.buildPreview(data);
    const entries = [...list(view?.entries)];
    // A verified short gloss may be unavailable while the source entry itself
    // remains readable. Preserve that distinction instead of hiding the entry.
    const exact = splitCandidates(data).exact;
    for (const raw of list(data.lexicon_entries).filter(accepted)) {
      const id = text(raw.id) || `${text(raw.source_url)}#${text(raw.entry_id)}`;
      if (entries.some(entry => entry.id === id) || !sourceUrl(raw.source_url) || !exact.some(candidate =>
        text(candidate.lemma).normalize('NFC') === text(raw.lemma).normalize('NFC') &&
        (list(candidate.lexicon_entry_ids).includes(id) || candidate.gloss_entry_id === id))) continue;
      entries.push({ id, lemma: text(raw.lemma), source: text(raw.source), source_url: raw.source_url,
        entry_url: sourceUrl(raw.entry_url) || raw.source_url, meanings: [] });
    }
    entries.sort((a, b) => Number(b.id === selectedEntryId) - Number(a.id === selectedEntryId));
    if (!entries.length) host.append(node('p', 'subtle', 'No safely linked dictionary excerpt is available for this form. Recorded analyses, when available, appear below.'));
    for (const entry of entries) {
      const card = node('article', 'dictionary-card'); const heading = node('h3', '', entry.lemma); heading.lang = 'grc'; card.append(heading);
      const source = node('p', 'dictionary-source'); addLink(source, entry.source_url, preview.friendlySourceName(entry.source)); card.append(source);
      const meanings = node('ol', 'meaning-list');
      for (const meaning of list(entry.meanings)) meanings.append(node('li', '', meaning.text));
      if (meanings.childNodes.length) card.append(meanings);
      else card.append(node('p', 'subtle', 'No verified short meaning is available. Read the original source entry below.'));
      const raw = list(data.lexicon_entries).find(row => (text(row.id) || `${text(row.source_url)}#${text(row.entry_id)}`) === entry.id);
      const full = text(raw?.rendered_entry_text) || text(raw?.entry_text) || text(raw?.gloss);
      const details = node('details'); details.append(node('summary', '', 'Read full source entry'));
      if (full) details.append(node('p', 'full-entry', full));
      if (raw?.rendering_warning) details.append(node('p', 'fine-print', raw.rendering_warning));
      if (raw?.dictionary_senses_warning) details.append(node('p', 'fine-print', raw.dictionary_senses_warning));
      if (full && !raw?.rendered_entry_text && raw?.entry_text) details.append(node('p', 'fine-print', 'Original source encoding; Beta Code may appear.'));
      addLink(details, entry.entry_url || entry.source_url, 'Open dictionary source'); card.append(details); host.append(card);
    }
  }
  function renderCandidates(host, rows, title) {
    if (!rows.length) return;
    const details = node('details', 'lexicon-advanced'); details.append(node('summary', '', `${title} · ${rows.length}`));
    details.append(node('p', 'fine-print', title.startsWith('Nearby') ? 'These analyses belong to different source spellings. They are not parses of the searched form.' : 'Recorded source alternatives, not a resolved parsing in context. Headword records may have no inflectional analysis.'));
    for (const row of rows) {
      const card = node('div', 'analysis-card'); const lemma = node('p', 'analysis-lemma', text(row.lemma)); lemma.lang = 'grc'; card.append(lemma);
      card.append(node('p', '', text(row.analysis_text) || text(row.analysis) || 'Dictionary headword; no recorded form analysis.'));
      if (row.matched_form && row.matched_form !== activeForm) card.append(node('p', 'fine-print', `Source spelling: ${row.matched_form}`));
      if (row.lemma_link_status === 'ambiguous_source_lemmas') card.append(node('p', 'warning', 'The source form is linked to more than one lemma; the link remains unresolved.'));
      addLink(card, row.source_url, preview?.friendlySourceName(row.source) || 'Analysis source'); details.append(card);
    }
    host.append(details);
  }
  function readerLinks(host) {
    const box = node('section', 'entry-tools'); box.append(node('h3', '', 'Read the word in context'));
    const label = node('label', '', 'Limit reader results to an author'); label.htmlFor = 'lexicon-author';
    const select = node('select'); select.id = 'lexicon-author'; const all = node('option', '', 'All indexed authors'); all.value = ''; select.append(all);
    const options = [...authors]; if (state.author && !options.includes(state.author)) options.unshift(state.author);
    for (const author of options) { const option = node('option', '', author); option.value = author; select.append(option); }
    select.value = state.author; box.append(label, select);
    const links = node('div', 'reader-links');
    function update() {
      links.replaceChildren();
      for (const [mode, title] of [['exact', 'Find this spelling'], ['forms', 'Explore indexed forms']]) {
        const anchor = node('a', '', title); anchor.href = readerUrl(activeForm, mode, state.author); anchor.append(arrow()); links.append(anchor);
      }
    }
    select.addEventListener('change', () => { state.author = select.value; save(); update(); }); update(); box.append(links);
    box.append(node('p', 'fine-print', 'The author filter applies to passages in the reader. Dictionary definitions are not author-specific.')); host.append(box);
  }
  function renderAdvanced(host, data) {
    const groups = list(data.observed_form_groups).filter(accepted);
    if (groups.length) {
      const details = node('details', 'lexicon-advanced'); details.append(node('summary', '', 'Source form inventories'));
      details.append(node('p', 'fine-print', 'Indexed source forms, grouped by source lemma. These are not complete dialect paradigms.'));
      for (const group of groups) {
        details.append(node('h3', '', text(group.lemma_raw) || text(group.lemma)));
        if (group.source) details.append(node('p', 'fine-print', preview?.friendlySourceName(group.source) || group.source));
        if (group.query_relation) details.append(node('p', 'fine-print', `Query relation: ${text(group.query_relation).replaceAll('_', ' ')}`));
        if (group.identity_status === 'unnumbered_homograph_ambiguous') details.append(node('p', 'warning', 'This unnumbered source lemma cannot distinguish its homographs.'));
        const forms = node('div', 'inventory-forms');
        for (const row of list(group.forms).filter(row => typeof row === 'string' || accepted(row))) {
          const form = typeof row === 'string' ? row : text(row.form); if (!form) continue;
          const button = node('button', '', form); button.type = 'button'; button.lang = 'grc'; button.addEventListener('click', () => selectEntry(form, true)); forms.append(button);
        }
        if (!forms.childNodes.length) forms.append(node('p', 'subtle', 'Open the contextual reader to inspect this source inventory.'));
        details.append(forms);
        if (group.truncated) details.append(node('p', 'fine-print', `Showing ${group.shown_forms} of ${group.total_forms} indexed forms.`));
        const sourceLinks = new Set();
        for (const row of list(group.forms)) for (const reference of list(row.source_refs)) {
          const url = sourceUrl(reference.source_url); if (!url || sourceLinks.has(url)) continue;
          sourceLinks.add(url); const paragraph = node('p', 'fine-print'); addLink(paragraph, url, preview?.friendlySourceName(reference.source) || 'Inventory source'); details.append(paragraph);
        }
      }
      host.append(details);
    }
    const details = node('details', 'lexicon-advanced'); details.append(node('summary', '', 'Lookup notes & sources'));
    if (preview?.buildPreview(data)?.ambiguous) details.append(node('p', 'fine-print', 'Dictionary alternatives are shown separately. No meaning or parsing has been selected for a passage.'));
    if (data.method) details.append(node('p', 'fine-print', data.method));
    warnings(details, data.warnings);
    details.append(node('p', 'fine-print', 'English lookup searches indexed dictionary meanings. Coverage depends on the indexed sources. Passage-specific evidence, parallel contexts and further analysis are available in the reader.')); host.append(details);
  }
  function renderEntry(data) {
    const host = $('entry-body'); host.replaceChildren(); renderDictionary(host, data); readerLinks(host);
    const candidates = splitCandidates(data); renderCandidates(host, candidates.exact, 'Recorded parsing alternatives'); renderCandidates(host, candidates.nearby, 'Nearby source spellings'); renderAdvanced(host, data);
  }
  async function selectEntry(form, push = false, entryId = '') {
    if (!form) return;
    entryController?.abort(); entryController = new AbortController(); const sequence = ++entrySequence;
    state.lemma = form; activeForm = form; selectedEntryId = entryId; currentData = null; save(push); markSelection();
    $('entry-heading').textContent = form; $('entry-heading').lang = 'grc'; $('entry-status').textContent = 'Looking up sources…';
    $('entry-body').replaceChildren(node('p', 'subtle', 'Retrieving dictionary entries and recorded forms…')); $('entry-panel').setAttribute('aria-busy', 'true');
    if (push && window.matchMedia('(max-width: 800px)').matches) $('headword-browser').open = false;
    try {
      const data = await api('/api/word', { form }, entryController.signal); if (sequence !== entrySequence) return;
      currentData = data; renderEntry(data); $('entry-status').textContent = 'Source lookup complete'; selectEnglishResult();
    } catch (err) {
      if (sequence !== entrySequence || err.name === 'AbortError') return;
      $('entry-body').replaceChildren(); error($('entry-body'), `Word lookup unavailable. ${err.message}`, () => selectEntry(form)); $('entry-status').textContent = 'Lookup unavailable';
    } finally { if (sequence === entrySequence) $('entry-panel').setAttribute('aria-busy', 'false'); }
  }
  function search(push = false) {
    clearTimeout(debounce); state.q = $('lexicon-query').value.trim().slice(0, 100); state.mode = $('lexicon-mode').value; state.offset = 0; state.prefix = ''; state.lemma = '';
    entryController?.abort(); ++entrySequence; currentData = null; activeForm = ''; latestRows = []; selectedEntryId = '';
    $('entry-panel').setAttribute('aria-busy', 'false'); $('entry-status').textContent = ''; $('entry-heading').textContent = state.q ? 'Search the sources' : 'A place to begin'; $('entry-heading').removeAttribute('lang');
    $('entry-body').replaceChildren(node('p', 'subtle', 'Choose a matching headword to read its dictionary entries.'));
    save(push); syncControls();
    if (state.q && state.mode !== 'english' && preview?.isCandidateQuery(state.q)) selectEntry(state.q);
    browse();
  }
  for (const letter of ['', ...alphabet]) {
    const button = node('button', letter ? '' : 'alphabet-all', letter || 'All headwords'); button.type = 'button'; button.dataset.letter = letter;
    if (letter) { button.lang = 'grc'; button.setAttribute('aria-label', `Headwords beginning with ${letter}`); }
    button.addEventListener('click', () => { clearTimeout(debounce); entryController?.abort(); ++entrySequence; currentData = null; latestRows = []; selectedEntryId = ''; state.prefix = letter; state.q = ''; state.lemma = ''; state.offset = 0; state.mode = 'auto'; $('entry-panel').setAttribute('aria-busy', 'false'); $('entry-status').textContent = ''; $('entry-heading').textContent = 'Choose a headword'; $('entry-heading').removeAttribute('lang'); $('entry-body').replaceChildren(node('p', 'subtle', 'Choose a matching headword to read its dictionary entries.')); save(true); syncControls(); browse(); }); $('lexicon-alphabet').append(button);
  }
  $('lexicon-search').addEventListener('submit', event => { event.preventDefault(); search(true); });
  $('lexicon-query').addEventListener('input', () => { clearTimeout(debounce); browseController?.abort(); entryController?.abort(); ++browseSequence; ++entrySequence; debounce = setTimeout(() => search(), 320); });
  $('lexicon-mode').addEventListener('change', () => search(true));
  for (const [id, change] of [['headword-prev', -30], ['headword-next', 30]]) $(id).addEventListener('click', () => { state.offset = Math.max(0, state.offset + change); save(true); browse(); });
  window.addEventListener('popstate', () => { clearTimeout(debounce); latestRows = []; selectedEntryId = ''; Object.assign(state, readState(location.href)); syncControls(); if (state.lemma) selectEntry(state.lemma); else { entryController?.abort(); ++entrySequence; currentData = null; $('entry-panel').setAttribute('aria-busy', 'false'); $('entry-body').replaceChildren(); $('entry-status').textContent = ''; $('entry-heading').textContent = 'Choose a headword'; } browse(); });
  syncControls(); browse(); if (state.lemma) selectEntry(state.lemma); else if (state.q && state.mode !== 'english' && preview?.isCandidateQuery(state.q)) selectEntry(state.q);
  api('/api/authors', {}).then(data => { authors = list(data.authors).map(row => text(row.author)).filter(Boolean); if (currentData) renderEntry(currentData); }).catch(() => {});
})();
