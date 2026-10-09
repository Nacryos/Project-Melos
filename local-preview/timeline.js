// Local-only presentation experiment. The production reader remains the sole
// implementation of dictionary, selection, parsing, retrieval and source views.
// Poet spellings and dates copied from the existing js/app.js POETS constant.
const POETS = [
  { en: 'Archilochus', gr: 'Ἀρχίλοχος', dt: 'c. 680–645' },
  { en: 'Alcman', gr: 'Ἀλκμάν', dt: 'late 7th c.' },
  { en: 'Sappho', gr: 'Σαπφώ', dt: 'b. c. 630' },
  { en: 'Alcaeus', gr: 'Ἀλκαῖος', dt: 'c. 625–580' },
  { en: 'Stesichorus', gr: 'Στησίχορος', dt: 'c. 630–555' },
  { en: 'Ibycus', gr: 'Ἴβυκος', dt: 'mid 6th c.' },
  { en: 'Anacreon', gr: 'Ἀνακρέων', dt: 'c. 570–485' },
  { en: 'Simonides', gr: 'Σιμωνίδης', dt: 'c. 556–468' },
  { en: 'Pindar', gr: 'Πίνδαρος', dt: 'c. 518–438' },
  { en: 'Bacchylides', gr: 'Βακχυλίδης', dt: 'c. 518–451' },
];
const $ = selector => document.querySelector(selector);
const arrow = '<svg class="row-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const make = (tag, className = '', text = '') => { const node = document.createElement(tag); node.className = className; node.textContent = text; return node; };
let actionSequence = 0;
let savedScroll = 0;

function status(message = '') { $('#page-status').hidden = !message; $('#page-status').textContent = message; }
function showPoets() {
  actionSequence++;
  $('#reading-room').hidden = true;
  $('#landing').hidden = false;
  document.body.classList.remove('in-reading-room');
  $('#painting-hero').hidden = false;
  status();
  history.replaceState(null, '', location.pathname);
  window.scrollTo({ top: savedScroll, behavior: 'instant' });
}
function readerUrl(values = {}) {
  const url = new URL('../reader.html', document.baseURI);
  for (const [key, value] of Object.entries(values)) if (value !== '' && value != null) url.searchParams.set(key, value);
  url.hash = values.id ? 'passage' : 'reader';
  return url;
}
function openReader(values = {}, title = 'Reading room') {
  if (!$('#landing').hidden) savedScroll = window.scrollY;
  $('#landing').hidden = true;
  $('#reading-room').hidden = false;
  document.body.classList.add('in-reading-room');
  $('#painting-hero').hidden = true;
  $('#room-title').textContent = title;
  const url = readerUrl(values);
  $('#standalone-reader').href = url.href;
  $('#reader-frame').src = url.href;
  history.replaceState(null, '', `${location.pathname}#reading-room`);
  window.scrollTo({ top: 0, behavior: 'instant' });
  status();
}
async function api(path, values) {
  const url = new URL(path, location.origin);
  for (const [key, value] of Object.entries(values || {})) url.searchParams.set(key, value);
  const response = await fetch(url, { signal: AbortSignal.timeout(35000) });
  if (!response.ok) throw new Error(`Corpus request returned ${response.status}`);
  return response.json();
}
async function openPoet(poet) {
  const sequence = ++actionSequence;
  status(`Opening ${poet.en}…`);
  try {
    const data = await api('/api/works', { author: poet.en });
    const works = (data.works || []).filter(work => work.language === 'grc');
    // Prefer a Greek work, but don't invent a passage or pass an unsupported
    // author parameter to /api/passages (that endpoint accepts work_id only).
    for (const work of works.slice(0, 8)) {
      if (sequence !== actionSequence) return;
      const passages = await api('/api/passages', { work_id: work.id, limit: 1 });
      const first = passages.results?.[0];
      if (first?.id) {
        if (sequence === actionSequence) openReader({ id: first.id, author: poet.en }, poet.en);
        return;
      }
    }
    if (sequence === actionSequence) status(`No Greek passage is available for ${poet.en} in this index. Use the Reading room to browse other sources.`);
  } catch {
    if (sequence === actionSequence) status('The corpus could not be reached. Please try again, or open the Reading room.');
  }
}

const portraits = new Map();
function renderPoets() {
  const timeline = $('#poet-timeline');
  timeline.replaceChildren();
  for (const poet of POETS) {
    const item = make('li', 'poet-row');
    item.append(make('span', 'poet-date', poet.dt));
    const button = make('button', 'poet-open');
    button.type = 'button';
    button.setAttribute('aria-label', `Read ${poet.en}`);
    const name = make('span', 'poet-name');
    name.append(make('h3', '', poet.en));
    const greek = make('span', 'poet-greek', poet.gr); greek.lang = 'grc'; name.append(greek);
    button.append(name);
    const portrait = portraits.get(poet.en.toLowerCase());
    const picture = make('span', 'portrait-wrap');
    if (portrait?.image) {
      const img = make('img');
      img.src = new URL(portrait.image, new URL('/local-preview/', location.origin)).href;
      img.alt = portrait.title || `Depiction of ${poet.en}`;
      img.loading = 'lazy'; img.decoding = 'async';
      if (portrait.object_position) img.style.objectPosition = portrait.object_position;
      else if (poet.en === 'Alcaeus') img.style.objectPosition = '85% center';
      picture.append(img);
      img.addEventListener('error', () => { picture.replaceChildren(); picture.classList.add('is-empty'); picture.textContent = poet.gr[0]; picture.setAttribute('aria-label', 'Portrait unavailable'); });
    } else { picture.classList.add('is-empty'); picture.textContent = poet.gr[0]; picture.setAttribute('aria-hidden', 'true'); }
    if (portrait && ['Archilochus', 'Bacchylides'].includes(poet.en)) {
      picture.append(make('span', 'art-type', poet.en === 'Bacchylides' ? 'Manuscript' : 'Attributed portrait'));
    }
    button.append(picture);
    button.insertAdjacentHTML('beforeend', arrow);
    button.addEventListener('click', () => openPoet(poet));
    item.append(button); timeline.append(item);
  }
}
function renderCredits() {
  const list = $('#credit-list'); list.replaceChildren();
  for (const portrait of portraits.values()) {
    const item = make('li');
    item.textContent = `${portrait.author}: ${[portrait.title, portrait.artist, portrait.credit, portrait.license].filter(Boolean).join(' · ')}. ${portrait.description || ''}`;
    try {
      const source = new URL(portrait.source_url);
      if (source.protocol === 'https:') {
        const link = make('a', '', ' Source'); link.href = source.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link);
      }
    } catch { /* no fabricated source link */ }
    try {
      const license = new URL(portrait.license_url);
      if (license.protocol === 'https:') {
        const link = make('a', '', ' License'); link.href = license.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link);
      }
    } catch { /* not every public-domain record has a separate license URL */ }
    list.append(item);
  }
  list.append(make('li', '', 'Images are cropped to fit and gently desaturated for this presentation. Downloaded source files are unchanged.'));
}
for (const poet of POETS) { const option = make('option', '', poet.en); option.value = poet.en; $('#search-author').append(option); }
renderPoets();
fetch('/local-preview/portraits.json').then(response => response.ok ? response.json() : { portraits: [] }).then(data => {
  for (const portrait of data.portraits || []) if (portrait.author) portraits.set(portrait.author.toLowerCase(), portrait);
  renderPoets(); renderCredits();
}).catch(() => {});

// Reuse the actual painting hero and its controls, rather than maintaining a
// second dither implementation. Only the local landing-page composition changes.
async function mountPaintingHero() {
  try {
    const response = await fetch('/reader.html');
    if (!response.ok) throw new Error('Hero unavailable');
    const source = new DOMParser().parseFromString(await response.text(), 'text/html');
    const hero = source.querySelector('.reader-hero');
    if (!hero) throw new Error('Hero not found');
    hero.querySelector('.search-options')?.remove();
    hero.querySelector('.forms-options')?.remove();
    const compactSearch = $('#poet-search');
    compactSearch.querySelector('.search-line').classList.add('search');
    // The shared hero module expects this input ID for its mobile placeholder.
    compactSearch.querySelector('#query').id = 'search-input';
    compactSearch.querySelector('label[for="query"]').htmlFor = 'search-input';
    hero.querySelector('#search-form').replaceWith(compactSearch);
    $('#painting-hero').append(hero);
    $('.introduction').remove();
    const credits = make('p'); credits.id = 'hero-credits';
    $('#image-credits').append(credits);
    document.body.classList.add('has-painting-hero');
    await import('/js/reader-hero.js?v=p2-20260930');
  } catch (error) {
    console.error('Painting hero could not be loaded:', error);
  }
}
const queryField = () => $('#search-input') || $('#query');
mountPaintingHero();

$('#poet-search').addEventListener('submit', event => {
  event.preventDefault(); const q = queryField().value.trim(); if (!q) return;
  actionSequence++;
  openReader({ q, mode: $('#search-mode').value, author: $('#search-author').value, order: $('#search-order').value }, q);
});
for (const id of ['show-poets', 'back-to-poets']) $(`#${id}`).addEventListener('click', () => {
  showPoets();
  $('#poets').scrollIntoView({ block: 'start' });
});
$('#room-search').addEventListener('click', () => { showPoets(); queryField().focus(); $('#poet-search').scrollIntoView({ block: 'center' }); });
for (const id of ['open-reader', 'browse-all']) $(`#${id}`).addEventListener('click', () => { actionSequence++; openReader(); });
$('#reader-frame').addEventListener('load', () => {
  // Presentation-only, scoped to this local preview iframe. Full view keeps
  // the unchanged standalone reader including hero and every search control.
  try {
    const doc = $('#reader-frame').contentDocument;
    const style = doc.createElement('style');
    style.textContent = '.bar,.reader-hero,.reader-footer{display:none!important} .utility-bar{position:relative!important;top:0!important} html{scroll-behavior:auto!important} :focus-visible{outline-color:var(--sea)!important}';
    doc.head.append(style);
    $('#reader-frame').contentWindow.scrollTo(0, 0);
  } catch { /* standalone view remains available if served cross-origin */ }
});
