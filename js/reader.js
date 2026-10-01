(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const ui = {
    searchForm: $('search-form'), searchInput: $('search-input'), bridgeNote: $('bridge-note'),
    status: $('corpus-status'), authors: $('author-list'), authorCount: $('author-count'),
    browseToggle: $('browse-toggle'), browseBody: $('browse-body'),
    authorFilter: $('author-filter'), edition: $('edition-filter'), language: $('language-filter'),
    order: $('order-filter'), reference: $('reference-filter'),
    results: $('search-results'), resultsHeading: $('results-heading'), resultsSummary: $('results-summary'),
    resultsList: $('results-list'), dictionaryPreview: $('dictionary-preview'), moreResults: $('more-results'), closeResults: $('close-results'),
    passage: $('passage'), title: $('passage-title'), subtitle: $('passage-subtitle'),
    kicker: $('passage-kicker'), text: $('passage-text'), textLeading: $('text-leading'),
    readingHint: $('reading-hint'), provenance: $('provenance'), related: $('related-material'),
    prev: $('prev-passage'), next: $('next-passage'),
    selectedPhrase: $('selected-phrase'), selectionActions: $('selection-actions'),
    inspector: $('inspector-content'), usage: $('open-usage'), lookupForm: $('lookup-form'),
    backToPassage: $('back-to-passage')
  };
  const state = {
    authors: [], works: new Map(), selectedAuthor: '', selectedWork: '', passage: null,
    search: null, displayedSearch: null, searchSequence: 0, passageSequence: 0, wordSequence: 0, passageLoading: false,
    selectedText: '', activeWord: null, semanticStatus: null, classifierStatus: null,
    dictionarySequence: 0, dictionaryCache: new Map()
  };

  function node(tag, className, content) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (content != null) el.textContent = String(content);
    if (tag === 'a' || tag === 'button') window.MelosIcons?.decorate(el);
    return el;
  }
  function clear(el) { el.replaceChildren(); }
  function safeLink(url, label) {
    if (!url) return null;
    try {
      const parsed = new URL(url, location.href);
      if (!['http:', 'https:'].includes(parsed.protocol)) return null;
      const a = node('a', '', label || 'Open original source ↗');
      a.href = parsed.href;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      return a;
    } catch { return null; }
  }
  function message(host, content, className = 'inspector-message') {
    clear(host); host.append(node('p', className, content));
  }
  function errorText(error) { return error instanceof Error ? error.message : String(error); }
  async function api(path, params = {}) {
    const url = window.melosApiUrl(path);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) {
      let detail = '';
      try { const body = await response.json(); detail = body.detail || body.error || ''; } catch { /* HTTP status remains useful. */ }
      throw new Error(detail ? `${response.status}: ${detail}` : `The corpus service returned ${response.status}.`);
    }
    return response.json();
  }
  async function apiPost(path, body, { signal } = {}) {
    const response = await fetch(window.melosApiUrl(path), { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
    if (!response.ok) {
      let detail = '', failure = null;
      try { failure = await response.json(); detail = failure.detail || failure.error || failure.status || ''; } catch {}
      const error = new Error(detail ? `${response.status}: ${detail}` : `The corpus service returned ${response.status}.`);
      error.status = response.status; error.response = failure; throw error;
    }
    return response.json();
  }
  function formMode() { return document.querySelector('input[name="search-mode"]:checked')?.value || 'hybrid'; }
  function setFormMode(mode) {
    const radio = document.querySelector(`input[name="search-mode"][value="${mode}"]`);
    if (radio) radio.checked = true;
    updateBridgeNote();
  }
  function updateBridgeNote() {
    ui.bridgeNote.textContent = formMode() === 'themes'
      ? 'Theme search may bridge through translations or commentary. Each result identifies the text that was indexed.'
      : formMode() === 'hybrid'
        ? 'All evidence combines word, form, and semantic candidates. Source links explain each result; ranking is not certainty or influence.'
        : 'English searches may use translations or commentary as a bridge. Results identify the indexed text.';
    if (state.semanticStatus) {
      const status = node('span', 'semantic-inline', ` ${state.semanticStatus.label}`);
      status.title = state.semanticStatus.detail;
      ui.bridgeNote.append(status);
    }
  }
  function qualityLabel(value) {
    return ({ source_text: 'Source text', machine_corrected_ocr: 'Machine-corrected OCR', machine_ocr: 'Raw machine OCR', mixed_content: 'Mixed content', needs_review: 'Needs review' })[value] || String(value || 'Unspecified');
  }
  function describeCount(count, thing) { return `${count.toLocaleString()} ${count === 1 ? thing : thing === 'match' ? 'matches' : `${thing}s`}`; }
  function semanticCoverage(embedding) {
    if (!embedding?.ready) return {
      label: 'Themes: unavailable (absent or stale).',
      detail: embedding?.warning || 'The local semantic index is absent or stale.'
    };
    const count = Number(embedding.count);
    const eligible = embedding.eligible_count == null ? NaN : Number(embedding.eligible_count);
    if (!Number.isFinite(count)) return { label: 'Themes: indexed.', detail: embedding.warning || 'Semantic index is ready.' };
    const detail = `${count.toLocaleString()} indexed${Number.isFinite(eligible) && eligible >= 0 ? ` of ${eligible.toLocaleString()} eligible source records` : ' source records'}. ${embedding.warning || ''}`;
    if (Number.isFinite(eligible) && eligible > count) return { label: `Themes: partial (${count.toLocaleString()}/${eligible.toLocaleString()} eligible).`, detail };
    return { label: Number.isFinite(eligible) ? `Themes: eligible index complete (${count.toLocaleString()}).` : `Themes: ${count.toLocaleString()} records indexed.`, detail };
  }
  function updateLanguageOptions(languages) {
    if (!Array.isArray(languages)) return;
    const selected = ui.language.value;
    const labels = { grc: 'Ancient Greek', ell: 'Modern Greek', eng: 'English', lat: 'Latin', ita: 'Italian', fra: 'French', deu: 'German', mul: 'Multilingual' };
    const available = [...new Set(languages.map(row => row.language).filter(Boolean))];
    clear(ui.language);
    const all = node('option', '', 'Any'); all.value = ''; ui.language.append(all);
    for (const code of available) {
      const option = node('option', '', labels[code] || code);
      option.value = code;
      ui.language.append(option);
    }
    if (available.includes(selected)) ui.language.value = selected;
  }
  function renderStatus(data) {
    const passages = Number(data.passages || 0);
    const authors = Number(data.authors || 0);
    const sourceLabels = data.author_labels == null ? null : Number(data.author_labels);
    ui.status.textContent = passages
      ? `${describeCount(passages, 'source record')} · ${Number.isFinite(sourceLabels) ? describeCount(sourceLabels, 'source author label') : describeCount(authors, 'author choice')}`
      : 'The corpus index is empty. Source records will appear when collection is complete.';
    if (Array.isArray(data.warnings) && data.warnings.length) ui.status.title = data.warnings.join(' ');
    state.semanticStatus = semanticCoverage(data.embeddings);
    state.classifierStatus = data.classifier || null;
    updateLanguageOptions(data.languages);
    updateBridgeNote();
  }
  function updateEditionOptions(allWorks) {
    const old = ui.edition.value;
    const editions = [...new Set(allWorks.map(w => w.edition).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    clear(ui.edition);
    ui.edition.append(node('option', '', 'All editions'));
    ui.edition.firstChild.value = '';
    for (const edition of editions) {
      const option = node('option', '', edition);
      option.value = edition;
      ui.edition.append(option);
    }
    retainSearchOption(ui.edition, old, 'edition');
  }
  function updateAuthorOptions() {
    const selected = ui.authorFilter.value;
    clear(ui.authorFilter);
    const all = node('option', '', 'All authors');
    all.value = '';
    ui.authorFilter.append(all);
    for (const entry of state.authors) {
      if (!entry.author) continue;
      const option = node('option', '', entry.author);
      option.value = entry.author;
      ui.authorFilter.append(option);
    }
    retainSearchOption(ui.authorFilter, selected, 'author');
  }
  function allKnownWorks() { return [...state.works.values()].flat(); }
  async function ensureWorks(author) {
    if (state.works.has(author)) return state.works.get(author);
    const data = await api('/api/works', { author });
    const works = Array.isArray(data.works) ? data.works : [];
    state.works.set(author, works);
    updateEditionOptions(allKnownWorks());
    return works;
  }
  function renderAuthors() {
    clear(ui.authors);
    ui.authorCount.textContent = String(state.authors.length).padStart(2, '0');
    if (!state.authors.length) {
      message(ui.authors, 'No authors are indexed yet.', 'panel-placeholder');
      return;
    }
    for (const item of state.authors) {
      const author = item.author || 'Unattributed';
      const row = node('div', 'author-row');
      const button = node('button', 'author-button');
      button.type = 'button';
      button.setAttribute('aria-expanded', String(state.selectedAuthor === author));
      const label = node('span', '', author);
      if (item.merged && Array.isArray(item.labels)) label.title = `Merged source labels: ${item.labels.join(', ')}`;
      const tail = node('span');
      tail.append(node('small', '', item.count != null ? item.count : ''), node('span', 'chevron', state.selectedAuthor === author ? '−' : '+'));
      button.append(label, tail);
      button.addEventListener('click', () => selectAuthor(author));
      row.append(button);
      if (state.selectedAuthor === author) {
        const list = node('div', 'work-list');
        const works = state.works.get(author);
        if (!works) list.append(node('p', 'panel-placeholder', 'Loading works…'));
        else if (!works.length) list.append(node('p', 'panel-placeholder', 'No works indexed.'));
        else for (const work of works) {
          const workButton = node('button', 'work-button');
          workButton.type = 'button';
          workButton.setAttribute('aria-current', String(work.id === state.selectedWork));
          workButton.append(node('span', '', work.work || 'Untitled work'));
          workButton.append(node('small', '', [work.edition, work.count != null ? `${work.count} passages` : ''].filter(Boolean).join(' · ')));
          workButton.addEventListener('click', () => selectWork(work));
          list.append(workButton);
        }
        row.append(list);
      }
      ui.authors.append(row);
    }
  }
  async function selectAuthor(author, openFirst = false) {
    if (state.selectedAuthor === author && !openFirst) {
      state.selectedAuthor = '';
      renderAuthors();
      return;
    }
    state.selectedAuthor = author;
    renderAuthors();
    try {
      const works = await ensureWorks(author);
      if (state.selectedAuthor !== author) return;
      renderAuthors();
      if (openFirst && works.length) {
        const preferred = works.find(w => w.language === 'grc') || works[0];
        await selectWork(preferred, false);
      }
    } catch (error) {
      if (state.selectedAuthor === author) {
        const list = ui.authors.querySelector('.work-list');
        if (list) message(list, `Could not load works: ${errorText(error)}`, 'warning error-message');
      }
    }
  }
  function resetPassageContext(loading = false) {
    state.machineAnalysisCancel?.();
    ui.selectionActions.classList.remove('selection-too-long');
    ++state.wordSequence;
    state.passage = null;
    state.passageLoading = loading;
    state.activeWord = null;
    state.selectedText = '';
    const selection = window.getSelection?.();
    if (selection?.anchorNode && ui.text.contains(selection.anchorNode)) selection.removeAllRanges?.();
    ui.passage.setAttribute('aria-busy', String(loading));
    ui.subtitle.textContent = '';
    ui.kicker.textContent = 'THE COLLECTION';
    ui.textLeading.textContent = '';
    ui.readingHint.textContent = '';
    clear(ui.provenance); ui.provenance.hidden = true;
    clear(ui.related); ui.related.hidden = true;
    ui.prev.disabled = true; ui.next.disabled = true;
    ui.selectionActions.hidden = true;
    ui.selectedPhrase.textContent = '';
    for (const button of ui.selectionActions.querySelectorAll('[data-phrase-mode]')) button.disabled = true;
    message(ui.inspector, loading ? 'Opening a new passage. Word lookup will be available once its text has loaded.' :
      'Open a passage to inspect a word in its context.');
  }
  async function selectWork(work, focus = true) {
    const sequence = ++state.passageSequence;
    resetPassageContext(true);
    state.selectedAuthor = work.author || state.selectedAuthor;
    state.selectedWork = work.id;
    ui.results.hidden = true;
    renderAuthors();
    ui.title.textContent = work.work || 'Opening work';
    message(ui.text, 'Loading a passage from this work…', 'loading-line');
    try {
      const data = await api('/api/passages', { work_id: work.id, limit: 20, offset: 0 });
      if (sequence !== state.passageSequence || state.selectedWork !== work.id) return;
      const results = Array.isArray(data.results) ? data.results : [];
      const first = results.find(p => p.language === 'grc' && p.kind === 'text' && p.quality === 'source_text' && p.text?.length < 700)
        || results.find(p => p.language === 'grc' && p.kind === 'text' && p.quality === 'source_text')
        || results.find(p => p.language === 'grc' && p.kind === 'text')
        || results.find(p => p.kind === 'text') || results[0];
      if (!first) { renderPassageEmpty('This work has no readable passages in the index.'); return; }
      await openPassage(first.id, focus);
    } catch (error) {
      if (sequence === state.passageSequence && state.selectedWork === work.id) renderPassageEmpty(`Could not load passages: ${errorText(error)}`, true);
    }
  }
  function renderPassageEmpty(text, isError = false) {
    ++state.passageSequence;
    resetPassageContext(false);
    ui.title.textContent = isError ? 'Passage unavailable' : 'No passage available';
    ui.subtitle.textContent = '';
    ui.kicker.textContent = 'THE COLLECTION';
    message(ui.text, text, isError ? 'warning error-message' : 'loading-line');
    ui.provenance.hidden = true; ui.related.hidden = true;
    ui.prev.disabled = true; ui.next.disabled = true;
  }

  // Shared literal lexer: retain source spelling, combining marks and offsets.
  // Apostrophes and the distinct printed spacing psili U+1FBF may attach inside
  // or at the end of a unit. Keeping that sign does not reinterpret it as elision.
  // Repeated punctuation separates units; mixed-script tokens are not partial Greek.
  function literalGreekWords(value) {
    const text = String(value || '');
    const letter = /\p{L}/u, greekLetter = /(?=\p{L})\p{Script=Greek}/u;
    const mark = /\p{M}/u, attachedSign = /['’᾽ʼ\u1fbf]/u;
    const words = [];
    let start = -1, end = 0, mixed = false;
    const flush = () => {
      if (start >= 0 && !mixed) {
        const raw = text.slice(start, end);
        words.push({ text: raw, start, end, form: raw, group: start, joined: false });
      }
      start = -1; mixed = false;
    };
    for (let offset = 0; offset < text.length;) {
      const character = String.fromCodePoint(text.codePointAt(offset));
      const next = offset + character.length;
      // Modifier apostrophe U+02BC is itself a letter: handle it first.
      if (attachedSign.test(character)) {
        if (start >= 0) {
          end = next;
          const following = next < text.length ? String.fromCodePoint(text.codePointAt(next)) : '';
          if (attachedSign.test(following) || !letter.test(following)) flush();
        }
      } else if (letter.test(character)) {
        if (start < 0) start = offset;
        end = next;
        if (!greekLetter.test(character)) mixed = true;
      } else if (mark.test(character)) {
        if (start >= 0) end = next;
      } else flush();
      offset = next;
    }
    flush();
    return words;
  }
  // Lookup units never replace the printed text. Only explicit line-end
  // divisions are joined; editorial brackets/lacunae/numbers remain barriers.
  function readingWords(value) {
    const text = String(value || '');
    const greekLetter = /(?=\p{L})\p{Script=Greek}/u;
    const words = literalGreekWords(text);
    for (let i = 0; i < words.length; i++) {
      let end = i;
      while (end + 1 < words.length) {
        const left = words[end], right = words[end + 1];
        if (!/^[-\u2010\u00ad][ \t]*\r?\n[ \t]*$/u.test(text.slice(left.end, right.start))) break;
        end++;
      }
      if (end > i) {
        const chain = words.slice(i, end + 1);
        const before = text.slice(0, words[i].start).match(/\S*$/u)[0];
        const after = text.slice(words[end].end).match(/^\S*/u)[0];
        const editorial = /[\[\]<>\{\}⟨⟩〈〉‹›⟦⟧⸢⸣⸤⸥†‡…\u0323\u2010\u00ad-]|\.{2,}/u;
        const dottedGap = /^\.(?:[ \t]*\.)+/u.test(text.slice(words[end].end));
        const orphanContinuation = /[-\u2010\u00ad][ \t]*\r?\n[ \t]*$/u.test(text.slice(0, words[i].start));
        const safe = !editorial.test(before) && !editorial.test(after) && !dottedGap && !orphanContinuation
          && chain.every(word => !/\u0323/u.test(word.text))
          && chain.slice(0, -1).every(word => greekLetter.test([...word.text.normalize('NFC')].at(-1)));
        if (safe) {
          const form = chain.map(word => word.text).join('');
          for (let j = i; j <= end; j++) Object.assign(words[j], { form, group: words[i].start, joined: true });
        } else {
          for (let j = i; j <= end; j++) words[j].fragmentaryJoinRejected = true;
        }
        // Advance even on rejection: never salvage a plausible-looking suffix
        // from the same uncertain chain as an independently complete word.
        i = end;
      }
    }
    return words;
  }
  function appendTextWithWords(host, value, words, offset = 0) {
    const text = String(value || '');
    let cursor = 0;
    for (const word of words.filter(word => word.start >= offset && word.end <= offset + text.length)) {
      const start = word.start - offset, end = word.end - offset;
      if (start > cursor) host.append(document.createTextNode(text.slice(cursor, start)));
      const button = node('button', 'word', text.slice(start, end));
      button.type = 'button';
      button.dataset.lookupGroup = String(word.group);
      button.setAttribute('aria-label', `Inspect ${word.form}${word.fragmentaryJoinRejected
        ? ', printed segment; complete word not established'
        : word.joined ? `, printed segment ${word.text}, divided across source lines` : ''}`);
      button.addEventListener('click', () => inspectWord(word.form, button, word.joined, Boolean(word.fragmentaryJoinRejected)));
      host.append(button);
      cursor = end;
    }
    if (cursor < text.length) host.append(document.createTextNode(text.slice(cursor)));
  }
  function separateLineLabel(line) {
    const label = String(line.label ?? '');
    if (!/^\d+$/.test(label)) return label;
    // Some source transcriptions retain their printed line number in text as
    // well as metadata. Suppress only the duplicate UI label, never source text.
    // Require a full stop followed by whitespace/end, a Greek letter or an
    // explicit editorial bracket. Bare numerals, decimals, repeated stops,
    // ranges and labels behind an editorial gap remain untouched.
    const printed = String(line.text || '').match(/^[ \t\u00a0]*(\d+)[ \t\u00a0]*\.(?=\s|$|(?=\p{L})\p{Script=Greek}|[\[\]⟨⟩])/u);
    return printed?.[1] === label ? '' : label;
  }
  // Verse keeps its line structure: each source line is one visual line and
  // the type shrinks to fit the box (js/verse-fit.js). Prose without line
  // breaks (long commentary, translations) wraps normally.
  function verseLines(passage) {
    if (Array.isArray(passage.lines) && passage.lines.length) {
      return passage.lines.map(line => ({ label: String(line?.label ?? ''), text: String(line?.text ?? '') }));
    }
    const text = String(passage.text || '');
    // Keep whitespace exactly: trimmed lines would shift lookup offsets and
    // alter the source text when selecting/copying or inspecting a word.
    if (text.includes('\n')) return text.split('\n').map(line => ({ label: '', text: line }));
    if (passage.kind === 'text' && passage.language === 'grc' && text.length <= 200) return [{ label: '', text }];
    return null;
  }
  function renderPassageText(passage) {
    clear(ui.text);
    ui.text.lang = passage.language === 'grc' ? 'grc' : passage.language || 'en';
    ui.textLeading.textContent = (passage.language || 'text').toUpperCase();
    const lines = verseLines(passage);
    ui.text.classList.toggle('verse-fit', Boolean(lines));
    if (lines) {
      // Lookup units are computed over the joined lines so a word divided at a
      // line end still forms one lookup; each printed line stays its own row.
      // Modern Greek translations are searchable evidence, not Ancient Greek
      // morphology attestations. Preserve their text without ancient-form buttons.
      const words = passage.language === 'ell' ? [] : readingWords(lines.map(line => line.text).join('\n'));
      let offset = 0;
      for (const line of lines) {
        const row = node('div', line.text ? 'line' : 'line blank');
        row.append(node('span', 'line-label', separateLineLabel(line)));
        const content = node('span', 'line-content');
        appendTextWithWords(content, line.text, words, offset);
        offset += line.text.length + 1;
        row.append(content); ui.text.append(row);
      }
      window.MelosVerseFit?.watch(ui.text, '.line');
    } else if (passage.text) {
      window.MelosVerseFit?.unwatch(ui.text);
      const paragraph = node('p');
      appendTextWithWords(paragraph, passage.text, passage.language === 'ell' ? [] : readingWords(passage.text));
      ui.text.append(paragraph);
    } else {
      window.MelosVerseFit?.unwatch(ui.text);
      message(ui.text, 'This record has no passage text.', 'loading-line');
    }
    ui.readingHint.textContent = passage.language === 'grc' && passage.kind === 'text'
      ? 'Select a phrase to trace it, or choose a Greek word to inspect it.'
      : passage.kind === 'translation'
        ? passage.language === 'ell'
          ? 'Modern Greek translation. Open the linked Ancient Greek passage below to inspect its word forms.'
          : 'Translation record. Related source material and provenance appear below when available.'
        : passage.kind === 'commentary' || passage.kind === 'apparatus'
          ? `${passage.kind === 'apparatus' ? 'Apparatus' : 'Commentary'} record. Consult its source details below.`
          : `This ${passage.kind || 'source'} record is labeled ${passage.language || 'unknown language'}; consult its source details below.`;
  }
  function addMeta(host, label, value, wide = false) {
    if (value == null || value === '') return;
    const item = node('div', `provenance-item${wide ? ' wide' : ''}`);
    item.append(node('span', 'meta-label', label));
    const val = node('div', 'meta-value');
    if (value instanceof Node) val.append(value); else val.textContent = String(value);
    item.append(val); host.append(item);
  }
  function renderSourcePageNotes(host, passage) {
    const metadata = passage.metadata && typeof passage.metadata === 'object' ? passage.metadata : {};
    const layoutNotes = [...new Set((Array.isArray(passage.lines) ? passage.lines : [])
      .map(line => line?.plain_text_limitation).filter(value => typeof value === 'string' && value.trim()))];
    if (layoutNotes.length) addMeta(host, 'Source layout', layoutNotes.join(' '));
    const seen = new Set([String(passage.citation || '').trim().replace(/\s+/g, ' ').toLowerCase()]);
    for (const [key, label] of [['source_heading', 'Source heading'], ['source_section', 'Source column / section'], ['source_subtitle', 'Source subtitle'], ['source_page_title', 'Source page title']]) {
      const value = metadata[key];
      if (typeof value !== 'string' || !value.trim()) continue;
      const identity = value.trim().replace(/\s+/g, ' ').toLowerCase();
      if (seen.has(identity)) continue;
      seen.add(identity); addMeta(host, label, value);
    }
    const notes = Array.isArray(metadata.source_footnote_links)
      ? metadata.source_footnote_links.filter(note => note && typeof note === 'object') : [];
    if (!notes.length) return;
    const disclosure = node('details', 'entry-details');
    disclosure.append(node('summary', '', `Read ${notes.length} source ${notes.length === 1 ? 'note' : 'notes'}`));
    for (const note of notes) {
      const entry = node('div', 'commentary-hit');
      const marker = typeof note.marker === 'string' && note.marker.trim() ? note.marker : '';
      let url = null;
      if (typeof note.href === 'string' && note.href.trim()) {
        try {
          // Resolve fragment and relative links against the original source,
          // never the current Melos route. safeLink still validates the protocol.
          url = new URL(note.href, passage.source_url).href;
        } catch { /* Keep the source note text when its link cannot be resolved. */ }
      }
      const link = safeLink(url, `${marker ? `Source note ${marker}` : 'Source note'} ↗`);
      entry.append(link || node('p', 'candidate-reason', `${marker ? `Source marker: ${marker} · ` : ''}Source note link unavailable`));
      if (note.scope === 'heading') entry.append(node('p', 'candidate-reason', 'Linked from the source heading.'));
      // title_html is an archival field, not display markup or a fallback. The
      // parser supplies plain description; line_index is not a verse citation.
      entry.append(node('p', 'commentary-excerpt', typeof note.description === 'string' && note.description.trim()
        ? note.description : 'Plain-text source note was not supplied.'));
      disclosure.append(entry);
    }
    addMeta(host, 'Source notes', disclosure, true);
  }
  function renderProvenance(passage) {
    clear(ui.provenance);
    addMeta(ui.provenance, 'Original reference', passage.citation || 'Not supplied');
    addMeta(ui.provenance, 'Edition', passage.edition || 'Not supplied');
    addMeta(ui.provenance, 'Collection', passage.source || 'Not supplied');
    addMeta(ui.provenance, 'Record type / language', [passage.kind || 'unlabeled', passage.language || 'unlabeled'].join(' · '));
    const tag = node('span', `quality-tag${passage.quality && passage.quality !== 'source_text' ? ' caution' : ''}`, qualityLabel(passage.quality));
    addMeta(ui.provenance, 'Text quality', tag);
    addMeta(ui.provenance, 'License', passage.license || 'Not supplied');
    const claim = chronologyClaim(passage);
    if (claim) {
      const date = node('span', '', `${claim.kind} claim: ${claim.interval} · selected ${claim.kind} interval; not a poem date`);
      if (claim.uncertainty.length) date.title = claim.uncertainty.join('; ');
      const sourceDate = safeLink(claim.sourceUrl, ' claim source ↗');
      if (sourceDate) date.append(sourceDate);
      addMeta(ui.provenance, 'Author date claim', date, true);
    }
    const metadata = passage.metadata && typeof passage.metadata === 'object' ? passage.metadata : {};
    if (typeof metadata.scope === 'string' && metadata.scope) {
      addMeta(ui.provenance, 'Source scope', metadata.scope === 'page' ? 'Page-wide material; no line-level alignment' : metadata.scope);
    }
    renderSourcePageNotes(ui.provenance, passage);
    const notes = [
      ['Attribution note', metadata.attribution_note, metadata.attribution_note_source_url],
      ['Source grouping note', metadata.source_group_description, metadata.source_group_source_url],
      ['Source note', metadata.source_note, metadata.source_note_url],
      ['Source warning', metadata.aggregation_warning || metadata.warning, metadata.warning_source_url],
      ['Index review', metadata.index_review, null]
    ];
    for (const [label, value, url] of notes) {
      if (typeof value !== 'string' || !value.trim()) continue;
      const note = node('span', '', value);
      const link = safeLink(url, ' source ↗');
      if (link) note.append(link);
      addMeta(ui.provenance, label, note, true);
    }
    const source = safeLink(passage.source_url, 'View the original source ↗');
    if (source) addMeta(ui.provenance, 'Source record', source, true);
    const page = safeLink(passage.metadata?.page_url, 'View scanned page ↗');
    if (page) addMeta(ui.provenance, 'Page in source edition', page, true);
    const image = safeLink(passage.metadata?.page_image_url, 'View page image ↗');
    if (image) addMeta(ui.provenance, 'Source image', image, true);
    ui.provenance.hidden = false;
  }
  function renderRelated(related) {
    clear(ui.related);
    const translations = passageTranslationPreviews(state.passage);
    const promoted = new Set(translations.map(item => item.record_id));
    related = (Array.isArray(related) ? related : []).filter(item => !promoted.has(item?.id));
    if (translations.length) renderPublishedTranslations(ui.related, translations);
    if (!related.length) { ui.related.hidden = !translations.length; return; }
    const heading = node('span', 'eyebrow', 'RELATED SOURCE MATERIAL');
    ui.related.append(heading);
    if (related.some(item => ['page', 'source_section'].includes(item?.metadata?.scope))) {
      ui.related.append(node('p', 'related-note', 'Page-wide and source-section notes are source-page material, not annotations aligned to the selected passage.'));
    }
    for (const item of related) {
      if (!item || !item.text) continue;
      const article = node('div', 'related-item');
      const pageWide = item.metadata?.scope === 'page';
      const sourceSection = item.metadata?.scope === 'source_section';
      const nonAligned = pageWide || sourceSection;
      article.append(node('span', 'eyebrow', [sourceSection ? 'Source-section note · not passage-aligned' : pageWide ? 'Page-wide note' : item.kind, item.edition].filter(Boolean).join(' · ') || 'Related record'));
      if (item.kind === 'translation') {
        // `author` commonly names the ancient poet, not the translator.
        // Only an explicit source-extracted translator field supplies a credit.
        const credit = typeof item.metadata?.translator === 'string' ? item.metadata.translator.trim() : '';
        const language = ({ ell: 'Modern Greek', eng: 'English', lat: 'Latin', grc: 'Ancient Greek' })[item.language] || item.language;
        article.append(node('p', 'candidate-reason', [language, credit ? `Translator: ${credit}` : 'Translator not recorded'].filter(Boolean).join(' · ')));
      }
      if (sourceSection) {
        const labels = [...new Set([item.metadata?.source_heading, item.metadata?.source_section, item.citation].filter(value => typeof value === 'string' && value.trim()))];
        article.append(node('p', 'candidate-reason', labels.length ? `Source section / citation: ${labels.join(' · ')}` : 'Source section label not supplied.'));
      }
      if (nonAligned) {
        const details = node('details', 'related-details');
        details.append(node('summary', '', `Read ${item.kind || 'reference'} from this source ${sourceSection ? 'section' : 'page'}`), node('p', item.language === 'grc' ? 'related-greek' : '', item.text));
        article.append(details);
      } else article.append(node('p', item.language === 'grc' ? 'related-greek' : '', item.text));
      const link = safeLink(item.metadata?.page_url || item.source_url, nonAligned ? 'View source page ↗' : 'Source ↗');
      if (link) article.append(link);
      const explicitlyLinked = item.parent_id === state.passage?.id || state.passage?.parent_id === item.id;
      if (item.id && explicitlyLinked && !nonAligned && ['text', 'translation'].includes(item.kind)) {
        const read = node('button', 'related-open', item.language === 'grc' ? 'Read linked Greek passage →' : 'Read linked translation →');
        read.type = 'button';
        read.addEventListener('click', () => openPassage(item.id));
        article.append(read);
      }
      ui.related.append(article);
    }
    ui.related.hidden = !translations.length && !ui.related.querySelector('.related-item');
  }
  function passageTranslationPreviews(record) {
    if (record?.kind !== 'text' || record?.language !== 'grc') return [];
    return (Array.isArray(record.translation_previews) ? record.translation_previews : []).filter(item =>
      item?.parent_id === record.id && item.scope === 'whole_source_passage' &&
      item.alignment === 'not_line_aligned' && typeof item.text_excerpt === 'string' && item.text_excerpt.trim());
  }
  function translationCredit(item) {
    const language = ({ ell: 'Modern Greek', eng: 'English', lat: 'Latin', grc: 'Ancient Greek' })[item.language] || item.language;
    const translator = typeof item.translator === 'string' ? item.translator.trim() : '';
    return [language, translator ? `Translator: ${translator}` : 'Translator not recorded'].filter(Boolean).join(' · ');
  }
  function renderPublishedTranslations(host, translations) {
    const section = node('section', 'published-translations');
    section.append(node('span', 'eyebrow', 'PUBLISHED TRANSLATION'),
      node('p', 'translation-scope', 'Of this complete source passage — not aligned to individual lines or a selected phrase.'));
    function card(item, target) {
      const article = node('div', 'published-translation');
      article.append(node('p', 'translation-credit', translationCredit(item)),
        node('p', 'translation-excerpt', item.text_excerpt));
      const details = node('details', 'translation-full');
      details.append(node('summary', '', 'Read full translation and source'));
      if (item.source === 'perseus' && typeof item.scope_note === 'string' && item.scope_note.trim()) {
        details.append(node('p', 'translation-scope', item.scope_note));
      }
      if (typeof item.text === 'string' && item.text.trim()) details.append(node('p', 'translation-text', item.text));
      details.append(node('p', 'translation-edition', [item.edition, item.citation].filter(Boolean).join(' · ')));
      const link = safeLink(item.source_url, 'Published source ↗');
      if (link) details.append(link);
      article.append(details); target.append(article);
    }
    card(translations[0], section);
    if (translations.length > 1) {
      const alternatives = node('details', 'translation-alternatives');
      alternatives.append(node('summary', '', `${translations.length - 1} other published ${translations.length === 2 ? 'translation' : 'translations'}`));
      for (const item of translations.slice(1)) card(item, alternatives);
      section.append(alternatives);
    }
    if (state.passage?.translation_previews_truncated) section.append(node('p', 'translation-scope',
      'Additional translations remain in the related source records below.'));
    host.append(section);
  }
  function renderOccurrencePreview(host, data) {
    const raw = Array.isArray(data.occurrences) ? data.occurrences : [];
    const groups = Array.isArray(data.occurrence_preview_groups)
      ? data.occurrence_preview_groups
      : raw.map(record => ({ representative_id: record.id, members: [record] }));
    const preview = groups.filter(group => Array.isArray(group.members) && group.members.length).slice(0, 12);
    const found = addInspectorSection(`Occurrence preview · ${preview.length} shown`, host);
    if (!preview.length) found.append(node('p', 'inspector-message', 'No occurrence preview was returned. Search the full index for additional matches.'));
    for (const group of preview) {
      const occurrence = group.members.find(item => item.id === group.representative_id) || group.members[0];
      const row = node('div', 'occurrence');
      const label = [occurrence.author, occurrence.work, occurrence.citation].filter(Boolean).join(' · ') || 'Passage';
      if (occurrence.id) {
        const open = node('button', '', label);
        open.type = 'button'; open.addEventListener('click', () => openPassage(occurrence.id));
        row.append(open);
      } else row.append(node('span', '', label));
      const copies = node('details', 'occurrence-sources');
      copies.append(node('summary', '', group.members.length > 1
        ? `Same text · ${group.members.length} source records` : 'Source record'));
      for (const member of group.members) {
        const line = node('p', 'occurrence-source');
        line.append(node('span', '', [member.author, member.work, member.citation,
          member.edition, member.source, member.quality && qualityLabel(member.quality)].filter(Boolean).join(' · ')));
        if (member.id) {
          const open = node('button', 'related-open', `Open ${member.id}`);
          open.type = 'button'; open.addEventListener('click', () => openPassage(member.id));
          line.append(open);
        }
        const link = safeLink(member.source_url, ' Source ↗');
        if (link) line.append(link);
        copies.append(line);
      }
      row.append(copies);
      found.append(row);
    }
    return found;
  }
  function renderMirrors(mirrors) {
    if (!Array.isArray(mirrors) || !mirrors.length) return;
    ui.related.hidden = false;
    const block = node('div', 'related-item mirror-list');
    block.append(node('span', 'eyebrow', `IDENTICAL TEXT IN ${mirrors.length} OTHER ${mirrors.length === 1 ? 'COPY' : 'COPIES'}`));
    block.append(node('p', 'related-note', 'Identical wording is shown together here; each copy retains its own source and citation.'));
    for (const copy of mirrors) {
      const line = node('p', 'mirror-copy');
      line.append(node('span', '', [copy.source, copy.edition, copy.citation, copy.author, copy.quality && copy.quality !== 'source_text' ? qualityLabel(copy.quality) : ''].filter(Boolean).join(' · ')));
      if (copy.id) {
        const open = node('button', 'related-open', 'Open this copy →');
        open.type = 'button';
        open.addEventListener('click', () => openPassage(copy.id));
        line.append(open);
      }
      const link = safeLink(copy.source_url, ' Source ↗');
      if (link) line.append(link);
      block.append(line);
    }
    ui.related.append(block);
  }
  async function openPassage(id, focus = true) {
    if (!id) return;
    const sequence = ++state.passageSequence;
    resetPassageContext(true);
    ui.title.textContent = 'Opening passage';
    message(ui.text, 'Loading the original text…', 'loading-line');
    try {
      const passage = await api('/api/passage', { id });
      if (sequence !== state.passageSequence) return;
      ++state.wordSequence;
      state.passage = passage;
      state.passageLoading = false;
      state.activeWord = null;
      state.selectedText = '';
      ui.passage.setAttribute('aria-busy', 'false');
      state.selectedAuthor = passage.author_canonical || passage.author || state.selectedAuthor;
      if (passage.work_id) state.selectedWork = passage.work_id;
      ui.kicker.textContent = passage.kind === 'text' ? 'FROM THE LYRIC COLLECTION' : 'REFERENCE RECORD';
      ui.title.textContent = [passage.author, passage.work].filter(Boolean).join(' · ') || 'Unattributed passage';
      ui.subtitle.textContent = passage.citation || 'Citation not supplied by source';
      renderPassageText(passage);
      renderRelated(passage.related);
      renderMirrors(passage.mirrors);
      renderProvenance(passage);
      ui.prev.disabled = !passage.previous_id;
      ui.next.disabled = !passage.next_id;
      clear(ui.inspector);
      const empty = node('div', 'inspector-empty');
      empty.append(node('span', 'inspector-symbol', 'α'), node('p', '', 'Choose a Greek word in the passage. Its recorded forms, possible analyses, and sources will appear here.'));
      ui.inspector.append(empty);
      ui.selectionActions.hidden = true;
      if (state.works.has(state.selectedAuthor)) renderAuthors();
      const current = new URL(location.href);
      current.searchParams.set('id', passage.id || id);
      history.replaceState(null, '', current);
      if (focus) ui.passage.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      if (sequence === state.passageSequence) renderPassageEmpty(`Could not open this passage: ${errorText(error)}`, true);
    }
  }

  function appendWarnings(host, warnings) {
    if (!Array.isArray(warnings)) return;
    for (const warning of warnings.slice(0, 3)) {
      if (warning) host.append(node('p', 'warning', typeof warning === 'string' ? warning : JSON.stringify(warning)));
    }
  }
  function chronologyClaim(record) {
    const chronology = record?.author_chronology;
    if (!chronology) return null;
    const selected = chronology.selected_claim;
    const bounds = Array.isArray(selected?.effective_year_interval) ? selected.effective_year_interval : [chronology.sort_start, chronology.sort_end];
    if (bounds[0] == null || bounds[0] === '' || !Number.isFinite(Number(bounds[0]))) return null;
    const start = Number(bounds[0]);
    const end = bounds[1] == null || bounds[1] === '' || !Number.isFinite(Number(bounds[1])) ? start : Number(bounds[1]);
    if (!start || !end) return null;
    const year = value => `${Math.abs(value)} ${value < 0 ? 'BCE' : 'CE'}`;
    const interval = start === end ? year(start) : (start < 0) === (end < 0)
      ? `${Math.abs(start)}–${Math.abs(end)} ${start < 0 ? 'BCE' : 'CE'}`
      : `${year(start)}–${year(end)}`;
    const kind = selected?.kind || chronology.claim_kind;
    if (!['birth', 'floruit'].includes(kind)) return null;
    return { kind, interval, sourceUrl: selected?.statement_url || chronology.source_url,
      uncertainty: Array.isArray(selected?.uncertainty) ? selected.uncertainty : [] };
  }
  function renderResult(record) {
    const button = node('button', 'result-button');
    button.type = 'button';
    const source = node('span', 'result-source', record.author || 'Unattributed');
    source.append(node('small', '', [record.work, record.citation, record.kind && record.kind !== 'text' ? `indexed ${record.kind}` : record.language !== 'grc' ? record.language : 'Greek text'].filter(Boolean).join(' · ')));
    if (record.quality && record.quality !== 'source_text') source.append(node('span', 'quality-tag caution', qualityLabel(record.quality)));
    const body = node('span', 'result-body');
    const excerpt = (record.text || '').replace(/\s+/g, ' ').trim();
    body.append(node('span', 'result-excerpt', excerpt || 'Text unavailable'));
    body.append(node('span', 'result-edition', `Edition: ${record.edition || 'Not supplied'}`),
      node('span', 'result-collection', `Collection: ${record.source || 'Not supplied'}`));
    const translation = passageTranslationPreviews(record)[0];
    if (translation) {
      const preview = node('span', 'result-translation');
      preview.append(node('span', 'result-translation-excerpt', translation.text_excerpt),
        node('span', 'result-translation-credit', translationCredit(translation)),
        node('span', 'result-translation-scope', 'Published translation excerpt · covers this source passage · open for full text and source'));
      body.append(preview);
    }
    const dateClaim = chronologyClaim(record);
    const copies = Number(record.mirror_count) > 1 ? `${record.mirror_count - 1} identical ${record.mirror_count === 2 ? 'copy' : 'copies'} collapsed` : '';
    const quality = record.quality && record.quality !== 'source_text' ? qualityLabel(record.quality) : '';
    const reason = [record.match_reason, quality, copies, dateClaim ? `Author date claim (${dateClaim.kind}): ${dateClaim.interval}` : ''].filter(Boolean).join(' · ');
    if (reason) body.append(node('span', 'result-reason', reason));
    const evidence = Array.isArray(record.matched_evidence) ? record.matched_evidence : [];
    const readingIds = new Set([record.id, ...(Array.isArray(record.mirrored_ids) ? record.mirrored_ids : [])]);
    const hasLinkedExcerpt = hit => record.kind === 'text' && record.language === 'grc' &&
      hit && ['commentary', 'translation'].includes(hit.kind) &&
      typeof hit.id === 'string' && hit.id !== record.id &&
      hit.projection_scope === 'explicit_parent_id' &&
      typeof hit.parent_id === 'string' && readingIds.has(hit.parent_id) &&
      typeof hit.text_excerpt === 'string' && !!hit.text_excerpt.trim();
    const comparableExcerpt = value => value.replace(/\s+/gu, ' ').trim();
    const alreadyPreviewed = hit => translation && hasLinkedExcerpt(hit) && hit.kind === 'translation' &&
      !!translation.record_id && hit.id === translation.record_id && hit.parent_id === translation.parent_id &&
      (!hit.source_url || !translation.source_url || hit.source_url === translation.source_url) &&
      comparableExcerpt(translation.text_excerpt).includes(comparableExcerpt(hit.text_excerpt));
    // Only suppress an exact source-record repetition already covered by the
    // visible preview. Different editions and additional excerpt text remain.
    const remainingEvidence = evidence.filter(hit => !alreadyPreviewed(hit));
    // Put the actual supporting source text before generic signal labels.
    // Multiple retrieval signals for one source record are not new witnesses.
    const linkedEvidence = remainingEvidence.filter(hasLinkedExcerpt);
    const seenEvidence = new Set();
    const displayedEvidence = [...linkedEvidence, ...remainingEvidence.filter(hit => hit && !hasLinkedExcerpt(hit))]
      .filter(hit => {
        if (!hit.id) return true;
        if (seenEvidence.has(hit.id)) return false;
        seenEvidence.add(hit.id); return true;
      }).slice(0, 3);
    if (displayedEvidence.some(hasLinkedExcerpt)) body.append(node('span', 'result-reason', 'Matched source excerpts'));
    for (const hit of displayedEvidence) {
      const detail = node('span', 'evidence-hit');
      if (hasLinkedExcerpt(hit)) {
        const credit = [
          hit.kind === 'commentary' ? 'Commentary excerpt' : 'Translation excerpt',
          hit.author || 'Author not recorded',
          hit.citation, hit.edition,
          hit.quality && hit.quality !== 'source_text' ? qualityLabel(hit.quality) : ''
        ].filter(Boolean).join(' · ');
        detail.append(node('span', '', credit), node('span', 'result-reason', hit.text_excerpt));
        const scope = hit.parent_id === record.id
          ? 'Linked passage; not word-aligned.'
          : 'Linked to another indexed reading; compare editions.';
        detail.append(node('span', 'result-reason',
          `${scope}${hit.excerpt_truncated ? ' Excerpt shortened.' : ''}`));
      } else {
        const label = [hit.signal && String(hit.signal).replaceAll('_', ' '), hit.kind, hit.quality && hit.quality !== 'source_text' ? qualityLabel(hit.quality) : '', hit.author, hit.citation].filter(Boolean).join(' · ');
        detail.append(node('span', '', `${label || 'Linked source'}: ${hit.match_reason || 'retrieval match'}`));
      }
      body.append(detail);
    }
    if (record.retrieval_score_kind === 'reciprocal_rank_fusion') body.append(node('span', 'result-reason', 'Ranked by reciprocal rank fusion; rank is not confidence.'));
    button.append(source, body);
    button.addEventListener('click', () => openPassage(record.id));
    return button;
  }
  function renderDictionaryPreview(host, data, { openEntries = true, wiktionary = null } = {}) {
    const preview = window.MelosDictionaryPreview?.buildPreview(data, wiktionary);
    if (!preview?.entries?.length) return false;
    const section = node('section', 'dictionary-glimpse');
    section.append(node('span', 'eyebrow', 'DICTIONARY'));
    const friendlySource = name => window.MelosDictionaryPreview.friendlySourceName?.(name) || name || 'Source';
    function renderEntries(entries, target, compact = false) {
    const lemmaGroups = new Map();
    for (const entry of entries) {
      const key = String(entry.lemma).normalize('NFC');
      let group = lemmaGroups.get(key);
      if (!group) {
        group = node('div', 'dictionary-glimpse-group');
        group.append(node('h3', 'dictionary-glimpse-lemma', entry.lemma));
        if (preview.query && preview.query !== entry.lemma) group.append(node('p', 'candidate-reason', `Searched form: ${preview.query}`));
        lemmaGroups.set(key, group); target.append(group);
      }
      const card = node('div', 'dictionary-glimpse-entry');
      if (!compact && entry.source) card.append(node('p', 'candidate-reason', entry.source));
      if (entry.ambiguous && entry.label && !compact) card.append(node('p', 'candidate-reason', entry.label));
      const parses = [...new Set((entry.analyses || []).map(analysis => analysis.text).filter(Boolean))];
      if (parses.length) card.append(node('p', 'candidate-analysis', parses.slice(0, 3).join(' · ')));
      const analysisSources = new Map((entry.analyses || []).map(analysis => [analysis.source_url, analysis.source]));
      for (const [url, sourceName] of compact ? [] : analysisSources) {
        const source = safeLink(url, `Form analysis: ${friendlySource(sourceName)}`);
        if (source) { source.className = 'dictionary-glimpse-source'; card.append(source); }
      }
      for (const meaning of entry.meanings || []) {
        const line = node('p', 'dictionary-glimpse-meaning', meaning.text);
        const source = safeLink(meaning.source_url, friendlySource(meaning.source || entry.source));
        if (source) { source.className = 'dictionary-glimpse-source'; source.title = meaning.source || entry.source || 'Dictionary source'; line.append(source); }
        card.append(line);
      }
      if (openEntries) {
        const open = node('button', 'text-action', 'Inspect this lemma');
        open.type = 'button';
        open.addEventListener('click', () => {
          inspectWord(entry.lemma);
          ui.inspector.closest('.inspector').scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        card.append(open);
        const full = safeLink(entry.entry_url || entry.source_url, 'Full dictionary entry');
        if (full) { full.className = 'dictionary-glimpse-source'; card.append(full); }
      }
      group.append(card);
    }
    }
    renderEntries(preview.compact?.entries || preview.entries, section, true);
    if (preview.compact && (preview.compact.omitted_entry_count || preview.compact.omitted_meaning_count || preview.truncated)) {
      const details = node('details', 'dictionary-glimpse-details');
      details.append(node('summary', '', 'More meanings and dictionary sources'));
      renderEntries(preview.entries, details);
      section.append(details);
    }
    section.append(node('p', 'candidate-reason', preview.ambiguous
      ? 'Several readings are recorded; context determines the intended sense.'
      : 'Dictionary meanings; context determines the intended sense.'));
    host.append(section);
    return true;
  }
  async function loadDictionaryPreview(query) {
    const sequence = ++state.dictionarySequence;
    clear(ui.dictionaryPreview);
    ui.dictionaryPreview.hidden = true;
    if (!window.MelosDictionaryPreview?.isCandidateQuery(query) || ui.language.value === 'ell') return;
    try {
      let evidence = state.dictionaryCache.get(query);
      if (!evidence) {
        const [word, wiktionary] = await Promise.all([
          api('/api/word', { form: query }).catch(() => null),
          /\p{Script=Greek}/u.test(query) ? api('/api/wiktionary', { form: query, limit: 8 }).catch(() => null) : Promise.resolve(null),
        ]);
        evidence = { word, wiktionary };
        if (word || wiktionary) state.dictionaryCache.set(query, evidence);
        if (state.dictionaryCache.size > 30) state.dictionaryCache.delete(state.dictionaryCache.keys().next().value);
      }
      if (sequence !== state.dictionarySequence) return;
      ui.dictionaryPreview.hidden = !renderDictionaryPreview(ui.dictionaryPreview, evidence.word || { form: query }, { wiktionary: evidence.wiktionary });
    } catch {
      // An unavailable dictionary preview must never block passage search or
      // fill the space with generated definitions.
    }
  }
  function readSearchUrl(params) {
    const issues = [];
    const value = (key, max = 500) => {
      const raw = params.get(key) || '';
      if (raw.length > max || /[\u0000-\u001f\u007f]/.test(raw)) {
        issues.push(`The saved ${key} is invalid; choose it again before searching.`); return '';
      }
      return raw.trim();
    };
    const choice = (key, allowed, fallback) => {
      const raw = value(key);
      if (!raw) return fallback;
      if (allowed.includes(raw)) return raw;
      issues.push(`The saved ${key} is unsupported; choose it again before searching.`);
      return fallback;
    };
    return { query: value('q', 1000),
      mode: choice('mode', ['hybrid', 'exact', 'fuzzy', 'forms', 'themes'], 'hybrid'),
      author: value('author'), edition: value('edition', 1000),
      language: (() => { const language = value('lang', 16);
        if (!language || /^[a-z]{2,8}(?:-[a-z]{2,8})?$/.test(language)) return language;
        issues.push('The saved language is invalid; choose it again before searching.'); return '';
      })(),
      order: choice('order', ['relevance', 'chronological'], 'relevance'),
      include_reference: choice('ref', ['0', '1'], '0') === '1', issues };
  }
  function writeSearchUrl(base, snapshot) {
    const url = new URL(base);
    const values = { q: snapshot.query, mode: snapshot.mode, author: snapshot.author,
      edition: snapshot.edition, lang: snapshot.language, order: snapshot.order,
      ref: snapshot.include_reference ? '1' : '0' };
    for (const [key, value] of Object.entries(values)) {
      if (value === '' || value == null) url.searchParams.delete(key);
      else url.searchParams.set(key, String(value));
    }
    return url;
  }
  function retainSearchOption(select, value, label) {
    if (value && !Array.from(select.options).some(option => option.value === value)) {
      const option = node('option', '', `${value} — saved ${label}, unavailable in current list`);
      option.value = value;
      option.dataset.unavailable = 'true';
      select.append(option);
    }
    select.value = value || '';
  }
  function restoreSearchUrl(params) {
    const saved = readSearchUrl(params);
    ui.searchInput.value = saved.query;
    setFormMode(saved.mode);
    retainSearchOption(ui.authorFilter, saved.author, 'author');
    retainSearchOption(ui.edition, saved.edition, 'edition');
    retainSearchOption(ui.language, saved.language, 'language');
    ui.order.value = saved.order;
    ui.reference.checked = saved.include_reference;
    return saved;
  }
  function snapshotSearch(query, mode) {
    return Object.freeze({ query, mode: ['hybrid', 'exact', 'fuzzy', 'forms', 'themes'].includes(mode) ? mode : 'fuzzy',
      author: ui.authorFilter.value, edition: ui.edition.value, language: ui.language.value,
      order: ['relevance', 'chronological'].includes(ui.order.value) ? ui.order.value : 'relevance',
      include_reference: ui.reference.checked });
  }
  function searchTransport(snapshot) {
    return { q: snapshot.query, mode: ['forms', 'themes', 'hybrid'].includes(snapshot.mode) ? snapshot.mode : 'words',
      match: snapshot.mode === 'exact' ? 'exact' : 'fuzzy', commentary_assisted: true,
      author: snapshot.author, edition: snapshot.edition, language: snapshot.language,
      order: snapshot.order, include_reference: snapshot.include_reference };
  }
  function usageSnapshot(query) {
    const current = snapshotSearch(query, formMode());
    if (!ui.results.hidden && state.displayedSearch) {
      const saved = state.displayedSearch;
      const changed = Object.keys(saved).some(key => saved[key] !== current[key]);
      return { ...searchTransport(saved), scope_origin: 'Last successfully displayed search',
        scope_notice: changed ? 'Current inputs differ; this view uses the displayed search filters, not the unsent changes.' : '' };
    }
    return { ...searchTransport(current), scope_origin: 'Current query and controls', scope_notice: '' };
  }
  async function search(query, mode = formMode(), append = false) {
    query = String(query || '').trim();
    if (!query) { ui.searchInput.focus(); return; }
    if (!append) {
      state.search = { query, mode, filters: snapshotSearch(query, mode), offset: 0, total: 0 };
      state.displayedSearch = null;
      clear(ui.resultsList);
      ui.results.hidden = false;
      ui.resultsHeading.textContent = `Results for “${query}”`;
      ui.resultsSummary.textContent = 'Searching the source index…';
      ui.moreResults.hidden = true;
      loadDictionaryPreview(query);
      ui.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    const active = state.search;
    if (!active) return;
    const snapshot = active.filters;
    query = snapshot.query;
    mode = snapshot.mode;
    const scopeWarnings = [[ui.authorFilter, 'author'], [ui.edition, 'edition'], [ui.language, 'language']]
      .filter(([select, label]) => Array.from(select.options).some(option => option.value === snapshot[label] && option.dataset.unavailable === 'true'))
      .map(([, label]) => `The saved ${label} “${snapshot[label]}” is unavailable in the current filter list. Its exact filter is retained; this search has not been broadened.`);
    const sequence = ++state.searchSequence;
    const params = {
      ...searchTransport(snapshot), limit: 30, offset: append ? active.offset : 0
    };
    try {
      const data = await api('/api/search', params);
      if (sequence !== state.searchSequence) return;
      const records = Array.isArray(data.results) ? data.results : [];
      active.total = Number(data.total || 0);
      active.offset += records.length;
      if (!append) clear(ui.resultsList);
      if (!append && Array.isArray(data.transliteration_phrase?.matched_greek_phrases)) {
        const wording = [...new Set(data.transliteration_phrase.matched_greek_phrases
          .filter(value => typeof value === 'string' && value.trim()).map(value => value.trim()))];
        if (wording.length) ui.resultsList.append(node('p', 'candidate-reason transliteration-wording',
          `Matched Greek wording: ${wording.join(' · ')} — normalized for matching, not the source's accents or spelling.`));
      }
      for (const record of records) ui.resultsList.append(renderResult(record));
      const count = ui.resultsList.querySelectorAll('.result-button').length;
      const ranked = ['themes', 'hybrid'].includes(mode) && !String(data.method || '').includes('reference');
      const method = ranked ? (mode === 'themes' ? ' · Thematic similarity' : ' · Words, forms and thematic links') : '';
      const sortLabel = snapshot.order === 'chronological' ? ' · author chronology, where sourced' : '';
      ui.resultsSummary.textContent = `${describeCount(active.total, ranked ? 'ranked result' : 'match')} · ${count} shown${method}${sortLabel}`;
      ui.resultsSummary.title = String(data.method || '').replaceAll('_', ' ');
      if (!count) ui.resultsList.append(node('p', 'inspector-message', mode === 'themes'
        ? 'No ranked passage candidates were returned for this query and filters.'
        : 'No indexed passage matches these terms and filters. This does not establish absence from the author’s work. Try another spelling, mode, or edition.'));
      if (!append && data.excluded_exact_matches?.total > 0) {
        const excluded = data.excluded_exact_matches;
        const notice = node('div', 'warning excluded-matches');
        const groups = (excluded.groups || []).map(group => `${group.count} ${qualityLabel(group.quality)} ${group.kind || 'record'}`).join('; ');
        notice.append(node('p', '', `${describeCount(excluded.total, 'indexed record')} with exact normalized wording or citation ${excluded.total === 1 ? 'is' : 'are'} excluded by the default quality/reference filter. ${groups}. These are not verified attestations.`));
        notice.append(node('p', 'candidate-reason', 'This check does not count excluded fuzzy, inflected-form, or thematic matches.'));
        const show = node('button', 'text-action', 'Include these records in exact search →');
        show.type = 'button';
        show.addEventListener('click', () => {
          ui.reference.checked = true;
          setFormMode('exact');
          search(query, 'exact');
        });
        notice.append(show);
        ui.resultsList.append(notice);
      }
      appendWarnings(ui.resultsList, data.warnings);
      appendWarnings(ui.resultsList, scopeWarnings);
      ui.moreResults.hidden = count >= active.total || records.length === 0;
      state.displayedSearch = snapshot;
      const url = writeSearchUrl(location.href, snapshot);
      history.replaceState(null, '', url);
    } catch (error) {
      if (sequence !== state.searchSequence) return;
      ui.resultsSummary.textContent = 'Search could not be completed.';
      ui.resultsList.append(node('p', 'warning error-message', errorText(error)));
      ui.moreResults.hidden = true;
    }
  }

  function addInspectorSection(title, host = ui.inspector) {
    const section = node('section', 'inspector-section');
    section.append(node('h3', '', title));
    host.append(section);
    return section;
  }
  function stringList(value) {
    if (typeof value === 'string') return value ? [value] : [];
    return Array.isArray(value) ? value.filter(item => typeof item === 'string' && item.trim()) : [];
  }
  function referenceList(value) {
    if (!Array.isArray(value)) return [];
    return value.map(item => typeof item === 'string' ? item : item?.word || item?.form || item?.term).filter(Boolean);
  }
  function addWiktionaryLabels(host, scope, tags, rawTags) {
    const labels = stringList(tags);
    const raw = stringList(rawTags);
    if (!labels.length && !raw.length) return;
    const row = node('p', 'wiktionary-labels');
    row.append(node('b', '', `${scope} labels: `), document.createTextNode(labels.join(' · ') || 'none supplied'));
    if (raw.length) row.append(node('span', 'wiktionary-raw-labels', `Source labels: ${raw.join(' · ')}`));
    host.append(row);
  }
  function addWiktionaryRelation(host, label, value) {
    const words = referenceList(value);
    if (words.length) host.append(node('p', 'wiktionary-relation', `${label}: ${words.join(' · ')}`));
  }
  function renderWiktionary(host, data) {
    clear(host);
    const section = addInspectorSection('Wiktionary dialect references', host);
    section.classList.add('wiktionary-section');
    section.append(node('p', 'wiktionary-caveat', 'Machine-extracted dictionary reference. Listed forms are not corpus attestations, and senses are not selected for this passage.'));
    if (!data.ready) {
      section.append(node('p', 'inspector-message', 'Audited Wiktionary references are unavailable for this snapshot.'));
      appendWarnings(section, data.warnings);
      return;
    }
    const entries = Array.isArray(data.results) ? data.results : [];
    if (!entries.length) {
      section.append(node('p', 'inspector-message', 'No audited headword or dictionary-listed form matched this query.'));
      appendWarnings(section, data.warnings);
      return;
    }
    const total = Number(data.total);
    section.append(node('p', 'candidate-reason', `${entries.length} of ${Number.isFinite(total) ? total : entries.length} source entries shown · ${data.method || 'audited dictionary lookup'}`));
    for (const entry of entries) {
      const card = node('article', 'wiktionary-entry');
      const heading = node('div', 'wiktionary-entry-heading');
      heading.append(node('span', 'candidate-lemma', entry.headword || 'Unlabeled headword'));
      if (entry.pos) heading.append(node('span', 'wiktionary-pos', entry.pos));
      card.append(heading);
      addWiktionaryLabels(card, 'Entry', entry.entry_tags, entry.entry_raw_tags);
      addWiktionaryRelation(card, 'Entry form of', entry.entry_form_of);
      addWiktionaryRelation(card, 'Entry alternative of', entry.entry_alt_of);
      const matches = Array.isArray(entry.matches) ? entry.matches : [];
      for (const match of matches) {
        if (match.kind === 'headword') {
          card.append(node('p', 'wiktionary-match', 'Matched dictionary headword'));
        } else if (match.kind === 'listed_form' && match.form) {
          const listed = node('div', 'wiktionary-listed-form');
          listed.append(node('p', 'wiktionary-match', `Matched dictionary-listed form: ${match.form.form || 'unlabeled'}`));
          addWiktionaryLabels(listed, 'Listed form', match.form.tags, match.form.raw_tags);
          card.append(listed);
        }
      }
      const senses = Array.isArray(entry.senses) ? entry.senses : [];
      if (senses.length) {
        const list = node('div', 'wiktionary-senses');
        list.append(node('span', 'candidate-meta-label', `Dictionary senses · ${senses.length}${Number(entry.total_senses) > senses.length ? ` of ${entry.total_senses} shown` : ''}`));
        for (const sense of senses) {
          const item = node('div', 'wiktionary-sense');
          const index = Number.isInteger(sense.sense_index) ? sense.sense_index + 1 : '';
          const glosses = stringList(sense.glosses);
          item.append(node('p', 'wiktionary-gloss', `${index ? `${index}. ` : ''}${glosses.join('; ') || 'No gloss supplied'}`));
          addWiktionaryLabels(item, 'Sense', sense.tags, sense.raw_tags);
          addWiktionaryRelation(item, 'Sense form of', sense.form_of);
          addWiktionaryRelation(item, 'Sense alternative of', sense.alt_of);
          const rawGlosses = stringList(sense.raw_glosses);
          if (rawGlosses.length && rawGlosses.join('; ') !== glosses.join('; ')) {
            const details = node('details', 'entry-details');
            details.append(node('summary', '', 'Source gloss text'), node('p', '', rawGlosses.join('; ')));
            item.append(details);
          }
          list.append(item);
        }
        card.append(list);
      }
      const live = safeLink(entry.entry_url || entry.live_entry_url, 'Live Wiktionary page ↗');
      if (live) {
        live.title = entry.live_entry_note || 'The live page may differ from the audited snapshot.';
        card.append(live, node('p', 'candidate-reason', 'Live page may differ from the saved dictionary snapshot.'));
      }
      card.append(node('p', 'candidate-reason', [entry.source, entry.quality, entry.license].filter(Boolean).join(' · ')));
      if (entry.raw_line_sha256) {
        const hash = node('details', 'entry-details');
        hash.append(node('summary', '', 'Snapshot record hash'), node('code', '', entry.raw_line_sha256));
        card.append(hash);
      }
      section.append(card);
    }
    appendWarnings(section, (data.warnings || []).filter(warning => !/not attestations/i.test(String(warning))));
  }
  async function loadWiktionary(form, sequence, host) {
    const section = addInspectorSection('Wiktionary dialect references', host);
    section.append(node('p', 'inspector-message', 'Checking the audited dictionary snapshot…'));
    try {
      const data = await api('/api/wiktionary', { form, limit: 8 });
      if (sequence !== state.wordSequence) return;
      renderWiktionary(host, data);
      return data;
    } catch (error) {
      if (sequence !== state.wordSequence) return;
      clear(host);
      const unavailable = addInspectorSection('Wiktionary dialect references', host);
      unavailable.append(node('p', 'inspector-message', `Dictionary reference unavailable: ${errorText(error)}`));
    }
  }
  function foldGreekForm(value) {
    return String(value || '').replace(/[’᾽ʼ]/gu, "'").normalize('NFD').toLowerCase().replace(/\p{M}/gu, '').replaceAll('ς', 'σ');
  }
  function renderRelatedCommentary(form, related, host) {
    if (!Array.isArray(related) || !/\p{Script=Greek}/u.test(form)) return;
    const folded = foldGreekForm(form);
    const hits = [];
    for (const item of related) {
      if (item?.kind !== 'commentary' || typeof item.text !== 'string') continue;
      for (const word of literalGreekWords(item.text)) {
        if (foldGreekForm(word.text) !== folded) continue;
        const start = Math.max(0, word.start - 65);
        const end = Math.min(item.text.length, word.end + 95);
        hits.push({ item, start, end });
        break; // One preview per source note; nearby mentions remain in its full text.
      }
      if (hits.length >= 3) break;
    }
    if (!hits.length) return;
    const section = addInspectorSection('Source commentary mentioning this form', host);
    section.append(node('p', 'candidate-reason', 'Literal whole-form match with accents folded in related source commentary; each note retains its source scope. No parse or sense is selected.'));
    for (const { item, start, end } of hits) {
      const source = node('div', 'commentary-hit');
      source.append(node('p', 'commentary-source', [item.author, item.work, item.citation, item.edition].filter(Boolean).join(' · ') || 'Linked source commentary'));
      if (item.metadata?.scope === 'page') source.append(node('p', 'candidate-reason', 'Page-wide source note; no line-level alignment claimed.'));
      if (item.metadata?.scope === 'source_section') {
        const labels = [...new Set([item.metadata?.source_heading, item.metadata?.source_section, item.citation].filter(value => typeof value === 'string' && value.trim()))];
        source.append(node('p', 'candidate-reason', `Source-section note; not aligned to the selected passage.${labels.length ? ` Source section / citation: ${labels.join(' · ')}` : ''}`));
      }
      source.append(node('p', 'commentary-excerpt', `${start ? '…' : ''}${item.text.slice(start, end)}${end < item.text.length ? '…' : ''}`));
      const link = safeLink(item.metadata?.page_url || item.source_url, 'View source note ↗');
      if (link) source.append(link);
      if (start || end < item.text.length) {
        const full = node('details', 'entry-details');
        full.append(node('summary', '', 'Read full source note'), node('p', '', item.text));
        source.append(full);
      }
      section.append(source);
    }
  }
  function formatFeatures(features) {
    if (!features || typeof features !== 'object') return String(features || '');
    const order = ['tense', 'voice', 'mood', 'person', 'number', 'gender', 'case'];
    return [...order.filter(key => features[key] != null), ...Object.keys(features).filter(key => !order.includes(key))]
      .map(key => String(features[key])).join(' · ');
  }
  function claimValue(claim) {
    const value = claim.object;
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join(' · ');
    if (!value || typeof value !== 'object') return String(value ?? '');
    const pieces = ['form', 'lemma', 'raw_label', 'gloss', 'sense', 'relation_raw', 'equivalent_form'].filter(key => value[key] != null).map(key => `${key.replaceAll('_', ' ')}: ${typeof value[key] === 'object' ? JSON.stringify(value[key]) : value[key]}`);
    if (value.features) pieces.push(`features: ${formatFeatures(value.features)}`);
    if (value.listed_form_count != null) pieces.push(`${value.listed_form_count} listed source forms`);
    return pieces.join(' · ') || JSON.stringify(value);
  }
  function renderClaim(claim) {
    const card = node('article', 'claim-card');
    const scope = claim.strength === 'explicit_passage_span' ? 'Linked to this passage and text span'
      : claim.strength === 'explicit_passage_link' ? 'Linked to this passage'
      : claim.strength === 'parallel_matching_text' ? 'Commentary on matching wording in another source'
      : claim.strength === 'listed_entry_form' ? 'Form listed in a source entry; no passage attestation'
      : 'General form claim; no passage attestation';
    card.append(node('div', 'claim-scope', `${scope} · ${String(claim.predicate || 'source claim').replaceAll('_', ' ')}`));
    card.append(node('p', 'claim-value', claimValue(claim)));
    if (Array.isArray(claim.matched_object_forms) && claim.matched_object_forms.length) {
      card.append(node('p', 'claim-scope', `Matched listed form: ${claim.matched_object_forms.map(value => typeof value === 'string' ? value : value?.form || JSON.stringify(value)).join(' · ')}`));
    }
    if (claim.status !== 'source_claim' || claim.assertion_type === 'model_inference') card.append(node('p', 'claim-status', `${String(claim.status || 'unreviewed').replaceAll('_', ' ')} · ${String(claim.assertion_type || '').replaceAll('_', ' ')}`));
    if (claim.match_reason) card.append(node('p', 'claim-scope', claim.match_reason));
    for (const evidence of (claim.evidence || []).slice(0, 2)) {
      if (evidence.quote) card.append(node('p', 'claim-quote', `“${evidence.quote}”`));
      const source = safeLink(evidence.source_url, [claim.source_family, evidence.locator].filter(Boolean).join(' · ') + ' ↗');
      if (source) card.append(source);
    }
    return card;
  }
  function renderStructuredEvidence(host, data, passageId) {
    if (!data) return;
    const claims = Array.isArray(data.claims) ? data.claims : [];
    const linked = claims.filter(claim => claim.strength === 'explicit_passage_span' || claim.strength === 'explicit_passage_link');
    const general = claims.filter(claim => !linked.includes(claim));
    if (passageId) {
      const section = addInspectorSection(`Claims linked to this passage · ${linked.length}`, host);
      section.append(node('p', 'candidate-reason', 'Only explicit source links to this passage appear here. A claim may still need editorial review.'));
      if (!linked.length) section.append(node('p', 'inspector-message', 'No accepted form claim is explicitly linked to this passage.'));
      linked.forEach(claim => section.append(renderClaim(claim)));
    }
    const section = addInspectorSection(`General source claims · ${general.length}`, host);
    section.append(node('p', 'candidate-reason', 'These concern a form or dictionary entry generally; they do not establish an occurrence here.'));
    if (!general.length) section.append(node('p', 'inspector-message', 'No general structured claims were returned.'));
    general.forEach(claim => section.append(renderClaim(claim)));
    if (Number(data.total) > claims.length) section.append(node('p', 'candidate-reason', `${data.total} claims matched; ${claims.length} shown in this preview.`));
    appendWarnings(host, data.warnings);
  }
  function candidateEntrySenses(candidate) {
    return (Array.isArray(candidate?.entry_senses) ? candidate.entry_senses : []).filter(sense =>
      sense?.scope === 'general_dictionary_entry' && typeof sense.entry_id === 'string' && sense.entry_id &&
      typeof sense.claim_id === 'string' && sense.claim_id &&
      [sense.raw_glosses, sense.glosses].some(values => Array.isArray(values) && values.some(value => typeof value === 'string' && value.trim())));
  }
  function packetCandidatesWithEntrySenses(packet) {
    return (Array.isArray(packet?.candidates) ? packet.candidates : []).map(candidate => {
      // Inline data remains authoritative, including an explicitly empty list.
      if (!candidate || Object.prototype.hasOwnProperty.call(candidate, 'entry_senses')) return candidate;
      const catalog = packet.entry_sense_catalog;
      if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog)) return candidate;
      const ids = Array.isArray(candidate.entry_sense_claim_ids) ? candidate.entry_sense_claim_ids : [];
      const senses = ids.filter(id => typeof id === 'string' && id && Object.prototype.hasOwnProperty.call(catalog, id))
        .map(id => catalog[id]?.claim_id === id ? catalog[id] : null).filter(Boolean);
      return { ...candidate, entry_senses: senses };
    });
  }
  function entrySenseGlosses(sense) {
    const strings = values => (Array.isArray(values) ? values : []).filter(value => typeof value === 'string' && value.trim());
    const qualified = strings(sense.raw_glosses);
    return qualified.length ? qualified : strings(sense.glosses);
  }
  function renderCandidateEntrySenses(host, candidate) {
    const senses = candidateEntrySenses(candidate);
    if (!senses.length) return false;
    host.append(node('p', 'candidate-meta-label', 'Source entry meaning'),
      node('p', 'candidate-gloss', entrySenseGlosses(senses[0])[0]));
    const details = node('details', 'entry-details');
    details.append(node('summary', '', `Dictionary senses and sources · ${senses.length}`),
      node('p', 'candidate-reason', 'General dictionary entry; no passage-specific meaning is selected.'));
    for (const sense of senses) {
      const row = node('div', 'candidate-entry-sense');
      for (const gloss of entrySenseGlosses(sense)) row.append(node('p', 'candidate-gloss', gloss));
      // Raw qualified glosses lead; retain any separately supplied source gloss too.
      for (const gloss of Array.isArray(sense.glosses) ? sense.glosses : []) {
        if (typeof gloss === 'string' && gloss.trim() && !entrySenseGlosses(sense).includes(gloss)) row.append(node('p', 'candidate-analysis', gloss));
      }
      const qualifiers = [sense.tags, sense.raw_tags].flatMap(values => Array.isArray(values) ? values : []).filter(value => typeof value === 'string' && value);
      if (qualifiers.length) row.append(node('p', 'candidate-reason', `Source labels: ${qualifiers.join(' · ')}`));
      if (sense.source_quality) row.append(node('p', 'candidate-reason', `Source quality: ${String(sense.source_quality).replaceAll('_', ' ')}`));
      const identity = [sense.entry_id, sense.claim_id, sense.source_sense_id, sense.locator].filter(value => typeof value === 'string' && value);
      row.append(node('p', 'candidate-reason', identity.join(' · ')));
      if (typeof sense.quote === 'string' && sense.quote) row.append(node('p', 'candidate-analysis', sense.quote));
      if (typeof sense.license === 'string' && sense.license) row.append(node('p', 'candidate-reason', sense.license));
      const link = safeLink(sense.source_url, 'Dictionary source ↗');
      if (link) row.append(link);
      details.append(row);
    }
    host.append(details);
    return true;
  }
  function renderSourceGrammarAlternatives(host, candidate) {
    const notices = {
      incomplete_explicit_alternatives: 'Not all source alternatives are indexed yet.',
      explicit_alternatives_represented: 'The source alternatives are indexed; no reading is selected here.',
      partial_with_explicit_alternatives: 'Partial analysis; the source alternatives remain open.'
    };
    const status = candidate?.source_projection_status;
    if (!Object.prototype.hasOwnProperty.call(notices, status)) return false;
    const notice = notices[status];
    const section = node('div', 'source-grammar-alternatives');
    section.append(node('p', 'candidate-meta-label', 'Source alternatives'),
      node('p', 'candidate-reason', notice));
    const proofs = Array.isArray(candidate.source_grammar_alternatives) ? candidate.source_grammar_alternatives : [];
    for (const proof of proofs) {
      if (!proof || typeof proof !== 'object') continue;
      if (typeof proof.source_text === 'string' && proof.source_text.trim()) {
        section.append(node('p', 'candidate-analysis', proof.source_text));
      } else {
        // Older/incomplete display packets can still carry printed branches.
        // Do not complete their features or invent connecting source words.
        for (const branch of Array.isArray(proof.branches) ? proof.branches : []) {
          if (typeof branch?.raw_label === 'string' && branch.raw_label.trim()) {
            section.append(node('p', 'candidate-analysis', branch.raw_label));
          }
        }
      }
      const link = safeLink(proof.source_url, 'Read source ↗');
      if (link) section.append(link);
    }
    host.append(section);
    return true;
  }
  function renderContextualCandidates(host, candidates, method) {
    if (!Array.isArray(candidates) || !candidates.length) return;
    const section = addInspectorSection(`Source candidate analyses · ${candidates.length}`, host);
    section.append(node('p', 'candidate-reason', method || 'Fields quoted or extracted from separate source claims; alternatives are retained.'));
    for (const candidate of candidates) {
      const row = node('div', 'candidate');
      row.append(node('div', 'candidate-lemma', candidate.lemma || candidate.equivalent_form || candidate.matched_form || 'Unlabeled candidate'));
      if (candidate.analysis) row.append(node('p', 'candidate-analysis', String(candidate.analysis)));
      if (candidate.features) row.append(node('p', 'candidate-analysis', formatFeatures(candidate.features)));
      renderCandidateEntrySenses(row, candidate);
      renderSourceGrammarAlternatives(row, candidate);
      if (candidate.equivalent_form) row.append(node('p', 'candidate-analysis', `Equivalent form: ${candidate.equivalent_form}`));
      row.append(node('p', 'candidate-reason', [candidate.strength?.replaceAll('_', ' '), candidate.source_family, candidate.match_reason].filter(Boolean).join(' · ')));
      if (candidate.status !== 'source_claim') row.append(node('p', 'claim-status', `Status: ${String(candidate.status || 'unreviewed').replaceAll('_', ' ')}`));
      section.append(row);
    }
  }
  function renderParallelContexts(host, comparisons) {
    if (!Array.isArray(comparisons) || !comparisons.length) return;
    const section = addInspectorSection('Commentary on matching wording', host);
    section.append(node('p', 'candidate-reason', 'These annotations belong to another source with the same complete word sequence. They are comparison evidence—not direct annotations of this edition. Editorial signs and source readings remain separate.'));
    for (const item of comparisons) {
      const card = node('div', 'parallel-context');
      card.append(node('p', 'candidate-meta-label', [item.passage?.edition, item.passage?.citation].filter(Boolean).join(' · ')));
      card.append(node('p', 'candidate-reason', `${item.alignment?.matched_words || 0} matching text tokens; local comparison window:`));
      card.append(node('p', 'candidate-analysis', item.alignment?.window || ''));
      for (const claim of item.claims || []) card.append(renderClaim({ ...claim, strength: 'parallel_matching_text', match_reason: item.alignment?.scope }));
      if (item.passage?.id) {
        const read = node('button', 'related-open', 'Read the annotated source →');
        read.type = 'button';
        read.addEventListener('click', () => openPassage(item.passage.id));
        card.append(read);
      }
      section.append(card);
    }
  }
  function candidatePreferenceLabel(candidate) {
    const parts = [candidate.lemma || candidate.matched_form || 'Unlabelled candidate'];
    const analysis = candidate.analysis_text || candidate.analysis;
    if (analysis) parts.push(Array.isArray(analysis) ? analysis.join(' · ') : typeof analysis === 'object' ? JSON.stringify(analysis) : String(analysis));
    if (candidate.features) parts.push(formatFeatures(candidate.features));
    if (candidate.equivalent_form) parts.push(`Equivalent form: ${candidate.equivalent_form}`);
    if (parts.length === 1) parts.push('No grammatical analysis supplied');
    const senses = candidateEntrySenses(candidate);
    if (senses.length) parts.push(`Source entry meaning: ${entrySenseGlosses(senses[0])[0]}`);
    return parts.filter(Boolean).join(' — ');
  }
  function addContextAction(host, form, passageId, sequence) {
    if (!passageId) return;
    const section = addInspectorSection('Contextual comparison', host);
    section.append(node('p', 'candidate-reason', 'A model may compare the existing candidates against this Greek passage. Its output is an interpretive proposal, not a new source claim.'));
    if (!state.classifierStatus?.configured) {
      section.append(node('p', 'inspector-message', state.classifierStatus?.reason || 'Contextual model comparison is not configured.'));
      return;
    }
    const button = node('button', 'classifier-action', 'Compare candidates with Jev');
    button.type = 'button';
    const output = node('div', 'classifier-output');
    section.append(button, output);
    button.addEventListener('click', async () => {
      if (sequence !== state.wordSequence || state.passageLoading || state.passage?.id !== passageId) return;
      button.disabled = true;
      message(output, 'Comparing candidates…');
      try {
        const result = await apiPost('/api/classify-context', { form, passage_id: passageId });
        if (sequence !== state.wordSequence) return;
        clear(output);
        const options = packetCandidatesWithEntrySenses(result.packet);
        const chosen = options.find(candidate => candidate.id === result.candidate_id);
        if (result.status === 'proposed' && chosen) {
          const title = chosen.lemma || chosen.matched_form || form;
          output.append(node('p', 'candidate-meta-label', 'Model proposal · interpretive only'));
          output.append(node('p', 'candidate-lemma', title));
          const description = [chosen.analysis_text || chosen.analysis, chosen.features ? formatFeatures(chosen.features) : '', chosen.equivalent_form ? `Equivalent form: ${chosen.equivalent_form} (source relation, not a complete parse)` : '', chosen.gloss].filter(Boolean).join(' · ');
          if (description) output.append(node('p', 'candidate-analysis', description));
          renderCandidateEntrySenses(output, chosen);
          if (chosen.match_reason) output.append(node('p', 'candidate-reason', chosen.match_reason));
          if (chosen.comparison_scope) output.append(node('p', 'warning', chosen.comparison_scope));
          output.append(node('p', 'candidate-reason', 'Other source candidates remain listed above. This proposal does not replace their source claims.'));
        } else {
          const outcome = result.decision_stage === 'model_abstained' ? 'Model abstained.'
            : result.decision_stage === 'preflight' ? 'Comparison not run; no model call was made.'
            : 'No usable model comparison was returned.';
          output.append(node('p', 'warning', `${outcome} ${result.reason || 'The available evidence did not support a selection.'}`));
        }
        if (result.model) output.append(node('p', 'candidate-reason', `Model: ${result.model}. ${result.reason || ''}`));
        if (result.cache_hit != null) output.append(node('p', 'candidate-reason', result.cache_hit
          ? 'Cached comparison for this passage and evidence; no new Jev call.'
          : 'New Jev comparison. Repeat lookups can reuse this result.'));
        const preference = result.model_probabilities_uncalibrated;
        const confidence = result.model_confidence_uncalibrated;
        if (preference != null || confidence != null) {
          const signal = node('div', 'model-signal');
          signal.append(node('p', 'candidate-reason', 'Raw model preference signals only; these are not calibrated probabilities of philological truth.'));
          if (confidence != null) signal.append(node('p', 'candidate-reason', `Raw model confidence signal: ${JSON.stringify(confidence)}`));
          if (preference != null) {
            const details = node('details', 'entry-details');
            details.append(node('summary', '', 'Show raw candidate preference values'));
            for (const [id, value] of Object.entries(preference)) {
              const candidate = options.find(option => option.id === id);
              const label = candidate ? candidatePreferenceLabel(candidate) : id === 'abstain' ? 'Abstain — no supported selection' : id;
              const row = node('div', 'candidate-preference');
              row.append(node('p', 'candidate-reason', `${label}: ${JSON.stringify(value)}`));
              if (candidate) {
                const provenance = node('details', 'entry-details');
                provenance.append(node('summary', '', 'Candidate identity and scope'));
                provenance.append(node('p', 'candidate-reason', id));
                provenance.append(node('p', 'candidate-reason', candidate.comparison_scope || candidate.match_reason || candidate.strength || 'Source scope not supplied'));
                renderCandidateEntrySenses(provenance, candidate);
                row.append(provenance);
              }
              details.append(row);
            }
            signal.append(details);
          }
          output.append(signal);
        }
        const technical = node('details', 'entry-details');
        technical.append(node('summary', '', 'Technical candidate and evidence IDs'));
        technical.append(node('p', 'candidate-reason', `Candidate: ${result.candidate_id || 'none'}`));
        if (Array.isArray(result.evidence_ids) && result.evidence_ids.length) technical.append(node('p', 'candidate-reason', `Linked evidence: ${result.evidence_ids.join(' · ')}`));
        output.append(technical);
        appendWarnings(output, result.warnings);
      } catch (error) {
        if (sequence === state.wordSequence) message(output, `Comparison unavailable: ${errorText(error)}`, 'warning error-message');
      } finally { if (sequence === state.wordSequence) button.disabled = false; }
    });
  }
  function renderFormInventories(host, data) {
    const groups = Array.isArray(data.observed_form_groups)
      ? data.observed_form_groups.filter(group => group && typeof group === 'object') : [];
    if (!groups.length) {
      if (Array.isArray(data.attested_forms) && data.attested_forms.length) {
        const section = addInspectorSection('Source lemma inventories unavailable', host);
        section.append(node('p', 'candidate-reason', 'The service returned an ungrouped form list without lemma-specific provenance. It is not displayed as forms of the selected word.'));
      }
      return;
    }
    const section = addInspectorSection(`Source lemma inventories · ${groups.length} groups`, host);
    section.append(node('p', 'candidate-reason', 'Forms recorded under each source lemma across indexed material—not a complete or dialect-specific paradigm, and not a list of attestations in the selected author or passage.'));
    for (const group of groups) {
      const forms = Array.isArray(group.forms) ? group.forms.filter(item => item && typeof item.form === 'string') : [];
      const total = Number.isInteger(group.total_forms) && group.total_forms >= forms.length ? group.total_forms : null;
      const count = total == null ? `${forms.length} forms shown; total not supplied` : `${forms.length} of ${total} forms shown`;
      const details = node('details', 'entry-details');
      const relationLabel = group.query_relation === 'spelling_suggestion' ? 'Nearby spelling'
        : group.query_relation === 'exact_or_folded_match' ? 'Matched source lemma' : 'Relationship unknown';
      const lemmaLabel = group.lemma_raw && group.lemma_raw !== group.lemma
        ? `${group.lemma || 'Unspecified lemma'} [${group.lemma_raw}]` : group.lemma || 'Unspecified lemma';
      details.append(node('summary', '', `${relationLabel}: ${lemmaLabel} · ${group.source || 'Unspecified source'} · ${count}`));
      const relation = group.query_relation === 'spelling_suggestion'
        ? 'Nearby-spelling suggestion only: this source lemma is not an analysis of the selected form.'
        : group.query_relation === 'exact_or_folded_match'
          ? 'Exact or normalized lookup candidate: the inventory belongs to this source lemma; it does not resolve the selected passage’s parse.'
          : 'Relationship to the selected form was not supplied; no query-form analysis is inferred.';
      details.append(node('p', 'candidate-reason', relation));
      if (group.lemma_raw && group.lemma_raw !== group.lemma) details.append(node('p', 'candidate-reason', `Source lemma spelling / identifier: ${group.lemma_raw}`));
      if (group.query_lemma_ambiguous) details.append(node('p', 'candidate-reason', 'The query has multiple lemma identities; choosing an inventory does not resolve the parse.'));
      if (group.identity_status === 'unnumbered_homograph_ambiguous') details.append(node('p', 'candidate-reason', 'Source lemma identity is ambiguous between homographs; these records do not establish a single resolved lemma.'));
      const matched = [...new Set((Array.isArray(group.matches) ? group.matches : []).flatMap(match => [match?.matched_form, ...(Array.isArray(match?.matched_form_variants) ? match.matched_form_variants : [])]).filter(value => typeof value === 'string' && value))];
      if (matched.length) details.append(node('p', 'candidate-reason', `Candidate source spellings: ${matched.join(' · ')}`));
      if (group.truncated || (total != null && forms.length < total)) details.append(node('p', 'candidate-reason', `Inventory preview is truncated: ${count}.`));
      if (!forms.length) details.append(node('p', 'inspector-message', 'No form records were included for this source lemma.'));
      for (const item of forms) {
        const row = node('div', 'occurrence');
        row.append(node('span', 'candidate-lemma', item.form));
        const refs = Array.isArray(item.source_refs) ? item.source_refs.filter(ref => ref && typeof ref === 'object') : [];
        const refTotal = Number.isInteger(item.source_ref_total) && item.source_ref_total >= refs.length ? item.source_ref_total : null;
        const refCount = refTotal == null ? `${refs.length} source references shown; total not supplied` : `${refs.length} of ${refTotal} source references shown`;
        const sources = node('details', 'entry-details');
        sources.append(node('summary', '', refCount));
        if (item.source_refs_truncated || (refTotal != null && refs.length < refTotal)) sources.append(node('p', 'candidate-reason', 'Source-reference preview is truncated.'));
        if (!refs.length) sources.append(node('p', 'candidate-reason', 'No per-form source references were supplied.'));
        for (const ref of refs) {
          const source = node('div', 'candidate');
          const link = safeLink(ref.source_url, `${ref.source || group.source || 'Source record'} ↗`);
          source.append(link || node('p', 'candidate-reason', `${ref.source || group.source || 'Source record'} · source URL unavailable`));
          renderSourceLocations(source, ref);
          if (ref.analysis) source.append(node('p', 'candidate-analysis', `Source analysis: ${ref.analysis}${ref.analysis_format ? ` (${ref.analysis_format})` : ''}`));
          if (ref.quality) source.append(node('p', 'candidate-reason', `Source quality label: ${ref.quality}`));
          if (ref.license) source.append(node('p', 'candidate-reason', `Source license label: ${ref.license}`));
          sources.append(source);
        }
        row.append(sources); details.append(row);
      }
      section.append(details);
    }
  }
  function renderSourceLocations(host, ref) {
    const locations = Array.isArray(ref.locations) ? ref.locations.filter(location => location && typeof location === 'object') : [];
    const total = Number.isInteger(ref.location_total) && ref.location_total >= locations.length ? ref.location_total : null;
    const count = total == null ? `${locations.length} source location records shown; total not supplied` : `${locations.length} of ${total} source location records shown`;
    const container = locations.length > 1 ? node('details', 'entry-details') : node('div');
    container.append(node(locations.length > 1 ? 'summary' : 'p', 'candidate-reason', count));
    if (ref.locations_truncated || (total != null && locations.length < total)) container.append(node('p', 'candidate-reason', 'Source-location preview is truncated.'));
    if (!locations.length) container.append(node('p', 'candidate-reason', 'No precise locator supplied.'));
    for (const location of locations) {
      const fields = [['document_id', 'Document'], ['sentence_id', 'Sentence'], ['token_id', 'Token']];
      const coordinates = fields.filter(([key]) => ['string', 'number'].includes(typeof location[key]) && String(location[key]).trim())
        .map(([key, title]) => `${title}: ${location[key]}`);
      const identifiers = coordinates.length ? `Source identifiers · ${coordinates.join(' · ')}` : '';
      const hasCitation = typeof location.citation === 'string' && location.citation.trim();
      const label = hasCitation ? `Source citation: ${location.citation}` : identifiers || 'No precise locator supplied.';
      const line = node('p', 'candidate-analysis', label);
      // CTS URNs and source document identifiers can be long unbroken strings.
      line.style.overflowWrap = 'anywhere';
      container.append(line);
      if (hasCitation && identifiers) {
        const coordinatesLine = node('p', 'candidate-reason', identifiers);
        coordinatesLine.style.overflowWrap = 'anywhere';
        container.append(coordinatesLine);
      }
    }
    host.append(container);
  }
  function renderLexicalEvidence(host, evidence, passageId) {
    const hits = (Array.isArray(evidence?.hits) ? evidence.hits : []).filter(hit =>
      hit.scope === 'dictionary_quotation_not_morphological_parse' &&
      hit.passage_id === passageId && passageId && hit.quote);
    if (!hits.length) return false;
    const section = addInspectorSection('Dictionary quotations matching this passage', host);
    section.append(node('p', 'candidate-reason', 'The dictionary quotes this wording. Its entry and sense are shown below; this does not identify every quoted word as a form of the headword.'));
    for (const hit of hits) {
      const card = node('div', 'candidate');
      if (hit.lemma) card.append(node('div', 'candidate-lemma', hit.lemma));
      if (hit.source_gloss) card.append(node('span', 'candidate-meta-label', 'Source sense excerpt'), node('p', 'candidate-gloss', hit.source_gloss));
      card.append(node('blockquote', 'dictionary-quotation', hit.quote));
      if (hit.citation) card.append(node('p', 'candidate-reason', hit.citation));
      const source = safeLink(hit.entry_url || hit.source_url, 'Read dictionary source ↗');
      if (source) card.append(source);
      const provenance = node('details', 'entry-details');
      provenance.append(node('summary', '', 'Quotation provenance'));
      for (const [label, value] of [['Source', hit.source], ['Entry', hit.entry_id], ['Sense', hit.sense_id],
        ['Source locator', hit.source_locator], ['Source SHA-256', hit.raw_sha256], ['Matching method', hit.match_method],
        ['Passage quality', hit.passage_quality]]) {
        if (value) provenance.append(node('p', 'candidate-reason', `${label}: ${value}`));
      }
      if (hit.raw_quote) provenance.append(node('p', 'candidate-reason', `${hit.raw_quote_encoding || 'Source quotation encoding'}: ${hit.raw_quote}`));
      card.append(provenance);
      section.append(card);
    }
    if (evidence.coverage) section.append(node('p', 'candidate-reason', evidence.coverage));
    for (const warning of (Array.isArray(evidence.warnings) ? evidence.warnings : [])) {
      if (typeof warning === 'string') section.append(node('p', 'candidate-reason', warning));
    }
    if (evidence.entries_truncated || evidence.hits_truncated) section.append(node('p', 'candidate-reason', 'Only the bounded preview is shown; additional entries or quotations were not checked or displayed.'));
    return true;
  }
  function candidateDictionaryExcerpt(candidate, entries) {
    const linked = typeof candidate.gloss_entry_id === 'string' && candidate.gloss_entry_id
      ? (Array.isArray(entries) ? entries : []).filter(entry => entry?.id === candidate.gloss_entry_id) : [];
    const clause = linked.length === 1 ? window.MelosDictionaryPreview?.definitionExcerpt?.(linked[0]) : null;
    return clause || { text: candidate.gloss, provenance: null };
  }
  async function inspectWord(form, button = null, joined = false, fragmentSegment = false) {
    if (!form) return;
    if (button && (state.passageLoading || !state.passage?.id || !ui.text.contains(button))) return;
    for (const active of ui.text.querySelectorAll('.word.active')) active.classList.remove('active');
    state.activeWord = button;
    if (button) {
      for (const part of ui.text.querySelectorAll('.word')) {
        if (part.dataset.lookupGroup === button.dataset.lookupGroup) part.classList.add('active');
      }
    }
    const passageId = button ? state.passage?.id : '';
    state.machineAnalysisCancel?.();
    clear(ui.inspector);
    ui.inspector.append(node('span', 'eyebrow', fragmentSegment ? 'PRINTED SEGMENT' : 'SELECTED FORM'), node('div', 'word-title', form));
    if (joined) ui.inspector.append(node('p', 'word-normalized', 'Lookup joins an explicit printed line-end division. Both printed segments remain unchanged in the passage; no missing letters are supplied.'));
    if (fragmentSegment) ui.inspector.append(node('p', 'warning', 'Printed segment of an editorially marked or uncertain line-divided span. No complete word has been reconstructed. Dictionary matches concern this literal string, not necessarily the source word; computational and Jev analysis are unavailable for this segment.'));
    if (form.includes('\u1fbf')) ui.inspector.append(node('p', 'word-normalized', 'Printed spacing mark retained; not silently treated as an apostrophe.'));
    if (!passageId) ui.inspector.append(node('p', 'word-normalized', 'Standalone form lookup · no passage context supplied.'));
    const machineHost = node('div', 'machine-panel');
    const morphologyHost = node('div', 'morphology-panel');
    const wiktionaryHost = node('div', 'wiktionary-panel');
    ui.inspector.append(machineHost, morphologyHost, wiktionaryHost);
    const pending = node('p', 'inspector-message', 'Looking up recorded analyses…');
    morphologyHost.append(pending);
    const sequence = ++state.wordSequence;
    if (!fragmentSegment && window.MelosMachineMorphology) state.machineAnalysisCancel = window.MelosMachineMorphology.mount({
      host: machineHost, form, passageId, node, safeLink, post: apiPost,
      current: () => sequence === state.wordSequence && !state.passageLoading && (!passageId || state.passage?.id === passageId),
      classifierReady: () => Boolean(state.classifierStatus?.configured),
    });
    const wikiPreview = loadWiktionary(form, sequence, wiktionaryHost);
    if (button && window.matchMedia('(max-width:1280px)').matches) {
      requestAnimationFrame(() => ui.inspector.closest('.inspector').scrollIntoView({ behavior: 'smooth', block: 'start' }));
    }
    try {
      const data = await api('/api/word', { form, passage_id: passageId });
      if (sequence !== state.wordSequence) return;
      pending.remove();
      if (data.normalized && data.normalized !== form) morphologyHost.append(node('p', 'word-normalized', `Normalized search: ${data.normalized}`));
      const glimpse = node('div');
      morphologyHost.append(glimpse);
      renderDictionaryPreview(glimpse, data, { openEntries: false });
      wikiPreview.then(wiktionary => {
        if (!wiktionary || sequence !== state.wordSequence) return;
        clear(glimpse);
        renderDictionaryPreview(glimpse, data, { openEntries: false, wiktionary });
      });
      const hasQuotation = renderLexicalEvidence(morphologyHost, data.lexical_evidence, passageId);
      renderStructuredEvidence(morphologyHost, data.structured_evidence, passageId);
      renderParallelContexts(morphologyHost, data.parallel_contexts);
      renderContextualCandidates(morphologyHost, data.contextual_candidates, data.contextual_candidate_method);
      if (passageId) renderRelatedCommentary(form, state.passage?.related, morphologyHost);
      const onlyNearby = data.analysis_match_status === 'spelling_suggestions_only'
        && !data.contextual_candidates?.length && !data.parallel_contexts?.some(item => item.candidates?.length);
      if (!fragmentSegment) {
        if (onlyNearby) morphologyHost.append(node('p', 'candidate-reason', 'Only nearby spellings were found in the source lookup. Use Analyze this form for separate computational alternatives.'));
        else addContextAction(morphologyHost, form, passageId, sequence);
      }
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      const analysisTitle = data.analysis_match_status === 'spelling_suggestions_only'
        ? 'Nearby spelling analyses'
        : candidates.length === 1 ? 'Recorded analysis' : 'Possible analyses';
      const hasLinkedSource = (data.contextual_candidates || []).some(candidate => candidate.strength === 'explicit_passage_span' || candidate.strength === 'explicit_passage_link');
      const collapseNearby = (hasLinkedSource || hasQuotation) && data.analysis_match_status === 'spelling_suggestions_only';
      const analysisHost = collapseNearby ? node('details', 'entry-details nearby-analysis') : morphologyHost;
      if (collapseNearby) {
        analysisHost.append(node('summary', '', `Nearby spelling analyses · ${candidates.length} other forms`));
        morphologyHost.append(analysisHost);
      }
      const analysis = addInspectorSection(collapseNearby ? 'General lexicon / treebank lookup' : analysisTitle, analysisHost);
      appendWarnings(analysis, data.warnings);
      if (!candidates.length) analysis.append(node('p', 'inspector-message', 'No sourced dictionary or morphology analysis is available for this form.'));
      for (const candidate of candidates) {
        const card = node('div', 'candidate');
        if (candidate.lemma) card.append(node('div', 'candidate-lemma', candidate.lemma));
        const definition = candidateDictionaryExcerpt(candidate, data.lexicon_entries);
        if (definition.text) card.append(node('span', 'candidate-meta-label', definition.provenance ? 'Source definition excerpt' : 'Dictionary excerpt'), node('p', 'candidate-gloss', definition.text));
        if (candidate.analysis_text) {
          const parse = node('p', 'candidate-analysis', candidate.analysis_text);
          if (candidate.analysis) parse.title = `Source analysis: ${candidate.analysis}${candidate.analysis_format ? ` (${candidate.analysis_format})` : ''}`;
          card.append(parse);
        } else if (candidate.analysis) card.append(node('p', 'candidate-analysis', `${candidate.analysis}${candidate.analysis_format ? ` (${candidate.analysis_format})` : ''}`));
        renderSourceGrammarAlternatives(card, candidate);
        if (candidate.matched_form && candidate.matched_form !== form) card.append(node('p', 'candidate-reason', `Matched source spelling: ${candidate.matched_form}`));
        else if (candidate.attested_form && candidate.attested_form !== form) card.append(node('p', 'candidate-reason', `Recorded form: ${candidate.attested_form}`));
        if (candidate.reason) card.append(node('p', 'candidate-reason', candidate.reason));
        const entryText = candidate.rendered_entry_text || candidate.entry_text;
        if (entryText) {
          const details = node('details', 'entry-details');
          details.append(node('summary', '', candidate.rendered_entry_text ? 'Read source entry' : 'Read source entry · original encoding'), node('p', '', entryText));
          if (!candidate.rendered_entry_text) details.append(node('p', 'candidate-reason', 'Entry text is shown in its source encoding; Beta Code may appear.'));
          card.append(details);
        }
        const link = safeLink(candidate.source_url, 'Analysis source ↗');
        if (link) card.append(link);
        const glossLink = safeLink(candidate.gloss_source_url, 'Gloss source ↗');
        if (glossLink) card.append(glossLink);
        for (const supporting of (candidate.supporting_sources || []).slice(0, 5)) {
          if (supporting.source_url === candidate.source_url) continue;
          const supportLink = safeLink(supporting.source_url, `${supporting.source || 'Additional source'} ↗`);
          if (supportLink) card.append(supportLink);
        }
        analysis.append(card);
      }
      renderFormInventories(morphologyHost, data);
      const found = renderOccurrencePreview(morphologyHost, data);
      const fullSearch = node('button', 'occurrence-search', 'Search all indexed occurrences ↗');
      fullSearch.type = 'button';
      fullSearch.title = 'Searches every indexed record, including reference material; clears the current author, edition, and language filters.';
      fullSearch.addEventListener('click', () => {
        ui.searchInput.value = form;
        ui.authorFilter.value = '';
        ui.edition.value = '';
        ui.language.value = '';
        ui.reference.checked = true;
        ui.order.value = 'relevance';
        setFormMode('exact');
        search(form, 'exact');
      });
      found.append(fullSearch);
      if (data.method) morphologyHost.append(node('p', 'candidate-reason', `Lookup method: ${String(data.method).replaceAll('_', ' ')}`));
    } catch (error) {
      if (sequence === state.wordSequence) message(morphologyHost, `Word lookup unavailable: ${errorText(error)}`, 'warning error-message');
    }
  }
  function updateSelectionTranslationAction() {
    let button = ui.selectionActions.querySelector('.selection-translation');
    const available = passageTranslationPreviews(state.passage).length > 0;
    if (!available) { if (button) button.hidden = true; return; }
    if (!button) {
      button = node('button', 'selection-translation', 'Containing passage translation');
      button.type = 'button';
      button.title = 'Read the published translation of the complete containing passage; it is not aligned to this selection.';
      button.addEventListener('click', () => {
        if (state.passageLoading || !state.selectedText || !passageTranslationPreviews(state.passage).length) return;
        const section = ui.related.querySelector('.published-translations');
        const full = section?.querySelector('.translation-full');
        if (full) full.open = true;
        section?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      ui.selectionActions.append(button);
    }
    button.hidden = false;
  }
  function selectedPassageText(selection, root) {
    if (!selection || selection.rangeCount !== 1) return '';
    const range = selection.getRangeAt(0);
    if (range.collapsed || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return '';
    // Read the ORIGINAL nodes, not cloneContents(): a range wholly inside a
    // label would clone a bare text node and lose its metadata ancestry.
    const walker = root.ownerDocument.createTreeWalker(root, 4); // SHOW_TEXT
    const pieces = [];
    let previousBlock = null;
    while (walker.nextNode()) {
      const text = walker.currentNode;
      if (text.parentElement?.closest('.line-label') || !range.intersectsNode(text)) continue;
      const start = text === range.startContainer ? range.startOffset : 0;
      const end = text === range.endContainer ? range.endOffset : text.data.length;
      const selected = text.data.slice(start, end);
      if (!selected) continue;
      const block = text.parentElement?.closest('.line, p') || null;
      if (pieces.length && block !== previousBlock) pieces.push('\n');
      pieces.push(selected);
      previousBlock = block;
    }
    return pieces.join('');
  }
  function updateSelection() {
    ui.selectionActions.classList.remove('selection-too-long');
    if (state.passageLoading || !state.passage) {
      state.selectedText = ''; ui.selectedPhrase.textContent = ''; ui.selectionActions.hidden = true;
      return;
    }
    const selection = window.getSelection();
    const anchor = selection?.anchorNode;
    const focus = selection?.focusNode;
    const inside = anchor && focus && ui.text.contains(anchor) && ui.text.contains(focus);
    const phrase = inside ? selectedPassageText(selection, ui.text).replace(/\s+/g, ' ').trim() : '';
    const length = [...phrase].length; // Match the backend's Unicode-codepoint query limit.
    if (!inside || length < 2) {
      state.selectedText = ''; ui.selectedPhrase.textContent = ''; ui.selectionActions.hidden = true; return;
    }
    if (length > 1000) {
      state.selectedText = '';
      ui.selectionActions.classList.add('selection-too-long');
      ui.selectedPhrase.textContent = 'Select up to 1,000 characters to search a passage. This selection has not been shortened or sent.';
      ui.selectionActions.hidden = false;
      for (const button of ui.selectionActions.querySelectorAll('button')) button.disabled = true;
      return;
    }
    state.selectedText = phrase;
    ui.selectedPhrase.textContent = `“${phrase}”`;
    ui.selectionActions.hidden = false;
    updateSelectionTranslationAction();
    for (const button of ui.selectionActions.querySelectorAll('button')) button.disabled = false;
  }
  async function initialize() {
    if (window.MELOS_FRONTEND_ONLY === true) {
      ui.status.textContent = 'Frontend preview · corpus service not connected';
      ui.bridgeNote.textContent = 'Search will become available when the hosted corpus service is connected.';
      message(ui.authors, 'Poets and works will appear when the corpus service is connected.');
      ui.authorCount.textContent = 'Not connected';
      renderPassageEmpty('The reader is ready for its corpus connection. No research data or sample search results are served in this frontend preview.');
      ui.title.textContent = 'The reading desk';
      ui.readingHint.textContent = 'Passages, word analyses, and usage comparisons require the corpus service.';
      message(ui.inspector, 'Source-backed word analyses will appear here once the corpus service is connected.');
      for (const control of [ui.authorFilter, ui.edition, ui.language, ui.order, ui.reference, ui.usage, ui.lookupForm]) control.disabled = true;
      document.querySelectorAll('input[name="search-mode"]').forEach(control => { control.disabled = true; });
      return;
    }
    const settled = await Promise.allSettled([api('/api/status'), api('/api/authors'), api('/api/works')]);
    if (settled[0].status === 'fulfilled') renderStatus(settled[0].value);
    else ui.status.textContent = `Corpus status unavailable: ${errorText(settled[0].reason)}`;
    if (settled[2].status === 'fulfilled' && Array.isArray(settled[2].value.works)) {
      const works = settled[2].value.works;
      for (const work of works) {
        if (!state.works.has(work.author)) state.works.set(work.author, []);
        state.works.get(work.author).push(work);
      }
      updateEditionOptions(works);
    }
    if (settled[1].status !== 'fulfilled') {
      message(ui.authors, `Could not load authors: ${errorText(settled[1].reason)}`, 'warning error-message');
      renderPassageEmpty('The corpus service is unavailable. Please try again when the index is running.', true);
      return;
    }
    state.authors = Array.isArray(settled[1].value.authors) ? settled[1].value.authors : [];
    updateAuthorOptions();
    renderAuthors();
    const params = new URL(location.href).searchParams;
    const saved = restoreSearchUrl(params);
    if (saved.issues.length) {
      ui.results.hidden = false;
      ui.resultsHeading.textContent = 'Search link needs attention';
      ui.resultsSummary.textContent = saved.issues.join(' ');
      ui.moreResults.hidden = true;
    } else if (saved.query) search(saved.query, saved.mode);
    if (params.get('id')) { await openPassage(params.get('id'), false); return; }
    if (saved.query || saved.issues.length) return;
    const preferred = state.authors.find(a => /sappho/i.test(a.author || ''))
      || state.authors.find(a => /pindar/i.test(a.author || ''))
      || state.authors.find(a => /bacchylides/i.test(a.author || ''))
      || state.authors[0];
    if (preferred) await selectAuthor(preferred.author, true);
    else renderPassageEmpty('The corpus has no indexed authors yet.');
  }

  ui.searchForm.addEventListener('submit', event => { event.preventDefault(); search(ui.searchInput.value); });
  for (const radio of document.querySelectorAll('input[name="search-mode"]')) radio.addEventListener('change', updateBridgeNote);
  ui.browseToggle.addEventListener('click', () => {
    const open = ui.browseToggle.getAttribute('aria-expanded') !== 'true';
    ui.browseToggle.setAttribute('aria-expanded', String(open));
    ui.browseBody.classList.toggle('open', open);
  });
  ui.prev.addEventListener('click', () => openPassage(state.passage?.previous_id));
  ui.next.addEventListener('click', () => openPassage(state.passage?.next_id));
  ui.closeResults.addEventListener('click', () => { ui.results.hidden = true; ui.passage.scrollIntoView({ behavior: 'smooth' }); });
  ui.moreResults.addEventListener('click', () => { if (state.search) search(state.search.query, state.search.mode, true); });
  for (const control of [ui.authorFilter, ui.edition, ui.language, ui.order, ui.reference]) control.addEventListener('change', () => {
    if (state.search && !ui.results.hidden) search(state.search.query, state.search.mode);
  });
  ui.usage.addEventListener('click', () => {
    const query = ui.searchInput.value.trim() || state.selectedText || state.activeWord?.textContent?.trim() || '';
    const snapshot = usageSnapshot(query);
    if (!snapshot.q) {
      ui.searchInput.placeholder = 'Enter a word or theme to explore its usage…';
      ui.searchInput.focus();
      return;
    }
    if (window.MelosUsageSpace?.open) window.MelosUsageSpace.open(snapshot.q, snapshot.author, snapshot);
    else message(ui.inspector, 'The usage view is unavailable on this page.', 'warning error-message');
  });
  ui.lookupForm.addEventListener('click', () => {
    const form = ui.searchInput.value.trim();
    if (!form) {
      ui.searchInput.placeholder = 'Enter a Greek form or transliteration to look up…';
      ui.searchInput.focus();
      return;
    }
    if (formMode() === 'themes') {
      message(ui.inspector, 'Choose Words or Forms before looking up a Greek form. A theme description is not a dictionary form.', 'warning');
      ui.lookupForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    inspectWord(form);
    ui.lookupForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  ui.backToPassage.addEventListener('click', () => {
    const target = state.activeWord?.isConnected ? state.activeWord : ui.passage;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (target === state.activeWord) target.focus({ preventScroll: true });
  });
  for (const button of ui.selectionActions.querySelectorAll('[data-phrase-mode]')) button.addEventListener('click', () => {
    if (state.passageLoading || !state.passage || !state.selectedText) return;
    const mode = button.dataset.phraseMode;
    ui.searchInput.value = state.selectedText;
    setFormMode(mode);
    search(state.selectedText, mode);
  });
  document.addEventListener('selectionchange', () => requestAnimationFrame(updateSelection));
  initialize();
})();
