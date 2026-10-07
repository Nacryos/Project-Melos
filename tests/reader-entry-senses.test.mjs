import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic source-entry fixtures only, not claims about Greek vocabulary.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {} }); }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
function sense(entry, gloss, overrides = {}) {
  return { claim_id: `${entry}:sense:0`, entry_id: entry, scope: 'general_dictionary_entry',
    sense_index: 0, source_sense_id: 'source-sense', glosses: [gloss], raw_glosses: [`(qualified) ${gloss}`],
    tags: ['source-tag'], raw_tags: ['Source qualifier'], source_quality: 'machine_extracted_unreviewed',
    source_url: `https://example.test/${entry}`, locator: 'source locator', quote: `Source quote: ${gloss}`,
    license: 'Fixture license', ...overrides };
}
function candidate(id, gloss) {
  return { id, lemma: 'Same synthetic headword', analysis: 'Same source parse', status: 'source_claim',
    entry_senses: [sense(id, gloss)], entry_sense_claim_ids: [`${id}:sense:0`] };
}
function harness(result = {}) {
  const context = vm.createContext({
    window: {},
    node: (tag, cls, text) => new Element(tag, cls, text),
    safeLink(url, label) {
      try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) return null;
        const link = new Element('a', '', label); link.href = parsed.href; return link; } catch { return null; }
    },
    addInspectorSection(label, host) { const section = new Element('section', '', label); host.append(section); return section; },
    formatFeatures: () => 'Source features',
    state: { classifierStatus: { configured: true }, wordSequence: 1, passage: { id: 'passage' } },
    apiPost: async () => result,
    message(host, text) { host.text = text; },
    clear(host) { host.text = ''; host.children = []; }, appendWarnings() {}, errorText: error => error.message
  });
  vm.runInContext(script.slice(script.indexOf('  function candidateDictionaryExcerpt('), script.indexOf('  async function inspectWord(')) +
    script.slice(script.indexOf('  function candidateEntrySenses('), script.indexOf('  function renderParallelContexts(')) +
    script.slice(script.indexOf('  function candidatePreferenceLabel('), script.indexOf('  function renderFormInventories(')), context);
  return name => vm.runInContext(name, context);
}

test('homographic candidate cards and preference labels retain distinct source entry meanings', () => {
  const lookup = harness(), rows = [candidate('entry-a', 'first lexical meaning'), candidate('entry-b', 'second lexical meaning')];
  const before = structuredClone(rows), host = new Element();
  lookup('renderContextualCandidates')(host, rows);
  const cards = descendants(host).filter(child => child.cls === 'candidate');
  assert.match(cards[0].textContent, /Source entry meaning\(qualified\) first lexical meaning/);
  assert.doesNotMatch(cards[0].textContent, /second lexical meaning|entry-b/);
  assert.match(cards[1].textContent, /second lexical meaning/);
  assert.notEqual(lookup('candidatePreferenceLabel')(rows[0]), lookup('candidatePreferenceLabel')(rows[1]));
  assert.match(lookup('candidatePreferenceLabel')(rows[0]), /Source entry meaning: \(qualified\) first/);
  assert.deepEqual(rows, before);
});

test('all qualified source senses, labels, literal strings and provenance remain expandable', () => {
  const row = candidate('entry-a', 'first meaning');
  row.entry_senses.push(sense('entry-a', '<b>second meaning</b>', { claim_id: 'entry-a:sense:1', raw_glosses: [],
    source_url: 'javascript:unsafe()' }));
  const host = new Element(); harness()('renderCandidateEntrySenses')(host, row);
  assert.match(host.textContent, /Dictionary senses and sources · 2/);
  assert.match(host.textContent, /General dictionary entry; no passage-specific meaning is selected/);
  for (const value of ['(qualified) first meaning', '<b>second meaning</b>', 'source-tag', 'Source qualifier',
    'entry-a:sense:0', 'entry-a:sense:1', 'source-sense', 'source locator', 'Source quote:', 'Fixture license', 'machine extracted unreviewed']) {
    assert.ok(host.textContent.includes(value), value);
  }
  assert.equal(descendants(host).filter(child => child.tag === 'b').length, 0);
  assert.equal(descendants(host).filter(child => child.tag === 'a').length, 1);
  assert.equal(descendants(host).find(child => child.tag === 'a').href, 'https://example.test/entry-a');
});

test('unresolved targets and unscoped or malformed senses cannot borrow a same-headword meaning', () => {
  const lookup = harness();
  for (const entry_senses of [undefined, null, [], [null], [sense('entry-a', 'unsupported', { scope: 'passage' })],
    [sense('entry-a', 'unsupported', { entry_id: '' })], [sense('entry-a', 'unsupported', { claim_id: null })],
    [sense('entry-a', '', { glosses: [], raw_glosses: [] })]]) {
    const row = { id: 'unresolved', lemma: 'Same synthetic headword', entry_senses }, host = new Element();
    assert.equal(lookup('renderCandidateEntrySenses')(host, row), false);
    assert.equal(host.children.length, 0);
    assert.doesNotMatch(lookup('candidatePreferenceLabel')(row), /Source entry meaning|unsupported/);
    assert.match(lookup('candidatePreferenceLabel')(row), /No grammatical analysis supplied/);
  }
});

test('selected proposal and each raw preference retain candidate-bound general entry senses', async () => {
  const first = candidate('entry-a', 'first meaning'), second = candidate('entry-b', 'second meaning');
  const result = { status: 'proposed', candidate_id: first.id, packet: { candidates: [first, second] },
    model_probabilities_uncalibrated: { 'entry-a': 0.7, 'entry-b': 0.2, abstain: 0.1 } };
  const before = structuredClone(result), host = new Element();
  harness(result)('addContextAction')(host, 'fixture', 'passage', 1);
  await descendants(host).find(child => child.tag === 'button').handlers.click();
  const output = descendants(host).find(child => child.cls === 'classifier-output');
  assert.match(output.textContent, /Model proposal · interpretive only/);
  const proposedMeaning = output.children.find(child => child.cls === 'candidate-gloss');
  assert.equal(proposedMeaning.textContent, '(qualified) first meaning');
  const preferences = descendants(output).filter(child => child.cls === 'candidate-preference');
  assert.match(preferences[0].textContent, /first meaning/);
  assert.doesNotMatch(preferences[0].textContent, /second meaning/);
  assert.match(preferences[1].textContent, /second meaning/);
  assert.doesNotMatch(preferences[1].textContent, /first meaning/);
  assert.match(preferences[2].textContent, /Abstain/);
  assert.match(output.textContent, /not calibrated probabilities of philological truth/);
  assert.deepEqual(result, before);
});

test('factored packet senses hydrate by exact declared claim ID only without mutating the packet', async () => {
  const first = candidate('entry-a', 'first meaning'), second = candidate('entry-b', 'second meaning');
  const catalog = Object.fromEntries([...first.entry_senses, ...second.entry_senses].map(row => [row.claim_id, row]));
  delete first.entry_senses; delete second.entry_senses;
  const packet = { candidates: [first, second, { id: 'unresolved', lemma: first.lemma }], entry_sense_catalog: catalog };
  const result = { status: 'proposed', candidate_id: second.id, packet,
    model_probabilities_uncalibrated: { 'entry-a': 0.1, 'entry-b': 0.8 } };
  const before = structuredClone(result), host = new Element(), lookup = harness(result);
  lookup('addContextAction')(host, 'fixture', 'passage', 1);
  await descendants(host).find(child => child.tag === 'button').handlers.click();
  const output = descendants(host).find(child => child.cls === 'classifier-output');
  assert.equal(output.children.find(child => child.cls === 'candidate-gloss').textContent, '(qualified) second meaning');
  assert.match(output.textContent, /Source entry meaning: \(qualified\) first meaning/);
  assert.deepEqual(result, before);
  assert.equal(lookup('packetCandidatesWithEntrySenses')(packet)[2].entry_senses.length, 0);
});

test('factored catalog mismatches, inherited keys and undeclared claims fail closed; explicit inline data wins', () => {
  const lookup = harness(), good = sense('entry-a', 'valid source meaning');
  const catalog = Object.assign(Object.create({ inherited: { ...good, claim_id: 'inherited' } }), {
    wrong: good, [good.claim_id]: good, undeclared: { ...good, claim_id: 'undeclared' }
  });
  const rows = [
    { id: 'missing', entry_sense_claim_ids: ['absent', 'wrong', 'inherited', null] },
    { id: 'explicit-empty', entry_sense_claim_ids: [good.claim_id], entry_senses: [] },
    { id: 'explicit-malformed', entry_sense_claim_ids: [good.claim_id], entry_senses: null },
    { id: 'exact', entry_sense_claim_ids: [good.claim_id] }
  ];
  const hydrated = lookup('packetCandidatesWithEntrySenses')({ candidates: rows, entry_sense_catalog: catalog });
  assert.equal(hydrated[0].entry_senses.length, 0);
  assert.equal(hydrated[1], rows[1]); assert.equal(hydrated[2], rows[2]);
  assert.equal(hydrated[3].entry_senses.length, 1);
  assert.equal(hydrated[3].entry_senses[0], good);
  assert.equal(lookup('packetCandidatesWithEntrySenses')({ candidates: rows, entry_sense_catalog: [] })[3], rows[3]);
});
