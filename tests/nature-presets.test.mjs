import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { webcrypto, createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../js/nature-presets.js', import.meta.url), 'utf8');
const sha = text => createHash('sha256').update(text).digest('hex');
function setup(map = {}, { mobile = false, saveData = false } = {}) {
  let art = null;
  const heading = { querySelector: () => art, insertBefore(image) {art = image;} };
  const card = { querySelector: () => heading, dataset: {}, style: { setProperty(name, value) { this[name] = value; } } };
  const events = {}, requests = [];
  const presets = Object.fromEntries(['garden_grove', 'sea_coast', 'river_spring'].map(id =>
    [id, {url:`/${id}.webp`,smallUrl:`/${id}-small.webp`}]));
  const window = { MelosNaturePresetData: {presets,defaultPresetId:'garden_grove',assignmentsUrl:'/map.json'},
    addEventListener(name, handler) {events[name] = handler;}, requestIdleCallback(fn) { fn(); } };
  class Image { set src(value) {requests.push(value);queueMicrotask(() => this.onload());} }
  const context = {window, document:{getElementById:()=>card,querySelector:()=>({}),createElement:()=>({setAttribute(name,value){this[name]=value;},getAttribute(name){return this[name];}})},
    navigator:{connection:{saveData}},matchMedia:()=>({matches:mobile}),Image,crypto:webcrypto,
    TextEncoder,Uint8Array,setTimeout,fetch:async()=>({ok:true,json:async()=>map})};
  vm.runInNewContext(source, context);
  return {api:window.MelosNaturePresets,card,requests,events,art:()=>art};
}
test('only exact passage ID and unchanged source text receive a thematic preset', async () => {
  const {api,card}=setup({p:{theme:'sea_coast',hash:sha('Greek')}});
  await api.select({id:'p',text:'Greek'});
  assert.equal(card.dataset.naturePreset,'sea_coast');
  assert.equal(card.dataset.natureMatch,'annotated');
  await api.select({id:'p',text:'Changed'});
  assert.equal(card.dataset.naturePreset,'garden_grove');
  assert.equal(card.dataset.natureMatch,'decorative-default');
});
test('passage transitions cancel a pending old image selection', async () => {
  const {api,card}=setup({p:{theme:'sea_coast',hash:sha('Greek')}});
  const previous=api.select({id:'p',text:'Greek'});
  await api.select(null);await previous;
  assert.equal(card.dataset.naturePreset,'garden_grove');
});
test('background preloading waits for hero and uses one cached request per preset', async () => {
  const {api,requests,events}=setup();
  assert.equal(requests.length,0);
  await events['melos:hero-assets-ready']();
  assert.equal(requests.length,3);
  await api.warmCurrent();await api.preloadAll();
  assert.equal(requests.length,3);
});
test('mobile uses smaller images; data-saver skips speculative preload', async () => {
  const {api,requests}=setup({}, {mobile:true,saveData:true});
  await api.preloadAll();assert.equal(requests.length,0);
  await api.warmCurrent();assert.deepEqual(requests,['/garden_grove-small.webp']);
});
test('unrecognised preset cannot inject an arbitrary image URL', async () => {
  const {api,card}=setup({p:{theme:'https://untrusted.example',hash:sha('Greek')}});
  await api.select({id:'p',text:'Greek'});
  assert.equal(card.dataset.naturePreset,'garden_grove');
});

test('fullscreen creates an eager real image even when speculative loading is disabled', async () => {
  const {api,art}=setup({}, {mobile:true,saveData:true});
  assert.equal(art(),null);
  await api.warmCurrent();
  assert.equal(art().src,'/garden_grove-small.webp');
  assert.equal(art().loading,'eager');
  assert.equal(art().fetchPriority,'high');
  assert.equal(art()['aria-hidden'],'true');
  art().onerror();
  assert.equal(art().src,'/garden_grove.webp');
});

test('late source-bound theme selection updates the visible fullscreen image', async () => {
  const {api,art}=setup({p:{theme:'sea_coast',hash:sha('Greek')}});
  api.showArtwork();
  await api.select({id:'p',text:'Greek'});
  assert.equal(art().src,'/sea_coast.webp');
});
