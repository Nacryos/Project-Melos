// Shared helpers for the Lexicon (lemma.html) and Concepts (concept.html) pages:
// API access, safe DOM building, plain-language number and date labels, and
// two small charts drawn without a library (HTML bars, SVG lines).
(() => {
  'use strict';

  function node(tag, className = '', text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }
  function svg(tag, attrs = {}) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  }
  function clear(element) { while (element?.firstChild) element.firstChild.remove(); }
  function link(href, text, className = '') {
    const a = node('a', className, text); a.href = href; return a;
  }
  function greek(tag, className, text) {
    const element = node(tag, className, text); element.lang = 'grc'; return element;
  }

  class ApiError extends Error {
    constructor(status, detail) { super(detail || `The corpus service answered ${status}.`); this.status = status; }
  }
  async function api(path, params = {}, signal) {
    const url = window.melosApiUrl(path);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
    const response = await fetch(url, { signal, headers: { accept: 'application/json' } });
    if (!response.ok) {
      let detail = '';
      try { const body = await response.json(); detail = typeof body?.detail === 'string' ? body.detail : ''; } catch { /* not JSON */ }
      throw new ApiError(response.status, detail);
    }
    return response.json();
  }
  function errorText(error) {
    if (error?.name === 'AbortError') return '';
    if (error?.status === 503) return 'The headword index is not available just now. Please try again in a minute.';
    if (error?.status >= 500) return 'The corpus service had a problem answering. Please try again.';
    if (error?.status === 404 || error?.status === 422) return error.message || 'Nothing was found for this.';
    return 'The corpus service could not be reached. Check the connection and try again.';
  }

  const number = value => Number(value || 0).toLocaleString('en-US');
  // Rates are per 10,000 words of the same group.
  function rate(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '–';
    const v = Number(value);
    return v === 0 ? '0' : v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2);
  }
  const plural = (count, one, many = `${one}s`) => `${number(count)} ${Number(count) === 1 ? one : many}`;
  // A 95% interval [low, high] (release P `per_10k_ci95`), or null.
  function interval(value) {
    if (!Array.isArray(value) || value.length !== 2) return null;
    const [low, high] = value.map(Number);
    return Number.isFinite(low) && Number.isFinite(high) && high >= low ? [low, high] : null;
  }
  const rangeText = ci => ci ? `${rate(ci[0])}–${rate(ci[1])}` : '';
  // Groups under 50,000 words: the API's `small_sample`, else the word count.
  const SMALL_SAMPLE = 50000;
  function smallSample(row, tokens = row?.tokens_in_group ?? row?.tokens_in_period) {
    if (typeof row?.small_sample === 'boolean') return row.small_sample;
    return Number.isFinite(Number(tokens)) && Number(tokens) > 0 && Number(tokens) < SMALL_SAMPLE;
  }

  // "Archaic (to 480 BCE)" -> { name: "Archaic", span: "to 480 BCE" }
  function periodParts(label) {
    const text = String(label || '');
    if (text === 'undated') return { name: 'Undated authors', span: 'no recorded date', undated: true };
    const match = text.match(/^(.*?)\s*\((.*)\)\s*$/);
    return match ? { name: match[1], span: match[2] } : { name: text, span: '' };
  }
  const year = value => `${Math.abs(Math.round(value))} ${value < 0 ? 'BCE' : 'CE'}`;
  // An author's date claim in words: "born c. 630–612 BCE", "fl. 300 BCE".
  function authorDate(date) {
    if (!date || !Number.isFinite(Number(date.start))) return 'undated';
    const start = Number(date.start), end = Number.isFinite(Number(date.end)) ? Number(date.end) : start;
    const span = start === end ? year(start) : (start < 0) === (end < 0)
      ? `${Math.abs(start)}–${Math.abs(end)} ${start < 0 ? 'BCE' : 'CE'}` : `${year(start)}–${year(end)}`;
    const kind = date.kind === 'birth' ? 'born ' : date.kind === 'floruit' ? 'active ' : '';
    return `${kind}${date.approximate ? 'c. ' : ''}${span}`;
  }
  const DATE_NOTE = 'Dates are author lifetimes, not composition dates.';

  const readerHref = id => `/?id=${encodeURIComponent(id)}`;
  const lemmaHref = lemma => `/lemma.html?lemma=${encodeURIComponent(lemma)}`;
  const conceptHref = query => `/concept.html?q=${encodeURIComponent(query)}`;
  const searchHref = (query, mode = 'lemma') => `/?q=${encodeURIComponent(query)}&mode=${encodeURIComponent(mode)}`;
  function citation(line) {
    const work = line.display_work || line.work || '';
    const cite = line.citation && line.citation !== work ? line.citation : '';
    return [work, cite].filter(Boolean).join(' ');
  }

  // Horizontal bars, one series: the label, a bar for the count, and the
  // count with its rate in words. Rows may carry a click handler, a note
  // (author date) and `separate` (drawn after a rule, e.g. undated authors).
  function barChart(rows, { caption = '', valueLabel = row => row.value, onSelect = null, selectLabel = '' } = {}) {
    const figure = node('figure', 'bar-chart');
    if (caption) figure.append(node('figcaption', 'chart-caption', caption));
    // Bars may carry a 95% interval (same units as the bar): a thin whisker.
    const max = Math.max(rows.some(row => row.interval) ? 0.01 : 1, ...rows.map(row => Math.max(Number(row.value) || 0, row.interval ? row.interval[1] : 0)));
    const list = node('ol', 'bar-list');
    for (const row of rows) {
      const item = node('li', `bar-row${row.separate ? ' bar-separate' : ''}${row.muted ? ' bar-muted' : ''}`);
      const label = node('span', 'bar-label');
      label.append(node('span', 'bar-name', row.label));
      if (row.note) label.append(node('span', 'bar-note', row.note));
      const track = node('span', 'bar-track');
      const fill = node('span', 'bar-fill');
      fill.style.width = `${Math.max(row.value > 0 ? 1.5 : 0, (Number(row.value) || 0) / max * 100)}%`;
      track.append(fill);
      if (row.interval) {
        const whisker = node('span', 'bar-ci');
        whisker.style.left = `${row.interval[0] / max * 100}%`;
        whisker.style.width = `${Math.max(0.5, (row.interval[1] - row.interval[0]) / max * 100)}%`;
        whisker.title = `95% interval ${rangeText(row.interval)} per 10,000 words`;
        track.append(whisker);
      }
      const value = node('span', 'bar-value', valueLabel(row));
      if (onSelect && row.selectable !== false) {
        const button = node('button', 'bar-button');
        button.type = 'button';
        button.title = row.title || selectLabel;
        button.setAttribute('aria-label', `${row.label}: ${valueLabel(row)}. ${selectLabel}`);
        button.append(label, track, value);
        button.addEventListener('click', () => onSelect(row));
        item.append(button);
      } else {
        item.classList.add('bar-plain');
        item.title = row.title || '';
        item.append(label, track, value);
      }
      list.append(item);
    }
    figure.append(list);
    return figure;
  }

  // Categorical hues in fixed order (light / dark steps of the same hue);
  // a series keeps its colour when others are hidden.
  const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#c98500', '#d55181', '#008300', '#4a3aa7', '#e34948'];

  // Rate per 10,000 words by period, one line per series, with the undated
  // authors drawn apart (after a gap and a dashed rule) and labelled.
  // series: [{ key, label, color, points: [{x: periodIndex, value, count, total}], undated: {value, count, total} }]
  const SHORT_PERIOD = { Archaic: 'Arch.', Classical: 'Class.', Hellenistic: 'Hell.', 'Roman imperial': 'Rom.', 'Late antique': 'Late', Byzantine: 'Byz.' };
  function timelineChart({ periods, series, undatedLabel = 'Undated', describe, width: available = 760 }) {
    const narrow = available < 600;
    const width = narrow ? Math.max(320, Math.round(available)) : 760, height = narrow ? 260 : 300, left = narrow ? 36 : 52, right = narrow ? 22 : 44, top = 18, bottom = 62;
    const columns = periods.length + 1, gap = 0.6;
    const plotWidth = width - left - right;
    const step = plotWidth / (columns + gap - 0.5);
    const xAt = index => left + step * (index + 0.5) + (index >= periods.length ? step * gap : 0);
    const values = series.flatMap(s => [...s.points.map(p => p.value), s.undated?.value]).filter(v => Number.isFinite(v));
    // Interval tops widen the scale, but never past 1.6× the largest rate (a
    // whisker that reaches the top edge runs on beyond it).
    const tops = series.flatMap(s => [...s.points, s.undated].map(p => p?.ci?.[1])).filter(v => Number.isFinite(v));
    const rawMax = Math.max(0.1, ...values, ...tops.map(v => Math.min(v, Math.max(0.1, ...values) * 1.6)));
    const magnitude = 10 ** Math.floor(Math.log10(rawMax));
    const niceMax = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(m => m >= rawMax) || rawMax;
    const yAt = value => top + (height - top - bottom) * (1 - value / niceMax);
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, class: `timeline-chart${narrow ? ' narrow' : ''}`, role: 'img' });
    root.setAttribute('aria-label', describe || 'Rate per 10,000 words by period');
    const grid = svg('g', { class: 'chart-grid' });
    for (let i = 0; i <= 5; i++) {
      const value = niceMax * i / 5, y = yAt(value);
      grid.append(svg('line', { x1: left, x2: width - right, y1: y, y2: y }));
      const label = svg('text', { x: left - 8, y: y + 4, 'text-anchor': 'end', class: 'chart-tick' });
      label.textContent = rate(value);
      grid.append(label);
    }
    root.append(grid);
    if (!narrow) {
    const axisTitle = svg('text', { x: 12, y: top + (height - top - bottom) / 2, class: 'chart-axis-title', transform: `rotate(-90 12 ${top + (height - top - bottom) / 2})`, 'text-anchor': 'middle' });
    axisTitle.textContent = 'per 10,000 words';
    root.append(axisTitle);
    }
    const dividerX = (xAt(periods.length - 1) + xAt(periods.length)) / 2;
    root.append(svg('line', { x1: dividerX, x2: dividerX, y1: top - 6, y2: height - bottom + 44, class: 'chart-divider' }));
    [...periods.map(p => periodParts(p.label)), { name: undatedLabel, span: 'no date' }].forEach((part, index) => {
      const x = xAt(index);
      const name = svg('text', { x, y: height - bottom + 18, 'text-anchor': 'middle', class: `chart-period${index === periods.length ? ' chart-undated' : ''}` });
      name.textContent = narrow ? SHORT_PERIOD[part.name] || part.name : part.name;
      root.append(name);
      if (!narrow) {
        const span = svg('text', { x, y: height - bottom + 33, 'text-anchor': 'middle', class: 'chart-span' });
        span.textContent = part.span;
        root.append(span);
      }
      const sample = index < periods.length ? periods[index] : null;
      if (sample?.small) {
        const flag = svg('text', { x, y: height - bottom + (narrow ? 33 : 47), 'text-anchor': 'middle', class: 'chart-small' });
        flag.textContent = sample.tokens ? (narrow ? 'few texts' : `only ${number(sample.tokens)} words`) : 'no texts';
        root.append(flag);
      }
    });
    const tooltip = node('div', 'chart-tooltip'); tooltip.hidden = true; tooltip.setAttribute('role', 'status');
    const wrap = node('div', 'timeline-wrap');
    const show = (event, text) => {
      tooltip.textContent = text; tooltip.hidden = false;
      const box = wrap.getBoundingClientRect(), x = event.clientX - box.left, y = event.clientY - box.top;
      tooltip.style.left = `${Math.min(Math.max(8, x + 12), box.width - 230)}px`; tooltip.style.top = `${Math.max(4, y - 44)}px`;
    };
    for (const s of series) {
      const group = svg('g', { class: 'chart-series' });
      const runs = []; let run = [];
      for (const p of s.points) {
        if (Number.isFinite(p.value)) run.push(p); else if (run.length) { runs.push(run); run = []; }
      }
      if (run.length) runs.push(run);
      for (const r of runs.filter(r => r.length > 1)) {
        group.append(svg('polyline', { points: r.map(p => `${xAt(p.x)},${yAt(p.value)}`).join(' '), fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round' }));
      }
      const marks = [...s.points.filter(p => Number.isFinite(p.value)).map(p => ({ ...p, undated: false })),
        ...(s.undated && Number.isFinite(s.undated.value) ? [{ ...s.undated, x: periods.length, undated: true }] : [])];
      for (const p of marks) {
        const cx = xAt(p.x), cy = yAt(p.value);
        const thin = p.undated ? Boolean(p.small) : Boolean(periods[p.x]?.small);
        if (p.ci) {
          const y1 = Math.max(top, yAt(p.ci[1])), y2 = Math.min(height - bottom, yAt(p.ci[0]));
          const bar = svg('g', { class: 'chart-ci', opacity: thin ? 0.45 : 0.8 });
          bar.append(svg('line', { x1: cx, x2: cx, y1, y2, stroke: s.color, 'stroke-width': 1.5 }));
          if (y1 > top) bar.append(svg('line', { x1: cx - 4, x2: cx + 4, y1, y2: y1, stroke: s.color, 'stroke-width': 1.5 }));
          bar.append(svg('line', { x1: cx - 4, x2: cx + 4, y1: y2, y2, stroke: s.color, 'stroke-width': 1.5 }));
          group.append(bar);
        }
        const dot = svg('circle', { cx, cy, r: 5, fill: p.undated ? '#fff' : s.color, stroke: p.undated ? s.color : '#fff', 'stroke-width': 2, class: 'chart-dot', opacity: thin ? 0.45 : 1 });
        const where = p.undated ? 'authors with no recorded date' : periodParts(periods[p.x].label).name;
        const text = `${s.label} · ${where}: ${rate(p.value)} per 10,000 words${p.ci ? `, probably between ${rangeText(p.ci)}` : ''} (${plural(p.count, 'occurrence')} in ${number(p.total)} words)${thin ? '. Few texts, so this rate is unreliable.' : ''}`;
        const title = svg('title'); title.textContent = text; dot.append(title);
        const hit = svg('circle', { cx, cy, r: 13, fill: 'transparent', class: 'chart-hit' });
        hit.addEventListener('pointerenter', event => show(event, text));
        hit.addEventListener('pointermove', event => show(event, text));
        hit.addEventListener('pointerleave', event => { if (event.pointerType === 'mouse') tooltip.hidden = true; });
        hit.addEventListener('click', event => show(event, text));
        group.append(dot, hit);
      }
      root.append(group);
    }
    root.addEventListener('click', event => { if (!event.target.classList?.contains('chart-hit')) tooltip.hidden = true; });
    wrap.append(root, tooltip);
    return wrap;
  }

  // Tabs that become side-by-side panels on wide screens (CSS decides).
  function tabs(host, items, { label = 'Views', onChange = null, initial = 0 } = {}) {
    const bar = node('div', 'tab-bar'); bar.setAttribute('role', 'tablist'); bar.setAttribute('aria-label', label);
    const panels = node('div', 'tab-panels');
    const buttons = items.map((item, index) => {
      const button = node('button', 'tab', item.label);
      const id = `${host.id || 'tabs'}-${index}`;
      button.type = 'button'; button.id = `${id}-tab`; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', `${id}-panel`);
      const panel = node('div', 'tab-panel'); panel.id = `${id}-panel`; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', button.id);
      panel.append(item.content);
      panels.append(panel);
      button.addEventListener('click', () => select(index));
      button.addEventListener('keydown', event => {
        const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (move) { event.preventDefault(); const next = (index + move + items.length) % items.length; select(next); buttons[next].focus(); }
      });
      bar.append(button);
      return button;
    });
    function select(index) {
      buttons.forEach((button, i) => {
        button.setAttribute('aria-selected', String(i === index)); button.tabIndex = i === index ? 0 : -1;
        panels.children[i].classList.toggle('active', i === index);
      });
      onChange?.(index);
    }
    select(Math.min(initial, items.length - 1));
    host.append(bar, panels);
    return { select };
  }

  function loading(host, text) { clear(host); host.append(node('p', 'status-line melos-loading', text)); }
  function failure(host, error, retry) {
    const text = errorText(error);
    if (!text) return;
    clear(host);
    const box = node('div', 'notice error');
    box.append(node('p', '', text));
    if (retry) { const again = node('button', 'quiet', 'Try again'); again.type = 'button'; again.addEventListener('click', retry); box.append(again); }
    host.append(box);
  }

  window.MelosLemma = Object.freeze({ node, svg, clear, link, greek, api, ApiError, errorText, number, rate, plural, interval, rangeText, smallSample, SMALL_SAMPLE, periodParts,
    authorDate, DATE_NOTE, readerHref, lemmaHref, conceptHref, searchHref, citation, barChart, timelineChart, tabs, loading, failure, SERIES });
})();
