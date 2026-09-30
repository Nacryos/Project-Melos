import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic source/lemma fixtures exercise presentation, not literary claims.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const context = vm.createContext({
  node: (tag, cls, text) => new Element(tag, cls, text),
  addInspectorSection(title, host) { const section = new Element('section', '', title); host.append(section); return section; },
  safeLink(url, label) {
    if (!url?.startsWith('https://')) return null;
    const link = new Element('a', '', label); link.href = url; return link;
  },
});
vm.runInContext(source.slice(source.indexOf('  function renderFormInventories('), source.indexOf('  async function inspectWord(')), context);
const render = vm.runInContext('renderFormInventories', context);
function inventory(data) { const host = new Element('aside'); render(host, data); return host; }
function descendants(root, tag) { return root.children.flatMap(child => [...(child.tag === tag ? [child] : []), ...descendants(child, tag)]); }
function group(overrides = {}) {
  return {
    lemma: 'fixture lemma A', lemma_raw: 'fixture lemma A1', source: 'Source A',
    query_relation: 'spelling_suggestion', matches: [{ matched_form: 'fixture spelling A' }],
    forms: [{ form: 'fixture form A', source_refs: [{ source: 'Source A', source_url: 'https://example.org/a', analysis: 'raw-code', analysis_format: 'fixture-format' }], source_ref_total: 3, source_refs_shown: 1, source_refs_truncated: true }],
    total_forms: 8, shown_forms: 1, truncated: true, complete_paradigm: false,
    identity_status: 'source_lemma', ...overrides,
  };
}

test('fuzzy inventories advertise nearby-spelling scope even while collapsed', () => {
  const host = inventory({ observed_form_groups: [group()] });
  const summary = descendants(host, 'summary')[0].textContent;
  assert.match(summary, /Nearby spelling: fixture lemma A \[fixture lemma A1\] · Source A · 1 of 8 forms shown/);
  assert.match(host.textContent, /not an analysis of the selected form/);
  assert.match(host.textContent, /not a complete or dialect-specific paradigm/);
  assert.match(host.textContent, /not a list of attestations in the selected author or passage/);
  assert.match(host.textContent, /Candidate source spellings: fixture spelling A/);
});

test('group-specific forms and provenance never merge across lemma or source groups', () => {
  const second = group({ lemma: 'fixture lemma B', source: 'Source B', query_relation: 'exact_or_folded_match',
    forms: [{ form: 'fixture form B', source_refs: [{ source: 'Source B', source_url: 'https://example.org/b' }], source_ref_total: 1 }], total_forms: 1, truncated: false });
  const host = inventory({ observed_form_groups: [group(), second] });
  const groups = host.children[0].children.filter(child => child.tag === 'details');
  assert.equal(groups.length, 2);
  assert.ok(groups[0].textContent.includes('fixture form A'));
  assert.ok(!groups[0].textContent.includes('fixture form B'));
  assert.ok(groups[1].textContent.includes('fixture form B'));
  assert.match(groups[1].textContent, /does not resolve the selected passage’s parse/);
  assert.equal(descendants(groups[0], 'a')[0].href, 'https://example.org/a');
  assert.equal(descendants(groups[1], 'a')[0].href, 'https://example.org/b');
  assert.match(groups[0].textContent, /Source analysis: raw-code \(fixture-format\)/);
});

test('inventory and provenance truncation counts remain distinct and count displayed records', () => {
  const host = inventory({ observed_form_groups: [group({ shown_forms: 99 })] });
  assert.match(host.textContent, /Inventory preview is truncated: 1 of 8 forms shown/);
  assert.match(host.textContent, /1 of 3 source references shown/);
  assert.match(host.textContent, /Source-reference preview is truncated/);
  assert.doesNotMatch(host.textContent, /99/);
  const unknown = inventory({ observed_form_groups: [group({ total_forms: undefined, truncated: false, identity_status: 'unnumbered_homograph_ambiguous', query_relation: 'unknown' })] });
  assert.match(unknown.textContent, /1 forms shown; total not supplied/);
  assert.match(unknown.textContent, /identity is ambiguous between homographs/);
  assert.match(descendants(unknown, 'summary')[0].textContent, /Relationship unknown/);
});

test('legacy ungrouped forms are never presented as a query-form paradigm', () => {
  for (const observed_form_groups of [undefined, []]) {
    const host = inventory({ observed_form_groups, attested_forms: ['LEGACY_MERGED_FORM'] });
    assert.match(host.textContent, /ungrouped form list without lemma-specific provenance/);
    assert.ok(!host.textContent.includes('LEGACY_MERGED_FORM'));
    assert.equal(descendants(host, 'details').length, 0);
  }
  assert.equal(inventory({ observed_form_groups: [], attested_forms: [] }).children.length, 0);
});

test('numbered homograph groups remain distinct before expansion and query ambiguity is explicit', () => {
  const first = group({ query_lemma_ambiguous: true });
  const second = group({ lemma_raw: 'fixture lemma A2', query_lemma_ambiguous: true });
  const host = inventory({ observed_form_groups: [first, second] });
  const groups = host.children[0].children.filter(child => child.tag === 'details');
  const summaries = groups.map(details => details.children[0].textContent);
  assert.notEqual(summaries[0], summaries[1]);
  assert.match(summaries[0], /\[fixture lemma A1\]/);
  assert.match(summaries[1], /\[fixture lemma A2\]/);
  for (const details of groups) assert.match(details.textContent, /multiple lemma identities; choosing an inventory does not resolve the parse/);
});
