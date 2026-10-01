import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic grammar-display fixtures only; never literary evidence or parses.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [] });
  }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
const context = vm.createContext({
  node: (tag, cls, text) => new Element(tag, cls, text),
  safeLink(url, label) {
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) return null;
      const link = new Element('a', '', label); link.href = parsed.href; return link;
    } catch { return null; }
  },
  addInspectorSection(label, host) { const section = new Element('section', '', label); host.append(section); return section; },
  formatFeatures: () => 'Existing recorded feature display',
});
vm.runInContext(script.slice(script.indexOf('  function renderSourceGrammarAlternatives('),
  script.indexOf('  function renderParallelContexts(')), context);
const render = vm.runInContext('renderSourceGrammarAlternatives', context);
const renderCandidates = vm.runInContext('renderContextualCandidates', context);
function candidate(status = 'incomplete_explicit_alternatives') {
  return { lemma: 'Synthetic source lemma', analysis: 'inf.', features: { mood: 'infinitive' },
    status: 'source_claim', source_projection_status: status,
    source_projection_note: 'Backend projection metadata, not a source quotation.',
    source_grammar_alternatives: [{ record_id: 'fixture:note', source_url: 'https://example.test/note',
      source_text: 'aor. act. inf. or 2nd sg. aor. mid. imper.', quote_start: 11, quote_end: 55,
      branches: [{ raw_label: 'aor. act. inf.', start: 11, end: 25 },
        { raw_label: '2nd sg. aor. mid. imper.', start: 29, end: 55,
          explicit_features: { mood: 'imperative' } }], complete_branch_inventory: false }] };
}

test('incomplete source alternatives appear beside the original candidate without inventing a parse', () => {
  const row = candidate(), before = structuredClone(row), host = new Element();
  renderCandidates(host, [row], 'Fixture source method');
  assert.deepEqual(row, before);
  assert.match(host.textContent, /inf\./);
  assert.match(host.textContent, /Source alternatives/);
  assert.match(host.textContent, /Not all source alternatives are indexed yet\./);
  assert.match(host.textContent, /aor\. act\. inf\. or 2nd sg\. aor\. mid\. imper\./);
  assert.doesNotMatch(host.textContent, /imperative|Backend projection metadata/);
  assert.equal(descendants(host).find(item => item.tag === 'a').href, 'https://example.test/note');
  assert.match(script, /renderSourceGrammarAlternatives\(row, candidate\)/);
  assert.match(script, /renderSourceGrammarAlternatives\(card, candidate\)/);
});

test('represented and partial inventories have distinct qualifications, not a blanket indexing error', () => {
  const complete = new Element(), partial = new Element();
  render(complete, candidate('explicit_alternatives_represented'));
  render(partial, candidate('partial_with_explicit_alternatives'));
  assert.match(complete.textContent, /alternatives are indexed; no reading is selected here/);
  assert.match(partial.textContent, /Partial analysis; the source alternatives remain open/);
  assert.doesNotMatch(complete.textContent + partial.textContent, /Not all source alternatives are indexed/);
});

test('literal branches remain literal when full run is absent; markup and offsets are not interpreted', () => {
  const row = candidate(); delete row.source_grammar_alternatives[0].source_text;
  row.source_grammar_alternatives[0].branches[1].raw_label = '<b>source branch</b>';
  row.source_grammar_alternatives[0].source_url = 'javascript:unsafe()';
  const host = new Element(); render(host, row);
  assert.match(host.textContent, /aor\. act\. inf\./);
  assert.match(host.textContent, /<b>source branch<\/b>/);
  assert.equal(descendants(host).filter(item => ['a', 'b'].includes(item.tag)).length, 0);
  assert.doesNotMatch(host.textContent, /line 11|verse 11|characters 11/);
});

test('unqualified candidates stay unchanged; missing proof text does not conceal known incompleteness', () => {
  for (const row of [{}, null, candidate('unknown_future_status'), candidate('constructor'), candidate('__proto__')]) {
    const host = new Element(); assert.equal(render(host, row), false); assert.equal(host.children.length, 0);
  }
  const row = candidate(); row.source_grammar_alternatives = null;
  const host = new Element(); assert.equal(render(host, row), true);
  assert.match(host.textContent, /Not all source alternatives are indexed yet/);
  assert.doesNotMatch(host.textContent, /inf\.|imper\./);
});
