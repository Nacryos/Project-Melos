import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

// Synthetic fixtures test scope/rendering, never supply literary evidence.
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], classList: { add() {} } }); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  get childNodes() { return this.children; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(' '); }
}
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const node = (tag, cls, text) => new Element(tag, cls, text);
const scope = vm.createContext({ node, clear: element => element.replaceChildren(),
  document: { createTextNode: text => node('text', '', text) }, safeLink: () => null, appendWarnings() {},
  addInspectorSection(title, host) { const section = node('section', '', title); host.append(section); return section; } });
vm.runInContext(source.slice(source.indexOf('  function stringList('), source.indexOf('  async function loadWiktionary(')), scope);
const render = vm.runInContext('renderWiktionary', scope);
const visible = element => element.tag === 'details' ? '' : element.text + element.children.map(visible).join(' ');
const entry = () => ({ headword: 'synthetic-headword', pos: 'verb', entry_tags: ['first-person'],
  entry_form_of: [{ word: 'synthetic-lemma' }], matches: [{ kind: 'listed_form', form: { form: 'synthetic-selected', tags: ['second-person', 'singular', 'aorist', 'indicative', 'active'] } }],
  senses: [{ sense_index: 0, glosses: ['first-person headword gloss'], form_of: [{ word: 'synthetic-lemma' }], tags: ['form-of', 'first-person'] },
    { sense_index: 1, glosses: ['third-person headword gloss'], tags: ['form-of', 'third-person'] }] });
test('table-matched form keeps its own full parsing visible but headword-specific morphology in collapsed notes', () => {
  const host = node('div'); render(host, { ready: true, query: 'synthetic-selected', results: [entry()], total: 1 });
  assert.match(visible(host), /second-person · singular · aorist · indicative · active/);
  assert.doesNotMatch(visible(host), /first-person|third-person/);
  assert.match(host.textContent, /first-person headword gloss/);
  assert.match(host.textContent, /not the selected table form/);
});
test('an actual headword match retains its source form-of definition', () => {
  const item = entry(); item.matches = [{ kind: 'headword' }];
  const host = node('div'); render(host, { ready: true, query: item.headword, results: [item], total: 1 });
  assert.match(visible(host), /first-person headword gloss/);
  assert.match(visible(host), /third-person headword gloss/);
});
test('ordinary lexical senses remain visible for a listed form', () => {
  const item = entry(); item.entry_form_of = []; item.entry_tags = [];
  item.senses.push({ glosses: ['source lexical meaning'], tags: [] });
  const host = node('div'); render(host, { ready: true, query: 'synthetic-selected', results: [item], total: 1 });
  assert.match(visible(host), /source lexical meaning/);
  assert.doesNotMatch(visible(host), /first-person headword gloss/);
});
test('normalized headword hit cannot override an exact table form and expose unrelated headword grammar', () => {
  const item = entry(); item.headword = 'ά'; item.matches = [{ kind: 'headword', word: 'ά' },
    { kind: 'listed_form', form: { form: 'α', tags: ['second-person'] } }];
  const host = node('div'); render(host, { ready: true, query: 'α', results: [item], total: 1 });
  assert.match(visible(host), /second-person/); assert.doesNotMatch(visible(host), /first-person/);
  assert.match(host.textContent, /Spelling-normalized headword match/);
});
test('accent-only table forms keep grammatical labels collapsed as normalized alternatives', () => {
  const item = entry(); item.matches = [{ kind: 'listed_form', form: { form: 'ά', tags: ['second-person'] } }];
  const host = node('div'); render(host, { ready: true, query: 'α', results: [item], total: 1 });
  assert.doesNotMatch(visible(host), /second-person|first-person/);
  assert.match(host.textContent, /Spelling-normalized dictionary-listed form/);
});
test('canonical Unicode composition counts as exact, unlike accent deletion', () => {
  const item = entry(); item.headword = 'ά'; item.matches = [{ kind: 'headword', word: 'ά' }];
  const host = node('div'); render(host, { ready: true, query: 'α\u0301', results: [item], total: 1 });
  assert.match(visible(host), /first-person headword gloss/);
});
test('unscoped inherited multi-gloss text belongs to headword notes, not table-form meaning', () => {
  const item = entry(); item.entry_form_of = []; item.entry_tags = [];
  item.senses = [{ glosses: ['parent grammatical description', 'nested lexical wording'] }];
  const host = node('div'); render(host, { ready: true, query: 'synthetic-selected', results: [item], total: 1 });
  assert.doesNotMatch(visible(host), /parent grammatical|nested lexical/);
  assert.match(host.textContent, /parent grammatical description/);
});
test('captured live response retains exact selected-headword parse while isolating inherited other-headword prose', () => {
  const raw = readFileSync(new URL('./fixtures/wiktionary-elthes-live.json', import.meta.url));
  const receipt = JSON.parse(readFileSync(new URL('./fixtures/wiktionary-elthes-live.receipt.json', import.meta.url)));
  assert.equal(createHash('sha256').update(raw).digest('hex'), receipt.sha256);
  const data = JSON.parse(raw), host = node('div'); render(host, data);
  const exact = data.results.find(item => item.headword === data.query);
  assert.match(visible(host), /second-person/); assert.match(visible(host), /aorist/);
  assert.ok(visible(host).includes(exact.senses[0].glosses[0]));
  const inherited = data.results.filter(item => item.headword !== data.query).flatMap(item => item.senses)
    .filter(sense => sense.glosses.length > 1).map(sense => sense.glosses[0]);
  assert.ok(inherited.length > 0);
  for (const text of inherited) { assert.ok(!visible(host).includes(text)); assert.ok(host.textContent.includes(text)); }
});
test('reader feature fallback preserves every supplied person and tense without converting coarse Past to aorist', () => {
  vm.runInContext(source.slice(source.indexOf('  function formatFeatures('), source.indexOf('  function claimValue(')), scope);
  const format = vm.runInContext('formatFeatures', scope);
  assert.match(format({ Person: '2', Number: 'Sing', Tense: 'Aor', Mood: 'Ind', Voice: 'Act' }), /2.*Sing.*Aor.*Ind.*Act/);
  assert.equal(format({ Tense: 'Past' }), 'Past');
});
