import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

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
// Lookup key: the printed unit without editorial brackets or underdots.
const lookupKey = text => /[\[\]⟨⟩⟦⟧{}()<>〈〉]/u.test(text) || text.normalize('NFD').includes('\u0323')
  ? text.normalize('NFD').replace(/[\[\]⟨⟩⟦⟧{}()<>〈〉\u0323]/gu, '').normalize('NFC') : text;

test('both printed segments inspect the same joined word without altering source characters', () => {
  const lines = ['αβγ- ', '\tδε ζη']; // Synthetic mechanics fixture, not literary evidence.
  const text = lines.join('\n');
  const units = words(text);
  assert.equal(units[0].form, 'αβγδε');
  assert.equal(units[1].form, 'αβγδε');
  assert.equal(units[0].group, units[1].group);
  let offset = 0;
  for (const line of lines) {
    const host = new Element('span');
    render(host, line, units, offset);
    assert.equal(host.textContent, line);
    const first = host.children.find(child => child.tag === 'button');
    first.handlers.click();
    assert.equal(clicks.at(-1)[0], 'αβγδε');
    assert.equal(clicks.at(-1)[2], true);
    assert.match(first.attributes['aria-label'], /divided across source lines/);
    offset += line.length + 1;
  }
});

test('a drag-ending click keeps the full phrase instead of inspecting the clicked word', () => {
  const host = new Element('span'), prior = clicks.length; let updates = 0;
  const leaf = { data: 'α β' };
  context.ui = { text: { contains: value => value === leaf } };
  context.updateSelection = () => updates++;
  context.window.getSelection = () => ({ rangeCount: 1, getRangeAt: () => ({ collapsed: false, startContainer: leaf, endContainer: leaf }) });
  render(host, 'α β', words('α β'));
  host.children.find(child => child.tag === 'button').handlers.click();
  assert.equal(clicks.length, prior); assert.equal(updates, 1);
  context.window.getSelection = () => null;
});

test('choosing the phrase endpoint never launches a single-word lookup', () => {
  const host = new Element('span'), prior = clicks.length; let chosen = null, updates = 0;
  context.state.passageAnalysis = { isExtending: () => true, chooseWord: button => { chosen = button; } };
  // Entering endpoint mode clears the old native highlight. A new native drag
  // still has precedence, as it does in ordinary word inspection mode.
  context.window.getSelection = () => null;
  context.updateSelection = () => updates++;
  render(host, 'α β', words('α β'));
  const last = host.children.filter(child => child.tag === 'button').at(-1);
  last.handlers.click();
  assert.equal(chosen, last); assert.equal(clicks.length, prior); assert.equal(updates, 1);
  delete context.state.passageAnalysis;
  context.window.getSelection = () => null;
});

test('phrase mode consumes taps without lookup, while moved pointer gestures do nothing', () => {
  const host = new Element('span'), prior = clicks.length; let chosen = 0;
  context.state.passageAnalysis = { isChoosingPhrase: () => true, chooseWord: () => chosen++, ignoreClick: event => event?.moved };
  context.window.getSelection = () => null; context.updateSelection = () => {};
  render(host, 'α β', words('α β'));
  const first = host.children.find(child => child.tag === 'button');
  first.handlers.click({ detail: 1, moved: true }); assert.equal(chosen, 0);
  first.handlers.click({ detail: 1 }); assert.equal(chosen, 1); assert.equal(clicks.length, prior);
  const leaf = { data: 'α β' }; context.ui = { text: { contains: value => value === leaf } };
  context.window.getSelection = () => ({ rangeCount: 1, getRangeAt: () => ({ collapsed: false, startContainer: leaf, endContainer: leaf }) });
  first.handlers.click({ detail: 1 }); assert.equal(chosen, 1); assert.equal(clicks.length, prior);
  delete context.state.passageAnalysis; context.window.getSelection = () => null;
});

test('ordinary space, digits, brackets, lacunae, blank lines and punctuation block joins', () => {
  for (const separator of ['- ', ' ', '-\n4. ', '-\n[', '-\n… ', '-\n\n', '-\n·']) {
    const units = words(`αβγ${separator}δε`);
    assert.equal(units[0].joined, false, separator);
    assert.equal(units[0].form, 'αβγ', separator);
  }
});

test('combining marks remain attached; Greek punctuation never becomes a word button', () => {
  const text = 'α\u0323β\u0323γ· δ; [ε]';
  const units = words(text);
  assert.equal(units[0].text, 'α\u0323β\u0323γ');
  assert.equal(units.map(unit => unit.text).join('|'), 'α\u0323β\u0323γ|δ|[ε]');
  const host = new Element('p');
  render(host, text, units);
  assert.equal(host.textContent, text);
});

test('all supported explicit hyphens and multi-line divisions retain one lookup group', () => {
  for (const hyphen of ['-', '\u2010', '\u00ad']) {
    const units = words(`αβ${hyphen}\r\nγδ${hyphen}\nεζ`);
    assert.equal(units.length, 3);
    assert.ok(units.every(unit => unit.form === 'αβγδεζ' && unit.group === 0));
  }
});

test('editorial markers on either outer boundary block whole-chain joining', () => {
  for (const input of ['[αβ-\nγδ', 'αβ-\nγδ]', 'α[β-\nγδ', 'αβ-\nγ[δ]',
    '⟨αβ-\nγδ⟩', '<αβ-\nγδ>', '{αβ-\nγδ}', '†αβ-\nγδ', 'αβ-\nγδ…', 'αβ-\nγδ. . .',
    'α\u0323β-\nγδ', 'αβ-\nγ\u0323δ']) {
    const units = words(input);
    assert.ok(units.every(unit => !unit.joined), input);
    assert.ok(units.some(unit => unit.fragmentaryJoinRejected), input);
    assert.ok(units.every(unit => unit.form === lookupKey(unit.text)), input);
  }
});

test('rejected multiple-line chains never salvage a suffix or drop terminal signs', () => {
  for (const input of ['[αβ-\nγδ-\nεζ', 'αβ-\nγδ-\nεζ]', 'α\u0323β-\nγδ-\nεζ',
    'αβ\u1fbf-\nγδ-\nεζ', "αβ'-\nγδ-\nεζ",
    'αβ]-\nγδ-\nεζ']) {
    const units = words(input);
    assert.ok(units.every(unit => !unit.joined), input);
    assert.ok(units.every(unit => unit.form === lookupKey(unit.text)), input);
  }
});

test('final attached elision and spacing signs survive intact joins; interior signs remain barriers', () => {
  for (const sign of ["'", '’', '᾽', 'ʼ', '\u1fbf']) {
    const complete = words(`αβ-\nγδ${sign}`);
    assert.ok(complete.every(unit => unit.joined));
    assert.ok(complete.every(unit => unit.form === `αβγδ${sign}`));
    const interrupted = words(`αβ${sign}-\nγδ-\nεζ`);
    assert.ok(interrupted.every(unit => !unit.joined));
  }
});

test('intact divisions remain joined beside ordinary punctuation and unrelated editorial spans', () => {
  for (const input of ['αβ-\nγδ.', '“αβ-\nγδ”', '[α] βγ-\nδε [ζ]', 'ἄβ-\nγδ', 'α\u0301β-\nγδ']) {
    const units = words(input);
    assert.ok(units.some(unit => unit.joined), input);
    assert.ok(units.every(unit => !unit.fragmentaryJoinRejected), input);
  }
});

test('rejected chain buttons retain exact printed text and pass a segment-only inspector flag', () => {
  const input = '[αβ-\nγδ]', units = words(input), host = new Element('p');
  render(host, input, units);
  assert.equal(host.textContent, input);
  for (const button of host.children.filter(item => item.tag === 'button')) {
    assert.match(button.attributes['aria-label'], /printed segment; complete word not established/);
    assert.doesNotMatch(button.attributes['aria-label'], /divided across source lines/);
    button.handlers.click();
    assert.equal(clicks.at(-1)[0], lookupKey(button.textContent));
    assert.equal(clicks.at(-1)[2], false); assert.equal(clicks.at(-1)[3], true);
  }
});
