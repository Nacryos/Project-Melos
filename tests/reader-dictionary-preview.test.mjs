import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// UI-only fixtures: no source data or dictionary claims are created here.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {} }); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const ui = { dictionaryPreview: new Element('div'), language: { value: '' }, inspector: { closest: () => ({ scrollIntoView() {} }) } };
const state = { dictionarySequence: 0, dictionaryCache: new Map() };
const pending = new Map();
const opened = [];
const fixture = query => ({ query, entries: [{ lemma: query, analyses: [{ text: 'recorded fixture analysis' }], meanings: [{ text: '<literal fixture gloss>', source: 'Fixture source', source_url: 'https://example.org/entry' }] }], ambiguous: false });
const context = vm.createContext({
  ui, state, window: { MelosDictionaryPreview: { isCandidateQuery: query => !query.includes(' '), buildPreview: data => data } },
  clear: element => element.replaceChildren(), node: (tag, cls, text) => new Element(tag, cls, text),
  safeLink: (url, label) => url ? Object.assign(new Element('a', '', label), { href: url }) : null,
  inspectWord: form => opened.push(form), api: (path, { form }) => path === '/api/wiktionary'
    ? Promise.resolve(null) : new Promise((resolve, reject) => pending.set(form, { resolve, reject })),
});
vm.runInContext(script.slice(script.indexOf('  function renderDictionaryPreview('), script.indexOf('  async function search(')), context);
const load = vm.runInContext('loadDictionaryPreview', context);
const render = vm.runInContext('renderDictionaryPreview', context);
function descendants(root) { return root.children.flatMap(child => [child, ...descendants(child)]); }

test('preview displays short sourced meanings as text and opens the selected lemma', () => {
  const host = new Element('div');
  assert.equal(render(host, fixture('FixtureLemma')), true);
  assert.match(host.textContent, /<literal fixture gloss>/);
  assert.match(host.textContent, /recorded fixture analysis/);
  assert.equal(descendants(host).find(el => el.tag === 'a').href, 'https://example.org/entry');
  descendants(host).find(el => el.tag === 'button').handlers.click();
  assert.equal(opened.at(-1), 'FixtureLemma');
  const compact = new Element('div');
  render(compact, fixture('FixtureLemma'), { openEntries: false });
  assert.equal(descendants(compact).filter(el => el.tag === 'button').length, 0);
});

test('an older slow lookup cannot replace the newer query preview', async () => {
  const old = load('older');
  const fresh = load('newer');
  pending.get('newer').resolve(fixture('newer')); await fresh;
  pending.get('older').resolve(fixture('older')); await old;
  assert.match(ui.dictionaryPreview.textContent, /newer/);
  assert.ok(!ui.dictionaryPreview.textContent.includes('older'));
  assert.equal(ui.dictionaryPreview.hidden, false);
});

test('nonword queries, Modern Greek filters and failed lookups do not fabricate a preview', async () => {
  await load('several query words');
  assert.equal(ui.dictionaryPreview.hidden, true);
  assert.ok(!pending.has('several query words'));
  ui.language.value = 'ell'; await load('modern'); ui.language.value = '';
  assert.ok(!pending.has('modern'));
  const failed = load('missing'); pending.get('missing').reject(new Error('fixture outage')); await failed;
  assert.equal(ui.dictionaryPreview.hidden, true);
  assert.equal(ui.dictionaryPreview.children.length, 0);
});

test('empty dictionary matches leave space to the passage results', () => {
  assert.equal(render(new Element('div'), { entries: [] }), false);
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('id="dictionary-preview"') < html.indexOf('id="results-list"'));
  assert.ok(html.indexOf('js/dictionary-preview.js') < html.indexOf('js/reader.js'));
});

test('one lemma heading groups dictionary sources without conflating their excerpts', () => {
  const host = new Element('div');
  const data = fixture('FixtureLemma');
  data.entries.push({ ...data.entries[0], source: 'Another dictionary', meanings: [{ text: 'Another literal excerpt', source: 'Another dictionary', source_url: 'https://example.org/other' }] });
  render(host, data);
  assert.equal(descendants(host).filter(element => element.tag === 'h3').length, 1);
  assert.equal(descendants(host).filter(element => element.cls === 'dictionary-glimpse-entry').length, 2);
  assert.match(host.textContent, /<literal fixture gloss>/);
  assert.match(host.textContent, /Another literal excerpt/);
});
