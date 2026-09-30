import { createDither } from './dither.js?v=p2-20260930';
import { IMAGES } from './images.js?v=p2-20260930';

// Each painting is paired with a line it answers. `focus` is the crop centre (0–1) for cover-fit.
const PAINTINGS = [
  {
    img: 'alma-tadema', focus: [0.62, 0.45], focusTall: [0.2, 0.5], edge: 0.05,
    title: 'Sappho and Alcaeus', artist: 'Lawrence Alma-Tadema', year: '1881', where: 'Walters Art Museum, Baltimore',
    gr: 'ἰόπλοκ᾽ ἄγνα μελλιχόμειδε Σάπφοι', tr: 'Violet-haired, holy, honey-smiling Sappho', cite: 'Alcaeus fr. 384 V',
  },
  {
    img: 'leap', focus: [0.5, 0.35], edge: 1.6,
    title: 'Sappho', artist: 'Miquel Carbonell i Selva', year: '1881', where: 'Museo del Prado, Madrid',
    gr: 'Ἔρος δηὖτέ μ᾽ ὀ λυσιμέλης δόνει', tr: 'Eros the limb-loosener shakes me again', cite: 'Sappho fr. 130.1 V',
  },
  {
    img: 'godward', focus: [0.6, 0.4], focusTall: [0.66, 0.45], edge: 1.6,
    title: 'Reverie (In the Days of Sappho)', artist: 'John William Godward', year: '1904', where: 'J. Paul Getty Museum, Los Angeles',
    gr: 'ποικιλόθρον᾽ ἀθανάτ᾽ Ἀφρόδιτα', tr: 'Immortal Aphrodite of the intricate throne', cite: 'Sappho fr. 1.1 V',
  },
  {
    img: 'altar', focus: [0.5, 0.55], focusTall: [0.4, 0.55], edge: 1.6,
    title: 'Dedication of a New Vestal Virgin', artist: 'Alessandro Marchesini', year: '1710s', where: 'State Hermitage Museum, St Petersburg',
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

const DEFAULTS = { on: true, palette: 'levels', matrix: 8, cell: 3, levels: 6, spread: 1.1, sat: 1.65, con: 1.1, bri: 0, amount: 1, lens: 0, shade: 0.9, blur: 3, dur: 2.2, glow: 0.14, parallax: 0, relief: 0.6, bevel: 0.5, edge: 1.2, aerial: 0.12, tilt: 0.23, grout: 0 };
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = s => document.querySelector(s);
const store = {
  get() { try { return JSON.parse(localStorage.getItem('melos.dither.v2')) || {}; } catch { return {}; } },
  set(v) { try { localStorage.setItem('melos.dither.v2', JSON.stringify(v)); } catch {} },
};

/* ---------- Hero ---------- */
const canvas = $('#dither');
let dither = null;
try { dither = createDither(canvas); } catch (e) { console.error(e); }
let params = { ...DEFAULTS, ...store.get() };
let current = -1, autoTimer = 0;

const loadImg = src => new Promise((ok, err) => { const i = new Image(); i.src = src; i.decode().then(() => ok(i), err); });
const fetchVariant = v => loadImg(v.avif).catch(() => loadImg(v.webp));   // AVIF, WebP fallback

// Source width that covers the hero on this screen; the dither hides anything finer.
const neededWidth = meta => {
  const d = Math.min(devicePixelRatio || 1, 1.5);   // finer than this is lost under the dither
  return Math.max(innerWidth * d, Math.max(innerHeight, 620) * d * meta.aspect);
};
const pick = (meta, need) => meta.variants.find(v => v.w >= need) || meta.variants.at(-1);

// Each painting: a small preview first (instant, and the dither hides the softness),
// then the size this screen needs, uploaded once into the same GPU texture.
const previews = [], sharp = [];
const preview = i => previews[i] ??= fetchVariant(IMAGES[PAINTINGS[i].img].variants[0])
  .then(img => {
    const slot = dither?.load(i, img, PAINTINGS[i].focus);
    if (slot) slot.edge = PAINTINGS[i].edge ?? 1;
    const dep = IMAGES[PAINTINGS[i].img].depth;   // small; drives the mosaic relief
    if (dep && dither) loadImg(dep).then(d => dither.loadDepth(i, d)).catch(() => {});
    return slot;
  });
function sharpen(i) {
  const meta = IMAGES[PAINTINGS[i].img], v = pick(meta, neededWidth(meta));
  if ((sharp[i] || meta.variants[0].w) >= v.w) return Promise.resolve();
  sharp[i] = v.w;
  return Promise.all([preview(i), fetchVariant(v)]).then(([, img]) => dither?.load(i, img, PAINTINGS[i].focus));
}
// Background queue: sharpen the current painting, then fetch the rest one at a time.
async function warm() {
  await sharpen(current);
  for (let k = 1; k < PAINTINGS.length; k++) { const i = (current + k) % PAINTINGS.length; await preview(i); await sharpen(i); }
}

function setCopy(p) {
  $('#verse-gr').textContent = p.gr;
  $('#verse-tr').textContent = p.tr;
  $('#verse-cite').textContent = p.cite;
  $('#caption').innerHTML = `<i>${p.title}</i>${p.artist}${p.year ? ', ' + p.year : ''}`;
  document.querySelectorAll('.thumbs button').forEach((b, i) => b.setAttribute('aria-selected', i === current));
}

async function go(i, instant = false) {
  if (i === current) return;
  current = i;
  const p = PAINTINGS[i];
  const still = instant || reduceMotion || document.hidden || !dither;
  // Text leads: the old quote fades out at once and the new one is back within ~0.4 s,
  // before the painting starts to change.
  const copy = [$('#verse'), $('#caption')];
  const swap = () => { setCopy(p); copy.forEach(el => el.classList.remove('out')); };
  if (still) swap();
  else { copy.forEach(el => el.classList.add('out')); setTimeout(() => current === i && swap(), 200); }
  const slot = await preview(i);
  if (i !== current) return;
  if (!dither) { const f = $('#fallback'); f.hidden = false; f.src = pick(IMAGES[p.img], neededWidth(IMAGES[p.img])).webp; return; }
  applyFocus();
  if (still) dither.show(slot);
  else {
    await new Promise(r => setTimeout(r, 180));
    if (i !== current) return;
    await dither.transition(slot, params.dur * 1000);
  }
  sharpen(i);   // after the transition, so a big upload never lands mid-animation
}
const next = d => { go((current + d + PAINTINGS.length) % PAINTINGS.length); scheduleAuto(); };

// Portrait screens crop hard; use each painting's tall-crop centre so the figures stay in frame.
function applyFocus() {
  const tall = canvas.clientHeight > canvas.clientWidth;
  PAINTINGS.forEach((p, i) => previews[i]?.then(slot => {
    const f = (tall && p.focusTall) || p.focus;
    if (slot) { slot.foc = [f[0], 1 - f[1]]; dither.set({}); }
  }));
}

function scheduleAuto() {
  clearInterval(autoTimer);
  if (!reduceMotion) autoTimer = setInterval(() => { if ($('#tune').hidden && !document.hidden) go((current + 1) % PAINTINGS.length); }, 14000);
}

PAINTINGS.forEach((p, i) => {
  const b = document.createElement('button');
  b.type = 'button'; b.role = 'tab';
  b.style.backgroundImage = `url(${IMAGES[p.img].thumb})`;
  b.setAttribute('aria-label', `${p.title}, ${p.artist}`);
  b.onclick = e => { e.stopPropagation(); go(i); scheduleAuto(); };
  $('#thumbs').append(b);
});

$('#credits').textContent = 'Paintings: ' + PAINTINGS.map(p =>
  `${p.artist}, ${p.title}${p.year ? ' (' + p.year + ')' : ''}${p.where ? ', ' + p.where : ''}`).join('; ') + '. All public domain.';

if (dither) {
  dither.set(params);
  const hero = $('.hero');
  const at = e => { const r = canvas.getBoundingClientRect(); dither.pointer(e.clientX - r.left, e.clientY - r.top); };
  // Mouse: lens follows the cursor. Touch: lens appears under the finger while pressed;
  // a horizontal swipe changes painting (vertical drags still scroll, via touch-action: pan-y).
  let swipe = null;
  const onArt = e => !e.target.closest('button, input, select, a, .tune, .search');
  hero.addEventListener('pointerdown', e => {
    if (e.pointerType === 'mouse' || !onArt(e)) return;
    swipe = { x: e.clientX, y: e.clientY }; at(e);
  });
  hero.addEventListener('pointermove', e => { if (e.pointerType === 'mouse' || swipe) at(e); });
  const end = e => {
    if (e.pointerType === 'mouse') return;
    if (swipe && e.type === 'pointerup') {
      const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) next(dx < 0 ? 1 : -1);
    }
    swipe = null; dither.pointer(null);
  };
  hero.addEventListener('pointerup', end);
  hero.addEventListener('pointercancel', end);
  hero.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') dither.pointer(null); });
  new ResizeObserver(() => { applyFocus(); if (current >= 0) sharpen(current); }).observe(hero);
}
if (matchMedia('(max-width: 640px)').matches) $('#q').placeholder = 'Greek, Beta Code or English';
go(0, true).then(warm);
// Dev aid: ?freeze=0.2 holds the transition to the next painting at that progress (no auto-advance).
const freezeAt = parseFloat(new URLSearchParams(location.search).get('freeze'));
if (dither && freezeAt >= 0) previews[0].then(() => preview(1)).then(slot => { clearInterval(autoTimer); dither.freeze(slot, freezeAt); });
scheduleAuto();

/* ---------- Dither controls ---------- */
const fields = ['on', 'palette', 'matrix', 'cell', 'levels', 'spread', 'sat', 'con', 'bri', 'amount', 'lens', 'shade', 'blur', 'dur', 'glow', 'parallax', 'relief', 'bevel', 'edge', 'aerial', 'tilt', 'grout'];
const pct = v => `${Math.round(v * 100)}%`;
const fmt = { sat: pct, amount: pct, shade: pct, glow: pct, relief: pct, bevel: pct, edge: pct, aerial: pct, tilt: pct, grout: pct, parallax: v => v ? `${v}px` : 'off', lens: v => v ? `${v}px` : 'off', cell: v => `${v}px`, blur: v => v ? `${v}px` : 'off', dur: v => `${(+v).toFixed(1)} s` };

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
  const hero = $('.hero');
  hero.style.setProperty('--shade', params.shade);
  hero.style.setProperty('--shade-blur', `${params.blur}px`);
}
for (const k of fields) {
  const el = $('#p-' + k);
  el.addEventListener('input', () => apply({ [k]: el.type === 'checkbox' ? el.checked : el.tagName === 'SELECT' && k === 'palette' ? el.value : +el.value }));
}
apply({});

const toggleTune = (open = $('#tune').hidden) => {
  $('#tune').hidden = !open; $('#tune-toggle').setAttribute('aria-expanded', open);
  if (!open) $('#tune-toggle').focus({ preventScroll: true });
};
$('#tune-toggle').onclick = () => toggleTune();
$('#tune-close').onclick = () => toggleTune(false);
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
  a.href = dither.snapshot(); a.download = `melos-${PAINTINGS[current].img}-dither.png`;
  a.click();
};
addEventListener('keydown', e => {
  if (e.target.closest('input, select, textarea')) return;
  if (e.key === 'd' || e.key === 'D') apply({ on: !params.on });
  if (e.key === 'ArrowRight') next(1);
  if (e.key === 'ArrowLeft') next(-1);
});

/* The original painting studio now reads the same live corpus as the reader. */
import('./studio-live.js?v=p2-20260930');
