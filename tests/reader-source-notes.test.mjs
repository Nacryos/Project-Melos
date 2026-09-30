import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic metadata tests; descriptions are fixtures, not philological claims.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const context = vm.createContext({
  URL, node: (tag, cls, text) => new Element(tag, cls, text),
  addMeta(host, label, value) { const row = new Element('div', 'provenance-item', label); row.append(value instanceof Element ? value : new Element('span', '', value)); host.append(row); },
  safeLink(url, label) { if (!url || !/^https?:\/\//.test(url)) return null; const a = new Element('a', '', label); a.href = url; return a; },
});
vm.runInContext(script.slice(script.indexOf('  function renderSourcePageNotes('), script.indexOf('  function renderProvenance(')), context);
const render = vm.runInContext('renderSourcePageNotes', context);
function display(metadata, source_url = 'https://example.org/fragments/44/') {
  const host = new Element('div'); render(host, { citation: 'Fragment 44', source_url, metadata }); return host;
}
function descendants(root, tag) { return root.children.flatMap(child => [...(child.tag === tag ? [child] : []), ...descendants(child, tag)]); }

test('plain source notes use source-relative links and never interpret archived HTML', () => {
  const host = display({ source_footnote_links: [
    { marker: '1', href: '#note-1', description: 'Literal extracted note.', title_html: '<img src=x onerror=alert(1)>', line_index: 17 },
    { marker: '*', href: '../shared/#note-a', description: 'Another extracted note.', scope: 'heading' },
  ] });
  const links = descendants(host, 'a');
  assert.equal(links[0].href, 'https://example.org/fragments/44/#note-1');
  assert.equal(links[1].href, 'https://example.org/fragments/shared/#note-a');
  assert.equal(links[0].textContent, 'Source note 1 ↗');
  assert.match(host.textContent, /Literal extracted note/);
  assert.match(host.textContent, /Linked from the source heading/);
  assert.ok(!host.textContent.includes('onerror'));
  assert.ok(!host.textContent.includes('17'));
  assert.equal(descendants(host, 'details').length, 1);
});

test('missing descriptions are explicit and unsafe or unresolvable links are not substituted', () => {
  const host = display({ source_footnote_links: [{ marker: 'a', href: 'javascript:alert(1)', title_html: '<p>DO_NOT_RENDER</p>' }] });
  assert.match(host.textContent, /Plain-text source note was not supplied/);
  assert.match(host.textContent, /Source marker: a · Source note link unavailable/);
  assert.ok(!host.textContent.includes('DO_NOT_RENDER'));
  assert.equal(descendants(host, 'a').length, 0);
  // A truly absent source must not resolve the fragment to a Melos page.
  const absent = new Element('div');
  render(absent, { metadata: { source_footnote_links: [{ href: '#note-1', description: 'Preserved note.' }] } });
  assert.equal(descendants(absent, 'a').length, 0);
  assert.match(absent.textContent, /Preserved note/);
});

test('distinct headings, columns and subtitles render without repeating equivalent metadata', () => {
  const host = display({ source_heading: ' Fragment 44 ', source_section: 'Column A', source_subtitle: 'Literal subtitle', source_page_title: 'Literal subtitle' });
  assert.equal(host.children.length, 2);
  assert.match(host.textContent, /Source column \/ sectionColumn A/);
  assert.match(host.textContent, /Source subtitleLiteral subtitle/);
  assert.ok(!host.textContent.includes('Source heading'));
  assert.ok(!host.textContent.includes('Source page title'));
  assert.equal(descendants(host, 'details').length, 0);
  assert.match(script, /renderSourcePageNotes\(ui\.provenance, passage\)/);
});
