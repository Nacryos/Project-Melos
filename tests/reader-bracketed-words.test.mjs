import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Tokeniser mechanics for words printed with editorial marks. Strings are
// test fixtures, not literary evidence.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls, text = '') { Object.assign(this, { tag, cls, text, dataset: {}, children: [], attributes: {}, handlers: {} }); }
  append(child) { this.children.push(child); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, handler) { this.handlers[type] = handler; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const clicks = [];
const context = vm.createContext({
  window: { getSelection: () => null }, state: {},
  node: (tag, cls, text) => new Element(tag, cls, text),
  document: { createTextNode: text => new Element('text', '', text) },
  inspectWord: (...args) => clicks.push(args),
});
vm.runInContext(source.slice(source.indexOf('  function literalGreekWords('), source.indexOf('  function renderPassageText(')), context);
const words = vm.runInContext('readingWords', context);
const render = vm.runInContext('appendTextWithWords', context);
const units = text => Array.from(words(text), unit => [unit.text, unit.form]);

test('every editorial bracket pair inside a word keeps one unit with a clean lookup key', () => {
  for (const [printed, form] of [
    ['ἐ[πί]σταμαι', 'ἐπίσταμαι'], ['[κ]ακῶν', 'κακῶν'], ['κακ[ῶν]', 'κακῶν'],
    ['ἀμφι⟨βάλων⟩', 'ἀμφιβάλων'], ['ἀ⟦ε⟧λίω', 'ἀελίω'], ['κα{ι}λός', 'καιλός'], ['βα(σιλεύς)', 'βασιλεύς'],
    ['κ[άλ]λιστος', 'κάλλιστος'], ['κά[τε]σσαν', 'κάτεσσαν'], ['[ἐπίσταμαι]', 'ἐπίσταμαι'],
    ['κ̣[ακ]ῶν', 'κακῶν'], ['ἐ[πί]στα̣μαι', 'ἐπίσταμαι'],
  ]) {
    const text = `α ${printed} β`;
    assert.deepEqual(units(text), [['α', 'α'], [printed, form], ['β', 'β']], printed);
    const unit = words(text)[1];
    assert.equal(text.slice(unit.start, unit.end), printed);
    assert.equal(unit.editorial, true);
    assert.equal(unit.fragmentaryJoinRejected, undefined, printed);
  }
});

test('elision marks stay with the word, including next to brackets', () => {
  assert.deepEqual(units('δ’ ἔννεκ[’] ἔργων'), [['δ’', 'δ’'], ['ἔννεκ[’]', 'ἔννεκ’'], ['ἔργων', 'ἔργων']]);
  assert.deepEqual(units('ἄμ[μ’] ἔχω'), [['ἄμ[μ’]', 'ἄμμ’'], ['ἔχω', 'ἔχω']]);
});

test('a bracket at a word edge attaches to its letters and marks a printed segment', () => {
  assert.deepEqual(units('[ . . . ]σταμαι'), [[']σταμαι', 'σταμαι']]);
  assert.deepEqual(units('λίπον Δ['), [['λίπον', 'λίπον'], ['Δ[', 'Δ']]);
  assert.deepEqual(units('ζάβαι[ς ἀ]ελίω'), [['ζάβαι[ς', 'ζάβαις'], ['ἀ]ελίω', 'ἀελίω']]);
  const [edge] = words('[ . . . ]σταμαι'), [, open] = words('λίπον Δ[');
  assert.equal(edge.fragmentaryJoinRejected, true);
  assert.equal(open.fragmentaryJoinRejected, true);
  // A word whose bracket closes later (δρό[μωμεν) still ends on a letter.
  assert.equal(words('δρό[μωμεν·')[0].fragmentaryJoinRejected, undefined);
});

test('lacunae with only dots, spaces or marks never become words', () => {
  for (const text of ['[ ]', '[. . .]', '[…]', '[    ]', '[̣]', '⟨ ⟩', '[ . . . . ]', '( )', '[.]  [ ]']) {
    assert.deepEqual(units(text), [], text);
  }
  assert.deepEqual(units('α [ . . . ] β'), [['α', 'α'], ['β', 'β']]);
});

test('rendered buttons show the brackets exactly as printed and inspect the clean form', () => {
  const text = 'ἐ[πί]σταμαι [κ]ακῶν [ . . . ]σταμαι';
  const host = new Element('p');
  render(host, text, words(text));
  assert.equal(host.textContent, text);
  const buttons = host.children.filter(child => child.tag === 'button');
  assert.deepEqual(buttons.map(button => button.textContent), ['ἐ[πί]σταμαι', '[κ]ακῶν', ']σταμαι']);
  buttons[0].handlers.click();
  assert.equal(clicks.at(-1)[0], 'ἐπίσταμαι');
  assert.equal(clicks.at(-1)[3], false);
  assert.match(buttons[0].attributes['aria-label'], /^Inspect ἐπίσταμαι, printed ἐ\[πί\]σταμαι$/);
  buttons[2].handlers.click();
  assert.equal(clicks.at(-1)[0], 'σταμαι');
  assert.equal(clicks.at(-1)[3], true);
});

test('line-end divisions never join through an editorially marked segment', () => {
  for (const input of ['α[β]-\nγδ', 'αβ-\nγ[δ]', 'αβ-\nγ̣δ']) {
    assert.ok(words(input).every(unit => !unit.joined), input);
  }
  assert.ok(words('αβ-\nγδ [ε]').slice(0, 2).every(unit => unit.joined));
});

// Span selection in passage-analysis.js: drags and counts treat the bracketed word as one.
const analysisWindow = {};
vm.runInNewContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), { window: analysisWindow, AbortController });
const { selectedSpan, selectionIssue } = analysisWindow.MelosPassageAnalysis;

test('a drag that starts or ends inside a bracketed word covers the whole word', () => {
  const sourceText = 'ἐ[πί]σταμαι [κ]ακῶν φάτιν';
  const leaf = (data, word) => ({ data, parentElement: { classList: { contains: name => word && name === 'word' } } });
  const leaves = [leaf('ἐ[πί]σταμαι', true), leaf(' ', false), leaf('[κ]ακῶν', true), leaf(' ', false), leaf('φάτιν', true)];
  const map = new Map(); let offset = 0;
  for (const item of leaves) { map.set(item, { start: offset, end: offset + item.data.length }); offset += item.data.length; }
  const root = { contains: () => true, ownerDocument: { createTreeWalker() {
    let cursor = -1; return { currentNode: null, nextNode() { this.currentNode = leaves[++cursor]; return this.currentNode || null; } };
  } } };
  const select = (first, low, last, high) => ({ rangeCount: 1, getRangeAt: () => ({ collapsed: false,
    startContainer: leaves[first], startOffset: low, endContainer: leaves[last], endOffset: high,
    intersectsNode: item => leaves.indexOf(item) >= first && leaves.indexOf(item) <= last }) });
  // Drag from inside "πί" to inside "ακῶν".
  assert.equal(selectedSpan(select(0, 3, 2, 4), root, map, sourceText).selected_text, 'ἐ[πί]σταμαι [κ]ακῶν');
  // Starting just after a word, or ending just before one, does not pull it in.
  assert.equal(selectedSpan(select(0, 11, 2, 0), root, map, sourceText).selected_text, ' ');
  assert.equal(selectedSpan(select(2, 2, 2, 3), root, map, sourceText).selected_text, '[κ]ακῶν');
});

test('the 80-word limit counts a bracketed word once', () => {
  assert.equal(selectionIssue({ selected_text: Array(80).fill('ἐ[πί]σταμαι').join(' ') }), '');
  assert.match(selectionIssue({ selected_text: Array(81).fill('[κ]ακῶν').join(' ') }), /80 words/);
  assert.equal(selectionIssue({ selected_text: Array(70).fill('α [ . . . ]').join(' ') }), '');
});
