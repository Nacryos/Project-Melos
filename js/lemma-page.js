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
      author: text('author'), page: Number.isInteger(page) && page > 0 && page < 10000 ? page : 1 };
  }
  function writeState(href, state) {
    const url = new URL(href);
    for (const key of ['lemma', 'q', 'order', 'author', 'page']) url.searchParams.delete(key);
    if (state.lemma) url.searchParams.set('lemma', state.lemma); else if (state.q) url.searchParams.set('q', state.q);
    if (state.order === 'author') url.searchParams.set('order', 'author');
    if (state.author) url.searchParams.set('author', state.author);
    if (state.page > 1) url.searchParams.set('page', String(state.page));
    return url;
  }
  // What a reading of the query is, in words.
  function viaText(reading) {
    return ({ headword: 'the headword', headword_without_accents: 'the unaccented spelling of',
      printed_form_reading: 'a form of', english_dictionary_gloss: 'an English meaning of' })[reading?.via] || 'a reading of';
  }
  // Collocate strength in words: how many times more often than chance.
  function timesChance(item) {
    const ratio = Number(item.count) / Number(item.expected);
    if (!Number.isFinite(ratio) || ratio <= 0) return '';
    return ratio >= 100 ? `${number(Math.round(ratio))}×` : ratio >= 10 ? `${Math.round(ratio)}×` : `${ratio.toFixed(1)}×`;
  }

  if (typeof document === 'undefined' || !document.getElementById?.('entry')) {
    window.MelosLemmaPage = Object.freeze({ readState, writeState, viaText, timesChance });
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
    for (const [id, label] of [['dictionaries', 'Dictionaries'], ['frequency', 'Frequency'], ['concordance', 'In context'], ['collocations', 'Keeps company with'], ['forms', 'Forms']]) {
      jump.append(link(`#${id}`, label));
    }
    const dictionaries = section('dictionaries', 'Dictionaries');
    const frequency = section('frequency', 'Frequency');
    const concordance = section('concordance', 'In context', 'Every occurrence of any form of the word, with the words around it. Choose a line to read the whole passage.');
    const collocations = section('collocations', 'Keeps company with');
    const forms = section('forms', 'Forms that occur', 'Each spelling in the corpus that was read as this headword, with how often it occurs. Choose one to search for it.');
    ui.entry.append(head, jump, dictionaries.box, frequency.box, concordance.box, collocations.box, forms.box);
    for (const part of [dictionaries, frequency, collocations, forms]) L.loading(part.body, 'Loading…');
    current = { lemma, q, concordance: concordance.body };

    const freq = api('/api/lemma/frequency', { q }, signal);
    freq.then(data => renderHead(data, gloss), () => { gloss.classList.remove('melos-loading'); gloss.textContent = ''; });
    freq.then(data => renderFrequency(frequency.body, data), error => L.failure(frequency.body, error));
    api('/api/word', { form: lemma, lemma }, signal).then(data => renderDictionaries(dictionaries.body, lemma, data), error => L.failure(dictionaries.body, error));
    loadConcordance();
    api('/api/lemma/collocations', { q }, signal).then(data => renderCollocations(collocations.body, data), error => L.failure(collocations.body, error));
    api('/api/lemma/search', { q, limit: 1 }, signal).then(data => renderForms(forms.body, data), error => L.failure(forms.body, error));
    await freq.catch(() => null);
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
    const authorRow = row => ({ label: row.author, value: row.count, rate: row.per_10k, note: L.authorDate(row.date), raw: row, author: row.author,
      title: `${row.author}: ${plural(row.count, 'occurrence')}, ${rate(row.per_10k)} per 10,000 of their words. Show these lines.` });
    const value = row => `${number(row.value)} · ${rate(row.rate)} per 10k`;
    const select = row => { state.author = row.author; state.page = 1; loadConcordance(true); };
    const authors = (data.by_author || []).map(authorRow);
    const authorBox = node('div', 'chart-box');
    const drawAuthors = all => {
      clear(authorBox);
      authorBox.append(L.barChart(all ? authors : authors.slice(0, 12), { caption: 'Occurrences · rate per 10,000 of the author’s words. Choose an author to see the lines.', valueLabel: value, onSelect: select, selectLabel: 'Show these lines' }));
      if (authors.length > 12) {
        const more = node('button', 'quiet', all ? 'Show fewer authors' : `Show all ${authors.length} authors`); more.type = 'button';
        more.addEventListener('click', () => drawAuthors(!all)); authorBox.append(more);
      }
    };
    drawAuthors(false);
    const genres = (data.by_genre || []).map(row => ({ label: row.genre, value: row.count, rate: row.per_10k,
      title: `${row.genre}: ${plural(row.count, 'occurrence')} in ${number(row.tokens_in_group)} words` }));
    const genreBox = node('div', 'chart-box');
    genreBox.append(L.barChart(genres, { caption: 'Occurrences · rate per 10,000 words of the genre.', valueLabel: value }),
      node('p', 'fine', 'Genres are an editorial grouping of authors, not a property of each poem.'));
    const periods = (data.by_period || []).map(row => {
      const part = L.periodParts(row.period);
      const few = !part.undated && Number(row.tokens_in_group) < 50000;
      return { label: part.name, note: few ? `${part.span} · few texts, rate unreliable` : part.span, value: row.count, rate: row.per_10k, separate: part.undated, muted: few,
        title: `${part.name}: ${plural(row.count, 'occurrence')} in ${number(row.tokens_in_group)} words` };
    });
    const periodBox = node('div', 'chart-box');
    periodBox.append(L.barChart(periods, { caption: 'Occurrences · rate per 10,000 words written in that period.', valueLabel: value }),
      node('p', 'fine', `${L.DATE_NOTE} Authors with no recorded date are counted separately and never placed in a period.`));
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
      const data = await api('/api/lemma/concordance', { q: current.q, order: state.order, author: state.author, limit: PAGE, offset: (state.page - 1) * PAGE }, signal);
      const lines = Array.isArray(data.lines) ? data.lines : [];
      const total = Number(data.total || 0);
      count.classList.remove('melos-loading');
      if (!total) { count.textContent = ''; list.replaceWith(node('p', 'notice', 'No lines found.')); return; }
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
    if (Number(line.confidence) < 0.8) {
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
    state = { ...readState(location.href), lemma: '', q: value, page: 1, author: '' };
    history.pushState(null, '', writeState(location.href, state));
    start();
  });
  window.addEventListener('popstate', () => { state = readState(location.href); start(); });
  start();
})();
