import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/themes-page.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../themes.html', import.meta.url), 'utf8');
class Node {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.attributes = {}; this.hidden = false; this.value = ''; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  get firstChild() { return this.children[0]; }
  get childNodes() { return this.children; }
  get options() { return this.children.flatMap(n => n.tagName === 'option' ? [n] : n.options); }
  focus() { this.focused = true; }
  scrollIntoView() {}
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(search = '') {
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Node()]));
  const requests = [], urls = [], listeners = {};
  const location = { search };
  const window = { MelosNaturePresetData: { presets: { sea_coast: { title: 'Sea & Coast', smallUrl: '/sea-small.webp', url: '/sea.webp' } } },
    addEventListener: (event, listener) => { listeners[event] = listener; },
    melosApiFetch: (path, options) => {
      if (path === '/api/authors') return Promise.resolve({ ok: true, json: async () => ({ authors: [{ author: 'Sappho' }] }) });
      if (path === '/api/discovery-catalog') return Promise.resolve({ ok: true, json: async () => ({ themes: [] }) });
      return new Promise((resolve, reject) => requests.push({ path, options, resolve: data => resolve({ ok: true, json: async () => data }), reject }));
    }
  };
  vm.runInNewContext(source, { window, location, URL, URLSearchParams, AbortController,
    history: { pushState: (_, __, url) => { urls.push(url); location.search = new URL(url, 'https://melos.test').search; } },
    document: { getElementById: id => nodes[id], createElement: tag => new Node(tag) } });
  const click = id => nodes[id].listeners.click({ preventDefault() {} });
  const submit = () => nodes['theme-search'].listeners.submit({ preventDefault() {} });
  return { nodes, requests, urls, listeners, location, api: window.MelosThemes, click, submit };
}
const all = node => [node, ...node.children.flatMap(all)];

test('URL state validates units and pagination and round-trips literal input', () => {
  const { api } = harness();
  const state = api.parseState('?q=%3Cscript%3E%26%20sea&author=Sappho&unit=word&offset=21');
  assert.equal(state.q, '<script>& sea');
  assert.equal(state.offset, 20);
  assert.equal(api.parseState('?unit=poem&offset=-20').unit, 'passage');
  assert.equal(api.parseState('?offset=NaN').offset, 0);
  assert.equal(api.parseState('?offset=10000000000000000000').offset, 0);
  assert.equal(api.parseState(api.stateParams(state)).q, state.q);
  assert.equal(api.parseState(`?q=${'x'.repeat(201)}`).q.length, 200);
  assert.equal(api.readerLink('a&b'), '/?id=a%26b');
});
test('browsing loads lazy compressed art without starting a corpus search', async () => {
  const { nodes, requests } = harness();
  await tick();
  assert.equal(requests.length, 0);
  assert.equal(nodes['theme-results-section'].hidden, true);
  const image = nodes['nature-categories'].children[0].children[0];
  assert.equal(image.loading, 'lazy');
  assert.equal(image.src, '/sea-small.webp');
  assert.equal(nodes['idea-categories'].children.length, 8);
  assert.equal(nodes['theme-authors'].children[0].value, 'Sappho');
});
test('form sends selected author and unit, URL pagination persists and back restores', async () => {
  const app = harness();
  app.nodes['theme-query'].value = 'sea'; app.nodes['theme-author'].value = 'Sappho'; app.nodes['theme-unit'].value = 'line';
  app.submit();
  assert.match(app.requests[0].path, /q=sea/); assert.match(app.requests[0].path, /author=Sappho/); assert.match(app.requests[0].path, /unit=line/);
  app.requests[0].resolve({ results: [{ passage_id: 'p', unit: 'line', text: 'sea', start: 0, end: 3 }], has_more: true, total: 21 });
  await tick(); app.click('theme-next');
  assert.match(app.urls.at(-1), /offset=20/);
  assert.match(app.requests[1].path, /offset=20/);
  app.location.search = '?q=old&unit=phrase'; app.listeners.popstate();
  assert.equal(app.nodes['theme-query'].value, 'old');
  assert.equal(app.nodes['theme-unit'].value, 'phrase');
  assert.match(app.requests[2].path, /q=old/);
});
test('stale asynchronous responses cannot overwrite the current result or reset', async () => {
  const app = harness('?q=first');
  app.nodes['theme-query'].value = 'second'; app.submit();
  assert.equal(app.requests[0].options.signal.aborted, true);
  app.requests[1].resolve({ results: [{ passage_id: 'second', unit: 'passage', text: 'Current' }], total: 1 });
  await tick();
  app.requests[0].resolve({ results: [{ passage_id: 'first', unit: 'passage', text: 'Stale' }], total: 1 });
  await tick();
  const quotes = all(app.nodes['theme-results']).filter(n => n.tagName === 'blockquote');
  assert.deepEqual(quotes.map(n => n.textContent), ['Current']);
  app.nodes['theme-query'].value = 'third'; app.submit(); app.click('theme-reset');
  app.requests[2].resolve({ results: [{ passage_id: 'third', text: 'Late', unit: 'passage' }] });
  await tick(); assert.equal(app.nodes['theme-results-section'].hidden, true); assert.equal(app.nodes['theme-results'].children.length, 0);
});
test('exact excerpts are grouped by parent, rendered safely, and linked to source', async () => {
  const app = harness('?q=love&unit=phrase');
  app.requests[0].resolve({ results: [
    { passage_id: 'p&1', unit: 'phrase', quote: '<img onerror=alert(1)>', author: 'Sappho', work: 'Fragments', citation: 'fr. 1', source: 'Source edition', source_url: 'javascript:alert(1)', start: 0, end: 21, offset_basis: 'unicode_codepoints', match_reason: 'lexical', segmentation_method: 'punctuation' },
    { passage_id: 'p&1', unit: 'phrase', text: 'Another exact span' }
  ], total: 2, method: 'parent_semantic_child_lexical', warnings: ['Punctuation-based boundaries.'] });
  await tick();
  assert.equal(app.nodes['theme-results'].children.length, 1);
  const contents = all(app.nodes['theme-results']);
  assert.equal(contents.filter(n => n.tagName === 'blockquote')[0].textContent, '<img onerror=alert(1)>');
  assert.equal(contents.some(n => n.tagName === 'img'), false);
  assert.ok(contents.filter(n => n.tagName === 'a').every(n => n.href === '/?id=p%261'));
  assert.ok(contents.some(n => n.textContent.includes('fr. 1 · Source edition')));
  assert.equal(app.nodes['search-evidence'].hidden, false);
  assert.equal(app.api.safeExternal('https://example.org/source'), 'https://example.org/source');
  assert.equal(app.api.safeExternal('javascript:alert(1)'), null);
});
test('errors can retry and empty states do not fabricate passage matches', async () => {
  const app = harness('?theme=sea_coast&unit=stanza');
  app.requests[0].reject(new Error('Service unavailable'));
  await tick(); assert.equal(app.nodes['theme-retry'].hidden, false); assert.equal(app.nodes['theme-status'].textContent, 'Service unavailable');
  app.click('theme-retry'); app.requests[1].resolve({ results: [], total: 0, warnings: ['No typographic stanza breaks.'] });
  await tick();
  assert.match(app.nodes['theme-status'].textContent, /No matching source spans/);
  assert.equal(app.nodes['theme-results'].children.length, 0);
  assert.equal(app.nodes['theme-pagination'].hidden, true);
  assert.equal(app.nodes['theme-results'].attributes['aria-busy'], 'false');
});
test('on-demand child semantic ranking exposes actual bounds and avoids corpus-wide totals', async () => {
  const app = harness('?q=longing&unit=line');
  app.requests[0].resolve({ results: [{ passage_id: 'p', unit: 'line', quote: 'Exact source', unit_embedding_method: 'on-demand existing local parent encoder; no independent unit index' }], total: 64, has_more: true,
    method: 'semantic', search_contract: { complete: false, total_scope: 'units in bounded retrieved parent window',
      child_semantic_reranking: { available: true, encoded_units: 64, candidate_units: 300, unit_limit: 64, parent_limit: 16, source_character_limit_per_unit: 1000, sampled: true,
        sampling: 'Round-robin over first 16 parents.', method: 'On-demand local BGE-M3 exact-span cosine; rank is not calibrated confidence.' } } });
  await tick();
  const evidence = all(app.nodes['search-evidence-body']).map(node => node.textContent).join(' ');
  assert.match(evidence, /64 source spans encoded from 300 candidate spans/);
  assert.match(evidence, /first 16 retrieved parents/);
  assert.match(evidence, /no separately stored child index/);
  assert.match(app.nodes['theme-status'].textContent, /bounded candidate selection/);
  assert.match(all(app.nodes['theme-results']).map(node => node.textContent).join(' '), /not calibrated confidence/);
});
