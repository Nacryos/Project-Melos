import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = path => readFile(new URL(`../${path}`, import.meta.url), 'utf8');
const [script, html, css, original, build] = await Promise.all([
  read('local-preview/timeline.js'), read('local-preview/index.html'),
  read('local-preview/timeline.css'), read('js/app.js'), read('scripts/build_frontend.mjs'),
]);
const poets = source => JSON.parse(JSON.stringify(vm.runInNewContext(`(${source.match(/const POETS = (\[[\s\S]*?\n\]);/)[1]})`)));

test('local timeline preserves existing poet names and dates without inventing floruit', () => {
  assert.deepEqual(poets(script), poets(original));
  assert.match(html, /Dates, BCE/);
  assert.match(html, /some are lifespans/);
});

test('preview stays outside production frontend allowlist', () => {
  assert.doesNotMatch(build, /copy\(['"]local-preview|['"]local-preview\/index\.html/);
  assert.match(html, /noindex, nofollow/);
});

test('original painting hero precedes the vertical timeline and reuses its existing module', () => {
  assert.ok(html.indexOf('id="painting-hero"') < html.indexOf('id="poet-timeline"'));
  assert.match(script, /fetch\('\/reader\.html'\)/);
  assert.match(script, /import\('\/js\/reader-hero\.js/);
  assert.match(script, /replaceWith\(compactSearch\)/);
  assert.match(script, /new URL\('\/local-preview\/', location\.origin\)/);
  assert.match(css, /\.has-painting-hero>main\{max-width:none;margin:0;padding:0\}/);
});

test('reader links preserve query filters and target passage for poet entries', () => {
  const fn = script.slice(script.indexOf('function readerUrl('), script.indexOf('function openReader('));
  const context = vm.createContext({ URL, document: { baseURI: 'http://127.0.0.1:8792/local-preview/' } });
  vm.runInContext(fn, context);
  const url = vm.runInContext("readerUrl({ id: 'p:1', author: 'Ibycus' })", context);
  assert.equal(url.pathname, '/reader.html');
  assert.equal(url.searchParams.get('author'), 'Ibycus');
  assert.equal(url.hash, '#passage');
  const search = vm.runInContext("readerUrl({ q: 'κηλήμασι παντοδαποῖς', mode: 'forms', order: 'chronological' })", context);
  assert.equal(search.searchParams.get('q'), 'κηλήμασι παντοδαποῖς');
  assert.equal(search.searchParams.get('mode'), 'forms');
  assert.equal(search.searchParams.get('order'), 'chronological');
});

test('portrait credits and ambiguity labels remain visible and source-linked', () => {
  assert.match(script, /portrait\.description/);
  assert.match(script, /portrait\.license_url/);
  assert.match(script, /Attributed portrait/);
  assert.match(script, /Manuscript/);
  assert.match(css, /\.art-type\{position:absolute;bottom:0/);
});

test('preview uses existing reader rather than a second parsing implementation', () => {
  assert.match(html, /id="reader-frame"/);
  assert.match(script, /work_id: work\.id/);
  assert.doesNotMatch(script, /\/api\/passage-analysis|\/api\/word|\/api\/classify/);
});

test('narrow zoomed screens stack dates instead of forcing three columns', () => {
  assert.match(css, /@media\(max-width:430px\)\{\.poet-row\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css, /@media\(max-width:340px\)/);
  assert.match(css, /\.poet-name\{min-width:0\}/);
});
