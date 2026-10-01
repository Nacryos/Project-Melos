import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic DOM/API mechanics only; no Greek source claims or real network calls.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [], dataset: {}, handlers: {}, classList: { add() {}, remove() {} } });
  }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  remove() {}
  contains(item) { return this.children.includes(item); }
  querySelectorAll(selector) { return selector === '.word' ? this.children : []; }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  get textContent() { return this.text + this.children.map(item => item.textContent).join(''); }
}
function harness() {
  const actions = [], lookups = [], word = new Element('button', 'word', 'αβ');
  word.dataset.lookupGroup = '0';
  const ui = { text: new Element(), inspector: new Element() }; ui.text.append(word);
  const state = { passage: { id: 'synthetic:passage' }, wordSequence: 0, passageLoading: false,
    machineAnalysisCancel: () => actions.push('cancel') };
  const empty = () => {};
  const context = vm.createContext({ ui, state,
    node: (tag, cls, value) => new Element(tag, cls, value), clear: node => node.replaceChildren(),
    window: { matchMedia: () => ({ matches: false }), MelosMachineMorphology: { mount: () => { actions.push('machine'); return empty; } } },
    api: async (path, params) => { lookups.push({ path, params }); return { candidates: [], contextual_candidates: [] }; },
    loadWiktionary: async () => null,
    renderDictionaryPreview: empty, renderLexicalEvidence: empty, renderStructuredEvidence: empty,
    renderParallelContexts: empty, renderContextualCandidates: empty, renderRelatedCommentary: empty,
    safeLink: empty, apiPost: empty,
    addContextAction: () => actions.push('jev'), renderFormInventories: empty, appendWarnings: empty,
    renderOccurrencePreview: host => host,
    addInspectorSection: (label, host) => { const node = new Element('section', '', label); host.append(node); return node; },
    message: (host, text) => host.append(new Element('p', '', text)), errorText: error => error.message,
  });
  vm.runInContext(script.slice(script.indexOf('  async function inspectWord('), script.indexOf('  function updateSelectionTranslationAction(')), context);
  return { ui, actions, lookups, word, state, inspect: context.inspectWord };
}

test('flagged printed segment retains literal dictionary lookup but mounts no machine or Jev action', async () => {
  const h = harness(); await h.inspect('αβ', h.word, false, true);
  assert.deepEqual(h.actions, ['cancel']); assert.equal(h.state.wordSequence, 1);
  assert.equal(h.lookups.length, 1); assert.equal(h.lookups[0].path, '/api/word');
  assert.equal(h.lookups[0].params.form, 'αβ');
  assert.match(h.ui.inspector.textContent, /Printed segment/);
  assert.match(h.ui.inspector.textContent, /PRINTED SEGMENT/); assert.doesNotMatch(h.ui.inspector.textContent, /SELECTED FORM/);
  assert.match(h.ui.inspector.textContent, /No complete word has been reconstructed/);
  assert.match(h.ui.inspector.textContent, /computational and Jev analysis are unavailable/);
  assert.doesNotMatch(h.ui.inspector.textContent, /Word lookup unavailable|Lookup joins an explicit/);
});

test('ordinary intact word and supported whole-word division retain existing explicit actions', async () => {
  for (const joined of [false, true]) {
    const h = harness(); await h.inspect('αβ', h.word, joined, false);
    assert.deepEqual(h.actions, ['cancel', 'machine', 'jev']);
    assert.doesNotMatch(h.ui.inspector.textContent, /Printed segment|Word lookup unavailable/);
  }
});
