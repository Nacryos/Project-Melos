// Lexicon page (lemma.html?lemma=σελήνη or ?q=σελάννα): one headword with its
// dictionaries side by side, frequency, a keyword-in-context concordance,
// collocations and inflected forms, from the corpus headword index.
(() => {
  'use strict';
  const L = window.MelosLemma || {};
  const { node, greek, clear, link, api, number, rate, plural } = L;
  const PAGE = 20;

  function readState(href) {
    const params = new URL(href).searchParams;
    const text = key => String(params.get(key) || '').trim().slice(0, 100);
    const page = Number(params.get('page'));
    return { lemma: text('lemma'), q: text('q'), order: params.get('order') === 'author' ? 'author' : 'chronological',
      author: text('author'), period: text('period'), variants: params.get('variants') === '1',
      page: Number.isInteger(page) && page > 0 && page < 10000 ? page : 1 };
  }
  function writeState(href, state) {
    const url = new URL(href);
    for (const key of ['lemma', 'q', 'order', 'author', 'period', 'variants', 'page']) url.searchParams.delete(key);
    if (state.lemma) url.searchParams.set('lemma', state.lemma); else if (state.q) url.searchParams.set('q', state.q);
    if (state.order === 'author') url.searchParams.set('order', 'author');
    if (state.author) url.searchParams.set('author', state.author);
    if (state.period) url.searchParams.set('period', state.period);
    if (state.variants) url.searchParams.set('variants', '1');
    if (state.page > 1) url.searchParams.set('page', String(state.page));
    return url;
  }
  // Concordance period filter: a period label, or "undated" for authors with
  // no recorded date (release P `period=` / `undated=true`).
  const PERIODS = ['Archaic (to 480 BCE)', 'Classical (480–323 BCE)', 'Hellenistic (323–31 BCE)', 'Roman imperial (31 BCE–300 CE)', 'Late antique (300–600 CE)'];
  function periodParams(period) {
    if (!period) return {};
    return period === 'undated' ? { undated: 'true' } : { period };
  }
  // Variant headwords (release P `variant_group`) in words, from the page's
  // headword: "ἔρος is a poetic form of ἔρως". One line per other member.
  const RELATION = { 'poet.': 'poetic form', 'Ep.': 'epic form', 'Ion.': 'Ionic form', 'Dor.': 'Doric form', 'Aeol.': 'Aeolic form',
    'Att.': 'Attic form', 'Lesb.': 'Lesbian form', 'Boeot.': 'Boeotian form', 'Lacon.': 'Laconian form', 'Thess.': 'Thessalian form', 'Cret.': 'Cretan form' };
  function relationText(variant, base, relation) {
    const rel = String(relation || '').trim();
    if (rel === '=' || !rel) return `${variant} is listed as another form of ${base}`;
    const words = RELATION[rel] || (/form/i.test(rel) ? rel : `${rel.replace(/\.$/, '')} form`);
    return `${variant} is ${/^[aeiouAEIOU]/.test(words) ? 'an' : 'a'} ${words} of ${base}`;
  }
  function variantLines(lemma, group) {
    const members = Array.isArray(group?.members) ? group.members : [];
    const same = value => String(value || '').normalize('NFC') === String(lemma || '').normalize('NFC');
    if (members.length < 2 || !members.some(member => same(member.lemma))) return [];
    const out = [];
    for (const member of members) {
      if (same(member.lemma)) continue;
      const links = (Array.isArray(member.links) ? member.links : []);
      // Prefer the link that joins this member to the page's headword.
      const link = links.find(item => same(item.lemma)) || links[0];
      if (!link) continue;
      const [variant, base] = link.direction === 'variant_of' ? [member.lemma, link.lemma] : [link.lemma, member.lemma];
      const dictionaries = [...new Set(links.filter(item => item.lemma === link.lemma).map(item => window.MelosWordPanel?.plainSource?.(item.dictionary) || item.dictionary).filter(Boolean))];
      out.push({ lemma: member.lemma, gloss: member.gloss || '', tokens: Number(member.tokens_all_records) || 0,
        text: relationText(variant, base, link.relation), dictionaries, evidence: String(link.evidence || '').trim() });
    }
    return out;
  }
  // What a reading of the query is, in words.
  function viaText(reading) {
    return ({ headword: 'the headword', headword_without_accents: 'the unaccented spelling of',
      printed_form_reading: 'a form of', english_dictionary_gloss: 'an English meaning of', english_dictionary_head_meaning: 'an English meaning of' })[reading?.via] || 'a reading of';
  }
  // Collocate strength in words: how many times more often than chance.
  function timesChance(item) {
    const ratio = Number(item.count) / Number(item.expected);
    if (!Number.isFinite(ratio) || ratio <= 0) return '';
    return ratio >= 100 ? `${number(Math.round(ratio))}×` : ratio >= 10 ? `${Math.round(ratio)}×` : `${ratio.toFixed(1)}×`;
  }

  if (typeof document === 'undefined' || !document.getElementById?.('entry')) {
    window.MelosLemmaPage = Object.freeze({ readState, writeState, viaText, timesChance, periodParams, relationText, variantLines, PERIODS });
    return;
  }

  const ui = { form: document.getElementById('lookup'), input: document.getElementById('lookup-input'),
    readings: document.getElementById('readings'), entry: document.getElementById('entry') };
  let state = readState(location.href), controller = null, concordanceController = null, current = null;

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
    ui.input.value = state.lemma || state.q;
    if (!state.lemma && !state.q) { ui.readings.hidden = true; return; }
    clear(ui.entry); L.loading(ui.entry, 'Finding the headword…');
    try {
      let resolution = [];
      if (state.q && !state.lemma) {
        const data = await api('/api/lemma/resolve', { q: state.q }, signal);
        resolution = Array.isArray(data.resolution) ? data.resolution : [];
        if (!resolution.length) {
          clear(ui.entry); ui.readings.hidden = true;
          ui.entry.append(node('h1', '', state.q), node('p', 'notice', `No headword was found for “${state.q}”. Try another spelling, the dictionary form, or an English word.`));
          return;
        }
        state.lemma = resolution[0].lemma;
        history.replaceState(null, '', writeState(location.href, state));
      }
      renderReadings(resolution);
      await renderLemma(state.lemma, signal);
    } catch (error) { if (!signal.aborted) L.failure(ui.entry, error, start); }
  }

  function renderReadings(resolution) {
    clear(ui.readings);
    const others = resolution.slice(1), first = resolution[0];
    const how = first && first.via !== 'headword' ? `“${state.q}” was found as ${viaText(first)} ${first.lemma}.` : '';
    if (!others.length && !how) { ui.readings.hidden = true; return; }
    ui.readings.hidden = false;
    if (how) ui.readings.append(node('span', 'readings-label', how));
    if (others.length) ui.readings.append(node('span', 'readings-label', `It can also be read as`));
    for (const reading of others.slice(0, 8)) {
      const a = link(L.lemmaHref(reading.lemma), '', 'chip');
      a.append(greek('span', '', reading.lemma));
      if (reading.gloss) a.append(node('span', 'chip-note', ` ${reading.gloss}`));
      a.title = `Found as ${viaText(reading)} ${reading.lemma}`;
      ui.readings.append(a);
    }
  }

  async function renderLemma(lemma, signal) {
    document.title = `${lemma} · Lexicon · Melos`;
    clear(ui.entry);
    const q = `lemma:${lemma}`;
    const head = node('header', 'entry-head');
    const title = greek('h1', 'headword', lemma);
    const gloss = node('p', 'gloss melos-loading', 'Looking up the meaning…');
    head.append(title, gloss);
    const actions = node('p', 'entry-actions');
    actions.append(link(L.searchHref(lemma), 'Search passages with any form →'), link(L.conceptHref(lemma), 'This meaning through time →'));
    head.append(actions);
    const jump = node('nav', 'jump'); jump.setAttribute('aria-label', 'Sections');
    for (const [id, label] of [['dictionaries', 'Dictionaries'], ['frequency', 'Frequency'], ['concordance', 'In context'], ['collocations', 'Keeps company with'], ['phrases', 'Common phrases'], ['forms', 'Forms']]) {
      jump.append(link(`#${id}`, label));
    }
    const dictionaries = section('dictionaries', 'Dictionaries');
    const frequency = section('frequency', 'Frequency');
    const concordance = section('concordance', 'In context', 'Every occurrence of any form of the word, with the words around it. Choose a line to read the whole passage.');
    const collocations = section('collocations', 'Keeps company with');
    const forms = section('forms', 'Forms that occur', 'Each spelling in the corpus that was read as this headword, with how often it occurs. Choose one to search for it.');
    const phrases = section('phrases', 'Common phrases', `Runs of headwords with ${lemma} that recur in one author, genre or period. Choose a phrase to find every passage with it.`);
    ui.entry.append(head, jump, dictionaries.box, frequency.box, concordance.box, collocations.box, phrases.box, forms.box);
    for (const part of [dictionaries, frequency, collocations, phrases, forms]) L.loading(part.body, 'Loading…');
    current = { lemma, q, concordance: concordance.body, frequency: frequency.body, signal };

    const freq = loadFrequency(signal);
    freq.then(data => { renderHead(data, gloss); renderVariants(head, lemma, data); }, () => { gloss.classList.remove('melos-loading'); gloss.textContent = ''; });
    freq.then(data => loadPhrases(phrases.body, lemma, data, signal), error => L.failure(phrases.body, error));
    api('/api/word', { form: lemma, lemma }, signal).then(data => renderDictionaries(dictionaries.body, lemma, data), error => L.failure(dictionaries.body, error));
    loadConcordance();
    api('/api/lemma/collocations', { q }, signal).then(data => renderCollocations(collocations.body, data), error => L.failure(collocations.body, error));
    api('/api/lemma/search', { q, limit: 1 }, signal).then(data => renderForms(forms.body, data), error => L.failure(forms.body, error));
    await freq.catch(() => null);
  }

  // Frequency, counting the variant headwords with this one when asked.
  function loadFrequency(signal = current?.signal) {
    const host = current.frequency;
    const request = api('/api/lemma/frequency', { q: current.q, ...(state.variants ? { combine_variants: 'true' } : {}) }, signal);
    request.then(data => renderFrequency(host, data), error => { if (!signal?.aborted) L.failure(host, error, () => loadFrequency()); });
    return request;
  }

  // "Related spellings": the dictionaries' variant links, each a lexicon link.
  function renderVariants(head, lemma, data) {
    const lines = variantLines(lemma, data?.variant_group);
    if (!lines.length) return;
    const box = node('div', 'variants');
    box.append(node('span', 'variants-label', lines.length === 1 ? 'Related spelling' : 'Related spellings'));
    const list = node('ul', 'variants-list');
    for (const line of lines) {
      const li = node('li');
      const a = link(L.lemmaHref(line.lemma), '', 'variant-link'); a.append(greek('span', '', line.lemma));
      if (line.gloss) a.append(node('span', 'chip-note', ` ${line.gloss}`));
      li.append(a, node('span', 'variant-text', ` — ${line.text}${line.dictionaries.length ? ` (${line.dictionaries.join(', ')})` : ''}${line.tokens ? ` · ${plural(line.tokens, 'occurrence')} in all records` : ''}`));
      if (line.evidence) li.title = `Dictionary text: “${line.evidence}”`;
      list.append(li);
    }
    box.append(list);
    head.insertBefore(box, head.querySelector('.entry-actions'));
  }

  // Common phrases with this headword: the corpus list and the lists of the
  // authors and genres that use it most (the service keeps the strongest
  // phrases of each group, so a headword's phrases are spread among them).
  async function loadPhrases(host, lemma, freq, signal) {
    const P = window.MelosPhrases;
    if (!P) { clear(host); return; }
    const groups = [{ kind: 'corpus', name: 'all', label: 'the whole corpus' },
      ...(freq?.by_author || []).slice(0, 4).map(row => ({ kind: 'author', name: row.author, label: row.author })),
      ...(freq?.by_genre || []).slice(0, 2).map(row => ({ kind: 'genre', name: row.genre, label: `${row.genre}` }))];
    const lists = await P.listsFor(groups, { load: () => api('/api/lemma/ngrams/groups'),
      fetchGroup: group => api('/api/lemma/ngrams', { kind: group.kind, name: group.name, q: lemma, limit: 20 }, signal) });
    if (signal?.aborted) return;
    clear(host);
    P.render(host, P.merge(lists), { node, shown: 8, highlight: lemma,
      empty: `No phrase with ${lemma} recurs often enough to list (three times in one author, five in a genre or period).` });
    host.append(node('p', 'fine', P.NOTE));
  }

  function renderHead(data, gloss) {
    const info = data?.lemma || {};
    gloss.classList.remove('melos-loading');
    gloss.textContent = '';
    if (info.gloss) gloss.append(node('span', 'gloss-text', info.gloss));
    const meta = [info.pos, info.gloss_source ? `meaning from ${info.gloss_source}` : ''].filter(Boolean).join(' · ');
    if (meta) gloss.append(node('span', 'gloss-meta', meta));
  }

  function renderDictionaries(host, lemma, data) {
    clear(host);
    const panel = window.MelosWordPanel;
    const blocks = panel?.dictionaryBlocks ? panel.dictionaryBlocks(lemma, Array.isArray(data?.lexicon_entries) ? data.lexicon_entries : []) : [];
    if (!blocks.length) { host.append(node('p', 'notice', `No dictionary entry for ${lemma} was found in the dictionaries we hold.`)); return; }
    const items = blocks.map(block => {
      const box = node('article', 'dictionary');
      const top = node('header', 'dictionary-head');
      top.append(node('h3', '', block.title));
      if (block.subtitle) top.append(node('p', 'dictionary-sub', block.subtitle));
      box.append(top);
      for (const entry of block.entries) {
        if (entry.senses.length) {
          const list = node('ol', 'senses');
          entry.senses.forEach((sense, index) => {
            const item = node('li', '');
            const label = sense.label && sense.label !== entry.senses[index - 1]?.label ? sense.label : '';
            if (label) item.append(node('span', 'sense-label', label));
            item.append(node('span', 'sense-text', sense.text));
            list.append(item);
          });
          box.append(list);
        }
        if (entry.text) {
          const full = node('details', 'full-entry');
          full.append(node('summary', '', 'Full entry'), node('p', '', entry.text));
          box.append(full);
        }
        if (/^https:\/\//.test(entry.url || '')) {
          const a = link(entry.url, `Open in ${block.title} ↗`, 'source-link'); a.target = '_blank'; a.rel = 'noopener noreferrer'; box.append(a);
        }
      }
      return { label: block.title, content: box };
    });
    const host2 = node('div', 'dictionary-set'); host2.id = 'dictionary-tabs';
    L.tabs(host2, items, { label: 'Dictionaries' });
    host.append(host2);
  }

  function renderFrequency(host, data) {
    clear(host);
    // "Count variants together": only when the dictionaries link this
    // headword to another (ἔρως and its poetic form ἔρος).
    const members = (data?.variant_group?.members || []).map(member => member.lemma).filter(Boolean);
    if (members.length > 1) {
      const toggle = node('label', 'variant-toggle');
      const box = node('input'); box.type = 'checkbox'; box.checked = state.variants;
      box.addEventListener('change', () => {
        state.variants = box.checked; history.replaceState(null, '', writeState(location.href, state));
        L.loading(host, box.checked ? `Counting ${members.join(' and ')} together…` : 'Counting this headword alone…');
        loadFrequency();
      });
      toggle.append(box, ' ', node('span', '', `Count variants together (${members.join(' + ')})`));
      host.append(toggle);
      if (state.variants) host.append(node('p', 'fine', `The figures below count ${members.join(', ')} as one word; the dictionaries list them as forms of one another, but the corpus keeps them as separate headwords.`));
    }
    if (!data?.tokens) {
      host.append(node('p', 'notice', 'This headword does not occur in the searchable Greek texts.'));
      return;
    }
    const stats = node('dl', 'stats');
    const stat = (value, label, note) => { const box = node('div', 'stat'); box.append(node('dt', '', label), node('dd', '', value)); if (note) box.append(node('dd', 'stat-note', note)); stats.append(box); };
    stat(number(data.tokens), 'occurrences', `in ${plural(data.passages, 'passage')}`);
    stat(rate(data.per_10k), 'per 10,000 words', `of ${number(data.scope_tokens)} words of edited Greek`);
    if (data.rank) stat(`No. ${number(data.rank)}`, 'by frequency', `of ${number(data.lemmas_in_scope)} headwords; no. 1 is the most common`);
    host.append(stats);
    if (data.possible_additional_tokens > 0) {
      host.append(node('p', 'fine', `${number(data.possible_additional_tokens)} more words have a spelling that could also be this headword, but were read as another; they are not counted.`));
    }
    // Rates carry their 95% interval (where the true rate probably lies);
    // groups under 50,000 words are faded and marked "few texts".
    const withRange = row => { const ci = L.interval(row.raw?.per_10k_ci95); return ci ? ` (${L.rangeText(ci)})` : ''; };
    const authorRow = row => {
      const few = L.smallSample(row);
      return { label: row.author, value: row.count, rate: row.per_10k, raw: row, author: row.author, muted: few,
        note: [L.authorDate(row.date), few ? 'few texts' : ''].filter(Boolean).join(' · '),
        title: `${row.author}: ${plural(row.count, 'occurrence')}, ${rate(row.per_10k)} per 10,000 of their words${L.interval(row.per_10k_ci95) ? ` (probably between ${L.rangeText(L.interval(row.per_10k_ci95))})` : ''}${few ? '; few texts, so the rate is unreliable' : ''}. Show these lines.` };
    };
    const countValue = row => `${number(row.value)} · ${rate(row.rate)} per 10k${withRange(row)}`;
    const select = row => { state.author = row.author; state.page = 1; loadConcordance(true); };
    const authors = (data.by_author || []).map(authorRow);
    const authorBox = node('div', 'chart-box');
    const drawAuthors = all => {
      clear(authorBox);
      authorBox.append(L.barChart(all ? authors : authors.slice(0, 12), { caption: 'Occurrences · rate per 10,000 of the author’s words (95% range in brackets). Choose an author to see the lines.', valueLabel: countValue, onSelect: select, selectLabel: 'Show these lines' }));
      if (authors.length > 12) {
        const more = node('button', 'quiet', all ? 'Show fewer authors' : `Show all ${authors.length} authors`); more.type = 'button';
        more.addEventListener('click', () => drawAuthors(!all)); authorBox.append(more);
      }
    };
    drawAuthors(false);
    // Genres and periods compare rates, so their bars are rates with a
    // whisker for the 95% interval.
    const rateRow = (row, name, extra = {}) => {
      const few = L.smallSample(row), ci = L.interval(row.per_10k_ci95);
      return { label: name, value: Number(row.per_10k) || 0, count: row.count, interval: ci, muted: few, raw: row, ...extra,
        note: [extra.note, few ? 'few texts, rate unreliable' : ''].filter(Boolean).join(' · '),
        title: `${name}: ${plural(row.count, 'occurrence')} in ${number(row.tokens_in_group)} words; ${rate(row.per_10k)} per 10,000${ci ? `, probably between ${L.rangeText(ci)}` : ''}${few ? '. Few texts, so the rate is unreliable.' : ''}` };
    };
    const rateValue = row => `${rate(row.value)} per 10k${row.interval ? ` (${L.rangeText(row.interval)})` : ''} · ${number(row.count)}`;
    const genres = (data.by_genre || []).map(row => rateRow(row, row.genre));
    const genreBox = node('div', 'chart-box');
    genreBox.append(L.barChart(genres, { caption: 'Rate per 10,000 words of the genre; the thin line is the 95% range, then the number of occurrences.', valueLabel: rateValue }),
      node('p', 'fine', 'Genres are an editorial grouping of authors, not a property of each poem.'));
    const periods = (data.by_period || []).map(row => {
      const part = L.periodParts(row.period);
      return rateRow(row, part.name, { note: part.span, separate: part.undated, period: part.undated ? 'undated' : row.period });
    });
    const periodBox = node('div', 'chart-box');
    periodBox.append(L.barChart(periods, { caption: 'Rate per 10,000 words written in that period; the thin line is the 95% range. Choose a period to see its lines.', valueLabel: rateValue,
      onSelect: row => { state.period = row.period; state.page = 1; loadConcordance(true); }, selectLabel: 'Show the lines from this period' }),
      node('p', 'fine', `${L.DATE_NOTE} Authors with no recorded date are counted separately and never placed in a period. A wide range means few words survive, so one poem can move the rate a lot.`));
    const tabsHost = node('div', 'chart-tabs'); tabsHost.id = 'frequency-tabs';
    L.tabs(tabsHost, [{ label: 'By author', content: authorBox }, { label: 'By genre', content: genreBox }, { label: 'By period', content: periodBox }], { label: 'Frequency' });
    host.append(tabsHost);
  }

  async function loadConcordance(scroll = false) {
    if (!current) return;
    const host = current.concordance;
    concordanceController?.abort(); concordanceController = new AbortController();
    const signal = concordanceController.signal;
    history.replaceState(null, '', writeState(location.href, state));
    clear(host);
    const controls = node('div', 'conc-controls');
    const sortLabel = node('label', '', 'Order ');
    const sort = node('select');
    for (const [value, text] of [['chronological', 'by author date'], ['author', 'by author name']]) {
      const option = node('option', '', text); option.value = value; sort.append(option);
    }
    sort.value = state.order;
    sort.addEventListener('change', () => { state.order = sort.value; state.page = 1; loadConcordance(); });
    sortLabel.append(sort);
    controls.append(sortLabel);
    // Period filter (release P): the dated periods, or authors with no date.
    const periodLabel = node('label', '', 'Period ');
    const period = node('select');
    for (const [value, text] of [['', 'all periods'], ...PERIODS.map(label => [label, L.periodParts(label).name]), ['undated', 'undated authors']]) {
      const option = node('option', '', text); option.value = value; period.append(option);
    }
    if (state.period && ![...period.options].some(option => option.value === state.period)) {
      const option = node('option', '', L.periodParts(state.period).name); option.value = state.period; period.append(option);
    }
    period.value = state.period;
    period.addEventListener('change', () => { state.period = period.value; state.page = 1; loadConcordance(); });
    periodLabel.append(period);
    controls.append(periodLabel);
    if (state.author) {
      const chip = node('button', 'chip chip-remove', `Only ${state.author} ×`); chip.type = 'button';
      chip.title = 'Show every author again';
      chip.addEventListener('click', () => { state.author = ''; state.page = 1; loadConcordance(); });
      controls.append(chip);
    }
    const count = node('span', 'conc-count melos-loading', 'Loading lines…');
    controls.append(count);
    host.append(controls);
    const list = node('ol', 'kwic'); host.append(list);
    if (scroll) host.closest('section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const data = await api('/api/lemma/concordance', { q: current.q, order: state.order, author: state.author, ...periodParams(state.period), limit: PAGE, offset: (state.page - 1) * PAGE }, signal);
      const lines = Array.isArray(data.lines) ? data.lines : [];
      const total = Number(data.total || 0);
      count.classList.remove('melos-loading');
      if (!total) { count.textContent = ''; list.replaceWith(node('p', 'notice', state.period || state.author ? 'No lines found with these filters.' : 'No lines found.')); return; }
      const first = (state.page - 1) * PAGE + 1;
      count.textContent = `Lines ${number(first)}–${number(first + lines.length - 1)} of ${number(total)}`;
      const seen = new Map();
      const fold = value => String(value || '').normalize('NFD').replace(/[\p{M}\p{P}\s]/gu, '').toLowerCase();
      for (const line of lines) {
        const key = `${line.author}|${fold(String(line.left).slice(-40))}|${fold(line.keyword)}|${fold(String(line.right).slice(0, 40))}`;
        const first = seen.get(key), collection = String(line.id || '').split(':')[0];
        // Another collection's copy of the same line is another edition; a
        // formula repeated within one text is a separate occurrence.
        if (first && !first.dataset.collections.split(' ').includes(collection)) {
          first.dataset.collections += ` ${collection}`;
          let also = first.querySelector('.kwic-also');
          if (!also) { also = node('p', 'kwic-also', 'Also in another edition: '); first.append(also); }
          const a = link(L.readerHref(line.id), L.citation(line) || 'another edition'); also.append(a, document.createTextNode(' '));
          continue;
        }
        const item = kwicLine(line); item.dataset.collections = collection; if (!first) seen.set(key, item); list.append(item);
      }
      const pages = Math.ceil(total / PAGE);
      if (pages > 1) {
        const pager = node('div', 'pager');
        const prev = node('button', 'quiet', '← Earlier lines'), next = node('button', 'quiet', 'Later lines →');
        prev.type = next.type = 'button'; prev.disabled = state.page <= 1; next.disabled = state.page >= pages;
        prev.addEventListener('click', () => { state.page -= 1; loadConcordance(true); });
        next.addEventListener('click', () => { state.page += 1; loadConcordance(true); });
        pager.append(prev, node('span', '', `Page ${state.page} of ${pages}`), next);
        host.append(pager);
      }
    } catch (error) { if (!signal.aborted) L.failure(host, error, () => loadConcordance()); }
  }

  function kwicLine(line) {
    const item = node('li');
    const a = link(L.readerHref(line.id), '', 'kwic-line');
    a.title = 'Read the whole passage';
    const where = node('span', 'kwic-where');
    where.append(node('span', 'kwic-author', line.author || 'Unattributed'), node('span', 'kwic-cite', L.citation(line)),
      node('span', 'kwic-date', L.authorDate(line.author_date)));
    const text = node('span', 'kwic-text'); text.lang = 'grc';
    text.append(node('span', 'kwic-left', line.left || ''), node('mark', 'kwic-key', line.keyword || ''), node('span', 'kwic-right', line.right || ''));
    a.append(where, text);
    // Calibrated probability (release P) in words; the raw score when absent.
    const panel = window.MelosWordPanel, likely = panel?.probabilityText?.(line.probability) || '';
    if (likely) {
      const low = panel.lowProbability(line.probability);
      where.append(node('span', `kwic-prob${low ? ' is-low' : ''}`, low ? `reading ${likely} · may be another word` : `reading ${likely}`));
      a.title = `Read the whole passage. The machine reading of this word as the headword is ${likely} to be right.`;
      if (low) item.classList.add('kwic-uncertain');
    } else if (Number(line.confidence) < 0.8) {
      a.append(node('span', 'kwic-flag', 'reading uncertain'));
      a.title = 'Read the whole passage. The machine reading of this word is less certain; it may belong to another headword.';
    }
    item.append(a);
    return item;
  }

  function renderCollocations(host, data) {
    clear(host);
    const items = Array.isArray(data?.collocates) ? data.collocates : [];
    const node0 = data?.node?.lemma || current?.lemma || '';
    host.append(node('p', 'lead', `Headwords found within ${data?.window || 5} words of ${node0} more often than chance would predict. “Together” counts how often they appear side by side; “more than chance” compares that with what you would expect if words were scattered at random; the score (log-likelihood) grows with both, and anything above 11 is very unlikely to be coincidence. Common little words such as “and” and “the” are left out.`));
    if (!items.length) { host.append(node('p', 'notice', 'Too few occurrences to say which words it keeps company with (at least three times together are needed).')); return; }
    const table = node('table', 'colloc');
    const headRow = node('tr');
    for (const text of ['Word', 'Meaning', 'Together', 'More than chance', 'Score', '']) headRow.append(node('th', '', text));
    const thead = node('thead'); thead.append(headRow);
    const body = node('tbody');
    items.forEach((item, index) => {
      const row = node('tr', index >= 12 ? 'extra' : '');
      const word = node('td'); const a = link(L.lemmaHref(item.lemma), '', 'colloc-word'); a.append(greek('span', '', item.lemma)); word.append(a);
      const example = node('td', 'colloc-example');
      if (item.example_passage) { const e = link(L.readerHref(item.example_passage), 'example', ''); e.title = 'Read a passage where they occur together'; example.append(e); }
      row.append(word, node('td', 'colloc-gloss', item.gloss || ''), node('td', 'num', number(item.count)), node('td', 'num', timesChance(item)),
        node('td', 'num', Number(item.log_likelihood).toFixed(0)), example);
      body.append(row);
    });
    table.append(thead, body);
    const wrap = node('div', 'table-wrap'); wrap.append(table);
    host.append(wrap);
    if (items.length > 12) {
      wrap.classList.add('collapsed');
      const more = node('button', 'quiet', `Show all ${items.length}`); more.type = 'button';
      more.addEventListener('click', () => { const open = wrap.classList.toggle('collapsed'); more.textContent = open ? `Show all ${items.length}` : 'Show fewer'; });
      host.append(more);
    }
  }

  function renderForms(host, data) {
    clear(host);
    const forms = Array.isArray(data?.forms_found) ? data.forms_found : [];
    if (!forms.length) { host.append(node('p', 'notice', 'No forms of this headword occur in the searchable texts.')); return; }
    const list = node('ul', 'forms');
    for (const form of forms) {
      const item = node('li');
      const a = link(L.searchHref(form.form, 'exact'), '', 'chip');
      a.title = `Search for the exact spelling ${form.form}`;
      a.append(greek('span', '', form.form), node('span', 'chip-count', number(form.count)));
      item.append(a); list.append(item);
    }
    host.append(list);
    if (data.forms_note) host.append(node('p', 'fine', data.forms_note));
  }

  ui.form.addEventListener('submit', event => {
    event.preventDefault();
    const value = ui.input.value.trim();
    if (!value) { ui.input.focus(); return; }
    state = { ...readState(location.href), lemma: '', q: value, page: 1, author: '', period: '', variants: false };
    history.pushState(null, '', writeState(location.href, state));
    start();
  });
  window.addEventListener('popstate', () => { state = readState(location.href); start(); });
  start();
})();
