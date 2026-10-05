import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const window = {};
vm.runInNewContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), { window, AbortController });
const { sourceMap, selectedSpan, selectionIssue, createRequester, mount, lexicalPrediction, sourceCandidateGroups, rankingCandidateLabel } = window.MelosPassageAnalysis;
const texts = element => element.data != null ? [element] : element.children.flatMap(texts);
const document = { createTreeWalker(root) {
  const leaves = texts(root); let cursor = -1;
  return { currentNode: null, nextNode() { this.currentNode = leaves[++cursor]; return this.currentNode || null; } };
} };
class Element {
  constructor(tag, className = '', content = null) {
    Object.assign(this, { tag, className, children: [], events: {}, attributes: {}, ownerDocument: document, hidden: false, disabled: false });
    if (content != null) this.textContent = content;
  }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  prepend(child) { child.parentElement = this; this.children.unshift(child); }
  after(child) { this.parentElement?.append(child); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  set textContent(value) { this.children = [{ data: String(value), parentElement: this }]; }
  get textContent() { return this.children.map(child => child.data ?? child.textContent).join(''); }
  contains(child) { return this === child || this.children.some(value => value === child || value.contains?.(child)); }
  querySelectorAll(selector) {
    const match = item => selector.split(',').some(part => {
      const query = part.trim();
      return query.startsWith('.') ? item.className?.split(' ').includes(query.slice(1)) : query.startsWith('#') ? item.id === query.slice(1) : item.tag === query;
    });
    return this.children.flatMap(child => child instanceof Element ? [...(match(child) ? [child] : []), ...child.querySelectorAll(selector)] : []);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  click() { if (!this.disabled) this.events.click?.(); }
}
const node = (...args) => new Element(...args);
function fixture(source, lines = source.split('\n')) {
  const root = node('div');
  for (const [index, line] of lines.entries()) {
    const row = node('div', 'line'), label = node('span', 'line-label', `${index + 1}`), content = node('span', 'line-content', line);
    row.append(label, content); root.append(row);
  }
  const leaves = root.querySelectorAll('.line-content').map(element => element.children[0]);
  const select = (first, low, last, high) => {
    const ordered = texts(root), a = ordered.indexOf(first), b = ordered.indexOf(last);
    const range = { startContainer: first, startOffset: low, endContainer: last, endOffset: high, collapsed: a === b && low === high,
      intersectsNode(leaf) { const index = ordered.indexOf(leaf); return index >= a && index <= b; } };
    return { rangeCount: 1, getRangeAt: () => range };
  };
  return { root, leaves, select, source };
}
test('exact UTF16 spans retain repeated forms, astral characters, combining marks and editorial material', () => {
  const f = fixture('𐀀 α\u0323 [λόγος] · λόγος\n… †β†'), map = sourceMap(f.root, f.source);
  const first = f.source.lastIndexOf('λόγος');
  const span = selectedSpan(f.select(f.leaves[0], first, f.leaves[1], 5), f.root, map, f.source);
  assert.equal(span.start, first); assert.equal(span.end, f.source.length);
  assert.equal(span.selected_text, 'λόγος\n… †β†');
  assert.equal(span.offset_unit, 'utf16');
  const partial = selectedSpan(f.select(f.leaves[0], 3, f.leaves[0], 5), f.root, map, f.source);
  assert.equal(partial.selected_text, 'α\u0323');
});
test('source mapping excludes rendered line labels and refuses omitted source letters', () => {
  const f = fixture('α\r\nβ', ['α', 'β']), map = sourceMap(f.root, f.source);
  assert.equal(selectedSpan(f.select(f.leaves[0], 0, f.leaves[1], 1), f.root, map, f.source).selected_text, 'α\r\nβ');
  assert.equal(sourceMap(f.root, 'α restored β'), null);
  assert.equal(selectedSpan({ rangeCount: 2 }, f.root, map, f.source), null);
  assert.equal(selectedSpan(f.select(f.leaves[0], 0, f.leaves[0], 0), f.root, map, f.source), null);
});
test('selection bounds count Unicode characters and reject excess words without truncation', () => {
  assert.equal(selectionIssue({ selected_text: '𐀀'.repeat(2000) }), '');
  assert.match(selectionIssue({ selected_text: '𐀀'.repeat(2001) }), /2,000/);
  assert.match(selectionIssue({ selected_text: 'α '.repeat(81) }), /80 words/);
  assert.equal(selectionIssue({ selected_text: 'α '.repeat(80) }), '');
});
test('nearby spelling parses, folded forms and exact spelling matches stay distinct', () => {
  const token = { text: 'κηλήμασι', source_candidates: [
    { matched_form: 'κηλήμασι', lemma: 'exact' }, { matched_form: 'κήλημάσι', lemma: 'folded', edit_distance: 0 },
    { matched_form: 'κτήμασι', lemma: 'nearby', edit_distance: 1 }, { lemma: 'unbound' }
  ] };
  const groups = sourceCandidateGroups(token);
  assert.equal(groups.exact[0].lemma, 'exact'); assert.equal(groups.nearby[0].lemma, 'nearby');
  assert.equal(groups.other.length, 2);
  assert.equal(sourceCandidateGroups({ ...token, analysis_match_status: 'spelling_suggestions_only' }).exact.length, 0);
  assert.equal(lexicalPrediction({ text: '[', token_kind: 'editorial', prediction_status: 'not_applicable' }), false);
  assert.equal(lexicalPrediction({ text: '\n', token_kind: 'whitespace' }), false);
  assert.equal(lexicalPrediction({ text: 'λόγος', token_kind: 'lexical' }), true);
});
test('ranked same-lemma machine alternatives retain distinct inflection and dictionary gender', () => {
  const common = { lemma: 'παντοδαπός', features: { case: 'dative', num: 'plural' } };
  const masculine = rankingCandidateLabel({ ...common, inflection: { gend: { $: 'masculine' } }, dictionary_fields: { hdwd: { $: 'παντοδαπός' }, pofs: { $: 'adjective' } } });
  const neuter = rankingCandidateLabel({ ...common, inflection: { gend: { $: 'neuter' } }, dictionary_fields: { hdwd: { $: 'παντοδαπός' }, pofs: { $: 'adjective' } } });
  assert.notEqual(masculine, neuter); assert.match(masculine, /gender: masculine/); assert.match(neuter, /gender: neuter/);
  assert.match(masculine, /case: dative · number: plural/); assert.match(masculine, /Dictionary fields: part of speech: adjective/);
  assert.match(rankingCandidateLabel({ lemma: 'α', features: { gender: 'feminine', case: 'genitive' } }), /gender: feminine · case: genitive/);
  assert.match(rankingCandidateLabel({ lemma: 'α', dictionary_fields: { gend: { $: 'masculine' } } }), /Dictionary fields: gender: masculine/);
});
const response = body => ({ passage: { id: body.passage_id }, selection: { text: body.selected_text, start_utf16: body.start, end_utf16: body.end } });
test('new selections abort requests and late responses never overwrite current output', async () => {
  const queued = [], results = [], errors = [];
  let currentId = 'a';
  const requester = createRequester({ post: (url, body, options) => new Promise(resolve => queued.push({ url, body, options, resolve })),
    current: body => body.passage_id === currentId, onResult: data => results.push(data), onError: error => errors.push(error), onBusy() {} });
  const body = { passage_id: 'a', start: 0, end: 1, selected_text: 'α' };
  const old = requester.run(body); requester.cancel(); currentId = 'b';
  assert.equal(queued[0].options.signal.aborted, true);
  queued[0].resolve(response(body)); await old;
  assert.equal(results.length, 0);
  const newer = { ...body, passage_id: 'b' }, pending = requester.run(newer);
  queued[1].resolve(response(newer)); await pending;
  assert.equal(results.length, 1); assert.equal(errors.length, 0);
});
test('response provenance mismatch and provider errors are visible', async () => {
  const errors = [], body = { passage_id: 'a', start: 0, end: 1, selected_text: 'α' };
  const options = { current: () => true, onBusy() {}, onResult() { assert.fail('Mismatched result accepted'); }, onError: error => errors.push(error.message) };
  await createRequester({ ...options, post: async () => response({ ...body, start: 7 }) }).run(body);
  await createRequester({ ...options, post: async () => { throw new Error('Provider offline'); } }).run(body);
  assert.match(errors[0], /different passage or selection/); assert.equal(errors[1], 'Provider offline');
});
test('word and endpoint selection never call the API; explicit actions preserve all alternatives and evidence labels', async () => {
  const f = fixture('α β'), content = f.root.querySelector('.line-content');
  const first = node('button', 'word', 'α'), last = node('button', 'word', 'β');
  content.replaceChildren(first, { data: ' ', parentElement: content }, last);
  const host = node('div'), toolbar = node('div'), label = node('span'); label.id = 'selected-phrase'; toolbar.append(label); host.append(toolbar);
  const requests = [], passage = { id: 'a', text: 'α β' };
  const controller = mount({ root: f.root, toolbar, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
    post: async (url, body) => {
      requests.push(body);
      return { ...response(body), tokens: [{ id: 't0', kind: 'word', text: 'α', start_utf16: 0, end_utf16: 1,
        source_candidates: [{ lemma: 'source-one', source: 'Dictionary', matched_form: 'α', analysis: 'nominative' }, { lemma: 'source-two', matched_form: 'γ', edit_distance: 1 }], machine: { status: 'not_requested', machine_candidates: [] } }],
        syntax: { status: 'ready', provider: 'Test parser', tokens: [
          { id: 1, text: 'α', token_kind: 'lexical', start_utf16: 0, end_utf16: 1, lemma: 'model-lemma', upos: 'NOUN', features: { Case: 'Dat' }, head: null, attachment_status: 'unresolved_nonlexical_head' },
          { id: 2, text: '[', token_kind: 'editorial', start_utf16: 0, end_utf16: 1, lemma: 'bogus-editorial-lemma', prediction_status: 'not_applicable', head: null },
          { id: 3, text: '\n', token_kind: 'whitespace', lemma: 'bogus-newline-lemma', prediction_status: 'not_applicable', head: null }
        ] },
        context: { published_translations: [{ text: 'A full translation', source: 'Published edition', selection_aligned: false }] }, ranking: body.rerank ? { status: 'complete', items: [{ token_id: 't0', form: 'α', status: 'machine_proposed',
          decision: { packet: { candidates: [
            { id: 'masculine-id', lemma: 'same-lemma', features: { gend: 'masculine', case: 'dative' } },
            { id: 'neuter-id', lemma: 'same-lemma', inflection: { gend: { $: 'neuter' }, case: { $: 'dative' } } }
          ] }, model_probabilities_uncalibrated: { 'masculine-id': 0.78, 'neuter-id': 0, abstain: 0.22 } },
          ranked_candidates: [{ candidate_id: 'masculine-id', score_uncalibrated: 0.78 }, { candidate_id: 'neuter-id', score_uncalibrated: 0 }]
        }] } : { status: 'not_requested' } };
    } });
  controller.bind(passage); controller.chooseWord(first);
  toolbar.querySelector('.selection-extend').click(); controller.chooseWord(last);
  assert.equal(requests.length, 0); assert.equal(controller.wordSelection().selected_text, 'α β');
  toolbar.querySelector('.selection-analyze').click(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 1); assert.equal(requests[0].fetch_machine, false); assert.equal(requests[0].rerank, false);
  assert.equal(requests[0].selected_text, 'α β');
  assert.match(host.textContent, /source-one/); assert.match(host.textContent, /source-two/);
  assert.match(host.textContent, /Source-recorded morphology/); assert.match(host.textContent, /Whole containing passage/);
  assert.match(host.textContent, /1 exact source matches · 1 nearby spellings/);
  const nearby = host.querySelector('.passage-spelling-suggestions');
  assert.notEqual(nearby.open, true); assert.match(nearby.textContent, /Nearby spelling—not a parse of this word/);
  assert.match(nearby.textContent, /source-two/); assert.doesNotMatch(nearby.textContent, /source-one/);
  const model = host.querySelector('.passage-model-prediction');
  assert.match(model.textContent, /Contextual model prediction/); assert.match(model.textContent, /model-lemma/); assert.match(model.textContent, /Case: Dat/);
  const syntaxRows = host.querySelectorAll('.passage-syntax-link'); assert.equal(syntaxRows.length, 1);
  assert.match(syntaxRows[0].textContent, /unresolved attachment to nonlexical material/); assert.doesNotMatch(syntaxRows[0].textContent, /root/);
  assert.match(host.textContent, /model estimates, not verified correctness rates/);
  host.querySelector('.passage-analysis-controls').querySelectorAll('button').find(button => button.textContent === 'Ask Jev to rank alternatives').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 2); assert.equal(requests[1].rerank, true);
  const rankedRows = host.querySelectorAll('.passage-ranking-candidate'); assert.equal(rankedRows.length, 2);
  assert.match(rankedRows[0].textContent, /gender: masculine/); assert.match(rankedRows[0].textContent, /78.0% model estimate/);
  assert.match(rankedRows[1].textContent, /gender: neuter/); assert.match(rankedRows[1].textContent, /0.0% model estimate/);
  assert.equal(rankedRows[0].title, 'Candidate ID: masculine-id');
  assert.match(host.querySelector('.passage-ranking-abstain').textContent, /22.0% model estimate/);
  host.querySelector('.passage-analysis-close').click(); assert.equal(host.querySelector('.passage-analysis').hidden, true);
});
