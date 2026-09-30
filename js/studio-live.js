// Live corpus content for the original Melos painting studio.
// Paintings and dither controls remain in app.js; no sample lexicon is loaded.
const $ = selector => document.querySelector(selector);
const queryInput = $('#q');
const resultList = $('#results');
const entry = $('#entry');
const count = $('#count');
const notes = $('#search-notes');
const timeline = $('#timeline');
const POETS = [
  ['Archilochus', 'Ἀρχίλοχος'], ['Alcman', 'Ἀλκμάν'],
  ['Sappho', 'Σαπφώ'], ['Alcaeus', 'Ἀλκαῖος'],
  ['Stesichorus', 'Στησίχορος'], ['Ibycus', 'Ἴβυκος'],
  ['Anacreon', 'Ἀνακρέων'], ['Simonides', 'Σιμωνίδης'],
  ['Pindar', 'Πίνδαρος'], ['Bacchylides', 'Βακχυλίδης'],
];
let selectedAuthor = '', requestSequence = 0, records = [], selectedId = '';

function el(tag, className = '', content = '') {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content != null) element.textContent = String(content);
  return element;
}
function sourceLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    const link = el('a', '', label);
    link.href = parsed.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch { return null; }
}
function readerLink(record) {
  const link = el('a', 'studio-reader-link', 'Read with source evidence ↗');
  link.href = `./?${new URLSearchParams({ id: record.id })}`;
  return link;
}
function setMessage(text) {
  entry.replaceChildren(el('p', 'note', text));
}
function titleFor(record) {
  return [record.author, record.work].filter(Boolean).join(' · ') || 'Source record';
}
function renderEntry(record) {
  selectedId = record?.id || '';
  resultList.querySelectorAll('button').forEach(button => button.setAttribute('aria-current', String(button.dataset.id === selectedId)));
  if (!record) { setMessage('Enter a Greek word, Beta Code, citation, or English description to search the live corpus.'); return; }
  entry.replaceChildren();
  entry.append(el('h3', '', titleFor(record)));
  entry.append(el('p', 'meta', [record.citation, record.edition].filter(Boolean).join(' · ')));
  const kind = record.kind || 'text', language = record.language || 'unspecified', quality = record.quality || 'unspecified';
  const label = el('p', 'studio-source-label', `${kind} · ${language} · ${quality.replaceAll('_', ' ')}`);
  entry.append(label);
  const text = record.text || 'Source text unavailable.';
  const body = el('div', 'studio-source-text');
  if (language === 'grc') body.lang = 'grc';
  // One source line per visual line; the type shrinks to fit (js/verse-fit.js).
  if (text.includes('\n') || (kind === 'text' && language === 'grc' && text.length <= 200)) {
    body.classList.add('verse-fit');
    for (const line of text.split('\n')) body.append(el('span', line.trim() ? 'line' : 'line blank', line.trim()));
    entry.append(body);
    window.MelosVerseFit?.watch(body, '.line');
  } else {
    body.textContent = text;
    entry.append(body);
  }
  if (record.match_reason) entry.append(el('p', 'note', `Retrieval: ${record.match_reason}`));
  const evidence = Array.isArray(record.matched_evidence) ? record.matched_evidence : [];
  if (evidence.length) {
    const details = el('details', 'studio-evidence');
    details.append(el('summary', '', `${evidence.length} retrieval source${evidence.length === 1 ? '' : 's'} · rank is not confidence`));
    for (const hit of evidence.slice(0, 8)) {
      const item = el('p', '', [hit.signal, hit.kind, hit.author, hit.citation, hit.match_reason].filter(Boolean).join(' · '));
      const link = sourceLink(hit.source_url, ' Source ↗');
      if (link) item.append(link);
      details.append(item);
    }
    entry.append(details);
  }
  const actions = el('p', 'studio-actions');
  actions.append(readerLink(record));
  const original = sourceLink(record.source_url, 'Original source ↗');
  if (original) actions.append(original);
  entry.append(actions);
  if (Number(record.mirror_count) > 1) entry.append(el('p', 'note', `${record.mirror_count - 1} identical ${record.mirror_count === 2 ? 'copy' : 'copies'} of this text collapsed into this result.`));
  if (quality === 'machine_corrected_ocr') entry.append(el('p', 'note', 'Machine-corrected OCR of a printed edition; compare with the scan before quoting.'));
  else if (quality !== 'source_text') entry.append(el('p', 'note', 'This record may include OCR or reference material; inspect its collection and source before using it as ancient text.'));
}
function renderRecords(items, summary) {
  records = items;
  resultList.replaceChildren();
  count.textContent = summary;
  if (!items.length) {
    resultList.append(el('li', 'empty', 'No source records found'));
    setMessage('Try another spelling, a poet, or a broader English description.');
    return;
  }
  for (const record of items) {
    const item = el('li');
    const button = el('button');
    button.type = 'button';
    button.dataset.id = record.id;
    button.append(el('span', 'lm', record.citation || record.author || 'Source record'));
    button.append(el('span', 'gl', `${record.author || 'Unattributed'} · ${(record.text || '').replace(/\s+/g, ' ').slice(0, 82)}`));
    button.addEventListener('click', () => {
      renderEntry(record);
      if (matchMedia('(max-width: 820px)').matches) entry.scrollIntoView({ block: 'start' });
    });
    item.append(button);
    resultList.append(item);
  }
  renderEntry(items.find(item => item.id === selectedId) || items[0]);
}
async function request(path, params = {}) {
  const url = window.melosApiUrl(path);
  for (const [key, value] of Object.entries(params)) {
    if (value !== '' && value != null) url.searchParams.set(key, String(value));
  }
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Corpus API returned ${response.status}.`);
  return response.json();
}
function errorMessage(error) {
  return `The corpus service is unavailable. ${error instanceof Error ? error.message : String(error)}`;
}
function showWarnings(warnings) {
  const list = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
  notes.hidden = !list.length;
  notes.textContent = list.length ? `Search notes: ${list.slice(0, 2).join(' ')}` : '';
}
async function search(query) {
  const sequence = ++requestSequence;
  const value = String(query || '').trim();
  if (!value) { await browseAuthor(selectedAuthor || 'Sappho'); return; }
  count.textContent = `Searching the live corpus for “${value}”…`;
  try {
    const response = await request('/api/search', { q: value, mode: 'words', author: selectedAuthor, match: 'fuzzy', limit: 30 });
    if (sequence !== requestSequence) return;
    const items = Array.isArray(response.results) ? response.results : [];
    const scope = selectedAuthor ? ` in ${selectedAuthor}` : '';
    renderRecords(items, `${Number(response.total || 0).toLocaleString()} word matches${scope} · ${items.length} shown`);
    showWarnings(response.warnings);
  } catch (error) {
    if (sequence !== requestSequence) return;
    showWarnings([]);
    renderRecords([], errorMessage(error));
    setMessage(errorMessage(error));
  }
}
async function browseAuthor(author) {
  const sequence = ++requestSequence;
  selectedAuthor = author;
  showWarnings([]);
  count.textContent = `Opening ${author} in the live corpus…`;
  try {
    const works = await request('/api/works', { author });
    if (sequence !== requestSequence) return;
    const choices = Array.isArray(works.works) ? works.works : [];
    const work = choices.find(item => item.language === 'grc') || choices[0];
    if (!work) { renderRecords([], `No indexed works for ${author}.`); return; }
    const response = await request('/api/passages', { work_id: work.id, limit: 30 });
    if (sequence !== requestSequence) return;
    const items = (response.results || []).filter(item => item.kind === 'text' && item.language === 'grc' && item.quality === 'source_text').slice(0, 15);
    renderRecords(items, `${author} · ${work.work || 'source work'} · ${items.length} source passages shown`);
  } catch (error) {
    if (sequence !== requestSequence) return;
    renderRecords([], errorMessage(error));
    setMessage(errorMessage(error));
  }
}
async function populatePoets() {
  try {
    const data = await request('/api/authors');
    const authors = Array.isArray(data.authors) ? data.authors : [];
    timeline.replaceChildren();
    for (const [name, greek] of POETS) {
      const profile = authors.find(item => String(item.author).toLowerCase() === name.toLowerCase())
        || authors.find(item => String(item.author).toLowerCase().startsWith(`${name.toLowerCase()} of `));
      const authorLabel = profile?.author || name;
      const li = el('li', profile ? 'has' : '');
      const button = el('button'); button.type = 'button';
      const gr = el('span', 'nm', greek); gr.lang = 'grc';
      button.append(gr, el('span', 'en', name), el('span', 'dt', profile ? `${Number(profile.count || 0).toLocaleString()} indexed records` : 'No source label indexed'));
      button.addEventListener('click', () => {
        selectedAuthor = authorLabel;
        if (queryInput.value.trim()) search(queryInput.value); else browseAuthor(authorLabel);
        $('#lexicon').scrollIntoView();
      });
      li.append(button); timeline.append(li);
    }
  } catch (error) {
    timeline.replaceChildren(el('li', 'empty', errorMessage(error)));
  }
}

$('#search').addEventListener('submit', event => {
  event.preventDefault();
  selectedAuthor = '';
  search(queryInput.value);
  $('#lexicon').scrollIntoView();
});
queryInput.addEventListener('input', () => {
  // The backend combines several bounded indexes. Submit to run one deliberate query.
  if (!queryInput.value.trim()) count.textContent = 'Press Search to browse the live corpus.';
});
if (window.MELOS_FRONTEND_ONLY === true) {
  count.textContent = 'Frontend preview · corpus service not connected';
  setMessage('Search and source passages will become available when the hosted corpus service is connected.');
  timeline.replaceChildren(el('li', 'empty', 'Poets and works require the corpus connection.'));
} else {
  populatePoets();
  browseAuthor('Sappho');
}
