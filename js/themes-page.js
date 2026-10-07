/* Dedicated discovery browser. Source text is always rendered as text, never HTML. */
(() => {
  'use strict';
  const UNITS = ['passage', 'stanza', 'line', 'sentence', 'phrase', 'word'];
  const PAGE_SIZE = 20;
  const IDEAS = [
    ['love', 'Love & desire'], ['unrequited_love', 'Unrequited love'],
    ['politics', 'Politics & civic life'], ['sympotic_song', 'Sympotic song'],
    ['melic_song', 'Melic song'], ['war', 'War & courage'],
    ['memory', 'Memory & loss'], ['religion', 'Gods & prayer']
  ];
  const NATURE_COPY = {
    garden_grove: 'Among blossoms, shade and sacred groves',
    meadow_pasture: 'Open fields, flowers and the pastoral world',
    mountain_woodland: 'High places, forests and the untamed earth',
    river_spring: 'Flowing water, springs and their banks',
    sea_coast: 'Waves, shores and journeys over water'
  };
  function parseState(search) {
    const params = new URLSearchParams(search);
    const rawOffset = params.get('offset') || '0';
    const offset = /^\d+$/.test(rawOffset) && Number.isSafeInteger(Number(rawOffset)) ? Number(rawOffset) : 0;
    return { q: (params.get('q') || '').trim().slice(0, 200), theme: (params.get('theme') || '').slice(0, 100),
      author: (params.get('author') || '').trim().slice(0, 200), unit: UNITS.includes(params.get('unit')) ? params.get('unit') : 'passage',
      offset: Math.floor(Math.min(offset, 100000) / PAGE_SIZE) * PAGE_SIZE };
  }
  function stateParams(state, api = false) {
    const params = new URLSearchParams();
    for (const key of ['q', 'theme', 'author']) if (state[key]) params.set(key, state[key]);
    if (state.unit !== 'passage' || api) params.set('unit', state.unit);
    if (state.offset || api) params.set('offset', String(state.offset));
    if (api) params.set('limit', String(PAGE_SIZE));
    return params;
  }
  function groupResults(results) {
    const groups = new Map();
    for (const item of results) {
      const id = item.passage_id || item.parent_id || (item.unit === 'passage' ? item.id : '');
      if (!id) continue;
      if (!groups.has(id)) groups.set(id, { id, passage: item, units: [] });
      groups.get(id).units.push(item);
    }
    return [...groups.values()];
  }
  function safeExternal(value) {
    try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
  }
  function readerLink(id) { return `/?${new URLSearchParams({ id: String(id) })}`; }
  // Pure helpers make URL and hierarchy contracts independently testable.
  window.MelosThemes = { parseState, stateParams, groupResults, safeExternal, readerLink };
  const $ = id => document.getElementById(id);
  if (!$('theme-search')) return;
  const ui = { form: $('theme-search'), query: $('theme-query'), theme: $('theme-filter'), author: $('theme-author'), unit: $('theme-unit'),
    section: $('theme-results-section'), results: $('theme-results'), status: $('theme-status'), pagination: $('theme-pagination'),
    previous: $('theme-previous'), next: $('theme-next'), page: $('theme-page'), evidence: $('search-evidence'), evidenceBody: $('search-evidence-body'), retry: $('theme-retry') };
  const presets = window.MelosNaturePresetData?.presets || {};
  let state = parseState(location.search), requestId = 0, controller;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  function categoryLink(id, label, className) {
    const link = element('a', className);
    link.href = `/themes?${new URLSearchParams({ theme: id })}`;
    link.setAttribute('aria-label', `Explore ${label}`);
    link.addEventListener('click', event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
      event.preventDefault();
      navigate({ ...state, q: '', theme: id, offset: 0 }, true);
    });
    return link;
  }
  function addThemeOption(id, label, group) {
    const option = element('option', '', label); option.value = id; group.append(option);
  }
  function renderCategories(ideas = IDEAS) {
    $('nature-categories').replaceChildren(); $('idea-categories').replaceChildren();
    ui.theme.replaceChildren(element('option', '', 'All themes')); ui.theme.firstChild.value = '';
    const natureGroup = element('optgroup'); natureGroup.label = 'Nature annotations';
    const ideaGroup = element('optgroup'); ideaGroup.label = 'Explore ideas';
    Object.entries(presets).forEach(([id, preset], index) => {
      const link = categoryLink(id, preset.title, 'nature-row');
      const image = element('img'); image.alt = ''; image.loading = 'lazy'; image.decoding = 'async'; image.width = 960; image.height = 540;
      // Images are drawn only from the shipped, compressed preset manifest.
      image.src = preset.smallUrl || preset.url;
      if (preset.smallUrl && preset.url) { image.srcset = `${preset.smallUrl} 480w, ${preset.url} 960w`; image.sizes = '(max-width: 760px) calc(100vw - 40px), 1124px'; }
      const copy = element('span', 'nature-row-copy');
      copy.append(element('span', 'row-number', String(index + 1).padStart(2, '0')), element('span', 'nature-row-title', preset.title), element('span', 'nature-row-subtitle', NATURE_COPY[id] || 'Explore this landscape'));
      link.append(image, copy); $('nature-categories').append(link); addThemeOption(id, preset.title, natureGroup);
    });
    for (const [id, label] of ideas) {
      const link = categoryLink(id, label, 'idea-link');
      link.append(element('strong', '', label), element('span', '', 'Explore'));
      $('idea-categories').append(link); addThemeOption(id, label, ideaGroup);
    }
    ui.theme.append(natureGroup, ideaGroup);
    if (state.theme && ![...ui.theme.options].some(option => option.value === state.theme)) addThemeOption(state.theme, state.theme.replaceAll('_', ' '), ui.theme);
    ui.theme.value = state.theme;
  }
  function syncForm() { ui.query.value = state.q; ui.theme.value = state.theme; ui.author.value = state.author; ui.unit.value = state.unit; }
  async function request(path, signal) {
    const response = await window.melosApiFetch(path, { signal });
    if (!response.ok) throw new Error(`The corpus service could not complete this request (${response.status}).`);
    return response.json();
  }
  function sourceCaption(item) {
    const caption = element('p', 'source-caption', [item.citation, item.source, item.edition].filter(Boolean).join(' · ') || 'Source citation not supplied');
    const href = safeExternal(item.source_url);
    if (href) { const link = element('a', '', 'Source'); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; caption.append(link); }
    return caption;
  }
  function renderResults(data) {
    const groups = groupResults(Array.isArray(data.results) ? data.results : []);
    ui.results.replaceChildren();
    for (const group of groups) {
      const article = element('article', 'passage-group');
      const heading = element('h3'); const parent = element('a', '', [group.passage.author, group.passage.work].filter(Boolean).join(' · ') || 'Source passage');
      parent.href = readerLink(group.id); heading.append(parent);
      article.append(heading, sourceCaption(group.passage));
      const list = element('ol', 'unit-results');
      for (const item of group.units) {
        const hit = element('li', 'unit-hit');
        const label = `${item.unit || state.unit}${Number.isInteger(item.start) && Number.isInteger(item.end) ? ` · source characters ${item.start}–${item.end}` : ''}`;
        const quote = element('blockquote', '', item.quote ?? item.text ?? '');
        if (item.language === 'grc') quote.lang = 'grc';
        const open = element('a', '', item.unit && item.unit !== 'passage' ? 'Read in its parent passage' : 'Open in the reader'); open.href = readerLink(group.id);
        hit.append(element('p', 'unit-label', label), quote, open);
        if (item.segmentation_method || item.match_reason || item.offset_basis || item.unit_embedding_method) {
          const detail = element('details', 'unit-details'); detail.append(element('summary', '', 'Match and source span'));
          if (item.match_reason) detail.append(element('p', '', `Match: ${typeof item.match_reason === 'string' ? item.match_reason : JSON.stringify(item.match_reason)}`));
          if (item.segmentation_method) detail.append(element('p', '', `Division: ${item.segmentation_method}`));
          if (item.offset_basis) detail.append(element('p', '', `Offsets: ${item.offset_basis}`));
          if (item.unit_embedding_method) detail.append(element('p', '', `Span ranking: ${item.unit_embedding_method}. Similarity is a ranking signal, not calibrated confidence.`));
          hit.append(detail);
        }
        list.append(hit);
      }
      article.append(list); ui.results.append(article);
    }
    const length = (data.results || []).length;
    const total = Number.isFinite(data.total) ? data.total : null;
    const contract = data.search_contract || {};
    const boundedLabel = contract.complete === false ? ' · within a bounded candidate selection' : '';
    ui.status.textContent = length ? `${state.offset + 1}–${state.offset + length}${total === null ? '' : ` of ${total}`} retrieved ${state.unit === 'passage' ? 'passages' : `${state.unit}s`} · grouped by source passage${boundedLabel}` : 'No matching source spans found. Try another theme, a broader phrase, or Passage as the search unit.';
    ui.previous.disabled = state.offset === 0; ui.next.disabled = data.has_more !== true;
    ui.pagination.hidden = state.offset === 0 && data.has_more !== true;
    ui.page.textContent = `Page ${Math.floor(state.offset / PAGE_SIZE) + 1}`;
    ui.evidenceBody.replaceChildren();
    if (data.method) ui.evidenceBody.append(element('p', '', `Retrieval method: ${data.method}`));
    const child = contract.child_semantic_reranking;
    if (child?.available === true) {
      ui.evidenceBody.append(element('p', '', `Child spans: ${child.method || 'On-demand local semantic ranking of exact source spans.'}`));
      if (Number.isFinite(child.encoded_units) && Number.isFinite(child.candidate_units)) ui.evidenceBody.append(element('p', '', `${child.encoded_units} source spans encoded from ${child.candidate_units} candidate spans. These embeddings are computed on demand; there is no separately stored child index.`));
      const bounds = [Number.isFinite(child.unit_limit) ? `up to ${child.unit_limit} spans` : '', Number.isFinite(child.parent_limit) ? `from the first ${child.parent_limit} retrieved parents` : '', Number.isFinite(child.source_character_limit_per_unit) ? `at most ${child.source_character_limit_per_unit} source characters per span` : ''].filter(Boolean);
      if (bounds.length) ui.evidenceBody.append(element('p', '', `Encoding bounds: ${bounds.join('; ')}.`));
      if (Number.isFinite(child.token_limit_including_special_tokens)) ui.evidenceBody.append(element('p', '', `Model input limit: ${child.token_limit_including_special_tokens} tokens per span, including special tokens.`));
      if (Number.isFinite(child.tokenizer_rejected_units) && child.tokenizer_rejected_units > 0) ui.evidenceBody.append(element('p', '', `${child.tokenizer_rejected_units} candidate spans exceeded the model token limit and were omitted from semantic reranking.`));
      if (child.sampling) ui.evidenceBody.append(element('p', '', `Selection: ${child.sampling}`));
    } else if (child?.reason) ui.evidenceBody.append(element('p', '', `Child semantic ranking: ${child.reason}`));
    if (contract.child_ranking && child?.available !== true) ui.evidenceBody.append(element('p', '', `Span order: ${contract.child_ranking}`));
    if (contract.total_scope) ui.evidenceBody.append(element('p', '', `Result count scope: ${contract.total_scope}.`));
    for (const warning of Array.isArray(data.warnings) ? data.warnings : []) ui.evidenceBody.append(element('p', '', typeof warning === 'string' ? warning : JSON.stringify(warning)));
    ui.evidence.hidden = !ui.evidenceBody.childNodes.length;
  }
  async function search(focus = false) {
    const sequence = ++requestId;
    controller?.abort(); controller = new AbortController();
    ui.results.replaceChildren(); ui.pagination.hidden = true; ui.evidence.hidden = true; ui.retry.hidden = true;
    if (!state.q && !state.theme && !state.author) { ui.section.hidden = true; ui.results.setAttribute('aria-busy', 'false'); return; }
    ui.section.hidden = false; ui.results.setAttribute('aria-busy', 'true'); ui.status.textContent = 'Searching the corpus…';
    if (focus) { $('results-heading').focus({ preventScroll: true }); ui.section.scrollIntoView({ block: 'start' }); }
    try {
      const data = await request(`/api/theme-search?${stateParams(state, true)}`, controller.signal);
      if (sequence !== requestId) return;
      renderResults(data);
    } catch (error) {
      if (sequence !== requestId || error.name === 'AbortError') return;
      ui.status.textContent = error.message || 'Theme search is unavailable. Please try again.'; ui.retry.hidden = false;
    } finally { if (sequence === requestId) ui.results.setAttribute('aria-busy', 'false'); }
  }
  function navigate(next, focus = false) {
    state = parseState(stateParams(next)); syncForm();
    const query = stateParams(state).toString();
    history.pushState(null, '', `/themes${query ? `?${query}` : ''}`);
    search(focus);
  }
  ui.form.addEventListener('submit', event => { event.preventDefault(); navigate({ q: ui.query.value, theme: ui.theme.value, author: ui.author.value, unit: ui.unit.value, offset: 0 }, true); });
  $('theme-reset').addEventListener('click', () => navigate({ q: '', theme: '', author: '', unit: 'passage', offset: 0 }));
  ui.previous.addEventListener('click', () => { if (!ui.previous.disabled) navigate({ ...state, offset: Math.max(0, state.offset - PAGE_SIZE) }, true); });
  ui.next.addEventListener('click', () => { if (!ui.next.disabled) navigate({ ...state, offset: state.offset + PAGE_SIZE }, true); });
  ui.retry.addEventListener('click', () => search());
  window.addEventListener('popstate', () => { state = parseState(location.search); renderCategories(); syncForm(); search(); });
  renderCategories(); syncForm(); search();
  Promise.allSettled([request('/api/discovery-catalog'), request('/api/authors')]).then(([catalog, authors]) => {
    if (catalog.status === 'fulfilled') {
      const ideas = (catalog.value.themes || []).filter(theme => theme.kind === 'retrieval_prompt' && typeof theme.id === 'string' && typeof theme.label === 'string').map(theme => [theme.id, theme.label]);
      if (ideas.length) renderCategories(ideas);
    } else $('catalog-note').textContent = 'The live theme catalog is unavailable. The collection’s saved categories are shown.';
    if (authors.status === 'fulfilled') for (const item of authors.value.authors || []) {
      if (typeof item.author !== 'string') continue;
      const option = element('option'); option.value = item.author; $('theme-authors').append(option);
    }
  });
})();
