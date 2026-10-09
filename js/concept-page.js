// Concepts page (concept.html?q=moon): the headwords that express a concept,
// their rate per 10,000 words by period (undated authors shown apart), typical
// collocates per period and example passages per period.
(() => {
  'use strict';
  const L = window.MelosLemma || {};
  const { node, greek, clear, link, api, number, rate, plural } = L;
  const SMALL_PERIOD = 50000;

  function readState(href) {
    const params = new URL(href).searchParams;
    return { q: String(params.get('q') || '').trim().slice(0, 100), lemma: String(params.get('lemma') || '').trim().slice(0, 100) };
  }
  // Where a headword comes from, in words.
  function sourceText(item, concept) {
    // Matched terms arrive stemmed ("lov"); show the word the reader typed when it is that stem.
    const word = term => String(concept || '').toLowerCase().startsWith(String(term).toLowerCase()) ? concept : term;
    const terms = (list => list.length ? [...new Set(list.map(word))].map(term => `“${term}”`).join(', ') : `“${concept}”`)(Array.isArray(item.matched_terms) ? item.matched_terms : Array.isArray(item.shared_gloss_terms) ? item.shared_gloss_terms : []);
    if (item.via === 'english_dictionary_gloss') return `Dictionary meaning: its definition${item.gloss_source ? ` in ${item.gloss_source}` : ''} uses ${terms}.`;
    if (item.via === 'semantic_neighbourhood_and_shared_gloss_word') {
      return `Meaning index: unusually common in the passages closest in meaning to “${concept}”${item.in_nearest_passages ? ` (${plural(item.in_nearest_passages, 'time')})` : ''}, and its definition shares ${terms}.`;
    }
    if (item.via === 'headword' || item.via === 'headword_without_accents') return 'The headword you asked for.';
    if (item.via === 'printed_form_reading') return 'Read from the form you typed.';
    return 'Related headword.';
  }
  // Chart series for one headword: rate by period, undated apart.
  function seriesFor(item, periods, undatedTokens) {
    const points = periods.map((period, x) => {
      const row = (item.by_period || []).find(p => p.period === period.label) || {};
      const total = Number(row.tokens_in_period ?? period.tokens) || 0;
      return { x, value: total > 0 && Number.isFinite(Number(row.per_10k)) ? Number(row.per_10k) : NaN, count: Number(row.count) || 0, total };
    });
    const count = Number(item.undated_count) || 0;
    const undated = undatedTokens > 0 ? { value: count / undatedTokens * 10000, count, total: undatedTokens } : null;
    return { points, undated };
  }

  if (typeof document === 'undefined' || !document.getElementById?.('concept')) {
    window.MelosConceptPage = Object.freeze({ readState, sourceText, seriesFor });
    return;
  }

  const ui = { form: document.getElementById('lookup'), input: document.getElementById('lookup-input'), host: document.getElementById('concept') };
  let state = readState(location.href), controller = null, data = null, visible = new Set(), picked = '';
  const narrow = () => (ui.host.clientWidth || 760) < 600;
  const chartable = () => (data?.lemmas || []).slice(0, L.SERIES.length);
  const color = item => L.SERIES[(data.lemmas || []).indexOf(item)] || '#999';

  function section(id, title, lead) {
    const box = node('section', 'block'); box.id = id;
    box.append(node('h2', '', title));
    if (lead) box.append(node('p', 'lead', lead));
    const body = node('div', 'block-body'); box.append(body);
    return { box, body };
  }

  async function start() {
    controller?.abort(); controller = new AbortController();
    const signal = controller.signal;
    ui.input.value = state.q;
    if (!state.q) return;
    document.title = `${state.q} · Concepts · Melos`;
    L.loading(ui.host, `Gathering the words for “${state.q}” across the corpus… (this takes a second)`);
    try {
      data = await api('/api/concept/diachrony', { q: state.q }, signal);
      const lemmas = Array.isArray(data.lemmas) ? data.lemmas : [];
      if (!lemmas.length) {
        clear(ui.host);
        ui.host.append(node('h1', '', state.q), node('p', 'notice', `No Greek headwords were found for “${state.q}”. Try a simpler English word (moon rather than moonlight) or a Greek headword.`));
        return;
      }
      data.lemmas = lemmas;
      const common = chartable().filter(item => Number(item.tokens) >= 10);
      visible = new Set((common.length ? common : chartable()).slice(0, 6).map(item => item.lemma));
      picked = lemmas.some(item => item.lemma === state.lemma) ? state.lemma : lemmas[0].lemma;
      render(signal);
    } catch (error) { if (!signal.aborted) L.failure(ui.host, error, start); }
  }

  function periodsOf() {
    const first = data.lemmas.find(item => Array.isArray(item.by_period) && item.by_period.length);
    return (first?.by_period || []).map(row => ({ label: row.period, tokens: Number(row.tokens_in_period) || 0, small: (Number(row.tokens_in_period) || 0) < SMALL_PERIOD }));
  }

  function render(signal) {
    clear(ui.host);
    const head = node('header', 'entry-head');
    head.append(node('h1', 'headword', `“${data.concept || state.q}”`));
    const share = data.scope_tokens ? Math.round(Number(data.undated_tokens) / Number(data.scope_tokens) * 100) : 0;
    head.append(node('p', 'lead', `${plural(data.lemmas.length, 'Greek headword')} express this meaning in ${number(data.scope_tokens)} words of edited Greek. ${L.DATE_NOTE} ${share ? `${share}% of the words are by authors with no recorded date; they are shown apart and never placed in a period.` : ''}`));
    const jump = node('nav', 'jump'); jump.setAttribute('aria-label', 'Sections');
    for (const [id, label] of [['words', 'The words'], ['timeline', 'Over time'], ['companions', 'Companions by period'], ['examples', 'Examples by period']]) jump.append(link(`#${id}`, label));
    const words = section('words', 'The words', 'Each headword is listed with where it comes from. Tick a word to draw it on the chart; choose its name to open its lexicon page.');
    const timeline = section('timeline', 'Over time', 'How often poets of each period use each word, per 10,000 of their words. Hover over a point for the counts.');
    const companions = section('companions', 'Companions by period', 'The words most often found within five words of the chosen headword, period by period.');
    const examples = section('examples', 'Examples by period', 'A passage from the author who uses the chosen headword most in each period. Choose a line to read the whole passage.');
    ui.host.append(head, jump, words.box, timeline.box, companions.box, examples.box);
    const drawChart = () => renderTimeline(timeline.body);
    let drawnNarrow = narrow();
    window.onresize = () => { if (narrow() !== drawnNarrow) { drawnNarrow = narrow(); drawChart(); } };
    renderWords(words.body, drawChart);
    drawChart();
    const drawPicked = () => { renderCompanions(companions.body, drawPicked); renderExamples(examples.body, signal); };
    drawPicked();
    if (Array.isArray(data.warnings) && data.warnings.length) ui.host.append(node('p', 'fine', data.warnings.join(' ')));
    if (data.headwords_without_occurrences?.length) {
      ui.host.append(node('p', 'fine', `Also in the dictionaries but not found in the texts: ${data.headwords_without_occurrences.map(item => item.lemma || item).join(', ')}.`));
    }
  }

  function renderWords(host, redraw) {
    clear(host);
    const list = node('ul', 'concept-lemmas');
    data.lemmas.forEach((item, index) => {
      const li = node('li', `concept-lemma${visible.has(item.lemma) ? '' : ' off'}`);
      const box = node('input'); box.type = 'checkbox'; box.id = `lemma-${index}`;
      const canChart = index < L.SERIES.length;
      box.checked = visible.has(item.lemma); box.disabled = !canChart;
      box.title = canChart ? 'Show on the chart' : 'Only the first eight words can be charted';
      box.setAttribute('aria-label', `Show ${item.lemma} on the chart`);
      box.addEventListener('change', () => {
        if (box.checked) visible.add(item.lemma); else visible.delete(item.lemma);
        li.classList.toggle('off', !box.checked); redraw();
      });
      const name = node('div');
      if (canChart) { const swatch = node('span', 'swatch'); swatch.style.background = color(item); name.append(swatch); }
      const a = link(L.lemmaHref(item.lemma), '', 'name'); a.append(greek('span', '', item.lemma)); name.append(a);
      if (item.gloss) name.append(node('span', 'gloss-meta', ` ${item.gloss}`));
      li.append(box, name, node('span', 'meta', `${plural(item.tokens, 'occurrence')}${item.undated_count ? `, ${number(item.undated_count)} by undated authors` : ''}`),
        node('span', 'from', sourceText(item, data.concept || state.q)));
      list.append(li);
    });
    host.append(list);
  }

  function renderTimeline(host) {
    clear(host);
    const periods = periodsOf();
    const shown = chartable().filter(item => visible.has(item.lemma));
    if (!periods.length) { host.append(node('p', 'notice', 'No dated occurrences to draw.')); return; }
    const undatedTokens = Number(data.undated_tokens) || 0;
    const series = shown.map(item => ({ key: item.lemma, label: item.lemma, color: color(item), ...seriesFor(item, periods, undatedTokens) }));
    const legend = node('ul', 'legend');
    for (const s of series) { const li = node('li'); const sw = node('span', 'swatch'); sw.style.background = s.color; li.append(sw, greek('span', '', s.label)); legend.append(li); }
    const hollow = node('li'); hollow.append(node('span', 'hollow'), node('span', '', 'open circle = authors with no recorded date'));
    legend.append(hollow);
    host.append(legend);
    if (!series.length) { host.append(node('p', 'notice', 'Tick a word above to draw it.')); return; }
    if (narrow()) host.append(node('p', 'fine', 'Rate per 10,000 words. Tap a point for the counts.'));
    host.append(L.timelineChart({ periods, series, undatedLabel: 'Undated', width: host.clientWidth || 760,
      describe: `Rate per 10,000 words by period for ${series.map(s => s.label).join(', ')}; undated authors shown separately.` }));
    const small = periods.filter(p => p.small);
    const notes = [L.DATE_NOTE + ' A poet is placed in the period of their recorded birth or activity; long or uncertain lives can fall either side of a boundary.'];
    if (small.length) notes.push(`Few texts survive from ${small.map(p => L.periodParts(p.label).name).join(' and ')}, so rates there rest on very little and can swing widely.`);
    notes.push(`The undated column at the right pools ${number(undatedTokens)} words by authors with no recorded date (for example Nonnus and Quintus); it is not a period.`);
    host.append(node('p', 'fine', notes.join(' ')));
    const table = node('details', 'data-table');
    table.append(node('summary', '', 'Show the numbers as a table'));
    const t = node('table'), head = node('tr');
    head.append(node('th', '', 'Period'));
    for (const s of series) head.append(greek('th', '', s.label));
    const thead = node('thead'); thead.append(head); t.append(thead);
    const body = node('tbody');
    [...periods.map((p, i) => ({ name: L.periodParts(p.label).name, cell: s => s.points[i] })), { name: 'Undated authors', cell: s => s.undated }].forEach(row => {
      const tr = node('tr'); tr.append(node('td', '', row.name));
      for (const s of series) { const c = row.cell(s); tr.append(node('td', '', c && Number.isFinite(c.value) ? `${rate(c.value)} (${number(c.count)})` : '–')); }
      body.append(tr);
    });
    t.append(body); table.append(t, node('p', 'fine', 'Rate per 10,000 words, with the number of occurrences in brackets.'));
    host.append(table);
  }

  function picker(redraw) {
    const bar = node('div', 'lemma-picker'); bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Choose a headword');
    for (const item of data.lemmas) {
      const b = node('button', '', item.lemma); b.type = 'button'; b.lang = 'grc';
      b.setAttribute('aria-pressed', String(item.lemma === picked));
      b.addEventListener('click', () => {
        picked = item.lemma; state.lemma = picked;
        const url = new URL(location.href); url.searchParams.set('lemma', picked); history.replaceState(null, '', url);
        redraw();
      });
      bar.append(b);
    }
    return bar;
  }

  function renderCompanions(host, redraw) {
    clear(host);
    host.append(picker(redraw));
    const item = data.lemmas.find(entry => entry.lemma === picked);
    const grid = node('div', 'period-grid');
    const unused = (item.by_period || []).filter(period => !period.count).map(period => L.periodParts(period.period).name);
    for (const period of (item.by_period || []).filter(period => period.count)) {
      const part = L.periodParts(period.period);
      const card = node('article', 'period-card');
      card.append(node('h3', '', part.name), node('p', 'span', `${part.span} · ${plural(period.count, 'occurrence')}`));
      const collocates = Array.isArray(period.collocates) ? period.collocates : [];
      if (!collocates.length) card.append(node('p', 'fine', 'Too few occurrences to show companions.'));
      else {
        const list = node('ul');
        for (const c of collocates) {
          const li = node('li'); const a = link(L.lemmaHref(c.lemma), ''); a.append(greek('span', '', c.lemma)); li.append(a);
          li.append(node('span', '', ` ${c.gloss ? `${c.gloss} · ` : ''}${number(c.count)}× together`));
          list.append(li);
        }
        card.append(list);
      }
      grid.append(card);
    }
    const undated = node('article', 'period-card undated');
    undated.append(node('h3', '', 'Undated authors'), node('p', 'span', `no recorded date · ${plural(item.undated_count || 0, 'occurrence')}`),
      node('p', 'fine', 'Companions are worked out per period only; see the lexicon page for all of them.'));
    grid.append(undated);
    host.append(grid);
    if (unused.length) host.append(node('p', 'fine', `Not used by authors dated to: ${unused.join(', ')}.`));
    host.append(node('p', 'fine', 'A refrain repeated in one poem (Theocritus’ “mark, lady Moon, whence came my love”, for example) can make one pairing count many times.'));
  }

  async function renderExamples(host, signal) {
    clear(host);
    const item = data.lemmas.find(entry => entry.lemma === picked);
    const authors = Array.isArray(item.by_author) ? item.by_author : [];
    const groups = [];
    for (const period of item.by_period || []) {
      if (!period.count) continue;
      const top = authors.filter(a => a.period === period.period).sort((a, b) => b.count - a.count)[0];
      if (top) groups.push({ ...L.periodParts(period.period), author: top.author });
    }
    const undated = authors.filter(a => !a.period).sort((a, b) => b.count - a.count)[0];
    if (undated) groups.push({ name: 'Undated authors', span: 'no recorded date', author: undated.author, undated: true });
    if (!groups.length) { host.append(node('p', 'notice', 'No passages to show.')); return; }
    const blocks = groups.map(group => {
      const box = node('div', 'example-period');
      box.append(node('h3', '', `${group.name} · ${group.author}`));
      const list = node('ol', 'examples-list kwic');
      list.append(node('li', 'status-line melos-loading', 'Loading…'));
      box.append(list); host.append(box);
      return { group, list };
    });
    await Promise.all(blocks.map(async ({ group, list }) => {
      try {
        const result = await api('/api/lemma/concordance', { q: `lemma:${picked}`, author: group.author, limit: 2, order: 'chronological' }, signal);
        clear(list);
        for (const line of result.lines || []) {
          const li = node('li'); const a = link(L.readerHref(line.id), '', 'kwic-line'); a.title = 'Read the whole passage';
          const where = node('span', 'kwic-where');
          where.append(node('span', 'kwic-author', line.author || group.author), node('span', 'kwic-cite', L.citation(line)), node('span', 'kwic-date', L.authorDate(line.author_date)));
          const text = node('span', 'kwic-text'); text.lang = 'grc';
          text.append(node('span', 'kwic-left', line.left || ''), node('mark', 'kwic-key', line.keyword || ''), node('span', 'kwic-right', line.right || ''));
          a.append(where, text); li.append(a); list.append(li);
        }
        if (!list.children.length) list.append(node('li', 'fine', 'No lines returned.'));
      } catch (error) { if (!signal.aborted) { clear(list); list.append(node('li', 'fine', L.errorText(error))); } }
    }));
  }

  ui.form.addEventListener('submit', event => {
    event.preventDefault();
    const value = ui.input.value.trim();
    if (!value) { ui.input.focus(); return; }
    state = { q: value, lemma: '' };
    const url = new URL(location.href); url.searchParams.set('q', value); url.searchParams.delete('lemma');
    history.pushState(null, '', url);
    start();
  });
  window.addEventListener('popstate', () => { state = readState(location.href); start(); });
  start();
})();
