import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const window = {};
vm.runInNewContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), { window, AbortController });
const { sourceMap, selectedSpan, selectionIssue, createRequester, mount, lexicalPrediction, sourceCandidateGroups, rankingCandidateLabel, dedupeCandidates, englishTranslation, interlinearSegments, renderInterlinear } = window.MelosPassageAnalysis;
const texts = element => element.data != null ? [element] : element.children.flatMap(texts);
const document = { createTreeWalker(root) {
  const leaves = texts(root); let cursor = -1;
  return { currentNode: null, nextNode() { this.currentNode = leaves[++cursor]; return this.currentNode || null; } };
} };
class Element {
  constructor(tag, className = '', content = null) {
    Object.assign(this, { tag, className, children: [], events: {}, attributes: {}, ownerDocument: document, hidden: false, disabled: false });
    const classes = new Set(className.split(/\s+/).filter(Boolean));
    this.classList = { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name) };
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

test('duplicate linguistic analyses combine evidence without merging homographs or distinct forms', () => {
  const original = { lemma: 'fixture', matched_form: 'α', features: { case: 'dative', number: 'plural' }, source: 'one' };
  const grouped = dedupeCandidates([original, { ...original, source: 'two', features: { number: 'plural', case: 'dative' }, gloss: 'English fixture' },
    { ...original, features: { case: 'genitive', number: 'plural' } }, { ...original, homograph_id: '2' },
    { ...original, matched_form: 'β' }]);
  assert.equal(grouped.length, 4);
  assert.equal(grouped[0].evidence_rows.length, 2);
  assert.equal(grouped[0].gloss, 'English fixture');
  assert.equal(original.evidence_rows, undefined);
  const senses = dedupeCandidates([{ ...original, gloss: 'First distinct sense' }, { ...original, gloss: 'Second distinct sense' }]);
  assert.equal(senses.length, 1);
  assert.deepEqual([...senses[0].glosses], ['First distinct sense', 'Second distinct sense']);
  assert.equal(dedupeCandidates([{ lemma: 'a', inflection: { gend: { $: 'masculine' } } },
    { lemma: 'a', inflection: { gend: { $: 'neuter' } } }]).length, 2);
});

test('translation surfaces require explicit English labels', () => {
  for (const language of ['eng', 'en', 'en-GB', ' eng-US ']) assert.equal(englishTranslation({ language }), true);
  for (const language of ['ell', 'el', 'grc', 'English', '', undefined]) assert.equal(englishTranslation({ language }), false);
});

// Synthetic render fixtures test source fidelity and UI states, not philology.
const readingFixture = () => {
  const selection = { text: '[α]\n β† α', start_utf16: 10, end_utf16: 19 };
  const words = [1, 5, 8].map((offset, index) => ({ token_id: `t${index}`, kind: 'word', text: index === 1 ? 'β' : 'α',
    start_utf16: offset + 10, end_utf16: offset + 11, parse_short: index === 2 ? '' : 'nom. fem. sg.',
    gloss: index === 2 ? { status: 'unavailable', text: null } : { status: 'available', text: index ? 'flower' : 'bright', full_text: 'Source dictionary fixture' },
    agreement_group_id: index === 2 ? null : 'g1' }));
  return { selection, interlinear: { text: selection.text, readings: [{ id: 'syntax-1', label: 'Proposed reading', tokens: words,
    groups: [{ id: 'g1', token_ids: ['t0', 't1'], label: 'nom. fem. sg.' }] }] } };
};

test('interlinear slices preserve exact editorial punctuation, whitespace and repeated occurrences', () => {
  const data = readingFixture(), reading = data.interlinear.readings[0];
  const segments = interlinearSegments(data.selection, reading);
  assert.equal(segments.map(item => item.text).join(''), data.selection.text);
  assert.deepEqual(Array.from(segments.filter(item => item.token), item => item.token.token_id), ['t0', 't1', 't2']);
  const invalid = { tokens: [...reading.tokens, { ...reading.tokens[0], token_id: 'overlap' },
    { ...reading.tokens[0], text: 'WRONG_SOURCE', start_utf16: 10, end_utf16: 11 }] };
  const retained = interlinearSegments(data.selection, invalid);
  assert.equal(retained.map(item => item.text).join(''), data.selection.text);
  assert.equal(retained.filter(item => item.token).length, 3);
  assert.equal(interlinearSegments({ text: 'literal only' }, reading).map(item => item.text).join(''), 'literal only');
});

test('interlinear renders Greek, bold short English gloss, compact parse and accessible agreement groups', () => {
  const data = readingFixture(), host = node('div');
  assert.equal(renderInterlinear(host, data, node), true);
  const words = host.querySelectorAll('.interlinear-word');
  assert.equal(words.length, 3);
  assert.equal(words[0].querySelector('.interlinear-greek').textContent, 'α');
  assert.equal(words[0].querySelector('.interlinear-greek').attributes.lang, 'grc');
  assert.equal(words[0].querySelector('.interlinear-gloss').tag, 'strong');
  assert.equal(words[0].querySelector('.interlinear-gloss').textContent, 'bright');
  assert.equal(words[0].querySelector('.interlinear-parse').textContent, 'nom. fem. sg.');
  assert.equal(words[0].attributes['data-agreement-group'], 'g1');
  assert.equal(words[1].attributes['data-agreement-group'], 'g1');
  assert.equal(words[2].attributes['data-agreement-group'], undefined);
  assert.equal(words[0].querySelector('.interlinear-group-key').textContent, 'A');
  assert.match(words[0].querySelector('.interlinear-group-key').attributes['aria-label'], /group A: nom. fem. sg./);
  assert.match(host.querySelector('.interlinear-legend').textContent, /Group A · nom. fem. sg./);
  assert.equal(words[2].querySelector('.interlinear-gloss').textContent, '—');
  assert.match(words[2].querySelector('.interlinear-gloss').attributes['aria-label'], /English dictionary meaning unavailable/);
  assert.equal(words[2].querySelector('.interlinear-parse').attributes['aria-label'], 'Parsing unavailable');
  assert.equal(host.querySelectorAll('sub').length, 0);
  assert.equal(host.querySelectorAll('select').length, 0);
  assert.ok(!host.querySelector('.interlinear-evidence').open);
  const reconstructed = host.querySelector('.interlinear-phrase').children.map(item => item.querySelector('.interlinear-greek')?.textContent ?? item.textContent).join('');
  assert.equal(reconstructed, data.selection.text);
});

test('unavailable or unbound gloss and agreement information is not invented', () => {
  const data = readingFixture(), token = data.interlinear.readings[0].tokens[0], host = node('div');
  token.gloss = { status: 'long_definition', text: 'MUST_NOT_BE_SHORTENED' };
  token.agreement_group_id = 'unrelated';
  renderInterlinear(host, data, node);
  const word = host.querySelector('.interlinear-word');
  assert.equal(word.querySelector('.interlinear-gloss').textContent, '—');
  assert.equal(word.attributes['data-agreement-group'], undefined);
  const stale = node('div'); data.interlinear.text = 'STALE_SELECTION';
  assert.equal(renderInterlinear(stale, data, node), false);
  assert.equal(stale.children.length, 0);
});

test('only supplied phrase readings are selectable, and changing one replaces its whole annotation layer', () => {
  const data = readingFixture(), first = data.interlinear.readings[0], host = node('div');
  data.interlinear.readings.push({ ...first, id: 'syntax-2', label: 'Alternative construction', groups: [],
    tokens: first.tokens.map(token => ({ ...token, agreement_group_id: null, parse_short: 'acc. fem. sg.',
      gloss: { status: 'available', text: 'second fixture' } })) });
  renderInterlinear(host, data, node);
  const select = host.querySelector('select');
  assert.equal(select.children.length, 2);
  select.value = '1'; select.events.change();
  assert.equal(host.querySelector('.interlinear-gloss').textContent, 'second fixture');
  assert.equal(host.querySelector('.interlinear-parse').textContent, 'acc. fem. sg.');
  assert.equal(host.querySelector('.interlinear-legend'), null);
  assert.equal(host.querySelectorAll('.interlinear-word').length, 3);
});

test('interlinear mobile layout keeps Greek, gloss and parse together in a restrained translucent palette', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /\.interlinear-word\{[^}]*display:inline-flex;[^}]*flex-direction:column;[^}]*max-width:100%/);
  assert.match(css, /\.interlinear-word\{[^}]*break-inside:avoid/);
  assert.match(css, /\.interlinear-literal\{white-space:pre-wrap\}/);
  assert.equal((css.match(/\.interlinear-agreement-[0-3]\{background:rgb\([^)]*\/ \.14\)/g) || []).length, 4);
  assert.match(css, /@media\(max-width:600px\)\{\.interlinear-word/);
});

test('proposed reading is primary, word alternatives stay expandable and new selections restore their quote', async () => {
  const data = readingFixture(), f = fixture(data.selection.text), host = node('div'), toolbar = node('div'); host.append(toolbar);
  const reading = data.interlinear.readings[0];
  for (const token of reading.tokens) { token.start_utf16 -= 10; token.end_utf16 -= 10; }
  const passage = { id: 'interlinear-fixture', text: f.source };
  const controller = mount({ root: f.root, toolbar, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
    post: async (url, body) => ({ ...response(body), interlinear: data.interlinear,
      tokens: reading.tokens.map(token => ({ ...token, source_candidates: [
        { lemma: 'fixture-one', matched_form: token.text, analysis: 'nominative' },
        { lemma: 'fixture-two', matched_form: token.text, analysis: 'accusative' }
      ] })) }) });
  controller.bind(passage);
  controller.selectionChanged(f.select(f.leaves[0], 0, f.leaves[1], f.leaves[1].data.length));
  toolbar.querySelector('.selection-analyze').click(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(host.querySelector('.passage-analysis-selection').hidden, true);
  assert.equal(host.querySelectorAll('.interlinear-word').length, 3);
  assert.ok(host.textContent.indexOf('Proposed reading') < host.textContent.indexOf('Word by word'));
  assert.doesNotMatch(host.textContent, /English translation aligned to this selection is not available yet/);
  const wordDetails = host.querySelectorAll('.passage-analysis-token');
  assert.equal(wordDetails.length, 3);
  for (const word of wordDetails) {
    assert.ok(!word.open); assert.match(word.textContent, /fixture-one/); assert.match(word.textContent, /fixture-two/);
  }
  controller.selectionChanged(f.select(f.leaves[0], 1, f.leaves[0], 2));
  assert.equal(host.querySelector('.passage-analysis-selection').hidden, false);
  assert.equal(host.querySelector('.passage-analysis').hidden, true);
});

test('captured multiword selection survives toolbar focus and replaces previous single-word selection', async () => {
  const f = fixture('α β'), host = node('div'), toolbar = node('div'); host.append(toolbar);
  const passage = { id: 'fixture', text: f.source }, requests = [];
  const controller = mount({ root: f.root, toolbar, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
    post: async (url, body) => { requests.push(body); return response(body); } });
  controller.bind(passage);
  controller.selectionChanged(f.select(f.leaves[0], 0, f.leaves[0], 1));
  controller.selectionChanged(f.select(f.leaves[0], 0, f.leaves[0], 3));
  controller.selectionChanged({ rangeCount: 0, isCollapsed: true });
  assert.equal(controller.currentSelection().selected_text, 'α β');
  toolbar.querySelector('.selection-analyze').click(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests[0].selected_text, 'α β');
  assert.equal(requests[0].end, 3);
});

test('explicit editorial whole-word selection preserves brackets and disables model requests', async () => {
  const f=fixture('[α]β γ'),host=node('div'),toolbar=node('div');host.append(toolbar);
  let passage={id:'editorial-fixture',text:f.source};const requests=[];
  const controller=mount({root:f.root,toolbar,getPassage:()=>passage,node,safeLink:()=>null,inspectWord(){},
    post:async(url,body)=>{requests.push(body);return response(body);}});
  controller.bind(passage);
  assert.equal(controller.selectSourceSpan({start:0,end:4,selected_text:'αβ',offset_unit:'utf16'},true),false);
  assert.equal(requests.length,0);
  assert.equal(controller.selectSourceSpan({start:0,end:4,selected_text:'[α]β',offset_unit:'utf16'},true),true);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,1);assert.equal(requests[0].selected_text,'[α]β');
  assert.equal(requests[0].fetch_machine,false);assert.equal(requests[0].rerank,false);
  passage={...passage,text:'[α]β changed'};
  assert.equal(controller.selectSourceSpan({start:0,end:4,selected_text:'[α]β',offset_unit:'utf16'},true),false);
});

test('word meanings use bound structured senses, preserve alternatives and label contextual proposals honestly', async () => {
  for (const contextual of [false, true]) {
    const f = fixture('α'), host = node('div'), toolbar = node('div'); host.append(toolbar);
    const passage = { id: 'sense-fixture', text: f.source };
    const senses = [0, 1].map(index => ({ id: `sense:${index}`, entry_id: 'entry:1', text: `Literal fixture ${index}`,
      language: 'en', evidence_type: 'dictionary_sense', source: 'Fixture dictionary', source_url: 'https://example.test/entry', scope_text: `Fixture scope ${index}` }));
    const projected = { token_id: 't0', kind: 'word', text: 'α', start_utf16: 0, end_utf16: 1, parse_short: 'nom. sg.',
      gloss: { text: senses[contextual ? 1 : 0].text, status: 'available', sense_id: senses[contextual ? 1 : 0].id,
        alternatives: senses, selection_basis: contextual ? 'jev_contextual_sense_proposal' : 'first_dictionary_sense_not_contextual_sense' } };
    const controller = mount({ root: f.root, toolbar, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
      post: async (url, body) => ({ ...response(body), tokens: [{ id: 't0', kind: 'word', text: 'α', start_utf16: 0, end_utf16: 1,
        lexicon_entries: [{ id: 'entry:1', dictionary_senses: senses }],
        source_candidates: [{ lemma: 'fixture', matched_form: 'α', analysis: 'fixture parse', gloss: 'OLD_ETYMOLOGY_MUST_NOT_RENDER' }] }],
        interlinear: { text: 'α', readings: [{ tokens: [projected] }] },
        sense_ranking: { status: contextual ? 'complete' : 'not_requested', items: contextual ? [{ token_id: 't0',
          ranked_senses: [{ sense_id: 'sense:1', score_uncalibrated: 0.9 }, { sense_id: 'sense:0', score_uncalibrated: 0.1 }] }] : [] }
      }) });
    controller.bind(passage); controller.selectionChanged(f.select(f.leaves[0], 0, f.leaves[0], 1));
    toolbar.querySelector('.selection-analyze').click(); await new Promise(resolve => setImmediate(resolve));
    const rows = host.querySelectorAll('.passage-dictionary-sense');
    assert.equal(rows.length, 2);
    assert.equal(rows[0].attributes['data-sense-id'], contextual ? 'sense:1' : 'sense:0');
    assert.ok(rows.every(row => !row.querySelector('details').open));
    const display = host.querySelector('.passage-dictionary-senses');
    assert.match(display.textContent, contextual ? /Contextual meaning proposed by Jev; not verified/ : /Dictionary source order; contextual meaning not selected/);
    assert.doesNotMatch(display.textContent, /OLD_ETYMOLOGY_MUST_NOT_RENDER|90%|accuracy/);
    assert.doesNotMatch(host.querySelector('.passage-analysis-token').querySelector('summary').textContent, /OLD_ETYMOLOGY/);
    assert.doesNotMatch(host.querySelector('.passage-lemma-group').querySelectorAll('.candidate-gloss').map(item => item.textContent).join(''), /OLD_ETYMOLOGY/);
    assert.ok(!host.querySelectorAll('.passage-analysis-section').find(item => item.textContent.startsWith('Contextual ranking')).open);
  }
});

test('phrase meaning precedes collapsed word breakdown and never substitutes Greek or unaligned context', async () => {
  const f = fixture('α β'), host = node('div'), toolbar = node('div'); host.append(toolbar);
  const passage = { id: 'fixture', text: f.source };
  const controller = mount({ root: f.root, toolbar, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
    post: async (url, body) => ({ ...response(body),
      tokens: ['α', 'β'].map((text, i) => ({ id: `t${i}`, text, kind: 'word', source_candidates: [] })),
      meaning: { interpretations: [
        { text: 'English aligned fixture.', language: 'eng', selection_aligned: true },
        { text: 'MODERN_GREEK_MUST_NOT_RENDER', language: 'ell', selection_aligned: true },
        { text: 'UNALIGNED_MUST_NOT_RENDER', language: 'eng', selection_aligned: false }
      ] }, context: { published_translations: [{ text: 'GREEK_CONTEXT_MUST_NOT_RENDER', language: 'ell' }] }
    }) });
  controller.bind(passage); controller.selectionChanged(f.select(f.leaves[0], 0, f.leaves[0], 3));
  toolbar.querySelector('.selection-analyze').click(); await new Promise(resolve => setImmediate(resolve));
  assert.match(host.textContent, /English aligned fixture/);
  assert.doesNotMatch(host.textContent, /MUST_NOT_RENDER/);
  assert.ok(host.textContent.indexOf('Phrase meaning') < host.textContent.indexOf('Word by word'));
  assert.equal(host.querySelectorAll('.passage-analysis-token').length, 2);
  assert.ok(host.querySelectorAll('.passage-analysis-token').every(item => !item.open));
  assert.ok(host.querySelectorAll('.passage-analysis-section').filter(item => item.tag === 'details').every(item => !item.open));
});
const response = body => ({ passage: { id: body.passage_id }, selection: { text: body.selected_text, start_utf16: body.start, end_utf16: body.end } });

function touchFixture() {
  // Synthetic source characters exercise literal offsets, not corpus evidence.
  const f = fixture('𐀀 α\u0323 [β]\nγ α\u0323'), rows = f.root.querySelectorAll('.line-content');
  const first = node('button', 'word', 'α\u0323'), middle = node('button', 'word', 'β');
  const next = node('button', 'word', 'γ'), last = node('button', 'word', 'α\u0323');
  rows[0].replaceChildren({ data: '𐀀 ', parentElement: rows[0] }, first, { data: ' [', parentElement: rows[0] }, middle, { data: ']', parentElement: rows[0] });
  rows[1].replaceChildren(next, { data: ' ', parentElement: rows[1] }, last);
  const host = node('div'), toolbar = node('div'), heading = node('div'), label = node('span');
  label.id = 'selected-phrase'; toolbar.append(label); host.append(heading, toolbar);
  const requests = [], passage = { id: 'touch-fixture', text: f.source };
  const controller = mount({ root: f.root, toolbar, selectionHost: heading, getPassage: () => passage, node, safeLink: () => null, inspectWord() {},
    post: async (url, body) => { requests.push(body); return response(body); } });
  controller.bind(passage);
  return { ...f, host, toolbar, heading, requests, controller, first, middle, next, last, passage };
}

test('touch phrase mode chooses exact cross-line endpoints in either direction without requests until Analyze', async () => {
  for (const backwards of [false, true]) {
    const f = touchFixture(), start = f.heading.querySelector('.selection-start'), analyze = f.toolbar.querySelector('.selection-analyze');
    start.click(); assert.equal(f.controller.isChoosingPhrase(), true); assert.equal(f.toolbar.hidden, false);
    assert.match(f.toolbar.textContent, /Tap the first word/); assert.equal(analyze.disabled, true);
    f.controller.chooseWord(backwards ? f.last : f.first);
    assert.match(f.toolbar.textContent, /Tap the last word/); assert.equal(analyze.disabled, true);
    f.controller.chooseWord(backwards ? f.first : f.last);
    assert.equal(f.requests.length, 0); assert.equal(analyze.disabled, false);
    assert.equal(f.controller.currentSelection().selected_text, 'α\u0323 [β]\nγ α\u0323');
    assert.ok([f.first, f.middle, f.next, f.last].every(button => button.classList.contains('phrase-selected')));
    analyze.click(); await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.requests.length, 1); assert.equal(f.requests[0].start, 3); assert.equal(f.requests[0].end, f.source.length);
    assert.equal(f.requests[0].offset_unit, 'utf16'); assert.equal(f.requests[0].rerank, false);
  }
});

test('touch cancel, new phrase and passage reset remove range highlights and stale endpoints', () => {
  const f = touchFixture(), start = f.heading.querySelector('.selection-start');
  start.click(); f.controller.chooseWord(f.first); f.controller.chooseWord(f.last);
  start.click(); assert.equal(f.controller.currentSelection(), null);
  assert.ok(!f.first.classList.contains('phrase-selected'));
  f.controller.chooseWord(f.middle); f.controller.chooseWord(f.middle);
  assert.equal(f.controller.currentSelection().selected_text, 'β');
  f.toolbar.querySelector('.selection-clear').click();
  assert.equal(f.controller.isChoosingPhrase(), false); assert.equal(f.controller.currentSelection(), null); assert.equal(f.toolbar.hidden, true);
  start.click(); f.controller.chooseWord(f.last); f.controller.reset();
  assert.equal(f.controller.isChoosingPhrase(), false); assert.ok(!f.last.classList.contains('phrase-selected')); assert.equal(start.disabled, true);
  assert.equal(f.requests.length, 0);
});

test('native selection overrides phrase mode and survives collapsed toolbar focus', () => {
  const f = touchFixture(); f.heading.querySelector('.selection-start').click(); f.controller.chooseWord(f.first);
  const a = f.middle.children[0], b = f.last.children[0];
  f.controller.selectionChanged(f.select(a, 0, b, 2));
  assert.equal(f.controller.isChoosingPhrase(), false); assert.equal(f.controller.currentSelection().selected_text, 'β]\nγ α\u0323');
  f.controller.selectionChanged({ rangeCount: 0 });
  assert.equal(f.controller.currentSelection().selected_text, 'β]\nγ α\u0323'); assert.equal(f.requests.length, 0);
});

test('scrolling, cancelled pointers and drags cannot become taps; keyboard activation remains usable', () => {
  const f = touchFixture();
  f.root.events.pointerdown({ pointerId: 7, clientX: 10, clientY: 20 });
  f.root.events.pointermove({ pointerId: 7, clientX: 12, clientY: 42 });
  assert.equal(f.controller.ignoreClick({ detail: 1 }), true); assert.equal(f.controller.ignoreClick({ detail: 0 }), false);
  f.root.events.pointerdown({ pointerId: 8, clientX: 10, clientY: 20 });
  assert.equal(f.controller.ignoreClick({ detail: 1 }), false);
  f.root.events.pointercancel(); assert.equal(f.controller.ignoreClick({ detail: 1 }), true);
  assert.equal(f.controller.currentSelection(), null); assert.equal(f.requests.length, 0);
});
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
        context: { published_translations: [{ text: 'A full translation', language: 'eng', source: 'Published edition', selection_aligned: false }] }, ranking: body.rerank ? { status: 'complete', items: [{ token_id: 't0', form: 'α', status: 'machine_proposed',
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
  assert.match(host.textContent, /Sources and analysis details/); assert.match(host.textContent, /Whole containing passage/);
  assert.match(host.textContent, /α · 1 parse/);
  const nearby = host.querySelector('.passage-spelling-suggestions');
  assert.notEqual(nearby.open, true); assert.match(nearby.textContent, /Nearby spelling—not a parse of this word/);
  assert.match(nearby.textContent, /source-two/); assert.doesNotMatch(nearby.textContent, /source-one/);
  const model = host.querySelector('.passage-model-prediction');
  assert.match(model.textContent, /Contextual model prediction/); assert.match(model.textContent, /model-lemma/); assert.match(model.textContent, /Case: Dat/);
  const syntaxRows = host.querySelectorAll('.passage-syntax-link'); assert.equal(syntaxRows.length, 1);
  assert.match(syntaxRows[0].textContent, /unresolved attachment to nonlexical material/); assert.doesNotMatch(syntaxRows[0].textContent, /root/);
  assert.match(host.textContent, /model estimates, not verified correctness rates/);
  host.querySelector('.passage-analysis-controls').querySelectorAll('button').find(button => button.textContent === 'Ask Jev to rank parses and meanings').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 2); assert.equal(requests[1].rerank, true);
  const rankedRows = host.querySelectorAll('.passage-ranking-candidate'); assert.equal(rankedRows.length, 2);
  assert.match(rankedRows[0].textContent, /gender: masculine/); assert.match(rankedRows[0].textContent, /78.0% model estimate/);
  assert.match(rankedRows[1].textContent, /gender: neuter/); assert.match(rankedRows[1].textContent, /0.0% model estimate/);
  assert.equal(rankedRows[0].title, 'Candidate ID: masculine-id');
  assert.match(host.querySelector('.passage-ranking-abstain').textContent, /22.0% model estimate/);
  host.querySelector('.passage-analysis-close').click(); assert.equal(host.querySelector('.passage-analysis').hidden, true);
});

test('a mouse drag from one word button to another selects every word between them; touch drags never do', () => {
  document.addEventListener = (name, fn) => { (document.events ??= {})[name] = fn; };
  try {
    const f = touchFixture(), at = word => ({ closest: () => word });
    f.root.events.pointerdown({ pointerType: 'mouse', button: 0, pointerId: 1, clientX: 0, clientY: 0, target: at(f.first) });
    f.root.events.pointermove({ pointerId: 1, buttons: 1, clientX: 60, clientY: 30, target: at(f.next) });
    assert.equal(f.controller.isDragging(), true);
    assert.ok([f.first, f.middle, f.next].every(button => button.classList.contains('phrase-selected')));
    assert.ok(!f.last.classList.contains('phrase-selected'));
    document.events.pointerup({});
    assert.equal(f.controller.isDragging(), false);
    assert.equal(f.controller.currentSelection().selected_text, 'α̣ [β]\nγ');
    assert.equal(f.toolbar.hidden, false); assert.equal(f.requests.length, 0);
    const g = touchFixture();
    g.root.events.pointerdown({ pointerType: 'touch', button: 0, pointerId: 2, clientX: 0, clientY: 0, target: at(g.first) });
    g.root.events.pointermove({ pointerId: 2, buttons: 1, clientX: 0, clientY: 80, target: at(g.last) });
    assert.equal(g.controller.isDragging(), false); assert.equal(g.controller.currentSelection(), null);
  } finally { delete document.addEventListener; delete document.events; }
});

test('holdInView keeps a clicked word where it was and scrolls it clear of the sticky toolbar', () => {
  const { holdInView } = window.MelosPassageAnalysis, calls = []; let y = 0;
  const view = { scrollBy: ({ top }) => { calls.push(top); y -= top; } };
  const word = { isConnected: true, ownerDocument: { defaultView: view }, getBoundingClientRect: () => ({ top: y }) };
  y = 466; // the toolbar appeared above the poem and pushed the word down
  holdInView(word, 300, { hidden: false, getBoundingClientRect: () => ({ bottom: 120 }) });
  assert.deepEqual(calls, [166]); assert.equal(y, 300);
  calls.length = 0; y = 60; // a word under the stuck toolbar
  holdInView(word, 60, { hidden: false, getBoundingClientRect: () => ({ bottom: 150 }) });
  assert.deepEqual(calls, [-98]); assert.equal(y, 158);
  calls.length = 0; holdInView(word, 158, { hidden: true });
  assert.deepEqual(calls, []);
});
