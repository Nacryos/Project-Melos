import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../js/authors-page.js', import.meta.url), 'utf8');
const context = vm.createContext({ URL, URLSearchParams });
vm.runInContext(source, context);
const api = context.MelosAuthors;
const dated = (author, kind, bounds) => ({ author, author_chronology: { selected_claim: { kind, effective_year_interval: bounds, statement_url: 'https://www.wikidata.org/wiki/Q1' } } });
test('chronology keeps claim type, interval and unknown dates distinct', () => {
  assert.equal(api.chronologyOf(dated('A', 'floruit', [-700, -601])).interval, '700–601 BCE');
  assert.equal(api.chronologyOf(dated('A', 'birth', [-630, -630])).kind, 'birth');
  assert.equal(api.chronologyOf(dated('A', 'birth', [-10, 10])).interval, '10 BCE–10 CE');
  for (const bounds of [[null, null], ['', ''], [0, 0], [-600, -700]]) assert.equal(api.chronologyOf(dated('A', 'birth', bounds)), null);
  assert.equal(api.chronologyOf({ author: 'Undated' }), null);
});
test('chronology order extends to actual API authors, undated names last', () => {
  const authors = [{ author: 'Z' }, dated('Later', 'birth', [100, 100]), dated('Earlier', 'floruit', [-700, -601]), { author: 'A' }];
  assert.equal(api.sortedAuthors(authors).map(a => a.author).join(','), 'Earlier,Later,A,Z');
  assert.equal(authors[0].author, 'Z');
});
test('author filtering supports source aliases and accent-insensitive Greek', () => {
  const authors = [{ author: 'Sappho', labels: ['Sappho of Lesbos'] }];
  const catalog = new Map([['sappho', { greek: 'Σαπφώ' }]]);
  assert.equal(api.filterAuthors(authors, 'σαπφω', catalog).length, 1);
  assert.equal(api.filterAuthors(authors, 'LESBOS', catalog).length, 1);
  assert.equal(api.filterAuthors(authors, 'unknown', catalog).length, 0);
});
test('unsafe attribution URLs are not activated', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,hi', '/fake-source', 'http://example.org']) assert.equal(api.safeExternal(url), '');
  assert.equal(api.safeExternal('https://example.org/source'), 'https://example.org/source');
});
test('reader navigation uses a real passage ID and encodes it safely', () => {
  const url = new URL(api.passageUrl('a&work=b#c'), 'https://melos.test');
  assert.equal(url.searchParams.get('id'), 'a&work=b#c');
  assert.equal(url.searchParams.has('work'), false);
  assert.equal(url.hash, '#passage');
});
test('source text is rendered as text and API/catalog failures remain independent', () => {
  assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML/);
  assert.match(source, /Promise\.allSettled/);
  assert.match(source, /record\?\.biography\?\.text && safeExternal/);
  assert.match(source, /work_id: work\.id, limit: 1/);
});

function browserHarness({ catalogFails = false, authorsFail = false, portrait = null } = {}) {
  class Element {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.attributes = {}; this.dataset = {}; this.style = {}; this.className = ''; this.textContent = ''; this.value = ''; this.hidden = false; this.parent = null; this.classList = { add: name => { this.className += ` ${name}`; } }; }
    append(...nodes) { for (const n of nodes) { n.parent = this; this.children.push(n); } }
    replaceChildren(...nodes) { for (const n of this.children) n.parent = null; this.children = []; this.append(...nodes); }
    replaceWith(node) { const parent = this.parent; parent.children[parent.children.indexOf(this)] = node; node.parent = parent; this.parent = null; }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    matches(selector) { return selector.startsWith('.') && this.className.split(' ').includes(selector.slice(1)); }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    get isConnected() { return this.root || Boolean(this.parent?.isConnected); }
    focus() { this.focused = true; }
  }
  const ids = new Map(['author-query', 'author-search', 'author-timeline', 'author-count', 'page-status', 'retry-authors', 'show-more-authors'].map(id => { const e = new Element(); e.root = true; return [id, e]; }));
  const document = {
    querySelector: selector => {
      const [id, nested] = selector.slice(1).split(' '), element = ids.get(id);
      return nested ? element.querySelectorAll(nested)[0] : element;
    },
    createElement: tag => new Element(tag), createElementNS: (namespaceURI, tag) => Object.assign(new Element(tag), { namespaceURI }),
    createTextNode: text => Object.assign(new Element('text'), { textContent: text }),
  };
  const calls = [], navigations = [], replacements = [];
  const browser = { document, URL, URLSearchParams, AbortSignal, console,
    location: { href: 'https://melos.test/authors', search: '', assign: url => navigations.push(url) },
    history: { replaceState: (_state, _unused, url) => replacements.push(String(url)) },
    fetch: async input => {
      const url = new URL(input, 'https://melos.test'); calls.push(url);
      if (url.pathname.endsWith('catalog.json')) return { ok: !catalogFails, json: async () => ({ authors: [{ author: 'Sappho', portrait, biography: { text: '<img src=x onerror=alert(1)> sourced text', source_url: 'https://example.org/sappho', source_title: 'Biography' } }] }) };
      if (url.pathname === '/api/authors') return { ok: !authorsFail, json: async () => ({ authors: [dated('Sappho', 'birth', [-630, -630])] }) };
      if (url.pathname === '/api/works') return { ok: true, json: async () => ({ works: [{ id: 'w:one', work: 'Fragments', language: 'grc' }] }) };
      if (url.pathname === '/api/passages') return { ok: true, json: async () => ({ results: [{ id: 'p:one&two' }] }) };
      throw new Error(`Unexpected request ${url}`);
    },
  };
  browser.window = { addEventListener() {}, melosApiUrl: path => new URL(path, 'https://melos.test') };
  vm.runInNewContext(source, browser);
  return { ids, calls, navigations, replacements };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
test('expanded source biography, cached works and actual passage navigation function together', async () => {
  const { ids, calls, navigations, replacements } = browserHarness();
  await settle();
  const list = ids.get('author-timeline'), button = list.querySelectorAll('.author-open')[0];
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  button.listeners.click(); await settle();
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(list.querySelectorAll('.biography')[0].textContent, '<img src=x onerror=alert(1)> sourced text');
  assert.equal(list.querySelectorAll('.work-open').length, 1);
  assert.match(replacements.at(-1), /author=Sappho/);
  button.listeners.click(); button.listeners.click(); await settle();
  assert.equal(calls.filter(url => url.pathname === '/api/works').length, 1);
  ids.get('author-query').value = 'Sappho'; ids.get('author-query').listeners.input(); await settle();
  assert.equal(list.querySelectorAll('.work-open').length, 1, 'rerendered open profile renders cached works after attachment');
  await list.querySelectorAll('.work-open')[0].listeners.click();
  const passageRequest = calls.find(url => url.pathname === '/api/passages');
  assert.equal(passageRequest.searchParams.get('work_id'), 'w:one');
  assert.equal(new URL(navigations[0], 'https://melos.test').searchParams.get('id'), 'p:one&two');
});
test('catalog failure does not prevent the actual author/works collection from loading', async () => {
  const { ids } = browserHarness({ catalogFails: true }); await settle();
  const list = ids.get('author-timeline'); list.querySelectorAll('.author-open')[0].listeners.click(); await settle();
  assert.equal(ids.get('author-count').textContent, '1 author');
  assert.equal(list.querySelectorAll('.work-open').length, 1);
  assert.match(list.querySelectorAll('.biography-missing')[0].textContent, /not yet been added/);
});
test('search input preserves an author API failure and its retry affordance', async () => {
  const { ids } = browserHarness({ authorsFail: true }); await settle();
  ids.get('author-query').value = 'Sappho'; ids.get('author-query').listeners.input();
  assert.equal(ids.get('author-count').textContent, 'Collection unavailable');
  assert.match(ids.get('page-status').textContent, /could not be reached/);
  assert.equal(ids.get('retry-authors').hidden, false);
});
test('expanded portrait is before its biography in the document', async () => {
  const { ids } = browserHarness({ portrait: { image: '/assets/authors/sappho.jpg', title: 'Sappho' } }); await settle();
  const list = ids.get('author-timeline'); list.querySelectorAll('.author-open')[0].listeners.click(); await settle();
  const profile = list.querySelectorAll('.profile')[0];
  assert.equal(profile.children[0].className, 'profile-figure');
  assert.equal(profile.children[1].querySelectorAll('.biography').length, 1);
});
test('wide source artwork focus remains within image bounds without exaggerated zoom', () => {
  for (const x of [.217, .88]) {
    const frame = api.portraitFrame({ x, y: .4, width: .21, height: .39 }, 650, 360, 960, 525);
    assert.ok(frame.left <= 0 && frame.left + frame.width >= 650);
    assert.ok(frame.top <= 0 && frame.top + frame.height >= 360);
    assert.ok(frame.height <= 360 / .39 + 1);
  }
});
test('work labels do not infer source type from language alone', () => {
  assert.equal(api.workTypeLabel({ source: 'dclp', language: 'eng' }), 'English-language source');
  assert.equal(api.workTypeLabel({ language: 'grc' }), 'Greek-language source');
  assert.equal(api.workTypeLabel({ language: 'eng', kind: 'reference' }), 'Reference metadata');
  assert.equal(api.workTypeLabel({ language: 'grc', kinds: ['text'] }), 'Greek text');
  assert.equal(api.workTypeLabel({ language: 'en-GB', kind: 'translation' }), 'English translation');
  assert.equal(api.workTypeLabel({ language: 'ell', kind: 'translation' }), 'Modern Greek translation');
  assert.equal(api.workTypeLabel({ language: 'grc', kinds: ['reference', 'text'] }), 'Mixed source material');
});
test('expanded portrait framing cannot animate through a displaced focus position', () => {
  const css = fs.readFileSync(new URL('../css/authors-page.css', import.meta.url), 'utf8');
  assert.match(css, /\.profile-figure \.portrait-wrap img\{object-fit:contain;transition:filter \.3s\}/);
});
