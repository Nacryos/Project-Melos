import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic source scopes verify presentation, not source attribution claims.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {} }); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  querySelector(selector) { return descendants(this).find(child => child.cls === selector.slice(1)) || null; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
function descendants(root) { return root.children.flatMap(child => [child, ...descendants(child)]); }
const ui = { related: new Element('div') };
const opened = [];
const context = vm.createContext({
  ui, state: { passage: { id: 'selected-record' } }, openPassage: id => opened.push(id),
  clear: element => element.replaceChildren(), node: (tag, cls, text) => new Element(tag, cls, text),
  safeLink: (url, label) => url ? Object.assign(new Element('a', '', label), { href: url }) : null,
});
vm.runInContext(script.slice(script.indexOf('  function renderRelated('), script.indexOf('  async function openPassage(')), context);
const render = vm.runInContext('renderRelated', context);
function show(records) { render(records); return ui.related; }

test('source-section notes disclose source labels and remain collapsed and nonaligned', () => {
  const host = show([{ id: 'section-note', kind: 'commentary', citation: 'Section citation', edition: 'Fixture edition', text: 'Verbatim fixture note.', source_url: 'https://example.org/page', metadata: { scope: 'source_section', source_heading: 'Source heading', source_section: 'Column A' } }]);
  assert.match(host.textContent, /not annotations aligned to the selected passage/);
  assert.match(host.textContent, /Source-section note · not passage-aligned/);
  assert.match(host.textContent, /Source section \/ citation: Source heading · Column A · Section citation/);
  const details = descendants(host).find(element => element.tag === 'details');
  assert.ok(details);
  assert.equal(details.open, undefined);
  assert.match(details.textContent, /Read commentary from this source section/);
  assert.ok(details.textContent.includes('Verbatim fixture note.'));
  assert.equal(descendants(host).filter(element => element.tag === 'button').length, 0);
  assert.equal(descendants(host).find(element => element.tag === 'a').href, 'https://example.org/page');
});

test('page notes stay collapsed and a nonaligned scope never gets a directly linked reading button', () => {
  const host = show([{ id: 'page-note', parent_id: 'selected-record', kind: 'translation', text: 'Fixture page text', metadata: { scope: 'page' } }]);
  assert.match(host.textContent, /Page-wide note/);
  assert.match(host.textContent, /Read translation from this source page/);
  assert.equal(descendants(host).filter(element => element.tag === 'details').length, 1);
  assert.equal(descendants(host).filter(element => element.tag === 'button').length, 0);
});

test('passage-linked material retains its ordinary inline display and reading control', () => {
  const host = show([{ id: 'linked-translation', parent_id: 'selected-record', kind: 'translation', text: 'Fixture translation', language: 'eng', metadata: { scope: 'passage' } }]);
  assert.equal(descendants(host).filter(element => element.tag === 'details').length, 0);
  assert.ok(!host.textContent.includes('not passage-aligned'));
  const button = descendants(host).find(element => element.tag === 'button');
  assert.ok(button); button.handlers.click();
  assert.equal(opened.at(-1), 'linked-translation');
});

test('linked Modern Greek translations show their own source credit and language', () => {
  const host = show([{ id: 'modern-translation', parent_id: 'selected-record', author: 'Fixture author', kind: 'translation', language: 'ell', text: 'Synthetic translation fixture', metadata: { translator: 'Source credit <literal>' } }]);
  assert.match(host.textContent, /Modern Greek · Translator: Source credit <literal>/);
  assert.ok(!host.textContent.includes('Fixture author'));
  const button = descendants(host).find(element => element.tag === 'button');
  assert.ok(button); button.handlers.click();
  assert.equal(opened.at(-1), 'modern-translation');
});

test('a Perseus record ancient author is not relabelled as its translator', () => {
  const host = show([{ id: 'fixture:perseus:translation', source: 'perseus', parent_id: 'selected-record',
    kind: 'translation', language: 'eng', author: 'Euripides', edition: 'Synthetic edition label',
    text: 'Synthetic translation text.', source_url: 'https://example.org/fixture-translation',
    metadata: { cts_urn: 'fixture:edition' } }]);
  assert.match(host.textContent, /English · Translator not recorded/);
  assert.ok(!host.textContent.includes('Translator: Euripides'));
  assert.match(host.textContent, /Synthetic edition label/);
  assert.equal(descendants(host).find(element => element.tag === 'a').href, 'https://example.org/fixture-translation');
});

test('missing or nontext translator metadata stays explicitly unknown', () => {
  for (const translator of [undefined, null, '', '   ', { name: 'Not a source string' }]) {
    const host = show([{ id: 'fixture:translation', kind: 'translation', language: 'ell',
      author: 'Ancient author', text: 'Synthetic text.', metadata: { translator } }]);
    assert.match(host.textContent, /Modern Greek · Translator not recorded/);
    assert.ok(!host.textContent.includes('Translator:'));
  }
});
