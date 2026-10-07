(() => {
  'use strict';
  const normalize = value => String(value || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
  const safeExternal = value => { try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; } catch { return ''; } };
  const yearLabel = n => `${Math.abs(n)} ${n < 0 ? 'BCE' : 'CE'}`;
  function chronologyOf(author) {
    const c = author?.author_chronology, claim = c?.selected_claim;
    if (!c) return null;
    const kind = claim?.kind || c.claim_kind;
    const bounds = claim?.effective_year_interval || [c.sort_start, c.sort_end];
    if (!['birth', 'floruit', 'death'].includes(kind) || !Array.isArray(bounds) || bounds.length !== 2 ||
        bounds.some(n => n === null || n === '' || !Number.isFinite(Number(n)) || Number(n) === 0)) return null;
    const [start, end] = bounds.map(Number);
    if (start > end) return null;
    const interval = start === end ? yearLabel(start) : Math.sign(start) === Math.sign(end)
      ? `${Math.abs(start)}–${Math.abs(end)} ${start < 0 ? 'BCE' : 'CE'}` : `${yearLabel(start)}–${yearLabel(end)}`;
    return { kind, interval, start, end, sort: (start + end) / 2,
      source: safeExternal(claim?.statement_url || c.source_url),
      uncertainty: Array.isArray(claim?.uncertainty) ? claim.uncertainty : Array.isArray(c.uncertainty) ? c.uncertainty : [],
      notes: Array.isArray(c.reference_notes) ? c.reference_notes : [] };
  }
  function sortedAuthors(authors) {
    return [...authors].sort((a, b) => (chronologyOf(a)?.sort ?? Infinity) - (chronologyOf(b)?.sort ?? Infinity) || a.author.localeCompare(b.author));
  }
  function filterAuthors(authors, query, catalog = new Map()) {
    const q = normalize(query);
    return authors.filter(a => [a.author, ...(a.labels || []), catalog.get(normalize(a.author))?.greek].some(v => normalize(v).includes(q)));
  }
  function passageUrl(id) {
    const params = new URLSearchParams({ id });
    return `/reader.html?${params}#passage`;
  }
  function workTypeLabel(work) {
    const kinds = [...new Set(Array.isArray(work.kinds) ? work.kinds : work.kind ? [work.kind] : [])];
    const language = String(work.language || '').toLowerCase();
    const english = /^(?:en|eng)(?:-[a-z0-9]{2,8})*$/.test(language);
    if (kinds.length > 1) return 'Mixed source material';
    if (kinds[0] === 'reference') return 'Reference metadata';
    if (kinds[0] === 'commentary') return 'Commentary';
    if (kinds[0] === 'translation') return english ? 'English translation' : language === 'ell' || language === 'el' ? 'Modern Greek translation' : 'Translation';
    if (kinds[0] === 'text' && language === 'grc') return 'Greek text';
    return language === 'grc' ? 'Greek-language source' : english ? 'English-language source' : language === 'ell' || language === 'el' ? 'Modern Greek source' : 'Indexed source';
  }
  function portraitFrame(focus, width, height, sourceWidth, sourceHeight) {
    const scale = Math.max(width / sourceWidth, height / sourceHeight, Math.min(width / (sourceWidth * focus.width), height / (sourceHeight * focus.height)));
    const imageWidth = sourceWidth * scale, imageHeight = sourceHeight * scale;
    return { width: imageWidth, height: imageHeight,
      left: Math.max(width - imageWidth, Math.min(0, width / 2 - imageWidth * focus.x)),
      top: Math.max(height - imageHeight, Math.min(0, height / 2 - imageHeight * focus.y)) };
  }
  globalThis.MelosAuthors = { normalize, safeExternal, chronologyOf, sortedAuthors, filterAuthors, passageUrl, portraitFrame, workTypeLabel };
  if (typeof document === 'undefined') return;

  const $ = selector => document.querySelector(selector);
  const make = (tag, cls = '', text = '') => { const n = document.createElement(tag); n.className = cls; n.textContent = text; return n; };
  const icon = (expand = false) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', expand ? 'M5 12h14' : 'M5 12h14M13 6l6 6-6 6'); svg.append(path);
    if (expand) { const p = document.createElementNS(svg.namespaceURI, 'path'); p.setAttribute('d', 'M12 5v14'); p.setAttribute('class', 'vertical'); svg.append(p); }
    return svg;
  };
  const state = { authors: [], catalog: new Map(), visible: 40, open: new Set(), works: new Map(), load: 0, phase: 'loading' };
  const framedImages = new Map();
  function framePortraits() {
    for (const [img, focus] of framedImages) {
      if (!img.isConnected) { framedImages.delete(img); continue; }
      const wrap = img.parentElement;
      if (!img.naturalWidth || !wrap?.clientWidth || !wrap?.clientHeight) continue;
      const frame = portraitFrame(focus, wrap.clientWidth, wrap.clientHeight, img.naturalWidth, img.naturalHeight);
      Object.assign(img.style, { width: `${frame.width}px`, height: `${frame.height}px`, left: `${frame.left}px`, top: `${frame.top}px`, transform: 'none' });
    }
  }
  window.addEventListener('resize', framePortraits);
  const params = new URLSearchParams(location.search);
  $('#author-query').value = params.get('q') || '';
  if (params.get('author')) state.open.add(params.get('author'));
  function updateUrl() {
    const url = new URL(location.href), q = $('#author-query').value.trim();
    q ? url.searchParams.set('q', q) : url.searchParams.delete('q');
    const author = [...state.open].at(-1);
    author ? url.searchParams.set('author', author) : url.searchParams.delete('author');
    history.replaceState(null, '', url);
  }
  async function api(path, values = {}) {
    const url = window.melosApiUrl(path);
    for (const [key, value] of Object.entries(values)) url.searchParams.set(key, value);
    const response = await fetch(url, { signal: AbortSignal.timeout(35000) });
    if (!response.ok) throw new Error(`Request returned ${response.status}`);
    return response.json();
  }
  function external(text, url) {
    const href = safeExternal(url);
    if (!href) return make('span', '', text);
    const a = make('a', '', text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  }
  function picture(author, portrait, expanded = false) {
    const wrap = make('span', 'portrait-wrap');
    const fallback = () => { wrap.replaceChildren(); wrap.classList.add('is-empty'); wrap.textContent = author.slice(0, 1); wrap.setAttribute('aria-label', 'No portrait available'); };
    if (!portrait?.image || !/^\/(?:assets|local-preview\/assets)\/[\w./%-]+$/.test(portrait.image)) { fallback(); return wrap; }
    const img = make('img'); img.src = portrait.image; img.alt = portrait.title || `Historical depiction associated with ${author}`; img.loading = 'lazy'; img.decoding = 'async';
    if (typeof portrait.object_position === 'string') img.style.objectPosition = portrait.object_position;
    const focus = portrait.focus;
    if (focus && ['x', 'y', 'width', 'height'].every(key => Number.isFinite(focus[key]) && focus[key] > 0 && focus[key] <= 1)) {
      // Presentation focus coordinates select a detail in the unchanged image.
      // Keep the bitmap untouched; scale its focus width to the visible frame.
      Object.assign(img.style, { position: 'absolute', width: `${100 / focus.width}%`, height: 'auto', maxWidth: 'none', left: '50%', top: '50%', transform: `translate(${-100 * focus.x}%, ${-100 * focus.y}%)` });
      if (expanded) { framedImages.set(img, focus); img.addEventListener('load', framePortraits); }
    }
    img.addEventListener('error', fallback, { once: true }); wrap.append(img);
    if (/manuscript|attributed|uncertain/i.test(portrait.caption || '')) wrap.append(make('span', 'art-type', /manuscript/i.test(portrait.caption) ? 'Manuscript' : 'Attributed portrait'));
    return wrap;
  }
  function sourceDetails(author, record) {
    const details = make('details', 'evidence'); details.append(make('summary', '', 'Dates, images & sources'));
    const date = chronologyOf(author);
    if (date) {
      const p = make('p', '', `${date.kind === 'floruit' ? 'Period of activity' : date.kind === 'birth' ? 'Birth' : 'Death'}: ${date.interval}. `);
      p.append(external('Date statement', date.source)); details.append(p);
      const uncertaintyLabels = { competing_non_deprecated_claims: 'the source contains competing dates', coarse_wikidata_time_precision: 'the date is recorded at broad precision', explicit_earliest_latest_qualifier: 'earliest/latest bounds are supplied by the source' };
      if (date.uncertainty.length) details.append(make('p', '', `Uncertainty: ${date.uncertainty.map(v => typeof v === 'string' ? uncertaintyLabels[v] || v.replaceAll('_', ' ') : v?.label || v?.note || 'qualified source claim').join('; ')}.`));
      for (const note of date.notes) if (typeof note === 'string') details.append(make('p', '', note));
      details.append(make('p', '', 'This is the selected biographical claim in the source metadata, not a lifespan or composition date.'));
    } else details.append(make('p', '', 'No supported biographical date is available in this index.'));
    const bio = record?.biography;
    if (bio?.text && safeExternal(bio.source_url)) {
      const p = make('p', '', 'Biography source: '); p.append(external(bio.source_title || 'Source', bio.source_url));
      if (safeExternal(bio.revision_url)) p.append(document.createTextNode(' · '), external('Source revision', bio.revision_url));
      if (bio.license) p.append(document.createTextNode(' · '), external(bio.license, bio.license_url));
      details.append(p);
      if (bio.attribution) details.append(make('p', '', `Text attribution: ${bio.attribution}.`));
      if (bio.extraction) details.append(make('p', '', bio.extraction));
    }
    const portrait = record?.portrait;
    if (portrait) {
      details.append(make('p', '', [portrait.title, portrait.artist, portrait.credit, portrait.license].filter(Boolean).join(' · ')));
      if (portrait.description) details.append(make('p', '', portrait.description));
      const p = make('p'); p.append(external('Image source', portrait.source_url));
      if (safeExternal(portrait.license_url)) p.append(document.createTextNode(' · '), external('License', portrait.license_url));
      details.append(p, make('p', '', 'Displayed with a crop and gentle desaturation. Historical depictions are not verified likenesses.'));
    }
    if (author.labels?.length > 1) details.append(make('p', '', `Source author labels: ${author.labels.join('; ')}.`));
    return details;
  }
  async function loadWorks(author, container) {
    const message = make('p', 'works-status', 'Loading works…'); message.setAttribute('role', 'status'); container.replaceChildren(message);
    await Promise.resolve();
    try {
      let works = state.works.get(author);
      if (!works) { const data = await api('/api/works', { author }); works = Array.isArray(data.works) ? data.works : []; state.works.set(author, works); }
      if (!container.isConnected) return;
      container.replaceChildren();
      if (!works.length) { container.append(make('p', 'works-status', 'No works are available in this index.')); return; }
      container.append(make('h4', 'works-heading', `Indexed works & source material · ${works.length.toLocaleString()}`));
      const list = make('ul', 'work-list');
      for (const work of works) {
        const item = make('li'), button = make('button', 'work-open'); button.type = 'button';
        const label = make('span'); label.append(make('strong', '', work.work || 'Untitled work'), make('small', '', [workTypeLabel(work), work.source, work.edition, work.language, work.count != null ? `${Number(work.count).toLocaleString()} source records` : ''].filter(Boolean).join(' · ')));
        button.append(label, icon());
        button.addEventListener('click', async () => {
          button.disabled = true; message.textContent = 'Opening the first indexed passage…'; container.append(message);
          try {
            const data = await api('/api/passages', { work_id: work.id, limit: 1 });
            const id = data.results?.[0]?.id;
            if (!id) { message.textContent = 'This work has no available passage.'; return; }
            location.assign(passageUrl(id));
          } catch { message.textContent = 'The passage could not be opened. Please try again.'; }
          finally { button.disabled = false; }
        });
        item.append(button); list.append(item);
      }
      container.append(list);
    } catch {
      message.textContent = 'Works could not be loaded. ';
      const retry = make('button', 'glass-button', 'Try again'); retry.type = 'button'; retry.addEventListener('click', () => loadWorks(author, container)); container.append(retry);
    }
  }
  function profile(author, record, id) {
    const detail = make('div', 'author-detail'); detail.id = id; detail.dataset.loaded = 'true';
    const layout = make('div', 'profile'), copy = make('div');
    if (record?.biography?.text && safeExternal(record.biography.source_url)) {
      copy.append(make('p', 'biography', record.biography.text));
      const credit = make('p', 'bio-source', 'Biography: '); credit.append(external(record.biography.source_title || 'Source', record.biography.source_url)); copy.append(credit);
    } else copy.append(make('p', 'biography-missing', 'A sourced biography has not yet been added. Explore the indexed works below.'));
    for (const reading of Array.isArray(record?.reading) ? record.reading : []) {
      if (!reading.text || !safeExternal(reading.source_url)) continue;
      const note = make('details', 'evidence commentary-reading'); note.append(make('summary', '', 'From the commentary'));
      note.append(make('blockquote', '', reading.text));
      const attribution = make('p'); attribution.append(external(reading.title || 'Commentary source', reading.source_url));
      if (reading.author) attribution.append(document.createTextNode(` · ${reading.author}`));
      if (reading.license) attribution.append(document.createTextNode(' · '), external(reading.license, reading.license_url));
      note.append(attribution); copy.append(note);
    }
    if (record?.portrait?.image) { const figure = make('figure', 'profile-figure'); figure.append(picture(author.author, record.portrait, true), make('figcaption', '', record.portrait.caption || 'Historical depiction · see image credits')); layout.append(figure); }
    layout.append(copy);
    detail.append(layout, sourceDetails(author, record));
    const works = make('div', 'author-works'); detail.append(works);
    // The detail is attached by the caller before the asynchronous response returns.
    loadWorks(author.author, works);
    return detail;
  }
  function render() {
    if (state.phase !== 'ready') return;
    const list = $('#author-timeline'), matching = filterAuthors(state.authors, $('#author-query').value, state.catalog);
    list.replaceChildren();
    $('#author-count').textContent = `${matching.length.toLocaleString()} ${matching.length === 1 ? 'author' : 'authors'}`;
    $('#page-status').textContent = matching.length ? '' : state.authors.length ? 'No authors match this search.' : 'No authors are currently indexed.';
    matching.slice(0, state.visible).forEach((author, i) => {
      const record = state.catalog.get(normalize(author.author)), row = make('li', 'author-row'), date = chronologyOf(author);
      const dateNode = make('div', 'author-date'); dateNode.append(make('span', 'date-kind', date ? { birth: 'Born', floruit: 'Active', death: 'Died' }[date.kind] : 'Chronology'), make('span', '', date?.interval || 'Undated'));
      const button = make('button', 'author-open'); button.type = 'button'; button.dataset.author = author.author; const detailId = `author-detail-${i}`;
      button.setAttribute('aria-expanded', String(state.open.has(author.author))); button.setAttribute('aria-controls', detailId);
      const name = make('span', 'author-name'); name.append(make('h3', '', author.author));
      if (record?.greek) { const greek = make('span', 'author-greek', record.greek); greek.lang = 'grc'; name.append(greek); }
      name.append(make('span', 'author-records', `${Number(author.count || 0).toLocaleString()} source records`));
      const expander = make('span', 'expand-icon'); expander.append(icon(true));
      button.append(name, picture(author.author, record?.portrait), expander); row.append(dateNode, button);
      let detail = make('div', 'author-detail'); detail.id = detailId; detail.hidden = true;
      if (state.open.has(author.author)) detail = profile(author, record, detailId);
      row.append(detail);
      button.addEventListener('click', () => {
        const open = !state.open.has(author.author);
        open ? state.open.add(author.author) : state.open.delete(author.author);
        button.setAttribute('aria-expanded', String(open));
        if (open && !detail.dataset.loaded) { const replacement = profile(author, record, detailId); replacement.dataset.loaded = 'true'; detail.replaceWith(replacement); detail = replacement; }
        detail.hidden = !open; updateUrl(); framePortraits();
      });
      list.append(row);
    });
    $('#show-more-authors').hidden = matching.length <= state.visible;
    framePortraits();
  }
  async function load() {
    const sequence = ++state.load;
    state.phase = 'loading';
    $('#author-timeline').setAttribute('aria-busy', 'true'); $('#retry-authors').hidden = true;
    $('#page-status').textContent = 'Loading the author collection…';
    const results = await Promise.allSettled([api('/api/authors'), fetch('/assets/authors/catalog.json').then(r => { if (!r.ok) throw new Error('No catalog'); return r.json(); })]);
    if (sequence !== state.load) return;
    $('#author-timeline').setAttribute('aria-busy', 'false');
    if (results[0].status === 'rejected') { state.phase = 'error'; $('#page-status').textContent = 'The author collection could not be reached. Please try again.'; $('#author-count').textContent = 'Collection unavailable'; $('#retry-authors').hidden = false; return; }
    state.phase = 'ready';
    state.authors = sortedAuthors((results[0].value.authors || []).filter(a => typeof a.author === 'string' && a.author));
    if (results[1].status === 'fulfilled') for (const entry of results[1].value.authors || []) if (entry.author) state.catalog.set(normalize(entry.author), entry);
    const selectedIndex = state.authors.findIndex(a => state.open.has(a.author));
    if (selectedIndex >= state.visible) state.visible = selectedIndex + 1;
    render();
  }
  $('#author-search').addEventListener('submit', event => { event.preventDefault(); state.visible = 40; render(); updateUrl(); $('#author-timeline .author-open')?.focus(); });
  $('#author-query').addEventListener('input', () => { state.visible = 40; render(); updateUrl(); });
  $('#show-more-authors').addEventListener('click', () => { const old = state.visible; state.visible += 40; render(); $('#author-timeline').querySelectorAll('.author-open')[old]?.focus(); });
  $('#retry-authors').addEventListener('click', load);
  $('#author-timeline').addEventListener('keydown', event => {
    if (!event.target.matches('.author-open') || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...$('#author-timeline').querySelectorAll('.author-open')], index = buttons.indexOf(event.target);
    event.preventDefault(); buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))].focus();
  });
  load();
})();
