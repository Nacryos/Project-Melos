/* Melos passage usage space. The API supplies every plotted coordinate. */
(() => {
  'use strict';

  let active = null;
  const STYLE_ID = 'melos-usage-space-style';
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    if (tag === 'a' || tag === 'button') window.MelosIcons?.decorate(node);
    return node;
  }

  function safeUrl(value) {
    if (!value || typeof value !== 'string') return null;
    try {
      const url = new URL(value, window.location.href);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  function year(value) {
    return value < 0 ? `${Math.abs(value)} BCE` : `${value} CE`;
  }

  function dateLabel(point) {
    // The source is required for a displayed chronology, not merely a numeric field.
    if (!point.date_source) return '';
    const start = Number(point.date_start);
    const end = Number(point.date_end);
    const validYear = (raw, numeric) => raw !== null && raw !== undefined &&
      (typeof raw === 'number' || (typeof raw === 'string' && raw.trim() !== '')) &&
      Number.isInteger(numeric) && numeric !== 0;
    const hasStart = validYear(point.date_start, start);
    const hasEnd = validYear(point.date_end, end);
    if (hasStart && hasEnd) return start === end ? year(start) : `${year(start)}–${year(end)}`;
    if (hasStart) return `from ${year(start)}`;
    if (hasEnd) return `by ${year(end)}`;
    return '';
  }

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = element('style');
    style.id = STYLE_ID;
    style.textContent = `
      .mus-overlay { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: clamp(8px, 2vw, 26px); background: rgba(9, 16, 28, .78); backdrop-filter: blur(7px); }
      .mus-dialog, .mus-dialog * { box-sizing: border-box; }
      .mus-dialog { width: min(1320px, 100%); height: min(900px, 100%); min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; overflow: hidden; border: 1px solid #aab2b5; border-radius: 5px; background: #edf0ef; color: #14223a; box-shadow: 0 24px 80px rgba(0,0,0,.45); font: 400 1rem/1.45 "Gentium Book Plus", Georgia, serif; }
      .mus-dialog button, .mus-dialog a { font: inherit; }
      .mus-dialog button { cursor: pointer; }
      .mus-dialog :focus-visible { outline: 2px solid #d39a2c; outline-offset: 2px; }
      .mus-head { display: flex; align-items: start; justify-content: space-between; gap: 1rem; padding: 1rem 1.3rem .85rem; border-bottom: 1px solid #cbd3d4; }
      .mus-eyebrow { margin: 0 0 .16rem; color: #46657c; font: 600 .72rem/1.2 system-ui, sans-serif; text-transform: uppercase; letter-spacing: .15em; }
      .mus-title { margin: 0; font: 400 clamp(1.5rem, 2.3vw, 2.25rem)/1.15 "GFS Didot", Georgia, serif; }
      .mus-subtitle { margin: .25rem 0 0; color: #4a5661; font-size: .9rem; }
      .mus-close { flex: none; border: 1px solid #aeb8bc; border-radius: 3px; background: transparent; padding: .35rem .65rem; }
      .mus-main { min-height: 0; display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(310px, .65fr); grid-template-rows: minmax(0, 1fr); overflow: auto; }
      .mus-visual { min-width: 0; min-height: 0; display: grid; grid-template-rows: minmax(120px, 1fr) auto; background: #101d30; color: #ecf1ef; }
      .mus-plot { position: relative; min-height: 0; overflow: hidden; background: radial-gradient(circle at 50% 46%, #203650 0, #14253c 53%, #0c1727 100%); }
      .mus-canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
      .mus-canvas:active { cursor: grabbing; }
      .mus-plot-note { position: absolute; top: .8rem; left: 1rem; right: 1rem; margin: 0; color: #d7e0e2; font: .75rem/1.4 system-ui, sans-serif; pointer-events: none; text-shadow: 0 1px 6px #0c1727; }
      .mus-plot-state { position: absolute; inset: 2.5rem 1rem 1rem; display: grid; place-items: center; text-align: center; color: #f3f5f4; pointer-events: none; }
      .mus-controls { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; padding: .55rem .8rem; border-top: 1px solid #3c5065; font: .76rem/1.3 system-ui, sans-serif; }
      .mus-controls button { border: 1px solid #82909e; border-radius: 3px; background: #1b304a; color: #f3f5f4; padding: .28rem .55rem; }
      .mus-controls span { margin-left: auto; color: #c1ced4; }
      .mus-side { display: grid; grid-template-rows: minmax(0, 1fr) minmax(0, 1fr); min-height: 0; border-left: 1px solid #cbd3d4; }
      .mus-detail, .mus-list-wrap { min-height: 0; overflow: auto; padding: 1rem 1.15rem; }
      .mus-detail { border-bottom: 1px solid #cbd3d4; }
      .mus-side h3 { margin: 0 0 .5rem; font: 400 1.25rem/1.2 "GFS Didot", Georgia, serif; }
      .mus-detail-title { color: #14223a; }
      .mus-meta { margin: .1rem 0 .7rem; color: #4e5963; font-size: .87rem; }
      .mus-reason { margin: .15rem 0 .7rem; padding-left: .55rem; border-left: 2px solid #d39a2c; color: #3f4e5a; font-size: .85rem; }
      .mus-text { margin: .7rem 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 1.08rem; line-height: 1.5; }
      .mus-links { display: flex; flex-wrap: wrap; gap: .4rem 1rem; align-items: center; }
      .mus-source, .mus-source:visited { display: inline-block; color: #14223a; text-underline-offset: 2px; }
      .mus-near { margin-top: 1rem; padding-top: .7rem; border-top: 1px solid #ccd4d5; }
      .mus-near h4 { margin: 0 0 .3rem; color: #4e5963; font: 600 .7rem/1.2 system-ui, sans-serif; text-transform: uppercase; letter-spacing: .08em; }
      .mus-near button { display: block; width: 100%; border: 0; background: transparent; padding: .25rem 0; color: #225581; text-align: left; text-decoration: underline; text-underline-offset: 2px; }
      .mus-list-head { display: flex; justify-content: space-between; align-items: baseline; gap: .5rem; }
      .mus-list-head small { color: #59646c; }
      .mus-list { list-style: none; margin: 0; padding: 0; }
      .mus-list li { border-top: 1px solid #d6dcdd; }
      .mus-list button { display: block; width: 100%; padding: .5rem .3rem; border: 0; border-left: 3px solid transparent; background: transparent; text-align: left; }
      .mus-list button:hover, .mus-list button[aria-current="true"] { background: #dfe6e5; border-left-color: #d39a2c; }
      .mus-item-head { display: flex; align-items: baseline; gap: .4rem; font-size: .94rem; }
      .mus-swatch { flex: none; width: .64rem; height: .64rem; display: inline-block; border-radius: 50%; }
      .mus-item-cite { display: block; margin-left: 1.04rem; color: #58646e; font-size: .81rem; }
      .mus-item-excerpt { display: block; margin-left: 1.04rem; overflow: hidden; color: #354555; font-size: .91rem; white-space: nowrap; text-overflow: ellipsis; }
      .mus-foot { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .65rem 1.5rem; align-items: start; max-height: 9rem; overflow: auto; padding: .65rem 1.25rem .8rem; border-top: 1px solid #cbd3d4; color: #3f4e5a; font-size: .82rem; line-height: 1.35; }
      .mus-foot p { margin: 0; }
      .mus-warnings { grid-column: 1 / -1; color: #715121; }
      .mus-legend { display: flex; gap: .35rem .7rem; flex-wrap: wrap; max-width: 25rem; justify-content: end; }
      .mus-legend span { white-space: nowrap; }
      .mus-legend i { display: inline-block; width: .55rem; height: .55rem; margin-right: .25rem; border-radius: 50%; }
      @media (max-width: 760px) {
        .mus-overlay { padding: 0; }
        .mus-dialog { width: 100%; height: 100%; border: 0; border-radius: 0; }
        .mus-head { padding: .7rem .8rem; }
        .mus-main { grid-template-columns: 1fr; grid-template-rows: minmax(280px, 44%) minmax(260px, 1fr); }
        .mus-side { grid-template-rows: minmax(0, 1fr) minmax(0, 1fr); border-left: 0; }
        .mus-detail, .mus-list-wrap { padding: .65rem .85rem; }
        .mus-foot { padding: .45rem .8rem; grid-template-columns: 1fr; }
        .mus-legend { max-width: none; justify-content: start; }
        .mus-controls span { display: none; }
      }
    `;
    document.head.append(style);
  }

  function colorFor(index) {
    // Golden-angle spacing gives each author a stable, distinct hue in a result set.
    return `hsl(${Math.round((index * 137.508 + 32) % 360)} 72% 68%)`;
  }

  function colorAuthor(point) {
    // The API owns alias identity. Original author labels remain untouched in
    // passage details; no client heuristics merge scholia or joint authors.
    const canonical = typeof point.author_canonical === 'string' ? point.author_canonical.trim() : '';
    const original = typeof point.author === 'string' ? point.author.trim() : '';
    return canonical || original || 'Unknown author';
  }

  function recordLabels(point) {
    const language = { grc: 'Ancient Greek', ell: 'Modern Greek', eng: 'English', lat: 'Latin' }[point.language] || point.language;
    const quality = { source_text: 'Source text', machine_corrected_ocr: 'Machine-corrected OCR',
      machine_ocr: 'Raw machine OCR', mixed_content: 'Mixed content', needs_review: 'Needs review' }[point.quality] || point.quality;
    return [language, point.kind, quality].filter(Boolean).join(' · ');
  }

  async function usageResponse(response) {
    if (!response.ok) {
      let detail = '';
      try { const body = await response.json(); if (typeof body?.detail === 'string') detail = body.detail; } catch { /* Keep the status fallback. */ }
      throw new Error(detail || `The server returned ${response.status}.`);
    }
    return response.json();
  }

  function usageRequest(query, author, scope = {}) {
    return new URLSearchParams({ q: String(query), author: String(author || ''), limit: '80',
      mode: scope.mode || 'forms', match: scope.match || 'fuzzy', language: scope.language || '',
      edition: scope.edition || '', include_reference: String(scope.include_reference === true),
      order: scope.order || 'relevance', commentary_assisted: String(scope.commentary_assisted !== false),
      ...(!scope.mode || scope.mode === 'forms' ? { forms_relation: scope.forms_relation || 'ordered', slop: String(scope.slop ?? 0) } : {}) });
  }

  function scopeLabel(scope) {
    const mode = { forms: 'Forms', themes: 'Themes', hybrid: 'All evidence', words: scope.match === 'exact' ? 'Exact words' : 'Fuzzy words' }[scope.mode] || scope.mode || 'Forms';
    const language = { grc: 'Ancient Greek', ell: 'Modern Greek', eng: 'English', lat: 'Latin' }[scope.language] || scope.language || 'Any language';
    const relation = !scope.mode || scope.mode === 'forms'
      ? scope.forms_relation === 'all_terms' ? 'All words in passage; not a phrase match'
        : `${scope.forms_relation === 'proximity' ? 'Nearby, any order' : 'In this order'} (multiple words) · ${scope.slop ?? 0} extra words allowed` : '';
    return [scope.scope_origin || 'Requested search', mode, relation, scope.author || 'All authors', language,
      scope.edition || 'All editions', scope.include_reference ? 'Reference/uncertain records included' : 'Default quality/reference filter',
      scope.order === 'chronological' ? 'Chronological order' : 'Relevance order'].filter(Boolean).join(' · ');
  }

  function preparePoints(raw) {
    if (!Array.isArray(raw)) return { points: [], rejected: 0 };
    const usableCoordinate = value =>
      (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) &&
      Number.isFinite(Number(value));
    const points = raw.filter(point => point && point.id != null &&
      [point.x, point.y, point.z].every(usableCoordinate));
    return { points: points.map(point => ({ ...point, x: Number(point.x), y: Number(point.y), z: Number(point.z) })), rejected: raw.length - points.length };
  }

  function setupGeometry(state) {
    const axes = ['x', 'y', 'z'];
    const minimum = axes.map(axis => Math.min(...state.points.map(point => point[axis])));
    const maximum = axes.map(axis => Math.max(...state.points.map(point => point[axis])));
    const center = axes.map((_, i) => (minimum[i] + maximum[i]) / 2);
    const span = Math.max(1e-12, ...axes.map((_, i) => maximum[i] - minimum[i]));
    state.points.forEach(point => { point.position = axes.map((axis, i) => (point[axis] - center[i]) * 2 / span); });
  }

  function project(state, width, height) {
    const yaw = state.yaw, pitch = state.pitch;
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const radius = Math.min(width, height) * .35 * state.zoom;
    return state.points.map(point => {
      const [x, y, z] = point.position;
      const rx = x * cy + z * sy;
      const rz0 = -x * sy + z * cy;
      const ry = y * cp - rz0 * sp;
      const rz = y * sp + rz0 * cp;
      const perspective = 3.2 / (3.2 - rz * .55);
      return { point, x: width / 2 + rx * radius * perspective, y: height / 2 - ry * radius * perspective, depth: rz, radius: clamp(4.3 * perspective, 3, 8) };
    });
  }

  function draw(state) {
    if (!state.points.length || !state.root.isConnected) return;
    const rect = state.canvas.getBoundingClientRect();
    const width = rect.width, height = rect.height;
    if (width < 1 || height < 1) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const pixelWidth = Math.max(1, Math.round(width * ratio));
    const pixelHeight = Math.max(1, Math.round(height * ratio));
    if (state.canvas.width !== pixelWidth || state.canvas.height !== pixelHeight) {
      state.canvas.width = pixelWidth; state.canvas.height = pixelHeight;
    }
    const ctx = state.canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    state.projected = project(state, width, height).sort((a, b) => a.depth - b.depth);
    for (const item of state.projected) {
      const picked = item.point === (state.hover || state.selected);
      ctx.beginPath();
      ctx.arc(item.x, item.y, picked ? item.radius + 5 : item.radius + 2, 0, Math.PI * 2);
      ctx.fillStyle = picked ? 'rgba(243,245,244,.34)' : 'rgba(243,245,244,.09)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(item.x, item.y, picked ? item.radius + 1 : item.radius, 0, Math.PI * 2);
      ctx.fillStyle = state.colors.get(colorAuthor(item.point));
      ctx.globalAlpha = picked ? 1 : clamp(.58 + item.depth * .14, .35, .85);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (picked) { ctx.strokeStyle = '#f3f5f4'; ctx.lineWidth = 1.5; ctx.stroke(); }
    }
  }

  function pick(state, x, y) {
    for (let i = state.projected.length - 1; i >= 0; i--) {
      const item = state.projected[i];
      if (Math.hypot(x - item.x, y - item.y) <= Math.max(10, item.radius + 5)) return item.point;
    }
    return null;
  }

  function select(state, point, scrollList = false) {
    state.selected = point;
    state.hover = null;
    state.list.querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-current', button.dataset.id === String(point.id));
      if (scrollList && button.dataset.id === String(point.id)) button.scrollIntoView({ block: 'nearest' });
    });
    showDetail(state, point, false);
    draw(state);
  }

  function showDetail(state, point, preview) {
    const detail = state.detail;
    detail.replaceChildren();
    if (!point) {
      detail.append(element('h3', '', 'Passage detail'), element('p', 'mus-meta', 'Select a plotted point or a passage from the list.'));
      return;
    }
    detail.append(element('h3', 'mus-detail-title', preview ? 'Passage preview' : 'Selected passage'));
    detail.append(element('p', 'mus-meta', [point.author, point.work, point.citation].filter(Boolean).join(' · ') || 'Citation unavailable'));
    if (recordLabels(point)) detail.append(element('p', 'mus-meta', recordLabels(point)));
    if (typeof point.match_reason === 'string' && point.match_reason.trim()) {
      detail.append(element('p', 'mus-reason', `Retrieved because: ${point.match_reason.trim()}`));
    }
    const text = element('p', 'mus-text', point.text || 'Passage text unavailable.');
    if (point.language) text.lang = String(point.language);
    detail.append(text);
    const date = dateLabel(point);
    if (date) detail.append(element('p', 'mus-meta', `Sourced date interval: ${date} (${point.date_source})`));
    const links = element('div', 'mus-links');
    if (!preview) {
      const readLink = element('a', 'mus-source', 'Read in Melos →');
      readLink.href = `/?${new URLSearchParams({ id: String(point.id) })}`;
      links.append(readLink);
    }
    const url = safeUrl(point.source_url);
    if (url) {
      const link = element('a', 'mus-source', 'Open source ↗');
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      links.append(link);
    }
    if (links.childElementCount) detail.append(links);
    if (state.points.length > 1) {
      const nearby = element('div', 'mus-near');
      nearby.append(element('h4', '', 'Nearest in supplied coordinates'));
      const peers = state.points.filter(other => other !== point).map(other => ({
        point: other,
        distance: Math.hypot(point.x - other.x, point.y - other.y, point.z - other.z)
      })).sort((a, b) => a.distance - b.distance).slice(0, 3);
      peers.forEach(({ point: peer }) => {
        const button = element('button', '', [peer.author, peer.citation || peer.work].filter(Boolean).join(' · ') || 'Passage');
        button.type = 'button';
        button.addEventListener('click', () => select(state, peer, true));
        nearby.append(button);
      });
      detail.append(nearby);
    }
  }

  function populate(state, payload) {
    const { points, rejected } = preparePoints(payload.points);
    state.points = points;
    if (points.length) setupGeometry(state);
    const authors = [...new Set(points.map(colorAuthor))].sort((a, b) => a.localeCompare(b));
    state.colors = new Map(authors.map((author, i) => [author, colorFor(i)]));
    state.status.textContent = points.length ? '' : payload.retrieved_count === 0
      ? 'No passages matched these search filters.'
      : 'No passages with usable coordinates were returned for this query.';
    const retrieved = Number.isInteger(payload.retrieved_count) ? payload.retrieved_count : points.length;
    const omitted = Number.isInteger(payload.omitted_count) ? payload.omitted_count : 0;
    state.count.textContent = `${points.length} plotted · ${retrieved} retrieved${omitted || rejected ? ` · ${omitted + rejected} omitted` : ''}`;
    if (state.scope) state.scope.textContent = scopeLabel({ ...state.requestScope, ...(payload.scope || {}) });
    state.method.textContent = typeof payload.method === 'string' && payload.method.trim()
      ? `Retrieval and projection method: ${payload.method}`
      : 'Retrieval and projection method was not supplied by the server.';
    const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean).map(String) : payload.warnings ? [String(payload.warnings)] : [];
    if (state.requestScope?.scope_notice) warnings.unshift(state.requestScope.scope_notice);
    if (rejected) warnings.push(`${rejected} passage${rejected === 1 ? ' was' : 's were'} omitted because its coordinates or ID were invalid.`);
    state.warnings.textContent = warnings.join(' ');
    state.warnings.hidden = warnings.length === 0;
    state.list.replaceChildren();
    state.legend.replaceChildren();
    authors.forEach(author => {
      const label = element('span', '', author);
      const swatch = element('i');
      swatch.style.background = state.colors.get(author);
      swatch.setAttribute('aria-hidden', 'true');
      label.prepend(swatch);
      state.legend.append(label);
    });
    points.forEach(point => {
      const li = element('li');
      const button = element('button');
      button.type = 'button'; button.dataset.id = String(point.id);
      const head = element('span', 'mus-item-head');
      const swatch = element('span', 'mus-swatch');
      swatch.style.background = state.colors.get(colorAuthor(point));
      swatch.setAttribute('aria-hidden', 'true');
      head.append(swatch, element('span', '', point.author || 'Unknown author'));
      button.append(head, element('span', 'mus-item-cite', [point.work, point.citation].filter(Boolean).join(' · ') || 'Citation unavailable'));
      if (recordLabels(point)) button.append(element('span', 'mus-item-cite', recordLabels(point)));
      button.append(element('span', 'mus-item-excerpt', point.text || 'Passage text unavailable.'));
      button.addEventListener('click', () => select(state, point));
      li.append(button); state.list.append(li);
    });
    showDetail(state, null, false);
    draw(state);
  }

  function open(query = '', author = '', scope = {}) {
    close();
    injectStyle();
    const priorFocus = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    const root = element('div', 'mus-overlay');
    const dialog = element('section', 'mus-dialog');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); dialog.setAttribute('aria-labelledby', 'mus-title');
    const head = element('header', 'mus-head');
    const heading = element('div');
    heading.append(element('p', 'mus-eyebrow', 'Passage usage'), element('h2', 'mus-title', 'Usage in space'));
    heading.querySelector('h2').id = 'mus-title';
    heading.append(element('p', 'mus-subtitle', String(query).trim() ? `“${String(query).trim()}”${author ? ` · ${author}` : ''}` : author ? String(author) : 'Corpus passages'));
    const scopeDescription = element('p', 'mus-subtitle', scopeLabel({ ...scope, author }));
    heading.append(scopeDescription);
    const closeButton = element('button', 'mus-close', 'Close ×'); closeButton.type = 'button';
    head.append(heading, closeButton);
    const main = element('div', 'mus-main');
    const visual = element('div', 'mus-visual');
    const plot = element('div', 'mus-plot');
    const canvas = element('canvas', 'mus-canvas');
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Interactive three dimensional projection of passages. Drag or use arrow keys to rotate; use scroll or plus and minus keys to zoom. All passages are available in the adjacent list.');
    const plotNote = element('p', 'mus-plot-note', 'Feature / embedding projection · position is similarity, not geography or chronology');
    const status = element('p', 'mus-plot-state', 'Loading passages…'); status.setAttribute('role', 'status');
    plot.append(canvas, plotNote, status);
    const controls = element('div', 'mus-controls');
    const reset = element('button', '', 'Reset view'); reset.type = 'button';
    const zoomIn = element('button', '', 'Zoom +'); zoomIn.type = 'button';
    const zoomOut = element('button', '', 'Zoom −'); zoomOut.type = 'button';
    controls.append(reset, zoomIn, zoomOut, element('span', '', 'Drag to rotate · scroll to zoom · select a point'));
    visual.append(plot, controls);
    const side = element('div', 'mus-side');
    const detail = element('section', 'mus-detail');
    detail.setAttribute('aria-label', 'Selected passage');
    const listWrap = element('section', 'mus-list-wrap');
    listWrap.setAttribute('aria-label', 'Passages in the projection');
    const listHead = element('div', 'mus-list-head');
    const count = element('small', '', 'Loading…');
    listHead.append(element('h3', '', 'Passages'), count);
    const list = element('ol', 'mus-list');
    listWrap.append(listHead, list);
    side.append(detail, listWrap);
    main.append(visual, side);
    const foot = element('footer', 'mus-foot');
    const method = element('p', '', 'Loading projection method…');
    const legend = element('div', 'mus-legend'); legend.setAttribute('aria-label', 'Author colors');
    const warnings = element('p', 'mus-warnings'); warnings.hidden = true;
    foot.append(method, legend, warnings);
    dialog.append(head, main, foot); root.append(dialog); document.body.append(root);
    document.body.style.overflow = 'hidden';

    const state = { root, canvas, status, count, method, warnings, legend, list, detail, scope: scopeDescription,
      requestScope: { ...scope, author }, points: [], projected: [], colors: new Map(), selected: null, hover: null, yaw: -.55, pitch: .28, zoom: 1, controller: new AbortController(), priorFocus, priorOverflow };
    active = state;
    showDetail(state, null, false);
    closeButton.focus();
    closeButton.addEventListener('click', close);
    root.addEventListener('click', event => { if (event.target === root) close(); });
    reset.addEventListener('click', () => { state.yaw = -.55; state.pitch = .28; state.zoom = 1; draw(state); });
    zoomIn.addEventListener('click', () => { state.zoom = clamp(state.zoom * 1.2, .55, 3); draw(state); });
    zoomOut.addEventListener('click', () => { state.zoom = clamp(state.zoom / 1.2, .55, 3); draw(state); });
    let drag = null;
    canvas.addEventListener('pointerdown', event => {
      canvas.setPointerCapture(event.pointerId);
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    });
    canvas.addEventListener('pointermove', event => {
      if (drag && drag.id === event.pointerId) {
        const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        if (drag.moved) {
          state.yaw += dx * .008;
          state.pitch = clamp(state.pitch + dy * .008, -1.48, 1.48);
          drag.x = event.clientX; drag.y = event.clientY;
          state.hover = null;
          draw(state);
        }
      } else {
        const rect = canvas.getBoundingClientRect();
        const point = pick(state, event.clientX - rect.left, event.clientY - rect.top);
        canvas.style.cursor = point ? 'pointer' : 'grab';
        if (point !== state.hover) { state.hover = point; showDetail(state, point || state.selected, !!point); draw(state); }
      }
    });
    canvas.addEventListener('pointerup', event => {
      if (!drag || drag.id !== event.pointerId) return;
      if (!drag.moved) {
        const rect = canvas.getBoundingClientRect();
        const point = pick(state, event.clientX - rect.left, event.clientY - rect.top);
        if (point) select(state, point, true);
      }
      drag = null;
    });
    canvas.addEventListener('pointercancel', () => { drag = null; });
    canvas.addEventListener('pointerleave', () => { if (!drag) { state.hover = null; showDetail(state, state.selected, false); draw(state); } });
    canvas.addEventListener('wheel', event => { event.preventDefault(); state.zoom = clamp(state.zoom * Math.exp(-event.deltaY * .001), .55, 3); draw(state); }, { passive: false });
    canvas.addEventListener('keydown', event => {
      const rotate = { ArrowLeft: [-.12, 0], ArrowRight: [.12, 0], ArrowUp: [0, -.12], ArrowDown: [0, .12] }[event.key];
      if (rotate) { event.preventDefault(); state.yaw += rotate[0]; state.pitch = clamp(state.pitch + rotate[1], -1.48, 1.48); draw(state); }
      if (event.key === '+' || event.key === '=') { event.preventDefault(); state.zoom = clamp(state.zoom * 1.2, .55, 3); draw(state); }
      if (event.key === '-') { event.preventDefault(); state.zoom = clamp(state.zoom / 1.2, .55, 3); draw(state); }
    });
    state.onKeyDown = event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      const focusable = [...dialog.querySelectorAll('button, a[href], [tabindex="0"]')].filter(node => !node.hidden);
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', state.onKeyDown, true);
    if (window.ResizeObserver) {
      state.resizeObserver = new ResizeObserver(() => draw(state));
      state.resizeObserver.observe(canvas);
    } else { state.onResize = () => draw(state); window.addEventListener('resize', state.onResize); }

    const params = usageRequest(query, author, scope);
    fetch(window.melosApiUrl(`/api/usage-space?${params}`), { signal: state.controller.signal, headers: { Accept: 'application/json' } })
      .then(usageResponse)
      .then(payload => { if (active === state) populate(state, payload && typeof payload === 'object' ? payload : {}); })
      .catch(error => {
        if (active !== state || error.name === 'AbortError') return;
        state.status.textContent = 'The usage projection could not be loaded.';
        state.count.textContent = 'Unavailable';
        state.method.textContent = error.message || 'Request failed.';
      });
  }

  function close() {
    if (!active) return;
    const state = active;
    active = null;
    state.controller.abort();
    document.removeEventListener('keydown', state.onKeyDown, true);
    state.resizeObserver?.disconnect();
    if (state.onResize) window.removeEventListener('resize', state.onResize);
    state.root.remove();
    document.body.style.overflow = state.priorOverflow;
    if (state.priorFocus?.isConnected) state.priorFocus.focus();
  }

  window.MelosUsageSpace = { open, close };
})();
