import { createDither, compactDither, phoneDither, COMPACT_BEVEL_MAX, constrainDither, coverPosition } from './dither.js?v=p2-20260930';
import { IMAGES } from './images.js?v=p2-20260930';

// The original Melos painting sequence and crop positions. This module owns only
// the painting stage; research results are supplied by reader.js and the API.
const PAINTINGS = [
  { img: 'alma-tadema', focus: [.62, .45], focusTall: [.8, .5], title: 'Sappho and Alcaeus', artist: 'Lawrence Alma-Tadema', year: '1881', where: 'Walters Art Museum, Baltimore', gr: 'ἰόπλοκ᾽ ἄγνα μελλιχόμειδε Σάπφοι', tr: 'Violet-haired, holy, honey-smiling Sappho', cite: 'Alcaeus fr. 384 V' },
  { img: 'leap', focus: [.5, .35], title: 'Sappho', artist: 'Miquel Carbonell i Selva', year: '1881', where: 'Museo del Prado, Madrid', gr: 'Ἔρος δηὖτέ μ᾽ ὀ λυσιμέλης δόνει', tr: 'Eros the limb-loosener shakes me again', cite: 'Sappho fr. 130.1 V' },
  { img: 'godward', focus: [.6, .4], focusTall: [.66, .45], title: 'Reverie (In the Days of Sappho)', artist: 'John William Godward', year: '1904', where: 'J. Paul Getty Museum, Los Angeles', gr: 'ποικιλόθρον᾽ ἀθανάτ᾽ Ἀφρόδιτα', tr: 'Immortal Aphrodite of the intricate throne', cite: 'Sappho fr. 1.1 V' },
  { img: 'altar', focus: [.5, .55], focusTall: [.8, .55], title: 'Dedication of a New Vestal Virgin', artist: 'Alessandro Marchesini', year: '1710s', where: 'State Hermitage Museum, St Petersburg', gr: 'βῶμοι δὲ τεθυμιάμενοι λιβανώτωι', tr: 'And altars smoking with frankincense', cite: 'Sappho fr. 2.4 V' },
];
const DEFAULTS = { on: true, palette: 'levels', matrix: 8, cell: 3, levels: 6, spread: 1.1, sat: 1.65, con: 1.1, bri: 0, amount: 1, lens: 0, shade: .9, blur: 3, dur: 2.2, glow: .14, parallax: 0, relief: .6, bevel: .5, aerial: .12, tilt: .23, grout: 0 };
const fields = Object.keys(DEFAULTS);
const $ = s => document.querySelector(s);
const hero = $('.reader-hero');
const canvas = $('#dither');
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
let dither = null;
try { dither = createDither(canvas); } catch (error) { console.warn('Dither unavailable:', error); }
let params;
try { params = { ...DEFAULTS, ...JSON.parse(localStorage.getItem('melos.dither.v2') || '{}') }; }
catch { params = { ...DEFAULTS }; }
params = constrainDither(params);
let current = -1, autoTimer = 0;
const previews = [], sharp = [];
const loadImg = src => new Promise((resolve, reject) => {
  const img = new Image(); img.src = src;
  img.decode().then(() => resolve(img), reject);
});
const fetchVariant = variant => loadImg(variant.avif).catch(() => loadImg(variant.webp));
const neededWidth = meta => Math.max(innerWidth * Math.min(devicePixelRatio || 1, 1.5), Math.max(innerHeight, 620) * Math.min(devicePixelRatio || 1, 1.5) * meta.aspect);
const pick = (meta, need) => meta.variants.find(v => v.w >= need) || meta.variants.at(-1);
const preview = i => previews[i] ??= fetchVariant(IMAGES[PAINTINGS[i].img].variants[0]).then(img => {
  const slot = dither?.load(i, img, PAINTINGS[i].focus);
  if (dither && IMAGES[PAINTINGS[i].img].depth) loadImg(IMAGES[PAINTINGS[i].img].depth).then(depth => dither.loadDepth(i, depth)).catch(() => {});
  return slot;
});
function sharpen(i) {
  const meta = IMAGES[PAINTINGS[i].img], variant = pick(meta, neededWidth(meta));
  if ((sharp[i] || meta.variants[0].w) >= variant.w) return Promise.resolve();
  sharp[i] = variant.w;
  return Promise.all([preview(i), fetchVariant(variant)]).then(([, img]) => dither?.load(i, img, PAINTINGS[i].focus));
}
async function warm() {
  await sharpen(current);
  for (let k = 1; k < PAINTINGS.length; k++) {
    const i = (current + k) % PAINTINGS.length;
    await preview(i); await sharpen(i);
  }
}
function setCopy(painting) {
  $('#verse-gr').textContent = painting.gr;
  window.MelosVerseFit?.watch($('#verse-gr'));
  $('#verse-tr').textContent = painting.tr;
  $('#verse-cite').textContent = painting.cite;
  $('#caption').replaceChildren();
  const title = document.createElement('i'); title.textContent = painting.title;
  $('#caption').append(title, document.createTextNode(`${painting.artist}, ${painting.year}`));
  document.querySelectorAll('.thumbs button').forEach((button, i) => button.setAttribute('aria-selected', String(i === current)));
}
function applyFocus() {
  const tall = canvas.clientHeight > canvas.clientWidth;
  if (current >= 0) {
    const painting = PAINTINGS[current];
    $('#fallback').style.objectPosition = coverPosition(tall && painting.focusTall || painting.focus,
      IMAGES[painting.img].aspect, canvas.clientWidth, canvas.clientHeight);
  }
  PAINTINGS.forEach((painting, i) => previews[i]?.then(slot => {
    const focus = tall && painting.focusTall || painting.focus;
    if (slot) { slot.foc = [focus[0], 1 - focus[1]]; dither.set({}); }
  }));
}
async function go(i, instant = false) {
  if (i === current) return;
  current = i;
  const painting = PAINTINGS[i], still = instant || reduceMotion || document.hidden || !dither;
  const copy = [$('#verse'), $('#caption')];
  if (still) setCopy(painting);
  else {
    copy.forEach(el => el.classList.add('out'));
    setTimeout(() => { if (current === i) { setCopy(painting); copy.forEach(el => el.classList.remove('out')); } }, 200);
  }
  let slot;
  try { slot = await preview(i); }
  catch (error) { console.warn('Painting unavailable:', error); }
  if (i !== current) return;
  if (!dither || !slot) {
    const fallback = $('#fallback');
    fallback.hidden = false;
    fallback.src = pick(IMAGES[painting.img], neededWidth(IMAGES[painting.img])).webp;
    applyFocus();
    return;
  }
  applyFocus();
  if (still) dither.show(slot);
  else { await new Promise(resolve => setTimeout(resolve, 180)); if (i !== current) return; await dither.transition(slot, params.dur * 1000); }
  sharpen(i).catch(() => {});
}
function scheduleAuto() {
  clearInterval(autoTimer);
  if (!reduceMotion) autoTimer = setInterval(() => {
    if ($('#tune').hidden && !document.hidden) go((current + 1) % PAINTINGS.length);
  }, 14000);
}
function next(delta) { go((current + delta + PAINTINGS.length) % PAINTINGS.length); scheduleAuto(); }
PAINTINGS.forEach((painting, i) => {
  const button = document.createElement('button');
  button.type = 'button'; button.role = 'tab';
  button.style.backgroundImage = `url(${IMAGES[painting.img].thumb})`;
  button.setAttribute('aria-label', `${painting.title}, ${painting.artist}`);
  button.addEventListener('click', event => { event.stopPropagation(); go(i); scheduleAuto(); });
  $('#thumbs').append(button);
});
$('#hero-credits').textContent = `Paintings: ${PAINTINGS.map(p => `${p.artist}, ${p.title} (${p.year}), ${p.where}`).join('; ')}. All public domain.`;
if (dither) {
  dither.set(params);
  const pointer = event => { const rect = canvas.getBoundingClientRect(); dither.pointer(event.clientX - rect.left, event.clientY - rect.top); };
  let swipe = null;
  hero.addEventListener('pointerdown', event => {
    if (event.pointerType === 'mouse' || event.target.closest('button, input, select, a, .tune, .search')) return;
    swipe = { x: event.clientX, y: event.clientY }; pointer(event);
  });
  hero.addEventListener('pointermove', event => { if (event.pointerType === 'mouse' || swipe) pointer(event); });
  const end = event => {
    if (event.pointerType === 'mouse') return;
    if (swipe && event.type === 'pointerup') {
      const dx = event.clientX - swipe.x, dy = event.clientY - swipe.y;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) next(dx < 0 ? 1 : -1);
    }
    swipe = null; dither.pointer(null);
  };
  hero.addEventListener('pointerup', end);
  hero.addEventListener('pointercancel', end);
  hero.addEventListener('pointerleave', event => { if (event.pointerType === 'mouse') dither.pointer(null); });
}
new ResizeObserver(() => { applyFocus(); if (current >= 0) sharpen(current).catch(() => {}); }).observe(hero);
if (matchMedia('(max-width: 640px)').matches) $('#search-input').placeholder = 'Greek, English, or Il. 1.1';
go(0, true).then(warm).catch(() => {}).finally(() => {
  window.MelosHeroAssetsReady = true;
  window.dispatchEvent(new Event('melos:hero-assets-ready'));
});
const freezeAt = parseFloat(new URLSearchParams(location.search).get('freeze'));
if (dither && freezeAt >= 0) previews[0].then(() => preview(1)).then(slot => { clearInterval(autoTimer); dither.freeze(slot, freezeAt); });
scheduleAuto();

const pct = value => `${Math.round(value * 100)}%`;
const format = { sat: pct, amount: pct, shade: pct, glow: pct, relief: pct, bevel: pct, aerial: pct, tilt: pct, grout: pct,
  parallax: value => value ? `${value}px` : 'off', lens: value => value ? `${value}px` : 'off',
  cell: value => `${value}px`, blur: value => value ? `${value}px` : 'off', dur: value => `${(+value).toFixed(1)} s` };
function syncControls() {
  $('#p-bevel').max = compactDither.matches ? COMPACT_BEVEL_MAX : 1.2;
  $('#p-bevel').step = compactDither.matches ? .01 : .05;
  $('#p-relief').disabled = compactDither.matches;
  for (const key of fields) {
    const input = $(`#p-${key}`);
    if (input.type === 'checkbox') input.checked = params[key]; else input.value = params[key];
    const output = document.querySelector(`output[for="p-${key}"]`);
    if (output) output.textContent = (format[key] || (value => (+value).toFixed(2).replace(/\.00$/, '')))(params[key]);
  }
  $('#p-levels').disabled = params.palette !== 'levels';
}
function apply(patch) {
  params = constrainDither({ ...params, ...patch });
  try { localStorage.setItem('melos.dither.v2', JSON.stringify(params)); } catch {}
  syncControls(); dither?.set(params);
  hero.style.setProperty('--shade', params.shade);
  hero.style.setProperty('--shade-blur', `${params.blur}px`);
}
for (const key of fields) {
  const input = $(`#p-${key}`);
  input.addEventListener('input', () => apply({ ...(key === 'cell' ? { cellUserSet: true } : {}), [key]: input.type === 'checkbox' ? input.checked : key === 'palette' ? input.value : +input.value }));
}
apply({});
compactDither.addEventListener('change', () => apply({}));
phoneDither.addEventListener('change', () => apply({}));
function toggleTune(open = $('#tune').hidden) {
  $('#tune').hidden = !open;
  $('#tune-toggle').setAttribute('aria-expanded', String(open));
  if (!open) $('#tune-toggle').focus({ preventScroll: true });
}
$('#tune-toggle').addEventListener('click', () => toggleTune());
$('#tune-close').addEventListener('click', () => toggleTune(false));
$('#p-reset').addEventListener('click', () => apply({ ...DEFAULTS, cellUserSet: false }));
$('#p-copy').addEventListener('click', async event => {
  const { on, ...rest } = params;
  try { await navigator.clipboard.writeText(JSON.stringify(rest, null, 2)); event.target.textContent = 'Copied'; }
  catch { event.target.textContent = 'Copy failed'; }
  setTimeout(() => { event.target.textContent = 'Copy settings'; }, 1400);
});
$('#p-save').addEventListener('click', () => {
  if (!dither) return;
  const link = document.createElement('a');
  link.href = dither.snapshot(); link.download = `melos-${PAINTINGS[current].img}-dither.png`; link.click();
});
addEventListener('keydown', event => {
  if (event.target.closest('input, select, textarea')) return;
  if (event.key.toLowerCase() === 'd') apply({ on: !params.on });
  if (event.key === 'ArrowRight') next(1);
  if (event.key === 'ArrowLeft') next(-1);
});
