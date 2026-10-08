import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic UI mechanics only, never literary/source evidence.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {} }); }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
const opened = [];
const context = vm.createContext({
  node: (tag, cls, text) => new Element(tag, cls, text),
  qualityLabel: quality => quality,
  openPassage: id => opened.push(id),
  safeLink(url, label) {
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) return null;
      const link = new Element('a', '', label); link.href = parsed.href; return link;
    } catch { return null; }
  },
  addInspectorSection(label, host) { const section = new Element('section', '', label); host.append(section); return section; },
});
vm.runInContext(script.slice(script.indexOf('  function renderOccurrencePreview('),
  script.indexOf('  function renderMirrors(')), context);
const render = vm.runInContext('renderOccurrencePreview', context);
const record = (id, changes = {}) => ({ id, author: 'Synthetic author', work: 'Synthetic work',
  citation: '189', edition: `Edition ${id}`, source: `Collection ${id}`, quality: 'source_text',
  source_url: `https://example.test/${id}`, ...changes });

test('grouped preview retains all edition labels, source IDs, links and click actions', () => {
  const members = [record('one'), record('two'), record('three', { author: 'original lowercase author', work: 'original work label' })];
  const data = { occurrences: members, occurrence_preview_groups: [{ representative_id: 'two', members }] };
  const before = structuredClone(data), host = new Element();
  render(host, data);
  assert.match(host.textContent, /Occurrence preview · 1 shown/);
  assert.match(host.textContent, /Same text · 3 source records/);
  assert.match(host.textContent, /original lowercase author/);
  assert.match(host.textContent, /original work label/);
  const nodes = descendants(host);
  assert.equal(nodes.filter(n => n.tag === 'details').length, 1);
  for (const member of members) {
    assert.ok(host.textContent.includes(member.edition));
    assert.ok(host.textContent.includes(member.id));
    assert.ok(nodes.some(n => n.tag === 'a' && n.href === member.source_url));
    nodes.find(n => n.tag === 'button' && n.text === 'Open this record →' && n.title === `Record ${member.id}`).handlers.click();
    assert.equal(opened.at(-1), member.id);
  }
  assert.deepEqual(data, before);
  assert.match(script, /renderOccurrencePreview\(occurrences, data\)/);
  assert.match(script, /notesHost\.append\(occurrences\)/);
});

test('cap applies to groups not members; legacy raw response stays separate', () => {
  const host = new Element();
  render(host, { occurrence_preview_groups: Array.from({ length: 13 }, (_, i) => ({ members: [record(`r${i}`), record(`copy${i}`)] })) });
  assert.match(host.textContent, /12 shown/);
  assert.equal(descendants(host).filter(n => n.tag === 'details').length, 12);
  assert.ok(!host.textContent.includes('Edition r12'));
  const legacy = new Element(); render(legacy, { occurrences: [record('a'), record('b')] });
  assert.match(legacy.textContent, /2 shown/);
  assert.doesNotMatch(legacy.textContent, /Same text/);
});

test('missing preview and malicious source strings remain safe literal display', () => {
  const empty = new Element(); render(empty, {});
  assert.match(empty.textContent, /No occurrence preview/);
  const host = new Element(); render(host, { occurrences: [record('unsafe', {
    edition: '<script>unsafe()</script>', source_url: 'javascript:unsafe()' })] });
  assert.ok(host.textContent.includes('<script>unsafe()</script>'));
  assert.equal(descendants(host).filter(n => ['a', 'script'].includes(n.tag)).length, 0);
});

test('source ID buttons remove the inherited side margin and wrap within narrow disclosures', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const scoped = css.match(/\.occurrence-source \.related-open\{([^}]+)\}/)?.[1];
  assert.ok(scoped);
  assert.match(scoped, /box-sizing:border-box/);
  assert.match(scoped, /max-width:100%/);
  assert.match(scoped, /margin:9px 0 0(?:;|$)/);
  assert.match(scoped, /white-space:normal/);
  assert.match(scoped, /overflow-wrap:anywhere/);
  assert.match(css, /\.occurrence-sources\{[^}]*min-width:0;max-width:100%;overflow-wrap:anywhere/);
});

test('source records show the readable collection name: source_label, else the /api/status label, else the id', () => {
  context.melosSourceLabels = new Map([['collection_id_b', 'Readable Collection B']]);
  try {
    const members = [record('one', { source: 'collection_id_a', source_label: 'Readable Collection A' }),
      record('two', { source: 'collection_id_b' }), record('three', { source: 'collection_id_c' })];
    const host = new Element();
    render(host, { occurrences: members, occurrence_preview_groups: [{ representative_id: 'one', members }] });
    const text = host.textContent;
    assert.match(text, /Readable Collection A/); assert.doesNotMatch(text, /collection_id_a/);
    assert.match(text, /Readable Collection B/); assert.doesNotMatch(text, /collection_id_b/);
    assert.match(text, /collection_id_c/);
  } finally { delete context.melosSourceLabels; }
});

test('provenance, mirror copies and search results read source_label too', () => {
  for (const pattern of [/'Collection', \(passage\.source_label \|\| globalThis\.melosSourceLabels\?\.get\(passage\.source\)/,
    /\[\(copy\.source_label \|\| globalThis\.melosSourceLabels\?\.get\(copy\.source\)/,
    /`Collection: \$\{\(record\.source_label \|\| globalThis\.melosSourceLabels\?\.get\(record\.source\)/,
    /globalThis\.melosSourceLabels = new Map\(/]) assert.match(script, pattern);
});
