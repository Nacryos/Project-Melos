import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// The word-panel loading layer (second block of js/word-panel.js), with
// synthetic loaders and storage; no network.
const source = readFileSync(new URL('../js/word-panel.js', import.meta.url), 'utf8');
function load(extra = {}) {
  const window = {};
  vm.runInContext(source, vm.createContext({ window, AbortController, DOMException, setTimeout, clearTimeout, ...extra }));
  return window.MelosWordPrefetch;
}
const tools = load();
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function memoryStorage({ quota = Infinity } = {}) {
  const map = new Map();
  const used = () => [...map.values()].reduce((sum, value) => sum + value.length, 0);
  return { map, getItem: key => map.has(key) ? map.get(key) : null, removeItem: key => map.delete(key),
    setItem(key, value) { const before = map.get(key)?.length || 0; if (used() - before + value.length > quota) throw new Error('QuotaExceededError'); map.set(key, String(value)); } };
}
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }

test('LRU keeps the most recently used entries', () => {
  const lru = tools.createLru(2);
  lru.set('a', 1); lru.set('b', 2); lru.get('a'); lru.set('c', 3);
  assert.equal(lru.has('a'), true); assert.equal(lru.has('b'), false); assert.equal(lru.has('c'), true);
});

test('session store respects its budget, evicts oldest first and survives a full quota', () => {
  const storage = memoryStorage();
  const store = tools.createStore(storage, 'p:', { budget: 30, maxItem: 20 });
  assert.equal(store.set('a', 'x'.repeat(10)), true);
  assert.equal(store.set('b', 'y'.repeat(10)), true);
  assert.equal(store.set('c', 'z'.repeat(10)), true);
  assert.equal(store.get('a'), undefined, 'oldest evicted to stay within budget');
  assert.equal(store.get('c'), 'z'.repeat(10));
  assert.equal(store.set('big', 'w'.repeat(40)), false, 'oversized values stay in memory only');
  const tight = tools.createStore(memoryStorage({ quota: 40 }), 'q:', { budget: 1000, maxItem: 1000 });
  assert.equal(tight.set('a', 'x'.repeat(10)), true);
  assert.equal(tight.set('b', 'y'.repeat(10)), true, 'a quota error evicts and retries');
  const broken = tools.createStore({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() {} }, 'r:');
  assert.equal(broken.get('a'), undefined); assert.equal(broken.set('a', 1), false);
});

test('one request per key: callers join, results are cached in memory and the session', async () => {
  const storage = memoryStorage(), cache = tools.create({ storage });
  let calls = 0; const gate = deferred();
  const loader = () => { calls++; return gate.promise; };
  const first = cache.load('word|k', loader), second = cache.load('word|k', loader);
  assert.equal(cache.pending('word|k'), true);
  gate.resolve({ lexicon_entries: [] });
  assert.deepEqual(plain(await first), { lexicon_entries: [] }); assert.deepEqual(plain(await second), { lexicon_entries: [] });
  assert.equal(calls, 1); assert.equal(cache.stats.joined, 1);
  assert.deepEqual(plain(await cache.load('word|k', loader)), { lexicon_entries: [] }); assert.equal(calls, 1);
  // A new page in the same session reads the stored copy.
  const again = tools.create({ storage });
  assert.deepEqual(plain(again.peek('word|k')), { lexicon_entries: [] });
  // Failures are not cached.
  await assert.rejects(cache.load('word|bad', async () => { throw new Error('502'); }));
  assert.equal(cache.peek('word|bad'), undefined);
});

test('low-priority prefetch runs at most maxLow at a time; a click promotes a queued key', async () => {
  const cache = tools.create({ maxLow: 2 });
  const gates = {}, started = [];
  const loader = key => ({ priority }) => { started.push(`${key}:${priority}`); return (gates[key] = deferred()).promise; };
  for (const key of ['a', 'b', 'c', 'd']) cache.load(key, loader(key), { priority: 'low', group: 'p1' }).catch(() => {});
  await tick();
  assert.deepEqual(started, ['a:low', 'b:low']); assert.equal(cache.queued, 2);
  const clicked = cache.load('d', loader('d'), { priority: 'high' });
  await tick();
  assert.deepEqual(started, ['a:low', 'b:low', 'd:high'], 'the clicked word does not wait behind prefetch');
  gates.a.resolve(1); await tick(); await tick();
  assert.deepEqual(started, ['a:low', 'b:low', 'd:high'], 'queued prefetch waits while the clicked word loads');
  gates.d.resolve('dict'); assert.equal(await clicked, 'dict');
  await tick(); await tick();
  assert.deepEqual(started, ['a:low', 'b:low', 'd:high', 'c:low']);
});

test('a passage change cancels unclaimed prefetch; a clicked word keeps its request', async () => {
  const cache = tools.create({ maxLow: 1 });
  const signals = {};
  const loader = key => ({ signal }) => { signals[key] = signal; return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); };
  const running = cache.load('a', loader('a'), { priority: 'low', group: 'p1' });
  const queued = cache.load('b', loader('b'), { priority: 'low', group: 'p1' });
  const hovered = cache.load('h', loader('h'), { priority: 'high', claim: false, group: 'p1' });
  const clicked = cache.load('c', ({ signal }) => { signals.c = signal; return Promise.resolve('kept'); }, { priority: 'high', group: 'p1' });
  await tick();
  cache.cancel();
  await assert.rejects(running); await assert.rejects(queued, error => error.name === 'AbortError'); await assert.rejects(hovered);
  assert.equal(signals.a.aborted, true); assert.equal(signals.h.aborted, true); assert.equal(signals.b, undefined, 'never started');
  assert.equal(await clicked, 'kept');
  assert.equal(cache.pending('a'), false);
});

test('the connection decides how much is fetched ahead', () => {
  assert.deepEqual(plain(tools.networkPolicy({ saveData: true })), { batch: false, hover: false, idle: 0, maxLow: 0, reason: 'save-data' });
  assert.equal(tools.networkPolicy({ effectiveType: '2g' }).idle, 0);
  assert.equal(tools.networkPolicy({ effectiveType: '2g' }).hover, true);
  assert.deepEqual([tools.networkPolicy({ effectiveType: '3g' }).idle, tools.networkPolicy({ effectiveType: '3g' }).maxLow], [3, 1]);
  assert.deepEqual([tools.networkPolicy({ effectiveType: '4g', downlink: 0.8 }).idle, tools.networkPolicy(undefined).idle], [3, 6]);
  const cache = tools.create({ maxLow: 0 });
  let called = false;
  return cache.load('x', () => { called = true; return 1; }, { priority: 'low' }).then(value => { assert.equal(value, undefined); assert.equal(called, false); });
});

test('likely clicks: content words and rarer spellings first, frequent particles skipped', () => {
  const words = ['καὶ', 'δ’', 'ποικιλόθρον’', 'σε', 'μή', 'Ἀφρόδιτα', 'λίσσομαί', 'τὰν', 'ποικιλόθρον’'].map((form, index) => ({ form, index, key: `${index}` }));
  const ranked = plain(tools.rankWords(words, { limit: 3 }).map(word => word.form));
  assert.deepEqual(ranked, ['ποικιλόθρον’', 'Ἀφρόδιτα', 'λίσσομαί']);
  // The batch headline's part of speech removes function words that slip past the list.
  const headlines = new Map([['5', { pos: 'particle' }]]);
  assert.equal(plain(tools.rankWords(words, { limit: 5, headlines }).map(word => word.form)).includes('Ἀφρόδιτα'), false);
  assert.deepEqual(plain(tools.rankWords(words, { limit: 0 })), []);
});

test('batch headlines map code-point offsets to the reader’s UTF-16 spans and keep ties', () => {
  const text = '𝔄 σ’ ἔρος';
  const payload = { index_version: 'o1', tokens: [
    { i: 0, start: 2, end: 4, printed: 'σ’', lemma: 'σύ', gloss: 'thou', parses: ['acc. 2nd sg.'], pos: 'pron', tie: true,
      alternatives: [{ lemma: 'σός', gloss: 'thy', parses: ['acc. neut. pl.'] }] },
    { i: 1, start: 5, end: 9, printed: 'ἔρος', lemma: null, parses: [] }] };
  const values = tools.batchHeadlines(payload, text, short => `plain:${short}`);
  const tie = plain(values.get('3:5'));
  assert.equal(text.slice(3, 5), 'σ’');
  assert.equal(tie.lemma, 'σύ'); assert.equal(tie.parse, 'acc. 2nd sg.'); assert.equal(tie.tie, true); assert.equal(tie.provisional, true);
  assert.deepEqual(tie.alternatives, [{ lemma: 'σός', parse: 'plain:acc. neut. pl.', short: 'acc. neut. pl.', gloss: 'thy', form: '' }]);
  assert.equal(values.get('6:10').lemma, '', 'a token without a headword is kept but not shown as one');
  assert.equal(tools.batchHeadlines({}, text).size, 0);
});
