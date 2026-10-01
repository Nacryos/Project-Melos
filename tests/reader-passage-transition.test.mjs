import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic asynchronous UI fixtures, not corpus entries or philological claims.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', value = '') {
    Object.assign(this, { tag, cls, value, children: [], handlers: {}, attributes: {}, dataset: {}, hidden: false,
      classList: { add() {}, remove() {} } });
  }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; this.value = ''; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  contains(element) { return element === this || this.children.some(child => child.contains?.(element)); }
  querySelectorAll(selector) { return this.children.filter(child => selector === '[data-phrase-mode]' ? child.dataset.phraseMode : child.cls === 'word'); }
  scrollIntoView() {}
  remove() {}
  get textContent() { return this.value + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.value = value; this.children = []; }
}
function harness() {
  const keys = ['passage', 'title', 'subtitle', 'kicker', 'text', 'textLeading', 'readingHint', 'provenance',
    'related', 'inspector', 'prev', 'next', 'selectionActions', 'selectedPhrase', 'results'];
  const ui = Object.fromEntries(keys.map(key => [key, new Element()]));
  const oldWord = new Element('button', 'word', 'old word');
  ui.text.append(oldWord);
  ui.title.textContent = 'Old author'; ui.subtitle.textContent = 'Old fragment';
  ui.related.textContent = 'Old commentary'; ui.provenance.textContent = 'Old provenance';
  ui.inspector.textContent = 'Old word classification';
  const phraseAction = new Element('button'); phraseAction.dataset.phraseMode = 'words';
  ui.selectionActions.append(phraseAction); ui.selectedPhrase.textContent = 'Old selection';
  const state = { passage: { id: 'old', related: [{ text: 'Old commentary' }] }, selectedText: 'Old selection',
    activeWord: oldWord, passageLoading: false, passageSequence: 0, wordSequence: 0,
    works: new Map(), selectedAuthor: 'Old author', selectedWork: 'old-work', classifierStatus: { configured: true } };
  const requests = [], posts = [];
  const context = vm.createContext({
    ui, state, URL, location: { href: 'https://example.test/?id=old' }, history: { replaceState() {} },
    window: { getSelection: () => null, matchMedia: () => ({ matches: false }) },
    errorText: error => error.message, clear: element => element.replaceChildren(),
    node: (tag, cls, value) => new Element(tag, cls, value),
    message(element, value) { element.textContent = value; },
    renderAuthors() {}, renderPassageText: passage => { ui.text.textContent = passage.text; },
    renderRelated: related => { ui.related.textContent = related?.[0]?.text || ''; ui.related.hidden = !related?.length; },
    renderMirrors() {}, renderProvenance: passage => { ui.provenance.textContent = passage.id; ui.provenance.hidden = false; },
    renderWiktionary(host) { host.textContent = 'STALE WIKI'; },
    addInspectorSection(label, host) { const section = new Element(); host.append(section); return section; },
    api(path, params) { return new Promise((resolve, reject) => requests.push({ path, params, resolve, reject })); },
    apiPost: (...args) => { posts.push(args); return Promise.resolve({}); }
  });
  for (const [start, end] of [
    ['  function resetPassageContext(', '  // Shared literal lexer:'],
    ['  async function openPassage(', '  function appendWarnings('],
    ['  async function loadWiktionary(', '  function foldGreekForm('],
    ['  function addContextAction(', '  function renderFormInventories('],
    ['  async function inspectWord(', '  function updateSelection(']
  ]) vm.runInContext(script.slice(script.indexOf(start), script.indexOf(end)), context);
  const lookup = name => vm.runInContext(name, context);
  return { ui, state, oldWord, requests, posts, open: lookup('openPassage'), selectWork: lookup('selectWork'),
    inspectWord: lookup('inspectWord'), addContextAction: lookup('addContextAction') };
}
const passage = id => ({ id, author: `Author ${id}`, work: 'Fixture work', citation: `Fragment ${id}`,
  kind: 'text', text: `Text ${id}`, related: [{ text: `Commentary ${id}` }] });

test('starting passage load synchronously removes every old context and disables navigation/selection', async () => {
  const h = harness(), pending = h.open('new');
  assert.equal(h.state.passage, null);
  assert.equal(h.state.passageLoading, true);
  assert.equal(h.state.activeWord, null);
  assert.equal(h.state.selectedText, '');
  assert.equal(h.ui.subtitle.textContent, '');
  assert.equal(h.ui.related.textContent, '');
  assert.equal(h.ui.provenance.textContent, '');
  assert.equal(h.ui.related.hidden, true);
  assert.equal(h.ui.prev.disabled, true); assert.equal(h.ui.next.disabled, true);
  assert.equal(h.ui.selectionActions.hidden, true);
  assert.equal(h.ui.selectionActions.children[0].disabled, true);
  assert.equal(h.ui.selectedPhrase.textContent, '');
  assert.equal(h.ui.passage.attributes['aria-busy'], 'true');
  assert.ok(!h.ui.inspector.textContent.includes('Old'));
  h.requests[0].resolve(passage('new')); await pending;
  assert.equal(h.state.passage.id, 'new');
  assert.equal(h.ui.subtitle.textContent, 'Fragment new');
  assert.equal(h.ui.related.textContent, 'Commentary new');
  assert.equal(h.ui.passage.attributes['aria-busy'], 'false');
});

test('failed replacement never leaves the former passage available for classification', async () => {
  const h = harness(), pending = h.open('broken');
  h.requests[0].reject(new Error('Fixture transport failure')); await pending;
  assert.equal(h.state.passage, null);
  assert.equal(h.state.passageLoading, false);
  assert.equal(h.ui.title.textContent, 'Passage unavailable');
  assert.equal(h.ui.subtitle.textContent, '');
  assert.equal(h.ui.related.textContent, '');
  assert.equal(h.ui.prev.disabled, true);
  assert.equal(h.ui.passage.attributes['aria-busy'], 'false');
});

test('slow older passage success or failure cannot replace a newer passage', async () => {
  const h = harness(), first = h.open('first'), second = h.open('second');
  h.requests[1].resolve(passage('second')); await second;
  h.requests[0].reject(new Error('Late old failure')); await first;
  assert.equal(h.state.passage.id, 'second');
  assert.equal(h.ui.subtitle.textContent, 'Fragment second');
});

test('late work enumeration cannot start another passage after an explicit passage was selected', async () => {
  const h = harness(), work = h.selectWork({ id: 'work-a', work: 'Work A', author: 'Author A' });
  const explicit = h.open('explicit');
  h.requests[1].resolve(passage('explicit')); await explicit;
  h.requests[0].resolve({ results: [{ id: 'unwanted', language: 'grc', kind: 'text' }] }); await work;
  assert.equal(h.requests.length, 2);
  assert.equal(h.state.passage.id, 'explicit');
});

test('pending word/Wiktionary results and old word buttons cannot restore stale context during transition', async () => {
  const h = harness();
  const oldLookup = h.inspectWord('fixture', h.oldWord);
  assert.equal(h.requests.length, 2);
  const pending = h.open('new');
  const openingMessage = h.ui.inspector.textContent;
  h.requests.find(request => request.path === '/api/word').resolve({ normalized: 'fixture' });
  h.requests.find(request => request.path === '/api/wiktionary').resolve({ ready: true });
  await oldLookup; await Promise.resolve();
  assert.equal(h.ui.inspector.textContent, openingMessage);
  await h.inspectWord('fixture', h.oldWord);
  assert.equal(h.requests.length, 3);
  h.requests[2].resolve(passage('new')); await pending;
  await h.inspectWord('fixture', h.oldWord);
  assert.equal(h.requests.length, 3);
});

test('a detached old classifier action cannot spend a paid call after the passage changes', async () => {
  const h = harness();
  h.addContextAction(h.ui.inspector, 'fixture', 'old', h.state.wordSequence);
  const action = h.ui.inspector.children[0].children.find(element => element.tag === 'button');
  const pending = h.open('new');
  await action.handlers.click();
  assert.equal(h.posts.length, 0);
  h.requests[0].resolve(passage('new')); await pending;
});
