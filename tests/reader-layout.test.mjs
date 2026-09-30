import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('collection note scrolls with the authors instead of reserving a bottom shelf', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  assert.match(html, /id="browse-body"[^]*?id="author-list"[^]*?<\/div><div class="browse-foot"[^]*?<\/div><\/div><\/aside>/);
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /height:calc\(100dvh - 24px - env\(safe-area-inset-bottom,0px\)\)/);
  assert.match(css, /\.corpus-panel \.browse-body\{flex:1;min-height:0;max-height:none\}/);
});

test('reader links have themed visited states and use local SVG line icons', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const icons = readFileSync(new URL('../js/ui-icons.js', import.meta.url), 'utf8');
  assert.match(html, /src="js\/ui-icons.js"/);
  assert.match(css, /\.reader-layout a:visited[^}]*color:var\(--ink\)/);
  assert.match(icons, /createElementNS\('http:\/\/www.w3.org\/2000\/svg', 'svg'\)/);
  assert.doesNotMatch(html, /[\u{1F300}-\u{1FAFF}]/u);
});

test('portrait iPad widths retain the same viewport-height collection sidebar as landscape', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const shared = css.slice(css.indexOf('@media(min-width:701px){'), css.indexOf('.claim-card{'));
  assert.match(shared, /\.corpus-panel\{position:sticky;top:12px;/);
  assert.match(shared, /height:calc\(100dvh - 24px - env\(safe-area-inset-bottom,0px\)\)/);
  assert.match(shared, /padding-bottom:8px;min-height:0/);
  const portrait = css.slice(css.indexOf('@media(min-width:701px) and (max-width:780px){'));
  assert.match(portrait, /\.reader-layout\{display:grid;grid-template-columns:190px minmax\(0,1fr\)/);
  assert.match(portrait, /\.corpus-panel \.mobile-toggle\{display:none\}/);
  assert.match(portrait, /\.corpus-panel \.browse-body\{display:block;max-height:none;padding-bottom:0\}/);
  assert.doesNotMatch(css, /max-height:max\(360px,calc\(100svh - 210px\)\)/);
});
