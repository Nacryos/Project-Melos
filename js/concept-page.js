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
    return { q: String(params.get('q') || '').trim().slice(0, 100), lemma: String(params.get('lemma') || '').trim().slice(0, 100),
      variants: params.get('variants') === '1' };
  }
  const isUndated = label => String(label || '') === 'undated';
  // With variants counted together (release P `combine_variants`) every member
  // of a group comes back with the group's counts: keep the first, and name
  // the others it now includes.
  function collapseVariants(lemmas) {
    const seen = new Set(), out = [];
    for (const item of Array.isArray(lemmas) ? lemmas : []) {
      const ids = Array.isArray(item.counted_lemma_ids) && item.counted_lemma_ids.length > 1 ? [...item.counted_lemma_ids].map(String).sort().join(',') : '';
      if (ids && seen.has(ids)) continue;
      if (ids) seen.add(ids);
      const others = ids ? (item.variant_group?.members || []).map(member => member.lemma).filter(name => name && name !== item.lemma) : [];
      out.push(others.length ? { ...item, together: others } : item);
    }
    return out;
  }
  // Where a headword comes from, in words.
  function sourceText(item, concept) {
    // Matched terms arrive stemmed ("lov"); show the word the reader typed when it is that stem.
    const word = term => String(concept || '').toLowerCase().startsWith(String(term).toLowerCase()) ? concept : term;
    const terms = (list => list.length ? [...new Set(list.map(word))].map(term => `“${term}”`).join(', ') : `“${concept}”`)(Array.isArray(item.matched_terms) ? item.matched_terms : Array.isArray(item.shared_gloss_terms) ? item.shared_gloss_terms : []);
    if (item.via === 'english_dictionary_head_meaning') return `Dictionary meaning: a sense of its definition${item.gloss_source ? ` in ${item.gloss_source}` : ''} is ${terms}.`;
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
    const ci = row => window.MelosLemma?.interval?.(row.per_10k_ci95) || null;
    const points = periods.map((period, x) => {
      const row = (item.by_period || []).find(p => p.period === period.label) || {};
      const total = Number(row.tokens_in_period ?? period.tokens) || 0;
      return { x, value: total > 0 && Number.isFinite(Number(row.per_10k)) ? Number(row.per_10k) : NaN, count: Number(row.count) || 0, total, ci: total > 0 ? ci(row) : null };
    });
    // Release P lists the undated authors as a by_period row with its interval.
    const row = (item.by_period || []).find(p => isUndated(p.period));
    if (row && Number(row.tokens_in_period) > 0) {
      return { points, undated: { value: Number(row.per_10k), count: Number(row.count) || 0, total: Number(row.tokens_in_period), ci: ci(row), small: row.small_sample === true } };
    }
    const count = Number(item.undated_count) || 0;
    const undated = undatedTokens > 0 ? { value: count / undatedTokens * 10000, count, total: undatedTokens } : null;
    return { points, undated };
  }

  // The dated periods of the chart (the undated row is drawn apart); a period
  // is small by the API's flag, else under 50,000 words.
  function periodsFrom(lemmas) {
    const first = (lemmas || []).find(item => Array.isArray(item.by_period) && item.by_period.length);
    return (first?.by_period || []).filter(row => !isUndated(row.period)).map(row => {
      const tokens = Number(row.tokens_in_period) || 0;
      return { label: row.period, tokens, small: typeof row.small_sample === 'boolean' && tokens > 0 ? row.small_sample : tokens < SMALL_PERIOD };
    });
  }

  if (typeof document === 'undefined' || !document.getElementById?.('concept')) {
    window.MelosConceptPage = Object.freeze({ readState, sourceText, seriesFor, collapseVariants, periodsFrom });
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
      data = await api('/api/concept/diachrony', { q: state.q, ...(state.variants ? { combine_variants: 'true' } : {}) }, signal);
      const lemmas = state.variants ? collapseVariants(data.lemmas) : Array.isArray(data.lemmas) ? data.lemmas : [];
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

  function periodsOf() { return periodsFrom(data.lemmas); }

  function render(signal) {
    clear(ui.host);
    const head = node('header', 'entry-head');
    head.append(node('h1', 'headword', `“${data.concept || state.q}”`));
    const share = data.scope_tokens ? Math.round(Number(data.undated_tokens) / Number(data.scope_tokens) * 100) : 0;
    head.append(node('p', 'lead', `${plural(data.lemmas.length, 'Greek headword')} express this meaning in ${number(data.scope_tokens)} words of edited Greek. ${L.DATE_NOTE} ${share ? `${share}% of the words are by authors with no recorded date; they are shown apart and never placed in a period.` : ''}`));
    const jump = node('nav', 'jump'); jump.setAttribute('aria-label', 'Sections');
    for (const [id, label] of [['words', 'The words'], ['timeline', 'Over time'], ['companions', 'Companions by period'], ['phrases', 'Common phrases'], ['examples', 'Examples by period']]) jump.append(link(`#${id}`, label));
    const words = section('words', 'The words', 'Each headword is listed with where it comes from. Tick a word to draw it on the chart; choose its name to open its lexicon page.');
    const timeline = section('timeline', 'Over time', 'How often poets of each period use each word, per 10,000 of their words. The thin vertical line through a point is the range the true rate probably lies in (95%); faded points rest on few texts. Hover over or tap a point for the counts.');
    const companions = section('companions', 'Companions by period', 'The words most often found within five words of the chosen headword, period by period.');
    const phrases = section('phrases', 'Common phrases', 'Runs of headwords with the chosen word that recur in one period or author. Choose a phrase to find every passage with it.');
    const examples = section('examples', 'Examples by period', 'Passages from each period that use the chosen headword. Choose a line to read the whole passage.');
    ui.host.append(head, jump, words.box, timeline.box, companions.box, phrases.box, examples.box);
    const drawChart = () => renderTimeline(timeline.body);
    let drawnNarrow = narrow();
    window.onresize = () => { if (narrow() !== drawnNarrow) { drawnNarrow = narrow(); drawChart(); } };
    renderWords(words.body, drawChart);
    drawChart();
    const drawPicked = () => { renderCompanions(companions.body, drawPicked); renderPhrases(phrases.body, signal); renderExamples(examples.body, signal); };
    drawPicked();
    if (Array.isArray(data.warnings) && data.warnings.length) ui.host.append(node('p', 'fine', data.warnings.join(' ')));
    if (data.headwords_without_occurrences?.length) {
      ui.host.append(node('p', 'fine', `Also in the dictionaries but not found in the texts: ${data.headwords_without_occurrences.map(item => item.lemma || item).join(', ')}.`));
    }
  }

  function renderWords(host, redraw) {
    clear(host);
    // "Count variants together" when the dictionaries link some of the words.
    const groups = [...new Map(data.lemmas.filter(item => (item.variant_group?.members || []).length > 1)
      .map(item => { const names = item.variant_group.members.map(member => member.lemma); return [names.slice().sort().join(' '), names]; })).values()];
    if (groups.length || state.variants) {
      const toggle = node('label', 'variant-toggle');
      const box = node('input'); box.type = 'checkbox'; box.checked = state.variants;
      box.addEventListener('change', () => {
        state.variants = box.checked;
        const url = new URL(location.href);
        if (box.checked) url.searchParams.set('variants', '1'); else url.searchParams.delete('variants');
        history.replaceState(null, '', url);
        start();
      });
      toggle.append(box, ' ', node('span', '', `Count variants together${groups.length ? ` (${groups.slice(0, 3).map(names => names.join(' + ')).join(', ')})` : ''}`));
      host.append(toggle);
      if (state.variants) host.append(node('p', 'fine', 'Headwords the dictionaries list as forms of one another are counted as one word, under the first of them.'));
    }
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
      if (item.together?.length) { const also = greek('span', 'together', ` + ${item.together.join(' + ')}`); also.title = 'Counted together with this headword'; name.append(also); }
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
    const unused = (item.by_period || []).filter(period => !period.count && !isUndated(period.period) && Number(period.tokens_in_period) > 0).map(period => L.periodParts(period.period).name);
    const collocateList = collocates => {
      const list = node('ul');
      for (const c of collocates) {
        const li = node('li'); const a = link(L.lemmaHref(c.lemma), ''); a.append(greek('span', '', c.lemma)); li.append(a);
        li.append(node('span', '', ` ${c.gloss ? `${c.gloss} · ` : ''}${number(c.count)}× together`));
        list.append(li);
      }
      return list;
    };
    for (const period of (item.by_period || []).filter(period => period.count && !isUndated(period.period))) {
      const part = L.periodParts(period.period);
      const card = node('article', 'period-card');
      card.append(node('h3', '', part.name), node('p', 'span', `${part.span} · ${plural(period.count, 'occurrence')}`));
      const collocates = Array.isArray(period.collocates) ? period.collocates : [];
      if (!collocates.length) card.append(node('p', 'fine', 'Too few occurrences to show companions.'));
      else card.append(collocateList(collocates));
      grid.append(card);
    }
    const undatedRow = (item.by_period || []).find(period => isUndated(period.period));
    const undated = node('article', 'period-card undated');
    undated.append(node('h3', '', 'Undated authors'), node('p', 'span', `no recorded date · ${plural(undatedRow?.count ?? item.undated_count ?? 0, 'occurrence')}`));
    if (Array.isArray(undatedRow?.collocates) && undatedRow.collocates.length) undated.append(collocateList(undatedRow.collocates));
    else undated.append(node('p', 'fine', undatedRow ? 'Too few occurrences to show companions.' : 'Companions are worked out per period only; see the lexicon page for all of them.'));
    grid.append(undated);
    host.append(grid);
    if (unused.length) host.append(node('p', 'fine', `Not used by authors dated to: ${unused.join(', ')}.`));
    host.append(node('p', 'fine', 'A refrain repeated in one poem (Theocritus’ “mark, lady Moon, whence came my love”, for example) is counted once, and each text is read in one edition.'));
  }

  // Common phrases with the chosen headword, from the n-gram lists of the
  // periods that use it and its three most frequent authors.
  async function renderPhrases(host, signal) {
    const P = window.MelosPhrases, item = data.lemmas.find(entry => entry.lemma === picked), lemma = picked;
    clear(host);
    if (!P || !item) return;
    L.loading(host, 'Finding the phrases…');
    const groups = [...(item.by_period || []).filter(period => period.count).map(period => ({ kind: 'period', name: period.period, label: isUndated(period.period) ? 'undated authors' : L.periodParts(period.period).name })),
      ...(item.by_author || []).slice().sort((a, b) => b.count - a.count).slice(0, 3).map(row => ({ kind: 'author', name: row.author, label: row.author }))];
    const lists = await P.listsFor(groups, { load: () => api('/api/lemma/ngrams/groups'),
      fetchGroup: group => api('/api/lemma/ngrams', { kind: group.kind, name: group.name, q: lemma, limit: 20 }, signal) });
    if (signal?.aborted || picked !== lemma) return;
    clear(host);
    P.render(host, P.merge(lists), { node, shown: 8, highlight: lemma, empty: `No phrase with ${lemma} recurs often enough to list.` });
    host.append(node('p', 'fine', P.NOTE));
  }

  // One KWIC line opening the reader.
  function exampleLine(line, author) {
    const li = node('li'); const a = link(L.readerHref(line.id), '', 'kwic-line'); a.title = 'Read the whole passage';
    const where = node('span', 'kwic-where');
    where.append(node('span', 'kwic-author', line.author || author || 'Unattributed'), node('span', 'kwic-cite', L.citation(line)), node('span', 'kwic-date', L.authorDate(line.author_date)));
    const text = node('span', 'kwic-text'); text.lang = 'grc';
    text.append(node('span', 'kwic-left', line.left || ''), node('mark', 'kwic-key', line.keyword || ''), node('span', 'kwic-right', line.right || ''));
    a.append(where, text); li.append(a);
    return li;
  }

  async function renderExamples(host, signal) {
    clear(host);
    const item = data.lemmas.find(entry => entry.lemma === picked);
    // Release P: examples per period (from the three authors using the word
    // most there), the undated authors last.
    const given = (item.by_period || []).filter(period => period.count && Array.isArray(period.examples) && period.examples.length);
    if (given.length) {
      for (const period of [...given.filter(p => !isUndated(p.period)), ...given.filter(p => isUndated(p.period))]) {
        const part = isUndated(period.period) ? { name: 'Undated authors' } : L.periodParts(period.period);
        const box = node('div', 'example-period');
        box.append(node('h3', '', `${part.name}${part.span ? ` · ${part.span}` : ''}`));
        const list = node('ol', 'examples-list kwic');
        for (const line of period.examples.slice(0, 3)) list.append(exampleLine(line));
        box.append(list); host.append(box);
      }
      return;
    }
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
    state = { q: value, lemma: '', variants: state.variants };
    const url = new URL(location.href); url.searchParams.set('q', value); url.searchParams.delete('lemma');
    history.pushState(null, '', url);
    start();
  });
  window.addEventListener('popstate', () => { state = readState(location.href); start(); });
  start();
})();
