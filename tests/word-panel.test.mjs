import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic fixtures and a tiny fake DOM; no network and no literary claims.
const panelSource = readFileSync(new URL('../js/word-panel.js', import.meta.url), 'utf8');
const readerSource = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');

class Element {
  constructor(tag = 'div', cls = '', text = '') {
    Object.assign(this, { tag, className: cls, text, children: [], dataset: {}, attrs: {}, parent: null, open: undefined });
    this.classList = { add: name => { this.className = `${this.className} ${name}`.trim(); }, remove() {} };
  }
  get cls() { return this.className; }
  append(...items) { for (const item of items) { if (item instanceof Element) item.parent = this; this.children.push(item); } }
  prepend(item) { item.parent = this; this.children.unshift(item); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener() {}
  contains(item) { return this.all().includes(item); }
  all() { return this.children.flatMap(child => child instanceof Element ? [child, ...child.all()] : []); }
  querySelectorAll(selector) {
    if (selector === '.word') return [];
    const name = selector.replace(/^\./, '');
    return this.all().filter(item => item.className.split(/\s+/).includes(name));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get lastChild() { return this.children.at(-1); }
  get textContent() { return this.text + this.children.map(item => typeof item === 'string' ? item : item.textContent).join(''); }
  set textContent(value) { this.text = String(value); this.children = []; }
}
const node = (tag, cls, text) => new Element(tag, cls, text);

function loadPanel() {
  const window = {};
  vm.runInContext(panelSource, vm.createContext({ window }));
  return window.MelosWordPanel;
}
const panel = loadPanel();

test('parse labels are written out in plain words in the usual order', () => {
  assert.equal(panel.plainParse('acc. fem. sg.'), 'accusative singular feminine');
  assert.equal(panel.plainParse('pres. act. inf.'), 'present active infinitive');
  assert.equal(panel.plainParse('3rd sg. aor. ind. act.'), 'third person singular aorist indicative active');
  assert.equal(panel.plainParse('dat. fem. sg. pres. act. ptcp.'), 'present active participle, dative singular feminine');
  assert.equal(panel.plainParse('2nd sg. pres. subj. mid./pass.'), 'second person singular present subjunctive middle or passive');
  assert.equal(panel.plainParse('part.'), 'particle');
  assert.equal(panel.plainParse('prep.'), 'preposition');
  // Unknown or repeated labels are left exactly as the server sent them.
  assert.equal(panel.plainParse('acc. acc.'), 'acc. acc.');
  assert.equal(panel.plainParse('damaged piece · no analysis'), 'damaged piece · no analysis');
});

test('the parse source is one plain sentence, and alternatives are ranked without repeating the choice', () => {
  const row = { lemma: 'ἔρως', parse_short: 'nom. masc. sg.', selection_basis: 'morphology_ranked_by_syntax',
    source_candidate: { basis: 'machine_analysis' },
    morphology_ranking: [
      { lemma: 'Ἔρως', parse_short: 'nom. masc. sg.' }, { lemma: 'ἔρως', parse_short: 'voc. masc. sg.' },
      { lemma: 'ἐράω', parse_short: '3rd sg. pres. ind. act.' }, { lemma: 'ἔρως', parse_short: 'voc. masc. sg.' }] };
  assert.equal(panel.parseSource(row), 'Parse from Morpheus parser (Perseus); chosen by fit to the sentence.');
  assert.equal(panel.parseSource({ selection_basis: 'source_morphology_consensus' }), 'The recorded analyses agree.');
  assert.equal(panel.parseSource({ source_candidate: { source: 'PerseusDL Greek Dependency Treebank v1.6' } }), 'Parse from Perseus treebank.');
  assert.deepEqual([...panel.alternatives(row).map(item => item.parse)],
    ['vocative singular masculine', 'third person singular present indicative active']);
});

test('one dictionary block per dictionary, in the order Middle Liddell, Autenrieth, LSJ, Cunliffe', () => {
  const entry = (id, source, lemma, senses) => ({ id, source, lemma, gloss: senses[0], rendered_entry_text: `${lemma} full entry`,
    entry_url: `https://example.test/${id}`, dictionary_senses: senses.map((text, i) => ({ text, sense_path: [{ n: String(i + 1) }] })) });
  const blocks = panel.dictionaryBlocks('σελήνη',
    [entry('c', 'Perseus Cunliffe TEI v1', 'σελήνη', ['The moon']), entry('x', 'Perseus Middle Liddell TEI', 'μέλας', ['black'])],
    [entry('l', 'LSJ (Logeion edition, H. Dik) TEI', 'σελήνη', ['the moon', 'month']), entry('m', 'Perseus Middle Liddell TEI', 'σελήνη', ['the moon']),
      entry('a', 'Perseus Autenrieth TEI via Homerica', 'Σελήνη', ['moon']), entry('m', 'Perseus Middle Liddell TEI', 'σελήνη', ['the moon'])]);
  assert.deepEqual([...blocks.map(block => block.title)], ['Middle Liddell', 'Autenrieth', 'LSJ', 'Cunliffe']);
  assert.equal(blocks[0].entries.length, 1, 'the same entry from two payloads is shown once');
  const host = node('div');
  assert.equal(panel.renderDictionaryBlocks(host, blocks, node, (url, label) => url ? node('a', '', label) : null), true);
  const boxes = host.querySelectorAll('.word-dictionary');
  assert.equal(boxes.length, 4);
  assert.equal(boxes[0].open, true); assert.equal(boxes[1].open, undefined, 'later dictionaries start collapsed');
  assert.match(boxes[0].children[0].textContent, /Middle Liddell/);
  assert.match(host.textContent, /Dictionaries · 4/);
  assert.match(boxes[2].textContent, /month/); assert.match(boxes[2].textContent, /Full entry/);
});

test('long sense lists are collapsed after four senses and repeated sense numbers are printed once', () => {
  const senses = ['a', 'b', 'c', 'd', 'e', 'f'].map(text => ({ text, sense_path: [{ n: 'I' }] }));
  const blocks = panel.dictionaryBlocks('λ', [{ id: '1', source: 'LSJ', lemma: 'λ', dictionary_senses: senses }]);
  const host = node('div'); panel.renderDictionaryBlocks(host, blocks, node, () => null);
  const more = host.querySelectorAll('.word-more')[0];
  assert.match(more.children[0].textContent, /2 more senses/);
  const labels = host.querySelectorAll('.word-sense-label').map(item => item.textContent);
  assert.deepEqual(labels, ['I', '', '', '', '', '']);
});

test('the headline shows the parse in words, its source and the ranked alternatives', () => {
  const head = node('div', 'word-headline'); head.append(node('p', 'word-headline-parse', 'acc. fem. sg.'));
  panel.decorateHeadline(head, { lemma: 'σελήνη', parse: 'acc. fem. sg.', source: 'Parse from Morpheus parser (Perseus).',
    alternatives: [{ lemma: 'σελήνη', parse: 'genitive plural feminine' }, { lemma: 'σέλας', parse: 'a' }, { parse: 'b' }, { parse: 'c' }] }, node);
  const parse = head.querySelector('.word-headline-parse');
  assert.equal(parse.textContent, 'accusative singular feminine'); assert.equal(parse.title, 'acc. fem. sg.');
  assert.match(head.textContent, /Parse from Morpheus parser/);
  assert.match(head.textContent, /Other possible parses, most likely first/);
  assert.deepEqual(head.querySelectorAll('.word-alt-lemma').map(item => item.textContent), ['σέλας'], 'the headword itself is not repeated');
  assert.match(head.querySelector('.word-more').textContent, /1 more/);
});

test('raw JSON receipts become a readable list without hashes', () => {
  const view = panel.readableValue({ reuse_status: 'public_domain_us_edition', comparison_id: 'c1', selection_aligned: false, raw_sha256: 'a'.repeat(64),
    source_provenance: { source_url: 'https://example.test', edition: 'Fixture' }, tags: ['x', 'y'] }, node);
  const text = view.textContent;
  assert.match(text, /Comparison ID/); assert.match(text, /Selection aligned/); assert.match(text, /no/);
  assert.match(text, /Source link/); assert.match(text, /x, y/); assert.match(text, /public domain us edition/);
  assert.doesNotMatch(text, /aaaa|sha256|[{}"]/);
});

test('touch words get a 44 px hit area without changing layout, and taps go to the nearest word', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const rule = css.slice(css.indexOf('@media(pointer:coarse){\n  .greek-text .word{position:relative}'));
  assert.match(rule, /\.greek-text \.word::before\{content:'';position:absolute;z-index:1;top:min\(-8px,calc\(\(100% - 44px\)\/2\)\)/);
  assert.doesNotMatch(rule.slice(0, rule.indexOf('}\n}') + 3), /padding|line-height|margin/);
  const words = [{ r: { left: 0, right: 14, top: 0, bottom: 25 } }, { r: { left: 18, right: 60, top: 0, bottom: 25 } }, { r: { left: 0, right: 40, top: 25, bottom: 50 } }]
    .map(item => ({ ...item, getBoundingClientRect: () => item.r }));
  const root = { querySelectorAll: () => words };
  assert.equal(panel.nearestWord(root, 7, -6), words[0], 'a tap just above δ’ belongs to δ’');
  assert.equal(panel.nearestWord(root, 15, 10), words[0], 'a tap in the gap goes to the closer word');
  assert.equal(panel.nearestWord(root, 30, 24), words[1], 'a tap inside a word box always belongs to that word');
  assert.equal(panel.nearestWord(root, 30, 27), words[2]);
});

test('reader loads the word-panel module before reader.js, and the build ships it', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('js/word-panel.js?v=') > 0 && html.indexOf('js/word-panel.js?v=') < html.indexOf('js/reader.js?v='));
  assert.match(readFileSync(new URL('../scripts/build_frontend.mjs', import.meta.url), 'utf8'), /'word-panel\.js'/);
});

// inspectWord with the real module: zone order and one coherent statement.
function harness(response) {
  const word = new Element('button', 'word', 'αβ'); word.dataset = { lookupGroup: '0', sourceStart: '0', sourceEnd: '2' };
  const ui = { text: new Element(), inspector: new Element() }; ui.text.append(word);
  ui.inspector.closest = () => ({ scrollIntoView() {} });
  const state = { passage: { id: 'synthetic:passage', text: 'αβ' }, wordSequence: 0, passageLoading: false, machineAnalysisCancel: () => {} };
  const empty = () => {}, lookups = [], calls = [];
  const window = { MelosWordPanel: panel, matchMedia: () => ({ matches: false }),
    MelosPassageAnalysis: {
      renderWordHeadline: (host, value, make) => { const head = make('div', 'word-headline'); head.append(make('div', 'word-headline-lemma', value.lemma || value.form)); if (!value.pending) head.append(make('p', 'word-headline-parse', value.parse || '')); host.replaceChildren(head); return head; },
      headlineFromRow: row => row ? { lemma: row.lemma, gloss: 'g', form: row.text, parse: row.parse_short } : null,
    } };
  const context = vm.createContext({ ui, state, window, node, clear: host => host.replaceChildren(),
    api: async (path, params) => { lookups.push(params.form); calls.push({ path, ...params }); return params.form === 'αβ' ? response : { lexicon_entries: [
      { id: 'ml', source: 'Perseus Middle Liddell TEI', lemma: 'λέμμα', dictionary_senses: [{ text: 'fixture sense', sense_path: [{ n: 'A' }] }] }] }; },
    apiPost: async () => ({ passage: { id: 'synthetic:passage' }, interlinear: { readings: [{ tokens: [{ kind: 'word', start_utf16: 0, text: 'αβ', lemma: 'λέμμα', parse_short: 'acc. fem. sg.',
      source_candidate: { basis: 'machine_analysis' }, selection_basis: 'unique_candidate', morphology_ranking: [] }] }] } }),
    loadWiktionary: async () => null, renderDictionaryPreview: empty, renderExactCommentaryNotes: empty, renderLexicalVariants: () => false,
    renderLexicalEvidence: empty, renderStructuredEvidence: empty, renderParallelContexts: empty, renderContextualCandidates: empty,
    renderRelatedCommentary: empty, safeLink: empty, addContextAction: empty, renderFormInventories: empty,
    renderOccurrencePreview: host => host, candidateDictionaryExcerpt: () => ({}),
    requestAnimationFrame: fn => fn(), message: (host, text) => host.append(new Element('p', '', text)), errorText: error => error.message,
  });
  vm.runInContext(readerSource.slice(readerSource.indexOf('  function appendWarnings('), readerSource.indexOf('  function chronologyClaim(')), context);
  vm.runInContext(readerSource.slice(readerSource.indexOf('  async function renderWordMachineDictionary('), readerSource.indexOf('  function updateSelectionTranslationAction(')), context);
  return { ui, word, lookups, calls, inspect: context.inspectWord };
}

test('panel zones run headword, dictionaries, notes, then one collapsed Sources and method', async () => {
  const h = harness({ analysis_match_status: 'spelling_suggestions_only', candidates: [], contextual_candidates: [] });
  await h.inspect('αβ', h.word);
  await new Promise(resolve => setTimeout(resolve, 0));
  const top = h.ui.inspector.children.map(child => child.className);
  const at = name => top.findIndex(cls => cls.includes(name));
  assert.ok(at('word-headline-host') < at('word-dictionary-host'));
  assert.ok(at('word-dictionary-host') < at('word-notes'));
  assert.ok(at('word-notes') < at('word-sources'));
  const sources = h.ui.inspector.children[at('word-sources')];
  assert.equal(sources.tag, 'details'); assert.equal(sources.open, undefined);
  assert.equal(sources.children[0].textContent, 'Sources and method');
  // Headline from the passage reading: the form index's "no exact match" notices give way.
  assert.match(h.ui.inspector.querySelector('.word-headline-parse').textContent, /accusative singular feminine/);
  assert.doesNotMatch(h.ui.inspector.textContent, /No exact source match|No sourced dictionary or morphology analysis/);
  assert.match(sources.textContent, /come from reading this word in its passage/);
  // Dictionaries follow the headline's headword, fetched by headword when the form lookup has none.
  assert.deepEqual(h.lookups, ['αβ', 'λέμμα']);
  assert.match(h.ui.inspector.querySelector('.word-dictionaries').textContent, /Middle Liddell.*fixture sense/);
});

test('the form lookup carries the headline headword as lemma=, and the dictionaries follow it', async () => {
  const h = harness({ candidates: [], contextual_candidates: [], lexicon_entries: [
    { id: 'ml', source: 'Perseus Middle Liddell TEI', lemma: 'λέμμα', dictionary_senses: [{ text: 'headline sense', sense_path: [] }] },
    { id: 'other', source: 'Perseus Middle Liddell TEI', lemma: 'ἄλλο', dictionary_senses: [{ text: 'other sense', sense_path: [] }] }] });
  await h.inspect('αβ', h.word);
  await new Promise(resolve => setTimeout(resolve, 0));
  const lookup = h.calls.find(call => call.path === '/api/word' && call.form === 'αβ');
  assert.equal(lookup.lemma, 'λέμμα'); assert.equal(lookup.passage_id, 'synthetic:passage');
  // The form lookup already brought the headword's entries: no second lookup.
  assert.deepEqual(h.lookups, ['αβ']);
  const dictionaries = h.ui.inspector.querySelector('.word-dictionaries').textContent;
  assert.match(dictionaries, /headline sense/); assert.doesNotMatch(dictionaries, /other sense/);
});

test('the headline names the parser the server reports in parse_source, with short build commits', () => {
  const panel = loadPanel();
  const local = { selection_basis: 'unique_candidate', source_candidate: { basis: 'machine_analysis' },
    parse_source: { kind: 'machine_analysis', label: `Morpheus, local build (alpheios-project/morpheus@2f1a30d${'0'.repeat(33)})` } };
  assert.equal(panel.parseSource(local), 'Parse from Morpheus, local build (alpheios-project/morpheus@2f1a30d); the only analysis found.');
  assert.doesNotMatch(panel.parseSource(local), /Perseus\)/);
  const recorded = { selection_basis: 'source_morphology_consensus',
    parse_source: { kind: 'source_analysis', label: 'PerseusDL Greek Dependency Treebank v1.6; LSJ (Logeion edition, H. Dik) TEI' } };
  assert.equal(panel.parseSource(recorded), 'Parse from Perseus treebank; LSJ; the recorded analyses agree.');
  const model = { selection_basis: 'syntax_prediction', parse_source: { kind: 'contextual_model', label: 'Contextual model prediction (odyCy), not a source parse' } };
  assert.equal(panel.parseSource(model), 'Predicted from the sentence only; no parser analysis.');
  // Older rows without parse_source keep the candidate-based wording.
  assert.match(panel.parseSource({ selection_basis: 'unique_candidate', source_candidate: { basis: 'machine_analysis' } }), /^Parse from Morpheus parser/);
});
