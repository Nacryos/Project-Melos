import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/usage-space.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [], style: {}, dataset: {}, attributes: {} });
  }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener() {}
  get childElementCount() { return this.children.length; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.text = value; this.children = []; }
}
const context = vm.createContext({
  element: (...args) => new Element(...args), dateLabel: () => '', safeUrl: () => null,
  URLSearchParams,
});
vm.runInContext(source.slice(source.indexOf('  function colorFor('), source.indexOf('  function open(')), context);
vm.runInContext('draw = () => {}', context);
const colorAuthor = vm.runInContext('colorAuthor', context);
const populate = vm.runInContext('populate', context);
const showDetail = vm.runInContext('showDetail', context);

test('canonical display key has safe raw-label fallback without client alias guessing', () => {
  assert.equal(colorAuthor({ author: 'ΙΒΥΚΟΣ', author_canonical: 'Ibycus' }), 'Ibycus');
  assert.equal(colorAuthor({ author: 'ΙΒΥΚΟΣ' }), 'ΙΒΥΚΟΣ');
  assert.equal(colorAuthor({ author: 'Raw label', author_canonical: '  ' }), 'Raw label');
  assert.equal(colorAuthor({ author: 'Raw label', author_canonical: {} }), 'Raw label');
  assert.equal(colorAuthor({}), 'Unknown author');
});

test('aliases share legend and swatch colors but mixed attribution and scholia stay separate', () => {
  const state = Object.fromEntries(['status', 'count', 'method', 'warnings', 'list', 'legend', 'detail'].map(key => [key, new Element('div')]));
  const rows = [
    ['Ibycus', 'Ibycus'], ['ΙΒΥΚΟΣ', 'Ibycus'],
    ['Homer', 'Homer'], ['homerus-epic', 'Homer'],
    ['scholia-in-homerum', 'scholia-in-homerum'], ['Sappho / Alcaeus', 'Sappho / Alcaeus'],
  ].map(([author, author_canonical], i) => ({ id: `synthetic:${i}`, author, author_canonical,
    x: i, y: 0, z: 0, text: 'Synthetic text', citation: `Synthetic ${i}` }));
  const original = JSON.stringify(rows);
  populate(state, { points: rows });
  assert.equal(state.legend.children.length, 4);
  const colors = state.list.children.map(li => li.children[0].children[0].children[0].style.background);
  assert.equal(colors[0], colors[1]);
  assert.equal(colors[2], colors[3]);
  assert.notEqual(colors[2], colors[4]);
  assert.notEqual(colors[0], colors[5]);
  assert.match(state.list.textContent, /ΙΒΥΚΟΣ/);
  assert.equal(JSON.stringify(rows), original);
});

test('passage details preserve original author spelling and exact citation', () => {
  const point = { id: 'synthetic', author: 'ΙΒΥΚΟΣ', author_canonical: 'Ibycus',
    citation: 'Synthetic citation 286', work: 'Synthetic work', text: 'Synthetic text' };
  const state = { points: [point], detail: new Element('div') };
  showDetail(state, point, false);
  assert.match(state.detail.textContent, /ΙΒΥΚΟΣ · Synthetic work · Synthetic citation 286/);
  assert.equal(point.author, 'ΙΒΥΚΟΣ');
});
