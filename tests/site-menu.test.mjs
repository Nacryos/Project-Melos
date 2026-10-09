import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// The hamburger site menu replaces the top navigation on every page (js/site-menu.js, css/site-menu.css).
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const menu = read('js/site-menu.js'), css = read('css/site-menu.css');
const PAGES = ['reader.html', 'index.html', 'lemma.html', 'concept.html', 'about.html'];

test('every page has the menu button, its assets, a home brand link and no old top navigation', () => {
  for (const page of PAGES) {
    const html = read(page);
    assert.match(html, /<button class="site-menu-button" id="site-menu-button" type="button" aria-label="Menu" aria-expanded="false" aria-controls="site-menu">/, page);
    assert.match(html, /<script src="js\/site-menu\.js\?v=site-menu-\d{8}" defer><\/script>/, page);
    assert.match(html, /<link rel="stylesheet" href="css\/site-menu\.css\?v=site-menu-\d{8}">/, page);
    assert.match(html, /<a class="(?:mark|site-mark)" href="(?:\/|\.\/)" aria-label="Melos, home">/, page);
    assert.doesNotMatch(html, /<nav aria-label="Main navigation">|class="nav-tool"/, page);
  }
  // The design studio folds its in-page links into the panel instead of a visible top nav.
  assert.match(read('index.html'), /<nav aria-label="On this page" data-site-menu-local hidden>/);
});

test('panel lists the sections in order and ends with Log in', () => {
  const order = ["section('Create design decks'", "section('Visuals'", "section('About'", "section('Features'", "'site-menu-foot' }, login"];
  const at = order.map(needle => menu.indexOf(needle));
  assert.ok(at.every(index => index > 0), 'every section present');
  assert.deepEqual([...at].sort((a, b) => a - b), at, 'sections in the requested order');
  assert.match(menu, /item\('Design studio', '\/legacy'/);
  assert.match(menu, /item\('What Melos does', '\/about'/);
  for (const feature of ["['Reader', '/'", "['Poets & works', '/#collection'", "['Lexicon', '/lexicon'", "['Concepts', '/concepts'", "['Search', '/#search'", "['Scansion', null, 'Coming soon']", "['Composer', null, 'Coming soon']"]) {
    assert.ok(menu.includes(feature), feature);
  }
  // Modules not yet released are shown but cannot be followed.
  assert.match(menu, /className: 'site-menu-item is-soon', ariaDisabled: 'true'/);
});

test('keyboard: Escape closes, Tab is trapped, focus returns to the button, aria-expanded follows', () => {
  assert.match(menu, /event\.key === 'Escape'\) \{ event\.preventDefault\(\); hide\(\); return; \}/);
  assert.match(menu, /event\.shiftKey && document\.activeElement === first\) \{ event\.preventDefault\(\); last\.focus\(\); \}/);
  assert.match(menu, /!event\.shiftKey && document\.activeElement === last\) \{ event\.preventDefault\(\); first\.focus\(\); \}/);
  assert.match(menu, /if \(returnFocus\) button\.focus\(\{ preventScroll: true \}\)/);
  assert.match(menu, /button\.setAttribute\('aria-expanded', 'true'\)/);
  assert.match(menu, /button\.setAttribute\('aria-expanded', 'false'\)/);
  assert.match(menu, /role: 'dialog', ariaModal: 'true'/);
  assert.doesNotMatch(menu, /innerHTML|insertAdjacentHTML|document\.write|eval\(/);
});

test('Log in has one switch and explains instead of a 404 until /owner exists', () => {
  assert.match(menu, /const OWNER_LOGIN_LIVE = false;/);
  assert.match(menu, /fetch\('\/owner', \{ method: 'HEAD', cache: 'no-store' \}\)/);
  assert.match(menu, /response\.ok && /);
  assert.match(menu, /'Owner login is not available yet\.'/);
  assert.match(menu, /role: 'status'/);
});

test('visual controls move into the panel: no floating dither button or painting strip', () => {
  assert.match(css, /\.tune-toggle, \.plate \.thumbs \{ display: none !important; \}/);
  assert.match(menu, /'Adjust dither'/);
  assert.match(menu, /'Background painting'/);
  assert.match(menu, /aria-pressed/);
  // Closing the dither controls returns focus to the menu button, which is always visible.
  for (const file of ['js/reader-hero.js', 'js/app.js']) {
    assert.match(read(file), /\(\$\('#site-menu-button'\) \|\| \$\('#tune-toggle'\)\)\.focus\(/, file);
  }
});

test('the panel is a fixed overlay (no layout jump) that fills a phone screen and shows focus', () => {
  assert.match(css, /\.site-menu \{ position: fixed; inset: 0; z-index: 1000;/);
  assert.match(css, /width: min\(380px, 100%\)/);
  assert.match(css, /\.site-menu-button:focus-visible, \.site-menu :focus-visible \{ outline: 2px solid #fff;/);
  assert.match(css, /\.site-menu \.site-menu-item:hover \{/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /width: 44px; height: 44px;/);
});

test('about page ships in the reader-only build with an /about route', () => {
  const build = read('scripts/build_frontend.mjs');
  assert.match(build, /const toolPages = \['lemma\.html', 'concept\.html', 'about\.html'\];/);
  assert.match(build, /'site-menu\.js'/);
  assert.match(build, /'site-menu\.css'/);
  const vercel = JSON.parse(read('vercel.json'));
  assert.ok(vercel.rewrites.some(rule => rule.source === '/about' && rule.destination === '/about.html'));
  const about = read('about.html');
  for (const heading of ['Reading', 'Dictionaries', 'Lexicon', 'Concepts through time', 'Search', 'Citations', 'Sources and licences', 'The parser and how accuracy is measured']) {
    assert.ok(about.includes(`>${heading}</h2>`), heading);
  }
});
