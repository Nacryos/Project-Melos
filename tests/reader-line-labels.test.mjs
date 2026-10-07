import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic mechanics fixtures only; no literary source claims or data writes.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [], dataset: {}, attributes: {}, handlers: {} });
    const classes = new Set(cls.split(/\s+/).filter(Boolean));
    this.classList = { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }, contains: name => classes.has(name) };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, handler) { this.handlers[type] = handler; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const clicks = [];
const fits = [];
const ui = { text: new Element('div'), textLeading: {}, readingHint: {} };
const context = vm.createContext({
  state: {},
  ui, node: (tag, cls, text) => new Element(tag, cls, text),
  window: { MelosVerseFit: { watch: (host, selector) => fits.push(['watch', host, selector]), unwatch: host => fits.push(['unwatch', host]) } },
  document: { createTextNode: text => new Element('#text', '', text) },
  clear: element => element.replaceChildren(), inspectWord: (...args) => clicks.push(args),
});
vm.runInContext(source.slice(source.indexOf('  function literalGreekWords('), source.indexOf('  function addMeta(')), context);
const label = vm.runInContext('separateLineLabel', context);
const render = vm.runInContext('renderPassageText', context);
const words = vm.runInContext('readingWords', context);
const verseLines = vm.runInContext('verseLines', context);

test('Modern Greek translations preserve text without Ancient Greek inspection buttons', () => {
  for (const text of ['αβ γδ', 'αβ\n γδ ']) {
    render({ kind: 'translation', language: 'ell', text });
    const all = element => element.children.flatMap(child => [child, ...all(child)]);
    assert.equal(all(ui.text).filter(element => element.tag === 'button').length, 0);
    assert.equal(all(ui.text).filter(element => element.tag === '#text').map(element => element.text).join('\n'), text);
    assert.match(ui.readingHint.textContent, /Modern Greek translation/);
    assert.match(ui.readingHint.textContent, /linked Ancient Greek/);
    assert.equal(ui.text.lang, 'ell');
  }
});

test('an exact printed numeric label suppresses only its duplicate UI label', () => {
  for (const value of ['1', '5', '10']) {
    assert.equal(label({ label: value, text: `${value}. αβ` }), '');
    assert.equal(label({ label: value, text: ` \t${value}\u00a0. αβ` }), '');
    assert.equal(label({ label: value, text: `${value}.` }), '');
  }
  assert.equal(label({ label: 5, text: '5. αβ' }), '');
});

test('ordinary, mismatched and ambiguous number or lacuna prefixes retain UI labels', () => {
  for (const text of ['αβ', '10. αβ', '01. αβ', '1 αβ', '1.5 αβ', '1.. αβ', '1–5. αβ', '[1. αβ', '⟨ ⟩ 1. αβ', '… 1. αβ']) {
    assert.equal(label({ label: '1', text }), '1', text);
  }
  assert.equal(label({ label: '1a', text: '1a. αβ' }), '1a');
  assert.equal(label({ label: '1.', text: '1. αβ' }), '1.');
  assert.equal(label({ label: '', text: '5. αβ' }), '');
});

test('printed labels can directly precede Greek or editorial brackets without matching decimals', () => {
  for (const text of ['4.αβ', '4.ἀβ', '4.]. αβ', '4.[.] αβ', '4.⟨ ⟩ αβ', '4.⟩ αβ']) {
    assert.equal(label({ label: '4', text }), '', text);
    render({ language: 'grc', kind: 'text', lines: [{ label: '4', text }] });
    assert.equal(ui.text.children[0].children[0].textContent, '');
    assert.equal(ui.text.children[0].children[1].textContent, text);
  }
  for (const text of ['4.5 αβ', '4.. αβ', '4...αβ', '4.· αβ', '4.a', '[.]4.αβ', '4.\u0323αβ']) {
    assert.equal(label({ label: '4', text }), '4', text);
  }
});

test('rendered source characters and word offsets stay exact when duplicate labels disappear', () => {
  const lines = [
    { label: '1', text: '1. α\u0323β [ . ] γδ' },
    { label: '5', text: '\t5. εζ’ ηθ' },
    { label: '', text: '⟨ ⟩' },
  ];
  const before = JSON.stringify(lines);
  render({ language: 'grc', kind: 'text', lines });
  assert.equal(JSON.stringify(lines), before);
  assert.equal(ui.text.children.length, 3);
  const originalText = lines.map(line => line.text).join('\n');
  const units = words(originalText);
  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const row = ui.text.children[i];
    assert.equal(row.children[0].textContent, '');
    assert.equal(row.children[1].textContent, lines[i].text);
    assert.equal(row.textContent, lines[i].text);
    for (const button of row.children[1].children.filter(child => child.tag === 'button')) {
      const expected = units.find(unit => String(unit.group) === button.dataset.lookupGroup);
      assert.ok(expected.start >= offset);
      assert.equal(originalText.slice(expected.start, expected.end), button.textContent);
      button.handlers.click();
      assert.equal(clicks.at(-1)[0], expected.form);
    }
    offset += lines[i].text.length + 1;
  }
});

test('normal metadata labels remain and printed numbering still blocks unsafe cross-line joins', () => {
  const lines = [{ label: '1', text: 'αβ-' }, { label: '2', text: '2. γδ' }, { label: '3', text: 'εζ' }];
  render({ language: 'grc', kind: 'text', lines });
  assert.equal(ui.text.children[0].children[0].textContent, '1');
  assert.equal(ui.text.children[1].children[0].textContent, '');
  assert.equal(ui.text.children[2].children[0].textContent, '3');
  assert.ok(words(lines.map(line => line.text).join('\n')).every(word => !word.joined));
});

test('fallback verse lines preserve indentation, trailing spaces, blank rows and source word offsets', () => {
  const text = '  αβ- \n\tγδ  \n\n εζ\t';
  const passage = { kind: 'text', language: 'grc', text };
  const lines = verseLines(passage);
  assert.equal(lines.map(line => line.text).join('\n'), text);
  render(passage);
  assert.equal(ui.text.children.map(row => row.children[1].textContent).join('\n'), text);
  assert.equal(ui.text.children[2].cls, 'line blank');
  assert.equal(ui.text.classList.contains('verse-fit'), true);
  assert.equal(fits.at(-1)[0], 'watch');
  assert.equal(fits.at(-1)[2], '.line');
  const units = words(text);
  for (const row of ui.text.children) {
    for (const button of row.children[1].children.filter(child => child.tag === 'button')) {
      const expected = units.find(unit => String(unit.group) === button.dataset.lookupGroup && unit.text === button.textContent);
      assert.ok(expected);
      assert.equal(text.slice(expected.start, expected.end), button.textContent);
      button.handlers.click();
      assert.equal(clicks.at(-1)[0], expected.form);
    }
  }
  assert.equal(units[0].form, 'αβγδ');
  assert.equal(units[1].group, units[0].group);
});

test('short Greek text is fitted while undivided prose exits fitting without losing source text', () => {
  render({ kind: 'text', language: 'grc', text: ' αβ ' });
  assert.equal(ui.text.classList.contains('verse-fit'), true);
  assert.equal(ui.text.children[0].children[1].textContent, ' αβ ');
  const prose = '  A synthetic prose sentence with no line division.  ';
  render({ kind: 'commentary', language: 'eng', text: prose });
  assert.equal(ui.text.classList.contains('verse-fit'), false);
  assert.equal(fits.at(-1)[0], 'unwatch');
  assert.equal(ui.text.textContent, prose);
});
