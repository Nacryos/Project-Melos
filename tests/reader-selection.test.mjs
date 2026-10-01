import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic DOM mechanics only. Text-node offsets are UTF-16 DOM offsets;
// element offsets are child indices, as in the Range API.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', children = []) {
    Object.assign(this, { tag, cls, childNodes: [], parentElement: null });
    for (const child of children) this.append(child);
  }
  append(child) { child.parentElement = this; this.childNodes.push(child); }
  contains(node) { return this === node || this.childNodes.some(child => child === node || child.contains?.(node)); }
  closest(selector) {
    if (selector.split(',').some(part => part.trim().startsWith('.')
      ? this.cls.split(' ').includes(part.trim().slice(1)) : this.tag === part.trim())) return this;
    return this.parentElement?.closest(selector) || null;
  }
  get textContent() { return this.childNodes.map(child => child.data ?? child.textContent).join(''); }
}
const text = data => ({ data, parentElement: null });
const words = (...values) => values.map((value, index) => index % 2 ? text(value) : new Element('button', 'word', [text(value)]));
function fixture(lines) {
  const root = new Element('div', 'greek-text', lines.map(([label, ...values]) => new Element('div', 'line', [
    new Element('span', 'line-label', [text(label)]), new Element('span', 'line-content', words(...values)),
  ])));
  function texts(node) { return node.data != null ? [node] : node.childNodes.flatMap(texts); }
  root.ownerDocument = { createTreeWalker(target, mask) {
    assert.equal(mask, 4); const nodes = texts(target); let index = -1;
    return { currentNode: null, nextNode() { this.currentNode = nodes[++index]; return this.currentNode || null; } };
  } };
  const offset = node => {
    let result = 0;
    for (const current of texts(root)) { if (current === node || node.contains?.(current)) return result; result += current.data.length; }
    return result;
  };
  const boundary = (node, position) => offset(node) + (node.data != null ? position
    : node.childNodes.slice(0, position).reduce((sum, child) => sum + (child.data ?? child.textContent).length, 0));
  function select(start, startOffset, end, endOffset, backward = false) {
    const low = boundary(start, startOffset), high = boundary(end, endOffset);
    const range = { startContainer: start, startOffset, endContainer: end, endOffset, collapsed: low === high,
      intersectsNode(node) { const beginning = offset(node); return beginning < high && beginning + node.data.length > low; } };
    return { rangeCount: 1, getRangeAt: () => range,
      anchorNode: backward ? end : start, focusNode: backward ? start : end,
      toString() { throw new Error('Selection.toString must not reintroduce rendered labels'); } };
  }
  return { root, select, texts, content: index => texts(root.childNodes[index].childNodes[1]), label: index => texts(root.childNodes[index].childNodes[0])[0] };
}
function harness(f) {
  let selection = null;
  const state = { passage: { id: 'synthetic' }, passageLoading: false, selectedText: '' };
  const button = { disabled: true }, translation = { disabled: false }, buttons = [button];
  const classes = new Set();
  const ui = { text: f.root, selectedPhrase: {}, selectionActions: { hidden: true,
    classList: { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) },
    querySelectorAll: selector => selector === 'button' ? buttons : [button] } };
  const context = vm.createContext({ state, ui, window: { getSelection: () => selection },
    updateSelectionTranslationAction: () => { if (state.translationAvailable && !buttons.includes(translation)) buttons.push(translation); } });
  vm.runInContext(script.slice(script.indexOf('  function selectedPassageText('), script.indexOf('  async function initialize(')), context);
  return { state, ui, button, translation, extract: context.selectedPassageText,
    update(value) { selection = value; context.updateSelection(); } };
}

test('cross-line forward and backward selections exclude metadata digits and preserve partial bounds', () => {
  const f = fixture([['4', 'before αβγ', ' ', 'δεζ'], ['5', 'ἥβη', ' ', 'τιμήεσσα after']]), h = harness(f);
  const start = f.content(0)[0], end = f.content(1)[2];
  for (const backwards of [false, true]) {
    const selection = f.select(start, 7, end, 'τιμήεσσα'.length, backwards);
    assert.equal(h.extract(selection, f.root), 'αβγ δεζ\nἥβη τιμήεσσα');
    h.update(selection); assert.equal(h.state.selectedText, 'αβγ δεζ ἥβη τιμήεσσα');
    assert.equal(h.ui.selectionActions.hidden, false); assert.equal(h.button.disabled, false);
  }
});

test('actual text numerals, accents, editorial signs and line-end hyphens are never repaired or removed', () => {
  const f = fixture([['10', '5. α\u0323β[γ]†-', ' ', '12'], ['11', 'δ᾽ ἄ 7']]), h = harness(f);
  const selection = f.select(f.root, 0, f.root, 2);
  assert.equal(h.extract(selection, f.root), '5. α\u0323β[γ]†- 12\nδ᾽ ἄ 7');
  h.update(selection); assert.equal(h.state.selectedText, '5. α\u0323β[γ]†- 12 δ᾽ ἄ 7');
});

test('within-word UTF16 bounds, label-only selections and element-child bounds remain exact', () => {
  const f = fixture([['123', 'α\u0323βγ', ' ', 'δεζ']]), h = harness(f), word = f.content(0)[0];
  assert.equal(h.extract(f.select(word, 1, word, 3), f.root), '\u0323β');
  assert.equal(h.extract(f.select(f.label(0), 0, f.label(0), 3), f.root), '');
  const line = f.root.childNodes[0], content = line.childNodes[1];
  assert.equal(h.extract(f.select(line, 0, content, 1), f.root), 'α\u0323βγ');
  assert.equal(h.extract(f.select(content, 1, content, 3), f.root), ' δεζ');
});

test('prose and source whitespace remain source text, not number-stripped or lexicalized', () => {
  const f = fixture([['', 'placeholder']]), h = harness(f);
  f.root.childNodes = []; f.root.append(new Element('p', '', words('Version 12', '\n[3] ', 'α-β')));
  const nodes = f.texts(f.root);
  assert.equal(h.extract(f.select(nodes[0], 0, nodes[2], 3), f.root), 'Version 12\n[3] α-β');
});

test('loading, outside passage, collapsed and multiple ranges clear the selection', () => {
  const f = fixture([['5', 'x'.repeat(181)]]), h = harness(f), word = f.content(0)[0];
  h.update(f.select(word, 0, word, 180)); assert.equal(h.state.selectedText.length, 180);
  for (const selection of [f.select(word, 0, word, 1), f.select(word, 0, word, 0),
    { ...f.select(word, 0, word, 10), anchorNode: text('outside') },
    { ...f.select(word, 0, word, 10), rangeCount: 2 }, null]) {
    h.update(selection); assert.equal(h.state.selectedText, ''); assert.equal(h.ui.selectedPhrase.textContent, ''); assert.equal(h.ui.selectionActions.hidden, true);
  }
  h.state.passageLoading = true; h.update(f.select(word, 0, word, 10)); assert.equal(h.state.selectedText, '');
  h.state.passageLoading = false; h.state.passage = null; h.update(f.select(word, 0, word, 10)); assert.equal(h.state.selectedText, '');
});

test('180, 181 and 1000 codepoints remain complete; oversize is visible and blocks all actions until a valid selection', () => {
  const f = fixture([['1', 'x'.repeat(1001)]]), h = harness(f), word = f.content(0)[0];
  h.state.translationAvailable = true;
  for (const length of [180, 181, 1000]) {
    h.update(f.select(word, 0, word, length));
    assert.equal(h.state.selectedText.length, length); assert.equal(h.button.disabled, false);
  }
  h.update(f.select(word, 0, word, 1001));
  assert.equal(h.state.selectedText, ''); assert.equal(h.ui.selectionActions.hidden, false); assert.equal(h.button.disabled, true);
  assert.equal(h.translation.disabled, true);
  assert.equal(h.ui.selectionActions.classList.contains('selection-too-long'), true);
  assert.match(h.ui.selectedPhrase.textContent, /up to 1,000 characters/);
  assert.match(h.ui.selectedPhrase.textContent, /not been shortened or sent/);
  assert.ok(h.ui.selectedPhrase.textContent.length < 150);
  h.update(f.select(word, 0, word, 181)); assert.equal(h.state.selectedText.length, 181); assert.equal(h.button.disabled, false);
  assert.equal(h.translation.disabled, false);
  assert.equal(h.ui.selectionActions.classList.contains('selection-too-long'), false);
  h.update(null); assert.equal(h.ui.selectionActions.hidden, true); assert.equal(h.ui.selectedPhrase.textContent, '');
});

test('astral characters count once, combining marks stay literal, and cross-line separators count toward 1000', () => {
  const f = fixture([['1', '𐀀'.repeat(1001)]]), h = harness(f), word = f.content(0)[0];
  h.update(f.select(word, 0, word, 2000)); assert.equal([...h.state.selectedText].length, 1000);
  h.update(f.select(word, 0, word, 2002)); assert.equal(h.state.selectedText, ''); assert.equal(h.button.disabled, true);
  const lines = fixture([['4', 'x'.repeat(499)], ['5', 'y'.repeat(500)]]), other = harness(lines);
  other.update(lines.select(lines.root, 0, lines.root, 2)); assert.equal(other.state.selectedText.length, 1000);
  assert.equal(other.state.selectedText, 'x'.repeat(499) + ' ' + 'y'.repeat(500));
  lines.content(1)[0].data += 'z'; other.update(lines.select(lines.root, 0, lines.root, 2));
  assert.equal(other.state.selectedText, ''); assert.equal(other.button.disabled, true);
});

test('only the oversize notice wraps, and clearing or loading removes its layout class', () => {
  const f = fixture([['1', 'x'.repeat(1001)]]), h = harness(f), word = f.content(0)[0];
  h.update(f.select(word, 0, word, 1001)); h.update(null);
  assert.equal(h.ui.selectionActions.classList.contains('selection-too-long'), false);
  h.update(f.select(word, 0, word, 1001)); h.state.passageLoading = true; h.update(f.select(word, 0, word, 1001));
  assert.equal(h.ui.selectionActions.classList.contains('selection-too-long'), false);
  assert.match(script, /function resetPassageContext\(loading = false\) \{[\s\S]*?classList.remove\('selection-too-long'\)/);
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /\.selection-actions\.selection-too-long>span\{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere\}/);
});
