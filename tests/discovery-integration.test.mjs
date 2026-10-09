import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read = file => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
test('homepage discovery links preserve hero and reader, with themes in a new tab', () => {
  const html = read('reader.html');
  assert.ok(html.indexOf('id="top"') < html.indexOf('class="discovery-nav"'));
  assert.ok(html.indexOf('class="discovery-nav"') < html.indexOf('id="reader"'));
  for (const route of ['lexicon','authors','themes']) assert.match(html, new RegExp(`class="discovery-door" href="/${route}"`));
  assert.match(html, /href="\/themes" target="_blank" rel="noopener"/);
  assert.match(html, /id="passage-text"/);
});
test('all focused routes have build assets and exact Vercel rewrites', () => {
  const build = read('scripts/build_frontend.mjs');
  const config = JSON.parse(read('vercel.json'));
  // /lexicon serves the headword page (lemma.html) since the lemma UI release.
  const page = { lexicon: 'lemma' };
  for (const route of ['lexicon','authors','themes']) {
    assert.ok(config.rewrites.some(r => r.source === `/${route}` && r.destination === `/${page[route] || route}.html`));
    assert.ok(build.includes(`${route}-page.js`));
    assert.ok(build.includes(`${route}-page.css`));
  }
  assert.match(build, /process\.env\.VERCEL === '1'/);
  assert.match(build, /assets\/authors/);
});
