import { createDither } from './dither.js';

// Each painting is paired with a line it answers. `focus` is the crop centre (0–1) for cover-fit.
const PAINTINGS = [
  {
    src: 'assets/paintings/alma-tadema.jpg', focus: [0.62, 0.45],
    title: 'Sappho and Alcaeus', artist: 'Lawrence Alma-Tadema', year: '1881',
    gr: 'ἰόπλοκ᾽ ἄγνα μελλιχόμειδε Σάπφοι', tr: 'Violet-haired, holy, honey-smiling Sappho', cite: 'Alcaeus fr. 384 V',
  },
  {
    src: 'assets/paintings/leap.jpg', focus: [0.5, 0.35],
    title: 'The Death of Sappho', artist: 'Miguel Carbonell Selva', year: '1881', verify: true,
    gr: 'Ἔρος δηὖτέ μ᾽ ὀ λυσιμέλης δόνει', tr: 'Eros the limb-loosener shakes me again', cite: 'Sappho fr. 130.1 V',
  },
  {
    src: 'assets/paintings/godward.jpg', focus: [0.6, 0.4],
    title: 'In the Days of Sappho', artist: 'John William Godward', year: '1904',
    gr: 'ποικιλόθρον᾽ ἀθανάτ᾽ Ἀφρόδιτα', tr: 'Immortal Aphrodite of the intricate throne', cite: 'Sappho fr. 1.1 V',
  },
  {
    src: 'assets/paintings/altar.jpg', focus: [0.5, 0.55],
    title: 'Sacrifice at the altar', artist: 'Artist to be confirmed', year: '', verify: true,
    gr: 'βῶμοι δὲ τεθυμιάμενοι λιβανώτωι', tr: 'And altars smoking with frankincense', cite: 'Sappho fr. 2.4 V',
  },
];

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

const DEFAULTS = { on: true, palette: 'levels', matrix: 8, cell: 3, levels: 4, spread: 1, sat: 1.35, con: 1.08, bri: 0, amount: 1, lens: 140 };
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = s => document.querySelector(s);
const store = {
  get() { try { return JSON.parse(localStorage.getItem('melos.dither')) || {}; } catch { return {}; } },
  set(v) { try { localStorage.setItem('melos.dither', JSON.stringify(v)); } catch {} },
};

/* ---------- Hero ---------- */
const canvas = $('#dither');
let dither = null;
try { dither = createDither(canvas); } catch (e) { console.error(e); }
let params = { ...DEFAULTS, ...store.get() };
let current = 0, busy = false, autoTimer = 0;

const loadImg = src => new Promise((ok, err) => { const i = new Image(); i.onload = () => ok(i); i.onerror = err; i.src = src; });
const images = PAINTINGS.map(p => loadImg(p.src));

function setCopy(p) {
  $('#verse-gr').textContent = p.gr;
  $('#verse-tr').textContent = p.tr;
  $('#verse-cite').textContent = p.cite;
  $('#caption').innerHTML = `<i>${p.title}</i>${p.artist}${p.year ? ', ' + p.year : ''}`;
  document.querySelectorAll('.thumbs button').forEach((b, i) => b.setAttribute('aria-selected', i === current));
}

async function go(i, instant = false) {
  if (busy || (i === current && !instant)) return;
  busy = true; current = i;
  const p = PAINTINGS[i], img = await images[i];
  setCopy(p);
  if (!dither) { const f = $('#fallback'); f.hidden = false; f.src = p.src; }
  else if (instant || reduceMotion || document.hidden) dither.show(img, p.focus);
  else await dither.transition(img, p.focus);
  busy = false;
}

function scheduleAuto() {
  clearInterval(autoTimer);
  if (!reduceMotion) autoTimer = setInterval(() => { if ($('#tune').hidden && !document.hidden) go((current + 1) % PAINTINGS.length); }, 14000);
}

PAINTINGS.forEach((p, i) => {
  const b = document.createElement('button');
  b.type = 'button'; b.role = 'tab';
  b.style.backgroundImage = `url(${p.src})`;
  b.setAttribute('aria-label', `${p.title}, ${p.artist}`);
  b.onclick = () => { go(i); scheduleAuto(); };
  $('#thumbs').append(b);
});

$('#credits').textContent = 'Paintings: ' + PAINTINGS.map(p =>
  `${p.artist}${p.verify ? ' (attribution to confirm)' : ''}, ${p.title}${p.year ? ' (' + p.year + ')' : ''}`).join('; ') + '.';

if (dither) {
  dither.set(params);
  const hero = $('.hero');
  hero.addEventListener('pointermove', e => { const r = canvas.getBoundingClientRect(); dither.pointer(e.clientX - r.left, e.clientY - r.top); });
  hero.addEventListener('pointerleave', () => dither.pointer(null));
}
go(0, true);
scheduleAuto();

/* ---------- Dither controls ---------- */
const fields = ['on', 'palette', 'matrix', 'cell', 'levels', 'spread', 'sat', 'con', 'bri', 'amount', 'lens'];
const fmt = { sat: v => `${Math.round(v * 100)}%`, amount: v => `${Math.round(v * 100)}%`, lens: v => v ? `${v}px` : 'off', cell: v => `${v}px` };

function syncControls() {
  for (const k of fields) {
    const el = $('#p-' + k);
    if (el.type === 'checkbox') el.checked = params[k]; else el.value = params[k];
    const out = document.querySelector(`output[for="p-${k}"]`);
    if (out) out.textContent = (fmt[k] || (v => (+v).toFixed(2).replace(/\.00$/, '')))(params[k]);
  }
  $('#p-levels').disabled = params.palette !== 'levels';
}
function apply(patch) {
  params = { ...params, ...patch };
  store.set(params); syncControls(); dither?.set(params);
}
for (const k of fields) {
  const el = $('#p-' + k);
  el.addEventListener('input', () => apply({ [k]: el.type === 'checkbox' ? el.checked : el.tagName === 'SELECT' && k === 'palette' ? el.value : +el.value }));
}
syncControls();

$('#tune-toggle').onclick = () => {
  const t = $('#tune'), open = t.hidden;
  t.hidden = !open; $('#tune-toggle').setAttribute('aria-expanded', open);
};
$('#p-reset').onclick = () => apply(DEFAULTS);
$('#p-copy').onclick = async e => {
  const { on, ...rest } = params;
  try { await navigator.clipboard.writeText(JSON.stringify(rest, null, 2)); e.target.textContent = 'Copied'; }
  catch { e.target.textContent = 'Copy failed'; }
  setTimeout(() => (e.target.textContent = 'Copy settings'), 1400);
};
$('#p-save').onclick = () => {
  if (!dither) return;
  const a = document.createElement('a');
  a.href = dither.snapshot(); a.download = `melos-${PAINTINGS[current].src.split('/').pop().replace(/\.\w+$/, '')}-dither.png`;
  a.click();
};
addEventListener('keydown', e => {
  if (e.target.closest('input, select, textarea')) return;
  if (e.key === 'd' || e.key === 'D') apply({ on: !params.on });
  if (e.key === 'ArrowRight') { go((current + 1) % PAINTINGS.length); scheduleAuto(); }
  if (e.key === 'ArrowLeft') { go((current + PAINTINGS.length - 1) % PAINTINGS.length); scheduleAuto(); }
});

/* ---------- Lexicon ---------- */
const BETA = { a: 'α', b: 'β', g: 'γ', d: 'δ', e: 'ε', z: 'ζ', h: 'η', q: 'θ', i: 'ι', k: 'κ', l: 'λ', m: 'μ', n: 'ν', c: 'ξ', o: 'ο', p: 'π', r: 'ρ', s: 'σ', t: 'τ', u: 'υ', f: 'φ', x: 'χ', y: 'ψ', w: 'ω' };
// Accent-, breathing- and case-insensitive; η/α folded so Aeolic and Attic-Ionic forms meet.
const norm = s => s.normalize('NFD').replace(/[̀-ͯ᾽᾿'’᾽\[\]]/g, '').toLowerCase().replace(/ς/g, 'σ');
const fold = s => norm(s).replace(/η/g, 'α');
const toGreek = s => s.toLowerCase().replace(/[a-z]/g, ch => BETA[ch] || ch);

let entries = [], filterPoet = null, selected = null;

function matches(e, q) {
  if (filterPoet && !e.attestations.some(a => a.poet === filterPoet)) return false;
  if (!q) return true;
  const ql = q.toLowerCase().trim(), gq = fold(/[a-z]/i.test(q) ? toGreek(q) : q);
  const greek = [e.lemma, ...e.attestations.map(a => a.text)].map(fold);
  const english = [e.gloss, e.note, ...e.attestations.flatMap(a => [a.tr, a.poet])].join(' ').toLowerCase();
  return greek.some(g => g.includes(gq)) || english.includes(ql);
}

function highlight(text, lemma) {
  const stem = fold(lemma).slice(0, 4);
  return text.split(/(\s+)/).map(w => (!/\s/.test(w) && stem.length > 2 && fold(w).includes(stem)) ? `<mark>${w}</mark>` : esc(w)).join('');
}
const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function renderEntry(e) {
  selected = e;
  const box = $('#entry');
  if (!e) { box.innerHTML = '<p class="note">Nothing matches that search. Try a Greek word without accents, Beta Code such as <i>selanna</i>, or an English gloss.</p>'; return; }
  const byPoet = {};
  e.attestations.forEach(a => (byPoet[a.poet] = (byPoet[a.poet] || 0) + 1));
  box.innerHTML = `
    <h3 lang="grc">${e.lemma}</h3>
    <p class="meta"><em>${e.pos}</em>${esc(e.gloss)}</p>
    ${e.note ? `<p class="note">${esc(e.note)}</p>` : ''}
    <ul class="spread" aria-label="Attestations by poet">
      ${Object.entries(byPoet).map(([p, n]) => `<li>${p} <b>${n}</b></li>`).join('')}
    </ul>
    <ol class="attest">
      ${e.attestations.map(a => `
        <li>
          <div class="src"><span>${a.poet}</span>${a.cite}</div>
          <div><p class="gr" lang="grc">${highlight(a.text, e.lemma)}</p><p class="tr">${esc(a.tr)}</p></div>
        </li>`).join('')}
    </ol>`;
  document.querySelectorAll('.results button').forEach(b => b.setAttribute('aria-current', b.dataset.lemma === e.lemma));
}

function renderResults(q = '') {
  const gq = fold(/[a-z]/i.test(q) ? toGreek(q) : q), ql = q.toLowerCase().trim();
  const rank = e => (q && (fold(e.lemma).includes(gq) || e.gloss.toLowerCase().includes(ql))) ? 0 : 1;
  const list = entries.filter(e => matches(e, q)).sort((a, b) => rank(a) - rank(b));
  const ol = $('#results');
  ol.innerHTML = list.length ? '' : '<li class="empty">No entries</li>';
  for (const e of list) {
    const li = document.createElement('li');
    li.innerHTML = `<button type="button" data-lemma="${e.lemma}"><span class="lm" lang="grc">${e.lemma}</span><span class="gl">${esc(e.gloss)}</span></button>`;
    li.firstChild.onclick = () => renderEntry(e);
    ol.append(li);
  }
  $('#count').textContent = `${list.length} of ${entries.length} sample entries` + (filterPoet ? ` attested in ${filterPoet}` : '') + (q ? ` matching “${q}”` : '');
  renderEntry(list[0]);
}

$('#search').addEventListener('submit', e => {
  e.preventDefault();
  filterPoet = null;
  renderResults($('#q').value);
  $('#lexicon').scrollIntoView();
});
$('#q').addEventListener('input', () => renderResults($('#q').value));

fetch('data/lexicon.json').then(r => r.json()).then(d => {
  entries = d.entries.sort((a, b) => norm(a.lemma).localeCompare(norm(b.lemma), 'el'));
  renderResults();
  $('#timeline').innerHTML = POETS.map(p => {
    const has = entries.some(e => e.attestations.some(a => a.poet === p.en));
    return `<li class="${has ? 'has' : ''}"><button type="button" data-poet="${p.en}"><span class="nm" lang="grc">${p.gr}</span><span class="en">${p.en}</span><span class="dt">${p.dt}</span></button></li>`;
  }).join('');
  $('#timeline').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    filterPoet = b.dataset.poet; $('#q').value = '';
    renderResults(); $('#lexicon').scrollIntoView();
  };
}).catch(() => { $('#count').textContent = 'Could not load data/lexicon.json. Serve the folder over http (see README).'; });
