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
function harness({ response = { candidates: [], contextual_candidates: [] }, validatedVariant = false, validatedLinked = false } = {}) {
  const actions = [], lookups = [], word = new Element('button', 'word', 'αβ');
  word.dataset.lookupGroup = '0';
  const ui = { text: new Element(), inspector: new Element() }; ui.text.append(word);
  const state = { passage: { id: 'synthetic:passage' }, wordSequence: 0, passageLoading: false,
    machineAnalysisCancel: () => actions.push('cancel') };
  const empty = () => {};
  const context = vm.createContext({ ui, state,
    node: (tag, cls, value) => new Element(tag, cls, value), clear: node => node.replaceChildren(),
    window: { matchMedia: () => ({ matches: false }), MelosDictionaryPreview: { linkedDictionaryGroups: () => validatedLinked ? [{}] : [] }, MelosMachineMorphology: { mount: () => { actions.push('machine'); return empty; } } },
    api: async (path, params) => { lookups.push({ path, params }); return response; },
    loadWiktionary: async () => null,
    renderDictionaryPreview: empty, renderExactCommentaryNotes: empty, renderLexicalVariants: () => validatedVariant, renderLexicalEvidence: empty, renderStructuredEvidence: empty,
    renderParallelContexts: empty, renderContextualCandidates: empty, renderRelatedCommentary: empty,
    safeLink: empty, apiPost: empty,
    addContextAction: () => actions.push('jev'), renderFormInventories: empty, appendWarnings: empty,
    renderOccurrencePreview: host => host,
    addInspectorSection: (label, host) => { const node = new Element('section', '', label); host.append(node); return node; },
    message: (host, text) => host.append(new Element('p', '', text)), errorText: error => error.message,
  });
  vm.runInContext(script.slice(script.indexOf('  function appendWarnings('), script.indexOf('  function chronologyClaim(')), context);
  vm.runInContext(script.slice(script.indexOf('  async function renderWordMachineDictionary('), script.indexOf('  function updateSelectionTranslationAction(')), context);
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
  assert.ok(h.ui.inspector.children.some(item => item.tag === 'details' && item.cls.includes('notice-details') && /No complete word/.test(item.textContent)));
  assert.doesNotMatch(h.ui.inspector.textContent, /Word lookup unavailable|Lookup joins an explicit/);
});

test('ordinary intact word and supported whole-word division retain existing explicit actions', async () => {
  for (const joined of [false, true]) {
    const h = harness(); await h.inspect('αβ', h.word, joined, false);
    assert.deepEqual(h.actions, ['cancel', 'machine', 'jev']);
    assert.doesNotMatch(h.ui.inspector.textContent, /Printed segment|Word lookup unavailable/);
  }
});

test('validated lexical variant is not contradicted by a dictionary absence notice when morphology is unavailable', async () => {
  const h = harness({ response: { analysis_match_status: 'spelling_suggestions_only', candidates: [], contextual_candidates: [] }, validatedVariant: true });
  await h.inspect('αβ', h.word);
  assert.doesNotMatch(h.ui.inspector.textContent, /No exact source match|No sourced dictionary or morphology analysis/);
  assert.match(h.ui.inspector.textContent, /No complete sourced morphological parse/);
  const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
  const disclosure = descendants(h.ui.inspector).find(element => element.tag === 'details' && element.textContent.includes('No complete sourced morphological parse'));
  assert.ok(disclosure); assert.equal(disclosure.open, undefined);
  assert.match(disclosure.textContent, /exact dictionary-listed variant/);
  assert.deepEqual(h.actions, ['cancel', 'machine']);
});

test('raw unvalidated variant payload does not suppress genuine exact-source absence', async () => {
  const h = harness({ response: { analysis_match_status: 'spelling_suggestions_only', lexical_variants: [{ id: 'unvalidated' }], candidates: [] } });
  await h.inspect('αβ', h.word);
  assert.match(h.ui.inspector.textContent, /No exact source match/);
  assert.match(h.ui.inspector.textContent, /No sourced dictionary or morphology analysis/);
});

test('validated linked alternatives remove the false dictionary-absence notice without claiming exact identity', async () => {
  const h = harness({ response: { analysis_match_status: 'spelling_suggestions_only', candidates: [] }, validatedLinked: true });
  await h.inspect('αβ', h.word);
  assert.doesNotMatch(h.ui.inspector.textContent, /No exact source match|No sourced dictionary or morphology analysis|exact dictionary-listed variant/);
  assert.match(h.ui.inspector.textContent, /Dictionary-linked meaning alternatives are shown above/);
});
