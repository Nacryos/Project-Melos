import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

// Synthetic API/UI mechanics only, never corpus records or scientific gold.
const script = readFileSync(new URL('../js/machine-morphology.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {}, disabled: false }); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute() {}
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
function setup(post, overrides = {}) {
  const context = vm.createContext({ AbortController }); vm.runInContext(script, context);
  const host = new Element(), requests = [];
  let active = true;
  const stop = context.MelosMachineMorphology.mount({ host, form: 'synthetic', passageId: 'synthetic:1',
    current: () => active, classifierReady: () => true,
    node: (tag, cls, text) => new Element(tag, cls, text),
    safeLink(url, label) { if (!String(url).startsWith('https://')) return null; const link = new Element('a', '', label); link.href = url; return link; },
    post: async (...args) => { requests.push(args); return post(...args); }, ...overrides });
  return { host, requests, stop, deactivate: () => { active = false; },
    button: label => descendants(host).find(item => item.tag === 'button' && item.text === label) };
}
const result = () => ({ status: 'ok', machine_candidates: [
  { id: 'a', candidate_kind: 'machine_analysis', lemma: 'Synthetic headword', features: { case: 'nominative', dial: 'Aeolic' },
    dictionary_fields: { pofs: { $: 'adjective' } }, inflection: { case: { $: 'nominative' } }, entry_pointer: '/0', inflection_pointer: '/0/infl', receipt_id: 'receipt' },
  { id: 'b', lemma: 'Other synthetic headword', features: { case: 'accusative', dial: 'Ionic' }, dictionary_fields: {}, inflection: {} },
], machine_entries: [{ entry: { fixture: 'raw synthetic entry' } }],
receipt: { id: 'receipt', engine_revision: null, url: 'https://example.test/api', raw_sha256: 'synthetic-hash' }, warnings: ['Synthetic upstream warning'] });

test('no automatic call; literal alternatives, dialect scope and provenance remain separate from meanings', async () => {
  const ui = setup(async () => result()); assert.equal(ui.requests.length, 0);
  // No engine is named before a receipt says which one answered.
  assert.doesNotMatch(ui.host.textContent, /Morpheus via Alpheios/);
  assert.match(ui.host.textContent, /engine is named on each result/);
  await ui.button('Analyze this form').handlers.click();
  assert.ok(descendants(ui.host).some(item => item.href === 'https://alpheios.net/pages/tools/' && item.text === 'Morpheus via Alpheios'));
  assert.ok(descendants(ui.host).some(item => item.href === 'https://alpheios.net/pages/apiterms/' && item.text === 'API terms'));
  assert.match(ui.host.textContent, /Parsed by Morpheus via Alpheios\./);
  assert.equal(ui.requests.length, 1); assert.equal(ui.requests[0][0], '/api/machine-analysis');
  assert.match(ui.host.textContent, /Synthetic headword/); assert.match(ui.host.textContent, /Other synthetic headword/);
  assert.match(ui.host.textContent, /Case: nominative/); assert.match(ui.host.textContent, /Case: accusative/);
  assert.match(ui.host.textContent, /Engine dialect: Aeolic/); assert.match(ui.host.textContent, /not exclusive attribution/);
  assert.match(ui.host.textContent, /Case: nominative · Engine dialect: Aeolic/);
  assert.match(ui.host.textContent, /No meaning is inferred/); assert.match(ui.host.textContent, /"engine_revision": null/);
  assert.ok(descendants(ui.host).some(item => item.tag === 'details' && item.cls.includes('notice-details') && /No meaning is inferred/.test(item.textContent)));
  assert.match(ui.host.textContent, /raw synthetic entry/); assert.match(ui.host.textContent, /synthetic-hash/);
  assert.ok(descendants(ui.host).some(item => item.href === 'https://example.test/api'));
});

test('a local Morpheus receipt names the build by commit, not Alpheios, and hides the internal URL', async () => {
  const local = result();
  local.receipt = { id: 'receipt', parser_version: 'morpheus-local-v1', url: 'http://internal-engine:8080/api/v1/analysis/word?word=x',
    engine_revision: `alpheios-project/morpheus@${'a'.repeat(7)}${'0'.repeat(33)} (dist/stemlib); alpheios-project/morphsvc@${'b'.repeat(7)}${'1'.repeat(33)}` };
  const ui = setup(async () => local, { safeLink(url, label) { if (!/^https?:/.test(String(url))) return null; const link = new Element('a', '', label); link.href = url; return link; } });
  await ui.button('Analyze this form').handlers.click();
  assert.match(ui.host.textContent, /Parsed by Morpheus, local build at commit aaaaaaa\./);
  assert.doesNotMatch(ui.host.textContent, /Morpheus via Alpheios|API terms/);
  const links = descendants(ui.host).filter(item => item.tag === 'a');
  assert.ok(links.some(item => item.text === 'Morpheus, local build at commit aaaaaaa'
    && item.href === `https://github.com/alpheios-project/morpheus/tree/${'a'.repeat(7)}${'0'.repeat(33)}`));
  assert.ok(links.some(item => item.text === 'morphsvc bbbbbbb' && item.href.startsWith('https://github.com/alpheios-project/morphsvc/tree/')));
  assert.ok(links.every(item => !item.href.includes('internal-engine')));
  const context = vm.createContext({ AbortController }); vm.runInContext(script, context);
  const engine = context.MelosMachineMorphology;
  assert.equal(engine.engineOf(null), null);
  assert.equal(engine.engineOf({ parser_version: 'alpheios-literal-v1' }).label, 'Morpheus via Alpheios');
});

test('Jev requires separate click and receipt, never displays inferred machine gloss', async () => {
  const ui = setup(async path => path === '/api/machine-analysis' ? result() : {
    status: 'machine_proposed', candidate_basis: 'machine', candidate_id: 'b', gloss: 'DO NOT DISPLAY', reason: 'Synthetic rationale',
    model: 'synthetic-model', cache_hit: true, model_confidence_uncalibrated: .7,
    model_probabilities_uncalibrated: { a: .3, b: .7 }, machine_evidence: { receipt_id: 'receipt', inflection_pointer: '/0/infl' } });
  await ui.button('Analyze this form').handlers.click(); assert.equal(ui.requests.length, 1);
  await ui.button('Compare these analyses with Jev').handlers.click();
  assert.equal(ui.requests.length, 2);
  const body = ui.requests[1][1]; assert.equal(body.candidate_basis, 'machine'); assert.equal(body.machine_receipt_id, 'receipt');
  assert.equal(body.passage_id, 'synthetic:1'); assert.match(ui.host.textContent, /interpretive only/);
  assert.doesNotMatch(ui.host.textContent, /DO NOT DISPLAY/);
  assert.match(ui.host.textContent, /Model: synthetic-model/); assert.match(ui.host.textContent, /Cached comparison; no new Jev call/);
  assert.match(ui.host.textContent, /uncalibrated, not probabilities of philological truth/);
  assert.match(ui.host.textContent, /candidate_preferences/); assert.match(ui.host.textContent, /inflection_pointer/);
});

test('standalone or unconfigured lookup does not offer paid contextual comparison', async () => {
  for (const overrides of [{ passageId: '' }, { classifierReady: () => false }]) {
    const ui = setup(async () => result(), overrides); await ui.button('Analyze this form').handlers.click();
    assert.equal(ui.button('Compare these analyses with Jev'), undefined);
  }
});

test('all source-supplied verb inflection fields render without Jev or tense inference', async () => {
  const payload = result();
  payload.machine_candidates = [{ id: 'complete', lemma: 'Synthetic headword', features: {
    pers: '2nd', num: 'singular', tense: 'aorist', mood: 'indicative', voice: 'active' } }];
  const ui = setup(async () => payload);
  await ui.button('Analyze this form').handlers.click();
  assert.match(ui.host.textContent, /Person: 2nd · Number: singular · Tense: aorist · Mood: indicative · Voice: active/);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0][0], '/api/machine-analysis');
  payload.machine_candidates[0].features.tense = 'past';
  const coarse = setup(async () => payload); await coarse.button('Analyze this form').handlers.click();
  assert.match(coarse.host.textContent, /Tense: past/);
  assert.doesNotMatch(coarse.host.textContent, /Tense: aorist/);
});

test('duplicate clicks, cancellation and ignored abort completion cannot publish stale results', async () => {
  let resolve;
  const ui = setup(() => new Promise(done => { resolve = done; }));
  const pending = ui.button('Analyze this form').handlers.click();
  await ui.button('Analyze this form').handlers.click(); assert.equal(ui.requests.length, 1);
  ui.button('Cancel request').handlers.click(); assert.equal(ui.requests[0][2].signal.aborted, true);
  resolve(result()); await pending;
  assert.match(ui.host.textContent, /Request cancelled/); assert.doesNotMatch(ui.host.textContent, /Synthetic headword/);
  assert.equal(ui.button('Analyze this form').disabled, false);
});

test('word selection invalidates old completion and old comparison click', async () => {
  let resolve;
  const ui = setup(() => new Promise(done => { resolve = done; }));
  const pending = ui.button('Analyze this form').handlers.click(); ui.deactivate(); resolve(result()); await pending;
  assert.doesNotMatch(ui.host.textContent, /Synthetic headword/);
  const complete = setup(async () => result()); await complete.button('Analyze this form').handlers.click(); complete.deactivate();
  await complete.button('Compare these analyses with Jev').handlers.click(); assert.equal(complete.requests.length, 1);
});

test('cancel then retry cannot let the cancelled request overwrite the newer analysis', async () => {
  const resolvers = [];
  const ui = setup(() => new Promise(resolve => resolvers.push(resolve)));
  const old = ui.button('Analyze this form').handlers.click(); ui.button('Cancel request').handlers.click();
  const newer = ui.button('Analyze this form').handlers.click();
  resolvers[1]({ status: 'no_analyses', warnings: ['New response'] }); await newer;
  resolvers[0](result()); await old;
  assert.match(ui.host.textContent, /New response/); assert.doesNotMatch(ui.host.textContent, /Synthetic headword/);
});

test('pending Jev comparison is single-click and stale completion cannot add a proposal', async () => {
  let resolve;
  const ui = setup(async path => path === '/api/machine-analysis' ? result() : new Promise(done => { resolve = done; }));
  await ui.button('Analyze this form').handlers.click();
  const compare = ui.button('Compare these analyses with Jev');
  const pending = compare.handlers.click(); await compare.handlers.click(); assert.equal(ui.requests.length, 2);
  ui.deactivate(); ui.stop(); assert.equal(ui.requests[1][2].signal.aborted, true);
  resolve({ status: 'machine_proposed', candidate_basis: 'machine', candidate_id: 'a' }); await pending;
  assert.doesNotMatch(ui.host.textContent, /Jev proposal among computational alternatives/);
});

test('ordinary source proposal status and unknown candidate IDs never promote a machine choice', async () => {
  for (const decision of [{ status: 'proposed', candidate_basis: 'machine', candidate_id: 'a' },
    { status: 'machine_proposed', candidate_basis: 'machine', candidate_id: 'unseen' },
    { status: 'machine_proposed', candidate_basis: 'source', candidate_id: 'a' }]) {
    const ui = setup(async path => path === '/api/machine-analysis' ? result() : decision);
    await ui.button('Analyze this form').handlers.click(); await ui.button('Compare these analyses with Jev').handlers.click();
    assert.match(ui.host.textContent, /No computational alternative was selected/);
    assert.doesNotMatch(ui.host.textContent, /Jev proposal among computational alternatives/);
  }
});

test('no analyses differs from failure and rate limit; unsafe strings stay literal', async () => {
  for (const [status, expected] of [['no_analyses', /No additional parses found/],
    ['upstream_error', /Could not load additional parses. Try again/], ['rate_limited', /rate-limited/]]) {
    const ui = setup(async () => ({ status, machine_candidates: [], warnings: [] }));
    await ui.button('Analyze this form').handlers.click(); assert.match(ui.host.textContent, expected);
  }
  const ui = setup(async () => { throw Object.assign(new Error('rate limit'), { status: 429,
    response: { warnings: ['Literal service warning'], receipt: { id: 'failed-receipt' } } }); });
  await ui.button('Analyze this form').handlers.click(); assert.match(ui.host.textContent, /rate-limited/);
  assert.match(ui.host.textContent, /Literal service warning/); assert.match(ui.host.textContent, /failed-receipt/);
  const unsafe = result(); unsafe.machine_candidates[0].lemma = '<script>unsafe()</script>'; unsafe.receipt.url = 'javascript:unsafe()';
  const safe = setup(async () => unsafe); await safe.button('Analyze this form').handlers.click();
  assert.match(safe.host.textContent, /<script>unsafe\(\)<\/script>/);
  assert.equal(descendants(safe.host).filter(item => item.tag === 'script').length, 0);
  assert.ok(descendants(safe.host).filter(item => item.tag === 'a').every(item => item.href.startsWith('https://alpheios.net/')));
});

test('reader mounts independently before recorded lookup and aborts on passage reset', () => {
  const reader = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
  const inspect = reader.slice(reader.indexOf('  async function inspectWord('));
  assert.ok(inspect.indexOf('MelosMachineMorphology.mount') < inspect.indexOf("await api('/api/word'"));
  assert.match(reader, /function resetPassageContext\(loading = false\) \{\s*state.machineAnalysisCancel\?\.\(\)/);
  assert.match(reader, /candidate_basis|onlyNearby/);
});

function sourcedAlternatives(index) {
  // Read already-audited public engine fixtures; no authored Greek/parses.
  // These test IDs are only display mechanics, not production receipt IDs.
  const directory = new URL('./fixtures/machine_morphology/', import.meta.url);
  const manifest = JSON.parse(readFileSync(new URL('manifest.json', directory), 'utf8'));
  const sample = manifest.samples[index], raw = readFileSync(new URL(sample.file, directory));
  assert.equal(createHash('sha256').update(raw).digest('hex'), sample.response.raw_sha256);
  const list = value => Array.isArray(value) ? value : [value];
  const candidates = [];
  for (const annotation of list(JSON.parse(raw).RDF.Annotation)) {
    for (const body of list(annotation.Body)) for (const entry of list(body.rest.entry)) {
      for (const inflection of list(entry.infl)) candidates.push({
        id: `test-fixture:${sample.file}:${candidates.length}`, lemma: entry.dict.hdwd.$,
        dictionary_fields: entry.dict, inflection,
        features: Object.fromEntries(Object.entries(inflection).filter(([, value]) => value && typeof value === 'object' && '$' in value).map(([key, value]) => [key, value.$])),
        entry_pointer: `synthetic-display-pointer:${candidates.length}`, inflection_pointer: `synthetic-infl-pointer:${candidates.length}`,
      });
    }
  }
  return candidates;
}

test('audited engine controls: five distinct inflections remain five; two same-display alternatives group without deletion', async () => {
  const five = sourcedAlternatives(0), two = sourcedAlternatives(1);
  assert.equal(five.length, 5); assert.equal(two.length, 2);
  const context = vm.createContext({ AbortController }); vm.runInContext(script, context);
  const group = context.MelosMachineMorphology.displayGroups;
  assert.equal(group(five).length, 5); assert.equal(group(two).length, 1);
  assert.equal(group(two)[0].length, 2);
  const original = structuredClone(two);
  const ui = setup(async path => path === '/api/machine-analysis' ? { ...result(), machine_candidates: two } : {
    status: 'machine_proposed', candidate_basis: 'machine', candidate_id: two[1].id });
  await ui.button('Analyze this form').handlers.click();
  assert.match(ui.host.textContent, /2 engine alternatives with the same displayed features/);
  assert.equal(descendants(ui.host).filter(item => item.cls === 'candidate machine-candidate').length, 1);
  for (const item of two) {
    assert.ok(ui.host.textContent.includes(item.id));
    assert.ok(ui.host.textContent.includes(item.inflection_pointer));
  }
  await ui.button('Compare these analyses with Jev').handlers.click();
  const comparison = descendants(ui.host).find(item => item.cls === 'machine-comparison');
  assert.ok(comparison.textContent.includes(two[1].id));
  assert.ok(!comparison.textContent.includes(two[0].id));
  assert.deepEqual(two, original);
});

test('presentation key sorts object keys but preserves every differing feature, dictionary field and headword', () => {
  const context = vm.createContext({ AbortController }); vm.runInContext(script, context);
  const group = context.MelosMachineMorphology.displayGroups;
  const first = { lemma: 'Synthetic', features: { case: 'nominative', num: 'plural' }, dictionary_fields: { a: 1, b: 2 } };
  const reordered = { ...first, features: { num: 'plural', case: 'nominative' }, dictionary_fields: { b: 2, a: 1 } };
  assert.equal(group([first, reordered]).length, 1);
  for (const different of [{ ...first, lemma: 'synthetic' }, { ...first, features: { ...first.features, dial: 'Synthetic tag' } },
    { ...first, dictionary_fields: { a: 1, b: 3 } }]) assert.equal(group([first, different]).length, 2);
});
